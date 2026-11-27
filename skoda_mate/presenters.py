"""Row -> JSON shaping, and the filters/resolvers the routers share.

Kept apart from the routers so the same rule (a missing value stays null, a date filter means the local day, a CSV cell
cannot start a formula) is applied in one place. Nothing here talks to FastAPI's request cycle except the 400 that
`local_bound` raises for a malformed date.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException

from . import costs, places, recorder

INFERRED_SOURCES = ("inferred", "import-trip")  # charges that were read off other data, not measured while charging
TYPICAL_WALLBOX_KW = 11.0  # a home AC charger: only used to say how long an inferred charge probably took
HIDDEN_SECTIONS = {"raw", "operations", "part_state", "api_errors"}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

BOOL_COLS = ("charging", "locked", "doors_open", "windows_open", "trunk_open", "bonnet_open", "sunroof_open", "lights_on",
             "plug_connected", "plug_locked", "in_motion", "reachable", "ignition_on", "battery_protection")


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def vehicle(conn, vid: int) -> dict:
    """One vehicle row, or the 404 every /api/vehicles/{vid}/... route answers with."""
    v = conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not v:
        raise HTTPException(404, "no such vehicle")
    return dict(v)


def snap_out(row) -> dict | None:
    """A snapshot row for the dashboard: SQLite stores booleans as 0/1 (NULL = the car did not say); send real
    true/false/null so the UI can tell 'unknown' from 'false'."""
    if row is None:
        return None
    d = dict(row)
    for c in BOOL_COLS:
        if d.get(c) is not None:
            d[c] = bool(d[c])
    return d


def local_day(day: str) -> date:
    """A local YYYY-MM-DD date; the one message a malformed date gets, shared by the filters and the timeline."""
    try:
        return date.fromisoformat(day)
    except ValueError:
        raise ValueError(f"bad date {day!r}, expected YYYY-MM-DD") from None


def local_bound(day: str | None, tz_offset: int = 0, end: bool = False) -> str | None:
    """A date filter from the browser -> a UTC ISO string comparable with the stored timestamps.

    `day` is a local date (YYYY-MM-DD), a full ISO datetime with a `T` (passed through), or the space-separated form
    `YYYY-MM-DD HH:MM` (a local time, shifted into UTC like a date); `tz_offset` is JS `getTimezoneOffset()` (minutes,
    UTC minus local). A `to` date means "through the end of that day", so its bound is the next local midnight."""
    if not day:
        return None
    if "T" in day:
        return day
    try:
        parsed = datetime.combine(local_day(day), datetime.min.time())
    except ValueError as e:
        try:
            parsed = datetime.fromisoformat(day)
        except ValueError:
            raise HTTPException(400, str(e)) from None
    d = parsed + timedelta(days=1 if end else 0, minutes=tz_offset)
    return d.replace(tzinfo=UTC).isoformat()


def csv_cell(v):
    """A CSV export value. Text that a spreadsheet would run as a formula (a note or place name starting with "=",
    "+", "-", "@", tab or CR) gets a leading apostrophe; numbers, including negative ones, are left as they are."""
    if v is None:
        return ""
    if isinstance(v, str) and v.startswith(FORMULA_START):
        return "'" + v
    return v


def redact(raw: dict) -> dict:
    """A copy of the raw API answer that is safe to attach to a bug report."""
    d = json.loads(json.dumps(raw))
    v = d.get("vehicle") or {}
    if v.get("vin"):
        v["vin"] = v["vin"][:3] + "*" * 11 + v["vin"][-3:]
    for k in ("licensePlate", "name", "renderUrl"):
        if k in v:
            v[k] = "<redacted>"
    pos = v.get("parkingPosition") or {}
    if "gpsCoordinates" in pos:
        pos["gpsCoordinates"] = {"latitude": None, "longitude": None, "note": "redacted"}
    if "formattedAddress" in pos:
        pos["formattedAddress"] = "<redacted>"
    cp = v.get("chargingProfiles") or {}
    for p in cp.get("profiles", []):
        p["name"] = "<redacted>"  # profile names are user-chosen and often a place ("Home", "Office")
    if isinstance(cp.get("currentVehiclePositionProfile"), dict):
        cp["currentVehiclePositionProfile"]["name"] = "<redacted>"
    return d


def curve_gaps(curve: list[dict], estimated_end: str | None) -> list[dict]:
    """Stretches of a charge without readings, which the curve leaves open instead of drawing a line across: holes
    longer than recorder.MAX_GAP_H between two readings, and the time from the last reading to an estimated end."""
    gaps = [{"from": a["t"], "to": b["t"]} for a, b in zip(curve, curve[1:], strict=False)
            if recorder._hours(a["t"], b["t"]) > recorder.MAX_GAP_H]
    if estimated_end and curve and curve[-1]["t"] < estimated_end:
        gaps.append({"from": curve[-1]["t"], "to": estimated_end})
    return gaps


def trip_out(t: dict, tariff: dict, detail: bool = False) -> dict:
    t["cost"] = costs.trip_cost(t, tariff)
    route = t.pop("route_json", None)
    if detail:
        t["route"] = json.loads(route) if route else []
    t["open"] = t["ended_at"] is None
    mj = t.pop("merged_json", None)
    t["merged_parts"] = len(json.loads(mj)) if mj else 0
    return t


def charge_out(c: dict, tariff: dict, conn) -> dict:
    place = places.get(conn, c["geofence_id"]) if c.get("geofence_id") else None
    cc = costs.charge_cost(c, tariff, place)
    c["cost"], c["cost_basis"], c["place_kind_resolved"] = cc["amount"], cc["basis"], cc["kind"]
    c["place"] = {"id": place["id"], "name": place["name"], "kind": place["kind"]} if place else None
    c["open"] = c["ended_at"] is None
    c["inferred"] = c.get("source") in INFERRED_SOURCES  # read off the battery level / a trip export, not measured live
    # A charge imported from a trip export knows only how much the level ROSE, not the levels before and after.
    c["soc_gained"] = None
    if c.get("source") == "import-trip":
        g = conn.execute("SELECT public_soc_gained FROM trips WHERE vehicle_id=? AND started_at=?",
                         (c["vehicle_id"], c["started_at"])).fetchone()
        c["soc_gained"] = g["public_soc_gained"] if g else None
    # Average power only means something when the duration is the time spent charging. For an inferred charge the
    # "duration" is the whole window the car stood there (e.g. overnight), so energy / window would be nonsense
    # (2 kW for a charger that really ran at 11 kW). Say how long it takes at a typical wallbox instead.
    c["avg_power_kw"] = (None if c["inferred"] else round(c["energy_kwh"] / (c["duration_min"] / 60), 1)
                         if c.get("duration_min") and c.get("energy_kwh") else None)
    c["max_power_kw"] = None if c["inferred"] else c.get("max_power_kw")
    c["hours_at_typical_wallbox"] = round(c["energy_kwh"] / TYPICAL_WALLBOX_KW, 1) if c["inferred"] and c.get("energy_kwh") else None
    c["typical_wallbox_kw"] = TYPICAL_WALLBOX_KW
    c["inferred_reason"] = inferred_reason(conn, c) if c["inferred"] and c.get("source") == "inferred" else None
    return c


def inferred_reason(conn, c: dict) -> str:
    """Why Mate never saw this charge live: it was not recording yet, or it had no poll / no charging poll in the window."""
    row = conn.execute("SELECT MIN(recorded_at) first FROM snapshots WHERE vehicle_id=?", (c["vehicle_id"],)).fetchone()
    end = c.get("ended_at") or c["started_at"]
    if not row["first"] or row["first"] > end:
        return "before_recording"
    n = conn.execute("SELECT COUNT(*) FROM snapshots WHERE vehicle_id=? AND recorded_at BETWEEN ? AND ?",
                     (c["vehicle_id"], c["started_at"], end)).fetchone()[0]
    return "no_polls" if n == 0 else "not_charging"
