"""Parked loss: SoC lost while the car stood still, as sessions plus aggregates."""
from datetime import UTC, datetime, timedelta

from skoda_mate import activity, costs, places, schema

from .test_activity import _vid
from .test_web import connected

START = datetime(2027, 3, 1, 0, 0, tzinfo=UTC)
FROM, TO = "2027-03-01T00:00:00+00:00", "2027-03-02T00:00:00+00:00"


def _ts(hours: float) -> str:
    return (START + timedelta(hours=hours)).isoformat()


def _snap(conn, vid, hours, soc, *, charging=0, in_motion=0, lat=None, lon=None):
    conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,soc,charging,in_motion,lat,lon) VALUES(?,?,?,?,?,?,?)",
                 (vid, _ts(hours), soc, charging, in_motion, lat, lon))
    conn.commit()


def _stand(conn, vid, begin, end, soc_start, soc_end, step=0.5, **kw):
    """Readings every `step` hours from `begin` to `end`: SoC stays at the start value, the last reading has the end."""
    t = begin
    while t < end - 1e-9:
        _snap(conn, vid, t, soc_start, **kw)
        t += step
    _snap(conn, vid, end, soc_end, **kw)


def _setup():
    conn = schema.connect(":memory:")
    return conn, _vid(conn)


def test_twelve_hour_stand_with_two_percent_drop():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 78)
    out = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)
    assert len(out["sessions"]) == 1
    s = out["sessions"][0]
    assert (s["start"], s["end"], s["hours"]) == (_ts(0), _ts(12), 12.0)
    assert (s["start_soc"], s["end_soc"], s["soc_delta"]) == (80, 78, 2)
    assert (s["kwh"], s["kwh_per_day"]) == (1.2, 2.4)
    assert s["warning"] is None and s["below_detection_floor"] is False
    assert out["detection_floor_kwh"] == 0.6 and out["min_hours"] == 6.0
    agg = out["aggregates"]
    assert (agg["count"], agg["kwh"], agg["median_kwh_per_day"], agg["mean_kwh_per_day"]) == (1, 1.2, 2.4, 2.4)


def test_zero_delta_is_below_the_detection_floor():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 80)
    s = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)["sessions"][0]
    assert s["below_detection_floor"] is True and s["kwh"] == 0.0 and s["kwh_per_day"] == 0.0
    assert s["warning"] is None


def test_positive_delta_is_an_unrecorded_charge():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 83)
    out = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)
    s = out["sessions"][0]
    assert s["soc_delta"] == -3 and s["warning"] == "likely an unrecorded charge"
    assert s["cost"] is None
    assert out["aggregates"]["count"] == 0 and out["aggregates"]["kwh"] is None
    assert out["aggregates"]["median_kwh_per_day"] is None and out["aggregates"]["cost"] is None


def test_huge_delta_is_an_unrecorded_charge():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 90, 60)
    out = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)
    assert out["sessions"][0]["warning"] == "likely an unrecorded charge"
    assert out["aggregates"]["count"] == 0


def test_charging_reading_ends_the_session():
    conn, vid = _setup()
    _stand(conn, vid, 0, 7, 80, 79)
    _snap(conn, vid, 7.5, 81, charging=1)
    _stand(conn, vid, 8, 15, 81, 80)
    out = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)
    assert [(s["start"], s["end"]) for s in out["sessions"]] == [(_ts(0), _ts(7)), (_ts(8), _ts(15))]


def test_gap_over_one_hour_splits_the_session():
    conn, vid = _setup()
    _stand(conn, vid, 0, 7, 80, 79)
    _stand(conn, vid, 9, 16, 79, 78)  # 2 h without a reading in between
    out = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)
    assert [(s["start"], s["end"], s["soc_delta"]) for s in out["sessions"]] == [(_ts(0), _ts(7), 1),
                                                                                 (_ts(9), _ts(16), 1)]


def test_a_charge_inside_a_stand_excludes_it_instead_of_inflating_the_loss():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 78)  # no charging reading, but the charge row says the car charged at 5-6 h
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at) VALUES(?,?,?)", (vid, _ts(5), _ts(6)))
    conn.commit()
    assert activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)["sessions"] == []


def test_a_trip_touching_the_stand_edge_does_not_exclude_it():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 78)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at) VALUES(?,?,?,?)",
                 (vid, "t1", _ts(12), _ts(13)))
    conn.commit()
    assert len(activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)["sessions"]) == 1


def test_min_hours_filters_short_stands():
    conn, vid = _setup()
    _stand(conn, vid, 0, 5, 80, 79)
    _stand(conn, vid, 7, 15, 79, 78)
    out = activity.parked_loss(conn, vid, FROM, TO, min_hours=6.0, capacity_kwh=60.0)
    assert [s["hours"] for s in out["sessions"]] == [8.0]
    out = activity.parked_loss(conn, vid, FROM, TO, min_hours=4.0, capacity_kwh=60.0)
    assert [s["hours"] for s in out["sessions"]] == [5.0, 8.0]


def test_home_tariff_and_place_price_choose_cost_basis():
    conn, vid = _setup()
    places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    places.create(conn, {"name": "Garage", "kind": "public", "lat": 51.0, "lon": 9.0, "radius_m": 150,
                         "price_kwh": 0.5})
    _stand(conn, vid, 0, 12, 80, 70, lat=50.0, lon=8.0)  # delta 10 -> 6 kWh
    _stand(conn, vid, 14, 26, 70, 60, lat=51.0, lon=9.0)  # 6 kWh
    out = activity.parked_loss(conn, vid, FROM, "2027-03-03T00:00:00+00:00", capacity_kwh=60.0,
                               tariff=costs.load_tariff(conn))
    home, garage = out["sessions"]
    assert (home["place"], home["cost_basis"], home["cost"]) == ("Home", "tariff", 1.8)
    assert (garage["place"], garage["cost_basis"], garage["cost"]) == ("Garage", "place", 3.0)
    assert out["aggregates"]["cost"] == 4.8


def test_parked_loss_prices_energy_only_never_minutes_or_a_session_fee():
    """A stand is energy that left the battery, not a charging session: no per-minute price, no session fee."""
    conn, vid = _setup()
    places.create(conn, {"name": "Garage", "kind": "public", "lat": 51.0, "lon": 9.0, "radius_m": 150,
                         "price_kwh": 0.5, "price_minute": 0.1, "session_fee": 1.0})
    places.create(conn, {"name": "Mall", "kind": "place", "lat": 52.0, "lon": 10.0, "radius_m": 150,
                         "session_fee": 2.0})
    places.create(conn, {"name": "Office", "kind": "work", "lat": 53.0, "lon": 11.0, "radius_m": 150,
                         "price_minute": 0.2, "free": True})
    _stand(conn, vid, 0, 12, 80, 78, lat=51.0, lon=9.0)  # 2 points -> 1.2 kWh, 12 h at 0.10/min would be 72.00
    _stand(conn, vid, 14, 26, 78, 76, lat=52.0, lon=10.0)  # 1.2 kWh, session fee only
    _stand(conn, vid, 28, 40, 76, 74, lat=53.0, lon=11.0)  # 1.2 kWh at a free place
    tariff = costs.load_tariff(conn)
    out = activity.parked_loss(conn, vid, FROM, "2027-03-03T00:00:00+00:00", capacity_kwh=60.0, tariff=tariff)
    garage, mall, office = out["sessions"]
    assert (garage["place"], garage["cost_basis"], garage["cost"]) == ("Garage", "place", 0.6)
    assert (mall["place"], mall["cost_basis"], mall["cost"]) == ("Mall", "tariff",
                                                                  round(1.2 * tariff["public_ac_kwh"], 2))
    assert (office["place"], office["cost_basis"], office["cost"]) == ("Office", "place", 0.0)
    assert out["aggregates"]["cost"] == round(0.6 + 1.2 * tariff["public_ac_kwh"], 2)


def test_missing_capacity_keeps_kwh_null():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 78)
    out = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=None)
    s = out["sessions"][0]
    assert (s["kwh"], s["kwh_per_day"], s["cost"]) == (None, None, None) and s["soc_delta"] == 2
    assert out["detection_floor_kwh"] is None
    assert out["aggregates"]["count"] == 0 and out["aggregates"]["cost"] is None


def test_recent_windows_count_sessions_ending_before_to():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 78)  # ends 1 Mar 12:00
    out = activity.parked_loss(conn, vid, FROM, "2027-03-20T00:00:00+00:00", capacity_kwh=60.0)
    assert (out["aggregates"]["kwh_7d"], out["aggregates"]["kwh_30d"]) == (None, 1.2)  # nothing ended in 7 days: None, not 0
    out = activity.parked_loss(conn, vid, FROM, "2027-03-05T00:00:00+00:00", capacity_kwh=60.0)
    assert (out["aggregates"]["kwh_7d"], out["aggregates"]["kwh_30d"]) == (1.2, 1.2)


def test_a_reading_exactly_at_the_range_end_does_not_size_an_open_charge():
    conn, vid = _setup()
    conn.execute("INSERT INTO charges(vehicle_id,started_at) VALUES(?,?)", (vid, _ts(0)))
    conn.commit()
    _snap(conn, vid, 2, 50)  # exactly the half-open end: not evidence inside the range
    assert activity.intervals(conn, vid, _ts(0), _ts(2)) == []


def test_route_rejects_bad_min_hours():
    c, conn, api, vid = connected()
    for bad in ("0.5", "169"):
        r = c.get(f"/api/vehicles/{vid}/parked-loss?min_hours={bad}")
        assert r.status_code == 400 and r.json()["detail"] == "min_hours must be between 1 and 168."


def test_route_other_vehicle_404():
    c, conn, api, vid = connected()
    r = c.get("/api/vehicles/999/parked-loss")
    assert r.status_code == 404 and r.json()["detail"] == "no such vehicle"


def test_route_returns_the_shape():
    c, conn, api, vid = connected()
    body = c.get(f"/api/vehicles/{vid}/parked-loss?from=2027-03-01&to=2027-03-02&tz_offset=-60").json()
    assert body["sessions"] == [] and body["min_hours"] == 6.0
    assert set(body["aggregates"]) >= {"count", "median_kwh_per_day", "mean_kwh_per_day", "kwh", "kwh_7d",
                                       "kwh_30d", "cost"}


def test_stands_below_the_floor_total_zero_and_no_stands_total_nothing():
    """0.0 means stands were counted and none lost a measurable point; None means no stand counted in that window.
    The dashboard shows the first as "below the detection floor" and the second as a dash."""
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 80)
    agg = activity.parked_loss(conn, vid, FROM, "2027-03-05T00:00:00+00:00", capacity_kwh=60.0)["aggregates"]
    assert (agg["count"], agg["kwh"], agg["kwh_7d"], agg["kwh_30d"]) == (1, 0.0, 0.0, 0.0)
    empty = activity.parked_loss(conn, vid, "2027-04-01T00:00:00+00:00", "2027-04-10T00:00:00+00:00",
                                 capacity_kwh=60.0)["aggregates"]
    assert (empty["count"], empty["kwh"], empty["kwh_7d"], empty["kwh_30d"]) == (0, None, None, None)


def _year(conn, vid, step_min=20):
    """A year of a commuter's readings: parked every `step_min` minutes, two 30-minute drives a day (5-minute
    readings plus a trip row), a three-hour charge every fourth evening (5-minute readings plus a charge row)."""
    snaps, trips, charges = [], [], []
    for day in range(365):
        d0 = START + timedelta(days=day)
        for h0, h1, kind in ((0, 8, "p"), (8, 8.5, "d"), (8.5, 17, "p"), (17, 17.5, "d"), (17.5, 20, "p"),
                             (20, 23, "c" if day % 4 == 0 else "p"), (23, 24, "p")):
            a, b = d0 + timedelta(hours=h0), d0 + timedelta(hours=h1)
            step = timedelta(minutes=5 if kind in "dc" else step_min)
            x = a
            while x < b:
                snaps.append((vid, x.isoformat(), 60, int(kind == "c"), int(kind == "d")))
                x += step
            if kind == "d":
                trips.append((vid, f"c{a.isoformat()}", a.isoformat(), b.isoformat(), 15.0))
            if kind == "c":
                charges.append((vid, a.isoformat(), b.isoformat(), 20.0))
    for sql, rows in (("INSERT INTO snapshots(vehicle_id,recorded_at,soc,charging,in_motion) VALUES(?,?,?,?,?)", snaps),
                      ("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km) VALUES(?,?,?,?,?)",
                       trips),
                      ("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh) VALUES(?,?,?,?)", charges)):
        for row in rows:
            conn.execute(sql, row)
    conn.commit()


def test_a_year_of_twenty_minute_readings_answers_in_well_under_two_seconds():
    """The Parked tab asks for 12 months by default; laying ~800 trips and charges over ~32k readings one by one
    took 10 s. The bound is generous for CI; the measured time is in the final fix report."""
    import time
    conn, vid = _setup()
    _year(conn, vid)
    t0 = time.perf_counter()
    out = activity.parked_loss(conn, vid, START.isoformat(), (START + timedelta(days=365)).isoformat(),
                               capacity_kwh=60.0)
    elapsed = time.perf_counter() - t0
    assert len(out["sessions"]) == 730  # the night and the working day of every day; evenings are too short
    assert elapsed < 2.0, f"parked loss over a year took {elapsed:.2f} s"


def test_route_rejects_a_reversed_range():
    c, conn, api, vid = connected()
    r = c.get(f"/api/vehicles/{vid}/parked-loss?from=2027-03-05&to=2027-03-01")
    assert r.status_code == 400 and r.json()["detail"] == "The start must be before the end."
    assert c.get(f"/api/vehicles/{vid}/parked-loss?from=2027-03-01&to=2027-03-01").status_code == 200  # one day


def test_zero_delta_without_a_capacity_has_no_energy_but_is_below_the_floor():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 80)
    out = activity.parked_loss(conn, vid, FROM, TO)
    s = out["sessions"][0]
    assert (s["kwh"], s["kwh_per_day"], s["cost"], s["cost_basis"]) == (None, None, None, "none")
    assert s["below_detection_floor"] is True and s["warning"] is None
    assert out["aggregates"]["count"] == 0 and out["aggregates"]["kwh"] is None


def test_a_run_ends_at_a_reading_without_a_soc():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 78)
    conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,soc) VALUES(?,?,NULL)", (vid, _ts(12.5)))
    _snap(conn, vid, 13, 70)
    conn.commit()
    s = activity.parked_loss(conn, vid, FROM, TO, capacity_kwh=60.0)["sessions"]
    assert [(x["end"], x["end_soc"]) for x in s] == [(_ts(12), 78)]  # the 70 % reading is a lone reading, not a stand


def test_the_median_of_an_even_number_of_stands_is_the_mean_of_the_middle_two():
    conn, vid = _setup()
    _stand(conn, vid, 0, 12, 80, 79)    # 1 point in 12 h -> 0.6 kWh -> 1.2 kWh/day
    _stand(conn, vid, 14, 26, 79, 76)   # 3 points -> 1.8 kWh -> 3.6 kWh/day
    agg = activity.parked_loss(conn, vid, FROM, "2027-03-03T00:00:00+00:00", capacity_kwh=60.0)["aggregates"]
    assert (agg["count"], agg["median_kwh_per_day"], agg["mean_kwh_per_day"]) == (2, 2.4, 2.4)


def test_the_cost_basis_of_a_zero_kwh_stand_names_the_place_or_tariff_that_would_price_it():
    conn, vid = _setup()
    places.create(conn, {"name": "Garage", "kind": "public", "lat": 51.0, "lon": 9.0, "radius_m": 150,
                         "price_kwh": 0.5})
    _stand(conn, vid, 0, 12, 80, 80, lat=51.0, lon=9.0)    # below the floor at a place with a per-kWh price
    _stand(conn, vid, 14, 26, 80, 80)                      # below the floor, nowhere in particular
    _stand(conn, vid, 28, 40, 80, 78, lat=51.0, lon=9.0)   # a measurable loss at the same place
    garage0, nowhere, garage2 = activity.parked_loss(conn, vid, FROM, "2027-03-03T00:00:00+00:00", capacity_kwh=60.0,
                                                     tariff=costs.load_tariff(conn))["sessions"]
    assert garage2["cost_basis"] == "place" and garage2["cost"] == 0.6
    assert (garage0["cost_basis"], garage0["cost"]) == ("place", None)
    assert (nowhere["cost_basis"], nowhere["cost"]) == ("tariff-guess", None)
