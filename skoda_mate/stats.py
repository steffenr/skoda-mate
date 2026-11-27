"""Aggregations over the derived trips and charges. Everything is computed, not measured by the car:
the API offers no statistics. Functions return plain dicts for the dashboard."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from . import costs, places, recorder


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def monthly(conn, vid: int, tariff: dict) -> list[dict]:
    """One row per month: distance, trip energy, charged energy, cost, consumption, charge counts."""
    months: dict[str, dict] = {}

    def m(key):
        return months.setdefault(key, {"month": key, "trips": 0, "km": 0.0, "odo_km": None, "trip_kwh": 0.0, "trip_kwh_km": 0.0,
                                       "charges": 0, "charged_kwh": 0.0, "ac_kwh": 0.0, "dc_kwh": 0.0, "inferred_kwh": 0.0,
                                       "inferred_charges": 0, "home_kwh": 0.0,
                                       "public_kwh": 0.0, "unknown_place_kwh": 0.0, "cost": 0.0, "cost_known": True})

    for t in _rows(conn.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NOT NULL", (vid,))):
        r = m((t["started_at"] or t["ended_at"])[:7])
        r["trips"] += 1
        r["km"] += t["distance_km"] or 0
        if t["energy_kwh"] and t["distance_km"]:
            r["trip_kwh"] += t["energy_kwh"]
            r["trip_kwh_km"] += t["distance_km"]
    places_by_id = {p["id"]: p for p in places.list_places(conn)}
    for c in _rows(conn.execute("SELECT * FROM charges WHERE vehicle_id=? AND ended_at IS NOT NULL", (vid,))):
        r = m(c["started_at"][:7])
        k = c["energy_kwh"] or 0
        r["charges"] += 1
        r["charged_kwh"] += k
        if c.get("source") in costs.INFERRED_SOURCES:  # read off other data, not measured: never mixed into AC/DC
            r["inferred_kwh"] += k
            r["inferred_charges"] += 1
        else:
            r["dc_kwh" if c["charge_type"] == "DC" else "ac_kwh"] += k
        cc = costs.charge_cost(c, tariff, places_by_id.get(c.get("geofence_id")))
        # a place that is neither known home nor known public (no home position set yet) is its own bucket, never "public"
        r[{"home": "home_kwh", "public": "public_kwh"}.get(cc["kind"], "unknown_place_kwh")] += k
        if cc["amount"] is None:
            r["cost_known"] = r["cost_known"] and not k
        else:
            r["cost"] += cc["amount"]
    # Distance as the ODOMETER saw it: exact even for drives Mate never caught as a trip. Per month: highest reading minus
    # the highest reading of the month before (or this month's lowest, for the first month Mate has readings).
    prev_hi = None
    for o in conn.execute("SELECT substr(recorded_at,1,7) m, MIN(mileage_km) lo, MAX(mileage_km) hi FROM snapshots "
                          "WHERE vehicle_id=? AND mileage_km IS NOT NULL GROUP BY m ORDER BY m", (vid,)):
        m(o["m"])["odo_km"] = round(o["hi"] - (prev_hi if prev_hi is not None else o["lo"]), 1)
        prev_hi = o["hi"]
    out = []
    for key in sorted(months):
        r = months[key]
        r["kwh_100km"] = round(r["trip_kwh"] / r["trip_kwh_km"] * 100, 1) if r["trip_kwh_km"] else None
        for f in ("km", "trip_kwh", "charged_kwh", "ac_kwh", "dc_kwh", "inferred_kwh", "home_kwh", "public_kwh", "unknown_place_kwh", "cost"):
            r[f] = round(r[f], 2)
        del r["trip_kwh_km"]
        out.append(r)
    return out


def totals(conn, vid: int, tariff: dict) -> dict:
    ms = monthly(conn, vid, tariff)
    km = sum(m["km"] for m in ms)
    kwh_km = conn.execute("SELECT COALESCE(SUM(energy_kwh),0) e, COALESCE(SUM(distance_km),0) d FROM trips "
                          "WHERE vehicle_id=? AND ended_at IS NOT NULL AND energy_kwh IS NOT NULL AND distance_km>=2", (vid,)).fetchone()
    # "Tracked since": the earliest thing Mate knows (a trip, a charge or a reading). Statistics can only cover that
    # period: the API has no history, so the car's lifetime distance (the odometer) is usually much more than the trips.
    first = min((x for x in (
        conn.execute("SELECT MIN(COALESCE(started_at, ended_at)) FROM trips WHERE vehicle_id=?", (vid,)).fetchone()[0],
        conn.execute("SELECT MIN(started_at) FROM charges WHERE vehicle_id=?", (vid,)).fetchone()[0],
        conn.execute("SELECT MIN(recorded_at) FROM snapshots WHERE vehicle_id=?", (vid,)).fetchone()[0]) if x), default=None)
    odo = conn.execute("SELECT mileage_km FROM snapshots WHERE vehicle_id=? AND mileage_km IS NOT NULL "
                       "ORDER BY recorded_at DESC LIMIT 1", (vid,)).fetchone()
    span = conn.execute("SELECT MIN(mileage_km) lo, MAX(mileage_km) hi, MIN(recorded_at) t0 FROM snapshots "
                        "WHERE vehicle_id=? AND mileage_km IS NOT NULL", (vid,)).fetchone()
    return {"since": first, "odometer_km": odo[0] if odo else None,
            "odometer_tracked_km": round(span["hi"] - span["lo"], 1) if span and span["lo"] is not None else None,
            "odometer_tracked_since": span["t0"] if span else None, "trips": sum(m["trips"] for m in ms),
            "km": round(km, 1), "charges": sum(m["charges"] for m in ms),
            "inferred_charges": sum(m["inferred_charges"] for m in ms),
            "inferred_kwh": round(sum(m["inferred_kwh"] for m in ms), 1),
            "charged_kwh": round(sum(m["charged_kwh"] for m in ms), 1),
            "home_kwh": round(sum(m["home_kwh"] for m in ms), 1), "public_kwh": round(sum(m["public_kwh"] for m in ms), 1),
            "unknown_place_kwh": round(sum(m["unknown_place_kwh"] for m in ms), 1),
            "cost": round(sum(m["cost"] for m in ms), 2), "currency": tariff["currency"],
            "kwh_100km": round(kwh_km["e"] / kwh_km["d"] * 100, 1) if kwh_km["d"] else None,
            "cost_per_100km": round(sum(m["cost"] for m in ms) / km * 100, 2) if km else None}


def battery(conn, vid: int) -> dict:
    """Usable-capacity ESTIMATE from AC charges that covered at least 30 % of SoC: wall energy per 100 % SoC.

    This includes charging losses (typically 5-12 % on AC), so it overstates the pack; the API does not report
    battery health. It is useful as a trend, and as a health indicator only when compared with itself.
    """
    nominal = recorder.battery_kwh(conn, vid)
    rows = _rows(conn.execute(
        "SELECT started_at,start_soc,end_soc,energy_kwh,charge_type FROM charges WHERE vehicle_id=? AND ended_at IS NOT NULL "
        "AND start_soc IS NOT NULL AND end_soc IS NOT NULL AND energy_kwh>0 AND (charge_type IS NULL OR charge_type!='DC') "
        "AND end_soc-start_soc>=30 ORDER BY started_at", (vid,)))
    points = [{"at": r["started_at"], "kwh_per_100": round(r["energy_kwh"] / (r["end_soc"] - r["start_soc"]) * 100, 1),
               "delta_soc": r["end_soc"] - r["start_soc"]} for r in rows]
    recent = [p["kwh_per_100"] for p in points[-10:]]
    est = round(statistics.median(recent), 1) if recent else None
    eff = _efficiency(conn, vid)
    return {"nominal_kwh": nominal, "estimate_kwh_at_wall": est, "samples": len(points), "points": points,
            "charging_efficiency": eff,
            "note": "Wall energy per 100 % SoC from AC charges of 30 %+ (includes charging losses). "
                    "MySkoda does not report battery health."}


def _efficiency(conn, vid) -> float | None:
    """Pack energy / wall energy over charges where both are known (needs the battery capacity setting)."""
    r = conn.execute("SELECT SUM(energy_battery_kwh) b, SUM(energy_kwh) w FROM charges WHERE vehicle_id=? AND ended_at IS NOT NULL "
                     "AND energy_battery_kwh>0 AND energy_kwh>0 AND end_soc-start_soc>=20", (vid,)).fetchone()
    return round(r["b"] / r["w"], 3) if r and r["w"] else None


def soc_history(conn, vid: int, hours: int, now_iso: str, max_points: int = 600) -> list[dict]:
    """The battery curve: every stored reading, plus the charge level at the start and end of each trip and charge.

    The API reports only the present moment and polling is sparse (a 30-minute drive may be read once), so the
    readings alone can look flat across a drive. A trip's start/end levels fill exactly that gap. Points that come
    from a trip or charge carry `src` so the UI can tell them apart."""
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    cutoff = (now - timedelta(hours=int(hours))).isoformat()
    rows = _rows(conn.execute(
        "SELECT recorded_at t, soc, range_km, charge_power_kw p, mileage_km odo, charging FROM snapshots WHERE vehicle_id=? "
        "AND recorded_at >= ? ORDER BY recorded_at", (vid, cutoff)))
    seen = {r["t"] for r in rows}
    extra = []
    for kind, table in (("trip", "trips"), ("charge", "charges")):
        for r in conn.execute(f"SELECT started_at, ended_at, start_soc, end_soc FROM {table} WHERE vehicle_id=? "
                              "AND COALESCE(ended_at, started_at) >= ?", (vid, cutoff)):
            for t, soc in ((r["started_at"], r["start_soc"]), (r["ended_at"], r["end_soc"])):
                if t and soc is not None and t >= cutoff and t not in seen:
                    seen.add(t)
                    extra.append({"t": t, "soc": soc, "range_km": None, "p": None, "odo": None, "charging": 0, "src": kind})
    rows = sorted(rows + extra, key=lambda r: r["t"])
    if len(rows) > max_points:  # thin evenly, keep the last point
        step = len(rows) / max_points
        rows = [rows[int(i * step)] for i in range(max_points)] + [rows[-1]]
    return rows


def map_points(conn, vid: int, limit: int = 1000) -> dict:
    all_places = places.list_places(conn)  # one query: every parked cluster matches against the same list
    parked = _rows(conn.execute(
        "SELECT lat, lon, address, MAX(recorded_at) last_seen, MIN(recorded_at) first_seen, COUNT(*) n FROM snapshots "
        "WHERE vehicle_id=? AND lat IS NOT NULL AND in_motion=0 GROUP BY ROUND(lat,3), ROUND(lon,3) ORDER BY last_seen DESC LIMIT ?",
        (vid, limit)))
    for cluster in parked:
        place = places.match(conn, cluster["lat"], cluster["lon"], all_places)
        cluster["place_id"] = place["id"] if place else None
    chg = _rows(conn.execute("SELECT id, lat, lon, address, started_at, energy_kwh, charge_type, geofence_id FROM charges "
                             "WHERE vehicle_id=? AND lat IS NOT NULL ORDER BY started_at DESC LIMIT ?", (vid, limit)))
    trips = _rows(conn.execute("SELECT id, start_lat, start_lon, end_lat, end_lon, start_place, end_place, started_at, distance_km, "
                               "start_geofence_id, end_geofence_id FROM trips WHERE vehicle_id=? AND end_lat IS NOT NULL "
                               "ORDER BY started_at DESC LIMIT ?", (vid, limit)))
    return {"parked": parked, "charges": chg, "trips": trips}
