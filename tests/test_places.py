import json

from skoda_mate import schema


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
