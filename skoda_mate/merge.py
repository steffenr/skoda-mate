"""Merging trips that a short stop split apart, and undoing it.

A merge keeps the first trip's row (so its id, note and links stay) and stores the original rows in `merged_json`.
The importer consults `merged_json`, so importing the same CSV again does not bring the parts back."""
from __future__ import annotations

import json
from datetime import datetime

from . import places

MAX_GAP_H = 6.0
MAX_PARTS = 12
PART_COLS = ("cloud_id", "started_at", "ended_at", "distance_km", "duration_min", "avg_speed_kmh", "avg_kwh_100km", "energy_kwh", "start_soc",
             "end_soc", "start_place", "end_place", "start_lat", "start_lon", "end_lat", "end_lon", "odo_start", "odo_end", "note", "approx",
             "energy_basis", "source", "driving_min", "short_trip", "public_stops", "public_soc_gained", "route_json")


class MergeError(ValueError):
    pass


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _sum(parts, k):
    vals = [p[k] for p in parts if p.get(k) is not None]
    return round(sum(vals), 2) if vals else None


def merge(conn, vid: int, ids: list[int]) -> int:
    """Merge the given trips into the earliest one. Returns its id."""
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not 2 <= len(ids) <= MAX_PARTS:
        raise MergeError(f"Choose between 2 and {MAX_PARTS} trips.")
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM trips WHERE vehicle_id=? AND id IN ({','.join('?' * len(ids))})", (vid, *ids))]
    if len(rows) != len(ids):
        raise MergeError("One of the trips does not exist.")
    if any(r["ended_at"] is None or not r["started_at"] for r in rows):
        raise MergeError("A trip that is still running cannot be merged.")
    rows.sort(key=lambda r: r["started_at"])
    for a, b in zip(rows, rows[1:], strict=False):
        gap = (_dt(b["started_at"]) - _dt(a["ended_at"])).total_seconds() / 3600
        if gap < -0.05:
            raise MergeError("These trips overlap in time.")
        if gap > MAX_GAP_H:
            raise MergeError(f"These trips are more than {MAX_GAP_H:.0f} hours apart: that was a separate trip.")
    first, last = rows[0], rows[-1]
    parts: list[dict] = []
    for r in rows:
        merged_before = json.loads(r["merged_json"]) if r.get("merged_json") else None
        parts += merged_before if merged_before else [{k: r.get(k) for k in PART_COLS}]
    km = _sum(rows, "distance_km")
    kwh = _sum(rows, "energy_kwh")
    minutes = max(1, round((_dt(last["ended_at"]) - _dt(first["started_at"])).total_seconds() / 60))
    notes = " · ".join(dict.fromkeys(r["note"].strip() for r in rows if r.get("note") and r["note"].strip())) or None
    route = [p for p in (json.loads(r["route_json"]) if r.get("route_json") else [] for r in rows) for p in p]
    new = {
        "ended_at": last["ended_at"], "distance_km": km, "duration_min": minutes,
        "avg_speed_kmh": round(km / minutes * 60, 1) if km else None, "energy_kwh": kwh,
        "avg_kwh_100km": round(kwh / km * 100, 1) if kwh and km and km >= 2 else None,
        "end_soc": last["end_soc"], "end_place": last["end_place"], "end_lat": last["end_lat"], "end_lon": last["end_lon"],
        "odo_end": last["odo_end"], "driving_min": _sum(rows, "driving_min"), "note": notes,
        "public_stops": int(_sum(rows, "public_stops") or 0), "public_soc_gained": _sum(rows, "public_soc_gained") or 0,
        "short_trip": 0, "route_json": json.dumps(route[:1] + route[-1:]) if route else None,
        "approx": 1 if any(r.get("approx") for r in rows) else 0, "merged_json": json.dumps(parts),
    }
    cols = ", ".join(f"{k}=?" for k in new)
    try:
        conn.execute(f"UPDATE trips SET {cols} WHERE id=?", (*new.values(), first["id"]))
        conn.execute(f"DELETE FROM trips WHERE id IN ({','.join('?' * (len(rows) - 1))})", [r["id"] for r in rows[1:]])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    places.assign_all(conn)  # the merged row now ends where the last part ended
    return first["id"]


def unmerge(conn, vid: int, trip_id: int) -> list[int]:
    """Restore the original trips. The merged row becomes the first part again; notes typed on the merged trip stay on it."""
    t = conn.execute("SELECT * FROM trips WHERE id=? AND vehicle_id=?", (trip_id, vid)).fetchone()
    if not t or not t["merged_json"]:
        raise MergeError("This trip was not merged.")
    parts = json.loads(t["merged_json"])
    ids = [t["id"]]
    try:
        for i, p in enumerate(parts):
            if i == 0:
                sets = {k: p.get(k) for k in PART_COLS if k != "note"}
                sets["merged_json"] = None
                conn.execute(f"UPDATE trips SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), t["id"]))
            else:
                cols = ["vehicle_id", *[k for k in PART_COLS if p.get(k) is not None]]
                cur = conn.execute(f"INSERT INTO trips({','.join(cols)}) VALUES({','.join('?' * len(cols))})", (vid, *[p[k] for k in cols[1:]]))
                ids.append(cur.lastrowid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    places.assign_all(conn)  # the restored parts carry their own coordinates again
    return ids


def merged_part_matches(conn, vid: int, start_iso: str, km: float, start_tol_min: float = 3, km_tol: float = 2.0):
    """For the importer: is this CSV row one of the parts of a merged trip? Returns the merged trip's id or None."""
    s = _dt(start_iso)
    for t in conn.execute("SELECT id, merged_json FROM trips WHERE vehicle_id=? AND merged_json IS NOT NULL", (vid,)):
        for p in json.loads(t["merged_json"]):
            if p.get("started_at") and abs((_dt(p["started_at"]) - s).total_seconds()) / 60 <= start_tol_min \
                    and p.get("distance_km") is not None and abs(p["distance_km"] - km) <= km_tol:
                return t["id"]
    return None
