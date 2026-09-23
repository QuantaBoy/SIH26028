"""Weather at every railway station, kept in its own database.

Station weather is read on every map hover and, later, for every ETA prediction, so it is
never fetched from the internet while a request waits: a poller fills weather.db and the
API only reads that file.

What is stored is an *hourly forecast*, not a single current reading. That covers both
uses from one fetch: the current hour answers "what is it doing there now", and the later
hours answer "what will it be doing when the train gets there" - which is the question an
ETA model has to ask.

Two limits shape the design. Open-Meteo's free tier counts every coordinate as a call
(600 a minute, 10,000 a day), and weather barely changes between stations a few km apart.
So stations are grouped into grid cells about 55 km across: 8,697 stations become 843
fetches, each covering the next two days, refreshed every few hours. That is ~3,400 calls
a day, inside the free tier, and every station still has its own hourly forecast.

    python -m app.services.weather_db          # one refresh pass, then a summary
"""
import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.services.db import connect as railway_db

ROOT = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "weather.db"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CELL_DEGREES = 0.5  # ~55 km
BATCH = 100  # coordinates per call
BATCH_PAUSE_SECONDS = 11  # 600 coordinates a minute is the free tier's limit
FORECAST_DAYS = 2
REFRESH_HOURS = float(os.environ.get("WEATHER_REFRESH_HOURS", 6))
HOURLY = "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code"
IST = timezone(timedelta(hours=5, minutes=30))  # Indian Railways runs on IST

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    cell          TEXT NOT NULL,
    hour          TEXT NOT NULL,      -- 'YYYY-MM-DDTHH:00', India Standard Time
    fetched_at    INTEGER NOT NULL,   -- unix seconds
    temperature   REAL,
    humidity      REAL,
    wind          REAL,
    precipitation REAL,
    weather_code  INTEGER,
    PRIMARY KEY (cell, hour)          -- a later fetch corrects an hour's forecast
);
CREATE INDEX IF NOT EXISTS forecasts_by_hour ON forecasts(hour);
"""

# Open-Meteo weather codes, in the words a passenger would use.
CONDITIONS = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def cell_of(lat: float, lon: float) -> str:
    """The grid cell a point falls in, named for the cell's centre."""
    return f"{round(lat / CELL_DEGREES) * CELL_DEGREES:.2f},{round(lon / CELL_DEGREES) * CELL_DEGREES:.2f}"


def hour_key(when: datetime | None = None) -> str:
    """The hour a time falls in, in IST, as stored."""
    return (when or datetime.now(IST)).astimezone(IST).strftime("%Y-%m-%dT%H:00")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def cells() -> dict[str, tuple[float, float]]:
    """Every cell holding at least one station, with the point to ask the weather for."""
    con = railway_db()
    try:
        rows = con.execute("SELECT lat, lon FROM stations WHERE lat IS NOT NULL").fetchall()
    finally:
        con.close()
    found = {}
    for r in rows:
        found.setdefault(cell_of(r["lat"], r["lon"]), (r["lat"], r["lon"]))
    return found


async def _fetch(client: httpx.AsyncClient, points: list[tuple[str, float, float]]) -> list[tuple]:
    """One call covering up to BATCH cells; Open-Meteo returns a list when given lists."""
    r = await client.get(OPEN_METEO_URL, params={
        "latitude": ",".join(str(lat) for _, lat, _ in points),
        "longitude": ",".join(str(lon) for _, _, lon in points),
        "hourly": HOURLY, "forecast_days": FORECAST_DAYS, "timezone": "Asia/Kolkata",
    })
    places = r.raise_for_status().json()
    if isinstance(places, dict):  # a single coordinate comes back unwrapped
        places = [places]
    now = int(time.time())
    rows = []
    for (cell, _, _), place in zip(points, places):
        h = place["hourly"]
        for i, t in enumerate(h["time"]):
            rows.append((cell, t[:14] + "00", now, h["temperature_2m"][i], h["relative_humidity_2m"][i],
                         h["wind_speed_10m"][i], h["precipitation"][i], h["weather_code"][i]))
    return rows


async def refresh(limit: int | None = None) -> dict:
    """Fetch forecasts for every cell and store them. A failed batch is skipped, not raised."""
    points = [(cell, lat, lon) for cell, (lat, lon) in sorted(cells().items())][:limit]
    written, failed = 0, 0
    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(0, len(points), BATCH):
            batch = points[i:i + BATCH]
            try:
                rows = await _fetch(client, batch)
            except (httpx.HTTPError, KeyError, ValueError):
                failed += len(batch)
                rows = []
            if rows:
                con = connect()
                try:
                    con.executemany(
                        "INSERT OR REPLACE INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
                    con.commit()
                finally:
                    con.close()
                written += len(rows)
            if i + BATCH < len(points):
                await asyncio.sleep(BATCH_PAUSE_SECONDS)  # stay under the per-minute limit
    return {"cells": len(points), "rows": written, "cells_failed": failed}


async def poll_forever() -> None:
    """Refresh every REFRESH_HOURS for as long as the app runs, starting with a pass now."""
    while True:
        try:
            result = await refresh()
            logging.getLogger(__name__).info("weather refreshed: %s", result)
        except Exception:  # a poller that dies takes all weather with it
            logging.getLogger(__name__).exception("weather refresh failed")
        await asyncio.sleep(REFRESH_HOURS * 3600)


def forecast_at(lat: float, lon: float, when: datetime | None = None) -> dict | None:
    """The forecast for a point at a given hour (now by default), or None if not stored yet."""
    con = connect()
    try:
        r = con.execute("SELECT * FROM forecasts WHERE cell = ? AND hour = ?",
                        (cell_of(lat, lon), hour_key(when))).fetchone()
    finally:
        con.close()
    if not r:
        return None
    return {"hour": r["hour"], "temperature": r["temperature"], "humidity": r["humidity"],
            "wind": r["wind"], "precipitation": r["precipitation"],
            "condition": CONDITIONS.get(r["weather_code"], "unknown"),
            "fetched_at": r["fetched_at"], "age_seconds": int(time.time()) - r["fetched_at"]}


def station_weather(code: str, when: datetime | None = None) -> dict | None:
    """Weather at a station, for now or for the hour a train is due. None if unknown."""
    con = railway_db()
    try:
        s = con.execute("SELECT code, name, lat, lon FROM stations WHERE code = ?",
                        (code.upper(),)).fetchone()
    finally:
        con.close()
    if not s or s["lat"] is None:
        return None
    return {"code": s["code"], "name": s["name"], "weather": forecast_at(s["lat"], s["lon"], when)}


if __name__ == "__main__":
    # Chennai Central and Ennore, 15 km apart, share one cell and so one fetch.
    assert cell_of(13.0827, 80.2707) == cell_of(13.2180, 80.3220) == "13.00,80.50"
    print(f"{len(cells())} cells; refreshing (about {len(cells()) // BATCH * BATCH_PAUSE_SECONDS}s)...")
    print(asyncio.run(refresh()))

    mas = station_weather("MAS")
    assert mas and mas["weather"], mas
    soon = station_weather("MAS", datetime.now(IST) + timedelta(hours=6))
    assert soon and soon["weather"], soon  # the same fetch answers "now" and "when the train arrives"
    w = mas["weather"]
    print(f"MAS now: {w['temperature']}C, {w['condition']}, wind {w['wind']} km/h, "
          f"rain {w['precipitation']} mm; in 6h: {soon['weather']['temperature']}C, "
          f"{soon['weather']['condition']}")
