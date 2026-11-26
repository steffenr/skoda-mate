"""Turns a stream of snapshots into events, charge sessions and trips.

The official API has no trip or charging history, so both are DERIVED here from what each poll reports:
* charges: `charging.status.state == CHARGING` plus `chargePowerInKw` integrated over time;
* trips: `parkingPosition.state` IN_MOTION/PARKED and odometer changes.
Pure logic over a sqlite connection (no network), so it is fully testable. Everything derived is honest
about its precision: times are accurate to the poll interval, trips found only through an odometer jump
carry `approx=1`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from . import places
from .store import set_setting

MAX_GAP_H = 1.0  # never integrate power over a longer hole than this
STALE_CHARGE_H = 3.0  # an open charge with no CHARGING snapshot for this long is closed
STALE_TRIP_H = 6.0  # an open trip older than this is closed even without a definite PARKED
MIN_TRIP_KM = 0.5  # shorter movements are GPS/odometer noise
MAX_PLAUSIBLE_KMH = 250.0  # an odometer jump implying more than this average speed is not a trip
GUESS_KMH = 45.0  # to place an odometer-jump trip in time when nothing else is known

EVENT_FLAGS = (("locked", "locked", "unlocked"), ("doors_open", "door_opened", "door_closed"),
               ("windows_open", "window_opened", "window_closed"), ("trunk_open", "trunk_opened", "trunk_closed"),
               ("bonnet_open", "bonnet_opened", "bonnet_closed"), ("sunroof_open", "sunroof_opened", "sunroof_closed"),
               ("lights_on", "lights_on", "lights_off"), ("plug_connected", "plugged_in", "unplugged"),
               ("plug_locked", "plug_locked", "plug_unlocked"))
EVENT_STATES = (("climate_state", "climate"), ("aux_state", "aux_heating"), ("vent_state", "ventilation"))


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _hours(a: str, b: str) -> float:
    return max(0.0, (_dt(b) - _dt(a)).total_seconds() / 3600)


def _iso(d: datetime) -> str:
    return d.isoformat()


def upsert_vehicle(conn, vin: str, name=None, model=None, battery_kwh=None) -> int:
    conn.execute(
        "INSERT INTO vehicles(vin,name,model,battery_kwh) VALUES(?,?,?,?) "
        "ON CONFLICT(vin) DO UPDATE SET name=COALESCE(excluded.name,name), "
        "model=COALESCE(excluded.model,model), battery_kwh=COALESCE(excluded.battery_kwh,battery_kwh)",
        (vin, name, model, battery_kwh),
    )
    conn.commit()
    return conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()["id"]


def battery_kwh(conn, vid: int) -> float | None:
    """Usable capacity: the API does not report it, so it is user-set (vehicle row, else global setting)."""
    r = conn.execute("SELECT battery_kwh FROM vehicles WHERE id=?", (vid,)).fetchone()
    if r and r["battery_kwh"]:
        return float(r["battery_kwh"])
    s = conn.execute("SELECT value FROM settings WHERE key='battery_kwh'").fetchone()
    try:
        return float(s["value"]) if s else None
    except (TypeError, ValueError):
        return None


def last_snapshot(conn, vehicle_id: int):
    return conn.execute(
        "SELECT * FROM snapshots WHERE vehicle_id=? ORDER BY recorded_at DESC, id DESC LIMIT 1", (vehicle_id,)
    ).fetchone()


def _columns(conn) -> list[str]:
    return [r["name"] for r in conn.execute("PRAGMA table_info(snapshots)") if r["name"] not in ("id", "vehicle_id")]


def _db_value(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def ingest(conn: sqlite3.Connection, vehicle_id: int, s: dict) -> None:
    """Store one normalised snapshot (`ts` required) and update events, charges and trips."""
    prev = last_snapshot(conn, vehicle_id)
    cols = _columns(conn)
    row = {"recorded_at": s["ts"], **{k: _db_value(v) for k, v in s.items() if k in cols and k != "recorded_at"}}
    row.setdefault("charging", 0)
    names = list(row)
    cur = conn.execute(f"INSERT INTO snapshots(vehicle_id,{','.join(names)}) VALUES(?,{','.join('?' * len(names))})",
                       (vehicle_id, *row.values()))
    snap_id = cur.lastrowid
    _events(conn, vehicle_id, prev, s, snap_id)
    _charge(conn, vehicle_id, prev, s)
    ended_before = conn.execute("SELECT COUNT(*) FROM events WHERE vehicle_id=? AND kind='trip_end'", (vehicle_id,)).fetchone()[0]
    _trips(conn, vehicle_id, prev, s, snap_id)
    ended_after = conn.execute("SELECT COUNT(*) FROM events WHERE vehicle_id=? AND kind='trip_end'", (vehicle_id,)).fetchone()[0]
    rose = prev is not None and prev["soc"] is not None and s.get("soc") is not None and s["soc"] - prev["soc"] >= 2
    if rose or ended_after != ended_before:  # new evidence that the car was charged while nobody was watching
        infer_charges(conn, vehicle_id)
    conn.commit()


# ---------------------------------------------------------------------------------------------- events

def _event(conn, vid, at, kind, detail=None):
    conn.execute("INSERT INTO events(vehicle_id,at,kind,detail) VALUES(?,?,?,?)", (vid, at, kind, detail))


def _last_known(conn, vid, col, before_id):
    """Last non-NULL value of a column. A poll that omits a field must not hide a later real change."""
    r = conn.execute(f"SELECT {col} FROM snapshots WHERE vehicle_id=? AND id<? AND {col} IS NOT NULL "
                     "ORDER BY recorded_at DESC, id DESC LIMIT 1", (vid, before_id)).fetchone()
    return r[0] if r else None


def _events(conn, vid, prev, s, snap_id):
    if prev is None:
        return
    ts = s["ts"]
    for key, on, off in EVENT_FLAGS:
        new = s.get(key)
        if new is None:
            continue  # unknown never counts as a change
        old = _last_known(conn, vid, key, snap_id)
        if old is None or int(bool(new)) == old:
            continue
        _event(conn, vid, ts, on if new else off)
    for key, kind in EVENT_STATES:
        new = s.get(key)
        old = _last_known(conn, vid, key, snap_id) if new is not None else None
        if new is not None and old is not None and new != old:
            _event(conn, vid, ts, kind, f"{old} -> {new}")
    new = s.get("charge_state")
    old = _last_known(conn, vid, "charge_state", snap_id) if new is not None else None
    if new is not None and old is not None and new != old and new != "CHARGING" and old != "CHARGING":
        _event(conn, vid, ts, "charge_state", f"{old} -> {new}")


# ---------------------------------------------------------------------------------------------- charges

def open_charge(conn, vid):
    return conn.execute(
        "SELECT * FROM charges WHERE vehicle_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1", (vid,)
    ).fetchone()


def _charge(conn, vid, prev, s):
    ts, charging = s["ts"], bool(s.get("charging"))
    cur = open_charge(conn, vid)
    power = s.get("charge_power_kw") or 0.0
    if charging and cur is None:
        start_soc = s.get("soc")
        if prev is not None and not prev["charging"] and prev["soc"] is not None and _hours(prev["recorded_at"], ts) <= 0.5:
            start_soc = prev["soc"]  # the SoC just before we noticed the charge starting
        place = places.match(conn, s.get("lat"), s.get("lon"))
        conn.execute(
            "INSERT INTO charges(vehicle_id,started_at,start_soc,end_soc,max_power_kw,charge_type,lat,lon,address,"
            "target_soc,source,geofence_id) VALUES(?,?,?,?,?,?,?,?,?,?,'detected',?)",
            (vid, ts, start_soc, s.get("soc"), power, s.get("charge_type"), s.get("lat"), s.get("lon"),
             s.get("address"), s.get("target_soc"), place["id"] if place else None))
        _event(conn, vid, ts, "charge_start", s.get("charge_type"))
        return
    if cur is None:
        return
    kwh, eff = battery_kwh(conn, vid), _efficiency(conn, vid)
    soc = s.get("soc") if s.get("soc") is not None else cur["end_soc"]
    energy = cur["energy_kwh"] or 0.0
    if prev is not None:
        energy += _step_energy(prev, {"recorded_at": ts, "soc": s.get("soc"), "charge_power_kw": power}, kwh, eff)
    if charging:
        conn.execute("UPDATE charges SET energy_kwh=?, end_soc=?, max_power_kw=MAX(max_power_kw,?),"
                     " charge_type=COALESCE(charge_type,?), target_soc=COALESCE(?,target_soc) WHERE id=?",
                     (energy, soc, power, s.get("charge_type"), s.get("target_soc"), cur["id"]))
        return
    # Not charging now. An omitted state is UNKNOWN (e.g. shortly after a drive), not "ended":
    # only close when the car says something definite, or when it has been silent for too long.
    definite = s.get("charge_state") is not None or s.get("plug_connected") is False
    last_charging = conn.execute(
        "SELECT recorded_at, soc, charge_power_kw, remaining_min FROM snapshots WHERE vehicle_id=? AND charging=1 "
        "ORDER BY recorded_at DESC LIMIT 1", (vid,)).fetchone()
    stale = last_charging is not None and _hours(last_charging["recorded_at"], ts) > STALE_CHARGE_H
    if not (definite or stale):
        return
    batt = None
    if kwh and cur["start_soc"] is not None and soc is not None:
        batt = max(0.0, (soc - cur["start_soc"]) * kwh / 100)
    if energy <= 0 and batt:  # no usable power readings: fall back to the pack-side estimate
        energy = batt
    guess = _estimate_end(last_charging, ts, soc, kwh, eff) if last_charging is not None else None
    ended = guess or (last_charging["recorded_at"] if stale and not definite else ts)
    dur = round((_dt(ended) - _dt(cur["started_at"])).total_seconds() / 60)
    conn.execute("UPDATE charges SET energy_kwh=?, energy_battery_kwh=?, end_soc=?, ended_at=?, duration_min=?, end_estimated=? "
                 "WHERE id=?", (energy, batt, soc, ended, dur, int(guess is not None), cur["id"]))
    _event(conn, vid, ended, "charge_end", f"{energy:.1f} kWh")
    infer_charges(conn, vid)  # a measured charge replaces any inferred one covering the same moments


def _efficiency(conn, vid) -> float:
    return _measured_efficiency(conn, vid) or DEFAULT_EFFICIENCY


def _step_energy(prev, cur, kwh, eff) -> float:
    """Wall energy between two readings of one charge (rows or dicts with recorded_at, soc, charge_power_kw).

    Normally the trapezoid of the two power readings. Across a hole longer than MAX_GAP_H the power readings say
    nothing (the charge may have stopped in it), so the rise in battery level is used instead, divided by the charging
    efficiency. Only without a battery capacity or level does the hole count as MAX_GAP_H at the two powers."""
    h = _hours(prev["recorded_at"], cur["recorded_at"])
    p0, p1 = prev["charge_power_kw"] or 0.0, cur["charge_power_kw"] or 0.0
    if h <= MAX_GAP_H:
        return h * (p0 + p1) / 2
    if kwh and prev["soc"] is not None and cur["soc"] is not None:
        return max(0.0, cur["soc"] - prev["soc"]) * kwh / 100 / eff
    return MAX_GAP_H * (p0 + p1) / 2


def _estimate_end(last, closed_at: str, soc, kwh, eff) -> str | None:
    """When a charge stopped, if Mate had no readings then (issue #8): None when the reading that saw it over came
    within MAX_GAP_H of the last CHARGING one (that reading's time is then accurate enough), or when nothing to
    estimate from is known.

    From the last CHARGING reading: the time its power needs for the rest of the rise in battery level, else the
    car's own remaining time. Never later than the reading that saw the charge over."""
    if _hours(last["recorded_at"], closed_at) <= MAX_GAP_H:
        return None
    hours = None
    if kwh and soc is not None and last["soc"] is not None and last["charge_power_kw"]:
        hours = max(0.0, soc - last["soc"]) * kwh / 100 / eff / last["charge_power_kw"]
    elif last["remaining_min"] is not None:
        hours = last["remaining_min"] / 60
    if hours is None:
        return None
    end = _dt(last["recorded_at"]) + timedelta(seconds=round(hours * 3600))
    return _iso(min(end, _dt(closed_at)))


REPAIRED_GAPS_KEY = "repaired_charge_gaps"


def repair_charge_gaps(conn) -> int:
    """Once per database: correct live-detected charges recorded before gaps in the readings were handled (issue #8).

    They were closed at the first reading after the gap and had each gap counted as at most MAX_GAP_H of power. The
    readings are still stored, so the charge is replayed with today's rules. Only charges closed by a definite
    reading are touched; a stale-closed one already ends at its last CHARGING reading. Returns how many changed."""
    if conn.execute("SELECT 1 FROM settings WHERE key=?", (REPAIRED_GAPS_KEY,)).fetchone():
        return 0
    n = sum(_repair_charge(conn, c) for c in conn.execute(
        "SELECT * FROM charges WHERE COALESCE(source,'detected')='detected' AND ended_at IS NOT NULL").fetchall())
    set_setting(conn, REPAIRED_GAPS_KEY, "1")
    conn.commit()
    return n


def _repair_charge(conn, c) -> int:
    vid = c["vehicle_id"]
    snaps = conn.execute("SELECT recorded_at, soc, charging, charge_power_kw, remaining_min FROM snapshots WHERE vehicle_id=? "
                         "AND recorded_at BETWEEN ? AND ? ORDER BY recorded_at, id", (vid, c["started_at"], c["ended_at"])).fetchall()
    pairs = list(zip(snaps, snaps[1:], strict=False))
    last = next((s for s in reversed(snaps) if s["charging"]), None)
    if last is None or snaps[-1]["charging"] or not any(_hours(a["recorded_at"], b["recorded_at"]) > MAX_GAP_H for a, b in pairs):
        return 0
    kwh, eff = battery_kwh(conn, vid), _efficiency(conn, vid)
    energy = sum(_step_energy(a, b, kwh, eff) for a, b in pairs)
    if energy <= 0 and c["energy_battery_kwh"]:
        energy = c["energy_battery_kwh"]
    soc = snaps[-1]["soc"] if snaps[-1]["soc"] is not None else c["end_soc"]
    guess = _estimate_end(last, snaps[-1]["recorded_at"], soc, kwh, eff)
    ended = guess or c["ended_at"]
    dur = round((_dt(ended) - _dt(c["started_at"])).total_seconds() / 60)
    conn.execute("UPDATE charges SET energy_kwh=?, ended_at=?, duration_min=?, end_estimated=? WHERE id=?",
                 (energy, ended, dur, int(guess is not None), c["id"]))
    conn.execute("UPDATE events SET at=?, detail=? WHERE vehicle_id=? AND kind='charge_end' AND at=?",
                 (ended, f"{energy:.1f} kWh", vid, c["ended_at"]))
    return 1


# ---------------------------------------------------------------------------------------------- inferred charges

INFER_MIN_RISE = 3.0  # percentage points: smaller rises are rounding noise
DEFAULT_EFFICIENCY = 0.90  # wall energy -> battery energy, used only when no real charge has measured it yet
INFER_WINDOW_DAYS = 45


def _anchors(conn, vid, since_iso):
    """Every moment the battery level is known, in time order: readings while parked, and the start/end of each trip."""
    a = []
    for t in conn.execute("SELECT started_at, ended_at, start_soc, end_soc, start_lat, start_lon, end_lat, end_lon, start_place, end_place "
                          "FROM trips WHERE vehicle_id=? AND ended_at IS NOT NULL AND ended_at>=?", (vid, since_iso)):
        if t["start_soc"] is not None and t["started_at"]:
            a.append({"t": t["started_at"], "soc": t["start_soc"], "kind": "drive-start", "lat": t["start_lat"], "lon": t["start_lon"], "place": t["start_place"]})
        if t["end_soc"] is not None:
            a.append({"t": t["ended_at"], "soc": t["end_soc"], "kind": "drive-end", "lat": t["end_lat"], "lon": t["end_lon"], "place": t["end_place"]})
    for r in conn.execute("SELECT recorded_at, soc, lat, lon, address FROM snapshots WHERE vehicle_id=? AND soc IS NOT NULL AND recorded_at>=? "
                          "AND (in_motion IS NULL OR in_motion=0)", (vid, since_iso)):
        a.append({"t": r["recorded_at"], "soc": r["soc"], "kind": "reading", "lat": r["lat"], "lon": r["lon"], "place": r["address"]})
    a.sort(key=lambda x: _dt(x["t"]))
    return a


def infer_charges(conn, vid: int, days: int = INFER_WINDOW_DAYS) -> int:
    """Charges nobody watched: the battery level went UP between two moments with no driving in between.

    The official API has no charging history and Mate can only see a charge while it polls during it. Every trip stores
    its start and end level, so a trip that starts higher than the previous one ended proves a charge in between.
    These rows are `source='inferred'`: the time window is only "somewhere between the two moments", the energy is the
    level change times the battery capacity (divided by a typical efficiency for the wall figure), the type is unknown.
    Live-detected charges always win: inferred rows that overlap one are dropped. User edits (note, place, cost) are kept."""
    latest = conn.execute("SELECT MAX(t) FROM (SELECT MAX(recorded_at) t FROM snapshots WHERE vehicle_id=? UNION ALL "
                          "SELECT MAX(ended_at) FROM trips WHERE vehicle_id=?)", (vid, vid)).fetchone()[0]
    if not latest:
        return 0
    since = _iso(_dt(latest) - timedelta(days=days))
    anchors = _anchors(conn, vid, since)
    cands: list[dict] = []
    cur = None

    def flush():
        if cur and cur["rise"] >= INFER_MIN_RISE:
            cands.append(cur)

    for a, b in zip(anchors, anchors[1:], strict=False):
        if a["kind"] == "drive-start" or b["kind"] == "drive-end":  # the car was driving between these two: not a charge
            flush()
            cur = None
            continue
        d = b["soc"] - a["soc"]
        if d > 0:
            cur = {"a": a, "b": b, "rise": d} if cur is None else {**cur, "b": b, "rise": cur["rise"] + d}
        else:
            flush()
            cur = None
    flush()

    real = [(r["started_at"], r["ended_at"] or "9999") for r in conn.execute(
        "SELECT started_at, ended_at FROM charges WHERE vehicle_id=? AND COALESCE(source,'detected')!='inferred'", (vid,))]
    kwh = battery_kwh(conn, vid)
    eff = _measured_efficiency(conn, vid) or DEFAULT_EFFICIENCY
    keep, n = set(), 0
    for c in cands:
        t0, t1 = c["a"]["t"], c["b"]["t"]
        if any(rs <= t1 and re >= t0 for rs, re in real):  # a live-detected charge already explains this rise
            continue
        batt = round(c["rise"] * kwh / 100, 2) if kwh else None
        place = places.match(conn, c["a"]["lat"], c["a"]["lon"])
        vals = (t1, c["a"]["soc"], c["b"]["soc"], None if batt is None else round(batt / eff, 2), batt,
                round((_dt(t1) - _dt(t0)).total_seconds() / 60), c["a"]["lat"], c["a"]["lon"], c["a"]["place"],
                place["id"] if place else None)
        existing = conn.execute("SELECT id FROM charges WHERE vehicle_id=? AND source='inferred' AND started_at=?", (vid, t0)).fetchone()
        if existing:
            conn.execute("UPDATE charges SET ended_at=?, start_soc=?, end_soc=?, energy_kwh=?, energy_battery_kwh=?, duration_min=?, "
                         "lat=?, lon=?, address=?, geofence_id=? WHERE id=?", (*vals, existing["id"]))
        else:
            conn.execute("INSERT INTO charges(vehicle_id,started_at,source,ended_at,start_soc,end_soc,energy_kwh,energy_battery_kwh,"
                         "duration_min,lat,lon,address,geofence_id) VALUES(?,?,'inferred',?,?,?,?,?,?,?,?,?,?)", (vid, t0, *vals))
            n += 1
        keep.add(t0)
    # inferred rows that no longer hold (a real charge now covers them, or the readings changed), unless the user edited them
    for r in conn.execute("SELECT id, started_at, note, cost_manual, place_kind FROM charges WHERE vehicle_id=? AND source='inferred' AND started_at>=?",
                          (vid, since)).fetchall():
        if r["started_at"] not in keep and not (r["note"] or r["cost_manual"] is not None or r["place_kind"]):
            conn.execute("DELETE FROM charges WHERE id=?", (r["id"],))
    conn.commit()
    return n


def _measured_efficiency(conn, vid) -> float | None:
    r = conn.execute("SELECT SUM(energy_battery_kwh) b, SUM(energy_kwh) w FROM charges WHERE vehicle_id=? AND ended_at IS NOT NULL "
                     "AND COALESCE(source,'detected')!='inferred' AND energy_battery_kwh>0 AND energy_kwh>0 AND end_soc-start_soc>=20", (vid,)).fetchone()
    if r and r["w"]:
        e = r["b"] / r["w"]
        return e if 0.6 <= e <= 1.0 else None  # a sparse-poll artefact must not distort the estimate
    return None


# ---------------------------------------------------------------------------------------------- trips

def open_trip(conn, vid):
    return conn.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
                        (vid,)).fetchone()


def _last_parked(conn, vid, before_id):
    """The latest snapshot while parked (or with a known odometer), i.e. where the car last stood still."""
    return conn.execute(
        "SELECT * FROM snapshots WHERE vehicle_id=? AND id<? AND (in_motion=0 OR in_motion IS NULL) "
        "AND (lat IS NOT NULL OR mileage_km IS NOT NULL) ORDER BY recorded_at DESC, id DESC LIMIT 1",
        (vid, before_id)).fetchone()


def _trips(conn, vid, prev, s, snap_id):
    ts, moving = s["ts"], s.get("in_motion") is True
    open_ = open_trip(conn, vid)
    if moving:
        if open_ is None:
            ref = _last_parked(conn, vid, snap_id)
            started = _drive_start(ref, s)
            start_lat, start_lon = (ref["lat"], ref["lon"]) if ref else (None, None)
            place = places.match(conn, start_lat, start_lon)
            conn.execute(
                "INSERT INTO trips(vehicle_id,cloud_id,started_at,start_soc,start_fuel_pct,start_place,start_lat,start_lon,"
                "odo_start,approx,start_geofence_id) VALUES(?,?,?,?,?,?,?,?,?,0,?)",
                (vid, f"drv-{ts}", started, ref["soc"] if ref else s.get("soc"), ref["fuel_pct"] if ref else s.get("fuel_pct"),
                 ref["address"] if ref else None, start_lat, start_lon,
                 (ref["mileage_km"] if ref and ref["mileage_km"] is not None else s.get("mileage_km")),
                 place["id"] if place else None))
            _event(conn, vid, started, "trip_start")
        else:
            conn.execute("UPDATE trips SET end_soc=COALESCE(?,end_soc) WHERE id=?", (s.get("soc"), open_["id"]))
        return
    if open_ is not None:
        # Close on a definite PARKED. An unknown state (position part missing this time) must not end a drive,
        # but a trip that has been "open" for hours is stuck and gets closed with what we have.
        if s.get("in_motion") is False or _hours(open_["started_at"], ts) > STALE_TRIP_H:
            _close_trip(conn, vid, open_, s)
        return
    # Parked and nothing open: did the odometer jump since the previous snapshot with a reading?
    if s.get("mileage_km") is None:
        return
    ref = conn.execute("SELECT * FROM snapshots WHERE vehicle_id=? AND id<? AND mileage_km IS NOT NULL "
                       "ORDER BY recorded_at DESC, id DESC LIMIT 1", (vid, snap_id)).fetchone()
    if ref is None or s["mileage_km"] - ref["mileage_km"] < MIN_TRIP_KM:
        return
    km = s["mileage_km"] - ref["mileage_km"]
    elapsed_h = max(_hours(ref["recorded_at"], ts), 1 / 60)
    if km / elapsed_h > MAX_PLAUSIBLE_KMH:
        # More distance than any car covers in that time: the odometer source changed (or readings were lost for a
        # long while). Do not invent a trip; leave a trace instead.
        _event(conn, vid, ts, "odometer_jump", f"+{km:.0f} km in {elapsed_h:.1f} h, not recorded as a trip")
        return
    ended = _clamp_end(s, ref["recorded_at"])
    start_dt = max(_dt(ref["recorded_at"]), _dt(ended) - timedelta(hours=km / GUESS_KMH))
    _finish(conn, vid, None, s, start_iso=_iso(start_dt), end_iso=ended, km=km, odo_start=ref["mileage_km"],
            start_soc=ref["soc"], start_fuel=ref["fuel_pct"], start=(ref["address"], ref["lat"], ref["lon"]), approx=1)


def _drive_start(ref, s) -> str:
    """When a drive began. The first poll that sees the car moving is usually mid-drive: if the odometer is already
    ahead of the last parked reading, place the start that far back (at a typical speed), never before that reading."""
    ts = s["ts"]
    if ref is None or ref["mileage_km"] is None or s.get("mileage_km") is None:
        return ts
    km = s["mileage_km"] - ref["mileage_km"]
    if km < MIN_TRIP_KM:
        return ts
    return _iso(max(_dt(ref["recorded_at"]), _dt(ts) - timedelta(hours=km / GUESS_KMH)))


def _clamp_end(s, not_before_iso: str) -> str:
    """When the car stopped: the car's own timestamp (position, else the latest report) if it is sane, else the poll time."""
    for cap in (s.get("park_captured_at"), s.get("captured_at")):
        if cap and _dt(not_before_iso) <= _dt(cap) <= _dt(s["ts"]):
            return cap
    return s["ts"]


def _close_trip(conn, vid, t, s):
    odo_start = t["odo_start"]
    km = None
    if odo_start is not None and s.get("mileage_km") is not None:
        km = s["mileage_km"] - odo_start
    ended = _clamp_end(s, t["started_at"])
    _finish(conn, vid, t["id"], s, start_iso=t["started_at"], end_iso=ended, km=km, odo_start=odo_start,
            start_soc=t["start_soc"], start_fuel=t["start_fuel_pct"], start=(t["start_place"], t["start_lat"], t["start_lon"]),
            approx=0)


def _finish(conn, vid, trip_id, s, *, start_iso, end_iso, km, odo_start, start_soc, start_fuel, start, approx):
    if km is not None and km < MIN_TRIP_KM:
        if trip_id is not None:  # the car moved but the odometer did not: not a real trip
            conn.execute("DELETE FROM trips WHERE id=?", (trip_id,))
        return
    minutes = max(1, round((_dt(end_iso) - _dt(start_iso)).total_seconds() / 60))
    kwh = battery_kwh(conn, vid)
    end_soc = s.get("soc")
    energy = basis = None
    if kwh and start_soc is not None and end_soc is not None and start_soc >= end_soc:
        energy, basis = round((start_soc - end_soc) * kwh / 100, 2), "soc_delta"
    per100 = round(energy / km * 100, 1) if energy is not None and km and km >= 2 else None
    route = [{"lat": start[1], "lon": start[2], "place": start[0], "soc": start_soc},
             {"lat": s.get("lat"), "lon": s.get("lon"), "place": s.get("address"), "soc": end_soc}]
    route = [p for p in route if p["lat"] is not None and p["lon"] is not None]
    start_place = places.match(conn, start[1], start[2])
    end_place = places.match(conn, s.get("lat"), s.get("lon"))
    links = (start_place["id"] if start_place else None, end_place["id"] if end_place else None)
    vals = (end_iso, km, minutes, round(km / minutes * 60, 1) if km else None, per100, energy, basis, end_soc,
            s.get("fuel_pct"), s.get("address"), s.get("lat"), s.get("lon"), s.get("mileage_km"), json.dumps(route), approx)
    if trip_id is not None:
        conn.execute(
            "UPDATE trips SET ended_at=?,distance_km=?,duration_min=?,avg_speed_kmh=?,avg_kwh_100km=?,energy_kwh=?,"
            "energy_basis=?,end_soc=?,end_fuel_pct=?,end_place=?,end_lat=?,end_lon=?,odo_end=?,route_json=?,approx=?,"
            "start_geofence_id=?,end_geofence_id=? WHERE id=?",
            (*vals, *links, trip_id))
    else:
        conn.execute(
            "INSERT INTO trips(ended_at,distance_km,duration_min,avg_speed_kmh,avg_kwh_100km,energy_kwh,energy_basis,end_soc,"
            "end_fuel_pct,end_place,end_lat,end_lon,odo_end,route_json,approx,vehicle_id,cloud_id,started_at,odo_start,"
            "start_soc,start_fuel_pct,start_place,start_lat,start_lon,start_geofence_id,end_geofence_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*vals, vid, f"odo-{start_iso}", start_iso, odo_start, start_soc, start_fuel, start[0], start[1], start[2], *links))
    _event(conn, vid, end_iso, "trip_end", f"{km:.1f} km" if km is not None else None)
