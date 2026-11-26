"""Named places: geofences the car's trips and charges are matched to.

Matching is a local haversine over the stored geofences; assignment writes the result onto the trip or charge, so
filters, costs and the map never repeat the spatial query. There is no FastAPI here: the router turns the `status`
of a `PlaceError` into an HTTP response.
"""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from datetime import datetime

from . import costs

KINDS = ("home", "work", "place")
MIN_RADIUS_M = 20
MAX_RADIUS_M = 5000
# The chart palette the dashboard offers for a place colour.
COLORS = ("#0b7a52", "#1d5fa8", "#b86e00", "#7a3fa8", "#b3261e", "#0e7a7a")

DETAIL_CHARGE_LIMIT = 100


class PlaceError(ValueError):
    """A place request the API answers with this plain message and `status`."""
    status = 400


class PlaceNotFound(PlaceError):
    status = 404


class PlaceConflict(PlaceError):
    status = 409


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _hours(a: str, b: str) -> float:
    return (_dt(b) - _dt(a)).total_seconds() / 3600


def _clamp_radius(radius_m: int) -> int:
    return max(MIN_RADIUS_M, min(MAX_RADIUS_M, int(radius_m)))


def _order_key(place: dict) -> tuple[int, str, int]:
    kind = place.get("kind")
    rank = KINDS.index(kind) if kind in KINDS else len(KINDS)
    return rank, str(place.get("name") or "").casefold(), int(place["id"])


def _total(values) -> float | None:
    """Sum optional numbers. A single unknown value makes the total unknown, never silently zero."""
    vals = list(values)
    if any(v is None for v in vals):
        return None
    return sum(vals)


def _ranked(places: list[dict]) -> list[dict]:
    """Smallest radius first; equal radii fall back to the lower id."""
    return sorted(places, key=lambda p: (int(p["radius_m"]), int(p["id"])))


def _match_ranked(ranked: list[dict], lat, lon) -> dict | None:
    if lat is None or lon is None:
        return None
    for place in ranked:
        if costs.distance_m(lat, lon, place["lat"], place["lon"]) <= place["radius_m"]:
            return place
    return None


def list_places(conn) -> list[dict]:
    """Every place: home first, then work and other places, each group by name."""
    places = [dict(r) for r in conn.execute("SELECT * FROM geofences")]
    places.sort(key=_order_key)
    return places


def get(conn, place_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM geofences WHERE id=?", (place_id,)).fetchone()
    return dict(row) if row else None


def match(conn, lat, lon, places: list[dict] | None = None) -> dict | None:
    """The place a point belongs to: the smallest overlapping radius, then the lower id."""
    ranked = _ranked(places if places is not None else list_places(conn))
    return _match_ranked(ranked, lat, lon)


def _match_id(ranked: list[dict], lat, lon) -> int | None:
    place = _match_ranked(ranked, lat, lon)
    return place["id"] if place else None


def assign_all(conn) -> dict[str, int]:
    """Recompute every trip and charge link from the current places; returns the rows that changed."""
    ranked = _ranked(list_places(conn))
    trips_changed = 0
    query = ("SELECT id, start_lat, start_lon, end_lat, end_lon, start_geofence_id, end_geofence_id FROM trips")
    for trip in conn.execute(query):
        start = _match_id(ranked, trip["start_lat"], trip["start_lon"])
        end = _match_id(ranked, trip["end_lat"], trip["end_lon"])
        changes, values = [], []
        if start != trip["start_geofence_id"]:
            changes.append("start_geofence_id=?")
            values.append(start)
        if end != trip["end_geofence_id"]:
            changes.append("end_geofence_id=?")
            values.append(end)
        if changes:
            conn.execute(f"UPDATE trips SET {', '.join(changes)} WHERE id=?", (*values, trip["id"]))
            trips_changed += 1
    charges_changed = 0
    for charge in conn.execute("SELECT id, lat, lon, geofence_id FROM charges"):
        place_id = _match_id(ranked, charge["lat"], charge["lon"])
        if place_id != charge["geofence_id"]:
            conn.execute("UPDATE charges SET geofence_id=? WHERE id=?", (place_id, charge["id"]))
            charges_changed += 1
    conn.commit()
    return {"trips": trips_changed, "charges": charges_changed}


def _summary(conn, place: dict, tz_offset: int = 0) -> dict:
    """All place fields plus visit, day and charge counts and the latest time the car was seen there."""
    visits = conn.execute(
        "SELECT COUNT(*) n, COUNT(DISTINCT substr(datetime(ended_at, ?), 1, 10)) d, MAX(ended_at) last "
        "FROM trips WHERE end_geofence_id=?", (f"{-int(tz_offset):+d} minutes", place["id"])).fetchone()
    charges = conn.execute(
        "SELECT COUNT(*) n, MAX(ended_at) last FROM charges WHERE geofence_id=?",
        (place["id"],)).fetchone()
    last_seen = max((x for x in (visits["last"], charges["last"]) if x), default=None)
    out = dict(place)
    out.update({"visit_count": visits["n"], "day_count": visits["d"], "charge_count": charges["n"],
                "last_seen": last_seen})
    return out


def summaries(conn, tz_offset: int = 0) -> list[dict]:
    """Every place with its counts, the days counted in the given local offset."""
    return [_summary(conn, place, tz_offset) for place in list_places(conn)]


def create(conn, data: dict) -> dict:
    """Insert one place with defaults for omitted optional fields, link existing rows and return its summary."""
    name = str(data.get("name") or "").strip()
    kind = str(data.get("kind") or "place")
    radius = data.get("radius_m")
    radius = 150 if radius is None else int(radius)
    try:
        cur = conn.execute(
            "INSERT INTO geofences(name,kind,lat,lon,radius_m,color,price_kwh,price_minute,session_fee,free) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (name, kind, float(data["lat"]), float(data["lon"]), radius, data.get("color"), data.get("price_kwh"),
             data.get("price_minute"), data.get("session_fee"), int(bool(data.get("free")))))
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if "geofences.kind" in str(e) or "idx_geofences_one_home" in str(e):
            raise PlaceConflict("Only one home place is allowed.") from None
        raise
    place_id = cur.lastrowid
    conn.commit()
    assign_all(conn)
    return _summary(conn, dict(conn.execute("SELECT * FROM geofences WHERE id=?", (place_id,)).fetchone()))


def update(conn, place_id: int, data: dict) -> dict:
    """Replace the fields present in `data`, enforce the one-home rule, reassign and return the summary."""
    current = get(conn, place_id)
    if current is None:
        raise PlaceNotFound("Place not found.")
    kind = str(data.get("kind") or "place") if "kind" in data else current["kind"]
    if current["kind"] == "home" and kind != "home":
        raise PlaceError("The home place cannot change its kind.")
    if kind == "home" and current["kind"] != "home":
        other = conn.execute("SELECT 1 FROM geofences WHERE kind='home' AND id<>? LIMIT 1", (place_id,)).fetchone()
        if other:
            raise PlaceConflict("Only one home place is allowed.")
    changes: dict = {}
    if "name" in data:
        changes["name"] = str(data["name"] or "").strip()
    if "kind" in data:
        changes["kind"] = kind
    for field in ("lat", "lon"):
        if field in data:
            changes[field] = float(data[field])
    if "radius_m" in data:
        changes["radius_m"] = int(data["radius_m"])
    for field in ("color", "price_kwh", "price_minute", "session_fee"):
        if field in data:
            changes[field] = data[field]
    if "free" in data:
        changes["free"] = int(bool(data["free"]))
    sets = [f"{field}=?" for field in changes]
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%S+00:00','now')")
    try:
        conn.execute(f"UPDATE geofences SET {', '.join(sets)} WHERE id=?", (*changes.values(), place_id))
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if "geofences.kind" in str(e) or "idx_geofences_one_home" in str(e):
            raise PlaceConflict("Only one home place is allowed.") from None
        raise
    conn.commit()
    assign_all(conn)
    return _summary(conn, dict(conn.execute("SELECT * FROM geofences WHERE id=?", (place_id,)).fetchone()))


def delete(conn, place_id: int) -> dict[str, int]:
    """Delete a non-home place, clearing links in one transaction, and return how many rows were unlinked."""
    place = get(conn, place_id)
    if place is None:
        raise PlaceNotFound("Place not found.")
    if place["kind"] == "home":
        raise PlaceError("The home place cannot be deleted.")
    trips = conn.execute("SELECT COUNT(*) FROM trips WHERE start_geofence_id=? OR end_geofence_id=?",
                         (place_id, place_id)).fetchone()[0]
    charges = conn.execute("SELECT COUNT(*) FROM charges WHERE geofence_id=?", (place_id,)).fetchone()[0]
    try:
        conn.execute("UPDATE charges SET geofence_id=NULL WHERE geofence_id=?", (place_id,))
        conn.execute("UPDATE trips SET start_geofence_id=NULL WHERE start_geofence_id=?", (place_id,))
        conn.execute("UPDATE trips SET end_geofence_id=NULL WHERE end_geofence_id=?", (place_id,))
        conn.execute("DELETE FROM geofences WHERE id=?", (place_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"trips": trips, "charges": charges}


def upsert_home(conn, lat: float, lon: float, radius_m: int | None = None, name: str = "Home") -> dict:
    """Move or resize the one home place, creating it (150 m) when none exists; never a second home."""
    radius = None if radius_m is None else _clamp_radius(radius_m)
    home = conn.execute("SELECT id FROM geofences WHERE kind='home' ORDER BY id LIMIT 1").fetchone()
    if home is None:
        cur = conn.execute("INSERT INTO geofences(name,kind,lat,lon,radius_m) VALUES(?,?,?,?,?)",
                           (str(name or "Home").strip(), "home", float(lat), float(lon),
                            150 if radius is None else radius))
        place_id = cur.lastrowid
    else:
        place_id = home["id"]
        sets = ["lat=?", "lon=?", "updated_at=strftime('%Y-%m-%dT%H:%M:%S+00:00','now')"]
        values: list = [float(lat), float(lon)]
        if radius is not None:
            sets.append("radius_m=?")
            values.append(radius)
        values.append(place_id)
        conn.execute(f"UPDATE geofences SET {', '.join(sets)} WHERE id=?", values)
    conn.commit()
    assign_all(conn)
    return _summary(conn, dict(conn.execute("SELECT * FROM geofences WHERE id=?", (place_id,)).fetchone()))


def _trip_starts(conn, trips: list[dict]) -> dict[int, list[str]]:
    """Per vehicle, every trip start in order: a visit ends at the next departure of the same car."""
    vids = sorted({trip["vehicle_id"] for trip in trips})
    out: dict[int, list[str]] = {}
    if not vids:
        return out
    marks = ",".join("?" * len(vids))
    rows = list(conn.execute(f"SELECT vehicle_id, started_at FROM trips WHERE vehicle_id IN ({marks}) "
                             "AND started_at IS NOT NULL", vids))
    rows.sort(key=lambda row: _dt(row["started_at"]))
    for row in rows:
        out.setdefault(row["vehicle_id"], []).append(row["started_at"])
    return out


def detail(conn, place_id: int, now_iso: str, tz_offset: int = 0) -> dict | None:
    """One place with its visits, its latest charges and their totals; `None` when the id is unknown."""
    place = get(conn, place_id)
    if place is None:
        return None
    out = _summary(conn, place, tz_offset)
    trips = [dict(r) for r in conn.execute(
        "SELECT id, vehicle_id, ended_at FROM trips WHERE end_geofence_id=? AND ended_at IS NOT NULL "
        "ORDER BY ended_at, id", (place_id,))]
    starts = _trip_starts(conn, trips)
    visits = []
    for trip in trips:
        raw_starts = starts.get(trip["vehicle_id"], [])
        departures = [_dt(start) for start in raw_starts]
        index = bisect_right(departures, _dt(trip["ended_at"]))
        next_start = raw_starts[index] if index < len(raw_starts) else None
        left_at = None
        minutes = None
        open_visit = next_start is None
        if next_start is None:
            minutes = max(0, round(_hours(trip["ended_at"], now_iso) * 60))
        else:
            left_at = next_start
            minutes = max(0, round(_hours(trip["ended_at"], next_start) * 60))
        visits.append({"arrived_at": trip["ended_at"], "left_at": left_at, "minutes": minutes,
                       "open": open_visit, "trip_id": trip["id"]})
    visits.reverse()
    tariff = costs.load_tariff(conn)
    charges = [dict(r) for r in conn.execute(
        "SELECT * FROM charges WHERE geofence_id=? ORDER BY started_at DESC, id DESC", (place_id,))]
    recent: list[dict] = []
    amounts: list = []
    energies: list = []
    for charge in charges:
        cc = costs.charge_cost(charge, tariff, place)
        amounts.append(cc["amount"])
        energies.append(charge["energy_kwh"])
        if len(recent) < DETAIL_CHARGE_LIMIT:
            recent.append({**charge, "cost": cc["amount"], "cost_basis": cc["basis"],
                           "place_kind_resolved": cc["kind"]})
    parked = _total(visit["minutes"] for visit in visits)
    charged = _total(energies)
    total = _total(amounts)
    out.update({"visits": visits, "charges": recent,
                "parked_minutes": None if parked is None else int(parked),
                "charged_kwh": None if charged is None else round(charged, 2),
                "cost": None if total is None else round(total, 2),
                "currency": tariff["currency"]})
    return out
