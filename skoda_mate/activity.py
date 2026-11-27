"""Activity intervals: readings, trips and charges of one time range as a single non-overlapping list.

`intervals()` and `timeline()` are read-only and return plain dicts; a refused range is a `ValueError` the router turns
into a 400. Every interval says where it came from (`source`) and whether its boundaries were measured or inferred
(`estimated`), so the timeline never presents a guess as a reading.
"""
from __future__ import annotations

import bisect
import statistics
from datetime import UTC, date, datetime, timedelta

from . import costs, places, presenters

KINDS = ("drive", "charge", "climate", "aux", "vent", "parked", "unknown")
CAP_DAYS = 31  # the timeline refuses a longer range
REVERSED_RANGE = "The start must be before the end."  # the 400 for a reversed range (German in static/i18n/de.json)
LIMIT_31 = "The range is limited to 31 days."  # German in static/i18n/de.json
BAD_MIN_HOURS = "min_hours must be greater than 0."  # German in static/i18n/de.json
GAP_H = 6.0  # a reading gap longer than this is unknown, not parked


class RangeError(ValueError):
    """A refused range or parameter; the routes turn exactly this into a 400 (any other ValueError is a bug)."""

_SNAPSHOT_COLUMNS = "id, recorded_at, soc, charging, in_motion, climate_state, aux_state, vent_state, lat, lon"


def heating_states() -> set[str]:
    """The climate states that mean the car is conditioning; OFF, IDLE and UNKNOWN are not among them."""
    return {"COOLING", "HEATING", "HEATING_AUXILIARY", "PREHEATING", "VENTILATION"}


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _minutes(start: str, end: str) -> int:
    return round((_dt(end) - _dt(start)).total_seconds() / 60)


def _interval(kind: str, start: str, end: str, *, source: str, estimated: bool,
              trip_id: int | None = None, charge_id: int | None = None, place: str | None = None) -> dict:
    return {"kind": kind, "start": start, "end": end, "minutes": _minutes(start, end), "source": source,
            "trip_id": trip_id, "charge_id": charge_id, "place": place, "estimated": estimated}


def _kind(row) -> str:
    """The state of the car at the earlier reading of a segment, in the spec's precedence order."""
    if row["in_motion"]:
        return "drive"
    if row["charging"]:
        return "charge"
    heating = heating_states()
    if row["climate_state"] in heating:
        return "climate"
    if row["aux_state"] in heating:
        return "aux"
    if row["vent_state"] in heating:
        return "vent"
    return "parked"


def _clip(start: str, end: str, lo: str, hi: str) -> tuple[str, str] | None:
    """Clip one span to `[lo, hi)`, keeping the original strings; None when nothing is left."""
    s, e = _dt(start), _dt(end)
    if e <= _dt(lo) or s >= _dt(hi):
        return None
    if s < _dt(lo):
        start = lo
    if e > _dt(hi):
        end = hi
    return start, end


def _segment(row, start: str, end: str, start_iso: str, end_iso: str) -> dict | None:
    """One reading-to-reading span, clipped to the range and classified by its earlier reading.

    The gap test uses the span before clipping: a long silence that only partly falls inside the range is still
    unknown, never parked."""
    bounds = _clip(start, end, start_iso, end_iso)
    if bounds is None:
        return None
    if (_dt(end) - _dt(start)).total_seconds() > GAP_H * 3600:
        return _interval("unknown", *bounds, source="gap", estimated=True)
    return _interval(_kind(row), *bounds, source="reading", estimated=True)


def _segments(conn, vid: int, start_iso: str, end_iso: str) -> list[dict]:
    """Base intervals from the readings: the one before the range, the ones inside, and the trailing edge."""
    before = conn.execute(f"SELECT {_SNAPSHOT_COLUMNS} FROM snapshots WHERE vehicle_id=? AND recorded_at < ? "
                          "ORDER BY recorded_at DESC, id DESC LIMIT 1", (vid, start_iso)).fetchone()
    rows = list(conn.execute(f"SELECT {_SNAPSHOT_COLUMNS} FROM snapshots WHERE vehicle_id=? AND recorded_at >= ? "
                             "AND recorded_at < ? ORDER BY recorded_at, id", (vid, start_iso, end_iso)))
    if before is not None:
        rows.insert(0, before)
    if not rows:
        return []
    out: list[dict] = []
    first = rows[0]["recorded_at"]
    if _dt(start_iso) < _dt(first):  # nothing seen before the first reading in the range
        segment = _segment(rows[0], start_iso, first, start_iso, end_iso)
        if segment is not None:
            out.append(segment)
    for i, row in enumerate(rows):
        end = rows[i + 1]["recorded_at"] if i + 1 < len(rows) else end_iso
        if _dt(end) <= _dt(row["recorded_at"]):
            continue
        segment = _segment(row, row["recorded_at"], end, start_iso, end_iso)
        if segment is not None:
            out.append(segment)
    return out


def _subtract(intervals: list[dict], start: str, end: str) -> list[dict]:
    """Remove `[start, end)` from every interval, splitting those it cuts; an empty or reversed span is a no-op."""
    a, b = _dt(start), _dt(end)
    if b <= a:
        return list(intervals)
    out: list[dict] = []
    for iv in intervals:
        s, e = _dt(iv["start"]), _dt(iv["end"])
        if e <= a or s >= b:
            out.append(iv)
            continue
        if s < a:
            out.append({**iv, "end": start})
        if e > b:
            out.append({**iv, "start": end})
    return out


def _last_reading(conn, vid: int, start_iso: str, end_iso: str) -> str | None:
    """The newest reading in (start_iso, end_iso): the evidence an open trip or charge can end on."""
    row = conn.execute("SELECT MAX(recorded_at) FROM snapshots WHERE vehicle_id=? AND recorded_at > ? "
                       "AND recorded_at < ?", (vid, start_iso, end_iso)).fetchone()
    return row[0] if row is not None else None


# A definite end, as the live recorder reads it: in_motion=0 is PARKED (NULL is unknown); a charge ends on a reading
# with a known charge state or an unplugged cable (charging is stored as 0 when the section is missing). One definition
# each: the timeline ends an open row on them, and the quality repairs close open rows with them.
PARKED = "in_motion = 0"
NOT_CHARGING = "COALESCE(charging, 0) = 0 AND (charge_state IS NOT NULL OR plug_connected = 0)"


def _row_end(conn, vid: int, row, ends_on: str, last_reading: str | None, end_iso: str) -> str | None:
    """A row's end: its own ended_at; for an open row the first reading after its start and inside the range that
    definitely ends it (`ends_on`: PARKED or NOT_CHARGING), else the last reading in the range. The lookup stops at the
    range end (a later definite end changes nothing the range can show); open rows are few, so it stays per row.

    Without the first rule a trip or charge nobody closed would stretch over every later week. None when an open row
    has neither and starts at or after the last reading: without evidence of how it ended it must be dropped."""
    if row["ended_at"] is not None:
        return row["ended_at"]
    first = conn.execute(f"SELECT MIN(recorded_at) FROM snapshots WHERE vehicle_id=? AND recorded_at > ? "
                         f"AND recorded_at < ? AND {ends_on}", (vid, row["started_at"], end_iso)).fetchone()[0]
    if first is not None:
        return first
    if last_reading is None or _dt(last_reading) <= _dt(row["started_at"]):
        return None
    return last_reading if _dt(last_reading) <= _dt(end_iso) else end_iso


def _span(conn, vid: int, row, ends_on: str, last_reading: str | None, end_iso: str) -> tuple[str, str] | None:
    """A trip or charge row's `(start, end)`; None for a reversed row or an open one with no reading after its start,
    which must not cut the base (nor exclude a parked stand)."""
    end = _row_end(conn, vid, row, ends_on, last_reading, end_iso)
    if end is None or _dt(end) <= _dt(row["started_at"]):
        return None
    return row["started_at"], end


# The trips and charges that overlap `[start, end)`; params (vid, end_iso, start_iso). One definition each, shared by
# the timeline overlay and the parked-loss exclusion so the two never disagree about what was busy.
_OVERLAPPING = ("WHERE vehicle_id=? AND started_at < ? AND (ended_at IS NULL OR ended_at > ?) "
                "ORDER BY started_at, id")
_CHARGE_ROWS = f"SELECT id, started_at, ended_at, lat, lon FROM charges {_OVERLAPPING}"
_TRIP_ROWS = f"SELECT id, started_at, ended_at, end_place FROM trips {_OVERLAPPING}"


def _charge_interval(conn, vid: int, row, start_iso: str, end_iso: str, last_reading: str | None) -> dict | None:
    span = _span(conn, vid, row, NOT_CHARGING, last_reading, end_iso)
    bounds = _clip(*span, start_iso, end_iso) if span is not None else None
    if bounds is None:
        return None
    match = places.match(conn, row["lat"], row["lon"])
    return _interval("charge", *bounds, source="charge", estimated=row["ended_at"] is None,
                     charge_id=row["id"], place=match["name"] if match else None)


def _trip_interval(conn, vid: int, row, start_iso: str, end_iso: str, last_reading: str | None) -> dict | None:
    span = _span(conn, vid, row, PARKED, last_reading, end_iso)
    bounds = _clip(*span, start_iso, end_iso) if span is not None else None
    if bounds is None:
        return None
    # An open trip's end is inferred from the readings, so it is estimated like an open charge.
    return _interval("drive", *bounds, source="trip", estimated=row["ended_at"] is None, trip_id=row["id"],
                     place=row["end_place"])


def _merge(intervals: list[dict]) -> list[dict]:
    """Sort by start and join touching intervals with the same kind, source and id."""
    out: list[dict] = []
    for iv in sorted(intervals, key=lambda iv: _dt(iv["start"])):
        prev = out[-1] if out else None
        if (prev is not None and _dt(prev["end"]) == _dt(iv["start"]) and prev["kind"] == iv["kind"]
                and prev["source"] == iv["source"] and prev["trip_id"] == iv["trip_id"]
                and prev["charge_id"] == iv["charge_id"]):
            prev["end"] = iv["end"]
        else:
            out.append(iv)
    return out


def intervals(conn, vid: int, start_iso: str, end_iso: str) -> list[dict]:
    """Activity intervals in `[start_iso, end_iso)`, clipped, non-overlapping, merged and sorted by start.

    Readings give the base; trips and charges are laid over them (a trip wins where both claim the same time)."""
    if _dt(end_iso) <= _dt(start_iso):
        return []
    # Merge the reading segments first: a long range is tens of thousands of reading spans but only a few runs a day,
    # and every trip and charge below is laid over the whole list.
    base = _merge(_segments(conn, vid, start_iso, end_iso))
    last_reading = _last_reading(conn, vid, start_iso, end_iso)
    for row in conn.execute(_CHARGE_ROWS, (vid, end_iso, start_iso)):
        charge = _charge_interval(conn, vid, row, start_iso, end_iso, last_reading)
        if charge is None:
            continue
        # Lay the charge over everything so far: charges are ordered by start, so the later one wins an overlap.
        base = _subtract(base, charge["start"], charge["end"]) + [charge]
    for row in conn.execute(_TRIP_ROWS, (vid, end_iso, start_iso)):
        trip = _trip_interval(conn, vid, row, start_iso, end_iso, last_reading)
        if trip is None:
            continue
        # Drive wins over every other kind where a trip and a charge overlap.
        base = _subtract(base, trip["start"], trip["end"]) + [trip]
    merged = _merge([iv for iv in base if _dt(iv["end"]) > _dt(iv["start"])])
    for iv in merged:
        iv["minutes"] = _minutes(iv["start"], iv["end"])
    return merged


# ---------------------------------------------------------------- timeline: local days

_BUCKET = {"drive": "drive_min", "charge": "charge_min", "climate": "climate_min", "aux": "climate_min",
           "vent": "climate_min", "parked": "parked_min", "unknown": "unknown_min"}
_MINUTE_BUCKETS = ("drive_min", "charge_min", "climate_min", "parked_min", "unknown_min")


def _empty_summary() -> dict:
    return {"drive_min": 0, "charge_min": 0, "climate_min": 0, "parked_min": 0, "unknown_min": 0,
            "km": 0.0, "kwh": 0.0, "cost": None, "cost_partial": False}



def _bound(day: date, tz_offset: int) -> str:
    """The UTC instant of a local midnight (the presenters helper also raises the 400 for a bad date)."""
    bound = presenters.local_bound(day.isoformat(), tz_offset)
    assert bound is not None
    return bound


def _now(now: datetime | None) -> datetime:
    """The fixed test instant, or the wall clock in UTC; a naive datetime is taken as UTC."""
    if now is None:
        return datetime.now(UTC)
    return now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)


def _local_date(ts: str, tz_offset: int) -> str:
    """The local day an ISO timestamp belongs to; JS tz_offset is minutes (UTC minus local)."""
    return (_dt(ts) - timedelta(minutes=tz_offset)).date().isoformat()


def _split(items: list[dict], bounds: list[tuple[str, str, str]], days: list[dict]) -> None:
    """Cut every interval at local midnights; a piece keeps its fields and gets its own bounds and minutes.

    A piece's minutes are the difference of its two boundaries rounded from the day's start, not its own rounded
    length: touching pieces then telescope, so a day's buckets add up to the minutes covered even when every piece
    alone is under a minute."""
    for iv in items:
        for (_, day_start, day_end), day in zip(bounds, days, strict=True):
            clipped = _clip(iv["start"], iv["end"], day_start, day_end)
            if clipped is None:
                continue
            start, end = clipped
            minutes = _minutes(day_start, end) - _minutes(day_start, start)
            if minutes > 0:
                day["intervals"].append({**iv, "start": start, "end": end, "minutes": minutes})


def timeline(conn, vid: int, from_day: str, to_day: str, tz_offset: int = 0,
             now: datetime | None = None, tariff: dict | None = None) -> dict:
    """A local-day timeline for `[from_day, to_day]` (inclusive): intervals per day plus exclusive minute buckets.

    Days are local dates, the window ends at `now`, and every day of the range is present even when nothing was
    recorded. `km`/`kwh`/`cost` belong to the day a trip or charge STARTED; a charge with no amount keeps the day's
    cost partial instead of pretending the total is complete. `climate_min` bundles climate, aux and vent (R7).
    """
    first, last = presenters.local_day(from_day), presenters.local_day(to_day)
    if last < first:
        raise RangeError(REVERSED_RANGE)
    if (last - first).days + 1 > CAP_DAYS:
        raise RangeError(LIMIT_31)
    start_iso = _bound(first, tz_offset)
    end_iso = _bound(last + timedelta(days=1), tz_offset)
    window_end = min(_dt(end_iso), _now(now)).isoformat()
    labels = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    bounds = [(label.isoformat(), _bound(label, tz_offset), _bound(label + timedelta(days=1), tz_offset))
              for label in labels]
    days: list[dict] = [{"date": label.isoformat(), "intervals": [], "summary": _empty_summary()}
                        for label in labels]
    _split(intervals(conn, vid, start_iso, window_end), bounds, days)

    tariff = costs.load_tariff(conn) if tariff is None else tariff
    known_places = places.list_places(conn)
    index = {day["date"]: i for i, day in enumerate(days)}
    km, kwh = [0.0] * len(days), [0.0] * len(days)
    known, has_known, partial = [0.0] * len(days), [False] * len(days), [False] * len(days)
    for row in conn.execute("SELECT started_at, distance_km FROM trips WHERE vehicle_id=? AND started_at >= ? "
                            "AND started_at < ?", (vid, start_iso, window_end)):
        i = index.get(_local_date(row["started_at"], tz_offset))
        if i is not None:
            km[i] += row["distance_km"] or 0
    for row in conn.execute("SELECT * FROM charges WHERE vehicle_id=? AND started_at >= ? AND started_at < ?",
                            (vid, start_iso, window_end)):
        i = index.get(_local_date(row["started_at"], tz_offset))
        if i is None:
            continue
        charge = dict(row)
        kwh[i] += charge["energy_kwh"] or 0
        amount = costs.charge_cost(charge, tariff, places.match(conn, charge["lat"], charge["lon"],
                                                                known_places))["amount"]
        if amount is None:
            partial[i] = True
        else:
            known[i] += amount
            has_known[i] = True

    for i, day in enumerate(days):
        summary: dict = day["summary"]
        for iv in day["intervals"]:
            summary[_BUCKET[iv["kind"]]] += iv["minutes"]
        summary["km"] = round(km[i], 1)
        summary["kwh"] = round(kwh[i], 2)
        summary["cost"] = round(known[i], 2) if has_known[i] else None
        summary["cost_partial"] = partial[i]

    total = _empty_summary()
    for key in _MINUTE_BUCKETS:
        total[key] = sum(day["summary"][key] for day in days)
    # From the rounded day values, so the week total is exactly what the day lines add up to.
    total["km"] = round(sum(day["summary"]["km"] for day in days), 1)
    total["kwh"] = round(sum(day["summary"]["kwh"] for day in days), 2)
    total["cost"] = round(sum(day["summary"]["cost"] or 0 for day in days), 2) if any(has_known) else None
    total["cost_partial"] = any(partial)
    return {"from": first.isoformat(), "to": last.isoformat(), "days": days, "summary": total}


# ---------------------------------------------------------------- parked loss

RUN_GAP_H = 1.0  # a parked run survives at most this long between two readings
UNRECORDED_CHARGE = "likely an unrecorded charge"
_MAX_PLAUSIBLE_DELTA = 20  # percentage points lost in one stand; more is a charge nobody recorded


def _runs(conn, vid: int, from_iso: str, to_iso: str) -> list[list]:
    """Runs of consecutive parked readings (SoC known, not moving, not charging) with gaps of at most an hour."""
    runs: list[list] = []
    current: list = []
    for row in conn.execute("SELECT recorded_at, soc, charging, in_motion, lat, lon FROM snapshots WHERE vehicle_id=? "
                            "AND recorded_at >= ? AND recorded_at < ? ORDER BY recorded_at, id",
                            (vid, from_iso, to_iso)):
        if row["soc"] is None or row["in_motion"] or row["charging"]:
            if current:
                runs.append(current)
            current = []
            continue
        if current and (_dt(row["recorded_at"]) - _dt(current[-1]["recorded_at"])).total_seconds() > RUN_GAP_H * 3600:
            runs.append(current)
            current = []
        current.append(row)
    if current:
        runs.append(current)
    return runs


def _session(conn, run: list, capacity_kwh: float | None, tariff: dict, known_places: list[dict]) -> dict:
    first, last = run[0], run[-1]
    hours = (_dt(last["recorded_at"]) - _dt(first["recorded_at"])).total_seconds() / 3600
    delta = first["soc"] - last["soc"]
    kwh = round(delta / 100 * capacity_kwh, 2) if capacity_kwh else None
    warning = UNRECORDED_CHARGE if delta < 0 or delta > _MAX_PLAUSIBLE_DELTA else None
    located = next((r for r in run if r["lat"] is not None and r["lon"] is not None), None)
    lat, lon = (located["lat"], located["lon"]) if located else (None, None)
    match = places.match(conn, lat, lon, known_places) if located else None
    cost, basis = None, "none"
    if kwh is not None and warning is None:
        # Energy only: the minutes of a stand are not charging minutes, and no session was started.
        priced = costs.energy_cost({"energy_kwh": kwh, "lat": lat, "lon": lon}, tariff, match)
        cost, basis = priced["amount"], priced["basis"]
        if cost is None:
            # A stand below the floor has no amount to price, but it sits at a place or under a tariff like any
            # other: name the basis that would have priced one measurable kWh there.
            basis = costs.energy_cost({"energy_kwh": 1.0, "lat": lat, "lon": lon}, tariff, match)["basis"]
    return {"start": first["recorded_at"], "end": last["recorded_at"], "hours": round(hours, 2),
            "place": match["name"] if match else None, "start_soc": first["soc"], "end_soc": last["soc"],
            "soc_delta": delta, "kwh": kwh,
            "kwh_per_day": round(kwh / (hours / 24), 2) if kwh is not None else None,
            "cost": cost, "cost_basis": basis, "warning": warning, "below_detection_floor": delta == 0}


def _aggregates(sessions: list[dict], to_iso: str) -> dict:
    valid = [s for s in sessions if s["warning"] is None and s["kwh"] is not None]
    end = _dt(to_iso)

    def total(rows: list[dict]) -> float | None:
        """None when no stand counts (nothing was measured), 0.0 when every counted stand stayed below the floor."""
        return round(sum(s["kwh"] for s in rows), 2) if rows else None

    def recent(days: int) -> float | None:
        return total([s for s in valid if end - timedelta(days=days) <= _dt(s["end"]) <= end])

    rates = [s["kwh_per_day"] for s in valid]
    amounts = [s["cost"] for s in valid if s["cost"] is not None]
    return {"count": len(valid), "flagged": sum(1 for s in sessions if s["warning"] is not None),
            "median_kwh_per_day": round(statistics.median(rates), 2) if rates else None,
            "mean_kwh_per_day": round(statistics.fmean(rates), 2) if rates else None,
            "kwh": total(valid), "kwh_7d": recent(7), "kwh_30d": recent(30),
            "cost": round(sum(amounts), 2) if amounts else None}


def parked_page(result: dict, limit: int, offset: int) -> dict:
    """One page of a `parked_loss` answer, newest stand first. The aggregates still cover the whole period."""
    newest = result["sessions"][::-1]  # computed in time order
    return {**result, "sessions": newest[offset:offset + limit], "total": len(newest), "limit": limit, "offset": offset}


def _busy(conn, vid: int, from_iso: str, to_iso: str) -> list[tuple[datetime, datetime]]:
    """The time trips and charges claim in the range, as sorted disjoint spans (ends ascending, for bisect).

    Built from the rows alone, with the same end rule as the timeline: a moving or charging reading already ends a
    parked run, so the reading-derived drive and charge spans of `intervals()` could never exclude a stand."""
    last_reading = _last_reading(conn, vid, from_iso, to_iso)
    spans = sorted((_dt(span[0]), _dt(span[1])) for sql, ends_on in ((_TRIP_ROWS, PARKED), (_CHARGE_ROWS, NOT_CHARGING))
                   for row in conn.execute(sql, (vid, to_iso, from_iso))
                   if (span := _span(conn, vid, row, ends_on, last_reading, to_iso)) is not None)
    out: list[tuple[datetime, datetime]] = []
    for s, e in spans:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def parked_loss(conn, vid: int, from_iso: str, to_iso: str, min_hours: float = 6.0,
                capacity_kwh: float | None = None, tariff: dict | None = None) -> dict:
    """SoC lost while parked, as sessions of at least `min_hours` in `[from_iso, to_iso)` plus aggregates.

    A stand that overlaps a drive or charge (an unrecorded charge shows up as a charge row) is dropped rather than
    counted, so a hole in the readings can never inflate the loss. A drop of 0 points is below the detection floor
    (one SoC step), never a decimal loss; a rise or a drop over 20 points is flagged and left out of the aggregates.
    A range that ends before it starts, or a `min_hours` of 0 or less, is a RangeError (the route's 400)."""
    if min_hours <= 0:
        raise RangeError(BAD_MIN_HOURS)
    if _dt(to_iso) <= _dt(from_iso):
        raise RangeError(REVERSED_RANGE)
    tariff = costs.load_tariff(conn) if tariff is None else tariff
    busy = _busy(conn, vid, from_iso, to_iso)
    busy_ends = [e for _, e in busy]
    known_places = places.list_places(conn)
    sessions: list[dict] = []
    for run in _runs(conn, vid, from_iso, to_iso):
        start, end = _dt(run[0]["recorded_at"]), _dt(run[-1]["recorded_at"])
        if (end - start).total_seconds() < min_hours * 3600:
            continue
        # Interior overlap with the first busy span ending after the start; touching at an edge is fine.
        i = bisect.bisect_right(busy_ends, start)
        if i < len(busy) and busy[i][0] < end:
            continue
        sessions.append(_session(conn, run, capacity_kwh, tariff, known_places))
    return {"sessions": sessions, "aggregates": _aggregates(sessions, to_iso), "min_hours": min_hours,
            "detection_floor_kwh": round(capacity_kwh / 100, 2) if capacity_kwh else None}
