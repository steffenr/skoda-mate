import json

from skoda_mate import recorder, schema


def make(kwh=77.0):
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "TMBJB9NY5RF999999", "Enyaq", None, kwh)
    return conn, vid


def t(h, m=0):
    return f"2026-01-01T{h:02d}:{m:02d}:00+00:00"


def snap(ts, soc=None, **kw):
    return {"ts": ts, "soc": soc, "charging": False, **kw}


def charging(ts, soc, power, **kw):
    return snap(ts, soc, charging=True, charge_state="CHARGING", charge_power_kw=power, charge_type="AC", **kw)


# ------------------------------------------------------------------ charges

def test_charge_session_integrates_power():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(9, 50), 18, charge_state="CONNECT_CABLE"))
    recorder.ingest(conn, vid, charging(t(10), 20, 10.0))
    recorder.ingest(conn, vid, charging(t(11), 40, 10.0))
    recorder.ingest(conn, vid, snap(t(11, 30), 45, charge_state="READY_FOR_CHARGING"))
    c = conn.execute("SELECT * FROM charges").fetchall()
    assert len(c) == 1
    c = c[0]
    assert c["ended_at"] == t(11, 30) and c["start_soc"] == 18 and c["end_soc"] == 45  # SoC from just before the start
    assert abs(c["energy_kwh"] - 12.5) < 1e-6 and c["max_power_kw"] == 10.0 and c["duration_min"] == 90
    assert abs(c["energy_battery_kwh"] - (45 - 18) * 77 / 100) < 1e-6  # what reached the pack


def test_unknown_charge_state_does_not_end_a_session():
    """API docs: an omitted state is unknown (e.g. right after a drive), never 'unplugged'."""
    conn, vid = make()
    recorder.ingest(conn, vid, charging(t(10), 20, 10.0))
    recorder.ingest(conn, vid, snap(t(10, 20), 25))  # state omitted, plug unknown
    assert conn.execute("SELECT ended_at FROM charges").fetchone()[0] is None
    recorder.ingest(conn, vid, snap(t(10, 40), 30, plug_connected=False, charge_state="CONNECT_CABLE"))
    assert conn.execute("SELECT ended_at FROM charges").fetchone()[0] == t(10, 40)


def test_stale_open_charge_is_closed_at_last_known_time():
    conn, vid = make()
    recorder.ingest(conn, vid, charging(t(1), 20, 10.0))
    recorder.ingest(conn, vid, snap(t(8), 60))  # silent for 7 h, state still unknown
    c = conn.execute("SELECT * FROM charges").fetchone()
    assert c["ended_at"] == t(1)


def test_energy_estimated_from_soc_without_power():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(10), 20, charging=True, charge_state="CHARGING"))
    recorder.ingest(conn, vid, snap(t(10, 10), 30, charge_state="COMPLETED_x"))
    c = conn.execute("SELECT * FROM charges").fetchone()
    assert abs(c["energy_kwh"] - 7.7) < 1e-6


def test_gap_is_capped():
    conn, vid = make()
    recorder.ingest(conn, vid, charging(t(0), 20, 10.0))
    recorder.ingest(conn, vid, charging(t(10), 80, 10.0))
    assert conn.execute("SELECT energy_kwh FROM charges").fetchone()[0] == 10.0


# ------------------------------------------------------------------ events

def test_events_ignore_unknowns_and_report_changes():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(10), 50, locked=True, plug_connected=False, climate_state="OFF"))
    recorder.ingest(conn, vid, snap(t(10, 5), 50))  # nothing reported: no event
    recorder.ingest(conn, vid, snap(t(10, 10), 50, locked=False, plug_connected=True, climate_state="HEATING"))
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events ORDER BY id")]
    assert kinds == ["unlocked", "plugged_in", "climate"]


# ------------------------------------------------------------------ trips

def test_trip_from_motion_and_parking():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(8), 90, in_motion=False, mileage_km=1000, lat=50.0, lon=8.0, address="Home"))
    recorder.ingest(conn, vid, snap(t(8, 10), 85, in_motion=True, mileage_km=1000))
    assert conn.execute("SELECT COUNT(*) FROM trips WHERE ended_at IS NULL").fetchone()[0] == 1
    recorder.ingest(conn, vid, snap(t(8, 40), 80, in_motion=False, mileage_km=1040, lat=50.4, lon=8.4, address="Work",
                                    park_captured_at=t(8, 32)))
    tr = conn.execute("SELECT * FROM trips").fetchall()
    assert len(tr) == 1
    tr = tr[0]
    assert tr["distance_km"] == 40 and tr["start_place"] == "Home" and tr["end_place"] == "Work"
    assert tr["started_at"] == t(8, 10) and tr["ended_at"] == t(8, 32) and tr["duration_min"] == 22
    assert tr["start_soc"] == 90 and tr["end_soc"] == 80 and abs(tr["energy_kwh"] - 7.7) < 1e-6
    assert abs(tr["avg_kwh_100km"] - 19.25) < 0.06 and tr["approx"] == 0
    route = json.loads(tr["route_json"])
    assert [p["place"] for p in route] == ["Home", "Work"]
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events ORDER BY id")]
    assert kinds == ["trip_start", "trip_end"]


def test_drive_first_seen_mid_way_starts_earlier_and_ends_at_the_cars_own_timestamp():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(8), 90, in_motion=False, mileage_km=1000, lat=50.0, lon=8.0, address="Home"))
    recorder.ingest(conn, vid, snap(t(9), 80, in_motion=True, mileage_km=1022.5))  # 22.5 km already driven: 30 min at 45 km/h
    recorder.ingest(conn, vid, snap(t(9, 20), 75, in_motion=False, mileage_km=1031, lat=50.4, lon=8.4, address="Work",
                                    captured_at=t(9, 14)))  # no position timestamp: the latest report is better than the poll
    tr = conn.execute("SELECT * FROM trips").fetchone()
    assert tr["started_at"] == t(8, 30) and tr["ended_at"] == t(9, 14) and tr["duration_min"] == 44
    assert [r["at"] for r in conn.execute("SELECT at FROM events WHERE kind='trip_start'")] == [t(8, 30)]


def test_drive_start_is_never_before_the_last_parked_reading():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(8, 50), 90, in_motion=False, mileage_km=1000, lat=50.0, lon=8.0))
    recorder.ingest(conn, vid, snap(t(9), 80, in_motion=True, mileage_km=1030))  # 30 km in 10 min is impossible: clamp
    assert conn.execute("SELECT started_at FROM trips").fetchone()[0] == t(8, 50)


def test_short_trip_found_only_through_odometer_jump_is_marked_approximate():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(8), 90, in_motion=False, mileage_km=1000, lat=50.0, lon=8.0, address="Home"))
    recorder.ingest(conn, vid, snap(t(8, 30), 88, in_motion=False, mileage_km=1009, lat=50.1, lon=8.1, address="Shop"))
    tr = conn.execute("SELECT * FROM trips").fetchone()
    assert tr["approx"] == 1 and tr["distance_km"] == 9 and tr["start_place"] == "Home" and tr["end_place"] == "Shop"
    assert t(8) <= tr["started_at"] < tr["ended_at"]


def test_implausible_odometer_jump_is_not_a_trip():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(8), 90, in_motion=False, mileage_km=1000))
    recorder.ingest(conn, vid, snap(t(8, 30), 88, in_motion=False, mileage_km=2900))  # +1900 km in 30 min
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0
    ev = conn.execute("SELECT kind, detail FROM events").fetchall()
    assert [e["kind"] for e in ev] == ["odometer_jump"] and "not recorded" in ev[0]["detail"]
    recorder.ingest(conn, vid, snap(t(9), 88, in_motion=False, mileage_km=2920))  # normal driving continues from the new baseline
    assert conn.execute("SELECT distance_km FROM trips").fetchone()[0] == 20


def test_no_trip_when_odometer_did_not_move():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(8), 90, in_motion=False, mileage_km=1000))
    recorder.ingest(conn, vid, snap(t(8, 20), 90, in_motion=True, mileage_km=1000))
    recorder.ingest(conn, vid, snap(t(8, 30), 90, in_motion=False, mileage_km=1000.2))
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0


def test_unknown_motion_does_not_close_a_drive_but_stale_does():
    conn, vid = make()
    recorder.ingest(conn, vid, snap(t(8), 90, in_motion=False, mileage_km=1000))
    recorder.ingest(conn, vid, snap(t(8, 10), 88, in_motion=True, mileage_km=1005))
    recorder.ingest(conn, vid, snap(t(8, 20), 86, mileage_km=1015))  # parking part missing: unknown
    assert conn.execute("SELECT COUNT(*) FROM trips WHERE ended_at IS NULL").fetchone()[0] == 1
    recorder.ingest(conn, vid, snap(t(15), 70, mileage_km=1030))  # 7 h later, still no definite PARKED
    tr = conn.execute("SELECT * FROM trips").fetchone()
    assert tr["ended_at"] is not None and tr["distance_km"] == 30


def test_trip_without_battery_capacity_has_no_energy():
    conn, vid = make(kwh=None)
    recorder.ingest(conn, vid, snap(t(8), 90, in_motion=False, mileage_km=1000))
    recorder.ingest(conn, vid, snap(t(8, 10), 88, in_motion=True, mileage_km=1005))
    recorder.ingest(conn, vid, snap(t(8, 30), 80, in_motion=False, mileage_km=1030))
    tr = conn.execute("SELECT * FROM trips").fetchone()
    assert tr["distance_km"] == 30 and tr["energy_kwh"] is None and tr["energy_basis"] is None
    conn.execute("INSERT INTO settings(key,value) VALUES('battery_kwh','60')")
    assert recorder.battery_kwh(conn, vid) == 60.0


def test_duplicate_trips_from_the_old_importer_are_removed_once_and_notes_survive():
    conn, vid = make()
    ins = "INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km,note) VALUES(?,?,?,?,?,?)"
    conn.execute(ins, (vid, "a", "2026-11-23T06:02:44.974+00:00", "2026-11-23T06:34:06.972+00:00", 32, None))
    conn.execute(ins, (vid, "b", "2026-11-23T06:02:44.974+00:00", "2026-11-23T06:34:06.972+00:00", 32, "to work"))  # same drive, new id
    conn.execute(ins, (vid, "c", "2026-11-22T13:18:18.516+00:00", "2026-11-22T13:30:34.281+00:00", 6, None))  # a different drive
    conn.execute(ins, (vid, "d", "2026-11-22T13:18:18.516+00:00", "2026-11-22T13:30:40.000+00:00", 6, None))  # same start, different end: keep
    conn.commit()
    assert schema.dedupe_trips(conn) == 1
    rows = conn.execute("SELECT cloud_id, note FROM trips ORDER BY id").fetchall()
    assert [r["cloud_id"] for r in rows] == ["a", "c", "d"] and rows[0]["note"] == "to work"
    assert schema.dedupe_trips(conn) == 0  # idempotent
    schema.migrate(conn)  # and it runs on every start without touching clean data
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 3


def test_migration_adds_columns_to_an_old_database(tmp_path):
    import sqlite3

    p = str(tmp_path / "old.db")
    old = sqlite3.connect(p)
    old.executescript("CREATE TABLE vehicles(id INTEGER PRIMARY KEY, vin TEXT UNIQUE NOT NULL, name TEXT, model TEXT,"
                      " battery_kwh REAL, created_at TEXT);"
                      "CREATE TABLE snapshots(id INTEGER PRIMARY KEY, vehicle_id INTEGER, recorded_at TEXT NOT NULL, soc REAL);"
                      "INSERT INTO vehicles(vin) VALUES('X'); INSERT INTO snapshots(vehicle_id,recorded_at,soc) VALUES(1,'a',5);")
    old.commit()
    old.close()
    conn = schema.connect(p)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(snapshots)")}
    assert {"in_motion", "mileage_km", "plug_connected", "park_captured_at"} <= cols
    assert conn.execute("SELECT soc FROM snapshots").fetchone()[0] == 5  # data survived
