"""The events MQTT and webhooks are told about.

`collect()` turns what one reading changed into named events with their data. It reads the rows the recorder just
wrote, so only what a live poll produced is ever reported: inferred charges, imports and repairs write no such rows.
Event data names places by their geofence only; it carries no coordinates, addresses or secrets.
"""
from __future__ import annotations

import uuid

from . import activity, costs, places  # `activity` imports the recorder, which imports this: use it by module
from .store import get_setting

# Grouped as the Automation card shows them.
EVENT_GROUPS = (
    ("Driving", ("trip.started", "trip.ended")),
    ("Charging", ("charge.started", "charge.ended", "charge.completed", "plug.connected", "plug.disconnected", "soc.low")),
    ("Climate", ("climate.started", "climate.ended")),
    ("Security", ("doors.opened", "windows.opened")),
    ("Places", ("geofence.entered", "geofence.left")),
    ("System", ("poll.failed",)),
)
EVENT_TYPES = tuple(name for _, names in EVENT_GROUPS for name in names)

POLL_FAILURES = 3  # `poll.failed` fires at this many failed readings in a row, once until one succeeds
SOC_LOW_KEY = "soc_low_pct"
SOC_LOW_DEFAULT = 20
SOC_LOW_RANGE = (5, 50)

_SIMPLE = {"plugged_in": "plug.connected", "unplugged": "plug.disconnected", "door_opened": "doors.opened",
           "window_opened": "windows.opened"}


def soc_low_threshold(conn) -> int:
    try:
        value = int(get_setting(conn, SOC_LOW_KEY) or SOC_LOW_DEFAULT)
    except ValueError:
        return SOC_LOW_DEFAULT
    return value if SOC_LOW_RANGE[0] <= value <= SOC_LOW_RANGE[1] else SOC_LOW_DEFAULT


def collect(conn, vid: int, since_event_id: int, prev, snap: dict, snap_id: int) -> list[dict]:
    """The events of the reading `snap`: `[{event, at, data}]`. `since_event_id` is the newest event row before it was
    stored and `prev` the reading before it (None for a car's first one, which has nothing to compare with)."""
    if prev is None:
        return []
    out: list[dict] = []
    rows = conn.execute("SELECT at, kind, detail FROM events WHERE vehicle_id=? AND id>? ORDER BY id",
                        (vid, since_event_id)).fetchall()
    for row in rows:
        kind, at = row["kind"], row["at"]
        if kind in _SIMPLE:
            out.append(_event(_SIMPLE[kind], at))
        elif kind == "climate":
            out.extend(_climate(row["detail"], at))
        elif kind in ("charge_start", "charge_end"):
            out.extend(_charge(conn, vid, kind, at))
        elif kind in ("trip_start", "trip_end"):
            out.extend(_trip(conn, vid, kind, at))
    out.extend(_soc_low(conn, vid, snap, snap_id))
    return out


def envelope(conn, vid: int, event: dict) -> dict:
    """An event as consumers get it. The id is new for every event, so a repeated delivery can be recognised."""
    car = conn.execute("SELECT name, vin FROM vehicles WHERE id=?", (vid,)).fetchone()
    return {"id": uuid.uuid4().hex, "event": event["event"], "at": event["at"],
            "vehicle": {"id": vid, "name": car["name"] or car["vin"], "vin": car["vin"]}, "data": event["data"]}


def _event(name: str, at: str, **data) -> dict:
    return {"event": name, "at": at, "data": data}


def _climate(detail: str | None, at: str) -> list[dict]:
    old, _, new = (detail or "").partition(" -> ")
    was, is_ = old in activity.heating_states(), new in activity.heating_states()
    if was == is_:
        return []
    return [_event("climate.started" if is_ else "climate.ended", at, state=new)]


def _name(conn, place_id) -> str | None:
    place = places.get(conn, place_id) if place_id else None
    return place["name"] if place else None


def _kwh(value) -> float | None:
    return None if value is None else round(value, 2)


def _charge(conn, vid: int, kind: str, at: str) -> list[dict]:
    column = "started_at" if kind == "charge_start" else "ended_at"
    row = conn.execute(f"SELECT * FROM charges WHERE vehicle_id=? AND {column}=? AND COALESCE(source,'detected')='detected' "
                       "ORDER BY id DESC LIMIT 1", (vid, at)).fetchone()
    if row is None:
        return []
    c = dict(row)
    place = places.get(conn, c["geofence_id"]) if c.get("geofence_id") else None
    data = {"charge_id": c["id"], "charge_type": c["charge_type"], "start_soc": c["start_soc"],
            "target_soc": c["target_soc"], "place": place["name"] if place else None}
    if kind == "charge_start":
        return [_event("charge.started", at, **data)]
    data.update(end_soc=c["end_soc"], energy_kwh=_kwh(c["energy_kwh"]),
                cost=(costs.charge_cost(c, costs.load_tariff(conn), place) or {}).get("amount"))
    out = [_event("charge.ended", at, **data)]
    if c["target_soc"] is not None and c["end_soc"] is not None and c["end_soc"] >= c["target_soc"]:
        out.append(_event("charge.completed", at, **data))
    return out


def _trip(conn, vid: int, kind: str, at: str) -> list[dict]:
    column = "started_at" if kind == "trip_start" else "ended_at"
    t = conn.execute(f"SELECT * FROM trips WHERE vehicle_id=? AND {column}=? ORDER BY id DESC LIMIT 1", (vid, at)).fetchone()
    if t is None:
        return []
    start = _name(conn, t["start_geofence_id"])
    if kind == "trip_start":
        return [_event("trip.started", at, trip_id=t["id"], start_place=start, start_soc=t["start_soc"])]
    out = [_event("trip.ended", at, trip_id=t["id"], start_place=start, end_place=_name(conn, t["end_geofence_id"]),
                  distance_km=None if t["distance_km"] is None else round(t["distance_km"], 1),
                  energy_kwh=_kwh(t["energy_kwh"]), start_soc=t["start_soc"], end_soc=t["end_soc"],
                  approx=bool(t["approx"]))]
    return out + _places(conn, vid, t, at)


def _places(conn, vid: int, trip, at: str) -> list[dict]:
    """Where the car stopped compared with where it stopped before, so passing through a place fires nothing."""
    before = conn.execute("SELECT end_geofence_id FROM trips WHERE vehicle_id=? AND id!=? AND ended_at IS NOT NULL "
                          "AND ended_at<=? ORDER BY ended_at DESC, id DESC LIMIT 1", (vid, trip["id"], at)).fetchone()
    old = before["end_geofence_id"] if before else trip["start_geofence_id"]
    new = trip["end_geofence_id"]
    if old == new:
        return []
    return [_event(name, at, place_id=pid, place=_name(conn, pid))
            for name, pid in (("geofence.left", old), ("geofence.entered", new)) if pid]


def _soc_low(conn, vid: int, snap: dict, snap_id: int) -> list[dict]:
    soc = snap.get("soc")
    if soc is None:
        return []
    last = conn.execute("SELECT soc FROM snapshots WHERE vehicle_id=? AND id<? AND soc IS NOT NULL "
                        "ORDER BY recorded_at DESC, id DESC LIMIT 1", (vid, snap_id)).fetchone()
    threshold = soc_low_threshold(conn)
    if last is None or not (last["soc"] >= threshold > soc):
        return []
    return [_event("soc.low", snap["ts"], soc=soc, threshold=threshold)]
