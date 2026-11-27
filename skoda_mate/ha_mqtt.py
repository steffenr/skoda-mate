"""Home Assistant MQTT Discovery: payload builders (pure) and a robust paho publisher.

Only what the official API provides plus a few values Mate derives itself: sensors from the snapshot, binary sensors,
the position as a device tracker, last trip / last charge sensors, and - only when the user opts in - buttons / a number for
the commands the API offers (charging, charge limit, climate, stopping the heater, ventilation). There is deliberately no lock
entity (the API cannot lock or unlock) and no way to start the auxiliary heater: that needs the S-PIN, and anyone who can
publish to the broker could otherwise use it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import suppress

from . import activity

_LOG = logging.getLogger(__name__)

# key, name, unit, device_class, state_class, icon
SENSORS = [
    ("soc", "Battery", "%", "battery", "measurement", None),
    ("range_km", "Range", "km", "distance", "measurement", None),
    ("charge_power_kw", "Charging power", "kW", "power", "measurement", None),
    ("target_soc", "Charge limit", "%", None, None, "mdi:battery-charging-high"),
    ("remaining_min", "Time to full", "min", "duration", "measurement", None),
    ("charge_state", "Charge state", None, None, None, "mdi:ev-station"),
    ("charge_type", "Charge type", None, None, None, "mdi:current-ac"),
    ("mileage_km", "Odometer", "km", "distance", "total_increasing", None),
    ("fuel_pct", "Fuel level", "%", None, "measurement", "mdi:gas-station"),
    ("fuel_range_km", "Fuel range", "km", "distance", "measurement", None),
    ("climate_state", "Climate", None, None, None, "mdi:air-conditioner"),
    ("climate_target", "Climate target", "°C", "temperature", None, None),
    ("aux_state", "Auxiliary heater", None, None, None, "mdi:radiator"),
    ("vent_state", "Ventilation", None, None, None, "mdi:fan"),
    ("captured_at", "Last update from car", None, "timestamp", None, None),
]
# Values Mate derives itself (not in the API): the last finished trip and charge. Same tuple layout; "{currency}" is filled in.
EXTRAS = [
    ("last_trip_km", "Last trip distance", "km", "distance", None, "mdi:map-marker-distance"),
    ("last_trip_kwh", "Last trip energy", "kWh", "energy", None, None),
    ("last_trip_consumption", "Last trip consumption", "kWh/100 km", None, None, "mdi:speedometer"),
    ("last_charge_kwh", "Last charge energy", "kWh", "energy", None, None),
    ("last_charge_cost", "Last charge cost", "{currency}", "monetary", None, None),
    ("last_charge_place", "Last charge place", None, None, None, "mdi:ev-station"),
    ("place", "Place", None, None, None, "mdi:map-marker"),
    ("parked_loss_7d_kwh", "Parked loss (7 days)", "kWh", "energy", None, "mdi:battery-arrow-down"),
    ("parked_loss_7d_cost", "Parked loss cost (7 days)", "{currency}", "monetary", None, None),
    ("capacity_estimate_kwh", "Capacity estimate (from the wall)", "kWh", "energy_storage", "measurement", None),
    ("range_at_100_km", "Projected range at 100 %", "km", "distance", "measurement", None),
    ("quality_issues", "Data quality issues", None, None, "measurement", "mdi:clipboard-alert-outline"),
]
# key, name, device_class
BINARY = [
    ("charging", "Charging", "battery_charging"), ("plug_connected", "Plug connected", "plug"),
    ("plug_locked", "Plug locked", None), ("doors_open", "Doors open", "door"), ("windows_open", "Windows open", "window"),
    ("trunk_open", "Trunk open", "opening"), ("bonnet_open", "Bonnet open", "opening"), ("lights_on", "Lights", "light"),
    ("in_motion", "Driving", "moving"),
    ("climate_on", "Climate running", "running"),  # derived from climate_state, see state_values
]
# No "start_aux_heating": it sends the stored S-PIN, so it is never offered over MQTT (only on the Control page).
BUTTONS = [("start_charging", "Start charging"), ("stop_charging", "Stop charging"), ("start_climate", "Start climate"),
           ("stop_climate", "Stop climate"), ("stop_aux_heating", "Stop auxiliary heater"),
           ("start_ventilation", "Start ventilation"), ("stop_ventilation", "Stop ventilation")]
COMMANDS = frozenset([b[0] for b in BUTTONS] + ["set_charge_limit"])  # the only command names accepted over MQTT
RETIRED_BUTTONS = ["start_aux_heating"]  # announced by older versions: removed from Home Assistant again
CHARGE_LIMIT_RANGE = (50, 100)
TIMESTAMP_FIELDS = frozenset(["captured_at"])  # published to their field topic on every poll
COMMAND_INTERVAL_S = 30.0  # at most one MQTT command per car in this time; each one spends the car's ~20 requests/hour
DISCOVERY_PREFIX = "homeassistant"  # Home Assistant's default; the MQTT integration's "discovery prefix" must match


def topics(prefix: str, vin: str) -> dict:
    base = f"{prefix}/{vin}"
    # cmd_result is deliberately NOT under cmd/: Mate subscribes to cmd/# and must not read its own answers back.
    return {"state": f"{base}/state", "avail": f"{prefix}/status", "cmd": f"{base}/cmd", "attrs": f"{base}/position",
            "result": f"{base}/cmd_result", "fields": f"{base}/fields", "events": f"{base}/events"}


def result_payload(command: str, status: str, error: str | None = None, now: float | None = None) -> str:
    """What happened to a command from MQTT. status: sent | failed (Škoda or the car refused) | rejected (Mate did not send
    it: unsupported, bad value, request budget used up) | dropped (too soon after the previous one)."""
    at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now))
    return json.dumps({"command": command, "status": status, "ok": status == "sent", "error": error, "at": at})


def command_discovery_topics(vin: str) -> list[str]:
    """Discovery topics of all command entities, including retired ones: an empty retained payload removes them from HA."""
    return ([f"{DISCOVERY_PREFIX}/number/{vin}/charge_limit/config", f"{DISCOVERY_PREFIX}/sensor/{vin}/last_command/config"]
            + [f"{DISCOVERY_PREFIX}/button/{vin}/{key}/config" for key, _ in BUTTONS]
            + [f"{DISCOVERY_PREFIX}/button/{vin}/{key}/config" for key in RETIRED_BUTTONS])


def discovery(prefix: str, vin: str, name: str | None, model: str | None = None, currency: str = "EUR",
              commands: bool = False) -> list[tuple[str, dict]]:
    """Entity configs for one car. Command entities (buttons, charge-limit number) only with `commands`."""
    t = topics(prefix, vin)
    dev = {"identifiers": [f"skoda_mate_{vin}"], "name": name or vin, "manufacturer": "Škoda", "model": model or "Škoda",
           "sw_version": "skoda-mate", "serial_number": vin}
    common = {"device": dev, "availability_topic": t["avail"]}
    out = []
    for key, label, unit, dc, sc, icon in SENSORS + EXTRAS:
        p = {**common, "name": label, "unique_id": f"{vin}_{key}", "state_topic": t["state"],
             "value_template": f"{{{{ value_json.{key} if value_json.{key} is not none else '' }}}}"}
        for k, v in (("unit_of_measurement", unit.replace("{currency}", currency) if unit else unit), ("device_class", dc),
                     ("state_class", sc), ("icon", icon)):
            if v:
                p[k] = v
        out.append((f"{DISCOVERY_PREFIX}/sensor/{vin}/{key}/config", p))
    for key, label, dc in BINARY:
        p = {**common, "name": label, "unique_id": f"{vin}_{key}", "state_topic": t["state"],
             "payload_on": "ON", "payload_off": "OFF",
             "value_template": f"{{% if value_json.{key} is none %}}{{% elif value_json.{key} %}}ON{{% else %}}OFF{{% endif %}}"}
        if dc:
            p["device_class"] = dc
        out.append((f"{DISCOVERY_PREFIX}/binary_sensor/{vin}/{key}/config", p))
    out.append((f"{DISCOVERY_PREFIX}/binary_sensor/{vin}/locked/config",
                {**common, "name": "Unlocked", "unique_id": f"{vin}_locked", "state_topic": t["state"], "device_class": "lock",
                 "payload_on": "ON", "payload_off": "OFF",  # read-only: the API cannot lock or unlock
                 "value_template": "{% if value_json.locked is none %}{% elif value_json.locked %}OFF{% else %}ON{% endif %}"}))
    out.append((f"{DISCOVERY_PREFIX}/device_tracker/{vin}/location/config",
                {**common, "name": "Position", "unique_id": f"{vin}_location", "json_attributes_topic": t["attrs"],
                 "source_type": "gps"}))
    if not commands:
        return out
    out.append((f"{DISCOVERY_PREFIX}/sensor/{vin}/last_command/config",  # sent / failed / rejected / dropped, reason as attribute
                {**common, "name": "Last command", "unique_id": f"{vin}_last_command", "state_topic": t["result"],
                 "value_template": "{{ value_json.command }}: {{ value_json.status }}", "json_attributes_topic": t["result"],
                 "icon": "mdi:remote"}))
    out.append((f"{DISCOVERY_PREFIX}/number/{vin}/charge_limit/config",
                {**common, "name": "Charge limit", "unique_id": f"{vin}_charge_limit_set", "min": CHARGE_LIMIT_RANGE[0],
                 "max": CHARGE_LIMIT_RANGE[1], "step": 10,
                 "unit_of_measurement": "%", "command_topic": f"{t['cmd']}/set_charge_limit",
                 "state_topic": t["state"], "value_template": "{{ value_json.target_soc }}", "mode": "slider"}))
    for key, label in BUTTONS:
        out.append((f"{DISCOVERY_PREFIX}/button/{vin}/{key}/config",
                    {**common, "name": label, "unique_id": f"{vin}_btn_{key}", "command_topic": f"{t['cmd']}/{key}",
                     "payload_press": "PRESS"}))
    return out


def state_values(snap: dict, extras: dict | None = None) -> dict:
    """Every published value by key; unknown is None. A reading read back from the database holds 0/1 for yes/no, so
    those are turned into booleans again: both kinds of reading must publish the same."""
    out = {s[0]: snap.get(s[0]) for s in SENSORS}
    for key in [b[0] for b in BINARY] + ["locked"]:
        value = snap.get(key)
        out[key] = None if value is None else bool(value)
    climate = snap.get("climate_state")
    out["climate_on"] = None if climate in (None, "UNKNOWN") else climate in activity.heating_states()
    out.update({k[0]: (extras or {}).get(k[0]) for k in EXTRAS})
    return out


def state_payload(snap: dict, extras: dict | None = None) -> str:
    return json.dumps(state_values(snap, extras))


def position_payload(snap: dict) -> str | None:
    if snap.get("lat") is None or snap.get("lon") is None:
        return None  # while driving the API gives no position: keep the last one
    return json.dumps({"latitude": snap["lat"], "longitude": snap["lon"], "gps_accuracy": 50, "address": snap.get("address")})


def command_for(name: str, payload: str, last_target: float | None) -> tuple[str, dict]:
    """MQTT payload -> (command, params). The number entity sends the value; buttons send PRESS.

    Raises ValueError for anything that is not an allowed command or not a valid charge limit."""
    if name not in COMMANDS:
        raise ValueError(f"not an MQTT command: {name!r}")
    if name == "set_charge_limit":
        try:
            percent = int(float(payload))
        except (ValueError, OverflowError):  # "abc", "inf", "nan"
            raise ValueError(f"not a charge limit: {payload!r}") from None
        if not CHARGE_LIMIT_RANGE[0] <= percent <= CHARGE_LIMIT_RANGE[1]:
            raise ValueError(f"charge limit out of range: {percent}")
        return name, {"percent": percent}
    if name == "start_climate":
        return name, {"temperature": last_target or 21.0}
    return name, {}


def _failed(rc) -> bool:
    """paho 2 passes a ReasonCode (has is_failure); older style passes an int (0 = success)."""
    return bool(getattr(rc, "is_failure", rc not in (0, None)))


def explain(rc) -> str:
    text = str(rc)
    low = text.lower()
    if "not authorized" in low or "bad user" in low or "not authorised" in low:
        return "The broker refused the user name or password. Check both (in Home Assistant: the user must exist and be allowed to use MQTT)."
    return text


def _make_client(user, password, tls, tls_insecure, factory=None):
    import paho.mqtt.client as mqtt

    c = (factory or (lambda: mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)))()
    if user:
        c.username_pw_set(user, password or None)
    if tls:
        import ssl

        c.tls_set(cert_reqs=ssl.CERT_NONE if tls_insecure else ssl.CERT_REQUIRED)
        if tls_insecure:
            c.tls_insecure_set(True)
    return c


def probe(host: str, port: int, user: str = "", password: str = "", tls: bool = False, tls_insecure: bool = False,
          timeout: float = 6.0, client_factory=None) -> dict:
    """Try to connect once and report {ok, message}. Never leaves a connection or thread behind."""
    done = threading.Event()
    res = {"ok": False, "message": ""}

    def on_connect(_c, _u, _f, rc, *_a):
        if _failed(rc):
            res["message"] = explain(rc)
        else:
            res.update(ok=True, message="Connected to the broker.")
        done.set()

    def on_fail(*_a):
        res["message"] = f"Cannot reach {host}:{port}. Is the broker running, is the address right, and can Mate's computer or container reach it?"
        done.set()

    try:
        c = _make_client(user, password, tls, tls_insecure, client_factory)
    except Exception as e:  # TLS setup problems
        return {"ok": False, "message": f"Could not set up the connection: {e}"}
    c.on_connect, c.on_connect_fail = on_connect, on_fail
    try:
        c.connect_async(host, port, keepalive=10)
        c.loop_start()
        if not done.wait(timeout):
            res["message"] = f"No answer from {host}:{port} within {int(timeout)} s."
    except Exception as e:
        res["message"] = f"Could not connect: {e}"
    finally:
        try:
            c.loop_stop()
            c.disconnect()
        except Exception:
            pass
    return res


class Publisher:
    """paho client that keeps itself connected. With `commands` on, calls `on_command(vin, name, params)` for messages on
    command topics (only allowed commands, at most one per car every COMMAND_INTERVAL_S).

    A broker that is down at start-up (or later) never blocks or crashes Mate: the client retries, and on every
    (re)connect it announces the entities again and republishes the last states, so Home Assistant always catches up.
    """

    def __init__(self, host, port, user, password, prefix, on_command=None, *, tls=False, tls_insecure=False, discovery=True,
                 commands=False, publish_fields=True, extras=None, currency=lambda: "EUR", client_factory=None,
                 clock=time.monotonic):
        self.host, self.port, self.prefix, self.on_command = host, port, prefix, on_command
        self.discovery_on, self.commands_on, self.extras, self.currency = discovery, bool(commands), extras, currency
        self.clock = clock
        self.fields_on = bool(publish_fields)
        self.fields_sent: dict[str, dict[str, str]] = {}  # vin -> key -> the payload the broker has since this connect
        self.last_command: dict[str, float] = {}  # vin -> clock() of the last command taken from MQTT
        self.last_target: dict = {}
        self.vehicles: dict[str, tuple] = {}   # vin -> (name, model)
        self.last: dict[str, dict] = {}        # vin -> last snapshot, republished after a reconnect
        self.connected = False
        self.error: str | None = None
        self.entities = 0
        self.last_publish: float | None = None
        self._lock = threading.Lock()
        self.c = _make_client(user, password, tls, tls_insecure, client_factory)
        self.c.will_set(f"{prefix}/status", "offline", retain=True)
        self.c.on_connect, self.c.on_disconnect, self.c.on_message = self._on_connect, self._on_disconnect, self._msg
        self.c.on_connect_fail = self._on_fail
        with suppress(Exception):
            self.c.reconnect_delay_set(1, 30)
        self.c.connect_async(host, port, keepalive=30)
        self.c.loop_start()

    # ---- connection callbacks (run on paho's thread)
    def _on_connect(self, _c, _u, _f, rc, *_a):
        if _failed(rc):
            self.connected, self.error = False, explain(rc)
            return
        self.connected, self.error = True, None
        self.c.publish(f"{self.prefix}/status", "online", retain=True)
        with self._lock:
            self.fields_sent.clear()  # a restarted broker may have lost them: publish every field again
            for vin in list(self.vehicles):
                self._announce(vin)
            for vin, snap in list(self.last.items()):
                self._send_state(vin, snap)

    def _on_disconnect(self, _c, _u, *args):
        self.connected = False
        rc = args[-2] if len(args) >= 2 else (args[0] if args else None)
        if rc not in (None, 0) and _failed(rc):
            self.error = f"Connection lost: {rc}"

    def _on_fail(self, *_a):
        self.connected = False
        self.error = f"Cannot reach {self.host}:{self.port}."

    def _msg(self, _c, _u, m):
        """Runs on paho's network thread: nothing may escape from here, or the connection dies."""
        try:
            self._handle_message(m.topic, m.payload)
        except Exception:
            _LOG.exception("MQTT: could not handle a message on %s", getattr(m, "topic", "?"))

    def _handle_message(self, topic: str, payload: bytes):
        if not (self.commands_on and self.on_command):
            return  # commands from MQTT are switched off: ignore whatever arrives
        parts = topic.split("/")  # prefix/vin/cmd/name
        if len(parts) != 4 or parts[0] != self.prefix or parts[2] != "cmd":
            return
        vin, cmd = parts[1], parts[3]
        if vin not in self.vehicles:
            _LOG.warning("MQTT: ignored a command for an unknown car on %s", topic)
            return
        try:
            name, params = command_for(cmd, payload.decode(errors="replace"), self.last_target.get(vin))
        except ValueError as e:
            _LOG.warning("MQTT: ignored a command on %s: %s", topic, e)
            self.publish_result(vin, cmd[:40], "rejected", str(e))
            return
        now = self.clock()
        last = self.last_command.get(vin)
        if last is not None and now - last < COMMAND_INTERVAL_S:
            _LOG.warning("MQTT: dropped %s for %s: only one command every %d s (it would use up the car's request budget)",
                         name, vin, int(COMMAND_INTERVAL_S))
            self.publish_result(vin, name, "dropped", f"Only one command every {int(COMMAND_INTERVAL_S)} s.")
            return
        self.last_command[vin] = now
        self.on_command(vin, name, params)

    # ---- publishing
    def publish_result(self, vin: str, command: str, status: str, error: str | None = None) -> None:
        """Tell Home Assistant what became of a command (retained: the "Last command" sensor survives an HA restart).
        Thread-safe: called from paho's thread and from the event loop."""
        try:
            self.c.publish(topics(self.prefix, vin)["result"], result_payload(command, status, error), retain=True)
        except Exception:
            _LOG.exception("MQTT: could not publish the result of %s", command)

    def _announce(self, vin):
        name, model = self.vehicles[vin]
        if self.discovery_on:
            items = discovery(self.prefix, vin, name, model, self.currency(), commands=self.commands_on)
            for topic, payload in items:
                self.c.publish(topic, json.dumps(payload), retain=True)
            announced = {t for t, _ in items}
            for topic in command_discovery_topics(vin):  # remove command entities announced earlier (or by older versions)
                if topic not in announced:
                    self.c.publish(topic, "", retain=True)
            self.entities = len(items) * len(self.vehicles)
        else:
            self.entities = 0
        if self.commands_on:
            self.c.subscribe(f"{topics(self.prefix, vin)['cmd']}/#")

    def announce(self, vin, name, model=None):
        with self._lock:
            self.vehicles[vin] = (name, model)
            if self.connected:
                self._announce(vin)

    def _send_state(self, vin, snap):
        t = topics(self.prefix, vin)
        try:
            extras = self.extras(vin) if self.extras else {}
        except Exception:
            extras = {}
        values = state_values(snap, extras)
        self.c.publish(t["state"], json.dumps(values), retain=True)
        if self.fields_on:
            self._send_fields(vin, values)
        pos = position_payload(snap)
        if pos:
            self.c.publish(t["attrs"], pos, retain=True)
        self.last_publish = time.time()

    def _send_fields(self, vin: str, values: dict) -> None:
        """One retained topic per value, published when it changes (the car's timestamp every time). An unknown value
        is an empty payload, which removes the retained one from the broker."""
        sent = self.fields_sent.setdefault(vin, {})
        base = topics(self.prefix, vin)["fields"]
        for key, value in values.items():
            payload = "" if value is None else json.dumps(value)
            if key in TIMESTAMP_FIELDS or sent.get(key) != payload:
                self.c.publish(f"{base}/{key}", payload, retain=True)
                sent[key] = payload

    def publish_events(self, vin: str, events: list[dict]) -> None:
        """One message per event, not retained and not queued while the broker is away: an automation must never act
        on an old event."""
        if not self.connected:
            return
        for event in events:
            self.c.publish(topics(self.prefix, vin)["events"], json.dumps(event), qos=0, retain=False)

    def publish_state(self, vin, snap, sections=None):
        self.last_target[vin] = snap.get("climate_target") or self.last_target.get(vin)
        with self._lock:
            self.last[vin] = dict(snap)
            if self.connected:
                self._send_state(vin, snap)

    def status(self) -> dict:
        state = "connected" if self.connected else ("error" if self.error else "connecting")
        return {"state": state, "error": self.error, "entities": self.entities, "vehicles": len(self.vehicles),
                "host": self.host, "port": self.port, "last_publish": self.last_publish}

    def close(self):
        try:
            if self.connected:
                self.c.publish(f"{self.prefix}/status", "offline", retain=True).wait_for_publish(1)
        except Exception:
            pass
        try:
            self.c.loop_stop()
            self.c.disconnect()
        except Exception:
            pass
