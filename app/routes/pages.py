import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates

from app.services.live import tracked, train_detail, train_list
from app.services.weather import get_weather

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/")
async def home(request: Request, city: str = Query("", max_length=100),
               train: str = Query("", pattern=r"^(\d{5})?$")):
    """Home page: one place for all data. Weather output is the same payload as /api/weather,
    dumped raw. ?train=<number> starts live tracking of that train."""
    city = city.strip()
    weather = None
    if city:
        try:
            weather = json.dumps(await get_weather(city), indent=2)
        except HTTPException as e:
            weather = json.dumps({"error": e.detail}, indent=2)
    return templates.TemplateResponse(request, "index.html", {
        "title": "Home", "city": city, "weather": weather, "train": train, "tracked": tracked(),
        "trains": train_list()})


@router.get("/train/{number}")
def train_page(request: Request, number: str):
    """One train's route: halts, scheduled times, real delays on past runs, and the route on a map."""
    found = train_detail(number)
    if not found:
        raise HTTPException(404, f"No stored runs for train {number}")
    return templates.TemplateResponse(request, "train.html", {"title": f"Train {number}", "t": found})


@router.get("/network")
def entire_network(request: Request):
    """The whole country divided into weather cells, with the rail network and tracked trains on top."""
    return templates.TemplateResponse(request, "network.html", {"title": "Entire Network"})
