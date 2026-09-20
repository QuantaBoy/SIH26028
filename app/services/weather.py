import logging
import os

import httpx
from fastapi import HTTPException

# httpx logs full request URLs at INFO, which would leak the OpenWeather `appid` key.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Primary: Open-Meteo (free, no key). Cross-check: OpenWeather (needs OPENWEATHER_API_KEY).
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
TEMP_TOLERANCE_C = 2.0  # sources "agree" when temperatures are within this


async def _open_meteo(client: httpx.AsyncClient, lat: float, lon: float) -> dict:
    r = await client.get(OPEN_METEO_URL, params={
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
    })
    cur = r.raise_for_status().json()["current"]
    return {  # °C, %, km/h
        "time": cur["time"],
        "temperature": cur["temperature_2m"],
        "humidity": cur["relative_humidity_2m"],
        "wind": cur["wind_speed_10m"],
    }


async def _openweather(client: httpx.AsyncClient, lat: float, lon: float, key: str) -> dict:
    r = await client.get(OPENWEATHER_URL, params={"lat": lat, "lon": lon, "units": "metric", "appid": key})
    w = r.raise_for_status().json()
    return {  # °C, %, km/h (OpenWeather gives m/s)
        "temperature": w["main"]["temp"],
        "humidity": w["main"]["humidity"],
        "wind": round(w["wind"]["speed"] * 3.6, 1),
    }


async def get_weather(city: str) -> dict:
    """City name -> current weather from both sources.

    Raises HTTPException 404 (unknown city) / 502 (Open-Meteo down).
    OpenWeather is best-effort: if the key is missing or the call fails, its data is None
    and `openweather_error` says why.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            geo = (await client.get(GEO_URL, params={"name": city, "count": 1})).raise_for_status().json()
            if not geo.get("results"):
                raise HTTPException(404, f"City not found: {city}")
            place = geo["results"][0]
            lat, lon = place["latitude"], place["longitude"]
            primary = await _open_meteo(client, lat, lon)
        except httpx.HTTPError:
            raise HTTPException(502, "Weather service unavailable") from None

        second = error = None
        key = os.environ.get("OPENWEATHER_API_KEY")
        if not key:
            error = "OPENWEATHER_API_KEY not set"
        else:
            try:
                second = await _openweather(client, lat, lon, key)
            except (httpx.HTTPError, KeyError):
                error = "OpenWeather unavailable (check API key)"

    diff = round(abs(primary["temperature"] - second["temperature"]), 1) if second else None
    return {
        "city": place["name"],
        "country": place.get("country"),
        "open_meteo": primary,
        "openweather": second,
        "openweather_error": error,
        "temp_diff": diff,
        "agree": None if diff is None else diff <= TEMP_TOLERANCE_C,
    }
