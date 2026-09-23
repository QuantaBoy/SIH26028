from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.services.db import route, search
from app.services.network import STATIONS_JSON, load_network
from app.services.weather import get_weather
from app.services.weather_db import station_weather

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/weather")
async def api_weather(city: str = Query(..., min_length=1, max_length=100)):
    return await get_weather(city)


@router.get("/railway/network")
def railway_network():
    return load_network()


@router.get("/railway/stations")
def railway_stations():
    return FileResponse(STATIONS_JSON, media_type="application/geo+json")


@router.get("/trains")
def api_trains(train: str = Query("", max_length=100), source: str = Query("", max_length=100),
               destination: str = Query("", max_length=100)):
    return search(train, source, destination)


@router.get("/trains/{number}/route")
def api_train_route(number: str):
    found = route(number)
    if not found:
        raise HTTPException(404, f"No train {number}")
    return found


@router.get("/stations/{code}/weather")
def api_station_weather(code: str):
    """Weather at a station, served from weather.db: never a live call on a page request."""
    found = station_weather(code)
    if not found:
        raise HTTPException(404, f"No station {code}")
    return found
