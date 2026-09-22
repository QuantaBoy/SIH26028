from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.services.network import STATIONS_JSON, load_network
from app.services.weather import get_weather

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
