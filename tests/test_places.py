import json

import pytest

from skoda_mate import places, schema


def test_schema_adds_place_columns_and_indexes():
    conn = schema.connect(":memory:")
    trip_cols = {r["name"] for r in conn.execute("PRAGMA table_info(trips)")}
    charge_cols = {r["name"] for r in conn.execute("PRAGMA table_info(charges)")}
    geo_cols = {r["name"] for r in conn.execute("PRAGMA table_info(geofences)")}
    assert {"start_geofence_id", "end_geofence_id"} <= trip_cols
    assert "geofence_id" in charge_cols
    assert {"name", "kind", "lat", "lon", "radius_m", "free"} <= geo_cols
    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_snapshots_place", "idx_geofences_one_home"} <= indexes


def test_migrate_seeds_home_once_and_clamps_the_radius():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?)",
                 (json.dumps({"home_lat": 50.11, "home_lon": 8.68, "home_radius_m": 5}),))
    conn.commit()
    schema.migrate(conn)
    homes = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchall()
    assert len(homes) == 1 and homes[0]["name"] == "Home" and homes[0]["radius_m"] == 20
    schema.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM geofences WHERE kind='home'").fetchone()[0] == 1


def test_migrate_clamps_a_huge_radius():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?)",
                 (json.dumps({"home_lat": 50.11, "home_lon": 8.68, "home_radius_m": 99999}),))
    conn.commit()
    schema.migrate(conn)
    assert conn.execute("SELECT radius_m FROM geofences WHERE kind='home'").fetchone()[0] == 5000


def test_migrate_without_home_is_fine():
    conn = schema.connect(":memory:")
    assert conn.execute("SELECT COUNT(*) FROM geofences").fetchone()[0] == 0


def test_migrate_survives_bad_tariff_json():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff','{not json')")
    conn.commit()
    schema.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM geofences").fetchone()[0] == 0


def test_migrate_skips_home_without_both_coordinates():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?)", (json.dumps({"home_lat": 50.11}),))
    conn.commit()
    schema.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM geofences").fetchone()[0] == 0


def _vid(conn) -> int:
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    return conn.execute("SELECT id FROM vehicles").fetchone()[0]


def test_match_prefers_smallest_radius_then_lowest_id():
    conn = schema.connect(":memory:")
    wide = places.create(conn, {"name": "Wide", "kind": "place", "lat": 50.0, "lon": 8.0, "radius_m": 500})
    assert wide["radius_m"] == 500
    narrow = places.create(conn, {"name": "Narrow", "kind": "place", "lat": 50.0005, "lon": 8.0005, "radius_m": 100})
    assert places.match(conn, 50.0005, 8.0005)["id"] == narrow["id"]
    twin = places.create(conn, {"name": "Twin", "kind": "place", "lat": 50.0005, "lon": 8.0005, "radius_m": 100})
    assert twin["id"] > narrow["id"]
    assert places.match(conn, 50.0005, 8.0005)["id"] == narrow["id"]
    assert places.match(conn, 51.0, 9.0) is None


def test_assign_all_sets_trip_start_end_and_charge():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.1, "lon": 8.1, "radius_m": 150})
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,start_lat,start_lon,end_lat,end_lon) VALUES(?,?,?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T08:00:00+00:00", "2027-02-10T08:40:00+00:00", 50.0, 8.0, 50.1, 8.1))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,lat,lon) VALUES(?,?,?,?)",
                 (vid, "2027-02-10T19:00:00+00:00", 50.1, 8.1))
    counts = places.assign_all(conn)
    trip = conn.execute("SELECT start_geofence_id, end_geofence_id FROM trips").fetchone()
    charge = conn.execute("SELECT geofence_id FROM charges").fetchone()
    assert (trip[0], trip[1], charge[0]) == (home["id"], work["id"], work["id"])
    assert counts["trips"] == 1 and counts["charges"] == 1


def test_summaries_count_visits_days_and_last_seen():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    for day in ("2027-02-11", "2027-02-12"):
        conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                     (vid, day, day + "T08:00:00+00:00", day + "T08:30:00+00:00", 50.0, 8.0))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,lat,lon) VALUES(?,?,?,?,?)",
                 (vid, "2027-02-12T19:00:00+00:00", "2027-02-12T20:00:00+00:00", 50.0, 8.0))
    places.assign_all(conn)
    summary = next(p for p in places.summaries(conn) if p["id"] == home["id"])
    assert summary["visit_count"] == 2 and summary["day_count"] == 2
    assert summary["charge_count"] == 1 and summary["last_seen"].startswith("2027-02-12")


def test_summaries_last_seen_is_the_later_charge_end():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-12T08:00:00+00:00", "2027-02-12T08:30:00+00:00", 50.0, 8.0))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,lat,lon) VALUES(?,?,?,?,?)",
                 (vid, "2027-02-12T19:00:00+00:00", "2027-02-12T20:00:00+00:00", 50.0, 8.0))
    places.assign_all(conn)
    summary = next(p for p in places.summaries(conn) if p["id"] == home["id"])
    assert summary["last_seen"] == "2027-02-12T20:00:00+00:00"


def test_create_defaults_list_and_get():
    conn = schema.connect(":memory:")
    place = places.create(conn, {"name": "Shop", "lat": 50.0, "lon": 8.0})
    assert place["kind"] == "place" and place["radius_m"] == 150 and place["free"] == 0
    assert place["price_kwh"] is None and place["created_at"] and place["updated_at"]
    assert places.get(conn, place["id"])["name"] == "Shop"
    assert places.get(conn, 9999) is None
    assert [p["id"] for p in places.list_places(conn)] == [place["id"]]


def test_create_a_second_home_is_a_conflict():
    conn = schema.connect(":memory:")
    places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    with pytest.raises(places.PlaceConflict) as err:
        places.create(conn, {"name": "Other", "kind": "home", "lat": 51.0, "lon": 9.0})
    assert err.value.status == 409 and str(err.value) == "Only one home place is allowed."
    assert conn.execute("SELECT COUNT(*) FROM geofences WHERE kind='home'").fetchone()[0] == 1


def test_summaries_order_home_first_then_name_case_insensitively():
    conn = schema.connect(":memory:")
    places.create(conn, {"name": "Casa", "kind": "home", "lat": 50.0, "lon": 8.0})
    places.create(conn, {"name": "alpha", "kind": "work", "lat": 50.1, "lon": 8.1})
    places.create(conn, {"name": "Zebra", "kind": "place", "lat": 50.2, "lon": 8.2})
    assert [p["name"] for p in places.summaries(conn)] == ["Casa", "alpha", "Zebra"]


def test_assign_all_counts_only_changed_rows():
    conn = schema.connect(":memory:")
    places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T08:00:00+00:00", "2027-02-10T08:30:00+00:00", 50.0, 8.0))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,lat,lon) VALUES(?,?,?,?)",
                 (vid, "2027-02-10T19:00:00+00:00", 50.0, 8.0))
    assert places.assign_all(conn) == {"trips": 1, "charges": 1}
    assert places.assign_all(conn) == {"trips": 0, "charges": 0}


def test_update_moves_and_resizes_a_place_and_reassigns_its_rows():
    conn = schema.connect(":memory:")
    place = places.create(conn, {"name": "Edge", "kind": "place", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T08:00:00+00:00", "2027-02-10T08:30:00+00:00", 50.0005, 8.0005))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,lat,lon) VALUES(?,?,?,?)",
                 (vid, "2027-02-10T19:00:00+00:00", 50.0005, 8.0005))
    places.assign_all(conn)
    assert conn.execute("SELECT geofence_id FROM charges").fetchone()[0] == place["id"]
    updated = places.update(conn, place["id"], {"name": "Tiny", "kind": "place", "lat": 50.0, "lon": 8.0, "radius_m": 20})
    assert updated["name"] == "Tiny" and updated["radius_m"] == 20
    trip = conn.execute("SELECT start_geofence_id, end_geofence_id FROM trips").fetchone()
    assert (trip[0], trip[1]) == (None, None)
    assert conn.execute("SELECT geofence_id FROM charges").fetchone()[0] is None


def test_update_refuses_to_change_the_home_kind_or_make_a_second_home():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.1, "lon": 8.1})
    with pytest.raises(places.PlaceError) as err:
        places.update(conn, home["id"], {"kind": "work"})
    assert err.value.status == 400 and str(err.value) == "The home place cannot change its kind."
    with pytest.raises(places.PlaceConflict) as err:
        places.update(conn, work["id"], {"kind": "home"})
    assert err.value.status == 409 and str(err.value) == "Only one home place is allowed."
    with pytest.raises(places.PlaceNotFound) as err:
        places.update(conn, 9999, {"name": "Nope"})
    assert err.value.status == 404 and str(err.value) == "Place not found."


def test_delete_clears_references_and_refuses_the_home():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.1, "lon": 8.1})
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,start_lat,start_lon,end_lat,end_lon) VALUES(?,?,?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T08:00:00+00:00", "2027-02-10T08:40:00+00:00", 50.0, 8.0, 50.1, 8.1))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,lat,lon) VALUES(?,?,?,?)",
                 (vid, "2027-02-10T19:00:00+00:00", 50.1, 8.1))
    places.assign_all(conn)
    assert places.delete(conn, work["id"]) == {"trips": 1, "charges": 1}
    trip = conn.execute("SELECT start_geofence_id, end_geofence_id FROM trips").fetchone()
    assert (trip[0], trip[1]) == (home["id"], None)
    assert conn.execute("SELECT COUNT(*) FROM charges WHERE geofence_id IS NOT NULL").fetchone()[0] == 0
    assert places.get(conn, work["id"]) is None
    with pytest.raises(places.PlaceError) as err:
        places.delete(conn, home["id"])
    assert err.value.status == 400 and str(err.value) == "The home place cannot be deleted."
    with pytest.raises(places.PlaceNotFound):
        places.delete(conn, 9999)


def test_delete_place_clears_references_and_refuses_home():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.1, "lon": 8.1, "radius_m": 150})
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,start_lat,start_lon,end_lat,end_lon) VALUES(?,?,?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T08:00:00+00:00", "2027-02-10T08:40:00+00:00", 50.1, 8.1, 50.1, 8.1))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,lat,lon) VALUES(?,?,?,?)",
                 (vid, "2027-02-10T19:00:00+00:00", 50.1, 8.1))
    places.assign_all(conn)
    assert places.delete(conn, work["id"]) == {"trips": 1, "charges": 1}
    assert tuple(conn.execute("SELECT start_geofence_id, end_geofence_id FROM trips").fetchone()) == (None, None)
    assert conn.execute("SELECT geofence_id FROM charges").fetchone()[0] is None
    with pytest.raises(places.PlaceError):
        places.delete(conn, home["id"])

def test_upsert_home_creates_moves_and_clamps_without_a_second_home():
    conn = schema.connect(":memory:")
    home = places.upsert_home(conn, 50.0, 8.0)
    assert home["kind"] == "home" and home["name"] == "Home" and home["radius_m"] == 150
    moved = places.upsert_home(conn, 50.1, 8.1, name="Casa")
    assert moved["id"] == home["id"] and moved["lat"] == 50.1 and moved["name"] == "Home" and moved["radius_m"] == 150
    resized = places.upsert_home(conn, 50.2, 8.2, radius_m=5)
    assert resized["radius_m"] == 20
    assert conn.execute("SELECT COUNT(*) FROM geofences WHERE kind='home'").fetchone()[0] == 1


def test_detail_lists_visits_charges_and_totals():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T07:30:00+00:00", "2027-02-10T08:00:00+00:00", 50.0, 8.0))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t2", "2027-02-10T08:30:00+00:00", "2027-02-10T17:00:00+00:00", 51.0, 9.0))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t3", "2027-02-10T17:30:00+00:00", "2027-02-10T18:00:00+00:00", 50.0, 8.0))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,charge_type,lat,lon) VALUES(?,?,?,?,?,?,?)",
                 (vid, "2027-02-10T18:30:00+00:00", "2027-02-10T19:00:00+00:00", 10.0, "AC", 50.0, 8.0))
    places.assign_all(conn)
    d = places.detail(conn, home["id"], "2027-02-10T19:00:00+00:00")
    assert d["visit_count"] == 2 and len(d["visits"]) == 2
    current, first = d["visits"]
    assert current["open"] is True and current["left_at"] is None and current["minutes"] == 60
    assert first["open"] is False and first["left_at"] == "2027-02-10T08:30:00+00:00" and first["minutes"] == 30
    assert first["trip_id"] != current["trip_id"]
    assert d["parked_minutes"] == 90
    assert d["charged_kwh"] == 10.0 and d["cost"] == 3.0 and d["currency"] == "EUR"
    assert len(d["charges"]) == 1 and d["charges"][0]["cost"] == 3.0


def test_detail_does_not_treat_a_departure_after_twelve_hours_as_a_visit():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T07:30:00+00:00", "2027-02-10T08:00:00+00:00", 50.0, 8.0))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                 (vid, "t2", "2027-02-10T21:00:00+00:00", "2027-02-10T21:30:00+00:00", 51.0, 9.0))
    places.assign_all(conn)
    d = places.detail(conn, home["id"], "2027-02-10T22:00:00+00:00")
    visit = d["visits"][0]
    assert visit["open"] is False and visit["left_at"] is None and visit["minutes"] is None
    assert d["parked_minutes"] is None


def test_detail_ignores_missing_timestamps_and_returns_none_for_unknown_place():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,end_geofence_id) VALUES(?,?,?,?)",
                 (vid, "open", "2027-02-10T08:00:00+00:00", home["id"]))
    conn.commit()
    d = places.detail(conn, home["id"], "2027-02-10T22:00:00+00:00")
    assert d["visits"] == [] and d["parked_minutes"] == 0
    assert places.detail(conn, 9999, "2027-02-10T22:00:00+00:00") is None


def test_detail_lists_only_the_last_hundred_charges_but_sums_them_all():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0})
    vid = _vid(conn)
    for i in range(101):
        ts = f"2027-02-{1 + i // 24:02d}T{i % 24:02d}:00:00+00:00"
        conn.execute("INSERT INTO charges(vehicle_id,started_at,energy_kwh,charge_type,lat,lon) VALUES(?,?,?,?,?,?)",
                     (vid, ts, 1.0, "AC", 50.0, 8.0))
    places.assign_all(conn)
    d = places.detail(conn, home["id"], "2027-02-06T00:00:00+00:00")
    assert len(d["charges"]) == 100
    assert d["charges"][0]["started_at"] == "2027-02-05T04:00:00+00:00"
    assert d["charged_kwh"] == 101.0 and d["cost"] == 30.3
