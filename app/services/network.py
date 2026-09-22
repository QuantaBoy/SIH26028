"""All-India railway sections from Railway_Network_.csv, placed on the map.

The CSV is a shapefile's attribute table without the shapes: each section is known
only by the names of its two end junctions. Those names are located in stations.json
(station points with coordinates), and each section is drawn junction to junction.
"""
import csv
import difflib
import json
import math
import re
from collections import defaultdict
from functools import cache
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
NETWORK_CSV = ROOT / "Railway_Network_.csv"
STATIONS_JSON = ROOT / "stations.json"

# Words that don't identify a place: "Arakkonam North Cabin" is at Arakkonam.
NOISE = re.compile(
    r"\b(junction|jn|jct|terminus|terminal|cantt|cantonment|road|rd|halt|central|city|town|cabin|bypass|"
    r"chord|siding|sdg|north|south|east|west|yard|goods|suburban|depot|block|hut|station|bridge|"
    r"military|outer|auxiliary|avoiding|link|linc|freight|scrap|[a-z])\b")
# A junction pair this much farther apart in a straight line than by rail is a wrong name match.
SLACK, SLACK_KM = 1.3, 15
MAX_HOP_KM = 300  # the same check where the CSV gives no track length
# Cities renamed after the station list was made: new spelling -> spelling in stations.json.
RENAMED = {
    "bengaluru": "bangalore", "ballari": "bellary", "belagavi": "belgaum", "kalaburagi": "gulbarga",
    "mysuru": "mysore", "vijayapura": "bijapur", "shivamogga": "shimoga", "tumakuru": "tumkur",
    "hosapete": "hospet", "mangaluru": "mangalore", "prayagraj": "allahabad", "gurugram": "gurgaon",
    "banaras": "varanasi", "baramula": "baramulla", "beed": "bid", "hubballi": "hubli",
    "kalyanadurga": "kalyandurg", "chikkamagaluru": "chikmagalur", "vadodara": "baroda",
}
# Typos and variants in the CSV's railwayzone column.
ZONE_FIX = {"Southen Railway": "Southern Railway", "Westem Railway": "Western Railway",
            "East Coast Railwa": "East Coast Railway", "North Frontier Railway": "Northeast Frontier Railway"}


def key(name: str) -> str:
    name = re.sub(r"\(.*?(\)|$)", "", name.lower())
    k = re.sub(r"[^a-z]", "", NOISE.sub("", name))
    for new, old in RENAMED.items():
        k = k.replace(new, old)
    return k


def candidates(name: str) -> list[str]:
    """Spellings to look a junction up by: its name, then any alternate name in brackets."""
    alt = re.findall(r"\((.*?)(?:\)|$)", name)
    return [k for k in [key(name), *map(key, alt)] if k]


def km(a, b):
    """Great-circle distance between two (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


@cache
def load_network() -> dict:
    # The CSV has one row per geometry piece; a section is one pair of end junctions.
    sections = {}
    with open(NETWORK_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            a, b = r["fromjunction"].strip(), r["tojunction"].strip()
            if not a or not b or a == b:
                continue
            s = sections.setdefault(tuple(sorted((a, b))), {
                "from": a, "to": b, "zone": ZONE_FIX.get(z := r["railwayzone"].strip(), z) or "Unknown",
                "type": r["type"].strip() or "Unknown",
                "speed": _num(r["speed"]), "stations": _num(r["noofstations"]),
                "track_km": _num(r["tracklength"]), "lanes": _num(r["nooflanes"]), "bridges": 0})
            s["bridges"] += r["bridge_yn"] == "Y"

    # One name can be several places (Bilaspur in Chhattisgarh and in Himachal), so keep them all.
    coords, exact = defaultdict(list), defaultdict(list)
    for f in json.load(open(STATIONS_JSON, encoding="utf-8"))["features"]:
        if f["geometry"]:
            lon, lat = f["geometry"]["coordinates"]
            name = f["properties"]["name"]
            exact[re.sub(r"[^a-z]", "", name.lower())].append((lat, lon))
            if key(name):
                coords[key(name)].append((lat, lon))

    by_letter = defaultdict(list)  # fuzzy search only among keys with the same first letter
    for k in coords:
        by_letter[k[0]].append(k)

    names = sorted({n for s in sections.values() for n in (s["from"], s["to"])})
    options = {}
    for name in names:
        found = exact.get(re.sub(r"[^a-z]", "", name.lower()))
        for k in candidates(name):
            if found:
                break
            found = coords.get(k)
            if not found:
                m = difflib.get_close_matches(k, by_letter[k[0]], n=1, cutoff=0.85)
                found = m and coords[m[0]]
        if found:
            options[name] = found

    # Track km per neighbour: a straight line can't be much longer than the rails.
    links = defaultdict(list)
    for s in sections.values():
        limit = SLACK * s["track_km"] + SLACK_KM if s["track_km"] else MAX_HOP_KM
        links[s["from"]].append((s["to"], limit))
        links[s["to"]].append((s["from"], limit))

    def misfits(name, p, located):
        near = [(located[n], limit) for n, limit in links[name] if n in located]
        return sum(km(p, q) > limit for q, limit in near), len(near)

    # Pick, for each name, the place that best fits the neighbours' places; twice, so
    # the second pass sees the first pass's choices. Then drop names that still fit
    # fewer than half their neighbours: wrong matches.
    located = {n: o[0] for n, o in options.items()}
    for _ in range(2):
        for name, opts in options.items():
            located[name] = min(opts, key=lambda p: misfits(name, p, located)[0])
    wrong = [n for n, p in located.items() if (m := misfits(n, p, located))[0] * 2 > m[1]]
    for name in wrong:
        del located[name]

    neighbours = {n: {m for m, _ in l} for n, l in links.items()}
    names = set(names)

    # Cabins, sidings and unlisted halts sit between the junctions they connect, so a
    # junction still not found goes at the centre of its located neighbours (needs two,
    # one alone says nothing about direction). Repeat: each pass can unlock the next.
    approx = set()
    while True:
        found = {}
        for name in sorted(names - located.keys()):
            near = [located[n] for n in neighbours[name] if n in located]
            if len(near) >= 2:
                found[name] = (sum(p[0] for p in near) / len(near), sum(p[1] for p in near) / len(near))
        if not found:
            break
        located.update(found)
        approx.update(found)

    # Last guard: a section whose ends are too far apart for its rail length has a
    # misplaced end (wrong matches that agree with each other, or a guessed centre).
    drawn, misplaced = [], 0
    for s in sections.values():
        if s["from"] in located and s["to"] in located:
            a, b = located[s["from"]], located[s["to"]]
            if km(a, b) > (SLACK * s["track_km"] + SLACK_KM if s["track_km"] else MAX_HOP_KM):
                misplaced += 1
                continue
            drawn.append({**s, "path": [a, b], "approximate": s["from"] in approx or s["to"] in approx})
    on_map = {n for s in drawn for n in (s["from"], s["to"])}
    return {
        "sections": drawn,
        "junctions": [{"name": n, "lat": p[0], "lon": p[1], "approximate": n in approx}
                      for n, p in sorted(located.items()) if n in on_map],
        "unlocated": sorted(names - located.keys()),
        "total_sections": len(sections),
        "misplaced_sections": misplaced,
    }


if __name__ == "__main__":
    assert key("Arakkonam North Cabin") == key("Arakkonam") == "arakkonam"
    assert key("Palakkad Junction (Palghat)") == "palakkad"
    assert candidates("Belagavi (Belgaum)") == ["belgaum", "belgaum"]
    assert key("Bengaluru City Junction") == "bangalore"
    assert round(km((13.08, 80.27), (12.97, 77.59))) in range(285, 295)  # Chennai-Bengaluru
    import time
    t = time.time()
    n = load_network()
    print(sum(j["approximate"] for j in n["junctions"]), "approximate")
    print(f"{len(n['junctions'])} junctions located, {len(n['unlocated'])} not; "
          f"{len(n['sections'])}/{n['total_sections']} sections drawn, {n['misplaced_sections']} misplaced, in {time.time() - t:.1f}s")
    print(n["unlocated"][:60])
