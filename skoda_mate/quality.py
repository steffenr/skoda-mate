"""Data-quality report and its repairs: derived-data problems found with read-only SQL, fixed by `fix()`.
No FastAPI, no clock, no network.

`checks()` and `fix()` take the current time as an argument; stored timestamps are UTC ISO strings (api_calls.at is epoch seconds).
Every count is the number of findings; samples are the five most recent. The `fix` hint names a repair action (the
constants below) or is None when no repair exists.
"""
from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timedelta

from . import activity, merge, messages, recorder

# Repair action names (the allowlist of the fix endpoint is built from the same constants).
CLOSE_OPEN_TRIPS = "close_open_trips"
CLOSE_OPEN_CHARGES = "close_open_charges"
REPAIR_CHARGES = "repair_charges"
INFER_CHARGES = "infer_charges"
DEDUPE_TRIPS = "dedupe_trips"
ACTIONS = (CLOSE_OPEN_TRIPS, CLOSE_OPEN_CHARGES, REPAIR_CHARGES, INFER_CHARGES, DEDUPE_TRIPS)

CHECKS = ("open_trips", "open_charges", "estimated_charges", "inferred_charges", "approx_trips",
          "reading_gaps", "odometer_jumps", "duplicate_trips", "api_errors", "stuck_operations", "missing_sections")

SECTIONS = ("info", "charging", "climate", "position")
# The API part (normalise.PARTS) behind a stored section, where one exists: its state says whether the car ever reports it.
SECTION_PARTS = {"charging": "charging", "climate": "airConditioning", "position": "parkingPosition"}
# Part states for "this car never reports it" (unsupported by the API, or absent from the answer without an error).
NEVER_REPORTED = ("unsupported", "missing")
# Operation statuses after which a request is settled (MyŠkoda operation events); anything else is still pending.
TERMINAL_STATUSES = ("COMPLETED_SUCCESS", "COMPLETED_WARNING", "ERROR")

OPEN_HOURS = 24
WINDOW_DAYS = 30
GAP_HOURS = 6
JUMP_KM = 1000
API_ERROR_HOURS = 24
STUCK_MINUTES = 30
SAMPLES = 5

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# One definition each, shared by the checks and the fixes so they cannot drift apart.
_OPEN_ROWS = "ended_at IS NULL AND started_at < ?"
_DUPLICATE_GROUPS = ("SELECT MIN(id) AS id, started_at, GROUP_CONCAT(id) AS ids FROM trips WHERE vehicle_id=? "
                     "AND started_at >= ? AND distance_km IS NOT NULL GROUP BY started_at, ROUND(distance_km, 1) "
                     "HAVING COUNT(*) > 1")


def _findings(table: str, where: str) -> str:
    """The rows of one trip or charge check (params: vid, then the `where` arguments)."""
    return f"SELECT id, started_at FROM {table} WHERE vehicle_id=? AND {where}"


def _day(iso: str | None) -> str:
    try:
        d = datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)[:10]
    return f"{d.day} {_MONTHS[d.month - 1]}"


def _day_time(when: datetime) -> str:
    return f"{when.day} {_MONTHS[when.month - 1]} {when:%H:%M}"


def _sample(label: str, href: str | None = None, **structured) -> dict:
    """A finding the card lists: `label` and `href` as before, plus structured fields (`kind` and its values) so the
    card can build a translated line instead of showing the English label."""
    return {"label": label, "href": href, **structured}


def _plural(n: int, one: str, many: str) -> str:
    return (one if n == 1 else many).format(n=n)


def _rows(conn, sql: str, args: tuple) -> list:
    return conn.execute(sql, args).fetchall()


def _count(conn, sql: str, args: tuple) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]


def _unreviewed(sql: str, args: tuple, col: str, after) -> tuple[str, tuple]:
    """A check's single definition narrowed to findings with `col` strictly after the review time `after` (unchanged
    when the check was never reviewed). The checks count with it and the repairs act through it, so a Fix changes
    exactly the findings the card counts."""
    if after is None:
        return sql, args
    return f"SELECT * FROM ({sql}) WHERE {col} > ?", (*args, after)


def _scan(conn, sql: str, args: tuple, order: str, col: str, after) -> tuple[int, int, list]:
    """One check's findings: (all in the window, those with `col` strictly after `after`, five most recent of those).
    `sql` is the check's single definition; the review bound wraps it, so it never forks the query."""
    total = _count(conn, sql, args)
    fsql, fargs = _unreviewed(sql, args, col, after)
    count = total if after is None else _count(conn, fsql, fargs)
    return total, count, _rows(conn, f"{fsql} ORDER BY {order} LIMIT ?", (*fargs, SAMPLES))


def _reviews(conn, vid: int) -> dict[str, tuple[str, str | None]]:
    return {r["check_id"]: (r["reviewed_at"], r["detail"])
            for r in _rows(conn, "SELECT check_id, reviewed_at, detail FROM quality_reviews WHERE vehicle_id=?", (vid,))}


def _consecutive(vid: int, since: str, column: str | None) -> tuple[str, tuple]:
    """(SQL, params) over consecutive snapshots ending in the window (optionally only those with `column` set), each
    with the previous one. The newest reading before the window is the lead row, so a gap or jump that ends inside the
    window is found; one that ended before it is not (only `at >= since` rows come out)."""
    cond = f" AND {column} IS NOT NULL" if column else ""
    cols = f", {column} AS v, LAG({column}) OVER (ORDER BY recorded_at, id) AS pv" if column else ""
    out = ", v, pv" if column else ""
    lead = (f"SELECT id FROM snapshots WHERE vehicle_id=? AND recorded_at < ?{cond} "
            f"ORDER BY recorded_at DESC, id DESC LIMIT 1")
    sql = (f"SELECT at, prev{out} FROM (SELECT recorded_at AS at, LAG(recorded_at) OVER (ORDER BY recorded_at, id) "
           f"AS prev{cols} FROM snapshots WHERE vehicle_id=? AND (recorded_at >= ? OR id = ({lead})){cond}) "
           f"WHERE at >= ?")
    return sql, (vid, since, vid, since, since)


def checks(conn, vid: int, now_iso: str) -> list[dict]:
    now = datetime.fromisoformat(now_iso)
    open_before = (now - timedelta(hours=OPEN_HOURS)).isoformat()
    since = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    stuck_before = (now - timedelta(minutes=STUCK_MINUTES)).isoformat()
    errors_since = (now - timedelta(hours=API_ERROR_HOURS)).timestamp()
    reviews = _reviews(conn, vid)
    epochs = {cid: datetime.fromisoformat(at).timestamp() for cid, (at, _) in reviews.items()}  # parsed once per run
    out: list[dict] = []

    def add(cid: str, severity: str, summary: tuple[str, str], scan: tuple[int, int, list], sample,
            fix: str | None = None, visible: bool = True) -> None:
        """`summary` is (singular, plural) with `{n}`; `visible` False keeps a check in the API but off the card."""
        total, count, rows = scan
        out.append({"id": cid, "severity": severity, "count": count, "summary": _plural(count, *summary),
                    "samples": [sample(r) for r in rows], "fix": fix,
                    "reviewed_at": reviews[cid][0] if cid in reviews else None, "total": total, "visible": visible})

    def after(cid: str, as_epoch: bool = False):
        """The review time a finding must be strictly newer than (None when the check was never reviewed)."""
        if cid not in reviews:
            return None
        return epochs[cid] if as_epoch else reviews[cid][0]

    def kind(cid: str, severity: str, summary: tuple[str, str], table: str, prefix: str, route: str, where: str, args: tuple,
             fix: str | None = None) -> None:
        sql = _findings(table, where)
        add(cid, severity, summary,
            _scan(conn, sql, (vid, *args), "started_at DESC, id DESC", "started_at", after(cid)),
            lambda r: _sample(f"{prefix} #{r['id']}, {_day(r['started_at'])}", f"#/{route}/{r['id']}",
                           kind=prefix.lower(), id=r["id"], at=r["started_at"]), fix)

    kind("open_trips", "important", ("{n} trip never ended", "{n} trips never ended"), "trips", "Trip", "trips",
         _OPEN_ROWS, (open_before,), CLOSE_OPEN_TRIPS)
    kind("open_charges", "important", ("{n} charge never ended", "{n} charges never ended"), "charges", "Charge",
         "charges", _OPEN_ROWS, (open_before,), CLOSE_OPEN_CHARGES)
    # No fix: a guessed end is how most live charges close, and REPAIR_CHARGES only replays charges with reading gaps.
    kind("estimated_charges", "info", ("{n} charge with an estimated end", "{n} charges with an estimated end"),
         "charges", "Charge", "charges", "end_estimated = 1 AND started_at >= ?", (since,))
    kind("inferred_charges", "info", ("{n} charge inferred from battery readings",
                                      "{n} charges inferred from battery readings"),
         "charges", "Charge", "charges", "source = 'inferred' AND started_at >= ?", (since,))
    # approx=1 means an odometer-jump trip, a merge with such a part, or a trip ended by close_open_trips: stay neutral.
    kind("approx_trips", "info", ("{n} approximate trip", "{n} approximate trips"), "trips", "Trip", "trips",
         "approx = 1 AND started_at >= ?", (since,))

    def hours_between(start: str, end: str) -> int:
        return round((datetime.fromisoformat(end).timestamp() - datetime.fromisoformat(start).timestamp()) / 3600)

    def gap(r) -> dict:
        hours = hours_between(r["prev"], r["at"])
        if r["silence"]:
            return _sample(f"Silent for {hours} h since {_day(r['prev'])}", kind="silence", **{"from": r["prev"]},
                           to=r["at"], hours=hours)
        return _sample(f"Gap of {hours} h, {_day(r['at'])}", kind="gap", **{"from": r["prev"]}, to=r["at"],
                       hours=hours)

    over = f"CAST(strftime('%s', {{a}}) AS INTEGER) - CAST(strftime('%s', {{b}}) AS INTEGER) > {GAP_HOURS * 3600}"
    inner, inner_args = _consecutive(vid, since, None)
    # Two kinds of finding share one query, so the count, the review bound and the samples stay a single definition:
    # a gap between two readings (found when the later one arrived: `found` = `at`) and the silence since the newest
    # reading (`at` = now; `found` = that reading, so a review stays valid until the car speaks again).
    gaps = (f"SELECT at, prev, at AS found, 0 AS silence FROM ({inner}) WHERE prev IS NOT NULL AND "
            + over.format(a="at", b="prev") + " UNION ALL SELECT ? AS at, last AS prev, last AS found, 1 AS silence "
            "FROM (SELECT MAX(recorded_at) AS last FROM snapshots WHERE vehicle_id=?) WHERE last IS NOT NULL AND "
            + over.format(a="?", b="last"))
    add("reading_gaps", "important",
        (f"{{n}} gap of more than {GAP_HOURS} h between readings", f"{{n}} gaps of more than {GAP_HOURS} h between readings"),
        _scan(conn, gaps, (*inner_args, now_iso, vid, now_iso), "at DESC", "found", after("reading_gaps")), gap)

    jinner, jargs = _consecutive(vid, since, "mileage_km")
    jumps = f"SELECT at, v, pv FROM ({jinner}) WHERE pv IS NOT NULL AND (v < pv OR v - pv > {JUMP_KM})"
    add("odometer_jumps", "important", ("{n} odometer jump or decrease", "{n} odometer jumps or decreases"),
        _scan(conn, jumps, jargs, "at DESC", "at", after("odometer_jumps")),
        lambda r: _sample(f"Odometer {r['pv']:g} to {r['v']:g} km, {_day(r['at'])}", kind="odometer",
                           from_km=r["pv"], to_km=r["v"], at=r["at"]))

    add("duplicate_trips", "important", ("{n} group of duplicate trips", "{n} groups of duplicate trips"),
        _scan(conn, _DUPLICATE_GROUPS, (vid, since), "started_at DESC, id DESC", "started_at", after("duplicate_trips")),
        lambda r: _sample(f"Trip #{r['id']}, {_day(r['started_at'])}", f"#/trips/{r['id']}", kind="trip", id=r["id"],
                           at=r["started_at"]), DEDUPE_TRIPS)

    def api_error(r) -> dict:
        when = datetime.fromtimestamp(r["at"], now.tzinfo)
        return _sample(f"{r['endpoint']} failed, {_day_time(when)}", kind="api_error", endpoint=r["endpoint"],
                       at=when.isoformat())

    errors = "SELECT id, at, endpoint FROM api_calls WHERE vehicle_id=? AND ok = 0 AND at >= ?"
    add("api_errors", "info", ("{n} API error in the last 24 h", "{n} API errors in the last 24 h"),
        _scan(conn, errors, (vid, errors_since), "at DESC, id DESC", "at", after("api_errors", as_epoch=True)), api_error)

    marks = ",".join("?" * len(TERMINAL_STATUSES))
    stuck = (f"SELECT id, name, status, updated_at FROM operations WHERE vehicle_id=? "
             f"AND UPPER(status) NOT IN ({marks}) AND updated_at < ?")
    # Hidden on the card: nothing writes `operations` (the official API answers with a bodiless 202), so this cannot fire
    # today. It stays in the API, in its place, so existing clients and the review contract keep working.
    add("stuck_operations", "important", ("{n} operation stuck for over 30 min", "{n} operations stuck for over 30 min"),
        _scan(conn, stuck, (vid, *TERMINAL_STATUSES, stuck_before), "updated_at DESC, id DESC", "updated_at",
              after("stuck_operations")),
        lambda r: _sample(f"Operation {r['name']} ({r['status']}), {_day(r['updated_at'])}"), visible=False)

    # No finding time: a review remembers the names missing back then, and only other names count afterwards.
    missing = _missing_sections(conn, vid)
    seen = set(json.loads(reviews["missing_sections"][1] or "[]")) if "missing_sections" in reviews else set()
    fresh = [name for name in missing if name not in seen]
    add("missing_sections", "info", ("{n} data section missing", "{n} data sections missing"),
        (len(missing), len(fresh), fresh),
        lambda name: _sample(f"Section {name} missing", kind="section", name=name))
    return out


def _missing_sections(conn, vid: int) -> list[str]:
    """The sections never stored for this car, except those it never reports at all: a car without a charging part
    (combustion) or without any answer for one (`part_state`, written by every poll) is not missing data."""
    rows = {r["key"]: r["json"] for r in _rows(conn, "SELECT key, json FROM vehicle_state WHERE vehicle_id=?", (vid,))}
    states = json.loads(rows.get("part_state") or "{}")
    return [name for name in SECTIONS if name not in rows
            and states.get(SECTION_PARTS.get(name, "")) not in NEVER_REPORTED]


# ------------------------------------------------------------------------------------------------------- repairs
# Each repair takes (conn, vid, now_iso) and returns how many rows (or duplicate groups) it changed. The three close and
# dedupe repairs act only on the findings their check counts: after a review, only those newer than it. The repairs end
# rows the way the live recorder would have (recorder._trips / recorder._charge) and do not commit on their own: `fix`
# commits the repair together with its event. `repair_charges` and `infer_charges` reuse recorder functions that
# commit themselves. No action loses data: `dedupe_trips` folds the extra rows of an exact duplicate group into the
# kept row's `merged_json` (restorable with Unmerge on the trip page), and `infer_charges` only replaces unedited
# inferred rows, exactly as every poll already does.

# A definite end (activity.PARKED / activity.NOT_CHARGING) is defined once, next to the timeline that ends open rows
# on the same readings, so a closed row and the timeline's estimate of it agree.
_PARKED = activity.PARKED
_NOT_CHARGING = activity.NOT_CHARGING


def _minutes(start: str, end: str) -> int:
    return max(0, round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60))


def _open_before(now_iso: str) -> str:
    return (datetime.fromisoformat(now_iso) - timedelta(hours=OPEN_HOURS)).isoformat()


def _review_time(conn, vid: int, check: str) -> str | None:
    """When `check` was last marked as reviewed (None if never): a repair leaves findings up to then alone."""
    return _reviews(conn, vid).get(check, (None, None))[0]


def _open_findings(conn, vid: int, table: str, check: str, now_iso: str) -> list:
    """The open rows `check` counts right now: old enough and, once reviewed, newer than the review."""
    sql, args = _unreviewed(_findings(table, _OPEN_ROWS), (vid, _open_before(now_iso)), "started_at",
                            _review_time(conn, vid, check))
    return conn.execute(sql, args).fetchall()


def _reading_at(conn, vid: int, since: str, where: str, first: bool) -> str | None:
    """The first (or last) reading time of this car at or after `since` that matches `where` (a constant above)."""
    agg = "MIN" if first else "MAX"
    return conn.execute(f"SELECT {agg}(recorded_at) FROM snapshots WHERE vehicle_id=? AND recorded_at >= ? AND {where}",
                        (vid, since)).fetchone()[0]


def _close_open_trips(conn, vid: int, now_iso: str) -> int:
    """End = the first PARKED reading after the start, else the last reading (an unknown state never ends a drive,
    but the car was heard from until then), else the start itself."""
    rows = _open_findings(conn, vid, "trips", "open_trips", now_iso)
    for r in rows:
        start = r["started_at"]
        end = _reading_at(conn, vid, start, _PARKED, True) or _reading_at(conn, vid, start, "1", False) or start
        conn.execute("UPDATE trips SET ended_at=?, duration_min=?, approx=1 WHERE id=? AND vehicle_id=?",
                     (end, _minutes(start, end), r["id"], vid))
    return len(rows)


def _close_open_charges(conn, vid: int, now_iso: str) -> int:
    """End = the first definitely-not-charging reading after the start, else the last CHARGING reading (what the
    recorder's stale close uses), else the start. The end is a guess either way, so `end_estimated = 1`."""
    rows = _open_findings(conn, vid, "charges", "open_charges", now_iso)
    for r in rows:
        start = r["started_at"]
        end = (_reading_at(conn, vid, start, _NOT_CHARGING, True) or _reading_at(conn, vid, start, "charging = 1", False)
               or start)
        conn.execute("UPDATE charges SET ended_at=?, duration_min=?, end_estimated=1 WHERE id=? AND vehicle_id=?",
                     (end, _minutes(start, end), r["id"], vid))
    return len(rows)


def _repair_charges(conn, vid: int, now_iso: str) -> int:
    return recorder.repair_charge_gaps(conn, vid)


def _infer_charges(conn, vid: int, now_iso: str) -> int:
    return recorder.infer_charges(conn, vid, days=WINDOW_DAYS)


def _parts(row) -> list[dict]:
    """The original rows a trip stands for: its own `merged_json` parts if it was merged before, else itself."""
    return json.loads(row["merged_json"]) if row["merged_json"] else [{k: row[k] for k in merge.PART_COLS}]


def _dedupe_trips(conn, vid: int, now_iso: str) -> int:
    """Fold exact duplicates into their lowest-id row, which keeps its numbers (duplicates describe one drive, so
    nothing is summed, unlike `merge.merge`). Every original row, including the parts of an extra row that was merged
    itself, goes into `merged_json`, so `merge.unmerge` restores them and the importer does not bring them back. Notes
    of the extra rows are added to the kept row's note, as a merge does."""
    since = (datetime.fromisoformat(now_iso) - timedelta(days=WINDOW_DAYS)).isoformat()
    sql, args = _unreviewed(_DUPLICATE_GROUPS, (vid, since), "started_at", _review_time(conn, vid, "duplicate_trips"))
    groups = [sorted(int(i) for i in g["ids"].split(",")) for g in conn.execute(sql, args)]
    done = 0
    for ids in groups:
        rows = conn.execute(f"SELECT * FROM trips WHERE vehicle_id=? AND id IN ({','.join('?' * len(ids))}) ORDER BY id",
                            (vid, *ids)).fetchall()
        if len(rows) < 2:
            continue
        keep, extra = rows[0], rows[1:]
        parts = [p for r in rows for p in _parts(r)]
        note = " · ".join(dict.fromkeys(r["note"].strip() for r in rows if r["note"] and r["note"].strip())) or None
        conn.execute("UPDATE trips SET merged_json=?, note=? WHERE id=? AND vehicle_id=?",
                     (json.dumps(parts), note, keep["id"], vid))
        conn.execute(f"DELETE FROM trips WHERE vehicle_id=? AND id IN ({','.join('?' * len(extra))})",
                     (vid, *[r["id"] for r in extra]))
        done += 1
    return done


_FIXES = {
    CLOSE_OPEN_TRIPS: (_close_open_trips, "Closed {n} open trips."),
    CLOSE_OPEN_CHARGES: (_close_open_charges, "Closed {n} open charges."),
    REPAIR_CHARGES: (_repair_charges, "Repaired {n} charges."),
    INFER_CHARGES: (_infer_charges, "Added {n} inferred charges."),
    DEDUPE_TRIPS: (_dedupe_trips, "Merged {n} groups of duplicate trips."),
}


def _atomic(conn):
    """Hold the connection's lock for a whole repair or review: SafeConnection locks per statement, so without this
    another thread (the poller) could write between the repair's statements and its event row. `nullcontext` for a
    plain sqlite3 connection, which has no lock of its own."""
    return conn.locked() if hasattr(conn, "locked") else nullcontext()


def fix(conn, vid: int, action: str, now_iso: str) -> dict:
    """Run one repair for one vehicle and log it. Raises ValueError("Unknown action.") for anything outside ACTIONS."""
    if action not in _FIXES:
        raise ValueError(messages.QUALITY_UNKNOWN_ACTION)
    run, message = _FIXES[action]
    with _atomic(conn):
        try:
            changed = run(conn, vid, now_iso)
            conn.execute("INSERT INTO events(vehicle_id,at,kind,detail) VALUES(?,?,?,?)",
                         (vid, now_iso, "quality_fix", f"{action}:{changed}"))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"action": action, "changed": changed, "message": message.format(n=changed)}


def review(conn, vid: int, check: str, reviewed: bool, now_iso: str) -> dict:
    """Mark one check of one vehicle as reviewed at `now_iso` (again: the time moves forward) or clear the review, and
    log it. `missing_sections` also stores the names missing now. Raises ValueError("Unknown check.") outside CHECKS."""
    if check not in CHECKS:
        raise ValueError(messages.QUALITY_UNKNOWN_CHECK)
    with _atomic(conn):
        _review(conn, vid, check, reviewed, now_iso)
    return {"check": check, "reviewed_at": now_iso if reviewed else None}


def _review(conn, vid: int, check: str, reviewed: bool, now_iso: str) -> None:
    try:
        if reviewed:
            detail = json.dumps(_missing_sections(conn, vid)) if check == "missing_sections" else None
            conn.execute("INSERT INTO quality_reviews(vehicle_id,check_id,reviewed_at,detail) VALUES(?,?,?,?) "
                         "ON CONFLICT(vehicle_id,check_id) DO UPDATE SET reviewed_at=excluded.reviewed_at, "
                         "detail=excluded.detail", (vid, check, now_iso, detail))
        else:
            conn.execute("DELETE FROM quality_reviews WHERE vehicle_id=? AND check_id=?", (vid, check))
        conn.execute("INSERT INTO events(vehicle_id,at,kind,detail) VALUES(?,?,?,?)",
                     (vid, now_iso, "quality_review", f"{check}:{'on' if reviewed else 'off'}"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
