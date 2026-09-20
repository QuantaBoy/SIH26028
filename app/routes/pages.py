from fastapi import APIRouter, HTTPException, Query, Request

from app.core.templating import templates
from app.services.weather import get_weather

router = APIRouter()


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"title": "Home"})


@router.get("/weather")
async def weather(request: Request, city: str = Query("", max_length=100)):
    city = city.strip()
    ctx = {"title": "Weather", "city": city, "data": None, "error": None}
    if city:
        try:
            ctx["data"] = await get_weather(city)
        except HTTPException as e:
            ctx["error"] = e.detail
    return templates.TemplateResponse(request, "weather.html", ctx)
