"""ETA at every halt ahead of a train, from its live position and its own past runs.

The baseline is what a static system says: every halt ahead at its scheduled time plus
the delay the train has now. Real trains don't keep their delay: timetables hold
recovery time (12639 on 23 Sep 2026 was 34 min late at KJM and 5 min early at SBC),
and some sections lose time every day. So the prediction is:

    delay at halt j = delay now + the delay change from here to j on past runs (median)

taken from runs of the same train, and never earlier than the train has ever arrived at j.
The spread of those past changes (10th-90th percentile) gives the range. With fewer than
MIN_RUNS past runs the baseline is used, and the answer says so.

Every ETA given for a running train is logged; once the run is collected, accuracy()
compares each ETA with the actual arrival, next to the baseline and RailRadar's own.
"""
import statistics
from datetime import datetime, timedelta

from app.services import bridges, live
from app.services.weather_db import IST, forecast_at

MIN_RUNS = 3
RANGE_RUNS = 5  # past runs needed before a range is given
STALE_MINUTES = 30


def _at(iso: str | None, minutes: float = 0) -> str | None:
    return iso and (datetime.fromisoformat(iso) + timedelta(minutes=round(minutes))).isoformat()


def _minutes(a: str, b: str) -> float:
    return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds() / 60


def _along(route: list[dict], km: float | None) -> dict | None:
    """The point `km` along the route, between the two route points either side of it:
    where the train is when RailRadar reports its distance run but no coordinates."""
    pts = [s for s in route if s.get("lat") is not None and s.get("distance") is not None]
    for a, b in zip(pts, pts[1:]):
        if km is not None and a["distance"] <= km <= b["distance"]:
            f = (km - a["distance"]) / ((b["distance"] - a["distance"]) or 1)
            return {"lat": a["lat"] + f * (b["lat"] - a["lat"]), "lng": a["lng"] + f * (b["lng"] - a["lng"])}
    return None


def _nearest(track: list, p) -> int:
    """Index of the track point closest to p."""
    return min(range(len(track)), key=lambda i: (track[i][0] - p[0]) ** 2 + (track[i][1] - p[1]) ** 2)


def predict(data: dict, runs: list[list]) -> dict:
    """The run as it stands and an ETA at each halt still ahead. `runs` are past runs of
    the train, each a list of its halts with station, delay_arr and delay_dep."""
    halts = [s for s in data["route"] if s["isHalt"]]
    reached = [s for s in halts if live.is_real(s)]
    anchor = reached[-1] if reached else halts[0]
    delay = data.get("delayMinutes") or 0
    if not reached or anchor["status"] == "at-station":
        delay = max(delay, 0)  # a train never leaves a halt before its time

    # Each past run's delay leaving the anchor halt, then its arrival delay at every halt.
    past = []
    for run in runs:
        by_code = {r["station"]: r for r in run}
        a = by_code.get(anchor["stationCode"])
        start = a and (a["delay_dep"] if a["delay_dep"] is not None else a["delay_arr"])
        if start is not None:
            past.append((start, by_code))

    out = []
    for s in halts:
        stop = {"seq": s["sequence"], "code": s["stationCode"], "name": s["stationName"],
                "lat": s.get("lat"), "lng": s.get("lng"), "platform": s.get("platform"),
                "scheduled": s.get("scheduledArrival") or s.get("scheduledDeparture"),
                "passed": live.is_real(s)}
        if stop["passed"]:
            stop["actual"] = s.get("actualArrival") or s.get("actualDeparture")
            stop["delay"] = s.get("delayArrival") if s.get("delayArrival") is not None else s.get("delayDeparture")
        else:
            changes = [by[s["stationCode"]]["delay_arr"] - start for start, by in past
                       if s["stationCode"] in by and by[s["stationCode"]]["delay_arr"] is not None]
            earliest = min((by[s["stationCode"]]["delay_arr"] for _, by in past
                            if s["stationCode"] in by and by[s["stationCode"]]["delay_arr"] is not None),
                           default=None)
            if len(changes) >= MIN_RUNS:
                d = max(delay + statistics.median(changes), earliest)
                model = "history"
            else:
                d, model = delay, "baseline"
            stop |= {"delay": round(d), "model": model, "past_runs": len(changes),
                     "eta": _at(stop["scheduled"], d), "baseline": _at(stop["scheduled"], delay),
                     "railradar": s.get("actualArrival")}
            if len(changes) >= RANGE_RUNS:
                lo, *_, hi = statistics.quantiles(changes, n=10)
                stop |= {"eta_low": _at(stop["scheduled"], max(delay + lo, earliest)),
                         "eta_high": _at(stop["scheduled"], delay + hi)}
            if stop["lat"] is not None:  # the weather expected there when the train is
                w = forecast_at(stop["lat"], stop["lng"], datetime.fromisoformat(stop["eta"]))
                stop["weather"] = w and {k: w[k] for k in ("temperature", "condition", "precipitation", "wind")}
        out.append(stop)

    updated = data.get("lastUpdatedAt")
    loc = data.get("currentLocation") or {}
    point = loc.get("coordinates") or _along(data["route"], loc.get("distanceFromOriginKm"))
    # The real track when RailRadar sends it, else station to station.
    track = (data.get("geometry") or {}).get("coordinates") or \
        [[s["lat"], s["lng"]] for s in data["route"] if s.get("lat") is not None]
    here = _nearest(track, [point["lat"], point["lng"]]) if point and track and data["status"] != "not-started" else -1
    if data["status"] == "completed":
        here = len(track)
    crossed = [{"name": b["name"], "length_m": b["length_m"], "viaduct": b["viaduct"], "line": b["line"],
                "crossed": _nearest(track, b["line"][len(b["line"]) // 2]) < here}
               for b in bridges.on_track(track)]
    return {
        "number": data["trainNumber"], "name": data["trainName"], "start_date": data["startDate"],
        "status": data["status"], "updated": updated, "delay": delay,
        "stale": bool(updated and data["status"] not in ("completed", "not-started") and
                      _minutes(datetime.now(IST).isoformat(), updated) > STALE_MINUTES),
        "exceptions": data.get("exceptions"),
        "position": {"code": loc.get("stationCode"), "name": loc.get("stationName"),
                     "status": loc.get("status"), "speed": loc.get("speedKmh"),
                     "km": loc.get("distanceFromOriginKm"), **(point or {})},
        "from_station": anchor["stationCode"], "next": data.get("nextHalt"),
        "past_runs": len(past), "halts": out, "path": track, "bridges": crossed,
    }


async def track(number: str, day: str | None = None) -> dict:
    """Live status and ETAs for a train; each fresh ETA is logged to measure accuracy."""
    data, fresh = await live.live(number, day)
    result = predict(data, live.runs_of(number))
    if fresh and data["status"] != "completed":
        now = datetime.now(IST).isoformat()
        con = live.connect()
        try:
            con.executemany("INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (result["number"], result["start_date"], h["code"], now, result["from_station"],
                 h["eta"], h["baseline"], h["railradar"])
                for h in result["halts"] if not h["passed"] and h["eta"]])
            con.commit()
        finally:
            con.close()
    result["calls_left"] = live.calls_left()
    return result


def accuracy() -> dict:
    """Mean absolute error, in minutes, of every logged ETA whose arrival is now known."""
    con = live.connect()
    try:
        rows = con.execute("""
            SELECT p.predicted, p.baseline, p.railradar, r.actual_arr
            FROM predictions p JOIN runs r
              ON r.train = p.train AND r.start_date = p.start_date AND r.station = p.station
            WHERE r.actual_arr IS NOT NULL""").fetchall()
    finally:
        con.close()
    def mae(col):
        errors = [abs(_minutes(r[col], r["actual_arr"])) for r in rows if r[col]]
        return round(statistics.mean(errors), 1) if errors else None
    return {"etas_checked": len(rows), "ours_min": mae("predicted"), "baseline_min": mae("baseline"),
            "railradar_min": mae("railradar")}


if __name__ == "__main__":
    def halt(seq, code, status, sched, delay=None):
        s = {"sequence": seq, "stationCode": code, "stationName": code, "isHalt": True,
             "status": status, "scheduledArrival": sched, "lat": None}
        if status != "upcoming":
            s |= {"actualArrival": _at(sched, delay), "delayArrival": delay}
        return s

    def past(kjm, sbc):
        return [{"station": "KJM", "delay_arr": kjm - 2, "delay_dep": kjm},
                {"station": "SBC", "delay_arr": sbc, "delay_dep": None}]

    data = {"trainNumber": "12639", "trainName": "T", "startDate": "2026-09-23", "status": "running",
            "delayMinutes": 20, "route": [halt(72, "KJM", "departed", "2026-09-23T12:48:00+05:30", 18),
                                          halt(76, "SBC", "upcoming", "2026-09-23T14:00:00+05:30")]}
    # Runs have made up 30-40 minutes after KJM: 20 late there means about on time at SBC.
    runs = [past(34, -5), past(30, -2), past(10, -6)]
    sbc = predict(data, runs)["halts"][-1]
    assert sbc["model"] == "history" and sbc["delay"] == -6, sbc  # 20 - 32 = -12, but never before -6
    assert sbc["baseline"] == "2026-09-23T14:20:00+05:30"
    assert predict(data, runs[:2])["halts"][-1]["model"] == "baseline"  # too few runs to learn from
    assert _along([{"lat": 0, "lng": 0, "distance": 0}, {"lat": 2, "lng": 4, "distance": 10}], 5) == \
        {"lat": 1, "lng": 2}  # half way by distance, half way on the map
    print("eta ok")
