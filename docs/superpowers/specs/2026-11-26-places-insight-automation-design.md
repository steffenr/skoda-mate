# Škoda Mate — places, insight and automation

**Status:** design for approval · **Date:** 2026-11-26 · **Scope:** eleven feature areas, seventeen languages, five phases

## 1. Intent

Škoda Mate already records trips, charges, events and the live state of the car. What is missing is the layer that turns
that record into everyday answers: where the car stands, what it cost there, what happened today, how much it loses while
parked, how it charges and drives, how healthy the battery looks, whether the data can be trusted, and how the whole thing
talks to a home automation system.

This program adds that layer. It stays inside the rules that make Mate trustworthy:

- **No new calls to Škoda.** Every figure is a local query over data Mate already stored. The request budget does not change.
- **No new service.** SQLite, the existing FastAPI app and the existing ES-module frontend. No external queue, no Postgres, no Grafana,
  no background worker outside the app process.
- **No build step.** New frontend code is plain modules loaded by the existing router; map plugins stay pinned CDN files with
  SRI, or the same files served locally.
- **Say what a number is.** Measured, derived from readings, and estimated values are labelled differently in the UI and in
  the API. Nothing is presented as car-reported when it is not.
- **One place for shared logic.** Place matching, activity segmentation and cost rules live in modules, not in routers or pages.
- **Every visible string is translatable.** New strings use the existing `t('English')` convention with literal keys; the
  language refactor generalises the storage without changing that authoring rule.
- **The existing visual language stays.** Cards, segmented controls, tables, charts, banners and the mobile breakpoints are
  reused. No new design system.

## 2. What the data can and cannot support

| Fact | Consequence for this program |
| --- | --- |
| The car is polled about every 5 minutes while active and every 20 minutes while idle. | Timeline and parked sessions are accurate to the poll interval, not to the minute. Every such view says so. |
| Position is reported only while parked. | No route, no speed trace, no live map while driving. Trip lines remain straight start/end lines. |
| State of charge is an integer percentage. | Parked loss smaller than one percent is not measurable; the UI shows a detection floor instead of inventing decimals. |
| No speed, outside temperature, tyre pressure, OTA history or per-door state. | These are non-goals, not future backlog items. |
| Addresses arrive only with a parked position, as a formatted string. | Places are built from coordinates and a user-given name. No city/country database is derived from address strings. |
| About 20 requests per hour per car. | All analytics are read-only SQL. A new page must never trigger a poll or a command. |
| Trips and charges are derived by Mate, sometimes from sparse readings. | Provenance is carried through: `source`, `approx`, `end_estimated`, `inferred`. |
| The API has no history. | “Tracked since” remains the honest start of every all-time figure. |
| Timestamps are stored in UTC; the browser sends `tz_offset`. | Day boundaries and “today” use `local_bound()` and the existing offset convention. |

## 3. Foundations

Three shared pieces are built before the feature pages: activity intervals, places, and event dispatch. They are the reason
the feature work does not duplicate SQL or invent a second definition of “parked”.

### 3.1 Activity intervals

A new `skoda_mate/activity.py` turns the existing rows into non-overlapping intervals for a time range. It is read-only and
has no FastAPI or SQLite-write dependency.

```
Interval = {kind, start, end, minutes, source, trip_id?, charge_id?, place?, estimated}
kind = drive | charge | climate | aux | vent | parked | unknown
```

Rules:

- **Drive** comes from `trips.started_at` to `ended_at` (an open trip ends at the last reading).
- **Charge** comes from `charges.started_at` to `ended_at` (an open charge ends at the last reading).
- **Climate, auxiliary heat and ventilation** come from the state transitions already recorded in `events`
  (`climate`, `aux_heating`, `ventilation`) and are closed by the next transition or the end of the range.
- **Parked** fills the gaps between the intervals above, using `in_motion = 0` readings as evidence. A parking session
  starts at the previous activity's end (or the first parked reading) and ends at the next activity's start (or now).
- **Unknown** replaces parked when there is no reading for more than six hours inside the gap. The car may have moved
  without being seen; the timeline hatches the interval instead of claiming it was parked.
- Consecutive parked intervals separated by a gap of at most two expected poll intervals are merged. Expected interval is
  5 minutes when the last reading was active, 20 minutes otherwise.
- A charge is a state inside a parked session. The timeline draws it over the parked background; totals count it once.
- Ranges are capped at 31 days per request. Longer views aggregate by day rather than returning every interval.
- Each interval carries `estimated = true` when either boundary was inferred from a gap rather than a reading.

Consumers: the timeline endpoint, parked-loss sessions, the data-quality gap check, and the MQTT/webhook event payloads.

### 3.2 Places and geofences

**Table `geofences`** (global, not per vehicle; the existing home position is global too):

```
id, name, kind (home|work|place), lat, lon, radius_m, color,
price_kwh, price_minute, session_fee, free, created_at, updated_at
```

- One row with `kind = 'home'`, enforced by a partial unique index. Radius 20–5000 m, default 150 m (the existing home radius already allows 20 m).
- `price_kwh`, `price_minute` and `session_fee` are optional; at least one price or `free = 1` is required for a priced place.
- `free = 1` means a deliberate zero, not “unknown”.
- Names are 1–60 characters; colours come from the existing chart palette.
- Geofences are global so a household with two cars shares “Home” and “Work”. Per-car places are not in this scope.

**Matching.** Haversine distance; a point matches when `distance <= radius_m`. Overlaps resolve to the smallest radius, then
the lowest id, so the result is deterministic. Home is not special in matching; it is a geofence with a kind.

**Assignment.** `trips.start_geofence_id`, `trips.end_geofence_id` and `charges.geofence_id` are added. They are filled on
insert and recomputed in one transaction when a geofence is created, edited or deleted. The response reports how many trips
and charges were re-assigned. Deleting a geofence clears the references; costs fall back to the tariff.

**Home migration.** On `migrate`, if no home geofence exists and the tariff has `home_lat`/`home_lon`, insert one with
`kind = 'home'`, the existing radius and no price. The Prices page then edits the home geofence. The old tariff coordinates
stay readable for one release so an existing database is never stranded; they are no longer used for matching.

**Cost precedence** (explicit user choices first):

1. `charges.cost_manual`.
2. A manual `charges.place_kind` (`home` or `public`): the user corrected the classification, so the tariff applies.
3. The matched geofence: `energy_kwh × price_kwh + minutes × price_minute + session_fee`, or `0` when `free`.
4. The home geofence's price, if the charge is at home and the geofence has no price.
5. The existing home/public AC/DC tariff.
6. Unknown place: the home tariff, flagged as an estimate.

Unknown energy with a per-kWh price produces an unknown cost, not a guess. A session fee is charged once per charge.

**Visits and place detail.** A visit is an arrival at the place (a trip ending inside it) until the next departure. Visits
separated by less than 30 minutes at the same place merge. Per place the API returns: visits, distinct days, parked minutes,
charged kWh, cost, last seen, and the trips and charges that make them up. Open visits end at now. This replaces the old
reading-count idea: a reading count measures parking time, not visits.

**Detected places.** The existing map grouping (`ROUND(lat,3)`, about 100 m) stays as a read-only suggestion list. “Name this
place” creates a geofence at the cluster centre and immediately assigns the trips and charges inside it.

**Performance.** Add `idx_snapshots_place` on `snapshots(vehicle_id, lat, lon) WHERE lat IS NOT NULL AND lon IS NOT NULL`, and
indexes on the new foreign keys. Place detail uses trips and charges for visits and only the bounding box of snapshots for
“last seen”, so it does not scan the whole history.

### 3.3 Event dispatch

`recorder.ingest()` returns the list of events of the reading it stored. Only what Mate watched is reported: inferred
charges, imports and repairs send nothing (decided 2026-11-27, when phase 4 was built; inferred charges never wrote events,
and sending them later could report old or since-removed charges). The poller dispatches the events after the data is
saved: MQTT publishes them and a pending delivery is stored for every subscribed webhook, so the deliveries table is the
queue. Nothing blocks the poll, and a slow consumer cannot fail an ingest. A crash between saving a reading and storing its
deliveries loses them; at-least-once delivery starts once a delivery is stored.

Event types: `trip.started`, `trip.ended`, `charge.started`, `charge.ended`, `charge.completed`, `plug.connected`,
`plug.disconnected`, `climate.started`, `climate.ended`, `doors.opened`, `windows.opened`, `soc.low`, `geofence.entered`,
`geofence.left`, `poll.failed`. `charge.completed` means the target was reached, not merely that charging stopped.
`soc.low` fires once per crossing below a configurable threshold (default 20 %). `poll.failed` fires after three consecutive
failures, not on every retry. `geofence.entered`/`left` are derived from consecutive trip ends, so a drive through a place
without stopping does not fire.

### 3.4 Map rendering

The map stays Leaflet 1.9.4 pinned from cdnjs with SRI. Add `leaflet.markercluster` 1.5.3 as a second pinned cdnjs file with
SRI for its JS and both CSS files. cdnjs is already allowed by the CSP for scripts, styles and images, so no new host is
needed; the CSP test is extended to keep it that way.

`mapView()` gains a `cluster` option (default on for the Map and Places pages):

- one `L.markerClusterGroup` for clustered markers, with `maxClusterRadius: 50`, `disableClusteringAtZoom: 14`,
  `spiderfyOnMaxZoom: true`, `showCoverageOnHover: false` and `chunkedLoading: true`;
- lines and circles stay in a separate `L.layerGroup` under the clusters;
- markers can opt out with `noCluster: true`; trip endpoints use it so a dashed start/end pair stays legible, and the
  draggable markers of the place editor always opt out;
- cluster icons use the app palette and show the count, with a title such as “12 places”;
- if the plugin fails to load, the map falls back to plain markers; it never goes blank.

The server cap rises from 300 to 1000 markers per layer (endpoint maximum 2000) because the DOM no longer holds one node per
marker. The “Show all” action asks for 2000 and is labelled with the count. Lifetime trip data is not sent as every point;
the map aggregates endpoints per place or 0.01° cell when “all time” is selected.

### 3.5 Translation-ready strings

All new visible text uses `t('English')` with a literal key. Dynamic values use `{placeholders}` passed to `t()`, never a
template literal as the key, so the extractor can see every string. New backend errors use the structured form described in
§4.11 from the start; older routers are migrated in the language phase.

## 4. Features

### 4.1 Places, place detail and map labels

**Outcome.** The car's world has names. A place can carry a radius, a colour and a price model; trips and charges are
assigned to it; the Map and the new Places page show it; a place page answers “how often, how long, how much”.

**Backend.** `GET /api/places` (geofences with counts plus detected clusters), `POST /api/places`, `PUT /api/places/{id}`,
`DELETE /api/places/{id}`, `GET /api/places/{id}` (detail). Validation returns structured errors. Re-assignment is
synchronous and transactional.

**UI.** A new `Places` page after Map in `PAGES`: list with search and kind filter; map with circles; “Add place” by clicking
the map, using the car's last position, or naming a detected cluster; edit panel with name, kind, radius, colour, prices and
free; delete with confirmation and a count of what will be unassigned. The Map page draws geofence circles and names and
links to the place; its place list shows visits, days and last seen when a geofence exists, and keeps the reading count for
only detected clusters. The Prices page's home card edits the home geofence instead of raw coordinates, and the existing
`/home-here` action moves the home place instead of writing raw tariff coordinates.

**Rules.** Radius and price validation as in §3.2. A place with `free` cannot also have prices. The home geofence cannot be
deleted, only moved. Editing a radius that would swallow another place is allowed; matching resolves overlaps.

**Done when.** A fresh database, a demo database and an existing database with home coordinates all show a working home
place; assigning, editing and deleting a place updates trip and charge costs; the Map shows the names; tests cover matching,
overlap, migration and re-assignment.

### 4.2 Activity timeline

**Outcome.** A day can be read at a glance: when the car drove, charged, was preconditioned, stood parked, or was not heard
from. The existing Events page becomes Activity with a Timeline/List toggle; the route `#/events` and its filters keep
working.

**Backend.** `GET /api/vehicles/{vid}/timeline?from&to&tz_offset` returns days with intervals and a summary. Range is capped
at 31 days; default is the current week. The endpoint uses `activity.py` and returns `estimated` flags.

**UI.** One row per day with a 24-hour track, colour by kind, a legend, and a summary above (driving, charging, parked,
climate, unknown, km, kWh, cost). Clicking an interval opens the trip or charge, or the place. A week selector and Today
shortcut; the List tab is the existing event table. On a phone the track scrolls horizontally rather than shrinking to
unreadable slivers. Keyboard focus reaches each interval, and a text list of the day is available to screen readers.

**Rules.** Precedence drive > charge > climate/aux/vent > parked > unknown when bars overlap; the tooltip lists the
underlying intervals. Summary buckets are exclusive (driving, charging, climate, parked, unknown) and sum to the range;
a charge inside parked therefore counts as charging, not as both. The precision note (“accurate to the poll
interval”) sits under the legend.

**Done when.** A week with a long drive, an AC charge, a preconditioning and a data gap renders correctly in all themes and
at 360 px; totals reconcile with the Trips and Charges pages; empty ranges show an honest empty state.

### 4.3 Parked loss

**Outcome.** “How much does the car lose standing still?” is answered with sessions, a median and a cost, not a single
scary number.

**Backend.** `GET /api/vehicles/{vid}/parked-loss?from&to&min_hours=6` returns sessions (place, start, end, hours, SoC
delta, kWh, kWh/day, cost) and aggregates (median, mean, 7/30-day totals, count, detection floor). kWh uses the configured
usable capacity; cost uses the place price, else the home tariff, and is labelled estimated.

**Rules.** Session must be at least `min_hours` (default 6), have a SoC reading at both ends, contain no charging or driving,
and have no data gap longer than one hour inside. A delta of zero is reported as “below the detection floor”, not as zero
loss. A negative delta or a delta above 20 % is flagged as a likely unrecorded charge: the session stays in the table with a
warning and is left out of the aggregates. Integer SoC means one percent is roughly 0.6 kWh on a 60 kWh pack; the UI states
this instead of showing two decimal places.

**UI.** A `Parked` tab in Statistics with the session table and aggregates, and a compact card on Overview for the last
seven days. Cost appears only when it can be derived; otherwise the card shows energy.

**Done when.** A 12-hour stand with a 2 % drop produces one session and a plausible kWh/day; a stand with an unrecorded
charge is excluded; the detection-floor copy is visible; no additional API call is made.

### 4.4 Charging insight

**Outcome.** The Charging tab answers where, when, how fast, how expensive and how reliable charging is.

**Backend.** `GET /api/vehicles/{vid}/insights/charging?from&to&tz_offset` returns totals (sessions, energy, cost, cost per
kWh, measured vs inferred share), AC/DC split, average and peak power (measured only), home/public/other split, session
fees, a weekday × hour heatmap, top places, and a charge curve binned by SoC in 5 % steps (average kW, sample count).

**Rules.** Inferred and imported charges count toward energy and cost but never toward power or the curve; the UI badges
them. A curve bin with fewer than three samples is hidden rather than drawn as a spike. Costs with unknown energy stay
unknown.

**UI.** Statistics gains tabs `Overview`, `Charging`, `Driving`, `Parked`; the period control stays shared. The Charging tab
uses the existing chart and table components. The heatmap is a CSS grid with a table fallback.

**Done when.** The tab reconciles with the monthly table; a period with only inferred charges shows energy and no curve;
AC and DC do not mix in the power average.

### 4.5 Driving insight

**Outcome.** The Driving tab shows where the car goes, when, how far, and what the trend is, without pretending to know
speed.

**Backend.** `GET /api/vehicles/{vid}/insights/driving?from&to&tz_offset` returns top destinations (geofence name, else end
place), weekday × hour heatmap, distance buckets, longest trips, average trip, consumption trend, and an annual-distance
projection.

**Rules.** Top destinations require a resolved place; unresolved endpoints group under “Unknown place”. The projection is
shown only after 60 tracked days and is labelled a projection. No max speed, no speed histogram, no elevation.

**UI.** Driving tab, same components as Charging. Top destinations link to the place; longest trips link to the trip.

**Done when.** A month with home/work commutes and one long trip produces sensible top destinations and buckets; the
projection is absent on a two-week-old database.

### 4.6 Battery health and projected range

**Outcome.** The Battery page answers “what range would 100 % give today, and is it drifting?” with an estimate that names
its assumptions.

**Backend.** Extend `GET /api/vehicles/{vid}/battery` with `projected_range`: points of `range_km / soc × 100` for readings
with SoC at least 20 %, a positive range and a result inside a broad plausible band (200–1000 km) and within median absolute
deviation of the recent median. It returns a daily median, the last value, a trend, and a degradation estimate comparing the
first and last 90-day windows when both have enough samples.

**Rules.** This is not state of health. Temperature, load and driving style are unknown, so the UI says “projected range
from reported range” and shows the sample count. Outliers are removed by median absolute deviation, not by cherry-picking.

**UI.** A card on Battery with the current projection, a small trend chart and the sample count; the existing capacity
estimate keeps its own card. No combined “health score”.

**Done when.** A year of readings produces a stable line; a week of readings shows a value but no degradation claim; the
copy never says “battery health” for the range projection.

### 4.7 Data-quality centre

**Outcome.** Derived data is only useful if its gaps are visible. The System page gets a card that lists what looks wrong
and offers safe repairs.

**Checks.** Open trips older than 24 h; open charges older than 24 h; charges with `end_estimated`; inferred charges;
approximate trips; reading gaps over 6 h in the last 30 days; odometer decreases or jumps over 1000 km; duplicate trips;
API errors in the last 24 h; operations stuck for over 30 min; missing or unsupported data sections.

**Backend.** `GET /api/vehicles/{vid}/quality` returns checks with severity, count, summary and up to five samples.
`POST /api/vehicles/{vid}/quality/fix` accepts an allowlisted action: `close_open_trips`, `close_open_charges`,
`repair_charges`, `infer_charges`, `dedupe_trips`. No delete action. Each fix returns what changed and is logged as an event.

**UI.** System card with counts by severity, a “Review” panel, and a confirmation for each fix that names the affected
rows. After a fix the card refreshes and the result is shown. Links go to the trip or charge for manual correction.

**Done when.** A fixture with an open trip, an estimated charge, a gap and an odometer jump shows all four; the safe fix
closes only the selected rows; no fix runs without confirmation.

### 4.8 MQTT field and event topics

**Outcome.** Consumers that do not want one large JSON blob can subscribe to one topic per value, and automations can react
to events instead of polling.

**Topics.** Existing `{prefix}/{vin}/state`, `position`, `cmd`, `cmd_result` and `{prefix}/status` stay unchanged. Add:

- `{prefix}/{vin}/fields/{key}` for every state key and the derived extras; retained; a JSON scalar; an empty retained
  payload clears a value that became unknown;
- `{prefix}/{vin}/events` for the event JSON; not retained, so a consumer never replays a stale event.

**Config.** A `publish_fields` toggle in the MQTT settings, default on. Discovery is unchanged; field topics are for
non-Home-Assistant consumers. Field publishing reuses the state payload, so it adds no query and no API call.

**Rules.** Do not publish a field on every poll if its value did not change, except the timestamp fields. Retain the last
known value. Event payloads include `event`, `at`, `vehicle` and `data`; `data` never contains secrets.

**Done when.** A broker shows one retained topic per value; a value that becomes unknown clears; one message per event
transition (QoS 0, with an id for dedupe); disabling the toggle stops field topics without touching discovery.

### 4.9 Home Assistant entities

**Outcome.** The entities that matter for dashboards and automations exist, with stable ids and honest units.

**New sensors.** `place` (current geofence name), `parked_loss_7d_kwh`, `parked_loss_7d_cost`, `capacity_estimate_kwh` (the
existing wall-energy estimate, named for what it is), `range_at_100_km`, `last_charge_place`, `quality_issues` (count). The
existing `last_charge_kwh` and `last_charge_cost` stay. New binary sensor `climate_on`. Device info gains
`serial_number: vin`.

**Rules.** Derived values come from the same functions as the dashboard, with a short per-vehicle cache so a state publish
does not scan the database on every poll. Unknown is `None`, not zero. Retired entity ids are cleaned up as today.

**Done when.** Discovery for one car lists the new entities with correct units and device classes; a demo car shows values;
the docs table matches the code.

### 4.10 Webhooks

**Outcome.** A user can send signed JSON to a URL when something happens, without a cloud service.

**Schema.** `webhooks(id, name, url, secret_enc, events, enabled, created_at, updated_at)` and
`webhook_deliveries(id, webhook_id, event, payload, status, attempts, next_at, last_code, last_error, created_at)`.
Secrets use `SecretBox`, like the other credentials. Deliveries are pruned after 30 days.

**Event selection.** The list from §3.3, grouped in the UI (Driving, Charging, Climate, Security, Places, System). A webhook
can subscribe to any subset.

**Payload.**

```json
{
  "version": 1,
  "event": "charge.ended",
  "at": "2026-11-26T18:04:00+00:00",
  "vehicle": {"id": 1, "name": "Enyaq", "vin": "..."},
  "data": {"charge_id": 42, "energy_kwh": 31.2, "cost": 9.36, "place": "Home"}
}
```

**Delivery.** `POST` with `Content-Type: application/json`, `User-Agent: skoda-mate/<version>`, `X-Skoda-Mate-Event`,
`X-Skoda-Mate-Delivery` and `X-Skoda-Mate-Signature: sha256=<hex>` over the exact body. Timeout 10 s. Success is 2xx.
Retries at 1 min, 5 min, 15 min, 1 h and 6 h (five attempts); 4xx stops except 408 and 429; 410 disables the webhook. Delivery
is at-least-once, so the delivery id is the dedupe key.

**UI.** Settings → Automation: list, add/edit (name, URL, events, enabled), “Send test”, rotate secret, last 20 deliveries
with status and a manual retry. The secret is shown once on creation and afterwards only “replace”.

**Rules.** Only `http` and `https` URLs. The URL is not secret; the signing secret is. Private/LAN addresses are allowed
(self-hosted receivers are the point), with a warning that the URL leaves the app. The worker starts with the app, resumes
pending deliveries after a restart, and never blocks polling.

**Done when.** A test delivery reaches a local receiver with a valid signature; a failing receiver retries and is visible;
a restart resumes a pending delivery; no secret appears in logs or API responses.

### 4.11 Languages

**Outcome.** The interface is available in Catalan, Danish, Dutch, English, Finnish, French, German, Hungarian, Italian,
Japanese, Korean, Norwegian Bokmål, Simplified Chinese, Spanish, Swedish, Turkish and Ukrainian (17 locales). English is
the source; German remains the reference translation.

**Current limit.** A single hard-coded German object, `t()` that knows only `en`/`de`, two settings buttons, a backend
that accepts only `en`/`de`, and a coverage test that checks only German. Adding a file is not enough.

**Architecture.**

- `static/i18n.js` becomes a loader: an explicit
  `CATALOGS` map of dynamic imports, `setLang(code, locale)` (async, loads one catalog), `t(key, vars)` with `{placeholder}`
  interpolation and English fallback, and `hasKey`. The list of languages and their native names comes from the backend, so
  there is one source of truth.
- Catalogs are plain modules under `static/i18n/<code>.js` exporting one object keyed by the English string. Only the
  selected catalog is fetched; English needs no fetch.
- Pages stop calling `extendDE`; their strings live in the catalogs. `de_backend.js` is folded into the catalogs.
- `app.js` awaits `setLang` before the first page render and sets `document.documentElement.lang` to the BCP-47 locale.
- `format.js` receives the BCP-47 locale (`zh-Hans`, `nb`), not the internal code; `Intl` then formats numbers, dates and
  currency correctly. Units stay independent of language.
- The hard-coded `lang === 'de'` branches in `format.js` (`Heute`, `Gestern`, `gerade eben`) become catalog entries through
  `t()`; `tEnum()` stops composing `enum:` keys in a German-only branch. A literal `ENUM_LABELS` map maps each raw API value
  to an English label, and the catalogs translate those labels, so the extractor sees them;
  `dictionary()` and `hasDE` give way to `hasKey`.
- Backend user-facing errors become `{message, params}` objects: the message is an English template with `{placeholders}`,
  the frontend calls `t(message, params)`. Static messages migrate first; dynamic ones get templates. The API keeps a plain
  string fallback for older clients.
- `skoda_mate/languages.py` is the backend source of truth for the accepted codes, native names and BCP-47 locales; `GET /api/settings`
  returns them, and the Settings picker renders that list. Setup and login stay English by design.

**Extraction and coverage.** `scripts/dom-smoke/i18n_extract.mjs` scans literal `t('…')` keys, `PAGES` labels and
`ENUM_LABELS`. A small Python companion, `scripts/i18n_backend.py`, extracts the user-facing templates from
`skoda_mate/messages.py`. Both write the same `static/i18n/keys.json`, and CI fails if it is stale. `i18n_coverage.mjs`
checks every catalog against that key list, including placeholder parity and extra keys, and reports per language. CI gates
English completeness and the reference German catalog; other catalogs are gated for key parity once their phase lands.

**Translation workflow.** A language appears in the picker when its catalog is complete. Catalogs are complete for all 17
locales in the release that ships them. They are community-maintainable: a language is one file, a PR can update it, and
the docs explain how to run the extractor and coverage check.
Native-speaker review is welcome and tracked in the docs; no machine-only catalog is presented as reviewed. The UI does not
badge languages, to avoid turning the picker into a warning list.

**Layout.** Long German, Finnish and Hungarian compounds wrap rather than clip; the CJK font stack is extended with system
fonts (`Noto Sans CJK`, `Hiragino Sans`, `Malgun Gothic`) and no external font is loaded. All 17 locales are left-to-right,
so no RTL work. Browser tests render a long-string locale at 360 px.

**Batches.** Framework and en/de migration first; then da/nl/sv/nb/fi; fr/es/it/ca; hu/tr/uk; ja/ko/zh_Hans. Each batch
runs the extractor, coverage, a browser pass and a native review where available.

**Added 2026-11-27, after reading the code again.** Approaches for the migration: (A) rebuild sentences that are pieced
together from several translations while migrating, so every later catalog is written against final keys; (B) migrate
them as they are and repair them later, which makes the first PR smaller but needs a second translation of the changed
text. **A was chosen.** It also settles three gaps in the text above:

- One English key can need two translations (`Range`: `Reichweite` or `Zeitraum`; `Open`: `Offen` or `Öffnen`). Today
  the last registration wins. A key may carry a context suffix, `'Open##action'`; English shows the part before `##`.
- Many strings reach `t()` through a variable. They are marked where they are written with `N_('…')`, which returns its
  argument, and the extractor scans `N_` as well as `t`. A catalog key that the extractor does not find fails coverage,
  so a missed marker cannot go unnoticed.
- The string fallback: an error keeps its formatted English string where it is today (`detail`, `error`, `message`) and
  gains a sibling `<field>_i18n: {message, params}`.

After checking W3C, CLDR and MDN guidance the same day, these replace the text above where they differ:

- Catalogs are JSON files (`static/i18n/<code>.json`), fetched on demand, instead of modules: a contributed translation
  is then data that cannot run code, and translation tools can read it.
- Counts use plural forms chosen with the built-in `Intl.PluralRules`; a catalog entry holds every category its
  language has, and coverage checks that.
- The key list records where each text is used, and a pseudo-language browser pass looks for missed or pieced-together
  text and for layouts that break with longer text.

**Done when.** All 17 locales appear in Settings with native names; switching updates the whole UI, `Intl` formats and the
`lang` attribute without a reload; every catalog has every key and matching placeholders; Japanese and Simplified Chinese
render without missing glyphs; a long German string does not break a 360 px layout.

## 5. Architecture and files

| Area | Change |
| --- | --- |
| Schema | `geofences`, `webhooks`, `webhook_deliveries`; `trips.start_geofence_id`, `trips.end_geofence_id`, `charges.geofence_id`; `idx_snapshots_place`; additive migration and home seed. |
| Modules | `activity.py`, `places.py`, `quality.py`, `webhooks.py`, `analytics.py`, `languages.py`; `recorder.py` returns events and assigns places; `poller.py` dispatches; `cloud.py` starts the webhook worker. |
| Routers | `routers/places.py`, `routers/quality.py`, `routers/webhooks.py`; timeline, parked loss and insights in `routers/reports.py`; settings returns languages. |
| Presenters | Place, timeline, quality and webhook shaping in `presenters.py`; routers stay thin. |
| Pages | New `places.js`; `events.js` gains Timeline/List; `stats.js` gains tabs; `battery.js`, `system.js`, `settings.js`, `prices.js`, `map.js` updated. |
| Map | `lib/mapview.js` gains clustering; SRI constants for the plugin; no new host. |
| i18n | `static/i18n.js`, `static/i18n/*.js`, extractor and coverage scripts; `de_backend.js` removed after migration. |
| MQTT | `ha_mqtt.py` topics/fields/events, sensors and extras; `cloud.py` extras cache and dispatch. |
| Docs | README, `docs/HOME-ASSISTANT.md`, `docs/FEATURE-PARITY.md`; new `docs/PLACES.md` and `docs/WEBHOOKS.md`. |
| Tests | `test_places.py`, `test_activity.py`, `test_quality.py`, `test_webhooks.py`, `test_analytics.py`, `test_i18n.py`; additions to MQTT, schema, stats, web and importer tests. |

All new endpoints take `ContextDep` and the existing session/bearer authorisation. No endpoint writes to the Škoda API.

## 6. Phases

| Phase | Features | Outcome | Depends on |
| --- | --- | --- | --- |
| **1. Places and map** | Places, place detail, map labels, clustering | A named world with correct costs; the map stays fast with many markers. | Nothing. |
| **2. Activity and trust** | Timeline, parked loss, data quality | A day can be read; parked loss is quantified; gaps are visible and repairable. | Activity intervals; places for names and prices. |
| **3. Insight** | Charging, driving, battery range | The existing Statistics and Battery pages answer the trend questions. | Places for destinations; activity for sessions. |
| **4. Automation** | MQTT fields/events, HA entities, webhooks | The data leaves the app in a stable, signed form. | Place and activity values; event dispatch. |
| **5. Languages** | 17 locales | Every feature above is readable in the selected language. | All feature strings final. |

Each phase is a shippable slice with its own migration, tests, docs and demo data. Phase 5 is last on purpose: the earlier
phases add several hundred strings, and translating them before they settle would mean doing it twice.

## 7. Quality gates

- `uv run --extra dev pytest -q`, `ruff check`, `mypy`; no new warnings.
- `scripts/dom-smoke`: `browser_e2e.mjs` (phone fit and click-through), `i18n_coverage.mjs`, `a11y_axe.mjs`,
  `a11y_contrast.mjs`; the map cluster path is a browser check, not a jsdom check.
- New tests: matching and overlap; cost precedence; home migration; visit counting; interval precedence and gaps; parked
  loss exclusion; quality fixes; webhook signature, retry and restart; MQTT field retain/clear and event non-retain;
  translation key and placeholder parity; every new endpoint's authorisation.
- No backend test touches the network; `FakeApi` and fixtures stay the rule (browser tests still load the pinned map CDN).
  No analytics endpoint may call the poller or budget.
- Demo mode seeds named places, a week of activity, a parked session, a data-quality finding and a disabled webhook so the
  features are visible without a real account.
- Docs are updated in the same phase: README (webhooks, languages), Home Assistant entities and topics, feature table, and
  the two new pages.

## 8. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Integer SoC makes parked loss noisy. | Minimum session length, detection floor, median, no decimal pretence. |
| A 20-minute idle poll can split one visit. | Merge gaps up to two expected intervals; show `estimated`. |
| Re-assigning places on a large history is slow. | Bounding-box queries, indexes, one transaction, counts in the response; cap the synchronous work and report partial progress if needed. |
| Map payload grows with clustering. | Cap at 1000/2000, cluster in the browser, aggregate “all time” server-side. |
| 15 new catalogs are a large content task. | Batches by language family, extractor + coverage gate, review where available. |
| Home migration surprises existing users. | Seed from tariff, keep old keys readable, test an old database, never delete the home place. |
| Webhooks retry into a dead endpoint. | Bounded attempts, visible delivery log, 410 disables, manual retry. |
| Structured backend errors break older clients. | Keep a string `detail` fallback for one release; frontend accepts both. |
| MQTT field traffic. | Publish only changed values, one retained topic per field, toggle. |

## 9. Decisions to confirm

1. **Activity page.** Rename the Events page to Activity and keep the `#/events` route, with Timeline as the default tab.
2. **Statistics tabs.** `Overview`, `Charging`, `Driving`, `Parked`; Battery stays its own page.
3. **Home as a geofence.** One global home place, seeded from the current tariff; the Prices page edits it.
4. **Languages.** All 17 selectable in the first language release, catalogs complete, native review tracked in docs.
5. **Webhook event names.** The list in §3.3, versioned payload, HMAC signature.
6. **Data-quality fixes.** Close, repair, infer and dedupe only; no deletes from the quality card.

## 10. Out of scope

Route or speed traces, max speed, elevation, outside/inside temperature, tyre pressure, OTA history, per-door/window state,
online/asleep states, a city/country database, a charging-station directory, scheduled departure, a read-only Prometheus
endpoint, a live charge card, GPX export, and any external analytics stack. These are not deferred features; the data or the
product constraints do not support them.
