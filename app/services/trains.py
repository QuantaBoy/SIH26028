"""Train timetables: find trains by number/name and by the stops they make.

Two sources, neither complete on its own and only 1,050 trains in both:
  - isl_wise_train_detail_03082015_v1.csv (Indian Railways via data.gov.in, 2015): 2,810
    trains, station code in its own column. The main source, but it has no running days.
  - EXP-TRAINS.json: 2,533 express trains, with running days. Fills in the rest.
Both are from 2015-ish, so trains introduced later (Vande Bharat, Tejas) are in neither.
"""
import csv
import json
from functools import cache
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
TIMETABLE_CSV = ROOT / "isl_wise_train_detail_03082015_v1.csv"
TRAINS_JSON = ROOT / "EXP-TRAINS.json"
MAX_RESULTS = 50
DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _minutes(hhmmss: str) -> int:
    h, m, _ = hhmmss.split(":")
    return int(h) * 60 + int(m)


def _from_csv() -> dict[str, dict]:
    """Trains keyed by number. The CSV has one row per stop, in running order (islno)."""
    trains = {}
    with open(TIMETABLE_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            number = r["Train No."].strip().strip("'")
            t = trains.setdefault(number, {"number": number, "name": r["train Name"].strip(),
                                           "days": [], "route": []})
            arrives, departs = r["Arrival time"].strip("'"), r["Departure time"].strip("'")
            t["route"].append({
                "code": r["station Code"].strip(), "name": r["Station Name"].strip(),
                "arrives": arrives[:5], "departs": departs[:5],
                "km": int(r["Distance"]), "_at": _minutes(arrives), "_out": _minutes(departs)})

    for t in trains.values():
        route = t["route"]
        route[0]["arrives"], route[-1]["departs"] = "Source", "Destination"
        # No day column: the clock going backwards means the train has passed midnight.
        # The first stop has no real arrival and the last no real departure (both 00:00:00).
        day, clock = 1, route[0]["_out"]
        for i, stop in enumerate(route):
            times = [stop["_at"], stop["_out"]]
            if i == 0:
                times = [stop["_out"]]
            elif i == len(route) - 1:
                times = [stop["_at"]]
            for t_min in times:
                if t_min < clock:
                    day += 1
                clock = t_min
            stop["day"] = str(day)
    return trains


def _from_json() -> dict[str, dict]:
    """Empty when the file is absent: it is not in the repo, and the CSV alone still works."""
    if not TRAINS_JSON.exists():
        return {}
    trains = {}
    for t in json.load(open(TRAINS_JSON, encoding="utf-8")):
        route = []
        for stop in t["trainRoute"]:
            name, _, code = stop["stationName"].rpartition(" - ")
            route.append({"code": code, "name": name, "arrives": stop["arrives"],
                          "departs": stop["departs"], "km": int(stop["distance"].split()[0]),
                          "day": stop["day"]})
        trains[t["trainNumber"]] = {
            "number": t["trainNumber"], "name": t["trainName"], "route": route,
            "days": [d for d in DAYS if t["runningDays"].get(d)]}
    return trains


@cache
def _trains() -> list[dict]:
    """The CSV's schedule wins where both have a train; the JSON supplies the running days."""
    trains, extra = _from_csv(), _from_json()
    for number, t in trains.items():
        if number in extra:
            t["days"] = extra[number]["days"]
    for number, t in extra.items():
        trains.setdefault(number, t)
    return sorted(trains.values(), key=lambda t: t["number"])


@cache
def _codes() -> frozenset[str]:
    return frozenset(stop["code"] for t in _trains() for stop in t["route"])


def _stop_index(train: dict, station: str) -> int | None:
    """Position of the stop for a station code, or the first whose name contains the text.
    A real code only matches as a code: "MAS" is Chennai Central, not SAMASTIPUR."""
    s = station.strip().upper()
    by_code = s in _codes()
    for i, stop in enumerate(train["route"]):
        if (stop["code"] == s) if by_code else (s in stop["name"].upper()):
            return i
    return None


def search(train: str = "", source: str = "", destination: str = "") -> list[dict]:
    """Trains matching every field given; a source must come before the destination on the route."""
    q = train.strip().upper()
    found = []
    for t in _trains():
        if q and not (t["number"].startswith(q) or q in t["name"].upper()):
            continue
        route = t["route"]
        a = _stop_index(t, source) if source.strip() else 0
        b = _stop_index(t, destination) if destination.strip() else len(route) - 1
        if a is None or b is None or a >= b:
            continue
        found.append({
            "number": t["number"], "name": t["name"], "days": t["days"],
            "from": route[a], "to": route[b], "stops": b - a + 1,
            "km": route[b]["km"] - route[a]["km"],
            # Days counted from this journey's start, not the train's first station.
            "day": int(route[b]["day"]) - int(route[a]["day"]) + 1})
        if len(found) == MAX_RESULTS:
            break
    return found


if __name__ == "__main__":
    t = {t["number"]: t for t in _trains()}
    assert t["00851"]["route"][-1]["day"] == "2", t["00851"]["route"]  # BBS 22:50 -> BNC 22:40 next day
    assert t["02877"]["days"] == ["FRI"], t["02877"]["days"]  # running days come from the JSON
    assert search(source="KBK", destination="MJ", train="00961") == []  # wrong direction
    r = search(source="MAS", destination="SBC")
    assert r and all(x["from"]["code"] == "MAS" for x in r), r
    # Chennai to Bengaluru takes a night at most, however far into its run the train already is.
    assert {x["day"] for x in r} <= {1, 2}, r
    assert next(x for x in r if x["number"] == "12296")["day"] == 1  # joins on its own day 3
    print(len(t), "trains;", len(r), "Chennai Central -> KSR Bengaluru")
