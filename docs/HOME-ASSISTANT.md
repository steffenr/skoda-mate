# Home Assistant with Škoda Mate

Škoda Mate can show your car in Home Assistant as a normal **device** with sensors, a map position and control buttons.
It uses **MQTT discovery**: you only tell Mate where your MQTT broker is, and Home Assistant creates every entity by itself.

Everything is set up in the dashboard: **Settings → MQTT → Home Assistant**. No environment variables, no restart.

## What you need

- Home Assistant running in your network (any installation type).
- An **MQTT broker**. If you use Home Assistant OS or Supervised, the *Mosquitto broker* add-on is the easy way (step 1).
- Škoda Mate connected to your Škoda account (the API key is already entered), and a network path from Mate to the broker.

## Step by step

### 1. Make sure an MQTT broker runs

**Home Assistant OS / Supervised**

1. *Settings → Add-ons → Add-on store*
2. Search for **Mosquitto broker**, open it, press **Install**
3. Press **Start** and switch on **Start on boot**

**Home Assistant in Docker or Core** — run your own Mosquitto. A minimal `docker-compose.yml`:

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    restart: unless-stopped
    ports: ["1883:1883"]
    volumes: ["./mosquitto:/mosquitto/config"]
```

with `./mosquitto/mosquitto.conf`:

```
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
```

Create the user with `docker compose exec mosquitto mosquitto_passwd -c /mosquitto/config/passwd skoda_mate`
(it asks for the password), then restart the container.

### 2. Create a user for Mate

**With the Mosquitto add-on**: *Settings → People → Users → Add user*. Choose a name such as `skoda_mate` and a password.
Administrator rights are not needed. The add-on accepts Home Assistant users.

### 3. Add the MQTT integration to Home Assistant

*Settings → Devices & services → Add integration → MQTT*

| Field | Value |
|---|---|
| Broker | `core-mosquitto` (add-on) or the broker's IP address |
| Port | `1883` |
| Username / password | the user from step 2 |

Leave **Enable discovery** switched on. The discovery prefix must stay `homeassistant` (the default).

### 4. Fill in Škoda Mate

Open **Settings** in Mate and find the card **MQTT → Home Assistant**:

| Field | What to enter |
|---|---|
| **Broker** | The **IP address** of the machine that runs the broker, usually the IP address of Home Assistant, for example `192.168.1.10` |
| **Port** | `1883` (or `8883` with TLS) |
| **Username / Password** | the user from step 2 |
| **Topic prefix** | leave `skoda_mate`. Change it only if two Mate installations use the same broker |
| **Discovery** | ticked |
| **Allow commands from Home Assistant** | off, unless you want buttons and the charge-limit slider (see *Controls* below) |
| **TLS** | only if your broker is set up for TLS. *TLS insecure* accepts a self-signed certificate |

> **Mate runs in Docker or DDEV?** Then `localhost` and `homeassistant.local` usually do not work from inside the container.
> Use Home Assistant's **IP address**. In your router, give Home Assistant a fixed address so it does not change.

### 5. Test, enable, save

1. Press **Test connection**. It tries the values on the form without saving anything.
   - **Connected to the broker** → continue.
   - *Cannot reach …* → wrong IP or port, broker not running, or a firewall.
   - *The broker refused the user name or password* → check the user and password.
2. Tick **Enabled** and press **Save**. The status at the top of the card changes to **Connected** and shows how many entities were created.

The password is stored **encrypted**. It is never shown again; leave the field empty to keep it. If you change the broker
address, port or TLS setting, enter the password again: Mate only sends the stored password to the broker it was saved for.

### 6. Find your car in Home Assistant

*Settings → Devices & services → MQTT → Devices*. Your car appears as a device named like the car, with about 30 entities (about 40 with commands allowed).
Add them to a dashboard: *Overview → pencil icon → Add card → Tile / Entities*.

## What you get

**Sensors**

| Entity | Unit |
|---|---|
| Battery | % |
| Range | km |
| Charging power | kW |
| Charge limit | % |
| Time to full | min |
| Charge state / Charge type | text |
| Odometer | km |
| Climate, Climate target | text, °C |
| Auxiliary heater, Ventilation | text |
| Fuel level, Fuel range (combustion/hybrid cars) | %, km |
| Last update from car | timestamp |

**Values Mate calculates itself** (not provided by Škoda). What cannot be worked out is *unknown*, never zero.

| Entity | Key | Unit | What it is |
|---|---|---|---|
| Last trip distance, energy, consumption | `last_trip_km`, `last_trip_kwh`, `last_trip_consumption` | km, kWh, kWh/100 km | the last finished trip |
| Last charge energy, cost, place | `last_charge_kwh`, `last_charge_cost`, `last_charge_place` | kWh, your currency, text | the last finished charge; cost uses your **Prices** |
| Place | `place` | text | the [place](PLACES.md) the car is parked in; unknown while driving or away from your places |
| Parked loss (7 days), and its cost | `parked_loss_7d_kwh`, `parked_loss_7d_cost` | kWh, your currency | [battery lost while parked](ACTIVITY.md#parked-loss) |
| Capacity estimate (from the wall) | `capacity_estimate_kwh` | kWh | wall energy per 100 % from long AC charges, so it includes charging losses; **not** battery health |
| Projected range at 100 % | `range_at_100_km` | km | [the reported range scaled to a full battery](INSIGHTS.md#projected-range) |
| Data quality issues | `quality_issues` | count | checks on the [data-quality card](ACTIVITY.md#data-quality) with something open |

Parked loss, capacity, range and quality are recalculated at most every 15 minutes, and at once when something happens
(a trip or charge ends, the cable is plugged in, ...).

**Binary sensors**: Charging, Plug connected, Plug locked, Doors open, Windows open, Trunk open, Bonnet open, Lights, Driving,
Climate running, Unlocked. The lock state is **read-only** because the Škoda API cannot lock or unlock the car.

**Position**: a *device tracker*, so the car appears on the Home Assistant map.

**Controls** (opt-in): only when **Allow commands from Home Assistant** is ticked, Mate adds buttons *Start/Stop charging*,
*Start/Stop climate*, *Start/Stop ventilation*, *Stop auxiliary heater*, and a **Charge limit** slider (50–100 %, steps of 10),
and listens for them on `<prefix>/<VIN>/cmd/<name>`. With the box unticked (the default) Mate ignores every command message and
removes these entities from Home Assistant again.

- **Anyone who can publish to your broker can then control these functions.** Restrict the broker with ACLs (only Home Assistant
  may publish to `skoda_mate/+/cmd/#`; Mate's own user needs to read that and to publish to `skoda_mate/#` and `homeassistant/#`),
  and use TLS whenever the broker is reachable from outside your own network.
- **The auxiliary heater cannot be started over MQTT**: starting it uses your S-PIN. Use Mate's **Control** page for that.
- Each press is one Škoda request, taken from the same budget as the Control page. Škoda allows about 20 requests per hour per
  car, so Mate accepts **at most one MQTT command per car every 30 seconds** and drops (and logs) the rest. Avoid automations
  that press buttons in a loop.
- **What became of a press**: the sensor **Last command** shows e.g. `start_charging: sent`. The possible results are:
  - `sent`: Škoda took the command.
  - `failed`: Škoda or the car refused it.
  - `rejected`: Mate did not send it, for example because the car does not support it, the value is out of range or the request budget is used up.
  - `dropped`: it came too soon after the previous command.

  The reason is in the sensor's `error` attribute. Mate publishes it retained on `<prefix>/<VIN>/cmd_result` as JSON
  `{"command", "status", "ok", "error", "at"}`. Failed and rejected commands also appear in Mate's command log and events.

If the car does not support a function (for example no ventilation), pressing its button reports `rejected` with the
reason. Mate shows what your car supports on the **Capabilities** page.

## Topics

`<prefix>` is the topic prefix (`skoda_mate`).

| Topic | Retained | Content |
|---|---|---|
| `<prefix>/status` | yes | `online` / `offline` |
| `<prefix>/<VIN>/state` | yes | all values as one JSON object (what Home Assistant reads) |
| `<prefix>/<VIN>/position` | yes | `latitude`, `longitude`, `address` |
| `<prefix>/<VIN>/fields/<key>` | yes | one value as a JSON scalar, e.g. `64`, `true`, `"HEATING"` |
| `<prefix>/<VIN>/events` | **no** | one JSON message per event |
| `<prefix>/<VIN>/cmd/<name>`, `<prefix>/<VIN>/cmd_result` | –, yes | commands, see *Controls* |

### One topic per value

For tools other than Home Assistant: `<prefix>/<VIN>/fields/<key>` has every key of the `state` object. A value is
published when it changes; `captured_at` (when the car last reported) on every reading; and all of them again after a
reconnect. A value that becomes **unknown** is sent as an **empty retained message**, which removes it from the broker.

**Also publish one topic per value** on the MQTT card switches these topics off (they are on by default). That does not
change Home Assistant discovery. Values the broker already holds stay there until you delete them.

### Events

`<prefix>/<VIN>/events` reports what happened, with the same [event names and data as the webhooks](WEBHOOKS.md#events):

```json
{"id": "5c1f…", "event": "charge.ended", "at": "2026-11-26T18:04:00+00:00",
 "vehicle": {"id": 1, "name": "Enyaq", "vin": "TMB…"}, "data": {"charge_id": 42, "energy_kwh": 36.4, "place": "Home"}}
```

Events are **not retained** (QoS 0) and are not queued while the broker is unreachable, so an automation never acts on
an old one. Use a [webhook](WEBHOOKS.md) when an event must not get lost. They are published whether or not the field
topics are on. `id` is unique per event.

```yaml
alias: Enyaq reached its charge limit
trigger:
  - platform: mqtt
    topic: skoda_mate/TMBJB9NY5RF999999/events
condition:
  - condition: template
    value_template: "{{ trigger.payload_json.event == 'charge.completed' }}"
action:
  - service: notify.notify
    data:
      message: "The Enyaq reached {{ trigger.payload_json.data.end_soc }} %."
```

## Examples

Entity names follow the car's name. For a car called *Enyaq* they look like `sensor.enyaq_battery`. Check the real names in
*Settings → Devices & services → Entities*.

**A dashboard card** (the `number` and `button` entities exist only with commands allowed)

```yaml
type: entities
title: Enyaq
entities:
  - sensor.enyaq_battery
  - sensor.enyaq_range
  - binary_sensor.enyaq_charging
  - sensor.enyaq_charging_power
  - number.enyaq_charge_limit
  - sensor.enyaq_last_trip_distance
  - sensor.enyaq_last_charge_cost
  - button.enyaq_start_charging
  - button.enyaq_stop_charging
```

**Notify when the car is charged**

```yaml
alias: Enyaq charged
trigger:
  - platform: numeric_state
    entity_id: sensor.enyaq_battery
    above: 79
condition:
  - condition: state
    entity_id: binary_sensor.enyaq_plug_connected
    state: "on"
action:
  - service: notify.notify
    data:
      message: "The Enyaq is at {{ states('sensor.enyaq_battery') }} %."
```

**Warn about an open window when you leave**

```yaml
alias: Enyaq window open
trigger:
  - platform: state
    entity_id: binary_sensor.enyaq_windows_open
    to: "on"
    for: "00:10:00"
action:
  - service: notify.notify
    data:
      message: "A window of the Enyaq is open."
```

## How it behaves

- **Updates** arrive whenever Mate reads the car (every 5 to 20 minutes, within Škoda's request limit). Values are *retained*, so Home Assistant shows the latest
  values right after a restart.
- **Availability**: if Mate stops or loses the broker, Home Assistant marks the entities *unavailable* by itself and restores them when Mate is back.
- **If the broker is down** when Mate starts, nothing breaks: Mate keeps retrying and announces everything again once the broker is back.
- **Several cars** (up to 5 per Mate installation) show up as separate devices.
- **Position** is only updated while the car is parked: the Škoda API gives no position while driving.

## Troubleshooting

| Symptom | What to check |
|---|---|
| *Cannot reach …* | IP and port; is the broker running; firewall; from a container use the LAN IP |
| *Refused the user name or password* | user and password; the user must exist in Home Assistant |
| Connected, but no device in Home Assistant | *Discovery* ticked in Mate **and** *Enable discovery* on in the MQTT integration, same prefix `homeassistant` |
| Entities are *unavailable* | Mate is stopped or cannot reach the broker (see the status in Mate's card) |
| Values never change | is Mate connected to Škoda? (an expired API key stops all readings, see the banner in Mate) |
| Old entities remain after you change the prefix | delete the old device in Home Assistant (*MQTT → Devices → Delete*) |

To watch the messages yourself (any computer with `mosquitto-clients`):

```
mosquitto_sub -h 192.168.1.10 -u skoda_mate -P '<password>' -t 'skoda_mate/#' -v
```

## Switching it off, security

- Untick **Enabled** and save: Mate publishes *offline*, closes the connection and stops sending. The device stays in Home Assistant until you delete it there.
- Use a dedicated MQTT user for Mate, and a long password. The position and charging data of your car pass through the broker; keep it inside your network or use TLS.
- Leave **Allow commands from Home Assistant** off unless you need it. When it is on, protect the command topics with broker ACLs (see *Controls*).
  Installs set up with environment variables never accept commands; tick the box in the dashboard if you want them.
- Environment variables (`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`, `MQTT_PREFIX`) still work for installs that already use them. As soon as you save settings in the dashboard they replace them.

## Trying it without Home Assistant

`scripts/minibroker.py` is a tiny MQTT broker for testing (user `mate`, password `secret`): `python scripts/minibroker.py 1883 18831`.
Point Mate at `127.0.0.1:1883` and watch what is published with the admin port: `echo DUMP | nc 127.0.0.1 18831`.
