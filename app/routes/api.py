import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.services import eta, live
from app.services.bridges import bridges
from app.services.network import STATIONS_JSON, load_network
from app.services.weather import get_weather
from app.services.weather_db import grid, station_weather

router = APIRouter()


@router.get("/weather/grid")
def api_weather_grid(hour: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2}T\d{2}:00)?$")):
    """The forecast for every weather cell at one hour (IST, 'YYYY-MM-DDTHH:00'; now by default)."""
    return grid(hour or None)


@router.get("/network/trains")
def api_network_trains():
    """Tracked trains' runs from yesterday to two days out, with halt times, for the network map."""
    return live.scheduled_runs()


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


@router.get("/railway/bridges")
def railway_bridges():
    """How many real bridges are mapped, and the 15 longest named as bridges. Unnamed and
    line-named ways ("Salem-Karur", 14 km) are often a whole elevated stretch tagged bridge."""
    named = [b for b in bridges() if not b["viaduct"] and b["name"] and
             any(w in b["name"].lower() for w in ("bridge", "setu", "pul"))]
    return {"count": len(bridges()), "longest": named[:15]}


@router.get("/trains")
def api_trains():
    """The trains whose runs are collected every day, the ones ETAs learn for."""
    return live.tracked()


@router.get("/trains/{number}/live")
async def api_train_live(number: str, date: str = Query("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")):
    """Where the train is now and its ETA at every halt ahead. `date` picks a run by its
    start date; without it, RailRadar's current run."""
    try:
        return await eta.track(number, date or None)
    except live.QuotaSpent as e:
        raise HTTPException(429, str(e)) from None
    except httpx.HTTPStatusError as e:
        raise HTTPException(404 if e.response.status_code == 404 else 502,
                            f"RailRadar: {e.response.status_code}") from None
    except httpx.HTTPError:
        raise HTTPException(502, "RailRadar unavailable") from None


@router.get("/eta/accuracy")
def api_eta_accuracy():
    """How close logged ETAs came to the actual arrivals, next to the baseline and RailRadar."""
    return eta.accuracy()


@router.get("/stations/{code}/weather")
def api_station_weather(code: str):
    """Weather at a station, served from weather.db: never a live call on a page request."""
    found = station_weather(code)
    if not found:
        raise HTTPException(404, f"No station {code}")
    return found
