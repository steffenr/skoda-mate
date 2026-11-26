from skoda_mate import costs, places, presenters, schema

TARIFF = {"currency": "EUR", "home_kwh": 0.30, "public_ac_kwh": 0.55, "public_dc_kwh": 0.79,
          "home_lat": 50.0, "home_lon": 8.0, "home_radius_m": 150}


def test_place_price_includes_energy_minutes_and_session_fee():
    place = {"kind": "work", "price_kwh": 0.50, "price_minute": 0.02, "session_fee": 1.0, "free": 0}
    charge = {"energy_kwh": 20.0, "duration_min": 60, "charge_type": "AC"}
    assert costs.charge_cost(charge, TARIFF, place) == {"amount": 12.2, "kind": "public", "basis": "place"}


def test_manual_cost_wins_over_place_price():
    place = {"kind": "home", "price_kwh": 0.50, "free": 0}
    charge = {"energy_kwh": 20.0, "cost_manual": 7.0, "charge_type": "AC"}
    assert costs.charge_cost(charge, TARIFF, place) == {"amount": 7.0, "kind": "home", "basis": "manual"}


def test_manual_place_kind_overrides_the_place_kind():
    place = {"kind": "work", "price_kwh": 0.50, "free": 0}
    charge = {"energy_kwh": 10.0, "place_kind": "home", "charge_type": "AC"}
    assert costs.charge_cost(charge, TARIFF, place) == {"amount": 5.0, "kind": "home", "basis": "place"}


def test_free_place_costs_zero_without_energy():
    place = {"kind": "work", "price_kwh": 0.50, "price_minute": 0.02, "session_fee": 3.0, "free": 1}
    assert costs.charge_cost({"charge_type": "AC"}, TARIFF, place) == {"amount": 0.0, "kind": "public", "basis": "place"}


def test_manual_cost_wins_on_a_free_place():
    place = {"kind": "work", "free": 1}
    assert costs.charge_cost({"cost_manual": 3.0}, TARIFF, place) == {"amount": 3.0, "kind": "public", "basis": "manual"}


def test_minute_price_without_duration_is_unknown():
    place = {"kind": "work", "price_minute": 0.02, "free": 0}
    assert costs.charge_cost({"charge_type": "AC"}, TARIFF, place)["amount"] is None


def test_place_without_price_falls_back_to_tariff_and_unknown_energy_is_unknown():
    no_price = {"kind": "work", "free": 0}
    assert costs.charge_cost({"energy_kwh": 10.0, "charge_type": "AC"}, TARIFF, no_price) == {
        "amount": 5.5, "kind": "public", "basis": "tariff"}
    priced = {"kind": "work", "price_kwh": 0.50, "free": 0}
    assert costs.charge_cost({"charge_type": "AC"}, TARIFF, priced) == {"amount": None, "kind": "public", "basis": "place"}


def test_charge_out_names_the_place_and_prices_with_it():
    conn = schema.connect(":memory:")
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.0, "lon": 8.0, "price_kwh": 0.50})
    conn.execute("INSERT INTO vehicles(vin) VALUES(?)", ("VIN",))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,duration_min,charge_type,lat,lon) "
                 "VALUES(1,?,?,?,?,?,?,?)",
                 ("2027-02-10T18:00:00+00:00", "2027-02-10T19:00:00+00:00", 10.0, 60, "AC", 50.0, 8.0))
    places.assign_all(conn)
    row = dict(conn.execute("SELECT * FROM charges").fetchone())
    out = presenters.charge_out(row, costs.DEFAULT_TARIFF, conn)
    assert out["place"] == {"id": work["id"], "name": "Work", "kind": "work"}
    assert out["cost"] == 5.0 and out["cost_basis"] == "place" and out["place_kind_resolved"] == "public"
