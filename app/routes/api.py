from fastapi import APIRouter, Query

from app.services.railway import load_lines
from app.services.weather import get_weather

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/weather")
async def api_weather(city: str = Query(..., min_length=1, max_length=100)):
    return await get_weather(city)


@router.get("/railway/lines")
def railway_lines():
    return load_lines()
