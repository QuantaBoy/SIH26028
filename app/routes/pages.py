import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates

from app.services.weather import get_weather

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"title": "Home"})


@router.get("/weather")
async def weather(request: Request, city: str = Query("", max_length=100)):
    """Same payload as /api/weather, dumped raw."""
    city = city.strip()
    output = None
    if city:
        try:
            output = json.dumps(await get_weather(city), indent=2)
        except HTTPException as e:
            output = json.dumps({"error": e.detail}, indent=2)
    return templates.TemplateResponse(
        request, "weather.html", {"title": "Weather", "city": city, "output": output})
