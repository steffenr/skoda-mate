# Webhooks

Mate can send signed JSON to your own URL when something happens, for example to Home Assistant, Node-RED or n8n.
Nothing goes through a cloud service, and webhooks cost no Škoda requests.

Set them up under **Settings → Automation**: **Add webhook**, enter a name and a URL, choose the events, save. Mate
shows the **signing secret once**. Copy it then; later you can only create a new one. **Send test** sends a `test`
event at once (also for a disabled webhook), and **Deliveries** shows the last 20 with their result and a **Retry**.

The events leave Mate and go to the address you enter. They contain the car's name and **VIN** and the names of your
places, but no coordinates, addresses, keys or passwords. Addresses in your own network are allowed. Use `https://`
when the receiver is outside it. A URL with a user name or password in it is refused.

## Events

Mate learns about changes when it reads the car (about every 5 to 20 minutes), so an event arrives that much later
than the change, and something that starts and ends between two readings is not seen.

| Event | When | `data` |
|---|---|---|
| `trip.started` | a drive was seen | `trip_id`, `start_place`, `start_soc` |
| `trip.ended` | it ended | `trip_id`, `start_place`, `end_place`, `distance_km`, `energy_kwh`, `start_soc`, `end_soc`, `approx` |
| `charge.started` | Mate saw the car charging | `charge_id`, `charge_type`, `start_soc`, `target_soc`, `place` |
| `charge.ended` | that charge ended | the same, and `end_soc`, `energy_kwh`, `cost` |
| `charge.completed` | it ended **at or above the charge limit** (sent with `charge.ended`) | as `charge.ended` |
| `plug.connected`, `plug.disconnected` | the cable | – |
| `soc.low` | the charge level fell below your threshold (default 20 %), once per crossing | `soc`, `threshold` |
| `climate.started`, `climate.ended` | air conditioning, heating or ventilation | `state` |
| `doors.opened`, `windows.opened` | | – |
| `geofence.left`, `geofence.entered` | a drive ended somewhere other than the previous one ([places](PLACES.md)); driving through a place fires nothing | `place_id`, `place` |
| `poll.failed` | three readings in a row failed; sent once until one succeeds | `failures`, `kind`, `error` |

`start_place`, `end_place` and `place` are the names of your places, or `null`. Unknown values are `null`.

**Only what Mate watched is sent.** A charge Mate did not see, but worked out later from the battery level (marked
*inferred* in the app), sends no event. Neither do CSV imports or data repairs. `trip.ended` with `"approx": true` is a
drive found from the odometer, so there was no `trip.started` for it.

A rejected or expired API key stops the readings at the first refusal, so it does not produce `poll.failed`. Mate's
banner and the key-expiry date on the Settings page show it.

## The request

```http
POST /your/path HTTP/1.1
Content-Type: application/json
User-Agent: skoda-mate/0.2.0
X-Skoda-Mate-Event: charge.ended
X-Skoda-Mate-Delivery: 17
X-Skoda-Mate-Signature: sha256=3f0c…
```

```json
{
  "version": 1,
  "event": "charge.ended",
  "at": "2026-11-26T18:04:00+00:00",
  "vehicle": {"id": 1, "name": "Enyaq", "vin": "TMB…"},
  "data": {"charge_id": 42, "charge_type": "AC", "start_soc": 38, "target_soc": 80, "place": "Home",
           "end_soc": 80, "energy_kwh": 36.4, "cost": 10.92}
}
```

## Checking the signature

The signature is HMAC-SHA256 of the **exact bytes of the body**, with your secret as the key. Compare it before you
parse or reformat the body.

```python
import hashlib, hmac

def is_from_mate(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

The signature proves who sent a body, not when. If a repeated request would matter, remember the delivery ids you have
handled and ignore a second one.

## Delivery and retries

- Any **2xx** answer within **10 seconds** is success. Mate does not read the answer's body.
- Otherwise Mate tries again after **1 min, 5 min, 15 min, 1 h and 6 h**, then gives up (six attempts in all).
- A **4xx** answer stops at once, except `408` and `429`. **`410 Gone` also disables the webhook.**
- **Redirects are not followed** and count as a failure: enter the final URL.
- Delivery is **at least once**. A retry has the same `X-Skoda-Mate-Delivery`, so use it to recognise repeats.
- Waiting deliveries survive a restart. One limit: if Mate is killed in the instant between saving a reading and
  queuing its deliveries, that reading's webhooks are not sent.
- Disabling a webhook drops what was still waiting, so old events are not sent when you enable it again.
- Each webhook has its own queue: a receiver that hangs does not hold up the others.
- The delivery log is kept for **30 days**.

## Home Assistant example

An automation with a webhook trigger gets the JSON in `trigger.json`. (Home Assistant does not check the signature; its
webhook URL is the secret part there, so keep it inside your network or use HTTPS.)

```yaml
alias: Tell me when the car is charged
trigger:
  - platform: webhook
    webhook_id: skoda-mate
    allowed_methods: [POST]
    local_only: true
condition:
  - condition: template
    value_template: "{{ trigger.json.event == 'charge.completed' }}"
action:
  - service: notify.notify
    data:
      message: "{{ trigger.json.vehicle.name }} reached {{ trigger.json.data.end_soc }} %."
```

Use `http://<home-assistant>:8123/api/webhook/skoda-mate` as the URL. The same events are also published over
[MQTT](HOME-ASSISTANT.md#events).

## API

Every route needs a dashboard session or the API token. No answer contains a secret except the two that create one.

| Route | |
|---|---|
| `GET /api/webhooks` | the webhooks, the event names and the low-battery threshold |
| `POST /api/webhooks` | create `{name, url, events, enabled}`; answers with the `secret` |
| `PUT /api/webhooks/{id}`, `DELETE /api/webhooks/{id}` | change, delete |
| `POST /api/webhooks/{id}/secret` | a new secret |
| `POST /api/webhooks/{id}/test` | send a test now and answer with the result |
| `GET /api/webhooks/{id}/deliveries` | the last 20 |
| `POST /api/webhooks/deliveries/{id}/retry` | queue one again |
| `PUT /api/webhooks/options` | `{"soc_low_threshold": 5–50}` |
