import asyncio
import os
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services.weather import get_weather

c = TestClient(app)
FAKE = {
    "city": "Paris", "country": "France",
    "open_meteo": {"time": "2026-09-20T12:00", "temperature": 18.5, "humidity": 60, "wind": 10.0},
    "openweather": {"temperature": 19.0, "humidity": 58, "wind": 10.8},
    "openweather_error": None, "temp_diff": 0.5, "agree": True,
}


def test_layout():
    r = c.get("/")
    assert r.status_code == 200 and "<nav" in r.text and "<footer" in r.text


def test_static_and_api():
    assert c.get("/static/style.css").status_code == 200
    assert c.get("/api/health").json() == {"status": "ok"}


async def _fake(city):
    return FAKE


async def _missing(city):
    raise HTTPException(404, f"City not found: {city}")


def test_weather_ok():
    with patch("app.routes.api.get_weather", _fake), patch("app.routes.pages.get_weather", _fake):
        assert c.get("/api/weather?city=Paris").json() == FAKE
        page = c.get("/weather?city=Paris").text
        assert "18.5°C" in page and "19.0°C" in page and "Sources agree" in page


def test_weather_errors():
    assert c.get("/api/weather").status_code == 422  # city required
    with patch("app.routes.api.get_weather", _missing), patch("app.routes.pages.get_weather", _missing):
        assert c.get("/api/weather?city=zzz").status_code == 404
        assert "City not found: &lt;b&gt;" in c.get("/weather?city=<b>").text  # escaped


def _upstream(ow_status=200):
    """Patch httpx.AsyncClient so both providers answer from memory."""
    def handler(req):
        host = req.url.host
        if host.startswith("geocoding"):
            return httpx.Response(200, json={"results": [
                {"name": "Paris", "country": "France", "latitude": 48.8, "longitude": 2.3}]})
        if host == "api.open-meteo.com":
            return httpx.Response(200, json={"current": {
                "time": "t", "temperature_2m": 18.0, "relative_humidity_2m": 60, "wind_speed_10m": 10.0}})
        return httpx.Response(ow_status, json={"main": {"temp": 21.5, "humidity": 55}, "wind": {"speed": 3.0}})

    real = httpx.AsyncClient
    return patch("app.services.weather.httpx.AsyncClient",
                 lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def _get(key, **kw):
    env = {"OPENWEATHER_API_KEY": key} if key else {}
    with patch.dict(os.environ, env), _upstream(**kw):
        if not key:
            os.environ.pop("OPENWEATHER_API_KEY", None)
        return asyncio.run(get_weather("Paris"))


def test_cross_check():
    d = _get("k")
    assert d["openweather"] == {"temperature": 21.5, "humidity": 55, "wind": 10.8}  # 3 m/s -> km/h
    assert d["temp_diff"] == 3.5 and d["agree"] is False


def test_openweather_optional():
    d = _get(None)  # no key: primary still works
    assert d["open_meteo"]["temperature"] == 18.0 and d["openweather"] is None and d["agree"] is None
    d = _get("bad", ow_status=401)  # bad key: no crash
    assert d["openweather"] is None and "unavailable" in d["openweather_error"]
