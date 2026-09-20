import asyncio
import os
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services.weather import get_weather

c = TestClient(app)


def test_pages():
    assert "<nav" in c.get("/").text
    with _upstream():  # no network
        page = c.get("/weather?city=Paris").text
    assert "<pre>" in page and "open_meteo" in page  # raw API payload on the page (quotes HTML-escaped)


def test_health():
    assert c.get("/api/health").json() == {"status": "ok"}


def test_city_required():
    assert c.get("/api/weather").status_code == 422


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
