"""Import of the trip history that the MyŠkoda app can export as CSV (tripStatistics_<VIN>.csv and the
tripStatistics_from_DDMMYYYY_to_DDMMYYYY_<VIN>.csv range exports).

The official API has no history, so this file is the only source of trips from before Mate started recording, and
the car's own numbers (odometer, energy, consumption, charge levels) are better than anything Mate can derive.

Duplicates are the main risk (overlapping exports, the same file twice, trips Mate already recorded itself or fetched
with the old importer), so the rules are explicit and tested:
  1. inside one upload, a trip is identified by (start minute, end minute, distance); repeats are dropped;
  2. against the database, a row is "the same trip" if it starts within 3 minutes AND (ends within 5 minutes OR has the
     same distance within 2 km), or if the odometer ranges of both overlap by at least half; such a trip is updated
     with the car's figures instead of being inserted again; one stored trip is matched at most once;
  3. a trip the user annotated keeps its note, and nothing is ever deleted.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import merge, places, recorder


def _cell(row: list[str], idx: dict[str, int | None], key: str) -> str:
    """One cell of a CSV row by column key; empty when the column is absent or the row is short."""
    i = idx[key]
    return row[i].strip() if i is not None and i < len(row) else ""


def _num(text) -> float | None:
    """'23' / '10.0' / '10,0' / '1.234,5' / '' -> float | None. The export's number format follows the app's language."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = re.search(r"-?\d[\d.,   ]*", str(text))
    if not m:
        return None
    s = m.group(0).strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if "," in s and "." in s:  # the later separator is the decimal one
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

# canonical key -> accepted header spellings (lower-cased). Only English is known; unknown headers give a clear error.
COLUMNS = {
    "start": ("start of trip",), "end": ("end of trip",), "klass": ("classification",),
    "start_addr": ("start address",), "end_addr": ("end address",),
    "start_xy": ("start coordinates",), "end_xy": ("end coordinates",),
    "km": ("distance in km",), "odo_start": ("start odometer in km",), "odo_end": ("end odometer in km",),
    "driving": ("driving time in minutes",), "travel": ("travel time in minutes",), "speed": ("average speed in km/h",),
    "kwh": ("electricity consumption in kwh",), "kwh100": ("average electricity consumption in kwh/100km",),
    "soc_start": ("start soc in %",), "soc_end": ("end soc in %",),
    "stops": ("public charging stops",), "gained": ("public charge soc gained in %",), "short": ("short trip",),
}
REQUIRED = ("start", "end", "km")
DATE_FORMATS = ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")
VIN_IN_NAME = re.compile(r"[A-HJ-NPR-Z0-9]{17}")

START_TOL_MIN, END_TOL_MIN, KM_TOL = 3, 5, 2.0
GRAIN_COLS = ("distance_km", "energy_kwh", "start_soc", "end_soc", "odo_start", "odo_end", "start_place", "end_place", "duration_min",
              "avg_speed_kmh", "avg_kwh_100km", "driving_min", "public_stops", "public_soc_gained", "short_trip")


class ImportError_(ValueError):
    """The whole upload is unusable (bad timezone, no file). Per-file and per-row problems are reported, not raised."""


@dataclass
class FileReport:
    name: str
    rows: int = 0
    parsed: int = 0
    skipped_no_distance: int = 0
    errors: list = field(default_factory=list)
    vin: str | None = None
    first: str | None = None
    last: str | None = None


def get_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ImportError_(f"Unknown time zone {name!r}. Use a name like Europe/Berlin.") from None


def parse_local(text: str, tz: ZoneInfo) -> datetime | None:
    """A local wall-clock time from the export -> UTC. The export carries no zone; it is the car's/phone's local time."""
    s = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            continue
    return None


def _xy(text: str) -> tuple[float | None, float | None]:
    """'53.087025,8.588595' (or '53,087025;8,588595', or the 4-part German comma form) -> (lat, lon)."""
    s = (text or "").strip()
    if not s:
        return None, None
    if ";" in s:
        parts = s.split(";")
    elif s.count(",") == 1:
        parts = s.split(",")
    elif s.count(",") == 3:
        p = s.split(",")
        parts = [f"{p[0]}.{p[1]}", f"{p[2]}.{p[3]}"]
    else:
        return None, None
    lat, lon = _num(parts[0]), _num(parts[1]) if len(parts) > 1 else None
    if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
        return None, None
    return lat, lon


def _int(text) -> int | None:
    v = _num(text)
    return None if v is None else int(round(v))


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat()


def sniff_delimiter(first_line: str) -> str:
    return max((",", ";", "\t"), key=lambda d: first_line.count(d))


def parse_file(name: str, text: str, tz: ZoneInfo) -> tuple[list[dict], FileReport]:
    rep = FileReport(name=name)
    m = VIN_IN_NAME.search(name.upper())
    rep.vin = m.group(0) if m else None
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        rep.errors.append("The file is empty.")
        return [], rep
    reader = csv.reader(io.StringIO(text), delimiter=sniff_delimiter(lines[0]))
    header = [h.strip().lower() for h in next(reader)]
    idx = {key: next((header.index(a) for a in aliases if a in header), None) for key, aliases in COLUMNS.items()}
    missing = [k for k in REQUIRED if idx[k] is None]
    if missing:
        rep.errors.append("This does not look like a MyŠkoda trip export: missing column(s) "
                          + ", ".join(COLUMNS[k][0] for k in missing) + f". Found: {', '.join(header[:8])}…")
        return [], rep
    out: list[dict] = []
    for n, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        rep.rows += 1
        get = partial(_cell, row, idx)
        start, end = parse_local(get("start"), tz), parse_local(get("end"), tz)
        if start is None or end is None:
            rep.errors.append(f"line {n}: unreadable date {get('start')!r} / {get('end')!r}")
            continue
        if end < start:
            rep.errors.append(f"line {n}: the trip ends before it starts")
            continue
        km = _num(get("km"))
        if not km or km <= 0:
            rep.skipped_no_distance += 1  # engine-on / climate time without driving: not a trip
            continue
        slat, slon = _xy(get("start_xy"))
        elat, elon = _xy(get("end_xy"))
        kwh, kwh100 = _num(get("kwh")), _num(get("kwh100"))
        if kwh100 is None and kwh is not None and km >= 2:
            kwh100 = round(kwh / km * 100, 1)
        out.append({
            "line": n, "start": start, "end": end, "distance_km": km, "duration_min": _int(get("travel")),
            "driving_min": _int(get("driving")), "avg_speed_kmh": _num(get("speed")), "energy_kwh": kwh, "avg_kwh_100km": kwh100,
            "start_soc": _num(get("soc_start")), "end_soc": _num(get("soc_end")),
            "start_place": get("start_addr") or None, "end_place": get("end_addr") or None,
            "start_lat": slat, "start_lon": slon, "end_lat": elat, "end_lon": elon,
            "odo_start": _num(get("odo_start")), "odo_end": _num(get("odo_end")),
            "short_trip": 1 if get("short").lower() == "true" else 0,
            "public_stops": _int(get("stops")) or 0, "public_soc_gained": _num(get("gained")) or 0.0,
        })
    rep.parsed = len(out)
    if out:
        rep.first, rep.last = _iso(min(r["start"] for r in out)), _iso(max(r["start"] for r in out))
    return out, rep


def dedupe_upload(rows: list[dict]) -> tuple[list[dict], int]:
    """Rule 1: the same trip in several files (overlapping range exports, the full file plus a range) counts once."""
    seen, unique = set(), []
    for r in rows:
        key = (r["start"].replace(second=0, microsecond=0), r["end"].replace(second=0, microsecond=0), round(r["distance_km"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique, len(rows) - len(unique)


def _minutes(a: str, b: datetime) -> float:
    return abs((datetime.fromisoformat(a.replace("Z", "+00:00")) - b).total_seconds()) / 60


def find_match(conn, vid: int, r: dict, taken: set[int]) -> dict | None:
    """Rule 2: is there a stored trip that is this very trip? Returns the row or None."""
    lo, hi = _iso(r["start"] - timedelta(hours=12)), _iso(r["start"] + timedelta(hours=12))
    best, best_d = None, None
    for t in conn.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NOT NULL AND started_at BETWEEN ? AND ?", (vid, lo, hi)):
        if t["id"] in taken or not t["started_at"]:
            continue
        d0 = _minutes(t["started_at"], r["start"])
        by_time = d0 <= START_TOL_MIN and (_minutes(t["ended_at"], r["end"]) <= END_TOL_MIN
                                           or (t["distance_km"] is not None and abs(t["distance_km"] - r["distance_km"]) <= KM_TOL))
        by_odo = False
        a0, a1, b0, b1 = t["odo_start"], t["odo_end"], r["odo_start"], r["odo_end"]
        if a0 is not None and a1 is not None and b0 is not None and b1 is not None:
            shortest = min(a1 - a0, b1 - b0)
            by_odo = shortest > 0 and (min(a1, b1) - max(a0, b0)) / shortest >= 0.5
        if (by_time or by_odo) and (best_d is None or d0 < best_d):
            best, best_d = dict(t), d0
    return best


def _changes(t: dict, r: dict) -> dict:
    """The columns of a stored trip that the export would change (values compared with a tolerance for floats)."""
    want = {"distance_km": r["distance_km"], "energy_kwh": r["energy_kwh"], "start_soc": r["start_soc"], "end_soc": r["end_soc"],
            "odo_start": r["odo_start"], "odo_end": r["odo_end"], "start_place": r["start_place"], "end_place": r["end_place"],
            "duration_min": r["duration_min"], "avg_speed_kmh": r["avg_speed_kmh"], "avg_kwh_100km": r["avg_kwh_100km"],
            "driving_min": r["driving_min"], "public_stops": r["public_stops"], "public_soc_gained": r["public_soc_gained"],
            "short_trip": r["short_trip"], "start_lat": r["start_lat"], "start_lon": r["start_lon"],
            "end_lat": r["end_lat"], "end_lon": r["end_lon"]}
    out = {}
    for k, v in want.items():
        if v is None:
            continue  # the export does not know: keep what we have
        cur = t.get(k)
        if cur is None or (abs(cur - v) > 1e-6 if isinstance(v, (int, float)) and isinstance(cur, (int, float)) else cur != v):
            out[k] = v
    if t.get("energy_basis") != "car" and r["energy_kwh"] is not None:
        out["energy_basis"] = "car"
    if t.get("source") != "import":
        out["source"] = "import"
    if t.get("approx"):
        out["approx"] = 0
    return out


def _route(r: dict) -> str:
    pts = [{"lat": r["start_lat"], "lon": r["start_lon"], "place": r["start_place"], "soc": r["start_soc"]},
           {"lat": r["end_lat"], "lon": r["end_lon"], "place": r["end_place"], "soc": r["end_soc"]}]
    return json.dumps([p for p in pts if p["lat"] is not None])


def plan(conn, vid: int, rows: list[dict]) -> list[dict]:
    """For every unique row: what would happen. Pure reading; nothing is written."""
    taken: set[int] = set()
    actions = []
    for r in sorted(rows, key=lambda x: x["start"]):
        t = find_match(conn, vid, r, taken)
        if t is None:
            if merge.merged_part_matches(conn, vid, _iso(r["start"]), r["distance_km"]) is not None:
                # this row is one of the parts of a trip the user merged: known, never re-added
                actions.append({"row": r, "status": "unchanged", "match": None, "changes": None})
                continue
            actions.append({"row": r, "status": "new", "match": None, "changes": None})
            continue
        taken.add(t["id"])
        ch = _changes(t, r)
        derived = bool(t.get("approx")) or str(t.get("cloud_id", "")).startswith(("drv-", "odo-"))
        if derived:  # Mate's own times were estimates: the export's are exact
            ch["started_at"], ch["ended_at"] = _iso(r["start"]), _iso(r["end"])
        # provenance tags alone (source, energy_basis) do not make a trip "updated": it was already known
        real = {k for k in ch if k not in ("source", "energy_basis")}
        actions.append({"row": r, "status": "updated" if real else "unchanged", "match": t, "changes": ch})
    return actions


def apply(conn, vid: int, actions: list[dict]) -> dict:
    """Write the plan in one transaction. Returns counters. Never deletes; never touches a note."""
    counts = {"new": 0, "updated": 0, "unchanged": 0, "public_charges": 0}
    kwh_cap = recorder.battery_kwh(conn, vid)
    try:
        for a in actions:
            r = a["row"]
            if a["status"] == "new":
                conn.execute(
                    "INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km,duration_min,avg_speed_kmh,avg_kwh_100km,energy_kwh,"
                    "start_soc,end_soc,start_place,end_place,start_lat,start_lon,end_lat,end_lon,odo_start,odo_end,route_json,approx,"
                    "energy_basis,source,driving_min,public_stops,public_soc_gained,short_trip) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)",
                    (vid, f"csv-{_iso(r['start'])}", _iso(r["start"]), _iso(r["end"]), r["distance_km"], r["duration_min"], r["avg_speed_kmh"],
                     r["avg_kwh_100km"], r["energy_kwh"], r["start_soc"], r["end_soc"], r["start_place"], r["end_place"], r["start_lat"],
                     r["start_lon"], r["end_lat"], r["end_lon"], r["odo_start"], r["odo_end"], _route(r),
                     "car" if r["energy_kwh"] is not None else None, "import", r["driving_min"], r["public_stops"], r["public_soc_gained"], r["short_trip"]))
            elif a["changes"]:  # "updated", or "unchanged" apart from the provenance tags
                ch = a["changes"]
                cols = ", ".join(f"{k}=?" for k in ch)
                conn.execute(f"UPDATE trips SET {cols}, route_json=COALESCE(route_json, ?) WHERE id=?", (*ch.values(), _route(r), a["match"]["id"]))
            counts[a["status"]] += 1
            counts["public_charges"] += _public_charge(conn, vid, r, kwh_cap)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


def _public_charge(conn, vid: int, r: dict, kwh_cap: float | None) -> int:
    """A trip with public charging stops proves charging happened during it: record it once (key: vehicle + trip start)."""
    if not r["public_stops"] or not r["public_soc_gained"]:
        return 0
    started = _iso(r["start"])
    batt = round(r["public_soc_gained"] * kwh_cap / 100, 2) if kwh_cap else None
    wall = None if batt is None else round(batt / recorder.DEFAULT_EFFICIENCY, 2)
    where = f"Public charging on the way to {r['end_place']}" if r["end_place"] else "Public charging during a trip"
    existing = conn.execute("SELECT id FROM charges WHERE vehicle_id=? AND source='import-trip' AND started_at=?", (vid, started)).fetchone()
    if existing:
        conn.execute("UPDATE charges SET ended_at=?, energy_kwh=?, energy_battery_kwh=?, duration_min=? WHERE id=?",
                     (_iso(r["end"]), wall, batt, r["duration_min"], existing["id"]))
        return 0
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,energy_battery_kwh,duration_min,place_kind,address,source,note) "
                 "VALUES(?,?,?,?,?,?,'public',?,'import-trip',?)",
                 (vid, started, _iso(r["end"]), wall, batt, r["duration_min"], where,
                  f"{r['public_stops']} stop(s), +{r['public_soc_gained']:.0f} % in total, from the trip export"))
    return 1


def run(conn, vid: int, vin: str, files: list[dict], tz_name: str, dry_run: bool) -> dict:
    """files: [{name, text}]. Returns the report the dashboard shows. dry_run=True writes nothing."""
    if not files:
        raise ImportError_("Choose at least one CSV file.")
    tz = get_tz(tz_name)
    all_rows, reports = [], []
    for f in files:
        rows, rep = parse_file(str(f.get("name") or "file.csv")[:200], str(f.get("text") or ""), tz)
        if rep.vin and rep.vin != vin:  # another car's export: refuse it rather than mixing two cars' histories
            rep.errors.append(f"This export belongs to another car ({rep.vin[:3]}…{rep.vin[-4:]}), not this one. It was skipped.")
            rows = []
        all_rows += rows
        reports.append(rep)
    unique, dup_upload = dedupe_upload(all_rows)
    actions = plan(conn, vid, unique)
    counts = {"new": 0, "updated": 0, "unchanged": 0, "public_charges": 0}
    inferred = 0
    if dry_run:
        for a in actions:
            counts[a["status"]] += 1
        counts["public_charges"] = sum(1 for a in actions if a["row"]["public_stops"] and a["row"]["public_soc_gained"])
    elif actions:
        counts = apply(conn, vid, actions)
        inferred = recorder.infer_charges(conn, vid, days=3650)  # overnight charges can now be read off the whole history
        places.assign_all(conn)  # link every written trip to the places its coordinates fall in
    skipped = sum(r.skipped_no_distance for r in reports)
    preview = [{"start": _iso(a["row"]["start"]), "from": a["row"]["start_place"], "to": a["row"]["end_place"], "km": a["row"]["distance_km"],
                "kwh": a["row"]["energy_kwh"], "status": a["status"]} for a in actions[-12:][::-1]]
    return {"dry_run": dry_run, "timezone": tz_name, "files": [r.__dict__ for r in reports], "unique": len(unique),
            "duplicates_in_upload": dup_upload, "skipped_no_distance": skipped, **counts, "charges_inferred": inferred,
            "first": _iso(min(a["row"]["start"] for a in actions)) if actions else None,
            "last": _iso(max(a["row"]["start"] for a in actions)) if actions else None,
            "km": round(sum(a["row"]["distance_km"] for a in actions), 1), "preview": preview}
