"""SQLite database of trains, their stops and the stations, built from the data files.

Build or rebuild it with `python -m app.services.db`; the app builds it on first use
if the file is missing. The data files stay the source of truth: this is a cache of
them in queryable form, so rebuilding is always safe.
"""
import json
import sqlite3
from functools import cache
from pathlib import Path

from app.services.network import STATIONS_JSON
from app.services.trains import DAYS, _trains

ROOT = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "railway.db"

SCHEMA = """
CREATE TABLE stations (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT,
    zone TEXT,
    lat REAL,
    lon REAL
);
CREATE TABLE trains (
    number TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    days TEXT,              -- "MON,TUE,..."; empty when no source gives the running days
    source_code TEXT NOT NULL,
    destination_code TEXT NOT NULL,
    stops INTEGER NOT NULL,
    distance_km INTEGER NOT NULL
);
CREATE TABLE stops (
    train_number TEXT NOT NULL REFERENCES trains(number),
    seq INTEGER NOT NULL,   -- 1-based position along the route
    station_code TEXT NOT NULL,
    station_name TEXT NOT NULL,
    arrives TEXT NOT NULL,  -- "HH:MM", or "Source" at the first stop
    departs TEXT NOT NULL,  -- "HH:MM", or "Destination" at the last stop
    day INTEGER NOT NULL,   -- day of the run, counted from the train's first station
    km INTEGER NOT NULL,    -- distance from the train's first station
    PRIMARY KEY (train_number, seq)
);
CREATE INDEX stops_by_station ON stops(station_code);
CREATE INDEX stations_by_name ON stations(name);
CREATE INDEX trains_by_name ON trains(name);
"""


def connect() -> sqlite3.Connection:
    """Read-only-ish connection; builds the database first if it isn't there yet."""
    if not DB_PATH.exists():
        build()
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def build() -> dict:
    """(Re)create the database from the data files. Returns row counts."""
    tmp = DB_PATH.with_suffix(".building")  # never leave a half-built file in place
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)

    stations = [
        (f["properties"]["code"].strip(), f["properties"]["name"].strip(),
         f["properties"].get("state"), (f["properties"].get("zone") or "").strip() or None,
         f["geometry"]["coordinates"][1] if f["geometry"] else None,
         f["geometry"]["coordinates"][0] if f["geometry"] else None)
        for f in json.load(open(STATIONS_JSON, encoding="utf-8"))["features"]]
    con.executemany("INSERT OR IGNORE INTO stations VALUES (?, ?, ?, ?, ?, ?)", stations)

    trains, stops = [], []
    for t in _trains():
        route = t["route"]
        trains.append((t["number"], t["name"], ",".join(d for d in DAYS if d in t["days"]),
                       route[0]["code"], route[-1]["code"], len(route), route[-1]["km"]))
        stops += [(t["number"], i, s["code"], s["name"], s["arrives"], s["departs"],
                   int(s["day"]), s["km"]) for i, s in enumerate(route, 1)]
    con.executemany("INSERT INTO trains VALUES (?, ?, ?, ?, ?, ?, ?)", trains)
    con.executemany("INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?, ?, ?)", stops)

    con.commit()
    con.close()
    tmp.replace(DB_PATH)
    return {"stations": len(stations), "trains": len(trains), "stops": len(stops)}


@cache
def _is_code(text: str) -> bool:
    con = connect()
    try:
        return bool(con.execute("SELECT 1 FROM stations WHERE code = ? LIMIT 1", (text,)).fetchone())
    finally:
        con.close()


def _station_sql(alias: str, station: str, key: str, params: dict) -> str:
    """SQL matching a stop to what the user typed. A real station code matches only as a
    code, so "MAS" is Chennai Central and not SAMASTIPUR; anything else matches by name."""
    station = station.strip().upper()
    if _is_code(station):
        params[key] = station
        return f"{alias}.station_code = :{key}"
    params[key] = f"%{station}%"
    return f"UPPER({alias}.station_name) LIKE :{key}"


def search(train: str = "", source: str = "", destination: str = "", limit: int = 50) -> list[dict]:
    """Trains matching every field given, with the leg from source to destination.

    A train counts only when it calls at the source before the destination, so a train
    running the other way is left out.
    """
    where, params = [], {"limit": limit}
    if q := train.strip().upper():
        where.append("(t.number LIKE :num OR UPPER(t.name) LIKE :name)")
        params |= {"num": q + "%", "name": f"%{q}%"}

    # The first stop matching the source, then the first matching stop after it.
    src = _station_sql("a", source, "src", params) if source.strip() else "a.seq = 1"
    dst = _station_sql("b", destination, "dst", params) if destination.strip() else None
    where.append(src)
    where.append(f"""a.seq = (SELECT MIN(seq) FROM stops a WHERE a.train_number = t.number AND {src})""")
    if dst:
        where.append(dst)
        where.append(f"""b.seq = (SELECT MIN(seq) FROM stops b WHERE b.train_number = t.number
                                  AND b.seq > a.seq AND {dst})""")
    else:
        where.append("b.seq = (SELECT MAX(seq) FROM stops b WHERE b.train_number = t.number)")

    rows_sql = f"""
    SELECT t.number, t.name, t.days,
           a.station_code AS from_code, a.station_name AS from_name, a.departs AS from_departs,
           a.day AS from_day, a.km AS from_km,
           b.station_code AS to_code, b.station_name AS to_name, b.arrives AS to_arrives,
           b.day AS to_day, b.km AS to_km, b.seq - a.seq + 1 AS stops
    FROM trains t
    JOIN stops a ON a.train_number = t.number
    JOIN stops b ON b.train_number = t.number AND b.seq > a.seq
    WHERE {' AND '.join(where)}
    ORDER BY t.number
    LIMIT :limit
    """
    con = connect()
    try:
        rows = con.execute(rows_sql, params).fetchall()
    finally:
        con.close()
    return [{
        "number": r["number"], "name": r["name"],
        "days": r["days"].split(",") if r["days"] else [],
        "from": {"code": r["from_code"], "name": r["from_name"], "departs": r["from_departs"]},
        "to": {"code": r["to_code"], "name": r["to_name"], "arrives": r["to_arrives"]},
        "stops": r["stops"], "km": r["to_km"] - r["from_km"],
        "day": r["to_day"] - r["from_day"] + 1,
    } for r in rows]


def route(number: str) -> dict | None:
    """One train with every stop in order, each with its coordinates where the station is known."""
    con = connect()
    try:
        t = con.execute("SELECT * FROM trains WHERE number = ?", (number,)).fetchone()
        if not t:
            return None
        stops = con.execute("""
            SELECT s.seq, s.station_code, s.station_name, s.arrives, s.departs, s.day, s.km,
                   st.lat, st.lon
            FROM stops s LEFT JOIN stations st ON st.code = s.station_code
            WHERE s.train_number = ? ORDER BY s.seq""", (number,)).fetchall()
    finally:
        con.close()
    return {"number": t["number"], "name": t["name"],
            "days": t["days"].split(",") if t["days"] else [],
            "stops": [dict(s) for s in stops]}


if __name__ == "__main__":
    counts = build()
    print(f"{DB_PATH.name}: " + ", ".join(f"{n} {k}" for k, n in counts.items()))

    r = search(source="MAS", destination="SBC")
    assert r and all(x["from"]["code"] == "MAS" for x in r), r
    assert {x["day"] for x in r} <= {1, 2}, r  # a night at most, wherever the train started
    assert not search(source="SBC", destination="MAS", train="12007")  # wrong direction
    assert all("KAVERI" in x["name"].upper() for x in search(train="kaveri"))
    assert any(x["number"] == "16021" for x in search(train="kaveri"))
    r12007 = route("12007")
    assert r12007["stops"][0]["station_code"] == "MAS" and r12007["stops"][0]["lat"]
    print(len(search(source="MAS", destination="SBC")), "Chennai Central -> KSR Bengaluru;",
          len(r12007["stops"]), "stops on 12007")
