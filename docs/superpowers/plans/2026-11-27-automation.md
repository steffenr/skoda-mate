# Automation (Phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MQTT field and event topics, new Home Assistant entities, and signed webhooks.

**Architecture:** `recorder.ingest()` returns the events of one reading. The poller hands them to `Cloud.dispatch` after
the data is saved; that publishes them on MQTT and stores one pending delivery per matching webhook. A worker owned by the
app's lifespan sends the pending rows, so they survive restarts.

**Tech Stack:** Python 3.15, FastAPI, SQLite, paho-mqtt, httpx, vanilla ES modules, pytest, puppeteer-core.

**Spec:** `docs/superpowers/specs/2026-11-26-places-insight-automation-design.md` §3.3, §4.8, §4.9, §4.10, §7

## Global Constraints

- No new calls to Škoda: nothing here calls `SkodaApi` or spends the budget.
- Events: `trip.started`, `trip.ended`, `charge.started`, `charge.ended`, `charge.completed`, `plug.connected`,
  `plug.disconnected`, `climate.started`, `climate.ended`, `doors.opened`, `windows.opened`, `soc.low`,
  `geofence.entered`, `geofence.left`, `poll.failed`.
- `charge.completed` = the target was reached. `soc.low` fires once per crossing below the threshold (default 20 %).
  `poll.failed` fires at the third consecutive failure. Geofence events come from consecutive trip ends.
- Topics `{prefix}/{vin}/fields/{key}` (retained, JSON scalar, empty retained payload clears) and `{prefix}/{vin}/events`
  (not retained, QoS 0, with `id`). Existing topics stay unchanged. `publish_fields` defaults to on.
- New sensors `place`, `parked_loss_7d_kwh`, `parked_loss_7d_cost`, `capacity_estimate_kwh`, `range_at_100_km`,
  `last_charge_place`, `quality_issues`; binary sensor `climate_on`; device `serial_number: vin`. Unknown is `None`.
- Webhooks: `POST`, `Content-Type: application/json`, `User-Agent: skoda-mate/<version>`, `X-Skoda-Mate-Event`,
  `X-Skoda-Mate-Delivery`, `X-Skoda-Mate-Signature: sha256=<hex>` over the exact body. Timeout 10 s. 2xx succeeds.
  Retries after 1 min, 5 min, 15 min, 1 h, 6 h; 4xx stops except 408 and 429; 410 disables the webhook.
- Secrets use `SecretBox`, are shown once, and never appear in logs, errors or other API responses. Deliveries are
  pruned after 30 days.
- Every visible string is `t('English')` with a German entry; DOM via `h()`; CSP unchanged.

## Decisions the spec leaves open

- **Only watched charges** (decided by the owner): inferred charges send nothing. This replaces "including events from
  inferred charges and repairs" in §3.3. Imports and repairs send nothing either: only live polls dispatch.
- **No separate in-process queue:** both subscribers return at once (paho queues itself; webhooks insert a row), so the
  deliveries table is the queue. A crash between saving a reading and queuing its delivery loses that webhook.
- **Retries:** "five attempts" is read as five retries after the first send.
- **Redirects** are not followed (a 3xx is retried), so a signed body never goes to a URL the user did not enter.
- **Disabling** a webhook (by hand or by 410) fails its pending deliveries, so old events are not sent on re-enable.
- **Send test** sends once at once, also for a disabled webhook, and is never retried.
- **No coordinates or addresses** in event data; places are named only by their geofence.
- **`quality_issues`** = visible quality checks with at least one open finding.
- **Extras cache:** the four expensive values (parked loss, capacity, range, quality) are kept 15 minutes and dropped
  as soon as the car has a new event.
- **Settings:** the `soc.low` threshold (5–50 %) lives on the Automation card.
- Turning `publish_fields` off stops publishing; values already retained on the broker stay there.

## Review Focus

- A receiver that hangs must not delay another webhook's delivery or polling.
- A webhook secret that cannot be decrypted (lost `secret.key`): the delivery fails visibly, nothing is sent unsigned.
- The first reading of a car, and fields missing from one poll: no events for "unknown → value".
- A boolean read back from the database (0/1) must publish the same field payload as the live one (`true`/`false`).
- Restart with a pending delivery whose webhook was deleted or disabled: nothing is sent.

## File Structure

| File | Responsibility |
|---|---|
| `skoda_mate/automation.py` (new) | `EVENT_GROUPS`, `EVENT_TYPES`, `collect()`: one reading's events and their data; threshold setting |
| `skoda_mate/webhooks.py` (new) | Webhook rows, validation, signing, enqueue, `Worker` |
| `skoda_mate/ha_values.py` (new) | Values Mate derives for MQTT, with the cache (moves `Cloud._extras` out of `cloud.py`) |
| `skoda_mate/routers/webhooks.py` (new) | `/api/webhooks…` |
| `skoda_mate/recorder.py`, `poller.py`, `cloud.py`, `web.py` | Return, dispatch, wire, worker lifecycle |
| `skoda_mate/ha_mqtt.py`, `mqtt_config.py` | Field and event topics, entities, `publish_fields` |
| `skoda_mate/schema.py` | `webhooks`, `webhook_deliveries` |
| `skoda_mate/static/lib/automation.js` (new) | Settings → Automation card |
| Tests | `tests/test_automation.py`, `tests/test_webhooks.py`, additions to `tests/test_mqtt.py` |

---

### Task 1: Event collection and dispatch

**Files:** Create `skoda_mate/automation.py`, `tests/test_automation.py`; modify `recorder.py`, `poller.py`.

**Interfaces — Produces:**
- `recorder.ingest(conn, vid, snap) -> list[dict]`, each `{"event": str, "at": str, "data": dict}`
- `automation.collect(conn, vid, since_event_id: int, prev, snap, snap_id: int) -> list[dict]`
- `automation.soc_low_threshold(conn) -> int`, `automation.SOC_LOW_KEY = "soc_low_pct"`
- `automation.envelope(conn, vid, event: dict) -> {"id", "event", "at", "vehicle": {"id","name","vin"}, "data"}`
- `Poller(..., on_events: Callable[[int, list[dict]], None] | None)` attribute `on_events`

- [ ] Write tests: watched charge gives `charge.started` then `charge.ended` with `charge_id, energy_kwh, cost, place`;
  `charge.completed` only when `end_soc >= target_soc`; an inferred charge gives nothing; first reading gives nothing;
  `soc.low` once on 21→19→18, again after 25→19, honours the stored threshold; trip start/end data; geofence
  left/entered across two trips and none when both end in the same place; climate started/ended from state changes;
  plug, doors, windows; command and quality events are ignored; `poll.failed` exactly at the third consecutive failure
  and again only after a success; a raising `on_events` does not fail the poll.
- [ ] Run `uv run --extra dev pytest -q tests/test_automation.py`: fails.
- [ ] Implement. `ingest` notes `MAX(events.id)` first and calls `collect` after `commit`.
- [ ] Run the whole suite, ruff, mypy: pass. Commit `feat(automation): return and dispatch the events of each reading`.

### Task 2: MQTT field and event topics

**Files:** modify `ha_mqtt.py`, `mqtt_config.py`, `cloud.py`; test `tests/test_mqtt.py`.

**Interfaces — Produces:** `ha_mqtt.state_values(snap, extras) -> dict`; `Publisher(..., publish_fields=True)`;
`Publisher.publish_events(vin, envelopes)`; `Cloud.dispatch(vid, events)`; `topics()` gains `fields`, `events`.

- [ ] Tests: one retained topic per state key; unchanged values are not republished but `captured_at` is; a value that
  becomes unknown publishes `""` retained; 0/1 from the database equals `true`/`false`; reconnect republishes all;
  toggle off publishes no field topic and the same discovery; events are not retained, QoS 0, one per transition;
  `publish_fields` is stored, defaults to true.
- [ ] Fail, implement, pass. Add the checkbox to the MQTT card with German text. Commit
  `feat(mqtt): publish one topic per value and an event topic`.

### Task 3: Home Assistant entities

**Files:** create `ha_values.py`; modify `ha_mqtt.py`, `cloud.py`, settings guide text; test `tests/test_mqtt.py`.

**Interfaces — Produces:** `ha_values.Values(conn, clock=time.monotonic).for_vin(vin) -> dict` with the keys of
`ha_mqtt.EXTRAS` plus `place`.

- [ ] Tests: discovery lists the seven sensors and `climate_on` with units/device classes, device has
  `serial_number`; `place` is the geofence of the parked position and `None` while driving; `climate_on` follows
  `activity.heating_states()` and is `None` when unknown; unknown derived values are `None`; the expensive values are
  computed once within 15 minutes and again after a new event; a demo car has non-null values.
- [ ] Fail, implement, pass. Commit `feat(mqtt): add place, parked loss, range, capacity and quality entities`.

### Task 4: Webhook store, signing and delivery

**Files:** create `webhooks.py`, `tests/test_webhooks.py`; modify `schema.py`, `cloud.py`, `web.py`.

**Interfaces — Produces:** `webhooks.create(conn, box, data) -> (dict, secret)`, `update(conn, id, data)`,
`delete`, `rotate(conn, box, id) -> str`, `listing(conn, box)`, `deliveries(conn, id, limit=20)`,
`retry(conn, delivery_id)`, `enqueue(conn, envelopes, now: float) -> int`, `sign(secret, body: bytes) -> str`,
`WebhookError`, `Worker(conn, box, transport=None, clock=time.time)` with `async run_once()`, `async send_test(id)`,
`start()`, `async stop()`, `wake()`.

- [ ] Tests: validation (name 1–60, http/https with host, known events, at least one); secret encrypted at rest and
  absent from listings; delivery to a local HTTP server carries the headers and a signature that verifies over the
  received bytes; retry schedule then `failed`; 400 stops, 408/429/500/3xx retry; 410 disables; pending delivery is
  sent by a new Worker on the same database file; a hanging receiver does not delay another; unreadable secret sends
  nothing; pruning after 30 days; only subscribed, enabled hooks get a row.
- [ ] Fail, implement, pass. Commit `feat(webhooks): store, sign and deliver webhooks with retries`.

### Task 5: Webhook API

**Files:** create `routers/webhooks.py`; modify `web.py`; test `tests/test_webhooks.py`.

Routes: `GET/POST /api/webhooks`, `PUT/DELETE /api/webhooks/{id}`, `POST /api/webhooks/{id}/secret|test`,
`GET /api/webhooks/{id}/deliveries`, `POST /api/webhooks/deliveries/{did}/retry`, `PUT /api/webhooks/options`.

- [ ] Tests: every route answers 401 without a session; create returns the secret once; 400 with a plain message,
  404 for unknown ids; threshold range 5–50.
- [ ] Fail, implement, pass. Commit `feat(webhooks): add the webhook API`.

### Task 6: Automation card, demo data, docs

**Files:** create `static/lib/automation.js`, `docs/WEBHOOKS.md`; modify `pages/settings.js`, `de_backend.js`,
`demo.py`/`web.py`, `scripts/dom-smoke/browser_e2e.mjs`, `README.md`, `docs/HOME-ASSISTANT.md`,
`docs/FEATURE-PARITY.md`, `docs/DASHBOARD.md`, the spec (§3.3).

- [ ] Demo seeds one disabled webhook (test first).
- [ ] Card: list; add/edit (name, URL, events grouped, enabled); private-network warning; secret shown once;
  send test; new secret; last 20 deliveries with retry; delete with confirmation; threshold.
- [ ] Browser check: add, secret shown once, deliveries, fits 360 px. Run `i18n_coverage.mjs`, `unit.mjs`,
  `browser_e2e.mjs`, both a11y scripts.
- [ ] Docs. Commit `feat(webhooks): add the Automation card` and `docs: describe automation`.
