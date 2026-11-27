"""The entities Mate adds from its own records, and the values behind them."""
import json
from datetime import UTC, datetime

import pytest

from skoda_mate import demo, ha_mqtt, ha_values, places, recorder, schema

NOW = datetime(2026, 1, 3, 12, 0, tzinfo=UTC)
HOME = (50.11, 8.68)
KEYS = ("place", "parked_loss_7d_kwh", "parked_loss_7d_cost", "capacity_estimate_kwh", "range_at_100_km",
        "last_charge_place", "quality_issues")


def make(kwh=77.0):
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "VIN1", "Enyaq", None, kwh)
    places.create(conn, {"name": "Home", "kind": "home", "lat": HOME[0], "lon": HOME[1], "radius_m": 150})
    return conn, vid


def reading(conn, vid, hour, soc=60, day=3, **kw):
    kw = {"in_motion": False, "lat": HOME[0], "lon": HOME[1], "range_km": soc * 4, **kw}
    recorder.ingest(conn, vid, {"ts": f"2026-01-{day:02d}T{hour:02d}:00:00+00:00", "soc": soc, "charging": False, **kw})


def values(conn, clock=lambda: 0.0):
    return ha_values.Values(conn, clock=clock, utcnow=lambda: NOW)


def test_discovery_lists_the_new_entities_with_their_units():
    items = dict(ha_mqtt.discovery("sm", "VIN1", "Enyaq", currency="CHF"))
    sensor = {key: items[f"homeassistant/sensor/VIN1/{key}/config"] for key in KEYS}
    shown = {key: (p.get("unit_of_measurement"), p.get("device_class")) for key, p in sensor.items()}
    assert shown == {"place": (None, None), "parked_loss_7d_kwh": ("kWh", "energy"),
                     "parked_loss_7d_cost": ("CHF", "monetary"), "capacity_estimate_kwh": ("kWh", "energy_storage"),
                     "range_at_100_km": ("km", "distance"), "last_charge_place": (None, None), "quality_issues": (None, None)}
    assert items["homeassistant/binary_sensor/VIN1/climate_on/config"]["device_class"] == "running"
    assert all(p["device"]["serial_number"] == "VIN1" for p in items.values())


@pytest.mark.parametrize("state, expected", [("HEATING", True), ("VENTILATION", True), ("OFF", False),
                                             ("UNKNOWN", None), (None, None)])
def test_climate_on_follows_the_climate_state(state, expected):
    assert json.loads(ha_mqtt.state_payload({"climate_state": state}))["climate_on"] is expected


def test_place_is_the_parked_place_and_unknown_while_driving():
    conn, vid = make()
    reading(conn, vid, 8)
    assert values(conn).for_vin("VIN1")["place"] == "Home"
    reading(conn, vid, 9, in_motion=True, lat=None, lon=None)
    assert values(conn).for_vin("VIN1")["place"] is None


def test_what_cannot_be_derived_is_unknown_not_zero():
    conn, vid = make(kwh=None)
    got = values(conn).for_vin("VIN1")
    assert all(got[key] is None for key in KEYS if key != "quality_issues")
    assert values(conn).for_vin("NOPE") == {}


def test_parked_loss_range_and_last_charge_place():
    conn, vid = make()
    for hour in range(13):  # a 12 h stand with hourly readings that loses 2 %
        reading(conn, vid, hour, 60 if hour < 6 else 58)
    reading(conn, vid, 9, 58, day=1, charging=True, charge_state="CHARGING", charge_power_kw=11.0)
    reading(conn, vid, 10, 70, day=1, charge_state="READY_FOR_CHARGING")
    got = values(conn).for_vin("VIN1")
    assert got["range_at_100_km"] == pytest.approx(400, abs=1)
    assert got["parked_loss_7d_kwh"] is not None and got["last_charge_place"] == "Home"
    assert isinstance(got["quality_issues"], int)


def test_one_value_that_fails_leaves_the_others(monkeypatch):
    conn, vid = make()
    reading(conn, vid, 8)
    monkeypatch.setattr(ha_values.quality, "checks", lambda *a: 1 / 0)
    got = values(conn).for_vin("VIN1")
    assert got["quality_issues"] is None and got["place"] == "Home" and got["range_at_100_km"] is not None


def test_the_expensive_values_are_cached_until_the_car_has_a_new_event(monkeypatch):
    conn, vid = make()
    reading(conn, vid, 8)
    calls, now = [], [0.0]
    monkeypatch.setattr(ha_values.quality, "checks", lambda *a: calls.append(1) or [])
    v = values(conn, clock=lambda: now[0])
    v.for_vin("VIN1")
    now[0] = 899
    v.for_vin("VIN1")
    assert len(calls) == 1
    now[0] = 901
    v.for_vin("VIN1")
    assert len(calls) == 2
    reading(conn, vid, 9, plug_connected=False)
    reading(conn, vid, 10, plug_connected=True)  # writes an event
    v.for_vin("VIN1")
    assert len(calls) == 3


def test_a_demo_car_shows_the_new_values():
    conn = schema.connect(":memory:")
    now = datetime.now(UTC)
    demo.seed(conn, now=now)
    got = ha_values.Values(conn).for_vin(demo.DEMO_VIN)
    missing = [k for k in ("parked_loss_7d_kwh", "capacity_estimate_kwh", "range_at_100_km", "quality_issues") if got[k] is None]
    assert missing == []
