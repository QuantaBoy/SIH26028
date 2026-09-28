"""Railway bridges at their real positions, from OpenStreetMap.

The network CSV knows how many bridge spans a section has and how long they are, but not
where they stand: its pieces are not stored in track order, so a bridge could only be
drawn at the section's middle, often kilometres off the river and sometimes on the wrong
line. OpenStreetMap maps every railway bridge as the track itself, so here each bridge is
its own line on the map, and a bridge is on a train's route only if that line lies on the
train's track.

The bridges are fetched once and committed, like the station list:

    python -m app.services.bridges        # rebuild network_map/rail_bridges.json (~1 min)
"""
import json
import math
from functools import cache

import httpx

from app.services.network import ROOT, km

BRIDGES_JSON = ROOT / "network_map" / "rail_bridges.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MIN_LENGTH_M = 100
QUERY = f"""[out:json][timeout:300];
area["ISO3166-1"="IN"][admin_level=2]->.in;
way["railway"="rail"]["bridge"](area.in)(if: length() > {MIN_LENGTH_M});
out tags geom;"""
ON_TRACK_KM = 0.3  # a bridge's ends this close to a train's track: the train crosses it


def build() -> int:
    """Fetch every railway bridge in India over MIN_LENGTH_M and save the file."""
    r = httpx.post(OVERPASS_URL, data={"data": QUERY}, timeout=400,
                   headers={"User-Agent": "SIH26028-railway-eta/0.1"})  # Overpass refuses no-name clients
    found = []
    for e in r.raise_for_status().json()["elements"]:
        line = [[round(p["lat"], 6), round(p["lon"], 6)] for p in e["geometry"]]
        t = e.get("tags", {})
        found.append({"osm_id": e["id"], "name": t.get("bridge:name") or t.get("name"),
                      "length_m": round(sum(km(a, b) for a, b in zip(line, line[1:])) * 1000),
                      "viaduct": t.get("bridge") == "viaduct",
                      "line": line})
    # Double track is often mapped as two ways side by side; they are one bridge to a passenger.
    found.sort(key=lambda b: -b["length_m"])
    kept = []
    for b in found:
        if not any(km(b["line"][0], k["line"][0]) < 0.05 and km(b["line"][-1], k["line"][-1]) < 0.05 or
                   km(b["line"][0], k["line"][-1]) < 0.05 and km(b["line"][-1], k["line"][0]) < 0.05
                   for k in kept if abs(k["length_m"] - b["length_m"]) < 0.1 * k["length_m"]):
            kept.append(b)
    BRIDGES_JSON.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    return len(kept)


@cache
def bridges() -> list[dict]:
    return json.loads(BRIDGES_JSON.read_text(encoding="utf-8")) if BRIDGES_JSON.exists() else []


def _to_segment_km(p, a, b) -> float:
    """Distance from point p to the segment a-b, on a flat projection (fine over a few km)."""
    cos = math.cos(math.radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * cos, a[0], b[1] * cos, b[0], p[1] * cos, p[0]
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ((dx * dx + dy * dy) or 1)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy) * 111.2


def near_track(p, track: list, limit_km: float) -> bool:
    return any(_to_segment_km(p, a, b) <= limit_km for a, b in zip(track, track[1:]))


def on_track(track: list[list[float]], min_length_m: int = 200) -> list[dict]:
    """Bridges whose both ends lie on the track: bridges the train really crosses. A
    bridge on a line running beside or across the track has at least one end off it."""
    if len(track) < 2:
        return []
    lats, lons = [p[0] for p in track], [p[1] for p in track]
    box = (min(lats) - 0.05, max(lats) + 0.05, min(lons) - 0.05, max(lons) + 0.05)
    return [b for b in bridges() if b["length_m"] >= min_length_m and
            all(box[0] <= p[0] <= box[1] and box[2] <= p[1] <= box[3] and near_track(p, track, ON_TRACK_KM)
                for p in (b["line"][0], b["line"][-1]))]


if __name__ == "__main__":
    import sys
    if "--build" in sys.argv or not BRIDGES_JSON.exists():
        print(build(), "bridges saved to", BRIDGES_JSON.name)
        bridges.cache_clear()
    track = [[9.2800, 79.1200], [9.2800, 79.2200]]  # an east-west track
    assert near_track([9.2810, 79.1700], track, ON_TRACK_KM)  # 110 m off it
    assert not near_track([9.2900, 79.1700], track, ON_TRACK_KM)  # 1.1 km off it
    top = bridges()[:5]
    print(len(bridges()), "bridges; longest:", [(b["name"], b["length_m"]) for b in top])
