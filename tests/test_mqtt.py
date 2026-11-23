import json

import pytest

from skoda_mate import ha_mqtt


def test_discovery_has_no_command_entities_unless_commands_are_allowed():
    topics = [t for t, _ in ha_mqtt.discovery("sm", "VIN1", "Enyaq", "iV")]
    assert not [t for t in topics if "/button/" in t or "/number/" in t] and not [t for t in topics if "cmd" in t]
    assert set(ha_mqtt.command_discovery_topics("VIN1")) & set(topics) == set()
    with_cmds = [t for t, _ in ha_mqtt.discovery("sm", "VIN1", "Enyaq", "iV", commands=True)]
    assert set(with_cmds) - set(topics) <= set(ha_mqtt.command_discovery_topics("VIN1"))
    assert "homeassistant/button/VIN1/start_aux_heating/config" not in with_cmds   # needs the S-PIN: never over MQTT
    assert "homeassistant/button/VIN1/start_aux_heating/config" in ha_mqtt.command_discovery_topics("VIN1")  # ... so it gets removed


def test_discovery_is_unique_json_and_has_no_lock_command():
    items = ha_mqtt.discovery("sm", "VIN1", "Enyaq", "iV", commands=True)
    ids = [p["unique_id"] for _, p in items]
    assert len(ids) == len(set(ids))
    topics = [t for t, _ in items]
    assert "homeassistant/sensor/VIN1/soc/config" in topics and "homeassistant/device_tracker/VIN1/location/config" in topics
    assert all(json.dumps(p) for _, p in items)
    assert not [t for t in topics if "/lock/" in t or "unlock" in t]  # the API cannot lock or unlock
    assert not [t for t, p in items if t.startswith("homeassistant/lock")]
    btn = dict(items)["homeassistant/button/VIN1/start_charging/config"]
    assert btn["command_topic"] == "sm/VIN1/cmd/start_charging"
    num = dict(items)["homeassistant/number/VIN1/charge_limit/config"]
    assert num["command_topic"] == "sm/VIN1/cmd/set_charge_limit" and (num["min"], num["max"], num["step"]) == (50, 100, 10)


def test_state_payload_keeps_unknowns_as_null():
    p = json.loads(ha_mqtt.state_payload({"soc": 50, "charging": False, "locked": None}))
    assert p["soc"] == 50 and p["charging"] is False and p["locked"] is None and p["range_km"] is None


def test_position_only_when_known():
    assert ha_mqtt.position_payload({"lat": None, "lon": None}) is None  # while driving: keep the last position
    p = json.loads(ha_mqtt.position_payload({"lat": 50.1, "lon": 8.6, "address": "X"}))
    assert (p["latitude"], p["longitude"]) == (50.1, 8.6)


def test_mqtt_payloads_become_commands():
    assert ha_mqtt.command_for("set_charge_limit", "80.0", None) == ("set_charge_limit", {"percent": 80})
    assert ha_mqtt.command_for("start_climate", "PRESS", 22.5) == ("start_climate", {"temperature": 22.5})
    assert ha_mqtt.command_for("start_climate", "PRESS", None)[1] == {"temperature": 21.0}
    assert ha_mqtt.command_for("stop_charging", "PRESS", None) == ("stop_charging", {})


@pytest.mark.parametrize("name, payload", [
    ("start_aux_heating", "PRESS"),            # uses the S-PIN: not allowed over MQTT
    ("lock", "PRESS"), ("anything_else", "PRESS"), ("", ""),
    ("set_charge_limit", "inf"), ("set_charge_limit", "-inf"), ("set_charge_limit", "nan"), ("set_charge_limit", "1e400"),
    ("set_charge_limit", "abc"), ("set_charge_limit", "49"), ("set_charge_limit", "101"), ("set_charge_limit", "-80"),
])
def test_bad_mqtt_commands_are_rejected_with_value_error(name, payload):
    with pytest.raises(ValueError):
        ha_mqtt.command_for(name, payload, None)
