# Activity and Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a day readable as driving, charging, climate, parked and unheard-from time; quantify what the car loses while parked; and make data gaps visible and repairable.

**Architecture:** One read-only `activity.py` builds non-overlapping intervals from snapshots, trips and charges; the timeline endpoint groups them into local days; parked loss reads parked runs of snapshots and reuses the existing tariff/place cost rules; `quality.py` reports checks and runs allowlisted repairs. Frontend work extends the existing Events page (renamed Activity) and Statistics/System pages with the existing `seg`, `card`, `table`, `modal` and `confirmDialog` helpers.

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest; vanilla ES modules, no build step; Node 26 browser checks.

**Spec:** `docs/superpowers/specs/2026-11-26-places-insight-automation-design.md` (§3.1, §4.2, §4.3, §4.7, §6 phase 2)

## Global Constraints

- No new calls to Škoda; every endpoint here is read-only SQL except the quality fixes, which touch only local tables. Tests never touch the network.
- Stored timestamps are UTC; browser input is a local date plus `tz_offset` (JS `getTimezoneOffset()`, minutes). Use `presenters.local_bound()` and never compare local dates to stored strings directly.
- Every visible string is `t('English')` with a German entry in `extendDE`; nav labels live in the `PAGES` table in `static/app.js`. `t()` takes one argument — compose dynamic text with existing format helpers, not placeholders (placeholder interpolation arrives in phase 5).
- The DOM is built with `h()`; no inline `<script>`; no new external hosts or CSP entries.
- Backend endpoints take `ContextDep` and use the same vehicle-ownership check as the neighbouring endpoints; shared shaping lives in `activity.py`/`quality.py`, not in the router.
- Run `uv run --extra dev pytest -q`, `uv run --extra dev ruff check` and `uv run --extra dev mypy` before every commit. Frontend tasks also run `node run.mjs` and `node i18n_coverage.mjs` from `scripts/dom-smoke`.
- Never commit `data/`; use scratch databases for tests and browser runs.

## Review Focus

- A SoC delta of zero: it must read as “below the detection floor”, not as no loss, and never as a decimal.
- A reading gap or an unrecorded charge inside a parked stand: it must split or exclude the session instead of inflating kWh/day.
- Day boundaries with a non-zero `tz_offset`: a drive or charge at 23:30 UTC must land on the right local day, and a range longer than 31 days must be refused.
- Quality fixes: they must touch only the rows named in the confirmation, never lose data (deduped trips stay restorable with Unmerge), and still work on a database with partially missing columns.
- Phone width (360 px): the 24-hour track scrolls sideways with a readable minimum width, and the summary/legend do not clip.

## File Structure

| File | Responsibility |
| --- | --- |
| `skoda_mate/activity.py` (new) | Interval builder, timeline grouping, parked-loss sessions and aggregates. No FastAPI imports. |
| `skoda_mate/quality.py` (new) | Check registry, samples and allowlisted repair actions. No FastAPI imports. |
| `skoda_mate/routers/reports.py` | Timeline and parked-loss endpoints. |
| `skoda_mate/routers/quality.py` (new) | Quality read and fix endpoints; registered in `web.py`. |
| `skoda_mate/recorder.py` | Existing `infer_charges` and charge repair reused; optional `vid` scope on `repair_charge_gaps`. |
| `skoda_mate/static/pages/events.js` | Activity page: Timeline/List toggle, week track, text list. |
| `skoda_mate/static/pages/stats.js` | Statistics tabs (Overview, Parked now; Charging/Driving later). |
| `skoda_mate/static/pages/overview.js` | Compact seven-day parked card. |
| `skoda_mate/static/pages/system.js` | Data-quality card and review panel. |
| `skoda_mate/static/style.css` | Track, session table and quality-card styles. |
| `scripts/dom-smoke/browser_e2e.mjs` | Timeline, Parked tab and quality-card browser checks. |
| `skoda_mate/demo.py` | A week of activity, a parked stand and a quality finding. |
| `tests/test_activity.py`, `tests/test_parked.py`, `tests/test_quality.py` (new) | Unit and endpoint coverage. |
| `docs/ACTIVITY.md` (new), `README.md`, `docs/DASHBOARD.md`, `docs/FEATURE-PARITY.md` | The phase's user-facing documentation. |

---

### Task 1: Activity intervals

**Files:** create `skoda_mate/activity.py`, `tests/test_activity.py`.

**Interface**

```python
KINDS = ("drive", "charge", "climate", "aux", "vent", "parked", "unknown")
CAP_DAYS = 31          # the timeline refuses a longer range
GAP_H = 6.0            # a reading gap longer than this is "unknown", not parked
def intervals(conn, vid: int, start_iso: str, end_iso: str) -> list[dict]: ...
```

Each interval is `{"kind", "start", "end", "minutes", "source", "trip_id", "charge_id", "place", "estimated"}`:

- `source` is `"trip"`, `"charge"`, `"reading"` or `"gap"`; `trip_id`/`charge_id` are set only for those kinds.
- `estimated` is `False` for trips and closed charges, `True` for reading-derived segments, open charges and gaps.
- `place` is the trip's `end_place`, the charge's matched place name (`places.match` at its coordinates), else `None`.
- Intervals are clipped to `[start_iso, end_iso)`, sorted, and adjacent intervals with the same kind, source and id are merged.

**Algorithm**

1. Read the last snapshot before `start_iso` and all snapshots with `recorded_at` in the range (id, time, soc, charging, in_motion, climate_state, aux_state, vent_state, lat, lon).
2. Turn consecutive readings into base segments classified by the earlier reading: `in_motion` truthy → drive, `charging` truthy → charge, then the first heating state wins — `climate_state` → climate, `aux_state` → aux, `vent_state` → vent — else parked. A segment longer than `GAP_H` is `unknown` instead (source `gap`). Before the first reading and after the last one in range, the range edge is the segment edge.
3. Overlay closed charges: query charges with `started_at < end_iso AND (ended_at IS NULL OR ended_at > start_iso)`, clip to range, remove every interval overlap, insert kind charge. An open charge (`ended_at IS NULL`) ends at the last reading in the range (or is dropped when none follows its start) and stays `estimated`. The same rule ends an open trip; both are `estimated` because the end is inferred.
4. Overlay trips the same way (drive wins over charge where a trip and a charge overlap).
5. Recompute minutes, drop empty intervals, merge adjacent ones as described, sort by start.

Define `heating_states()` in the module returning `{"COOLING", "HEATING", "HEATING_AUXILIARY", "PREHEATING", "VENTILATION"}` and test that an `OFF`/`IDLE`/`UNKNOWN` value is not climate.

**Steps**

- [ ] Write `tests/test_activity.py` with a helper that inserts a snapshot row (`recorded_at`, optional `soc`, `charging`, `in_motion`, `climate_state`, `lat`, `lon`).
- [ ] Failing tests: `test_parked_readings_become_one_parked_interval` (10:00, 10:20, 11:00 → 60 min parked, source reading, estimated), `test_trip_wins_over_reading_segments` (parked readings plus a 10:05–10:35 trip → one 30-min drive with `trip_id`, no parked inside), `test_charge_interval_uses_charge_row` (2-hour charge row plus charging readings → 120 min, `charge_id`), `test_climate_state_makes_a_climate_interval` (`HEATING` for one gap), `test_off_is_not_climate` (`OFF` → parked), `test_long_reading_gap_is_unknown` (10:00 → 18:00 → one 8-hour unknown, source gap), `test_trip_beats_overlapping_charge` (charge row and trip overlap → drive), `test_range_clipping_and_merge` (segments outside the window clipped; two adjacent parked segments merged).
- [ ] Run `uv run --extra dev pytest tests/test_activity.py -q`; confirm every test fails for the right reason.
- [ ] Implement `activity.py` until the tests pass.
- [ ] Run the full suite plus `ruff check` and `mypy`.
- [ ] Commit: `feat(activity): build non-overlapping activity intervals`.

---

### Task 2: Timeline endpoint

**Files:** modify `skoda_mate/activity.py` (add `timeline`), `skoda_mate/routers/reports.py`, `tests/test_activity.py`, `tests/test_web.py`.

**Interface**

```python
def timeline(conn, vid: int, from_day: str, to_day: str, tz_offset: int = 0, now: datetime | None = None,
             tariff: dict | None = None) -> dict: ...
```

`from_day`/`to_day` are local `YYYY-MM-DD`. The function converts them with `presenters.local_bound(day, tz_offset)` / `local_bound(next_day, tz_offset)`, clips the window end at `now`, calls `intervals()`, splits intervals at local midnights and returns:

```json
{"from": "2026-11-20", "to": "2026-11-26",
 "days": [{"date": "2026-11-20", "intervals": [ ... ],
           "summary": {"drive_min": 0, "charge_min": 0, "climate_min": 0, "parked_min": 0, "unknown_min": 0,
                       "km": 0.0, "kwh": 0.0, "cost": null, "cost_partial": false}}],
 "summary": { ...same shape, summed... }}
```

- Every day in the range appears, including empty ones (all buckets 0, `cost` null).
- `km` sums `trips.distance_km` for trips whose `started_at` falls in that local day; `kwh` sums charge energy for charges starting that day; `cost` sums `costs.charge_cost()` amounts, with the place from `places.match`; `cost_partial` is true when at least one included charge has an unknown amount.
- `summary` minutes are the sum of the day buckets; buckets are exclusive and partition the elapsed range. `climate_min` bundles the `climate`, `aux` and `vent` kinds.

**Route** in `routers/reports.py` after `events`:

```python
@router.get("/api/vehicles/{vid}/timeline")
def timeline_view(vid: int, ctx: ContextDep, from_: str | None = Query(None, alias="from"),
                  to: str | None = None, tz_offset: int = 0): ...
```

Default `to` = today in local time; default `from` = `to` − 6 days. Reject `from > to` with 400 `"The start must be before the end."` and a span longer than `CAP_DAYS` with 400 `"The range is limited to 31 days."`. Use the same `_vehicle_or_404`-style ownership helper as `events` in that file.

**Steps**

- [ ] Failing unit tests: `test_timeline_defaults_to_seven_days`, `test_timeline_rejects_more_than_31_days` (ValueError or 400 through the client), `test_timeline_splits_a_drive_at_local_midnight` (22:30–23:30 UTC on 1 Jan, `tz_offset=-60` → 30 min on each local day), `test_timeline_buckets_sum_to_elapsed_minutes`, `test_timeline_km_kwh_and_cost` (one trip and one priced charge on the day).
- [ ] Failing route tests in `tests/test_web.py` or `test_activity.py`: default window returns 7 days, 32-day request returns 400 with the exact message, another vehicle's id returns 404.
- [ ] Implement `timeline()` and the route; keep the arithmetic in `activity.py`.
- [ ] Full gates and commit: `feat(activity): add the local-day timeline endpoint`.

---

### Task 3: Activity page with Timeline and List

**Files:** modify `skoda_mate/static/pages/events.js`, `skoda_mate/static/app.js` (label), `skoda_mate/static/style.css`, `scripts/dom-smoke/browser_e2e.mjs`.

**What changes**

- `PAGES`: path `events` keeps its icon, label becomes `Activity` (German `Aktivität`). Route `#/events` and its deep links keep working; the page title and heading become Activity.
- `events.js` renders `seg([['timeline', t('Timeline')], ['list', t('List')]], mode, ...)`; Timeline is the default. The List tab is today's filtered event table, unchanged, including chips, search, dates and “Load more”.
- Timeline toolbar: previous week / `Today` / next week and a label with the range; a `24 h` legend (Driving, Charging, Climate, Parked, Not heard from); `aux` and `vent` intervals use the climate colour and legend entry.
- For each day: heading with the weekday and date, a track of 24 hours, intervals positioned by `left = minutes_of_day / 14.4` and `width = minutes / 14.4` percent (minimum 2 px via `min-width`), colours `--chart-1` drive, `--chart-2` charge, `--chart-4` climate, `--surface-3` parked with a hairline, `--muted` unknown; a summary line (driving time, charged kWh, parked time) and a `<details>` “Text list” with one `<li>` per interval using `format.duration`/`format.time`.
- Each interval is a `<button>` with `aria-label` = kind label + start + end (compose with template strings and `f.time()`; do not add a second translation mechanism) and `title` = the same. Clicking a drive opens `#/trips/<id>`, a charge `#/charges/<id>`, otherwise nothing (intervals carry a place name, not an id). Keyboard focus is visible via the existing `:focus-visible` rule.
- Track container is `overflow-x: auto`; the inner track has `min-width: 640px` so a phone scrolls instead of shrinking bars.
- Empty week: `empty(t('Nothing recorded in this week'), t('Mate records a day from the readings it has. A gap means it did not hear from the car.'))`.
- Fetch `GET /api/vehicles/{vid}/timeline?from&to&tz_offset=${new Date().getTimezoneOffset()}`; week navigation moves seven days; do not offer weeks beyond 31 days.
- All new labels get German entries; `i18n_coverage.mjs` must stay at 0 missing.

**Steps**

- [ ] Add the German entries and the label change; run `node i18n_coverage.mjs` (fails until the keys are used — that is the point).
- [ ] Implement the Timeline tab and keep List working; verify both with the demo server.
- [ ] Extend `browser_e2e.mjs`: open `#/events`, assert at least one `.track` bar exists in demo mode, toggle “Text list” and assert a list item, click List and assert the event table is still there; run at 360 px and assert `document.documentElement.scrollWidth <= innerWidth` for the page.
- [ ] Run `node run.mjs`, `node i18n_coverage.mjs`, the focused browser check, and the backend gates.
- [ ] Commit: `feat(activity): show the day as a timeline on the Activity page`.

---

### Task 4: Parked loss backend

**Files:** modify `skoda_mate/activity.py` (add `parked_loss`), `skoda_mate/routers/reports.py`; create `tests/test_parked.py`.

**Interface**

```python
def parked_loss(conn, vid: int, from_iso: str, to_iso: str, min_hours: float = 6.0,
                capacity_kwh: float | None = None, tariff: dict | None = None) -> dict: ...
```

Returns `{"sessions": [...], "aggregates": {...}, "min_hours": ..., "detection_floor_kwh": ...}`.

- Session: `{"start", "end", "hours", "place", "start_soc", "end_soc", "soc_delta", "kwh", "kwh_per_day", "cost", "cost_basis", "warning", "below_detection_floor"}`.
- Build runs from snapshots with `soc` not null, `in_motion` falsy and `charging` falsy, ordered by time. Extend a run while the next such reading is at most one hour later; a charging or moving reading, a missing SoC or a gap longer than one hour ends it. Ignore runs whose `[start, end]` intersects any drive or charge interval from `intervals()` (interior overlap, not mere touching).
- Keep only runs of at least `min_hours` with SoC at both ends. `soc_delta = start_soc - end_soc`; `kwh = round(soc_delta / 100 * capacity_kwh, 2)` when capacity is known, else `None`. `kwh_per_day = round(kwh / (hours / 24), 2)`.
- A delta below 0 or above 20 means a likely unrecorded charge: set `warning = 'likely an unrecorded charge'`, keep the row, exclude it from aggregates. A delta of exactly 0 sets `below_detection_floor = True` and `kwh = 0.0`.
- `detection_floor_kwh = round(capacity_kwh / 100, 2)` or `None`.
- Cost: build a synthetic charge `{"energy_kwh": kwh, "duration_min": hours * 60, "lat": lat, "lon": lon}` and call `costs.charge_cost(charge, tariff, places.match(conn, lat, lon))`; `cost_basis` is its `basis`; cost is `None` when no amount can be derived. Place name is the matched place's name, else `None`.
- Aggregates over valid sessions (no warning, `kwh` not None): `count`, `median_kwh_per_day`, `mean_kwh_per_day`, `kwh`, `kwh_7d`, `kwh_30d` (sessions ending within 7/30 days before `to_iso`), `cost` (sum of known amounts, `None` when none known).

**Route** `GET /api/vehicles/{vid}/parked-loss` with `from`, `to` (local dates, default last 30 days), `min_hours: float = 6` (must be 1–168, else 400 `"min_hours must be between 1 and 168."`) and `tz_offset`. Pass `recorder.battery_kwh(conn, vid)` and `ctx.tariff()`.

**Steps**

- [ ] Failing tests in `tests/test_parked.py`: `test_twelve_hour_stand_with_two_percent_drop` (60 kWh → 1.2 kWh, 2.4 kWh/day, one session), `test_zero_delta_is_below_the_detection_floor`, `test_positive_delta_is_an_unrecorded_charge` (delta −3 → warning, excluded from aggregates), `test_huge_delta_is_an_unrecorded_charge` (>20), `test_charging_reading_ends_the_session`, `test_gap_over_one_hour_splits_the_session`, `test_min_hours_filters_short_stands`, `test_home_tariff_and_place_price_choose_cost_basis`, `test_missing_capacity_keeps_kwh_null`, `test_route_rejects_bad_min_hours` (400) and `test_route_other_vehicle_404`.
- [ ] Implement `parked_loss` and the route.
- [ ] Full gates and commit: `feat(activity): quantify parked loss with sessions and aggregates`.

---

### Task 5: Statistics tabs and the Parked tab

**Files:** modify `skoda_mate/static/pages/stats.js`, `skoda_mate/static/style.css`, `scripts/dom-smoke/browser_e2e.mjs`.

**What changes**

- Add a tab control above the period control: `seg([['overview', t('Overview')], ['parked', t('Parked')]], tab, ...)`. Overview keeps today's page unchanged; Parked is new. (Charging and Driving tabs arrive in phase 3.)
- The period control (6 / 12 months / all) remains shared. For Parked, send `from` = period start date and `to` = today plus `tz_offset`.
- Parked tab: four `stat` cards (Median loss, Sessions, Energy, Cost; show `–` when unknown), a note with the detection floor copy from the spec, a `table` with Start, Place, Hours, SoC, kWh, kWh/day, Cost, and a warning `chip` on rows with `warning`; link the place name to `#/places/<id>` when present.
- Empty state: `empty(t('No parked sessions'), t('A session needs at least six hours, a charge level at both ends and no charging or driving in between.'))`.
- German entries for every new key; keep `i18n_coverage.mjs` at 0 missing.

**Steps**

- [ ] Refactor the page body into `renderOverview()` and `renderParked()` without changing Overview output; verify with the demo server that Overview looks identical.
- [ ] Implement the Parked tab against the task 4 endpoint, including warning rows, detection-floor copy and empty state.
- [ ] Extend `browser_e2e.mjs`: open `#/stats`, click `Parked`, assert the sessions table renders at 360 px and the page does not scroll horizontally.
- [ ] Run node checks and gates; commit: `feat(stats): add the Parked tab for parked loss`.

---

### Task 6: Overview parked card

**Files:** modify `skoda_mate/static/pages/overview.js`, `skoda_mate/static/style.css`, `scripts/dom-smoke/browser_e2e.mjs`.

**What changes**

- A compact card after “Last charge”: title `Parked, last 7 days`; fetch `/api/vehicles/{vid}/parked-loss?from=<today-6>&to=<today>&min_hours=6&tz_offset=...`.
- Body: median kWh/day as the main stat (or `–`), session count, energy; subtitle `One percent of the battery is about X kWh, so smaller losses are not measurable.` when the detection floor is known; a `button` “Details” linking to `#/stats` (Parked tab is reachable through the tab control; link to `#/stats` and let the user switch) and the warning count when present.
- No data: a quiet `empty`-style line “No parked stand long enough yet.” with the same six-hour rule.
- German entries; i18n coverage stays green.

**Steps**

- [ ] Add the card and fetch; keep the existing grid order stable.
- [ ] Browser check: the demo overview shows the card and no horizontal overflow at 360 px.
- [ ] Gates and commit: `feat(overview): show the seven-day parked loss`.

---

### Task 7: Data-quality checks

**Files:** create `skoda_mate/quality.py`, `skoda_mate/routers/quality.py`, `tests/test_quality.py`; modify `skoda_mate/web.py`.

**Interface**

```python
CHECKS = ("open_trips", "open_charges", "estimated_charges", "inferred_charges", "approx_trips",
          "reading_gaps", "odometer_jumps", "duplicate_trips", "api_errors", "stuck_operations", "missing_sections")
def checks(conn, vid: int, now_iso: str) -> list[dict]: ...
```

Each item: `{"id", "severity", "count", "summary", "samples": [{"label", "href"}], "fix": action_or_None}`. Severity is `"important"` for open trips/charges, reading gaps, odometer jumps, duplicate trips and stuck operations, `"info"` for the rest. Samples are at most five, each label a short English noun phrase plus an id/date (e.g. `Trip #12, 2 Nov`), `href` a hash route (`#/trips/12`, `#/charges/9`) or null.

Thresholds:

- `open_trips`: `ended_at IS NULL AND started_at < now − 24 h`.
- `open_charges`: `ended_at IS NULL AND started_at < now − 24 h`.
- `estimated_charges`: `end_estimated = 1` (last 30 days).
- `inferred_charges`: `source = 'inferred'` (last 30 days).
- `approx_trips`: `approx = 1` (last 30 days).
- `reading_gaps`: consecutive snapshots in the last 30 days more than 6 h apart (count = number of gaps).
- `odometer_jumps`: consecutive snapshots with `mileage_km` in the last 30 days where the value decreases or rises by more than 1000 km.
- `duplicate_trips`: groups sharing `started_at` and `round(distance_km, 1)` (last 30 days); one finding per group.
- `api_errors`: `api_calls.ok = 0` in the last 24 h.
- `stuck_operations`: status not terminal and `updated_at < now − 30 min`.
- `missing_sections`: `vehicle_state` lacks any of `info`, `charging`, `climate`, `position`; one sample per missing section, label `Section <name> missing`.

Counts are exact; `summary` is a short English sentence such as `”3 trips never ended”` (single form; no plural machinery).

Fix hints: `open_trips` → `close_open_trips`, `open_charges` → `close_open_charges`, `duplicate_trips` → `dedupe_trips`; every other check has none. `estimated_charges` deliberately has no hint: a guessed end is how most live charges close, and `repair_charges` only replays charges with reading gaps, so a Fix button there would change nothing. `repair_charges` and `infer_charges` stay callable on the fix endpoint.

**Route** `GET /api/vehicles/{vid}/quality` returns `{"checked_at": now_iso, "checks": [...]}`; register the router in `web.py` next to the existing ones. Use the shared ownership helper (404 for another car).

**Steps**

- [ ] Failing test fixture with: one open trip 30 h old, one open charge 30 h old, one estimated charge, one inferred charge, one approx trip, a 7-hour reading gap, an odometer decrease, two duplicate trips, an API error 2 h ago, a 40-minute-old stuck operation, and a vehicle_state missing `position`.
- [ ] Assert exactly the expected ids/counts/severities and that samples are capped at five and routed correctly; assert an empty database returns the full check list with zero counts.
- [ ] Route tests: 401 without a session, 404 for another vehicle, no writes (compare `conn.total_changes` before/after).
- [ ] Implement `quality.py` and the router; full gates; commit: `feat(quality): report derived-data problems`.

---

### Task 8: Data-quality fixes

**Files:** modify `skoda_mate/quality.py`, `skoda_mate/routers/quality.py`, `skoda_mate/recorder.py`, `tests/test_quality.py`.

**Interface**

```python
ACTIONS = ("close_open_trips", "close_open_charges", "repair_charges", "infer_charges", "dedupe_trips")
def fix(conn, vid: int, action: str, now_iso: str) -> dict: ...   # -> {"action", "changed", "message"}
```

- Ends follow the live recorder's rules (`recorder._trips`, `recorder._charge`): an unknown state never ends a row. `in_motion = 0` is a definite PARKED; a reading is definitely not charging only with a known `charge_state` or `plug_connected = 0` (the recorder stores `charging = 0` when the charging section is missing).
- `close_open_trips`: trips open longer than 24 h get `ended_at` = the first PARKED snapshot at or after `started_at`, else the last snapshot, else `started_at`; `duration_min` = whole minutes between start and end, `approx = 1`; only those rows.
- `close_open_charges`: charges open longer than 24 h get `ended_at` = the first definitely-not-charging snapshot at or after `started_at`, else the last CHARGING snapshot (what the recorder's stale close uses), else `started_at`; `duration_min` recomputed, `end_estimated = 1`; only those rows.
- `repair_charges`: extend `recorder.repair_charge_gaps(conn, vid=None)` with an optional vehicle scope and return the repaired count for the car; keep existing callers working.
- `infer_charges`: `recorder.infer_charges(conn, vid, days=30)`; return its count.
- `dedupe_trips`: fold each duplicate group into its lowest-id row, which keeps its own numbers. Do **not** use `merge.merge`: it sums distance and energy, which doubles a duplicated drive. Every original row goes into the kept row's `merged_json`, including the parts of an extra row that was merged itself, so `merge.unmerge` (Unmerge on the trip page) restores them and the importer does not re-import them. Notes are joined as a merge joins them. Return the number of groups folded; skip groups that no longer have at least two rows.
- The repair and its event commit together: one failure leaves every row as it was and logs nothing (`repair_charges` and `infer_charges` reuse recorder functions that commit on their own).
- Every action writes one `events` row `(vehicle_id, at, 'quality_fix', '<action>:<changed>')`. Unknown action → 400 `"Unknown action."`. No action loses data: only `dedupe_trips` removes rows, and only into `merged_json`; `infer_charges` replaces unedited inferred rows exactly as every poll already does.

**Route** `POST /api/vehicles/{vid}/quality/fix` with a pydantic body `{"action": str}`; return the `fix()` result.

**Steps**

- [ ] Failing tests: `test_close_open_trips_touches_only_old_open_rows`, `test_close_open_charges_uses_first_non_charging_reading`, `test_repair_charges_fills_energy_for_measured_rows_only` (and the optional `vid` scope keeps other cars untouched), `test_infer_charges_adds_an_inferred_row`, `test_dedupe_trips_merges_duplicates`, `test_each_fix_logs_one_event`, `test_unknown_action_is_400`, `test_fix_never_deletes_rows` (row counts before/after; dedupe removes exactly the extra rows and Unmerge brings them back).
- [ ] Implement the actions and the route; confirm the read endpoint's `fix` hints match `ACTIONS`.
- [ ] Full gates and commit: `feat(quality): repair open, estimated and duplicate rows safely`.

---

### Task 9: Data-quality card on System

**Files:** modify `skoda_mate/static/pages/system.js`, `skoda_mate/static/style.css`, `scripts/dom-smoke/browser_e2e.mjs`.

**What changes**

- A card at the top of the System page: `Data quality`; fetch `/quality` when the page loads.
- Header line: counts by severity with `chip` (`bad` for important, `warn` for info) and the check time; `button` “Check again”.
- Body: one row per check with a non-zero count (and a compact “Everything else looks consistent.” line), severity chip, summary and `Review` button. Zero-count checks are hidden behind a `<details>` “Show all checks”.
- Review opens a `modal`: the samples as links (or plain labels), the count, and — when `fix` is set — `button` “Fix” styled by `asyncButton`; fixing asks `confirmDialog(t('Apply this fix?'), t('This changes <n> rows. Nothing is lost.'), ...)` composed with the count (concatenate; no placeholder support yet) and then `POST /quality/fix` with `{action}`.
- After a fix: toast with `changed`, close the modal, refresh the card. A 400 shows the message in a `banner` inside the modal and does not refresh.
- German entries for every new key; `i18n_coverage.mjs` stays at 0 missing.

**Steps**

- [ ] Add the card and read path; verify the demo (task 10 seeds a finding) shows an important chip.
- [ ] Add the review modal, confirmation and fix flow; verify with the demo that the card refreshes and the count drops.
- [ ] Extend `browser_e2e.mjs`: open `#/system`, assert the quality card exists, open Review, close it; run at 360 px.
- [ ] Node checks and gates; commit: `feat(quality): surface data-quality checks on the System page`.

---

### Task 10: Demo data, docs and phase gate

**Files:** modify `skoda_mate/demo.py`, `tests/test_demo.py`, `README.md`, `docs/DASHBOARD.md`, `docs/FEATURE-PARITY.md`; create `docs/ACTIVITY.md`.

**What changes**

- Demo seed: make the last week contain at least one trip, one charge, one climate run and one 12-hour parked stand with a 2 % drop; leave one trip open for more than 24 h so the quality card has an important finding; keep the seed deterministic (`rng_seed`).
- `tests/test_demo.py`: the demo `/timeline` returns 7 days with at least one drive and one charge interval; `/parked-loss` returns at least one valid session with `kwh_per_day`; `/quality` includes `open_trips` with count ≥ 1.
- `docs/ACTIVITY.md`: what the timeline shows, the precedence rule, the poll-interval precision caveat, how parked loss is computed (capacity, detection floor, exclusions), and what the quality fixes do and never do (nothing is lost; folded duplicates can be split again with Unmerge).
- `README.md`: add the Activity/Parked-loss/quality rows to the feature table, linking `docs/ACTIVITY.md`; keep the existing tone and table order.
- `docs/FEATURE-PARITY.md`: mark the three capabilities as present with the same honest caveats.
- `docs/DASHBOARD.md`: the page table now lists Activity (route `#/events`) and the System quality card; the “Events” row becomes Activity with both tabs.

**Steps**

- [ ] Seed the demo data and make the three demo tests pass.
- [ ] Write the docs and keep the internal links valid.
- [ ] Run the complete gate set: pytest, ruff, mypy, `node run.mjs`, `node i18n_coverage.mjs`, and one browser pass against a scratch demo server (ports 8799, never 8766).
- [ ] Commit: `docs: describe activity, parked loss and data quality` (demo/test changes may be a separate commit `test(demo): seed activity, a parked stand and a quality finding`).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-27-activity-and-trust.md`.

Execute with `superpowers:subagent-driven-development`: one fresh implementer per task, a task-scoped review after each, a fix loop for Critical/Important findings, then one whole-branch review and a scoped re-review of the fix wave. Every role runs on the session's Flash model.
