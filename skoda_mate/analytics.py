"""Insight over the stored trips, charges and readings: charging, driving and the projected range.

Read-only queries with no FastAPI dependency. Inferred and imported charges count toward energy and cost but never
toward power, the charge curve or the time-of-day heatmap, because their times and power were not measured. The
projected range is the range the car reports scaled to 100 %; it says nothing about the condition of the battery.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from weakref import WeakKeyDictionary

from . import costs, places

CURVE_BIN = 5  # percentage points of SoC per charge-curve bin
CURVE_MIN_SAMPLES = 3  # a thinner bin would draw one reading as if it were the car's behaviour
TOP_PLACES = 5
TOP_DESTINATIONS = 8
LONGEST_TRIPS = 5
DISTANCE_BUCKETS: tuple[tuple[int, int | None], ...] = ((0, 5), (5, 20), (20, 50), (50, 100), (100, None))
PROJECTION_MIN_DAYS = 60
PROJECTION_WINDOW_DAYS = 365

RANGE_MIN_SOC = 20  # below this the integer percentage makes the scaled range too coarse
RANGE_PLAUSIBLE_KM = (200, 1000)
RANGE_MEDIAN_HALF_WINDOW = 15  # days either side: "recent" follows the seasons instead of deleting one of them
RANGE_MAD_FACTOR = 3
RANGE_MAD_FLOOR = 0.01  # of the median: a flat series has no deviation, yet integer SoC still adds noise
TREND_MIN_SPAN_DAYS = 60
TREND_MIN_DAYS = 10
WINDOW_DAYS = 90
WINDOW_MIN_DAYS = 20  # days with data a 90-day window needs before it is compared


def _local(iso: str, tz_offset: int) -> datetime:
    """The viewer's wall-clock time; `tz_offset` is JS `getTimezoneOffset()` (minutes, UTC minus local)."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(minutes=tz_offset)


def _finished(conn, table: str, vid: int, from_iso: str | None, to_iso: str | None) -> list[dict]:
    """Closed trips or charges whose start lies in [from, to)."""
    sql = f"SELECT * FROM {table} WHERE vehicle_id=? AND ended_at IS NOT NULL"
    args: list = [vid]
    for op, bound in ((">=", from_iso), ("<", to_iso)):
        if bound:
            sql += f" AND COALESCE(started_at, ended_at) {op} ?"
            args.append(bound)
    return [dict(r) for r in conn.execute(sql + " ORDER BY COALESCE(started_at, ended_at), id", args)]


def _heatmap(starts: list[str], tz_offset: int) -> list[list[int]]:
    """Counts per local weekday (Monday first) and hour of day."""
    grid = [[0] * 24 for _ in range(7)]
    for iso in starts:
        at = _local(iso, tz_offset)
        grid[at.weekday()][at.hour] += 1
    return grid


class _Money:
    """A cost total that stays unknown while nothing is known, and says when part of it is missing."""

    def __init__(self) -> None:
        self.sessions, self.energy, self.amount, self.known, self.partial = 0, 0.0, 0.0, 0, False

    def add(self, energy: float | None, amount: float | None) -> None:
        self.sessions += 1
        self.energy += energy or 0
        if amount is None:
            self.partial = True
        else:
            self.amount += amount
            self.known += 1

    def out(self) -> dict:
        return {"sessions": self.sessions, "energy_kwh": round(self.energy, 2),
                "cost": round(self.amount, 2) if self.known else None, "cost_partial": self.partial}


def charging(conn, vid: int, tariff: dict, from_iso: str | None = None, to_iso: str | None = None,
             tz_offset: int = 0) -> dict:
    rows = _finished(conn, "charges", vid, from_iso, to_iso)
    by_id = {p["id"]: p for p in places.list_places(conn)}
    total = _Money()
    split = {k: _Money() for k in ("home", "public", "other")}
    top: dict[tuple, _Money] = defaultdict(_Money)
    measured: list[dict] = []
    inferred_kwh = priced_kwh = priced_amount = fees = 0.0
    unknown_energy = 0
    for c in rows:
        place = by_id.get(c.get("geofence_id"))
        cost = costs.charge_cost(c, tariff, place)
        energy, amount = c["energy_kwh"], cost["amount"]
        total.add(energy, amount)
        split[cost["kind"] if cost["kind"] in ("home", "public") else "other"].add(energy, amount)
        top[(place["id"], place["name"]) if place else (None, c.get("address") or None)].add(energy, amount)
        if not energy:
            unknown_energy += 1
        elif amount is not None:
            priced_kwh += energy
            priced_amount += amount
        if cost["basis"] == "place" and amount is not None and place and not place.get("free"):
            fees += place.get("session_fee") or 0
        if c.get("source") in costs.INFERRED_SOURCES:
            inferred_kwh += energy or 0
        else:
            measured.append(c)

    t = total.out()
    measured_kwh = sum(c["energy_kwh"] or 0 for c in measured)
    t.update({"cost_per_kwh": round(priced_amount / priced_kwh, 3) if priced_kwh else None,
              "measured_sessions": len(measured), "measured_kwh": round(measured_kwh, 2),
              "inferred_sessions": len(rows) - len(measured), "inferred_kwh": round(inferred_kwh, 2),
              "inferred_share": round(inferred_kwh / total.energy, 3) if total.energy else None,
              "unknown_energy_sessions": unknown_energy, "session_fees": round(fees, 2)})
    ranked = sorted(top.items(), key=lambda kv: (-kv[1].energy, -kv[1].sessions, str(kv[0][1])))[:TOP_PLACES]
    return {"totals": t,
            "types": {name: _power([c for c in measured if _type(c) == name]) for name in ("ac", "dc", "unknown")},
            "split": {k: v.out() for k, v in split.items()},
            "heatmap": _heatmap([c["started_at"] for c in measured], tz_offset),
            "heatmap_excluded": len(rows) - len(measured),
            "top_places": [{"place_id": pid, "name": name, **m.out()} for (pid, name), m in ranked],
            "curve": _curve(conn, vid, measured)}


def _type(charge: dict) -> str:
    return {"AC": "ac", "DC": "dc"}.get(charge.get("charge_type") or "", "unknown")


def _power(charges: list[dict]) -> dict:
    """Energy over time for the charges where both were measured; a worked-out end time would only echo the estimate."""
    timed = [c for c in charges if c["energy_kwh"] and c["duration_min"] and not c["end_estimated"]]
    hours = sum(c["duration_min"] for c in timed) / 60
    peaks = [c["max_power_kw"] for c in charges if c["max_power_kw"]]
    return {"sessions": len(charges), "energy_kwh": round(sum((c["energy_kwh"] or 0) for c in charges), 2),
            "avg_power_kw": round(sum(c["energy_kwh"] for c in timed) / hours, 1) if hours else None,
            "peak_power_kw": round(max(peaks), 1) if peaks else None, "power_sessions": len(timed)}


def _curve(conn, vid: int, measured: list[dict]) -> dict:
    bins: dict[str, dict[int, list[float]]] = {"ac": defaultdict(list), "dc": defaultdict(list)}
    for c in measured:
        kind = _type(c)
        if kind not in bins:
            continue
        for s in conn.execute(
                "SELECT soc, charge_power_kw p FROM snapshots WHERE vehicle_id=? AND recorded_at BETWEEN ? AND ? "
                "AND charging=1 AND soc IS NOT NULL AND charge_power_kw>0", (vid, c["started_at"], c["ended_at"])):
            low = min(int(s["soc"] // CURVE_BIN) * CURVE_BIN, 100 - CURVE_BIN)  # 100 % belongs to the last bin
            bins[kind][low].append(s["p"])
    return {kind: [{"soc_from": low, "soc_to": low + CURVE_BIN, "avg_kw": round(statistics.fmean(v), 1),
                    "samples": len(v)} for low, v in sorted(data.items()) if len(v) >= CURVE_MIN_SAMPLES]
            for kind, data in bins.items()}


def driving(conn, vid: int, from_iso: str | None = None, to_iso: str | None = None, tz_offset: int = 0) -> dict:
    rows = _finished(conn, "trips", vid, from_iso, to_iso)
    names = {p["id"]: p["name"] for p in places.list_places(conn)}
    with_km = [t for t in rows if t["distance_km"] is not None]
    timed = [t["duration_min"] for t in rows if t["duration_min"] is not None and not t["approx"]]
    km = sum(t["distance_km"] for t in with_km)

    destinations: dict[tuple, list[float]] = defaultdict(list)
    for t in rows:
        pid = t.get("end_geofence_id")
        key = (pid, names[pid]) if pid in names else (None, t.get("end_place") or None)
        destinations[key].append(t["distance_km"] or 0)
    ranked = sorted(destinations.items(), key=lambda kv: (-len(kv[1]), -sum(kv[1]), str(kv[0][1])))[:TOP_DESTINATIONS]

    buckets = []
    for low, high in DISTANCE_BUCKETS:
        inside = [t["distance_km"] for t in with_km
                  if t["distance_km"] >= low and (high is None or t["distance_km"] < high)]
        buckets.append({"from_km": low, "to_km": high, "trips": len(inside), "km": round(sum(inside), 1)})

    longest = [{"id": t["id"], "started_at": t["started_at"] or t["ended_at"], "distance_km": t["distance_km"],
                "start": names.get(t.get("start_geofence_id")) or t.get("start_place"),
                "end": names.get(t.get("end_geofence_id")) or t.get("end_place"), "approx": bool(t["approx"])}
               for t in sorted(with_km, key=lambda t: -t["distance_km"])[:LONGEST_TRIPS]]
    projection, tracked_days = _annual_distance(conn, vid)
    exact = [t["started_at"] for t in rows if t["started_at"] and not t["approx"]]
    return {"totals": {"trips": len(rows), "km": round(km, 1), "approx_trips": sum(1 for t in rows if t["approx"]),
                       "avg_km": round(km / len(with_km), 1) if with_km else None,
                       "avg_duration_min": round(statistics.fmean(timed)) if timed else None},
            "top_destinations": [{"place_id": pid, "name": name, "trips": len(v), "km": round(sum(v), 1)}
                                 for (pid, name), v in ranked],
            "heatmap": _heatmap(exact, tz_offset), "heatmap_excluded": len(rows) - len(exact),
            "buckets": buckets, "longest": longest, "consumption": _consumption(rows),
            "projection": projection, "tracked_days": tracked_days}


def _consumption(trips: list[dict]) -> list[dict]:
    """Per month, bucketed and defined like the monthly statistics, so the two always agree."""
    months: dict[str, list[dict]] = defaultdict(list)
    for t in trips:
        months[(t["started_at"] or t["ended_at"])[:7]].append(t)
    out = []
    for month, group in sorted(months.items()):
        used = [t for t in group if t["energy_kwh"] and t["distance_km"]]
        dist = sum(t["distance_km"] for t in used)
        out.append({"month": month, "kwh_100km": round(sum(t["energy_kwh"] for t in used) / dist * 100, 1) if dist else None,
                    "km": round(sum(t["distance_km"] or 0 for t in group), 2), "trips": len(group)})
    return out


def _annual_distance(conn, vid: int) -> tuple[dict | None, int]:
    """A year's distance at the pace the odometer showed over (at most) the last 365 days of readings."""
    def reading(order: str, since: str = ""):
        return conn.execute("SELECT recorded_at, mileage_km FROM snapshots WHERE vehicle_id=? AND mileage_km IS NOT NULL "
                            f"AND recorded_at >= ? ORDER BY recorded_at {order} LIMIT 1", (vid, since)).fetchone()

    def when(row):
        return datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))

    first, last = reading("ASC"), reading("DESC")
    if first is None:
        return None, 0
    tracked = (when(last) - when(first)).days
    start = reading("ASC", (when(last) - timedelta(days=PROJECTION_WINDOW_DAYS)).isoformat())
    days = (when(last) - when(start)).days
    if days < PROJECTION_MIN_DAYS:
        return None, tracked
    return {"annual_km": round((last["mileage_km"] - start["mileage_km"]) / days * 365), "days": days}, tracked


# connection -> (vehicle, tz offset) -> (newest reading it was computed from, result)
_range_cache: WeakKeyDictionary = WeakKeyDictionary()


def projected_range(conn, vid: int, tz_offset: int = 0) -> dict:
    """The reported range scaled to 100 % SoC: one median per local day, outliers removed by median absolute deviation.

    The Battery page asks every 30 s and years of readings take most of a second, so the answer is kept until a reading
    is added or removed. Callers must not change the dict they get."""
    stamp = tuple(conn.execute("SELECT COUNT(*), MAX(id) FROM snapshots WHERE vehicle_id=?", (vid,)).fetchone())
    cache = _range_cache.setdefault(conn, {})
    cached = cache.get((vid, tz_offset))
    if cached is None or cached[0] != stamp:
        cached = cache[(vid, tz_offset)] = (stamp, _compute_range(conn, vid, tz_offset))
    return cached[1]


def _compute_range(conn, vid: int, tz_offset: int) -> dict:
    low, high = RANGE_PLAUSIBLE_KM
    by_day: dict[date, list[float]] = defaultdict(list)
    for s in conn.execute("SELECT recorded_at, soc, range_km FROM snapshots WHERE vehicle_id=? AND soc>=? AND range_km>0",
                          (vid, RANGE_MIN_SOC)):
        km = s["range_km"] / s["soc"] * 100
        if low <= km <= high:
            by_day[_local(s["recorded_at"], tz_offset).date()].append(km)

    days = sorted(by_day)
    daily: dict[date, tuple[float, int]] = {}
    rejected = start = end = 0
    for day in days:
        while days[start] < day - timedelta(days=RANGE_MEDIAN_HALF_WINDOW):
            start += 1
        while end < len(days) and days[end] <= day + timedelta(days=RANGE_MEDIAN_HALF_WINDOW):
            end += 1
        window = [v for d in days[start:end] for v in by_day[d]]
        centre = statistics.median(window)
        spread = max(statistics.median(abs(v - centre) for v in window), centre * RANGE_MAD_FLOOR)
        kept = [v for v in by_day[day] if abs(v - centre) <= RANGE_MAD_FACTOR * spread]
        rejected += len(by_day[day]) - len(kept)
        if kept:
            daily[day] = (round(statistics.median(kept), 1), len(kept))

    out = [{"day": d.isoformat(), "range_km": km, "samples": n} for d, (km, n) in daily.items()]
    return {"samples": sum(n for _, n in daily.values()), "rejected": rejected, "daily": out,
            "latest": out[-1] if out else None, "trend_km_per_year": _trend(daily),
            "degradation": _window_change(daily)}


def _trend(daily: dict[date, tuple[float, int]]) -> float | None:
    if len(daily) < TREND_MIN_DAYS or (max(daily) - min(daily)).days < TREND_MIN_SPAN_DAYS:
        return None
    first = min(daily)
    fit = statistics.linear_regression([(d - first).days for d in daily], [km for km, _ in daily.values()])
    return round(fit.slope * 365, 1) + 0.0  # + 0.0 turns -0.0 into 0.0


def _window_change(daily: dict[date, tuple[float, int]]) -> dict | None:
    """The first against the last 90 days, once they are separate and both have enough days with data."""
    if not daily:
        return None
    first_end = min(daily) + timedelta(days=WINDOW_DAYS - 1)
    last_start = max(daily) - timedelta(days=WINDOW_DAYS - 1)
    first = [km for d, (km, _) in daily.items() if d <= first_end]
    last = [km for d, (km, _) in daily.items() if d >= last_start]
    if last_start <= first_end or min(len(first), len(last)) < WINDOW_MIN_DAYS:
        return None
    a, b = statistics.median(first), statistics.median(last)
    return {"first_km": round(a, 1), "last_km": round(b, 1), "change_pct": round((b - a) / a * 100, 1) + 0.0,
            "first_days": len(first), "last_days": len(last)}
