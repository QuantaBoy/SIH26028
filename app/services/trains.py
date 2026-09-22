"""Express train timetables from EXP-TRAINS.json: find trains by number/name and by the stops they make."""
import json
from functools import cache
from pathlib import Path

TRAINS_JSON = Path(__file__).parent.parent.parent / "EXP-TRAINS.json"
MAX_RESULTS = 50


@cache
def _trains() -> list[dict]:
    trains = json.load(open(TRAINS_JSON, encoding="utf-8"))
    for t in trains:
        for stop in t["trainRoute"]:  # "MARWAR JN - MJ" -> name and station code
            stop["name"], _, stop["code"] = stop["stationName"].rpartition(" - ")
    return trains


def _km(stop: dict) -> int:
    """Distance from the train's first station: "25 kms" -> 25."""
    return int(stop["distance"].split()[0])


@cache
def _codes() -> frozenset[str]:
    return frozenset(stop["code"] for t in _trains() for stop in t["trainRoute"])


def _stop_index(train: dict, station: str) -> int | None:
    """Position of the stop for a station code, or the first whose name contains the text.
    A real code only matches as a code: "MAS" is Chennai Central, not SAMASTIPUR."""
    s = station.strip().upper()
    by_code = s in _codes()
    for i, stop in enumerate(train["trainRoute"]):
        if (stop["code"] == s) if by_code else (s in stop["name"].upper()):
            return i
    return None


def search(train: str = "", source: str = "", destination: str = "") -> list[dict]:
    """Trains matching every field given; a source must come before the destination on the route."""
    q = train.strip().upper()
    found = []
    for t in _trains():
        if q and not (t["trainNumber"].startswith(q) or q in t["trainName"].upper()):
            continue
        route = t["trainRoute"]
        a = _stop_index(t, source) if source.strip() else 0
        b = _stop_index(t, destination) if destination.strip() else len(route) - 1
        if a is None or b is None or a >= b:
            continue
        found.append({
            "number": t["trainNumber"], "name": t["trainName"],
            "days": [d for d, runs in t["runningDays"].items() if runs],
            "from": route[a], "to": route[b], "stops": b - a + 1,
            "km": _km(route[b]) - _km(route[a]),
        })
        if len(found) == MAX_RESULTS:
            break
    return found


if __name__ == "__main__":
    r = search(train="00961")
    assert r and r[0]["from"]["code"] == "MJ" and r[0]["to"]["code"] == "KBK"
    assert search(source="KBK", destination="MJ", train="00961") == []  # wrong direction
    assert search(source="PHULAD", destination="KBK", train="00961")[0]["stops"] == 2
    r = search(source="MAS", destination="SBC")
    assert r and all(t["from"]["code"] == "MAS" for t in r), r
    assert search(source="chennai", destination="bangalore")
    print(len(r), "trains Chennai Central -> Bengaluru")
