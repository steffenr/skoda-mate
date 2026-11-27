from datetime import UTC, datetime, timedelta

import pytest

from skoda_mate import activity, analytics, costs, demo, quality, recorder, schema
from skoda_mate.config import Config
from skoda_mate.web import create_app

from .helpers import client_for


def demo_client():
    cfg = Config(db_path=":memory:", demo=True)
    return client_for(create_app(cfg, schema.connect(":memory:")))


def test_demo_mode_needs_no_login_or_account_and_has_history():
    with demo_client() as c:
        assert c.get("/").status_code == 200  # straight to the dashboard
        v = c.get("/api/vehicles").json()
        assert v[0]["vin"] == demo.DEMO_VIN and v[0]["name"] == "Demo Enyaq"
        vid = v[0]["id"]
        o = c.get(f"/api/vehicles/{vid}/overview").json()
        assert o["demo"] is True and o["snapshot"]["soc"] is not None and o["features"]["charge_control"]["available"]
        trips = c.get(f"/api/vehicles/{vid}/trips?limit=500").json()
        assert trips["total"] >= 25 and all(t["distance_km"] and t["start_place"] for t in trips["items"][:10])
        charges = c.get(f"/api/vehicles/{vid}/charges").json()
        assert charges["total"] >= 3 and {x["charge_type"] for x in charges["items"]} >= {"AC"}
        months = c.get(f"/api/vehicles/{vid}/stats").json()["monthly"]
        assert len(months) >= 2 and sum(m["km"] for m in months) > 500
        assert c.get(f"/api/vehicles/{vid}/map").json()["parked"]
        assert c.get(f"/api/vehicles/{vid}/battery").json()["samples"] >= 1


def test_demo_has_named_places_and_links():
    with demo_client() as c:
        conn = c.app.state.ctx.conn
        names = {p["name"] for p in c.get("/api/places").json()["items"]}
        assert {"Home", "Work", "Shop", "Darmstadt"} <= names
        assert conn.execute("SELECT COUNT(*) FROM trips WHERE start_geofence_id IS NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM charges WHERE geofence_id IS NULL").fetchone()[0] == 0


def test_demo_commands_change_the_demo_car_and_setup_is_refused():
    with demo_client() as c:
        vid = c.get("/api/vehicles").json()[0]["id"]
        r = c.post(f"/api/vehicles/{vid}/command", json={"name": "set_charge_limit", "params": {"percent": 90}})
        assert r.status_code == 200 and r.json()["ok"]
        r = c.post(f"/api/vehicles/{vid}/refresh").json()
        assert r["ok"]
        assert c.get(f"/api/vehicles/{vid}/overview").json()["snapshot"]["target_soc"] == 90
        assert c.post("/api/setup/skoda", json={"api_key": "x" * 20, "vins": demo.DEMO_VIN}).status_code == 400


def test_demo_history_never_runs_ahead_of_the_clock():
    # A day's schedule in seed() can run past midnight. Those samples must not be written: they would sort after
    # every live poll (last_snapshot orders by recorded_at), so the dashboard would show stale data forever.
    conn = schema.connect(":memory:")
    now = datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
    vid = demo.seed(conn, now=now)
    newest = conn.execute("SELECT MAX(recorded_at) FROM snapshots WHERE vehicle_id=?", (vid,)).fetchone()[0]
    assert datetime.fromisoformat(newest) <= now


def test_demo_history_reads_a_parked_car_like_the_poller_does():
    """The real poller reads a parked car every 20 minutes, so a seeded demo must not show reading gaps nobody would
    see in a real database: no data-quality gap findings and no unknown time on the timeline while the car stands."""
    conn = schema.connect(":memory:")
    now = datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
    vid = demo.seed(conn, now=now)
    checks = {c["id"]: c["count"] for c in quality.checks(conn, vid, now.isoformat())}
    assert checks["reading_gaps"] == 0
    week = activity.timeline(conn, vid, "2026-05-13", "2026-05-19", 0, now=now)
    assert week["summary"]["unknown_min"] == 0
    assert week["summary"]["drive_min"] > 0 and week["summary"]["charge_min"] > 0 and week["summary"]["parked_min"] > 0
    newest = conn.execute("SELECT MAX(recorded_at) FROM snapshots WHERE vehicle_id=?", (vid,)).fetchone()[0]
    assert now - datetime.fromisoformat(newest) <= timedelta(hours=1)  # the history reaches the live demo


def test_demo_parked_readings_never_land_inside_a_drive_or_a_charge():
    conn = schema.connect(":memory:")
    now = datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
    vid = demo.seed(conn, now=now)
    inside_drive = conn.execute(
        "SELECT COUNT(*) FROM snapshots s JOIN trips t ON t.vehicle_id=s.vehicle_id AND s.recorded_at > t.started_at "
        "AND s.recorded_at < t.ended_at WHERE s.vehicle_id=? AND COALESCE(s.in_motion, 0) = 0", (vid,)).fetchone()[0]
    inside_charge = conn.execute(
        "SELECT COUNT(*) FROM snapshots s JOIN charges c ON c.vehicle_id=s.vehicle_id AND s.recorded_at > c.started_at "
        "AND s.recorded_at < c.ended_at WHERE s.vehicle_id=? AND s.charging = 0", (vid,)).fetchone()[0]
    assert (inside_drive, inside_charge) == (0, 0)


def test_demo_battery_drains_while_parked_like_a_real_car():
    """A parked Enyaq loses roughly 1-2 % a day to standby electronics, and the API reports whole percent. The demo's
    Parked statistics must show measurable losses (and, for short stands, the detection floor), never only zeros."""
    conn = schema.connect(":memory:")
    now = datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
    vid = demo.seed(conn, now=now)
    socs = [r[0] for r in conn.execute("SELECT soc FROM snapshots WHERE vehicle_id=? AND soc IS NOT NULL", (vid,))]
    assert socs and all(s == int(s) for s in socs)  # whole percent, like stateOfChargeInPercent
    out = activity.parked_loss(conn, vid, (now - timedelta(days=30)).isoformat(), now.isoformat(), 6.0, 77.0)
    sessions, agg = out["sessions"], out["aggregates"]
    measured = [s for s in sessions if s["soc_delta"] > 0]
    assert len(measured) >= 10 and any(s["below_detection_floor"] for s in sessions)
    assert not any(s["warning"] for s in sessions)  # a drain is never mistaken for an unrecorded charge
    assert 0.3 <= agg["median_kwh_per_day"] <= 2.5 and agg["kwh"] > 0
    assert conn.execute("SELECT COUNT(*) FROM charges WHERE vehicle_id=? AND source='inferred'", (vid,)).fetchone()[0] == 0


def test_demo_odometer_is_whole_km_so_the_live_demo_continues_without_a_decrease():
    """mileageInKm is a whole number, and the live demo reports int(odo). A seeded history with decimals made the first
    live reading look like an odometer decrease (13034.2 -> 13034 km) on the data-quality card."""
    conn = schema.connect(":memory:")
    now = datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
    vid = demo.seed(conn, now=now)
    odos = [r[0] for r in conn.execute("SELECT mileage_km FROM snapshots WHERE vehicle_id=? AND mileage_km IS NOT NULL", (vid,))]
    assert odos and all(o == int(o) for o in odos)
    last = recorder.last_snapshot(conn, vid)["mileage_km"]
    first_live = demo.vehicle_response(now, 50, False, odo=last)["vehicle"]["odometer"]["mileageInKm"]  # what DemoApi sends
    assert first_live == last
    assert {c["id"]: c["count"] for c in quality.checks(conn, vid, now.isoformat())}["odometer_jumps"] == 0


def test_demo_started_on_a_charge_evening_never_shows_a_phantom_charge():
    """A Sunday 22:00 charge after `now` is skipped, but the loop still raised the internal level; the final parked
    readings up to `now` must not carry that future level (38 % then 80 % without a charge -> an inferred charge)."""
    conn = schema.connect(":memory:")
    now = datetime(2026, 5, 17, 21, 0, tzinfo=UTC)  # a Sunday: the seed always charges at 22:00
    vid = demo.seed(conn, now=now)
    rows = conn.execute("SELECT soc, charging FROM snapshots WHERE vehicle_id=? AND soc IS NOT NULL "
                        "ORDER BY recorded_at, id", (vid,)).fetchall()
    rises = [(a["soc"], b["soc"]) for a, b in zip(rows, rows[1:], strict=False)
             if not a["charging"] and not b["charging"] and b["soc"] > a["soc"]]
    assert rises == []  # the level only goes up while charging
    assert conn.execute("SELECT COUNT(*) FROM charges WHERE vehicle_id=? AND source='inferred'", (vid,)).fetchone()[0] == 0


def test_demo_week_shows_activity_parked_loss_and_a_quality_finding():
    """The demo's last week must make the Activity page, the Parked tab and the System quality card worth opening."""
    with demo_client() as c:
        vid = c.get("/api/vehicles").json()[0]["id"]
        week = c.get(f"/api/vehicles/{vid}/timeline").json()
        assert len(week["days"]) == 7
        kinds = {iv["kind"] for day in week["days"] for iv in day["intervals"]}
        assert {"drive", "charge", "climate"} <= kinds
        loss = c.get(f"/api/vehicles/{vid}/parked-loss").json()
        assert any(s["warning"] is None and s["kwh_per_day"] and s["kwh_per_day"] > 0 for s in loss["sessions"])
        found = {x["id"]: x for x in c.get(f"/api/vehicles/{vid}/quality").json()["checks"]}
        assert found["duplicate_trips"]["count"] >= 1 and found["duplicate_trips"]["severity"] == "important"


def test_demo_seed_is_deterministic_with_its_climate_run_and_duplicate_trip():
    def snapshot():
        conn = schema.connect(":memory:")
        now = datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
        vid = demo.seed(conn, now=now)
        return (conn.execute("SELECT COUNT(*) FROM trips WHERE vehicle_id=?", (vid,)).fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM charges WHERE vehicle_id=?", (vid,)).fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM snapshots WHERE vehicle_id=? AND climate_state='HEATING'", (vid,)).fetchone()[0])

    first = snapshot()
    assert first == snapshot() and first[2] >= 2


@pytest.mark.parametrize(("end_offset_s", "removed"), [(1, False), (0, True)])
def test_demo_duplicate_trip_survives_the_startup_cleanup_only_as_a_near_copy(end_offset_s, removed):
    """schema.dedupe_trips runs on every start and removes exact start-and-end copies. The seeded copy ends one second
    later and must stay; made an exact copy it must go, so the test fails if the clean-up stops removing anything."""
    conn = schema.connect(":memory:")
    now = datetime(2026, 5, 20, 8, 30, tzinfo=UTC)
    vid = demo.seed(conn, now=now)
    copy = conn.execute("SELECT id, started_at, ended_at FROM trips WHERE vehicle_id=? AND cloud_id LIKE '%-copy'",
                        (vid,)).fetchone()
    original = conn.execute("SELECT ended_at FROM trips WHERE vehicle_id=? AND started_at=? AND id!=?",
                            (vid, copy["started_at"], copy["id"])).fetchone()
    end = datetime.fromisoformat(original["ended_at"]) + timedelta(seconds=end_offset_s)
    conn.execute("UPDATE trips SET ended_at=? WHERE id=?", (end.isoformat(), copy["id"]))
    conn.commit()
    assert schema.dedupe_trips(conn) == (1 if removed else 0)
    found = {c["id"]: c for c in quality.checks(conn, vid, "2026-05-20T08:30:00+00:00")}
    assert (found["duplicate_trips"]["count"] == 0) is removed


def test_demo_shows_the_insight_features():
    conn = schema.connect(":memory:")
    now = datetime(2027, 3, 17, 12, tzinfo=UTC)
    vid = demo.seed(conn, now=now)
    charging = analytics.charging(conn, vid, costs.load_tariff(conn))
    assert len(charging["curve"]["ac"]) >= 3 and len(charging["curve"]["dc"]) >= 3
    assert charging["types"]["dc"]["avg_power_kw"] > 40 > charging["types"]["ac"]["avg_power_kw"]
    dc_places = {r[0] for r in conn.execute("SELECT g.name FROM charges c JOIN geofences g ON g.id=c.geofence_id "
                                            "WHERE c.charge_type='DC'")}
    assert dc_places == {"Darmstadt"}  # fast charging happens at the public stop, never at home
    driving = analytics.driving(conn, vid)
    assert driving["projection"]["annual_km"] > 5000
    assert len({d["name"] for d in driving["top_destinations"]} & {"Home", "Work", "Shop", "Darmstadt"}) >= 2
    ranged = analytics.projected_range(conn, vid)
    assert 500 < ranged["latest"]["range_km"] < 620 and ranged["samples"] > 500
    assert ranged["trend_km_per_year"] is not None and ranged["degradation"] is None
