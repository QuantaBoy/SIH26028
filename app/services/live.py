"""Live train running status from RailRadar, and the history of real runs built from it.

RailRadar's free plan is 1,000 calls a month and 10 a minute, so every call is spent on
purpose:
  - history: once a day, each tracked train's finished run from yesterday is fetched
    once and kept in runs.db. One call gives the actual times at every halt, so a month
    of this is ~500 real runs, which is what the ETA model learns from.
  - live: a train's current status when someone tracks it, reused for CACHE_SECONDS.
RailRadar reports the month's remaining calls on every response; that number is kept,
and calls stop at a reserve so the quota never runs out mid-demo.

Only halts carry actual times (a passing station has none), so everything is per halt.

    python -m app.services.live            # collect yesterday's runs now, then a summary
"""
import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import date, datetime, timedelta

import httpx

from app.services.network import stations
from app.services.weather_db import IST, ROOT

DB_PATH = ROOT / "runs.db"
LIVE_URL = "https://api.railradar.in/v1/trains/{number}/live"
CACHE_SECONDS = 300
COLLECT_HOUR = 9  # IST; every tracked train's run of yesterday has arrived by then
CALL_GAP_SECONDS = 7  # the plan allows 10 calls a minute
KEEP_FOR_LIVE = 300  # history collection stops when the month has this few calls left
KEEP_IN_RESERVE = 20  # live tracking stops here
# Chennai - Bengaluru, both directions: short daily runs, so one day's run has always
# finished by the next morning. ponytail: multi-day trains (12296 Sanghamitra) are left
# out; collect them with date = today - their run length when the corridor grows.
TRACKED = os.environ.get("TRACKED_TRAINS", "12007,12027,12607,12639,12657,16021,22625,"
                         "12008,12028,12608,12640,12658,16022,22626").split(",")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    train       TEXT NOT NULL,
    start_date  TEXT NOT NULL,     -- the run's date at its first station
    seq         INTEGER NOT NULL,  -- RailRadar's position along the route
    station     TEXT NOT NULL,
    sched_arr   TEXT,              -- ISO times, IST; arrival is empty at the first station
    sched_dep   TEXT,              -- and departure at the last
    actual_arr  TEXT,
    actual_dep  TEXT,
    delay_arr   INTEGER,           -- minutes late; negative is early
    delay_dep   INTEGER,
    PRIMARY KEY (train, start_date, seq)
);
CREATE TABLE IF NOT EXISTS predictions (
    train       TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    station     TEXT NOT NULL,
    made_at     TEXT NOT NULL,     -- when the ETA was given
    from_station TEXT,             -- the halt the train was last reported at
    predicted   TEXT NOT NULL,     -- our ETA
    baseline    TEXT NOT NULL,     -- schedule + current delay
    railradar   TEXT               -- RailRadar's own projection, for comparison
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

log = logging.getLogger(__name__)
_cache: dict[tuple, tuple[float, dict]] = {}


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def meta(key: str, value=None):
    """Read a stored value, or store one when given."""
    con = connect()
    try:
        if value is not None:
            con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
            con.commit()
            return value
        r = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r and r["value"]
    finally:
        con.close()


def calls_left() -> int | None:
    left = meta("calls_left")
    return int(left) if left is not None else None


class QuotaSpent(Exception):
    pass


async def fetch(number: str, day: str | None = None, reserve: int = KEEP_IN_RESERVE) -> dict:
    """A run's status from RailRadar: the current run when no day is given.
    Raises QuotaSpent below the reserve, httpx errors when RailRadar fails."""
    key = os.environ.get("RAILRADAR_API_KEY")
    if not key:
        raise QuotaSpent("RAILRADAR_API_KEY not set")
    left = calls_left()
    if left is not None and left <= reserve:
        raise QuotaSpent(f"{left} RailRadar calls left this month")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(LIVE_URL.format(number=number),
                             params={"includeCoordinates": "true", "geometry": "true", "format": "coordinates",
                                     **({"date": day} if day else {})},
                             headers={"Authorization": f"Bearer {key}"})
    if (left := r.headers.get("x-ratelimit-remaining-month")) is not None:
        meta("calls_left", left)
    data = r.raise_for_status().json()["data"]
    meta(f"days:{number}", ",".join(data["train"].get("runDays") or []))
    meta(f"name:{number}", data["trainName"])
    return data


async def live(number: str, day: str | None = None) -> tuple[dict, bool]:
    """The run's status, from the cache while it is fresh. True when it was just fetched."""
    hit = _cache.get((number, day))
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1], False
    data = await fetch(number, day)
    _cache[(number, day)] = (time.time(), data)
    if data["status"] == "completed":
        store(data)  # a live look at a finished run is history too, for free
    return data, True


def is_real(stop: dict) -> bool:
    """RailRadar fills 'actual' times ahead of the train with its own projection;
    they are real only for halts the train has reached."""
    return stop["status"] in ("departed", "at-station")


def store(data: dict) -> int:
    """Keep a finished run's halts. Returns the number of halts stored."""
    rows = [(data["trainNumber"], data["startDate"], s["sequence"], s["stationCode"],
             s.get("scheduledArrival"), s.get("scheduledDeparture"),
             s.get("actualArrival"), s.get("actualDeparture"),
             s.get("delayArrival"), s.get("delayDeparture"))
            for s in data["route"] if s["isHalt"] and is_real(s)]
    con = connect()
    try:
        con.executemany("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.commit()
    finally:
        con.close()
    return len(rows)


def tracked() -> list[dict]:
    """The tracked trains, with the name and running days learnt from their last fetch."""
    return [{"number": n, "name": meta(f"name:{n}"), "days": [d for d in (meta(f"days:{n}") or "").split(",") if d]}
            for n in TRACKED]


def runs_of(number: str) -> list[list[sqlite3.Row]]:
    """Every stored run of a train, each its halts in order."""
    con = connect()
    try:
        rows = con.execute("SELECT * FROM runs WHERE train = ? ORDER BY start_date, seq",
                           (number,)).fetchall()
    finally:
        con.close()
    runs = {}
    for r in rows:
        runs.setdefault(r["start_date"], []).append(r)
    return list(runs.values())


def scheduled_runs(now: datetime | None = None, days_ahead: int = 2) -> list[dict]:
    """Tracked trains' runs from yesterday to `days_ahead` days out, each halt with its time
    for that run: the timetable of the train's latest stored run, moved to the run's date.
    A run carries its live delay when someone tracked it in the last half hour. No API call
    is made, so a map can place and move every tracked train as often as it likes."""
    now = now or datetime.now(IST)
    out = []
    for t in tracked():
        runs = runs_of(t["number"])
        if not runs:
            continue
        latest = runs[-1]
        base = date.fromisoformat(latest[0]["start_date"])
        for offset in range(-1, days_ahead + 1):
            start = now.date() + timedelta(days=offset)
            if t["days"] and start.strftime("%a").lower() not in t["days"]:
                continue
            shift = timedelta(days=(start - base).days)
            halts = []
            for r in latest:
                s = stations().get(r["station"])
                if s:
                    arr, dep = r["sched_arr"] or r["sched_dep"], r["sched_dep"] or r["sched_arr"]
                    halts.append({"code": s["code"], "name": s["name"], "lat": s["lat"], "lon": s["lon"],
                                  "arr": (datetime.fromisoformat(arr) + shift).isoformat(),
                                  "dep": (datetime.fromisoformat(dep) + shift).isoformat()})
            hit = _cache.get((t["number"], None))
            live = bool(hit and time.time() - hit[0] < 1800 and hit[1]["startDate"] == start.isoformat())
            if len(halts) > 1:
                out.append({"number": t["number"], "name": t["name"], "start_date": start.isoformat(),
                            "halts": halts, "live": live,
                            "delay": (hit[1].get("delayMinutes") or 0) if live else 0})
    return out


async def collect(day: date | None = None) -> dict:
    """Fetch and keep each tracked train's run on a day (yesterday by default)."""
    day = day or datetime.now(IST).date() - timedelta(days=1)
    weekday = day.strftime("%a").lower()
    con = connect()
    try:  # a restart mid-collection doesn't pay twice for the trains already in
        have = {r[0] for r in con.execute("SELECT DISTINCT train FROM runs WHERE start_date = ?",
                                          (day.isoformat(),))}
    finally:
        con.close()
    done, skipped, failed = [], [], []
    for i, number in enumerate(TRACKED):
        days = meta(f"days:{number}")
        if number in have or (days and weekday not in days.split(",")):
            skipped.append(number)  # stored already, or doesn't run that day: no call spent
            continue
        if i:
            await asyncio.sleep(CALL_GAP_SECONDS)
        try:
            data = await fetch(number, day.isoformat(), reserve=KEEP_FOR_LIVE)
        except QuotaSpent as e:
            log.warning("history collection stopped: %s", e)
            break
        except (httpx.HTTPError, KeyError, ValueError) as e:
            failed.append(f"{number}: {e}")
            continue
        if data["status"] == "completed":
            store(data)
            done.append(number)
        else:
            failed.append(f"{number}: {data['status']}")
    meta("collected_on", day.isoformat())
    return {"day": day.isoformat(), "stored": done, "skipped": skipped, "failed": failed,
            "calls_left": calls_left()}


async def collect_forever() -> None:
    """Collect yesterday's runs once a day, from COLLECT_HOUR IST. A restart doesn't
    collect twice: the last collected day is remembered."""
    while True:
        now = datetime.now(IST)
        yesterday = (now.date() - timedelta(days=1)).isoformat()
        if now.hour >= COLLECT_HOUR and meta("collected_on") != yesterday:
            try:
                log.info("runs collected: %s", await collect())
            except Exception:  # a dead collector silently ends the history
                log.exception("run collection failed")
        await asyncio.sleep(1800)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    print(json.dumps(asyncio.run(collect()), indent=1))
    print(sum(len(r) for n in TRACKED for r in runs_of(n)), "halts stored in", DB_PATH.name)
