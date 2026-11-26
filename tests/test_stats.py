from skoda_mate import costs, places, recorder, schema, stats


def test_odometer_distance_per_month_counts_drives_that_were_never_a_trip():
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "TMBJB9NY5RF999999", "Enyaq", None, 77.0)
    def rd(ts, odo):
        recorder.ingest(conn, vid, {"ts": ts, "soc": 50, "charging": False, "mileage_km": odo})
    rd("2027-01-10T08:00:00+00:00", 1000)
    rd("2027-01-31T20:00:00+00:00", 1100)
    rd("2027-02-02T08:00:00+00:00", 1180)  # the 80 km between 31 Jan and 2 Feb belong to February
    rd("2027-02-20T08:00:00+00:00", 1300)
    rd("2027-04-01T08:00:00+00:00", 1350)  # March has no reading: April carries the difference from February's last one
    months = {m["month"]: m for m in stats.monthly(conn, vid, costs.DEFAULT_TARIFF)}
    assert months["2027-01"]["odo_km"] == 100  # first month: highest minus lowest
    assert months["2027-02"]["odo_km"] == 200  # 1300 - 1100
    assert months["2027-04"]["odo_km"] == 50
    # the odometer is the authority: derived trips can only ever add up to (at most) what it measured
    assert all(m["km"] <= m["odo_km"] + 1e-6 for m in months.values() if m["odo_km"] is not None)
    t = stats.totals(conn, vid, costs.DEFAULT_TARIFF)
    assert t["odometer_km"] == 1350 and t["odometer_tracked_km"] == 350 and t["odometer_tracked_since"].startswith("2027-01-10")


def test_monthly_cost_uses_the_price_of_a_priced_place():
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "TMBJB9NY5RF999999", "Enyaq")
    places.create(conn, {"name": "Work", "kind": "work", "lat": 52.5, "lon": 13.4, "price_kwh": 0.50})
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,duration_min,charge_type,lat,lon) "
                 "VALUES(?,?,?,?,?,?,?,?)",
                 (vid, "2027-02-10T18:00:00+00:00", "2027-02-10T19:00:00+00:00", 10.0, 60, "AC", 52.5, 13.4))
    places.assign_all(conn)
    (m,) = stats.monthly(conn, vid, costs.DEFAULT_TARIFF)
    # 10 kWh at Work's 0.50 sit in the month's cost bucket, not the 0.55 public AC tariff
    assert m["cost"] == 5.0 and m["public_kwh"] == 10.0 and m["cost_known"] is True


def test_totals_without_any_reading_do_not_crash():
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "TMBJB9NY5RF999999", "Enyaq")
    t = stats.totals(conn, vid, costs.DEFAULT_TARIFF)
    assert t["odometer_km"] is None and t["odometer_tracked_km"] is None and t["km"] == 0
