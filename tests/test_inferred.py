
from skoda_mate import costs, recorder, schema, stats


def make(kwh=77.0):
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "TMBJB9NY5RF999999", "Enyaq", None, kwh)
    return conn, vid


def trip(conn, vid, start, end, s0, s1, place_a="Home", place_b="Work", lat=50.0, lon=8.0):
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km,start_soc,end_soc,start_place,end_place,"
                 "start_lat,start_lon,end_lat,end_lon) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (vid, f"t-{start}", start, end, 30, s0, s1, place_a, place_b, lat, lon, lat + 0.1, lon + 0.1))
    conn.commit()


def charges(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM charges ORDER BY started_at")]


def test_a_trip_that_starts_higher_than_the_last_one_ended_proves_a_charge():
    conn, vid = make()
    trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 36)
    trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 63, 52)  # +27 points overnight
    assert recorder.infer_charges(conn, vid) == 1
    (c,) = charges(conn)
    assert c["source"] == "inferred" and c["start_soc"] == 36 and c["end_soc"] == 63
    assert c["started_at"] == "2026-11-20T07:30:00+00:00" and c["ended_at"] == "2026-11-21T08:00:00+00:00"  # the window it MUST lie in
    assert abs(c["energy_battery_kwh"] - 20.79) < 0.01 and abs(c["energy_kwh"] - 20.79 / 0.9) < 0.01  # level change x capacity
    assert c["address"] == "Work" and c["lat"] == 50.1 and c["charge_type"] is None  # where the car stood; type unknown


def test_small_rises_and_driving_are_not_charges():
    conn, vid = make()
    trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 60)
    trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 62, 50)  # +2: rounding / regen, below the threshold
    trip(conn, vid, "2026-11-21T17:00:00+00:00", "2026-11-21T17:30:00+00:00", 50, 40)
    assert recorder.infer_charges(conn, vid) == 0 and charges(conn) == []


def test_parked_readings_reveal_a_charge_nobody_watched_but_a_drive_in_between_does_not():
    conn, vid = make()
    def rd(ts, soc, **k):
        recorder.ingest(conn, vid, {"ts": ts, "soc": soc, "charging": False, "in_motion": False, "lat": 50.0, "lon": 8.0, **k})
    rd("2026-11-20T10:00:00+00:00", 40)
    rd("2026-11-20T10:20:00+00:00", 41)
    rd("2026-11-20T14:00:00+00:00", 75)  # rose 34 points between two parked readings, never seen charging
    (c,) = charges(conn)
    assert c["source"] == "inferred" and c["start_soc"] == 40 and c["end_soc"] == 75
    conn2, vid2 = make()
    trip(conn2, vid2, "2026-11-20T10:00:00+00:00", "2026-11-20T10:40:00+00:00", 80, 50)
    recorder.ingest(conn2, vid2, {"ts": "2026-11-20T09:00:00+00:00", "soc": 80, "charging": False, "in_motion": False})
    recorder.ingest(conn2, vid2, {"ts": "2026-11-20T11:00:00+00:00", "soc": 50, "charging": False, "in_motion": False})
    assert charges(conn2) == []  # 80 -> 50 is a drive, not a charge


def test_a_measured_charge_wins_and_replaces_an_inferred_one():
    conn, vid = make()
    trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 36)
    trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 80, 70)
    recorder.infer_charges(conn, vid)
    assert [c["source"] for c in charges(conn)] == ["inferred"]
    def ch(ts, soc, state, p=None):
        recorder.ingest(conn, vid, {"ts": ts, "soc": soc, "charging": state == "CHARGING", "charge_state": state,
                                    "charge_power_kw": p, "charge_type": "AC", "in_motion": False})
    ch("2026-11-20T22:00:00+00:00", 36, "CHARGING", 10.0)  # now the car is caught charging inside that window
    ch("2026-11-21T01:00:00+00:00", 66, "CHARGING", 10.0)
    ch("2026-11-21T01:05:00+00:00", 80, "READY_FOR_CHARGING")
    assert [c["source"] for c in charges(conn)] == ["detected"]  # the inferred row is gone, no double counting


def test_idempotent_and_user_edits_survive():
    conn, vid = make()
    trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 36)
    trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 63, 52)
    assert recorder.infer_charges(conn, vid) == 1 and recorder.infer_charges(conn, vid) == 0
    conn.execute("UPDATE charges SET note='at my sister''s', place_kind='public'")
    conn.commit()
    conn.execute("DELETE FROM trips WHERE start_soc=63")  # the evidence disappears...
    conn.commit()
    recorder.infer_charges(conn, vid)
    (c,) = charges(conn)
    assert c["note"] == "at my sister's" and c["place_kind"] == "public"  # ...but a row the user edited is never deleted silently


def test_an_inferred_charge_has_no_average_power_only_a_typical_wallbox_estimate():
    """Regression: 24.8 kWh over a 12.5 h overnight window was shown as '2.0 kW average power' for an 11 kW charger."""
    from skoda_mate.presenters import TYPICAL_WALLBOX_KW

    from .test_web import connected

    c, conn, api, vid = connected()
    conn.execute("UPDATE vehicles SET battery_kwh=77")  # the energy of an inferred charge needs the capacity
    conn.commit()
    trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 36)
    trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 63, 52)
    recorder.infer_charges(conn, vid)
    item = [x for x in c.get(f"/api/vehicles/{vid}/charges").json()["items"] if x["start_soc"] == 36][0]  # the overnight one
    assert item["inferred"] and item["avg_power_kw"] is None and item["max_power_kw"] is None
    assert item["duration_min"] > 24 * 60 - 60  # the window is a whole day, not charging time
    assert item["hours_at_typical_wallbox"] == round(item["energy_kwh"] / TYPICAL_WALLBOX_KW, 1) and 1 < item["hours_at_typical_wallbox"] < 3
    # a measured charge still reports its real average power
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,duration_min,max_power_kw,source) VALUES(?,?,?,?,?,?,'detected')",
                 (vid, "2026-11-25T22:00:00+00:00", "2026-11-26T01:00:00+00:00", 30.0, 180, 10.9))
    conn.commit()
    live = [x for x in c.get(f"/api/vehicles/{vid}/charges").json()["items"] if not x["inferred"]][0]
    assert live["avg_power_kw"] == 10.0 and live["max_power_kw"] == 10.9 and live["hours_at_typical_wallbox"] is None


def test_without_battery_capacity_the_energy_is_unknown_but_the_charge_is_still_listed():
    conn, vid = make(kwh=None)
    trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 36)
    trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 63, 52)
    recorder.infer_charges(conn, vid)
    (c,) = charges(conn)
    assert c["energy_kwh"] is None and c["start_soc"] == 36 and c["end_soc"] == 63


def test_statistics_keep_inferred_energy_apart_from_measured_ac_dc():
    conn, vid = make()
    trip(conn, vid, "2026-11-20T07:00:00+00:00", "2026-11-20T07:30:00+00:00", 70, 36)
    trip(conn, vid, "2026-11-21T08:00:00+00:00", "2026-11-21T08:30:00+00:00", 63, 52)
    recorder.infer_charges(conn, vid)
    (m,) = [m for m in stats.monthly(conn, vid, costs.DEFAULT_TARIFF) if m["month"] == "2026-11"]
    assert m["charges"] == 1 and m["inferred_charges"] == 1 and m["inferred_kwh"] > 20
    assert m["ac_kwh"] == 0 and m["dc_kwh"] == 0 and m["charged_kwh"] == m["inferred_kwh"]
    # no home position is set, so the place is unknown: it must NOT be reported as "public"
    assert m["public_kwh"] == 0 and m["home_kwh"] == 0 and m["unknown_place_kwh"] == m["charged_kwh"]
    t = stats.totals(conn, vid, costs.DEFAULT_TARIFF)
    assert t["charges"] == 1 and t["inferred_charges"] == 1 and t["charged_kwh"] > 20
