"""Data-quality report (derived-data problems, counted exactly, read-only) and its repair actions."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from skoda_mate import merge, quality, recorder, schema

from .test_activity import _vid
from .test_inferred import make as make_car
from .test_inferred import trip as inferred_trip
from .test_recorder import _old_charge_with_a_night_gap
from .test_web import connected

NOW = datetime(2027, 3, 10, 12, 0, tzinfo=UTC)
NOW_ISO = NOW.isoformat()


def _ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _setup():
    conn = schema.connect(":memory:")
    return conn, _vid(conn)


def _trip(conn, vid, hours_ago, *, ended=True, distance=10.0, approx=0, cid=None):
    cur = conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km,approx) VALUES(?,?,?,?,?,?)",
                       (vid, cid or f"t{vid}-{hours_ago}-{distance}-{approx}-{ended}", _ts(hours_ago),
                        _ts(hours_ago - 0.5) if ended else None, distance, approx))
    conn.commit()
    return cur.lastrowid


def _charge(conn, vid, hours_ago, *, ended=True, estimated=0, source="detected"):
    cur = conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,end_estimated,source) VALUES(?,?,?,?,?)",
                       (vid, _ts(hours_ago), _ts(hours_ago - 1) if ended else None, estimated, source))
    conn.commit()
    return cur.lastrowid


def _snap(conn, vid, hours_ago, mileage=None):
    conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,mileage_km) VALUES(?,?,?)", (vid, _ts(hours_ago), mileage))
    conn.commit()


def _by_id(items):
    return {c["id"]: c for c in items}


def test_empty_database_returns_every_check_in_order_with_zero_counts():
    conn, vid = _setup()
    items = quality.checks(conn, vid, NOW_ISO)
    assert [c["id"] for c in items] == list(quality.CHECKS)
    for c in items:
        assert set(c) == {"id", "severity", "count", "summary", "samples", "fix", "reviewed_at", "total", "visible"}
        assert c["visible"] is (c["id"] != "stuck_operations")
        assert c["total"] == c["count"] and c["reviewed_at"] is None
        if c["id"] == "missing_sections":
            assert c["count"] == 4
        else:
            assert c["count"] == 0 and c["samples"] == []


def test_fixture_reports_exact_counts_severities_samples_and_hints():
    conn, vid = _setup()
    open_trip = _trip(conn, vid, 30, ended=False)
    open_charge = _charge(conn, vid, 30, ended=False)
    est = _charge(conn, vid, 50, estimated=1)
    inf = _charge(conn, vid, 60, source="inferred")
    approx = _trip(conn, vid, 70, approx=1)
    d1 = _trip(conn, vid, 80, distance=12.34, cid="a")
    _trip(conn, vid, 80, distance=12.31, cid="b")
    # reading gap of 7 h and an odometer decrease
    _snap(conn, vid, 100, 1000)
    _snap(conn, vid, 99, 1010)
    _snap(conn, vid, 92, 1005)
    for h in range(86, 0, -6):  # heard from every 6 h since: no further gap, and no silence now
        _snap(conn, vid, h)
    conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok,error) VALUES(?,?,?,0,'boom')",
                 (vid, (NOW - timedelta(hours=2)).timestamp(), "get_vehicle"))
    conn.execute("INSERT INTO operations(vehicle_id,request_id,name,status,at,updated_at) VALUES(?,?,?,?,?,?)",
                 (vid, "r1", "start-air-conditioning", "IN_PROGRESS", _ts(1), _ts(40 / 60)))
    for k in ("info", "charging", "climate"):
        conn.execute("INSERT INTO vehicle_state(vehicle_id,key,json,fetched_at) VALUES(?,?,?,?)", (vid, k, "{}", _ts(0)))
    conn.commit()

    c = _by_id(quality.checks(conn, vid, NOW_ISO))
    expected = {
        "open_trips": ("important", "1 trip never ended", f"#/trips/{open_trip}"),
        "open_charges": ("important", "1 charge never ended", f"#/charges/{open_charge}"),
        "estimated_charges": ("info", "1 charge with an estimated end", f"#/charges/{est}"),
        "inferred_charges": ("info", "1 charge inferred from battery readings", f"#/charges/{inf}"),
        "approx_trips": ("info", "1 approximate trip", f"#/trips/{approx}"),
        "reading_gaps": ("important", "1 gap of more than 6 h between readings", None),
        "odometer_jumps": ("important", "1 odometer jump or decrease", None),
        "duplicate_trips": ("important", "1 group of duplicate trips", f"#/trips/{d1}"),
        "api_errors": ("info", "1 API error in the last 24 h", None),
        "stuck_operations": ("important", "1 operation stuck for over 30 min", None),
        "missing_sections": ("info", "1 data section missing", None),
    }
    for cid, (sev, summary, href) in expected.items():
        assert (c[cid]["severity"], c[cid]["count"], c[cid]["summary"]) == (sev, 1, summary), cid
        assert len(c[cid]["samples"]) == 1 and c[cid]["samples"][0]["href"] == href, cid
    assert c["missing_sections"]["samples"] == [{"label": "Section position missing", "href": None, "kind": "section",
                                                 "name": "position"}]
    assert c["open_trips"]["samples"][0]["label"] == f"Trip #{open_trip}, 9 Mar"
    assert c["open_charges"]["samples"][0]["label"] == f"Charge #{open_charge}, 9 Mar"
    # The structured fields the card translates from, as the real backend builds them (not a mocked payload)
    gap = c["reading_gaps"]["samples"][0]
    assert {k: gap[k] for k in ("kind", "from", "to", "hours")} == {"kind": "gap", "from": _ts(99), "to": _ts(92), "hours": 7}
    odo = c["odometer_jumps"]["samples"][0]
    assert {k: odo[k] for k in ("kind", "from_km", "to_km", "at")} == {"kind": "odometer", "from_km": 1010, "to_km": 1005, "at": _ts(92)}
    dup = c["duplicate_trips"]["samples"][0]
    assert (dup["kind"], dup["id"], dup["at"]) == ("trip", d1, _ts(80)) and dup["href"] == f"#/trips/{d1}"
    err = c["api_errors"]["samples"][0]
    assert {k: err[k] for k in ("kind", "endpoint", "at")} == {"kind": "api_error", "endpoint": "get_vehicle", "at": _ts(2)}
    fixes = {cid: c[cid]["fix"] for cid in c}
    assert fixes["open_trips"] == quality.CLOSE_OPEN_TRIPS
    assert fixes["open_charges"] == quality.CLOSE_OPEN_CHARGES
    assert fixes["duplicate_trips"] == quality.DEDUPE_TRIPS
    assert [k for k, v in fixes.items() if v is None] == [
        "estimated_charges", "inferred_charges", "approx_trips", "reading_gaps", "odometer_jumps", "api_errors", "stuck_operations",
        "missing_sections"]


def test_thresholds_exclude_recent_old_and_terminal_rows():
    conn, vid = _setup()
    _trip(conn, vid, 23, ended=False)  # open under 24 h: still in progress
    _charge(conn, vid, 23, ended=False)
    _charge(conn, vid, 24 * 31, estimated=1)  # older than 30 days
    _trip(conn, vid, 24 * 31, approx=1)
    conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok) VALUES(?,?,?,0)",
                 (vid, (NOW - timedelta(hours=25)).timestamp(), "get_vehicle"))
    conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok) VALUES(?,?,?,1)",
                 (vid, (NOW - timedelta(hours=1)).timestamp(), "get_vehicle"))
    for i, (status, age) in enumerate([("IN_PROGRESS", 20 / 60), ("COMPLETED_SUCCESS", 5), ("ERROR", 5)]):
        conn.execute("INSERT INTO operations(vehicle_id,request_id,name,status,at,updated_at) VALUES(?,?,?,?,?,?)",
                     (vid, f"r{i}", "x", status, _ts(age), _ts(age)))
    _snap(conn, vid, 10, 100)
    _snap(conn, vid, 4, 1900)  # exactly 6 h apart is not a gap; +1800 km is a jump
    conn.commit()
    c = _by_id(quality.checks(conn, vid, NOW_ISO))
    for cid in ("open_trips", "open_charges", "estimated_charges", "approx_trips", "api_errors", "stuck_operations",
                "reading_gaps"):
        assert c[cid]["count"] == 0, cid
    assert c["odometer_jumps"]["count"] == 1


def test_odometer_rise_of_exactly_1000_is_fine_and_a_decrease_is_not():
    conn, vid = _setup()
    _snap(conn, vid, 5, 100)
    _snap(conn, vid, 4, 1100)
    _snap(conn, vid, 3, 1099)
    _snap(conn, vid, 2, None)  # a reading without mileage is skipped, not a break
    _snap(conn, vid, 1, 1100)
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["odometer_jumps"]["count"] == 1


def test_counts_are_exact_and_samples_capped_at_five_most_recent_first():
    conn, vid = _setup()
    ids = [_trip(conn, vid, 30 + i * 24, ended=False, distance=i) for i in range(8)]
    for i in range(8):  # 7 gaps: snapshots 8 h apart
        _snap(conn, vid, 10 + i * 8, 100)
    _snap(conn, vid, 4, 100)  # heard from recently: no silence on top of the 7 gaps
    c = _by_id(quality.checks(conn, vid, NOW_ISO))
    assert c["open_trips"]["count"] == 8 and c["open_trips"]["summary"] == "8 trips never ended"
    assert [s["href"] for s in c["open_trips"]["samples"]] == [f"#/trips/{i}" for i in ids[:5]]
    assert c["reading_gaps"]["count"] == 7 and len(c["reading_gaps"]["samples"]) == 5
    assert c["reading_gaps"]["samples"][0]["label"].startswith("Gap of 8 h")


def test_duplicate_groups_count_once_each():
    conn, vid = _setup()
    for cid in "abc":  # one group of three
        _trip(conn, vid, 50, distance=5.04, cid=cid)
    for cid in "de":  # a second group
        _trip(conn, vid, 60, distance=7.0, cid=cid)
    _trip(conn, vid, 70, distance=7.0, cid="f")  # same distance, other start: not a duplicate
    c = _by_id(quality.checks(conn, vid, NOW_ISO))
    assert c["duplicate_trips"]["count"] == 2


def test_another_vehicle_never_leaks():
    conn, vid = _setup()
    conn.execute("INSERT INTO vehicles(vin) VALUES('OTHER')")
    other = conn.execute("SELECT id FROM vehicles WHERE vin='OTHER'").fetchone()[0]
    _trip(conn, other, 30, ended=False)
    _charge(conn, other, 30, ended=False, estimated=1)
    conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok) VALUES(?,?,?,0)", (other, NOW.timestamp(), "x"))
    conn.execute("INSERT INTO operations(vehicle_id,request_id,name,status,at,updated_at) VALUES(?,?,?,?,?,?)",
                 (other, "r", "x", "IN_PROGRESS", _ts(5), _ts(5)))
    conn.execute("INSERT INTO vehicle_state(vehicle_id,key,json,fetched_at) VALUES(?,?,?,?)", (vid, "info", "{}", _ts(0)))
    conn.commit()
    mine = quality.checks(conn, vid, NOW_ISO)
    assert [c["count"] for c in mine] == [0] * 10 + [3]
    theirs = _by_id(quality.checks(conn, other, NOW_ISO))
    assert theirs["open_trips"]["count"] == 1 and theirs["open_charges"]["count"] == 1
    assert theirs["stuck_operations"]["count"] == 1 and theirs["api_errors"]["count"] == 1
    assert theirs["missing_sections"]["count"] == 4


def test_route_requires_a_session():
    c, conn, api, vid = connected()
    c.cookies.clear()
    assert c.get(f"/api/vehicles/{vid}/quality").status_code == 401


def test_route_other_vehicle_404():
    c, conn, api, vid = connected()
    r = c.get("/api/vehicles/999/quality")
    assert r.status_code == 404 and r.json()["detail"] == "no such vehicle"


def test_route_returns_the_shape_and_writes_nothing():
    c, conn, api, vid = connected()
    before = conn._c.total_changes
    r = c.get(f"/api/vehicles/{vid}/quality")
    assert r.status_code == 200
    body = r.json()
    assert datetime.fromisoformat(body["checked_at"]).tzinfo is not None
    assert [x["id"] for x in body["checks"]] == list(quality.CHECKS)
    assert conn._c.total_changes == before


# ------------------------------------------------------------------------------------------------------- fixes

def _reading(conn, vid, hours_ago, charging=0, *, state=None, plug=None, moving=None):
    """A snapshot as the recorder stores it: `charging` is 0 when the car said nothing, so only `state` (charge_state)
    or `plug` (plug_connected=0) makes a non-charging reading definite; `moving` is in_motion (None = unknown)."""
    conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,charging,charge_state,plug_connected,in_motion) "
                 "VALUES(?,?,?,?,?,?)", (vid, _ts(hours_ago), charging, state, plug, moving))
    conn.commit()


def _other(conn):
    conn.execute("INSERT INTO vehicles(vin) VALUES('OTHER')")
    return conn.execute("SELECT id FROM vehicles WHERE vin='OTHER'").fetchone()[0]


def _events(conn, vid):
    return [tuple(r) for r in conn.execute("SELECT at, kind, detail FROM events WHERE vehicle_id=? AND kind='quality_fix' "
                                           "ORDER BY id", (vid,))]


def _counts(conn):
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("trips", "charges", "snapshots"))


def test_close_open_trips_touches_only_old_open_rows():
    conn, vid = _setup()
    other = _other(conn)
    old = _trip(conn, vid, 30, ended=False)
    recent = _trip(conn, vid, 5, ended=False)
    done = _trip(conn, vid, 50, distance=7.0)
    theirs = _trip(conn, other, 30, ended=False)
    _reading(conn, vid, 31)  # before the trip started: ignored
    _reading(conn, vid, 29)
    _reading(conn, vid, 20)  # the last reading of this car at or after the start
    _reading(conn, other, 2)  # another car's later reading is ignored
    snapshot = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM trips")}
    res = quality.fix(conn, vid, quality.CLOSE_OPEN_TRIPS, NOW_ISO)
    assert res == {"action": "close_open_trips", "changed": 1, "message": "Closed 1 open trips."}
    t = dict(conn.execute("SELECT * FROM trips WHERE id=?", (old,)).fetchone())
    assert t["ended_at"] == _ts(20) and t["duration_min"] == 600 and t["approx"] == 1
    for tid in (recent, done, theirs):
        assert dict(conn.execute("SELECT * FROM trips WHERE id=?", (tid,)).fetchone()) == snapshot[tid]


def test_close_open_trips_without_a_later_reading_ends_at_the_start():
    conn, vid = _setup()
    old = _trip(conn, vid, 30, ended=False)
    assert quality.fix(conn, vid, quality.CLOSE_OPEN_TRIPS, NOW_ISO)["changed"] == 1
    t = conn.execute("SELECT ended_at, duration_min, approx FROM trips WHERE id=?", (old,)).fetchone()
    assert tuple(t) == (_ts(30), 0, 1)


def test_close_open_charges_uses_first_non_charging_reading():
    conn, vid = _setup()
    other = _other(conn)
    old = _charge(conn, vid, 30, ended=False)
    recent = _charge(conn, vid, 5, ended=False)
    theirs = _charge(conn, other, 30, ended=False)
    _reading(conn, vid, 29, 1)
    _reading(conn, vid, 28, 1)
    _reading(conn, vid, 27, 0, state="READY_FOR_CHARGING")  # the first reading that is definitely not charging
    _reading(conn, vid, 20, 0, state="READY_FOR_CHARGING")
    before = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM charges")}
    res = quality.fix(conn, vid, quality.CLOSE_OPEN_CHARGES, NOW_ISO)
    assert res == {"action": "close_open_charges", "changed": 1, "message": "Closed 1 open charges."}
    c = dict(conn.execute("SELECT * FROM charges WHERE id=?", (old,)).fetchone())
    assert c["ended_at"] == _ts(27) and c["duration_min"] == 180 and c["end_estimated"] == 1
    for cid in (recent, theirs):
        assert dict(conn.execute("SELECT * FROM charges WHERE id=?", (cid,)).fetchone()) == before[cid]


def test_close_open_charges_falls_back_to_the_last_charging_reading_then_the_start():
    conn, vid = _setup()
    old = _charge(conn, vid, 30, ended=False)
    quality.fix(conn, vid, quality.CLOSE_OPEN_CHARGES, NOW_ISO)
    assert tuple(conn.execute("SELECT ended_at, duration_min FROM charges WHERE id=?", (old,)).fetchone()) == (_ts(30), 0)
    conn2, vid2 = _setup()
    old2 = _charge(conn2, vid2, 30, ended=False)
    _reading(conn2, vid2, 29, 1)
    _reading(conn2, vid2, 28, 1)  # no definite end: the last charging reading is the end, like a stale close
    _reading(conn2, vid2, 10, 0)  # charging section missing: unknown, says nothing about the charge
    quality.fix(conn2, vid2, quality.CLOSE_OPEN_CHARGES, NOW_ISO)
    assert tuple(conn2.execute("SELECT ended_at, duration_min FROM charges WHERE id=?", (old2,)).fetchone()) == (_ts(28), 120)


def test_close_open_charges_ignores_readings_without_a_charge_state():
    """The recorder stores charging=0 when the charging section is missing; the live recorder does not end a charge on
    such a reading, so neither does the repair. A known state or an unplugged cable is definite."""
    conn, vid = _setup()
    old = _charge(conn, vid, 30, ended=False)
    _reading(conn, vid, 29, 1)
    _reading(conn, vid, 28, 0)  # unknown
    _reading(conn, vid, 27, 0, state="READY_FOR_CHARGING")
    quality.fix(conn, vid, quality.CLOSE_OPEN_CHARGES, NOW_ISO)
    assert conn.execute("SELECT ended_at FROM charges WHERE id=?", (old,)).fetchone()[0] == _ts(27)
    conn2, vid2 = _setup()
    old2 = _charge(conn2, vid2, 30, ended=False)
    _reading(conn2, vid2, 29, 1)
    _reading(conn2, vid2, 28, 0)  # unknown
    _reading(conn2, vid2, 26, 0, plug=0)  # unplugged: definite even without a state
    quality.fix(conn2, vid2, quality.CLOSE_OPEN_CHARGES, NOW_ISO)
    assert tuple(conn2.execute("SELECT ended_at, duration_min FROM charges WHERE id=?", (old2,)).fetchone()) == (_ts(26), 240)


def test_closes_rows_the_recorder_left_open_when_polling_stopped():
    """Real ingested readings: a charge and a drive are open, the next readings miss the charging/position parts (the
    recorder keeps both open), then the server stops. The repair ends them where the recorder would have."""
    conn, vid = make_car()
    day = "2026-01-01T{}:00+00:00"
    for ts, soc in ((day.format("10:00"), 20), (day.format("11:00"), 40)):
        recorder.ingest(conn, vid, {"ts": ts, "soc": soc, "charging": True, "charge_state": "CHARGING",
                                    "charge_power_kw": 10.0, "charge_type": "AC"})
    recorder.ingest(conn, vid, {"ts": day.format("11:30"), "soc": 45})  # charging part missing: unknown
    recorder.ingest(conn, vid, {"ts": day.format("13:00"), "in_motion": True, "mileage_km": 1000.0})
    recorder.ingest(conn, vid, {"ts": day.format("13:20"), "mileage_km": 1010.0})  # position part missing
    assert conn.execute("SELECT charging FROM snapshots WHERE recorded_at=?", (day.format("11:30"),)).fetchone()[0] == 0
    (charge,) = conn.execute("SELECT id FROM charges WHERE ended_at IS NULL").fetchall()
    (trip,) = conn.execute("SELECT id, started_at FROM trips WHERE ended_at IS NULL").fetchall()
    now = "2026-01-03T12:00:00+00:00"
    names = {c["id"]: c for c in quality.checks(conn, vid, now)}
    assert names["open_trips"]["count"] == 1 and names["open_charges"]["count"] == 1
    assert quality.fix(conn, vid, quality.CLOSE_OPEN_CHARGES, now)["changed"] == 1
    assert quality.fix(conn, vid, quality.CLOSE_OPEN_TRIPS, now)["changed"] == 1
    c = conn.execute("SELECT ended_at, duration_min, end_estimated FROM charges WHERE id=?", (charge[0],)).fetchone()
    assert tuple(c) == (day.format("11:00"), 60, 1)  # the last CHARGING reading, not the unknown one after it
    t = conn.execute("SELECT ended_at, approx FROM trips WHERE id=?", (trip["id"],)).fetchone()
    assert tuple(t) == (day.format("13:20"), 1)


def test_close_open_trips_ends_at_the_first_parked_reading():
    """Like the live recorder: a definite PARKED reading ends the drive, an unknown motion state does not."""
    conn, vid = _setup()
    old = _trip(conn, vid, 30, ended=False)
    _reading(conn, vid, 29, moving=1)
    _reading(conn, vid, 28)  # in_motion unknown
    _reading(conn, vid, 27, moving=0)  # first definite PARKED
    _reading(conn, vid, 20, moving=0)
    quality.fix(conn, vid, quality.CLOSE_OPEN_TRIPS, NOW_ISO)
    t = conn.execute("SELECT ended_at, duration_min, approx FROM trips WHERE id=?", (old,)).fetchone()
    assert tuple(t) == (_ts(27), 180, 1)


def test_close_fixes_touch_exactly_the_rows_the_check_names():
    conn, vid = _setup()
    trips = [_trip(conn, vid, 30 + i, ended=False, distance=i) for i in range(3)]
    charges = [_charge(conn, vid, 30 + i, ended=False) for i in range(2)]
    _trip(conn, vid, 10, ended=False)  # under 24 h: still running, not named
    _charge(conn, vid, 10, ended=False)
    c = _by_id(quality.checks(conn, vid, NOW_ISO))
    named_trips = {int(s["href"].rsplit("/", 1)[1]) for s in c["open_trips"]["samples"]}
    named_charges = {int(s["href"].rsplit("/", 1)[1]) for s in c["open_charges"]["samples"]}
    assert named_trips == set(trips) and named_charges == set(charges)
    open_before = {r[0] for r in conn.execute("SELECT id FROM trips WHERE ended_at IS NULL")}
    assert quality.fix(conn, vid, c["open_trips"]["fix"], NOW_ISO)["changed"] == c["open_trips"]["count"]
    assert open_before - {r[0] for r in conn.execute("SELECT id FROM trips WHERE ended_at IS NULL")} == named_trips
    assert quality.fix(conn, vid, c["open_charges"]["fix"], NOW_ISO)["changed"] == c["open_charges"]["count"]
    still_open = {r[0] for r in conn.execute("SELECT id FROM charges WHERE ended_at IS NULL")}
    assert still_open.isdisjoint(named_charges) and len(still_open) == 1
    after = _by_id(quality.checks(conn, vid, NOW_ISO))
    assert after["open_trips"]["count"] == 0 and after["open_charges"]["count"] == 0


def test_repair_charges_fills_energy_for_measured_rows_only():
    conn, vid = make_car()
    other = recorder.upsert_vehicle(conn, "TMBJB9NY5RF000002", "Enyaq", None, 77.0)
    _old_charge_with_a_night_gap(conn, vid)
    _old_charge_with_a_night_gap(conn, other)
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,source) VALUES(?,?,?,?,'inferred')",
                 (vid, "2026-01-01T21:26:00+00:00", "2026-01-02T05:27:00+00:00", 5.95))
    conn.commit()
    theirs = dict(conn.execute("SELECT * FROM charges WHERE vehicle_id=?", (other,)).fetchone())
    inferred = dict(conn.execute("SELECT * FROM charges WHERE source='inferred'").fetchone())
    res = quality.fix(conn, vid, quality.REPAIR_CHARGES, NOW_ISO)
    assert res["changed"] == 1 and res["message"] == "Repaired 1 charges."
    c = dict(conn.execute("SELECT * FROM charges WHERE vehicle_id=? AND source='detected'", (vid,)).fetchone())
    assert c["end_estimated"] == 1 and c["ended_at"] == "2026-01-01T22:23:47+00:00" and c["duration_min"] == 58
    assert abs(c["energy_kwh"] - (4 / 60 * 10.5 + 11 * 77 / 100 / 0.9)) < 1e-6
    assert dict(conn.execute("SELECT * FROM charges WHERE source='inferred'").fetchone()) == inferred
    assert dict(conn.execute("SELECT * FROM charges WHERE vehicle_id=?", (other,)).fetchone()) == theirs
    # idempotent, and the once-per-database startup repair is still available for the other car
    assert quality.fix(conn, vid, quality.REPAIR_CHARGES, NOW_ISO)["changed"] == 0
    assert recorder.repair_charge_gaps(conn) == 1
    assert conn.execute("SELECT end_estimated FROM charges WHERE vehicle_id=?", (other,)).fetchone()[0] == 1


def test_infer_charges_adds_an_inferred_row():
    conn, vid = make_car()
    other = recorder.upsert_vehicle(conn, "TMBJB9NY5RF000002", "Enyaq", None, 77.0)
    inferred_trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 36)
    inferred_trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 63, 52)
    inferred_trip(conn, other, "2026-11-22T07:00:00+00:00", "2026-11-22T07:30:00+00:00", 70, 36)
    inferred_trip(conn, other, "2026-11-23T08:00:00+00:00", "2026-11-23T08:30:00+00:00", 63, 52)
    res = quality.fix(conn, vid, quality.INFER_CHARGES, NOW_ISO)
    assert res == {"action": "infer_charges", "changed": 1, "message": "Added 1 inferred charges."}
    (c,) = conn.execute("SELECT * FROM charges WHERE vehicle_id=?", (vid,)).fetchall()
    assert c["source"] == "inferred" and c["start_soc"] == 36 and c["end_soc"] == 63
    assert conn.execute("SELECT COUNT(*) FROM charges WHERE vehicle_id=?", (other,)).fetchone()[0] == 0
    assert quality.fix(conn, vid, quality.INFER_CHARGES, NOW_ISO)["changed"] == 0


def _duplicates(conn, vid, prefix):
    ids = [_trip(conn, vid, 80, distance=12.34, cid=f"{prefix}a"), _trip(conn, vid, 80, distance=12.31, cid=f"{prefix}b"),
           _trip(conn, vid, 80, distance=12.3, cid=f"{prefix}c")]
    for i, tid in enumerate(ids):
        conn.execute("UPDATE trips SET energy_kwh=?, note=? WHERE id=?", (2.0 + i, f"n{i}", tid))
    conn.commit()
    return ids


def test_dedupe_trips_merges_duplicates():
    conn, vid = _setup()
    other = _other(conn)
    keep, dup1, dup2 = _duplicates(conn, vid, "m")
    theirs = _duplicates(conn, other, "o")
    single = _trip(conn, vid, 60, distance=5.0)
    originals = {t: dict(conn.execute("SELECT * FROM trips WHERE id=?", (t,)).fetchone()) for t in (keep, dup1, dup2)}
    res = quality.fix(conn, vid, quality.DEDUPE_TRIPS, NOW_ISO)
    assert res == {"action": "dedupe_trips", "changed": 1, "message": "Merged 1 groups of duplicate trips."}
    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM trips WHERE vehicle_id=?", (vid,))}
    assert sorted(rows) == [keep, single]
    k = rows[keep]
    assert k["distance_km"] == 12.34 and k["energy_kwh"] == 2.0 and k["ended_at"] == originals[keep]["ended_at"]
    parts = json.loads(k["merged_json"])
    assert [p["cloud_id"] for p in parts] == ["ma", "mb", "mc"]
    assert [p["distance_km"] for p in parts] == [12.34, 12.31, 12.3]
    assert conn.execute("SELECT COUNT(*) FROM trips WHERE vehicle_id=?", (other,)).fetchone()[0] == 3
    assert all(conn.execute("SELECT merged_json FROM trips WHERE id=?", (t,)).fetchone()[0] is None for t in theirs)
    # the importer would still recognise the removed rows as parts of the kept trip
    assert merge.merged_part_matches(conn, vid, _ts(80), 12.31) == keep
    assert quality.fix(conn, vid, quality.DEDUPE_TRIPS, NOW_ISO)["changed"] == 0
    restored = merge.unmerge(conn, vid, keep)
    assert len(restored) == 3
    back = sorted(r["distance_km"] for r in conn.execute("SELECT distance_km FROM trips WHERE vehicle_id=? AND started_at=?",
                                                         (vid, _ts(80))))
    assert back == [12.3, 12.31, 12.34]


def test_dedupe_extends_an_existing_merged_json():
    conn, vid = _setup()
    keep, dup, _ = _duplicates(conn, vid, "m")
    first = {k: None for k in merge.PART_COLS} | {"cloud_id": "orig", "started_at": _ts(80), "distance_km": 6.0}
    conn.execute("UPDATE trips SET merged_json=? WHERE id=?", (json.dumps([first]), keep))
    conn.commit()
    quality.fix(conn, vid, quality.DEDUPE_TRIPS, NOW_ISO)
    parts = json.loads(conn.execute("SELECT merged_json FROM trips WHERE id=?", (keep,)).fetchone()[0])
    assert [p["cloud_id"] for p in parts] == ["orig", "mb", "mc"]


def test_dedupe_keeps_the_parts_of_an_extra_row_that_was_itself_merged():
    conn, vid = _setup()
    keep, dup, last = _duplicates(conn, vid, "m")
    inner = [{k: None for k in merge.PART_COLS} | {"cloud_id": f"p{i}", "started_at": _ts(80 - i), "distance_km": 6.0}
             for i in range(2)]
    conn.execute("UPDATE trips SET merged_json=? WHERE id=?", (json.dumps(inner), dup))
    conn.commit()
    quality.fix(conn, vid, quality.DEDUPE_TRIPS, NOW_ISO)
    parts = json.loads(conn.execute("SELECT merged_json FROM trips WHERE id=?", (keep,)).fetchone()[0])
    assert [p["cloud_id"] for p in parts] == ["ma", "p0", "p1", "mc"]  # nothing the extra row carried is lost
    assert len(merge.unmerge(conn, vid, keep)) == 4


def test_dedupe_carries_the_notes_onto_the_kept_trip():
    conn, vid = _setup()
    keep, dup, last = _duplicates(conn, vid, "m")
    conn.execute("UPDATE trips SET note=? WHERE id=?", ("n0", last))  # same text twice: shown once
    conn.execute("UPDATE trips SET note=NULL WHERE id=?", (keep,))
    conn.commit()
    quality.fix(conn, vid, quality.DEDUPE_TRIPS, NOW_ISO)
    assert conn.execute("SELECT note FROM trips WHERE id=?", (keep,)).fetchone()[0] == "n1 · n0"


def test_dedupe_is_all_or_nothing(monkeypatch):
    """A failure halfway leaves every group as it was and logs nothing (no group is committed on its own)."""
    conn, vid = _setup()
    _duplicates(conn, vid, "m")
    for cid in "xy":
        _trip(conn, vid, 90, distance=3.0, cid=cid)
    before = [tuple(r) for r in conn.execute("SELECT * FROM trips ORDER BY id")]
    real, calls = json.dumps, []

    def flaky(obj, *a, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("disk full")
        return real(obj, *a, **kw)

    monkeypatch.setattr(quality.json, "dumps", flaky)
    with pytest.raises(RuntimeError):
        quality.fix(conn, vid, quality.DEDUPE_TRIPS, NOW_ISO)
    monkeypatch.undo()
    assert [tuple(r) for r in conn.execute("SELECT * FROM trips ORDER BY id")] == before
    assert _events(conn, vid) == []


def test_every_hinted_fix_clears_its_own_finding():
    """Run each fix a check offers on the fixture that has every finding; the open and duplicate findings go to zero,
    and the closes do not create new duplicates or open rows."""
    conn, vid = _setup()
    _trip(conn, vid, 30, ended=False)
    _charge(conn, vid, 30, ended=False)
    _duplicates(conn, vid, "m")
    _reading(conn, vid, 29, 1, moving=1)
    _reading(conn, vid, 27, 0, state="READY_FOR_CHARGING", moving=0)
    for check in ("open_trips", "open_charges", "duplicate_trips"):
        item = _by_id(quality.checks(conn, vid, NOW_ISO))[check]
        assert item["count"] >= 1, check
        res = quality.fix(conn, vid, item["fix"], NOW_ISO)
        assert res["changed"] == item["count"], check
        assert _by_id(quality.checks(conn, vid, NOW_ISO))[check]["count"] == 0, check
    after = _by_id(quality.checks(conn, vid, NOW_ISO))
    assert [after[k]["count"] for k in ("open_trips", "open_charges", "duplicate_trips")] == [0, 0, 0]
    assert after["estimated_charges"]["count"] == 1  # a closed charge is honest about its guessed end
    # a closed trip is approximate too; the label must not claim it came from an odometer jump
    assert (after["approx_trips"]["count"], after["approx_trips"]["summary"]) == (1, "1 approximate trip")


def test_each_fix_logs_one_event():
    for action in quality.ACTIONS:
        conn, vid = _setup()
        assert quality.fix(conn, vid, action, NOW_ISO)["changed"] == 0
        assert _events(conn, vid) == [(NOW_ISO, "quality_fix", f"{action}:0")]  # a no-op still logs
        quality.fix(conn, vid, action, NOW_ISO)
        assert len(_events(conn, vid)) == 2
    conn, vid = _setup()
    _trip(conn, vid, 30, ended=False)
    quality.fix(conn, vid, quality.CLOSE_OPEN_TRIPS, NOW_ISO)
    quality.fix(conn, vid, quality.CLOSE_OPEN_TRIPS, NOW_ISO)  # idempotent: nothing left to close
    assert [e[2] for e in _events(conn, vid)] == ["close_open_trips:1", "close_open_trips:0"]
    assert _events(conn, _other(conn)) == []


def test_unknown_action_is_400():
    conn, vid = _setup()
    with pytest.raises(ValueError, match="Unknown action."):
        quality.fix(conn, vid, "drop_database", NOW_ISO)
    assert _events(conn, vid) == []
    c, conn, api, vid = connected()
    r = c.post(f"/api/vehicles/{vid}/quality/fix", json={"action": "drop_database"})
    assert r.status_code == 400 and r.json()["detail"] == "Unknown action."


def test_fix_never_deletes_rows():
    for action in (quality.CLOSE_OPEN_TRIPS, quality.CLOSE_OPEN_CHARGES, quality.REPAIR_CHARGES, quality.INFER_CHARGES):
        conn, vid = _setup()
        _trip(conn, vid, 30, ended=False)
        _charge(conn, vid, 30, ended=False)
        _reading(conn, vid, 20)
        before = _counts(conn)
        quality.fix(conn, vid, action, NOW_ISO)
        after = _counts(conn)
        assert after[0] == before[0] and after[2] == before[2]
        assert after[1] >= before[1]
    conn, vid = _setup()
    keep, *removed = _duplicates(conn, vid, "m")
    _reading(conn, vid, 20)
    before = _counts(conn)
    quality.fix(conn, vid, quality.DEDUPE_TRIPS, NOW_ISO)
    after = _counts(conn)
    assert after == (before[0] - len(removed), before[1], before[2])
    assert len(merge.unmerge(conn, vid, keep)) == 3


def test_fix_hints_are_all_known_actions():
    conn, vid = _setup()
    hints = {c["fix"] for c in quality.checks(conn, vid, NOW_ISO)} - {None}
    assert hints == {quality.CLOSE_OPEN_TRIPS, quality.CLOSE_OPEN_CHARGES, quality.DEDUPE_TRIPS}
    assert hints <= set(quality.ACTIONS)


def test_an_estimated_end_offers_no_fix_because_repair_would_not_change_it():
    """A charge closed live with a guessed end is the normal case, and repair_charges only replays charges with gaps in
    their readings: a Fix button there would do nothing. The action stays available on the endpoint."""
    conn, vid = make_car()
    for ts, soc in (("2026-01-01T10:00:00+00:00", 20), ("2026-01-01T10:30:00+00:00", 30)):
        recorder.ingest(conn, vid, {"ts": ts, "soc": soc, "charging": True, "charge_state": "CHARGING",
                                    "charge_power_kw": 10.0, "remaining_min": 90})
    recorder.ingest(conn, vid, {"ts": "2026-01-01T15:00:00+00:00", "soc": 80, "charge_state": "READY_FOR_CHARGING"})
    now = "2026-01-02T12:00:00+00:00"
    item = _by_id(quality.checks(conn, vid, now))["estimated_charges"]
    assert item["count"] == 1 and item["fix"] is None
    assert quality.fix(conn, vid, quality.REPAIR_CHARGES, now)["changed"] == 0
    assert _by_id(quality.checks(conn, vid, now))["estimated_charges"]["count"] == 1


def test_fix_route_rejects_a_missing_or_malformed_action():
    c, conn, api, vid = connected()
    assert c.post(f"/api/vehicles/{vid}/quality/fix", json={}).status_code == 422
    assert c.post(f"/api/vehicles/{vid}/quality/fix", json={"action": ["close_open_trips"]}).status_code == 422
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='quality_fix'").fetchone()[0] == 0


def test_fix_route_requires_a_session():
    c, conn, api, vid = connected()
    c.cookies.clear()
    assert c.post(f"/api/vehicles/{vid}/quality/fix", json={"action": "close_open_trips"}).status_code == 401


def test_fix_route_other_vehicle_404():
    c, conn, api, vid = connected()
    r = c.post("/api/vehicles/999/quality/fix", json={"action": "close_open_trips"})
    assert r.status_code == 404 and r.json()["detail"] == "no such vehicle"


def test_fix_route_runs_the_action_and_logs_it():
    c, conn, api, vid = connected()
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "route-open", old))
    conn.commit()
    r = c.post(f"/api/vehicles/{vid}/quality/fix", json={"action": "close_open_trips"})
    assert r.status_code == 200
    assert r.json() == {"action": "close_open_trips", "changed": 1, "message": "Closed 1 open trips."}
    assert conn.execute("SELECT approx FROM trips WHERE cloud_id='route-open'").fetchone()[0] == 1
    assert conn.execute("SELECT detail FROM events WHERE kind='quality_fix'").fetchone()[0] == "close_open_trips:1"


# ------------------------------------------------------------------------------------------------------- reviews

def _later(hours=0.0, seconds=0.0):
    return (NOW + timedelta(hours=hours, seconds=seconds)).isoformat()


def _review_events(conn, vid):
    return [tuple(r) for r in conn.execute("SELECT at, kind, detail FROM events WHERE vehicle_id=? "
                                           "AND kind='quality_review' ORDER BY id", (vid,))]


def test_review_hides_a_check_until_a_newer_finding():
    conn, vid = _setup()
    _trip(conn, vid, 30, ended=False)
    _trip(conn, vid, 40, ended=False)
    assert quality.review(conn, vid, "open_trips", True, NOW_ISO) == {"check": "open_trips", "reviewed_at": NOW_ISO}
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["open_trips"]
    assert (c["count"], c["total"], c["samples"], c["reviewed_at"]) == (0, 2, [], NOW_ISO)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "new", _later(seconds=1)))
    conn.commit()
    new = conn.execute("SELECT id FROM trips WHERE cloud_id='new'").fetchone()[0]
    c = _by_id(quality.checks(conn, vid, _later(25)))["open_trips"]
    assert (c["count"], c["total"]) == (1, 3)
    assert [s["href"] for s in c["samples"]] == [f"#/trips/{new}"]


def test_a_finding_exactly_at_the_review_time_stays_reviewed():
    conn, vid = _setup()
    _snap(conn, vid, 1, 1000)
    _snap(conn, vid, 0, 900)
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["odometer_jumps"]["count"] == 1
    quality.review(conn, vid, "odometer_jumps", True, NOW_ISO)
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["odometer_jumps"]
    assert (c["count"], c["total"]) == (0, 1)


def test_review_is_per_vehicle():
    conn, vid = _setup()
    other = _other(conn)
    _trip(conn, vid, 30, ended=False)
    _trip(conn, other, 30, ended=False)
    quality.review(conn, vid, "open_trips", True, NOW_ISO)
    b = _by_id(quality.checks(conn, other, NOW_ISO))["open_trips"]
    assert b["count"] == 1 and b["reviewed_at"] is None
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["open_trips"]["count"] == 0


def test_review_again_moves_the_time_forward_and_undo_restores():
    conn, vid = _setup()
    _trip(conn, vid, 30, ended=False)
    quality.review(conn, vid, "open_trips", True, NOW_ISO)
    quality.review(conn, vid, "open_trips", True, _later(1))
    rows = conn.execute("SELECT reviewed_at FROM quality_reviews WHERE vehicle_id=?", (vid,)).fetchall()
    assert [r[0] for r in rows] == [_later(1)]
    assert quality.review(conn, vid, "open_trips", False, _later(2)) == {"check": "open_trips", "reviewed_at": None}
    assert conn.execute("SELECT COUNT(*) FROM quality_reviews").fetchone()[0] == 0
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["open_trips"]
    assert c["count"] == c["total"] == 1 and c["reviewed_at"] is None and len(c["samples"]) == 1


def test_a_reviewed_checks_fix_changes_exactly_its_count():
    """The Fix dialog shows `count` (unreviewed findings only); the repair must change exactly those rows."""
    conn, vid = _setup()
    reviewed = [_trip(conn, vid, 40, ended=False), _trip(conn, vid, 30, ended=False)]
    old_charge = _charge(conn, vid, 40, ended=False)
    old_dupes = _duplicates(conn, vid, "r")
    for check in ("open_trips", "open_charges", "duplicate_trips"):
        quality.review(conn, vid, check, True, NOW_ISO)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "new", _later(seconds=1)))
    conn.execute("INSERT INTO charges(vehicle_id,started_at) VALUES(?,?)", (vid, _later(seconds=1)))
    for cid, dist in (("na", 7.0), ("nb", 7.04)):
        conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km) VALUES(?,?,?,?,?)",
                     (vid, cid, _later(seconds=2), _later(seconds=900 if cid == "na" else 901), dist))
    conn.commit()
    later = _later(25)
    cards = _by_id(quality.checks(conn, vid, later))
    assert [cards[c]["count"] for c in ("open_trips", "open_charges", "duplicate_trips")] == [1, 1, 1]
    for action, check in ((quality.CLOSE_OPEN_TRIPS, "open_trips"), (quality.CLOSE_OPEN_CHARGES, "open_charges"),
                          (quality.DEDUPE_TRIPS, "duplicate_trips")):
        assert quality.fix(conn, vid, action, later)["changed"] == cards[check]["count"] == 1
    assert all(conn.execute("SELECT ended_at FROM trips WHERE id=?", (t,)).fetchone()[0] is None for t in reviewed)
    assert conn.execute("SELECT ended_at FROM charges WHERE id=?", (old_charge,)).fetchone()[0] is None
    assert conn.execute(f"SELECT COUNT(*) FROM trips WHERE id IN ({','.join('?' * 3)})", old_dupes).fetchone()[0] == 3
    assert conn.execute("SELECT ended_at FROM trips WHERE cloud_id='new'").fetchone()[0] is not None
    assert conn.execute("SELECT COUNT(*) FROM trips WHERE cloud_id IN ('na', 'nb')").fetchone()[0] == 1
    assert [r[0] for r in conn.execute("SELECT detail FROM events WHERE kind='quality_fix' ORDER BY id")] == [
        "close_open_trips:1", "close_open_charges:1", "dedupe_trips:1"]


def test_api_errors_compare_epoch_seconds():
    conn, vid = _setup()
    for delta in (timedelta(hours=2), timedelta(minutes=10)):
        conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok) VALUES(?,?,?,0)",
                     (vid, (NOW - delta).timestamp(), "get_vehicle"))
    conn.commit()
    quality.review(conn, vid, "api_errors", True, _ts(1))
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["api_errors"]
    assert (c["count"], c["total"]) == (1, 2)


def test_missing_sections_review_remembers_the_names():
    conn, vid = _setup()
    for k in ("info", "charging", "climate"):
        conn.execute("INSERT INTO vehicle_state(vehicle_id,key,json,fetched_at) VALUES(?,?,?,?)", (vid, k, "{}", _ts(0)))
    conn.commit()
    quality.review(conn, vid, "missing_sections", True, NOW_ISO)
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]
    assert (c["count"], c["total"]) == (0, 1)
    conn.execute("DELETE FROM vehicle_state WHERE vehicle_id=? AND key='charging'", (vid,))
    conn.commit()
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]
    assert c["count"] == 1 and c["total"] == 2
    assert c["samples"] == [{"label": "Section charging missing", "href": None, "kind": "section", "name": "charging"}]


def test_each_review_logs_one_event():
    conn, vid = _setup()
    quality.review(conn, vid, "open_trips", True, NOW_ISO)
    quality.review(conn, vid, "open_trips", False, _later(1))
    assert _review_events(conn, vid) == [(NOW_ISO, "quality_review", "open_trips:on"),
                                         (_later(1), "quality_review", "open_trips:off")]


def test_review_unknown_check_is_400():
    conn, vid = _setup()
    with pytest.raises(ValueError, match="Unknown check."):
        quality.review(conn, vid, "drop_database", True, NOW_ISO)
    assert _review_events(conn, vid) == []


def test_review_route_unknown_check_is_400():
    c, conn, api, vid = connected()
    r = c.post(f"/api/vehicles/{vid}/quality/review", json={"check": "nope", "reviewed": True})
    assert r.status_code == 400 and r.json()["detail"] == "Unknown check."


def test_review_route_other_vehicle_404():
    c, conn, api, vid = connected()
    r = c.post("/api/vehicles/999/quality/review", json={"check": "open_trips", "reviewed": True})
    assert r.status_code == 404 and r.json()["detail"] == "no such vehicle"


def test_review_route_requires_a_session():
    c, conn, api, vid = connected()
    c.cookies.clear()
    assert c.post(f"/api/vehicles/{vid}/quality/review", json={"check": "open_trips", "reviewed": True}).status_code == 401


def test_review_route_sets_and_clears():
    c, conn, api, vid = connected()
    r = c.post(f"/api/vehicles/{vid}/quality/review", json={"check": "open_trips", "reviewed": True})
    assert r.status_code == 200 and r.json()["check"] == "open_trips"
    stamp = r.json()["reviewed_at"]
    got = _by_id(c.get(f"/api/vehicles/{vid}/quality").json()["checks"])["open_trips"]
    assert got["reviewed_at"] == stamp
    r = c.post(f"/api/vehicles/{vid}/quality/review", json={"check": "open_trips", "reviewed": False})
    assert r.json() == {"check": "open_trips", "reviewed_at": None}
    got = _by_id(c.get(f"/api/vehicles/{vid}/quality").json()["checks"])["open_trips"]
    assert got["reviewed_at"] is None


# ----------------------------------------------------------------------------------------- minors (wave 2a)

def test_summaries_use_the_singular_for_one_finding():
    conn, vid = _setup()
    _trip(conn, vid, 30, ended=False)
    _trip(conn, vid, 31, ended=False)
    _charge(conn, vid, 30, ended=False)
    c = _by_id(quality.checks(conn, vid, NOW_ISO))
    assert c["open_trips"]["summary"] == "2 trips never ended"
    assert c["open_charges"]["summary"] == "1 charge never ended"
    assert c["estimated_charges"]["summary"] == "0 charges with an estimated end"


def test_stuck_operations_stay_in_the_api_but_are_marked_invisible():
    conn, vid = _setup()
    items = quality.checks(conn, vid, NOW_ISO)
    assert [c["id"] for c in items] == list(quality.CHECKS) and "stuck_operations" in quality.CHECKS
    assert {c["id"] for c in items if not c["visible"]} == {"stuck_operations"}


def test_consecutive_binds_its_parameters():
    sql, args = quality._consecutive(1, "x' OR 1=1 --", "mileage_km")
    assert "x' OR" not in sql and "x' OR 1=1 --" in args
    conn, vid = _setup()
    assert conn.execute(sql, args).fetchall() == []


def _gap_check(conn, vid, now_iso=NOW_ISO):
    return _by_id(quality.checks(conn, vid, now_iso))["reading_gaps"]


def test_silence_since_the_last_reading_counts_as_a_gap_of_its_own_kind():
    conn, vid = _setup()
    _snap(conn, vid, 11)
    _snap(conn, vid, 10)
    c = _gap_check(conn, vid)
    assert c["count"] == 1
    assert c["samples"] == [{"label": "Silent for 10 h since 10 Mar", "href": None, "kind": "silence",
                             "from": _ts(10), "to": NOW_ISO, "hours": 10}]
    _snap(conn, vid, 2)  # heard from again: the silence turns into a real gap of 8 h
    c = _gap_check(conn, vid)
    assert [s["kind"] for s in c["samples"]] == ["gap"] and c["count"] == 1


def test_a_reading_within_six_hours_is_no_silence_and_an_empty_car_has_none():
    conn, vid = _setup()
    assert _gap_check(conn, vid)["count"] == 0
    _snap(conn, vid, 6)  # exactly 6 h: not a gap
    assert _gap_check(conn, vid)["count"] == 0
    _snap(conn, vid, 6.0001)
    assert _gap_check(conn, vid)["count"] == 0


def test_a_reviewed_silence_stays_reviewed_until_the_car_speaks_again():
    conn, vid = _setup()
    _snap(conn, vid, 12)
    quality.review(conn, vid, "reading_gaps", True, NOW_ISO)
    c = _gap_check(conn, vid, _later(5))  # still silent, only longer
    assert (c["count"], c["total"]) == (0, 1)


def test_a_gap_before_the_window_counts_only_when_it_ends_inside_it():
    conn, vid = _setup()
    _snap(conn, vid, 24 * 40)
    _snap(conn, vid, 24 * 35)       # both before the 30-day window: not counted
    _snap(conn, vid, 5)             # the gap from the last pre-window reading to here ends inside the window
    c = _gap_check(conn, vid)
    assert c["count"] == 1 and c["samples"][0]["from"] == _ts(24 * 35) and c["samples"][0]["to"] == _ts(5)


def test_the_open_threshold_is_exactly_24_hours_and_the_window_edge_is_inclusive():
    conn, vid = _setup()
    _trip(conn, vid, 24, ended=False)
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["open_trips"]["count"] == 0
    _trip(conn, vid, 24 + 1 / 3600, ended=False)
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["open_trips"]["count"] == 1
    _charge(conn, vid, 24 * 30, estimated=1)  # exactly 30 days ago: inside
    _charge(conn, vid, 24 * 30 + 1 / 3600, estimated=1)  # a second older: outside
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["estimated_charges"]["count"] == 1


def test_an_operation_is_stuck_after_more_than_30_minutes_only():
    conn, vid = _setup()
    for i, minutes in enumerate((30, 30 + 1 / 60)):
        conn.execute("INSERT INTO operations(vehicle_id,request_id,name,status,at,updated_at) VALUES(?,?,?,?,?,?)",
                     (vid, f"r{i}", "x", "IN_PROGRESS", _ts(1), _ts(minutes / 60)))
    conn.commit()
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["stuck_operations"]["count"] == 1


def test_reviews_compare_strictly_at_the_boundary_second():
    conn, vid = _setup()
    for delta in (timedelta(hours=1), timedelta(hours=1) - timedelta(seconds=1)):
        conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok) VALUES(?,?,?,0)",
                     (vid, (NOW - delta).timestamp(), "get_vehicle"))
    conn.commit()
    quality.review(conn, vid, "api_errors", True, _ts(1))  # one error exactly at the review, one a second later
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["api_errors"]
    assert (c["count"], c["total"]) == (1, 2)
    # the same for a check that compares ISO times: a jump a second after the review is new
    _snap(conn, vid, 3, 1000)
    conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,mileage_km) VALUES(?,?,?)", (vid, _ts(2), 900))
    conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,mileage_km) VALUES(?,?,?)", (vid, _ts(1 / 3600 + 1), 800))
    conn.commit()
    quality.review(conn, vid, "odometer_jumps", True, _ts(2))
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["odometer_jumps"]
    assert (c["count"], c["total"]) == (1, 2)


def test_api_error_sample_uses_the_shared_date_format_and_structured_fields():
    conn, vid = _setup()
    at = NOW - timedelta(hours=2)
    conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok) VALUES(?,?,?,0)", (vid, at.timestamp(), "get_vehicle"))
    conn.commit()
    s = _by_id(quality.checks(conn, vid, NOW_ISO))["api_errors"]["samples"][0]
    assert s["label"] == "get_vehicle failed, 10 Mar 10:00"
    assert (s["kind"], s["endpoint"], s["at"]) == ("api_error", "get_vehicle", at.isoformat())


def _state(conn, vid, **sections):
    for key, value in sections.items():
        conn.execute("INSERT INTO vehicle_state(vehicle_id,key,json,fetched_at) VALUES(?,?,?,?)",
                     (vid, key, json.dumps(value), _ts(0)))
    conn.commit()


def test_a_section_that_reappears_and_vanishes_again_stays_reviewed_and_undo_counts_it_again():
    conn, vid = _setup()
    _state(conn, vid, info={}, charging={}, climate={})  # position is missing
    quality.review(conn, vid, "missing_sections", True, NOW_ISO)
    _state(conn, vid, position={})
    assert _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]["count"] == 0
    conn.execute("DELETE FROM vehicle_state WHERE vehicle_id=? AND key='position'", (vid,))
    conn.commit()
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]
    assert (c["count"], c["total"]) == (0, 1)
    quality.review(conn, vid, "missing_sections", False, _later(1))
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]
    assert (c["count"], c["total"]) == (1, 1)


def test_a_section_the_car_does_not_support_is_not_missing():
    conn, vid = _setup()
    _state(conn, vid, info={}, climate={}, position={},
           part_state={"charging": "unsupported", "airConditioning": "present", "parkingPosition": "present"})
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]
    assert (c["count"], c["total"], c["samples"]) == (0, 0, [])
    conn.execute("DELETE FROM vehicle_state WHERE vehicle_id=? AND key='climate'", (vid,))
    conn.commit()  # supported but gone: still reported
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]
    assert [s["label"] for s in c["samples"]] == ["Section climate missing"]
    # a disabled part is a real gap the owner may want to see; only "never reported" parts are skipped
    conn.execute("UPDATE vehicle_state SET json=? WHERE vehicle_id=? AND key='part_state'",
                 (json.dumps({"airConditioning": "disabled"}), vid))
    conn.execute("DELETE FROM vehicle_state WHERE vehicle_id=? AND key='charging'", (vid,))
    conn.commit()
    c = _by_id(quality.checks(conn, vid, NOW_ISO))["missing_sections"]
    assert [s["label"] for s in c["samples"]] == ["Section charging missing", "Section climate missing"]


def test_fix_and_review_run_under_the_connections_lock():
    """No other thread's statement may slip in between a repair's statements and its event row."""
    import threading
    conn, vid = _setup()
    ran: list[str] = []
    threads: list[threading.Thread] = []

    def probe(c, v, now_iso):
        other = threading.Thread(target=lambda: (c.execute("SELECT 1"), ran.append("other")))
        other.start()
        other.join(0.3)
        ran.append("blocked" if other.is_alive() else "slipped in")  # a held lock keeps the other thread waiting
        threads.append(other)
        return 0

    quality._FIXES["probe"] = (probe, "{n}")
    try:
        quality.fix(conn, vid, "probe", NOW_ISO)
    finally:
        del quality._FIXES["probe"]
    threads[0].join(2)
    assert ran == ["blocked", "other"]


def test_every_visible_sample_kind_carries_structured_fields():
    conn, vid = _setup()
    t = _trip(conn, vid, 30, ended=False)
    ch = _charge(conn, vid, 30, ended=False)
    est = _charge(conn, vid, 50, estimated=1)
    ap = _trip(conn, vid, 70, approx=1)
    _snap(conn, vid, 100, 1000)
    _snap(conn, vid, 99, 1010)
    _snap(conn, vid, 92, 1005)
    for h in range(86, 0, -6):
        _snap(conn, vid, h)
    c = _by_id(quality.checks(conn, vid, NOW_ISO))
    s = c["open_trips"]["samples"][0]
    assert (s["kind"], s["id"], s["href"]) == ("trip", t, f"#/trips/{t}") and s["at"] == _ts(30)
    s = c["open_charges"]["samples"][0]
    assert (s["kind"], s["id"], s["href"]) == ("charge", ch, f"#/charges/{ch}") and s["at"] == _ts(30)
    assert c["estimated_charges"]["samples"][0]["kind"] == "charge"
    assert c["estimated_charges"]["samples"][0]["id"] == est
    assert c["approx_trips"]["samples"][0]["kind"] == "trip" and c["approx_trips"]["samples"][0]["id"] == ap
    j = c["odometer_jumps"]["samples"][0]
    assert (j["kind"], j["from_km"], j["to_km"], j["at"]) == ("odometer", 1010, 1005, _ts(92))
    assert j["label"].startswith("Odometer 1010 to 1005 km")
