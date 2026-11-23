import json
import types

import pytest

from skoda_mate import ha_mqtt, mqtt_config
from skoda_mate.secrets_store import SecretBox

from .test_web import connected


class RC:
    """A paho ReasonCode stand-in."""
    def __init__(self, text, failure=True): self.text, self.is_failure = text, failure
    def __str__(self): return self.text


class FakeClient:
    """Stands in for paho: records what would go to the broker; the test decides when the broker 'answers'."""
    instances: list = []

    def __init__(self):
        self.pub, self.subs, self.will, self.looping, self.closed = [], [], None, False, False
        FakeClient.instances.append(self)

    def username_pw_set(self, user, password=None): self.auth = (user, password)
    def will_set(self, topic, payload=None, retain=False): self.will = (topic, payload)
    def reconnect_delay_set(self, *a): pass
    def connect_async(self, host, port, keepalive=60): self.addr = (host, port)
    def loop_start(self): self.looping = True
    def loop_stop(self): self.looping = False
    def disconnect(self): self.closed = True
    def tls_set(self, **kw): self.tls = kw
    def tls_insecure_set(self, v): self.insecure = v
    def subscribe(self, t): self.subs.append(t)

    def publish(self, topic, payload=None, retain=False):
        self.pub.append((topic, payload))
        return types.SimpleNamespace(wait_for_publish=lambda timeout=None: None)

    def broker_accepts(self): self.on_connect(self, None, {}, 0, None)
    def broker_refuses(self, text="Not authorized"): self.on_connect(self, None, {}, RC(text), None)


@pytest.fixture(autouse=True)
def fake_paho(monkeypatch):
    FakeClient.instances.clear()
    real = ha_mqtt._make_client
    monkeypatch.setattr(ha_mqtt, "_make_client", lambda user, pw, tls, insecure, factory=None: real(user, pw, tls, insecure, factory=factory or FakeClient))


# ------------------------------------------------------------------ settings storage
def test_validation_gives_plain_messages():
    ok = mqtt_config.validate({"enabled": True, "host": "192.168.1.10", "port": "1883", "prefix": "skoda_mate"})
    assert ok["host"] == "192.168.1.10" and ok["port"] == 1883 and ok["discovery"] is True and ok["tls_insecure"] is False
    for bad, msg in (({"enabled": True, "host": ""}, "broker address"), ({"host": "http://ha.local"}, "no http://"), ({"host": "ha", "port": 0}, "port"),
                     ({"host": "ha", "port": "abc"}, "port"), ({"host": "ha", "prefix": "a/b"}, "topic prefix"), ({"host": "my broker"}, "no http://")):
        with pytest.raises(mqtt_config.MqttConfigError, match=msg):
            mqtt_config.validate(bad)
    assert mqtt_config.validate({"host": "ha", "tls": False, "tls_insecure": True})["tls_insecure"] is False  # "insecure" only means something with TLS


def test_password_is_encrypted_kept_and_never_shown():
    from skoda_mate import schema
    conn, box = schema.connect(":memory:"), SecretBox(None)
    saved = mqtt_config.save(conn, box, {"enabled": True, "host": "ha.local", "user": "mate", "password": "s3cret-pw"})
    raw = conn.execute("SELECT value FROM settings WHERE key='mqtt'").fetchone()[0]
    assert "s3cret-pw" not in raw and saved["password"] == "s3cret-pw"             # stored encrypted, readable only with the key
    assert "password" not in mqtt_config.public_view(saved) and mqtt_config.public_view(saved)["password_set"] is True
    again = mqtt_config.save(conn, box, {"enabled": True, "host": "ha.local", "user": "mate", "prefix": "other"})   # no password sent: keep it
    assert again["password"] == "s3cret-pw" and again["prefix"] == "other"
    cleared = mqtt_config.save(conn, box, {"enabled": False, "host": "ha.local", "clear_password": True})
    assert cleared["password"] == "" and mqtt_config.public_view(cleared)["password_set"] is False


def test_stored_password_is_only_kept_for_the_same_broker():
    from skoda_mate import schema
    conn, box = schema.connect(":memory:"), SecretBox(None)
    mqtt_config.save(conn, box, {"enabled": True, "host": "ha.local", "user": "mate", "password": "s3cret-pw"})
    for changed in ({"host": "evil.example"}, {"host": "ha.local", "port": 1884}, {"host": "ha.local", "tls": True}):
        with pytest.raises(mqtt_config.MqttConfigError, match="Enter the password again"):
            mqtt_config.save(conn, box, {"enabled": True, "user": "mate", **changed})
    assert mqtt_config.load(conn, box)["host"] == "ha.local"                                    # nothing was stored
    moved = mqtt_config.save(conn, box, {"enabled": True, "host": "new.local", "user": "mate", "password": "new-pw"})
    assert moved["password"] == "new-pw"                                                          # re-entered: fine
    gone = mqtt_config.save(conn, box, {"enabled": True, "host": "other.local", "clear_password": True})
    assert gone["password"] == ""
    assert mqtt_config.save(conn, box, {"enabled": True, "host": "third.local"})["host"] == "third.local"  # no password to protect


def test_commands_setting_defaults_to_off_and_is_saved():
    from skoda_mate import schema
    from skoda_mate.config import Config
    conn, box = schema.connect(":memory:"), SecretBox(None)
    assert mqtt_config.load(conn, box, Config(mqtt_host="10.0.0.5"))["commands"] is False             # env installs: off
    conn.execute("INSERT INTO settings(key, value) VALUES('mqtt', ?)", (json.dumps({"enabled": True, "host": "ha"}),))  # saved by an older version
    assert mqtt_config.load(conn, box)["commands"] is False
    saved = mqtt_config.save(conn, box, {"enabled": True, "host": "ha", "commands": True})
    assert saved["commands"] is True and mqtt_config.public_view(saved)["commands"] is True


def test_environment_variables_still_work_until_saved():
    from skoda_mate import schema
    from skoda_mate.config import Config
    conn, box = schema.connect(":memory:"), SecretBox(None)
    cfg = Config(mqtt_host="10.0.0.5", mqtt_user="u", mqtt_password="p")
    env = mqtt_config.load(conn, box, cfg)
    assert env["source"] == "env" and env["enabled"] and env["host"] == "10.0.0.5" and env["password"] == "p"
    mqtt_config.save(conn, box, {"enabled": False, "host": "ha.local"})
    assert mqtt_config.load(conn, box, cfg)["source"] == "db" and not mqtt_config.load(conn, box, cfg)["enabled"]


# ------------------------------------------------------------------ the publisher
def test_publisher_announces_on_connect_republishes_after_reconnect_and_survives_a_dead_broker():
    pub = ha_mqtt.Publisher("ha", 1883, "mate", "pw", "sm", commands=True, extras=lambda vin: {"last_trip_km": 12.3, "last_charge_cost": 6.82})
    c = FakeClient.instances[-1]
    assert c.looping and c.addr == ("ha", 1883) and c.will == ("sm/status", "offline") and c.auth == ("mate", "pw")
    assert pub.status()["state"] == "connecting"
    pub.announce("VIN1", "Enyaq")                       # broker not reachable yet: nothing is sent, nothing raises
    pub.publish_state("VIN1", {"soc": 61, "lat": 50.1, "lon": 8.6})
    assert c.pub == []
    c.broker_accepts()                                  # connected: online, discovery, subscriptions, the last state
    topics = [t for t, _ in c.pub]
    assert ("sm/status", "online") in c.pub and "homeassistant/sensor/VIN1/soc/config" in topics and "sm/VIN1/state" in topics
    assert "sm/VIN1/cmd/#" in c.subs and pub.status()["state"] == "connected" and pub.status()["entities"] > 20
    state = json.loads(dict(c.pub)["sm/VIN1/state"])
    assert state["soc"] == 61 and state["last_trip_km"] == 12.3 and state["last_charge_cost"] == 6.82
    n = len(c.pub)
    pub.publish_state("VIN1", {"soc": 60})
    assert len(c.pub) > n and json.loads(c.pub[-2][1] if c.pub[-1][0].endswith("position") else c.pub[-1][1])["soc"] == 60
    c.on_disconnect(c, None, {}, RC("Unspecified error"), None)   # the broker restarts ...
    assert pub.status()["state"] == "error"
    c.pub.clear(); c.broker_accepts()                                              # ... and Mate re-announces everything by itself
    assert any(t == "homeassistant/sensor/VIN1/soc/config" for t, _ in c.pub) and any(t == "sm/VIN1/state" for t, _ in c.pub)
    pub.close()
    assert c.closed and not c.looping


def test_discovery_can_be_switched_off_and_a_refused_login_is_explained():
    pub = ha_mqtt.Publisher("ha", 1883, "", "", "sm", discovery=False)
    c = FakeClient.instances[-1]
    pub.announce("VIN1", "Enyaq"); c.broker_accepts()
    assert not [t for t, _ in c.pub if t.startswith("homeassistant/")] and pub.status()["entities"] == 0
    pub2 = ha_mqtt.Publisher("ha", 1883, "mate", "wrong", "sm")
    FakeClient.instances[-1].broker_refuses("Not authorized")
    assert pub2.status()["state"] == "error" and "user name or password" in pub2.status()["error"]


def _send(client, topic, payload=b"PRESS"):
    client.on_message(client, None, types.SimpleNamespace(topic=topic, payload=payload))


def test_commands_are_off_by_default_ignored_and_their_entities_removed():
    seen = []
    pub = ha_mqtt.Publisher("ha", 1883, "", "", "sm", on_command=lambda *a: seen.append(a))
    c = FakeClient.instances[-1]
    pub.announce("VIN1", "Enyaq"); c.broker_accepts()
    assert c.subs == []                                                     # not even subscribed
    removed = {t for t, p in c.pub if p == ""}
    assert removed == set(ha_mqtt.command_discovery_topics("VIN1"))         # retained empty payloads: HA deletes old buttons
    assert not [t for t, p in c.pub if p and ("/button/" in t or "/number/" in t)]
    _send(c, "sm/VIN1/cmd/start_charging")
    assert seen == []


def test_allowed_commands_only_allowlisted_rate_limited_and_never_crash_paho():
    seen, now = [], [1000.0]
    pub = ha_mqtt.Publisher("ha", 1883, "", "", "sm", commands=True, on_command=lambda *a: seen.append(a), clock=lambda: now[0])
    c = FakeClient.instances[-1]
    pub.announce("VIN1", "Enyaq"); c.broker_accepts()
    assert c.subs == ["sm/VIN1/cmd/#"]
    assert ("homeassistant/button/VIN1/start_aux_heating/config", "") in c.pub          # removed even with commands on
    assert "homeassistant/button/VIN1/start_charging/config" in [t for t, p in c.pub if p]
    for topic, payload in (("sm/VIN1/cmd/start_aux_heating", b"PRESS"), ("sm/VIN1/cmd/unlock", b"PRESS"),
                           ("sm/VIN1/cmd/set_charge_limit", b"inf"), ("sm/VIN1/cmd/set_charge_limit", b"20"),
                           ("sm/OTHER/cmd/start_charging", b"PRESS"), ("other/VIN1/cmd/start_charging", b"PRESS"),
                           ("sm/VIN1/cmd/start_charging/x", b"PRESS")):
        _send(c, topic, payload)                                                         # nothing raises, nothing is sent
    assert seen == []
    _send(c, "sm/VIN1/cmd/set_charge_limit", b"80")
    assert seen == [("VIN1", "set_charge_limit", {"percent": 80})]
    now[0] += 10; _send(c, "sm/VIN1/cmd/stop_charging")                                  # too soon: dropped
    assert len(seen) == 1
    now[0] += ha_mqtt.COMMAND_INTERVAL_S; _send(c, "sm/VIN1/cmd/stop_charging")
    assert seen[-1] == ("VIN1", "stop_charging", {})

    def boom(*a): raise RuntimeError("callback failed")
    pub.on_command = boom
    now[0] += 60; _send(c, "sm/VIN1/cmd/start_charging")                                 # logged, not raised into paho
    _send(c, "sm/VIN1/cmd/start_charging", None)                                         # even a broken message object


def test_tls_options_reach_the_client():
    ha_mqtt.Publisher("ha", 8883, "", "", "sm", tls=True, tls_insecure=True)
    c = FakeClient.instances[-1]
    assert c.tls and c.insecure is True


def test_extra_sensors_are_in_discovery_with_the_currency():
    items = dict(ha_mqtt.discovery("sm", "V", "Car", None, currency="CHF"))
    cost = items["homeassistant/sensor/V/last_charge_cost/config"]
    assert cost["unit_of_measurement"] == "CHF" and cost["device_class"] == "monetary"
    assert items["homeassistant/sensor/V/last_trip_km/config"]["unit_of_measurement"] == "km"
    assert json.loads(ha_mqtt.state_payload({"soc": 5}))["last_trip_km"] is None


def test_probe_reports_success_refusal_and_unreachable():
    ok = ha_mqtt.probe("ha", 1883, client_factory=lambda: _answering("ok"), timeout=1)
    assert ok["ok"] is True
    refused = ha_mqtt.probe("ha", 1883, "mate", "bad", client_factory=lambda: _answering("refused"), timeout=1)
    assert refused["ok"] is False and "user name or password" in refused["message"]
    gone = ha_mqtt.probe("10.255.255.1", 1883, client_factory=lambda: _answering("unreachable"), timeout=1)
    assert gone["ok"] is False and "Cannot reach 10.255.255.1:1883" in gone["message"]
    silent = ha_mqtt.probe("ha", 1883, client_factory=lambda: _answering("silent"), timeout=0.2)
    assert silent["ok"] is False and "No answer" in silent["message"]


def _answering(mode):
    c = FakeClient()

    def connect_async(host, port, keepalive=60):
        if mode == "ok":
            c.on_connect(c, None, {}, 0, None)
        elif mode == "refused":
            c.on_connect(c, None, {}, RC("Not authorized"), None)
        elif mode == "unreachable":
            c.on_connect_fail(c, None)
    c.connect_async = connect_async
    return c


# ------------------------------------------------------------------ the HTTP endpoints
def test_settings_endpoints_save_apply_and_never_leak_the_password():
    c, conn, api, vid = connected()
    first = c.get("/api/settings/mqtt").json()
    assert first["config"]["enabled"] is False and first["status"]["state"] == "disabled" and first["config"]["prefix"] == "skoda_mate"
    assert first["discovery_prefix"] == "homeassistant" and first["entities_per_car"] > 20
    assert c.put("/api/settings/mqtt", json={"enabled": True, "host": ""}).status_code == 400
    assert c.put("/api/settings/mqtt", json={"enabled": True, "host": "ha", "prefix": "bad/prefix"}).status_code == 400
    r = c.put("/api/settings/mqtt", json={"enabled": True, "host": "192.168.1.10", "user": "mate", "password": "pw-1", "prefix": "garage"})
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["host"] == "192.168.1.10" and body["config"]["password_set"] is True and "pw-1" not in json.dumps(body)
    assert body["status"]["state"] in ("connecting", "connected")              # the publisher was started right away, no restart
    live = FakeClient.instances[-1]
    assert live.addr == ("192.168.1.10", 1883) and live.auth == ("mate", "pw-1")
    assert body["config"]["commands"] is False
    live.broker_accepts()
    assert live.subs == [] and live.pub                                          # announced, but commands are opt-in
    assert c.get("/api/settings/mqtt").json()["status"]["state"] == "connected"
    c.put("/api/settings/mqtt", json={"enabled": True, "host": "192.168.1.10", "user": "mate", "prefix": "garage"})   # password left out
    assert FakeClient.instances[-1].auth == ("mate", "pw-1") and live.closed
    on = c.put("/api/settings/mqtt", json={"enabled": True, "host": "192.168.1.10", "user": "mate", "prefix": "garage", "commands": True}).json()
    FakeClient.instances[-1].broker_accepts()
    assert on["config"]["commands"] is True and FakeClient.instances[-1].subs and all(s.startswith("garage/") for s in FakeClient.instances[-1].subs)
    assert on["entities_per_car"] > body["entities_per_car"]
    off = c.put("/api/settings/mqtt", json={"enabled": False, "host": "192.168.1.10"}).json()
    assert off["status"]["state"] == "disabled"


def test_connection_test_uses_form_values_and_stored_password(monkeypatch):
    c, conn, api, vid = connected()
    c.put("/api/settings/mqtt", json={"enabled": False, "host": "ha", "user": "mate", "password": "stored-pw"})
    seen = {}
    monkeypatch.setattr(ha_mqtt, "probe", lambda host, port, user, password, tls, insecure, **k: seen.update(a=(host, port, user, password, tls)) or {"ok": True, "message": "Connected to the broker."})
    r = c.post("/api/settings/mqtt/test", json={"host": "ha", "port": 1883, "user": "other"})
    assert r.json()["ok"] is True and seen["a"] == ("ha", 1883, "other", "stored-pw", False)        # same broker: stored password
    for moved in ({"host": "attacker.example"}, {"host": "ha", "port": 1884}, {"host": "ha", "tls": True}):
        seen.clear()
        r = c.post("/api/settings/mqtt/test", json={"user": "mate", **moved})                       # never sent to another broker
        assert r.json() == {"ok": False, "message": "Enter the password again: the broker address changed."} and not seen
    c.post("/api/settings/mqtt/test", json={"host": "192.168.1.20", "user": "mate", "password": "typed"})
    assert seen["a"][:4] == ("192.168.1.20", 1883, "mate", "typed")
    c.post("/api/settings/mqtt/test", json={"host": "192.168.1.20", "user": "mate", "clear_password": True})
    assert seen["a"][3] == ""
    r = c.put("/api/settings/mqtt", json={"enabled": False, "host": "192.168.1.20", "user": "mate"})
    assert r.status_code == 400 and "Enter the password again" in r.json()["detail"]
    assert c.post("/api/settings/mqtt/test", json={"host": ""}).status_code == 400
    assert c.post("/api/settings/mqtt/test", json={"host": "no spaces allowed"}).status_code == 400


# ------------------------------------------------------------------ command results back to Home Assistant
def _results(client, topic):
    return [json.loads(p) for t, p in client.pub if t == topic and p]


def test_refused_and_dropped_commands_are_reported_to_home_assistant():
    now = [1000.0]
    pub = ha_mqtt.Publisher("ha", 1883, "", "", "sm", commands=True, on_command=lambda *a: None, clock=lambda: now[0])
    c = FakeClient.instances[-1]
    pub.announce("VIN1", "Enyaq"); c.broker_accepts()
    cfg = dict(ha_mqtt.discovery("sm", "VIN1", "Enyaq", commands=True))["homeassistant/sensor/VIN1/last_command/config"]
    assert cfg["state_topic"] == "sm/VIN1/cmd_result" and not cfg["state_topic"].startswith("sm/VIN1/cmd/")  # never read back
    assert "homeassistant/sensor/VIN1/last_command/config" in ha_mqtt.command_discovery_topics("VIN1")  # removed when off
    _send(c, "sm/VIN1/cmd/set_charge_limit", b"20")
    assert _results(c, "sm/VIN1/cmd_result")[-1]["status"] == "rejected"
    _send(c, "sm/VIN1/cmd/stop_charging"); now[0] += 5; _send(c, "sm/VIN1/cmd/start_charging")
    last = _results(c, "sm/VIN1/cmd_result")[-1]
    assert last["command"] == "start_charging" and last["status"] == "dropped" and last["ok"] is False and "30 s" in last["error"]


def _wait_for(pred, timeout=3.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_mqtt_command_outcomes_reach_home_assistant_and_mates_log(monkeypatch):
    from skoda_mate import commands
    from skoda_mate.client import ApiError
    from .fixtures import VIN

    c, conn, api, vid = connected()
    c.put("/api/settings/mqtt", json={"enabled": True, "host": "ha", "prefix": "garage", "commands": True})
    broker = FakeClient.instances[-1]
    broker.broker_accepts()
    topic = f"garage/{VIN}/cmd_result"
    ha_mqtt_interval = ha_mqtt.COMMAND_INTERVAL_S
    monkeypatch.setattr(ha_mqtt, "COMMAND_INTERVAL_S", 0)  # the 30 s limit has its own test
    try:
        _send(broker, f"garage/{VIN}/cmd/stop_charging")
        assert _wait_for(lambda: _results(broker, topic)), "no result published"
        assert _results(broker, topic)[-1]["status"] == "sent"

        api.operate_error = ApiError(409, "vehicle-not-accepting-requests")
        _send(broker, f"garage/{VIN}/cmd/start_charging")
        assert _wait_for(lambda: len(_results(broker, topic)) == 2)
        failed = _results(broker, topic)[-1]
        assert failed["status"] == "failed" and "declined" in failed["error"]

        def refuse(*a, **k):
            raise commands.CommandError("Škoda's request limit is used up; try again in 5 min.")
        monkeypatch.setattr(commands, "build", refuse)
        _send(broker, f"garage/{VIN}/cmd/stop_climate")
        assert _wait_for(lambda: len(_results(broker, topic)) == 3)
        assert _results(broker, topic)[-1] == {**_results(broker, topic)[-1], "command": "stop_climate", "status": "rejected", "ok": False}
    finally:
        monkeypatch.setattr(ha_mqtt, "COMMAND_INTERVAL_S", ha_mqtt_interval)
    log = conn.execute("SELECT name, ok, kind, source FROM commands WHERE vehicle_id=? ORDER BY id", (vid,)).fetchall()
    assert [tuple(r) for r in log][-3:] == [("stop_charging", 1, None, "mqtt"), ("start_charging", 0, "vehicle-not-accepting-requests", "mqtt"),
                                            ("stop_climate", 0, "rejected", "mqtt")]
