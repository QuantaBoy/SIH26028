import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
LINES_CSV = ROOT / "railway_line_mapping.csv"
STATIONS_CSV = ROOT / "station_mapping.csv"


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_lines() -> list[dict]:
    """Lines from railway_line_mapping.csv, each with its stations (with coordinates) in running order.

    Coordinates live in station_mapping.csv; the two files join on rail_id.
    km_from_start is the rail distance along the line from its first station, per the
    official Southern Railway system map (None where the map gives no distance).
    """
    by_line = defaultdict(list)
    for r in sorted(_read(STATIONS_CSV), key=lambda r: (int(r["rail_id"]), int(r["sequence_in_line"]))):
        by_line[r["rail_id"]].append({
            "name": r["station_name"],
            "lat": float(r["latitude"]),
            "lon": float(r["longitude"]),
            "operational": r["status"] == "Operational",
            "km_from_start": float(r["km_from_start"]) if r["km_from_start"] else None,
        })

    return [{
        "id": int(line["rail_id"]),
        "route": line["route"],
        "length_km": float(line["length_km"]),
        "stations": by_line[line["rail_id"]],
    } for line in _read(LINES_CSV)]
