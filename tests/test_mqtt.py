import json
import types

import pytest

from skoda_mate import ha_mqtt, mqtt_config, recorder, schema
from skoda_mate.cloud import Cloud
from skoda_mate.config import Config
from skoda_mate.secrets_store import SecretBox

from .test_mqtt_settings import FakeClient


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


# ------------------------------------------------------------------ one topic per value, and events

class Broker(FakeClient):
    """FakeClient that also records how each message was sent."""

    def __init__(self):
        super().__init__()
        self.sent: list[tuple] = []  # (topic, payload, retain, qos)

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.sent.append((topic, payload, retain, qos))
        return super().publish(topic, payload, retain)

    def fields(self) -> dict:
        """The field messages since the last `clear`, by key."""
        return {t.rsplit("/", 1)[1]: (p, retain) for t, p, retain, _ in self.sent if "/fields/" in t}


def publisher(**kw):
    pub = ha_mqtt.Publisher("broker", 1883, "", "", "sm", client_factory=Broker, **kw)
    pub.announce("VIN1", "Enyaq")
    pub.c.broker_accepts()
    pub.c.sent.clear()
    return pub


STATE = {"soc": 50, "charging": False, "locked": True, "charge_state": "READY_FOR_CHARGING", "captured_at": "2026-01-01T10:00:00+00:00"}


def test_one_retained_topic_per_state_value():
    pub = publisher()
    pub.publish_state("VIN1", STATE)
    fields = pub.c.fields()
    assert set(fields) == set(json.loads(ha_mqtt.state_payload({})))
    assert fields["soc"] == ("50", True) and fields["charging"] == ("false", True)
    assert fields["charge_state"] == ('"READY_FOR_CHARGING"', True)
    assert fields["range_km"] == ("", True)  # unknown: an empty retained payload clears what an earlier run left
    assert fields["last_trip_km"] == ("", True)


def test_only_changed_values_and_the_timestamp_are_published_again():
    pub = publisher()
    pub.publish_state("VIN1", STATE)
    pub.c.sent.clear()
    pub.publish_state("VIN1", {**STATE, "soc": 51})
    assert pub.c.fields() == {"soc": ("51", True), "captured_at": ('"2026-01-01T10:00:00+00:00"', True)}


def test_a_value_that_becomes_unknown_is_cleared():
    pub = publisher()
    pub.publish_state("VIN1", STATE)
    pub.c.sent.clear()
    pub.publish_state("VIN1", {**STATE, "soc": None})
    assert pub.c.fields()["soc"] == ("", True)


def test_booleans_from_the_database_publish_like_live_ones():
    pub = publisher()
    pub.publish_state("VIN1", STATE)
    pub.c.sent.clear()
    pub.publish_state("VIN1", {**STATE, "charging": 0, "locked": 1})  # a row read back from SQLite
    assert set(pub.c.fields()) == {"captured_at"}
    assert json.loads(ha_mqtt.state_payload({"charging": 0, "locked": 1}))["locked"] is True


def test_every_field_is_published_again_after_a_reconnect():
    pub = publisher()
    pub.publish_state("VIN1", STATE)
    pub.c.sent.clear()
    pub.c.broker_accepts()
    assert pub.c.fields()["soc"] == ("50", True)


def test_the_toggle_stops_field_topics_and_leaves_discovery_alone():
    on, off = publisher(), publisher(publish_fields=False)
    off.publish_state("VIN1", STATE)
    assert off.c.fields() == {} and [t for t, *_ in off.c.sent] == ["sm/VIN1/state"]
    on.c.sent.clear()
    off.c.sent.clear()
    on.c.broker_accepts()
    off.c.broker_accepts()

    def announced(pub):
        return [(t, v) for t, v, *_ in pub.c.sent if t.startswith("homeassistant/")]

    assert announced(on) == announced(off) != []


def test_events_are_published_once_each_and_not_retained():
    pub = publisher(publish_fields=False)  # events do not depend on the field topics
    events = [{"id": "a", "event": "plug.connected", "data": {}}, {"id": "b", "event": "soc.low", "data": {"soc": 19}}]
    pub.publish_events("VIN1", events)
    assert [(t, json.loads(p), retain, qos) for t, p, retain, qos in pub.c.sent] == [
        ("sm/VIN1/events", events[0], False, 0), ("sm/VIN1/events", events[1], False, 0)]


def test_events_are_dropped_while_the_broker_is_away():
    pub = ha_mqtt.Publisher("broker", 1883, "", "", "sm", client_factory=Broker)
    pub.publish_events("VIN1", [{"id": "a", "event": "soc.low", "data": {}}])
    pub.c.broker_accepts()
    assert not [t for t, *_ in pub.c.sent if t.endswith("/events")]  # no stale event is replayed later


def test_publish_fields_is_a_stored_setting_that_defaults_to_on():
    conn, box = schema.connect(":memory:"), SecretBox(None)
    assert mqtt_config.load(conn, box)["publish_fields"] is True
    mqtt_config.save(conn, box, {"enabled": True, "host": "b", "publish_fields": False})
    assert mqtt_config.public_view(mqtt_config.load(conn, box))["publish_fields"] is False
    mqtt_config.save(conn, box, {"enabled": True, "host": "b"})
    assert mqtt_config.load(conn, box)["publish_fields"] is True


def test_the_cloud_sends_events_to_mqtt_with_the_car_named():
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "VIN1", "Enyaq")
    cloud = Cloud(conn, SecretBox(None), Config(db_path=":memory:"), types.SimpleNamespace(publisher=publisher()))
    cloud.dispatch(vid, [{"event": "plug.connected", "at": "2026-01-01T10:00:00+00:00", "data": {}}])
    topic, payload, retain, _ = cloud.poller.publisher.c.sent[-1]
    assert (topic, retain) == ("sm/VIN1/events", False)
    assert json.loads(payload)["vehicle"] == {"id": vid, "name": "Enyaq", "vin": "VIN1"}
