import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates

from app.services.db import search
from app.services.weather import get_weather

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/")
async def home(
    request: Request,
    city: str = Query("", max_length=100),
    train: str = Query("", max_length=100),
    source: str = Query("", max_length=100),
    destination: str = Query("", max_length=100),
    show: str = Query("", max_length=20),
):
    """Home page: one place for all data. Weather output is the same payload as /api/weather, dumped raw."""
    city = city.strip()
    weather = None
    if city:
        try:
            weather = json.dumps(await get_weather(city), indent=2)
        except HTTPException as e:
            weather = json.dumps({"error": e.detail}, indent=2)
    asked = any(s.strip() for s in (train, source, destination))
    trains = search(train, source, destination) if asked else None

    # The map draws a train as soon as one is found: the first result, or the one picked
    # from the results with ?show=<number>.
    drawn = next((t for t in trains or [] if t["number"] == show), None) or (trains or [None])[0]
    return templates.TemplateResponse(request, "index.html", {
        "title": "Home", "city": city, "weather": weather,
        "train": train, "source": source, "destination": destination,
        "trains": trains, "show": drawn["number"] if drawn else "",
        "drawn": {"number": drawn["number"], "from_code": drawn["from"]["code"],
                  "to_code": drawn["to"]["code"]} if drawn else None,
    })
