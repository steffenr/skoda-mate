# Named Places and Map Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add named geofences (home, work, other places) with per-place prices and visit history, and make the existing map usable with thousands of points through clustering.

**Architecture:** Geofences are rows in the local SQLite database. A small `places.py` module owns matching, assignment and summaries; trips and charges store the matched `geofence_id` so filters, costs and the map need no spatial query per row. Costs gain one precedence step for a place price. The frontend adds a Places list and detail page, draws geofence circles on the existing map, and loads the clustering plugin only when the map is opened.

**Tech Stack:** Python 3.15, FastAPI, Pydantic, SQLite, vanilla ES modules, Leaflet 1.9.4 and leaflet.markercluster 1.5.3 from cdnjs with SRI.

**Spec:** `docs/superpowers/specs/2026-11-26-places-insight-automation-design.md`

## Scope

This is Plan 1 of the five phases in the design. It implements Phase 1 (named places, per-place prices, map clustering, home migration) and produces working, testable software on its own. Phases 2 to 5 get their own plans after this one is reviewed and shipped.

## Global Constraints

- Every new figure comes from the local database. No feature in this plan may add a request to the Škoda API; the poll budget stays unchanged.
- Schema changes are additive. Never drop a table, column or index; `migrate()` must upgrade an existing database in place and stay idempotent.
- One home geofence at most. The home place cannot be deleted; it can be renamed, moved and resized.
- A point inside overlapping geofences belongs to the smallest radius; ties go to the lower id.
- Cost precedence is: manual cost, manual place kind, place price, home/public tariff, unknown. A missing energy or duration value is unknown, never silently zero; a free place is zero by definition.
- Every visible frontend string is `t('English')` with a German entry. Every new backend message shown to users gets its exact German entry in `static/de_backend.js`.
- Nav labels live only in the `PAGES` table in `static/app.js`. Do not add a second route or navigation list.
- Strict CSP stays. Leaflet and markercluster load from cdnjs with pinned versions and SRI hashes; no new host is added to the CSP.
- Marker clustering must degrade to plain markers when the plugin cannot load. A blocked CDN never blanks the map or the page.
- The map is capped per layer. The endpoint accepts `limit` from 1 to 2000; the page asks for 1000 by default and offers 2000.
- All new analytics and matching are local SQL over indexed columns. Do not add a background job or an external queue.
- Tests use fixtures and in-memory databases. Backend tests never touch the network.
- Do not use `git add -A`. Stage only the files named in each task; the working tree already has an unrelated README change.
- No text in code, comments, documentation or commit messages may name the benchmark product this feature was compared with at product level. Describe the feature on its own terms.

## Review Focus

1. **Overlapping places and ties.** A charging stop inside both a 500 m place and a 100 m place must go to the 100 m place; two places with the same radius and distance must go to the lower id. Covered by `test_match_prefers_smallest_radius_then_lowest_id` in Task 2.
2. **Old and moved home data.** An existing database may have no tariff row, invalid JSON, missing coordinates, a radius of 5 m or 99999 m, or already one home. Migration must create exactly one usable home or none, never crash and never duplicate. Covered by the five migration tests in Task 1 and `test_home_here_moves_the_home_geofence` in Task 11.
3. **Cost unknowns.** A priced place with no energy, a minute price with no duration, a free place with no energy and a manual cost on a free place must each resolve to the correct amount or to unknown. Covered by the seven cost tests in Task 3.
4. **A crowded map and a blocked CDN.** A car with 2000 parked readings must not freeze the page; when the clustering script is blocked, pins must still appear and the map must remain usable. Covered by the map limit test in Task 6, the cluster option check and browser cluster check in Task 7, and the blocked-plugin browser check in Task 7.
5. **Editing and deleting places.** Shrinking or deleting a place must clear or recompute the links of every affected trip and charge, without deleting any trip, charge or visit. The home place must refuse deletion. Covered by `test_editing_a_place_reassigns_trips_and_charges` and `test_delete_place_clears_references_and_refuses_home` in Tasks 2 and 5.

## File Structure

- `skoda_mate/schema.py`: geofence table and indexes, new foreign-key columns, one-time home seed.
- `skoda_mate/places.py` (new): matching, assignment, summaries, detail, CRUD invariants and home upsert. No FastAPI imports.
- `skoda_mate/costs.py`: `place` argument and the place-price precedence step.
- `skoda_mate/presenters.py`: resolve a charge place once and pass it to the cost function.
- `skoda_mate/stats.py`: pass places into cost calculation and annotate parked map clusters with a place id.
- `skoda_mate/recorder.py`: write `geofence_id` whenever a charge or trip location is written.
- `skoda_mate/importer.py`, `skoda_mate/merge.py`: reassign after bulk changes.
- `skoda_mate/routers/places.py` (new): `/api/places` CRUD and detail.
- `skoda_mate/routers/reports.py`: map limit, geofence summaries and cluster annotations.
- `skoda_mate/routers/settings.py`, `skoda_mate/routers/vehicles.py`: keep the legacy home coordinates and `home-here` working by upserting the home geofence.
- `skoda_mate/web.py`: include the new router and backfill place links at startup.
- `skoda_mate/static/lib/mapview.js`: circles, optional clustering, fallback.
- `skoda_mate/static/pages/places.js` (new): list, create, edit, delete.
- `skoda_mate/static/pages/place.js` (new): one place with visits and charges.
- `skoda_mate/static/pages/map.js`: names, circles, clustering, place links and the cap note.
- `skoda_mate/static/pages/prices.js`: home card reads and moves the home geofence.
- `skoda_mate/static/pages/charge.js`: explain `cost_basis === 'place'`.
- `skoda_mate/static/app.js`: two `PAGES` entries.
- `skoda_mate/static/style.css`: place list, detail and cluster styles.
- `skoda_mate/static/de_backend.js`: German for new backend errors.
- `skoda_mate/demo.py`: seed home, work and two other places before the first snapshot.
- `tests/test_places.py` (new), `tests/test_costs.py` (new), additions to `tests/test_web.py`, `tests/test_importer.py`, `tests/test_merge.py`, `tests/test_demo.py`.
- `scripts/dom-smoke/run.mjs`, `scripts/dom-smoke/browser_e2e.mjs`: new routes, cluster options, cluster presence and blocked-plugin fallback.
- `docs/PLACES.md` (new), `docs/FEATURE-PARITY.md`, `docs/DASHBOARD.md`, `README.md`.

---

### Task 1: Schema, indexes and one-time home seed

**Files:**
- Modify: `skoda_mate/schema.py`
- Test: `tests/test_places.py` (new)

**Interfaces:**
- Produces: `geofences` columns `id, name, kind, lat, lon, radius_m, color, price_kwh, price_minute, session_fee, free, created_at, updated_at`.
- Produces: `trips.start_geofence_id`, `trips.end_geofence_id`, `charges.geofence_id`.
- Produces: `schema.migrate(conn)` seeds a home place from `settings.tariff` when coordinates exist, exactly once.

- [ ] **Step 1: Write the failing migration tests**

```python
import json
from skoda_mate import schema

def test_schema_adds_place_columns_and_indexes():
    conn = schema.connect(":memory:")
    trip_cols = {r["name"] for r in conn.execute("PRAGMA table_info(trips)")}
    charge_cols = {r["name"] for r in conn.execute("PRAGMA table_info(charges)")}
    geo_cols = {r["name"] for r in conn.execute("PRAGMA table_info(geofences)")}
    assert {"start_geofence_id", "end_geofence_id"} <= trip_cols
    assert "geofence_id" in charge_cols
    assert {"name", "kind", "lat", "lon", "radius_m", "free"} <= geo_cols
    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_snapshots_place", "idx_geofences_one_home"} <= indexes

def test_migrate_seeds_home_once_and_clamps_the_radius():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?)",
                 (json.dumps({"home_lat": 50.11, "home_lon": 8.68, "home_radius_m": 5}),))
    conn.commit()
    schema.migrate(conn)
    homes = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchall()
    assert len(homes) == 1 and homes[0]["name"] == "Home" and homes[0]["radius_m"] == 20
    schema.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM geofences WHERE kind='home'").fetchone()[0] == 1

def test_migrate_clamps_a_huge_radius():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?)",
                 (json.dumps({"home_lat": 50.11, "home_lon": 8.68, "home_radius_m": 99999}),))
    conn.commit()
    schema.migrate(conn)
    assert conn.execute("SELECT radius_m FROM geofences WHERE kind='home'").fetchone()[0] == 5000

def test_migrate_without_home_is_fine():
    conn = schema.connect(":memory:")
    assert conn.execute("SELECT COUNT(*) FROM geofences").fetchone()[0] == 0

def test_migrate_survives_bad_tariff_json():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff','{not json')")
    conn.commit()
    schema.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM geofences").fetchone()[0] == 0

def test_migrate_skips_home_without_both_coordinates():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?)", (json.dumps({"home_lat": 50.11}),))
    conn.commit()
    schema.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM geofences").fetchone()[0] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest -q tests/test_places.py -v`
Expected: FAIL because `geofences` and the new columns do not exist.

- [ ] **Step 3: Implement the schema and seed**

Add the table and indexes to `SCHEMA`: `geofences(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'place', lat REAL NOT NULL, lon REAL NOT NULL, radius_m INTEGER NOT NULL DEFAULT 150, color TEXT, price_kwh REAL, price_minute REAL, session_fee REAL, free INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')), updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')))`, a partial unique index `idx_geofences_one_home ON geofences(kind) WHERE kind='home'`, `idx_snapshots_place ON snapshots(vehicle_id, lat, lon) WHERE lat IS NOT NULL AND lon IS NOT NULL`, and indexes on `trips(start_geofence_id)`, `trips(end_geofence_id)` and `charges(geofence_id)`.

Add the three columns to `EXTRA_COLUMNS` as `INTEGER` so an old database gains them through `ALTER TABLE`. Add `_seed_home_geofence(conn)` in `schema.py` (import `json` and `math` there; keep the module free of app imports): read `settings.tariff` with a plain `SELECT`, parse it inside `try/except (ValueError, TypeError, KeyError)`, require finite `home_lat` and `home_lon`, clamp `home_radius_m` to 20..5000 with a default of 150, and insert `name='Home'`, `kind='home'`, `color=NULL` only when no home row exists. Call it from `migrate()` after `dedupe_trips` and before the final commit.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest -q tests/test_places.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add skoda_mate/schema.py tests/test_places.py
git commit -m "feat: add geofences and seed home from the saved tariff"
```

---

### Task 2: Places module, matching, assignment, summaries, detail and deletion

**Files:**
- Create: `skoda_mate/places.py`
- Test: `tests/test_places.py`

**Interfaces:**
- Produces: `KINDS = ("home", "work", "place")`, `MIN_RADIUS_M = 20`, `MAX_RADIUS_M = 5000`, `COLORS` (six hex strings).
- Produces: `class PlaceError(ValueError)` with `status = 400`, `class PlaceNotFound(PlaceError)` with `status = 404`, `class PlaceConflict(PlaceError)` with `status = 409`.
- Produces: `list_places(conn) -> list[dict]`, `get(conn, place_id: int) -> dict | None`.
- Produces: `match(conn, lat, lon, places: list[dict] | None = None) -> dict | None`.
- Produces: `assign_all(conn) -> dict[str, int]`, `summaries(conn) -> list[dict]`.
- Produces: `detail(conn, place_id: int, now_iso: str, tz_offset: int = 0) -> dict | None` with `visits` (`arrived_at`, `left_at`, `minutes`, `open`, `trip_id`), `charges` (last 100), `parked_minutes`, `charged_kwh`, `cost`, `currency`.
- Produces: `create(conn, data: dict) -> dict` and `update(conn, place_id: int, data: dict) -> dict`, both returning the summary shape (all place fields plus `visit_count`, `day_count`, `charge_count`, `last_seen`).
- Produces: `delete(conn, place_id: int) -> dict[str, int]`.
- Produces: `upsert_home(conn, lat: float, lon: float, radius_m: int | None = None, name: str = "Home") -> dict`; a new home gets 150 m, an existing home keeps its radius when `radius_m` is `None`.

- [ ] **Step 1: Write the failing places tests**

Add `import pytest` and `from skoda_mate import places` to the top of `tests/test_places.py`; Task 4 adds `recorder` and the `VIN` constant from `tests.test_web`.

```python
def test_match_prefers_smallest_radius_then_lowest_id():
    conn = schema.connect(":memory:")
    wide = places.create(conn, {"name": "Wide", "kind": "place", "lat": 50.0, "lon": 8.0, "radius_m": 500})
    assert wide["radius_m"] == 500
    narrow = places.create(conn, {"name": "Narrow", "kind": "place", "lat": 50.0005, "lon": 8.0005, "radius_m": 100})
    assert places.match(conn, 50.0005, 8.0005)["id"] == narrow["id"]
    twin = places.create(conn, {"name": "Twin", "kind": "place", "lat": 50.0005, "lon": 8.0005, "radius_m": 100})
    assert twin["id"] > narrow["id"]
    assert places.match(conn, 50.0005, 8.0005)["id"] == narrow["id"]
    assert places.match(conn, 51.0, 9.0) is None

def test_assign_all_sets_trip_start_end_and_charge():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.1, "lon": 8.1, "radius_m": 150})
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,start_lat,start_lon,end_lat,end_lon) VALUES(?,?,?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T08:00:00+00:00", "2027-02-10T08:40:00+00:00", 50.0, 8.0, 50.1, 8.1))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,lat,lon) VALUES(?,?,?,?)",
                 (vid, "2027-02-10T19:00:00+00:00", 50.1, 8.1))
    counts = places.assign_all(conn)
    trip = conn.execute("SELECT start_geofence_id, end_geofence_id FROM trips").fetchone()
    charge = conn.execute("SELECT geofence_id FROM charges").fetchone()
    assert (trip[0], trip[1], charge[0]) == (home["id"], work["id"], work["id"])
    assert counts["trips"] == 1 and counts["charges"] == 1

def test_summaries_count_visits_days_and_last_seen():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    for day in ("2027-02-11", "2027-02-12"):
        conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_lat,end_lon) VALUES(?,?,?,?,?,?)",
                     (vid, day, day + "T08:00:00+00:00", day + "T08:30:00+00:00", 50.0, 8.0))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,lat,lon) VALUES(?,?,?,?,?)",
                 (vid, "2027-02-12T19:00:00+00:00", "2027-02-12T20:00:00+00:00", 50.0, 8.0))
    places.assign_all(conn)
    summary = next(p for p in places.summaries(conn) if p["id"] == home["id"])
    assert summary["visit_count"] == 2 and summary["day_count"] == 2
    assert summary["charge_count"] == 1 and summary["last_seen"].startswith("2027-02-12")

def test_delete_place_clears_references_and_refuses_home():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.1, "lon": 8.1, "radius_m": 150})
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,start_lat,start_lon,end_lat,end_lon) VALUES(?,?,?,?,?,?,?,?)",
                 (vid, "t1", "2027-02-10T08:00:00+00:00", "2027-02-10T08:40:00+00:00", 50.1, 8.1, 50.1, 8.1))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,lat,lon) VALUES(?,?,?,?)",
                 (vid, "2027-02-10T19:00:00+00:00", 50.1, 8.1))
    places.assign_all(conn)
    assert places.delete(conn, work["id"]) == {"trips": 1, "charges": 1}
    assert tuple(conn.execute("SELECT start_geofence_id, end_geofence_id FROM trips").fetchone()) == (None, None)
    assert conn.execute("SELECT geofence_id FROM charges").fetchone()[0] is None
    with pytest.raises(places.PlaceError):
        places.delete(conn, home["id"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest -q tests/test_places.py -k 'match or assign or summaries or delete' -v`
Expected: FAIL with `ModuleNotFoundError: skoda_mate.places`.

- [ ] **Step 3: Implement `skoda_mate/places.py`**

Use `costs.distance_m(lat1, lon1, lat2, lon2)` for matching. `match` loads places when none are passed, sorts by `(radius_m, id)` and returns the first whose distance is less than or equal to its radius; return `None` when `lat` or `lon` is `None`. `assign_all` reads every place once, then updates `trips.start_geofence_id`, `trips.end_geofence_id` and `charges.geofence_id` only where the value changes, commits once and returns the number of changed trips and charges.

`summaries` returns each place plus `visit_count` (trips whose `end_geofence_id` is this place), `day_count` (distinct UTC dates of those arrivals), `charge_count` and `last_seen` (latest trip arrival or charge end at the place). Order by `kind` with home first, then `name` case-insensitively.

`detail` builds one visit per trip that ends at the place: `arrived_at` is the trip end, `left_at` is the next trip start when it follows within 12 hours, `minutes` is the parked time, and `open` is true while no later trip has started. `parked_minutes` sums those visits, `charged_kwh` sums the linked charges and `cost` sums `costs.charge_cost` for them with their place; load the tariff with `costs.load_tariff(conn)` and take `currency` from it. Ignore a missing timestamp rather than inventing one.

`create` inserts the row with defaults for omitted optional fields, translates a SQLite uniqueness error on the home index into `PlaceConflict`, commits, calls `assign_all` and returns the place summary. `update` raises `PlaceConflict` when it would create a second home, raises `PlaceError` when changing an existing home away from `home`, updates `updated_at`, commits, calls `assign_all` and returns the summary. `delete` raises `PlaceError` for a home, sets `charges.geofence_id`, `trips.start_geofence_id` and `trips.end_geofence_id` to `NULL` for that place in one transaction, deletes the row, commits and returns the counts.

`upsert_home` clamps a given radius, updates the existing home row or inserts one with `kind='home'`, commits and calls `assign_all`. When a home exists, keep its name, colour and radius unless a new radius is passed, and only move or resize it. It never creates a second home.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest -q tests/test_places.py -v`
Expected: all tests in the file pass.

- [ ] **Step 5: Run lint and types**

Run: `uv run --extra dev ruff check skoda_mate/places.py tests/test_places.py && uv run --extra dev mypy`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add skoda_mate/places.py tests/test_places.py
git commit -m "feat: match trips and charges to named places"
```

---

### Task 3: Per-place prices in costs and presenters

**Files:**
- Modify: `skoda_mate/costs.py`, `skoda_mate/presenters.py`, `skoda_mate/stats.py`
- Test: `tests/test_costs.py` (new)

**Interfaces:**
- Consumes: `places.get(conn, id)` from Task 2.
- Produces: `costs.place_kind(charge: dict, tariff: dict, place: dict | None = None) -> str`.
- Produces: `costs.charge_cost(charge: dict, tariff: dict, place: dict | None = None) -> dict` with `basis` in `manual`, `place`, `tariff`, `tariff-guess`, `none`.
- Produces: `presenters.charge_out` adds `place` as `{id, name, kind}` or `None`, and passes the same place to `charge_cost`.

- [ ] **Step 1: Write the failing cost tests**

```python
TARIFF = {"currency": "EUR", "home_kwh": 0.30, "public_ac_kwh": 0.55, "public_dc_kwh": 0.79,
          "home_lat": 50.0, "home_lon": 8.0, "home_radius_m": 150}

def test_place_price_includes_energy_minutes_and_session_fee():
    place = {"kind": "work", "price_kwh": 0.50, "price_minute": 0.02, "session_fee": 1.0, "free": 0}
    charge = {"energy_kwh": 20.0, "duration_min": 60, "charge_type": "AC"}
    assert costs.charge_cost(charge, TARIFF, place) == {"amount": 12.2, "kind": "public", "basis": "place"}

def test_manual_cost_wins_over_place_price():
    place = {"kind": "home", "price_kwh": 0.50, "free": 0}
    charge = {"energy_kwh": 20.0, "cost_manual": 7.0, "charge_type": "AC"}
    assert costs.charge_cost(charge, TARIFF, place) == {"amount": 7.0, "kind": "home", "basis": "manual"}

def test_manual_place_kind_overrides_the_place_kind():
    place = {"kind": "work", "price_kwh": 0.50, "free": 0}
    charge = {"energy_kwh": 10.0, "place_kind": "home", "charge_type": "AC"}
    assert costs.charge_cost(charge, TARIFF, place) == {"amount": 5.0, "kind": "home", "basis": "place"}

def test_free_place_costs_zero_without_energy():
    place = {"kind": "work", "price_kwh": 0.50, "price_minute": 0.02, "session_fee": 3.0, "free": 1}
    assert costs.charge_cost({"charge_type": "AC"}, TARIFF, place) == {"amount": 0.0, "kind": "public", "basis": "place"}

def test_manual_cost_wins_on_a_free_place():
    place = {"kind": "work", "free": 1}
    assert costs.charge_cost({"cost_manual": 3.0}, TARIFF, place) == {"amount": 3.0, "kind": "public", "basis": "manual"}

def test_minute_price_without_duration_is_unknown():
    place = {"kind": "work", "price_minute": 0.02, "free": 0}
    assert costs.charge_cost({"charge_type": "AC"}, TARIFF, place)["amount"] is None

def test_place_without_price_falls_back_to_tariff_and_unknown_energy_is_unknown():
    no_price = {"kind": "work", "free": 0}
    assert costs.charge_cost({"energy_kwh": 10.0, "charge_type": "AC"}, TARIFF, no_price) == {
        "amount": 5.5, "kind": "public", "basis": "tariff"}
    priced = {"kind": "work", "price_kwh": 0.50, "free": 0}
    assert costs.charge_cost({"charge_type": "AC"}, TARIFF, priced) == {"amount": None, "kind": "public", "basis": "place"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest -q tests/test_costs.py -v`
Expected: FAIL with `TypeError` or wrong `basis` because `place` is not accepted.

- [ ] **Step 3: Implement the precedence**

In `place_kind`, return an explicit `charge['place_kind']` first, then `home` when `place['kind'] == 'home'`, then `public` for a non-home place, then the existing DC and tariff-home rules. In `charge_cost`, keep `cost_manual` first. When a place has `free` or any of `price_kwh`, `price_minute`, `session_fee` set, compute `amount = round((energy_kwh or 0) * price_kwh + (duration_min or 0) * price_minute + (session_fee or 0), 2)` and set `basis='place'`; return `0.0` for `free` even when energy is missing; return `None` when a non-zero `price_kwh` has no energy or a `price_minute` has no duration. When the place has no price fields, use the existing tariff branch. Do not change the manual-cost branch.

In `presenters.charge_out`, load the place with `places.get(conn, c['geofence_id'])` when the id is set, set `c['place']` to `{'id', 'name', 'kind'}` or `None`, and pass the row as the third argument. In `stats.monthly`, load all places once into an id map and pass `places_by_id.get(c.get('geofence_id'))` to `charge_cost`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest -q tests/test_costs.py tests/test_stats.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skoda_mate/costs.py skoda_mate/presenters.py skoda_mate/stats.py tests/test_costs.py
git commit -m "feat: price charges with the rate of their place"
```

---

### Task 4: Write place links at every write boundary

**Files:**
- Modify: `skoda_mate/recorder.py`, `skoda_mate/importer.py`, `skoda_mate/merge.py`, `skoda_mate/web.py`
- Test: `tests/test_places.py`, `tests/test_importer.py`, `tests/test_merge.py`

**Interfaces:**
- Consumes: `places.match(conn, lat, lon)` and `places.assign_all(conn)` from Task 2.
- Produces: every new or updated trip and charge has its `geofence_id` fields set; app startup backfills old rows.

- [ ] **Step 1: Write the failing assignment tests**

```python
def test_ingest_links_a_charge_to_its_place():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    vid = recorder.upsert_vehicle(conn, VIN, battery_kwh=77.0)
    recorder.ingest(conn, vid, {"ts": "2027-02-10T19:00:00+00:00", "soc": 40.0, "charging": True,
                                 "charge_state": "CHARGING", "charge_power_kw": 11.0, "lat": 50.0, "lon": 8.0})
    assert conn.execute("SELECT geofence_id FROM charges").fetchone()[0] == home["id"]

def test_ingest_links_trip_start_and_end():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.1, "lon": 8.1, "radius_m": 150})
    vid = recorder.upsert_vehicle(conn, VIN, battery_kwh=77.0)
    recorder.ingest(conn, vid, {"ts": "2027-02-10T08:00:00+00:00", "soc": 90.0, "charging": False,
                                "in_motion": False, "mileage_km": 2000.0, "lat": 50.0, "lon": 8.0})
    recorder.ingest(conn, vid, {"ts": "2027-02-10T08:10:00+00:00", "soc": 88.0, "charging": False,
                                "in_motion": True, "mileage_km": 2005.0})
    recorder.ingest(conn, vid, {"ts": "2027-02-10T08:40:00+00:00", "soc": 78.0, "charging": False,
                                "in_motion": False, "mileage_km": 2010.0, "lat": 50.1, "lon": 8.1})
    trip = conn.execute("SELECT start_geofence_id, end_geofence_id FROM trips").fetchone()
    assert (trip["start_geofence_id"], trip["end_geofence_id"]) == (home["id"], work["id"])

def test_app_start_backfills_place_links():
    conn = schema.connect(":memory:")
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    vid = recorder.upsert_vehicle(conn, VIN, battery_kwh=77.0)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,start_lat,start_lon) VALUES(?,?,?,?,?)",
                 (vid, "old", "2027-02-09T08:00:00+00:00", 50.0, 8.0))
    conn.commit()
    make_app(conn=conn)
    assert conn.execute("SELECT start_geofence_id FROM trips").fetchone()[0] == home["id"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest -q tests/test_places.py -k 'ingest or backfill' -v`
Expected: FAIL because the links stay `NULL`.

- [ ] **Step 3: Wire the writers**

In `recorder._charge`, resolve the place from `s.get('lat')` and `s.get('lon')` for the detected INSERT and add `geofence_id` to its column list and values. In `infer_charges`, resolve from `c['a']['lat']` and `c['a']['lon']` for the inferred INSERT and UPDATE. In `_trips`, resolve the trip start from `ref['lat']`/`ref['lon']` and add `start_geofence_id` to the INSERT. In `_finish`, resolve both start and end, add `start_geofence_id` and `end_geofence_id` to the UPDATE and to the odometer-jump INSERT.

In `importer.run`, call `places.assign_all(conn)` after `recorder.infer_charges` when the import wrote something. In `merge.merge` and `merge.unmerge`, call `places.assign_all(conn)` after the commit. In `web.create_app`, after the existing `repair_charge_gaps` and `infer_charges` loop, call `places.assign_all(conn)` so an upgraded database gets its links before the first page load.

Add one assertion to `tests/test_importer.py` that an imported trip has a non-null `start_geofence_id` and `end_geofence_id` when the CSV coordinates fall inside two places, and one to `tests/test_merge.py` that a merged trip keeps the first start and last end place.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest -q tests/test_places.py tests/test_importer.py tests/test_merge.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add skoda_mate/recorder.py skoda_mate/importer.py skoda_mate/merge.py skoda_mate/web.py tests/test_places.py tests/test_importer.py tests/test_merge.py
git commit -m "feat: keep trip and charge place links up to date"
```

---

### Task 5: Places API and detail

**Files:**
- Create: `skoda_mate/routers/places.py`
- Modify: `skoda_mate/web.py`, `skoda_mate/static/de_backend.js`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `GET /api/places` returns `{"items": [summary]}`; summary fields are all geofence fields plus `visit_count`, `day_count`, `charge_count`, `last_seen`.
- Produces: `POST /api/places` with a place body, returns the created summary.
- Produces: `GET /api/places/{id}` returns the summary plus `visits` (`arrived_at`, `left_at`, `minutes`, `open`, `trip_id`), `charges` (last 100), `parked_minutes`, `charged_kwh`, `cost`, `currency`.
- Produces: `PUT /api/places/{id}` replaces name, kind, position, radius, colour and prices; returns the updated summary.
- Produces: `DELETE /api/places/{id}` returns `{"ok": true, "trips": n, "charges": m}`.

- [ ] **Step 1: Write the failing API tests**

```python
def test_places_crud_and_one_home():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    home = c.post("/api/places", json={"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150}).json()
    work = c.post("/api/places", json={"name": "Office", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 150}).json()
    assert work["visit_count"] == 1 and home["kind"] == "home"
    assert c.post("/api/places", json={"name": "Second home", "kind": "home", "lat": 51, "lon": 9}).status_code == 409
    edited = c.put(f"/api/places/{work['id']}",
                   json={"name": "Office 2", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 80}).json()
    assert edited["name"] == "Office 2" and edited["radius_m"] == 80
    assert c.delete(f"/api/places/{home['id']}").status_code == 400
    assert c.delete(f"/api/places/{work['id']}").json() == {"ok": True, "trips": 1, "charges": 0}

def test_place_validation():
    c, conn, api, vid = connected()
    for body in ({"name": "", "lat": 50, "lon": 8},
                 {"name": "X", "lat": 91, "lon": 8},
                 {"name": "X", "lat": 50, "lon": 8, "radius_m": 5},
                 {"name": "X", "lat": 50, "lon": 8, "free": True, "price_kwh": 0.5}):
        assert c.post("/api/places", json=body).status_code == 400

def test_editing_a_place_reassigns_trips_and_charges():
    c, conn, api, vid = connected()
    seed_charge(conn, vid, lat=50.001, lon=8.001)
    place = c.post("/api/places", json={"name": "Edge", "kind": "place", "lat": 50.0, "lon": 8.0,
                                          "radius_m": 150, "price_kwh": 0.50}).json()
    linked = c.get(f"/api/vehicles/{vid}/charges").json()["items"][0]
    assert linked["geofence_id"] == place["id"] and linked["cost_basis"] == "place"
    c.put(f"/api/places/{place['id']}", json={"name": "Edge", "kind": "place", "lat": 50.0, "lon": 8.0, "radius_m": 20})
    cleared = c.get(f"/api/vehicles/{vid}/charges").json()["items"][0]
    assert cleared["geofence_id"] is None and cleared["cost_basis"] == "tariff-guess"

def test_place_detail_lists_visits_and_charges():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    seed_charge(conn, vid, lat=50.4, lon=8.4)
    work = c.post("/api/places", json={"name": "Office", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 150}).json()
    d = c.get(f"/api/places/{work['id']}?tz_offset=0").json()
    assert d["visit_count"] == 1 and len(d["visits"]) == 1 and d["charged_kwh"] > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest -q tests/test_web.py -k place -v`
Expected: FAIL with 404 for `/api/places`.

- [ ] **Step 3: Implement the router**

Create `router = APIRouter()` in `skoda_mate/routers/places.py` with full paths (`/api/places`, `/api/places/{place_id}`). Define `PlaceIn(BaseModel)` with `name: str`, `kind: str = "place"`, `lat: float`, `lon: float`, `radius_m: int = 150`, `color: str | None = None`, `price_kwh: float | None = None`, `price_minute: float | None = None`, `session_fee: float | None = None`, `free: bool = False`.

Validate in one `_payload(body)` function and raise `HTTPException(400, message)` with these exact English messages: `Name must be 1 to 60 characters.`, `Kind must be home, work or place.`, `Latitude must be between -90 and 90.`, `Longitude must be between -180 and 180.`, `Radius must be between 20 and 5000 metres.`, `Colour must be a hex colour such as #0b7a52.`, `Price per kWh must be between 0 and 10.`, `Price per minute must be between 0 and 10.`, `Session fee must be between 0 and 1000.`, `A free place cannot have a price.` Strip the name and reject non-finite coordinates; the model requires both coordinates.

Catch `PlaceError` and use `exc.status` for 400, 404 and 409. Home creation returns 409 through `PlaceConflict` with `Only one home place is allowed.`; deleting or re-kinding a home raises 400 with `The home place cannot be deleted.` and `The home place cannot change its kind.`. A missing id returns 404 with `Place not found.`. `GET /{id}` calls `places.detail(conn, id, ctx.now_iso(), tz_offset)` with `tz_offset: int = Query(0, ge=-840, le=840)`. `PUT` calls `places.update`, `DELETE` calls `places.delete`, and both return the shapes above.

Include the module in the `web.py` router tuple after `reports`. Add the German entries for the exact messages to `de_backend.js` (for example `Name must be 1 to 60 characters.` becomes `Der Name muss 1 bis 60 Zeichen lang sein.`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest -q tests/test_web.py -k place -v`
Expected: all places API tests pass.

- [ ] **Step 5: Commit**

```bash
git add skoda_mate/routers/places.py skoda_mate/web.py skoda_mate/static/de_backend.js tests/test_web.py
git commit -m "feat: expose places over the dashboard API"
```

---

### Task 6: Map endpoint with places, annotations and a limit

**Files:**
- Modify: `skoda_mate/routers/reports.py`, `skoda_mate/stats.py`, `skoda_mate/demo.py`
- Test: `tests/test_web.py`, `tests/test_demo.py`

**Interfaces:**
- Consumes: `places.summaries(conn)`, `places.create(...)`, `places.upsert_home(...)` and `places.match(...)` from Task 2.
- Produces: `GET /api/vehicles/{vid}/map?limit=1000` returns `parked`, `charges`, `trips`, `places`, `limit`, `current`, `tariff`.
- Produces: each parked cluster has `place_id`; each charge has `geofence_id`; each trip has `start_geofence_id` and `end_geofence_id`.
- Produces: demo data with Home, Work, Shop and Darmstadt places created before the first snapshot, so every demo trip and charge has a place.

- [ ] **Step 1: Write the failing map tests**

```python
def test_map_returns_places_and_respects_the_limit():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    work = c.post("/api/places", json={"name": "Office", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 150}).json()
    m = c.get(f"/api/vehicles/{vid}/map?limit=1").json()
    assert m["limit"] == 1 and len(m["parked"]) <= 1
    assert any(p["id"] == work["id"] and p["visit_count"] == 1 for p in m["places"])
    assert c.get(f"/api/vehicles/{vid}/map?limit=2001").status_code == 422

def test_map_marks_a_parked_cluster_inside_a_place():
    c, conn, api, vid = connected()
    place = c.post("/api/places", json={"name": "Parked", "kind": "place", "lat": 50.11, "lon": 8.68, "radius_m": 150}).json()
    m = c.get(f"/api/vehicles/{vid}/map").json()
    assert any(p["place_id"] == place["id"] for p in m["parked"])

def test_demo_has_named_places_and_links():
    with demo_client() as c:
        conn = c.app.state.ctx.conn
        names = {p["name"] for p in c.get("/api/places").json()["items"]}
        assert {"Home", "Work", "Shop", "Darmstadt"} <= names
        assert conn.execute("SELECT COUNT(*) FROM trips WHERE start_geofence_id IS NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM charges WHERE geofence_id IS NULL").fetchone()[0] == 0
```

Put the first two tests in `tests/test_web.py` and the demo test in `tests/test_demo.py` (it uses the existing `demo_client()` helper).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest -q tests/test_web.py tests/test_demo.py -k 'map or demo' -v`
Expected: FAIL because `places` is missing, the default cap is 300, and the demo has no places.

- [ ] **Step 3: Implement the map additions**

Change `stats.map_points(conn, vid, limit=1000)` to add `place_id` to each parked cluster by calling `places.match(conn, lat, lon, all_places)`; load the places once. Keep charges and trips as they are but select `geofence_id` / `start_geofence_id` / `end_geofence_id`. In the map route, add `limit: int = Query(1000, ge=1, le=2000)`, pass it to `map_points`, and add `"places": places.summaries(conn)` plus `"limit": limit` to the response. Preserve `current` and `tariff`.

- [ ] **Step 4: Seed the demo places before the first snapshot**

In `demo.seed`, after saving the tariff settings and before the first `snap`, call `places.upsert_home(conn, HOME[0], HOME[1], 180)` and create `Work` at `WORK`, `Shop` at `SHOP` and `Darmstadt` at `FAR` with kinds `work` and `place` and radii of 150 m. This must happen before any `snap`, so `recorder` links every row. Use the existing coordinate tuples; do not hard-code new coordinates.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev pytest -q tests/test_web.py tests/test_demo.py -k 'map or demo' -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add skoda_mate/routers/reports.py skoda_mate/stats.py skoda_mate/demo.py tests/test_web.py tests/test_demo.py
git commit -m "feat: return named places and a limit from the map endpoint"
```

---

### Task 7: Map circles and marker clustering with fallback

**Files:**
- Modify: `skoda_mate/static/lib/mapview.js`, `skoda_mate/static/style.css`, `scripts/dom-smoke/run.mjs`, `scripts/dom-smoke/browser_e2e.mjs`
- Test: `scripts/dom-smoke/run.mjs`, `scripts/dom-smoke/browser_e2e.mjs`

**Interfaces:**
- Produces: `export const CLUSTER_OPTIONS = { maxClusterRadius: 50, disableClusteringAtZoom: 14, chunkedLoading: true, showCoverageOnHover: false, spiderfyOnMaxZoom: true }`.
- Produces: `export function loadMarkerCluster(): Promise<void>`; it loads both markercluster CSS files and the JS from cdnjs 1.5.3 with SRI, and rejects on failure.
- Produces: `mapView({ circles: [{lat,lon,radius,color,label,id}], cluster?: boolean, onCircleClick?: (id) => void, onMapClick?: (lat, lon) => void })`; `circle` remains supported.

- [ ] **Step 1: Add the failing checks**

In `scripts/dom-smoke/run.mjs`, import `CLUSTER_OPTIONS` from `../../skoda_mate/static/lib/mapview.js` after the DOM globals are installed, and fail the run when `disableClusteringAtZoom !== 14` or `maxClusterRadius !== 50`.

In `scripts/dom-smoke/browser_e2e.mjs`, after the map navigation, evaluate `document.querySelectorAll('.marker-cluster').length` and check it is greater than zero on the demo data. Then open a second page with request interception that aborts every URL containing `markercluster`, go to `#/map`, wait, and check that `#main .pin` is greater than zero and the page has no `Something went wrong` text.

- [ ] **Step 2: Run the checks to verify they fail**

Run from `scripts/dom-smoke`: `node run.mjs`
Expected: FAIL because `CLUSTER_OPTIONS` is not exported.

- [ ] **Step 3: Implement the map changes**

Add markercluster 1.5.3 constants and SRI entries. Read the three hashes from `https://api.cdnjs.com/libraries/leaflet.markercluster/1.5.3?fields=sri`; do not invent them. `loadMarkerCluster` appends `MarkerCluster.min.css`, `MarkerCluster.Default.min.css` and `leaflet.markercluster.min.js`, resolves when `window.L.markerClusterGroup` exists, and resets its cached promise on error.

In `mapView`, create a `lineLayer` for lines and circles, a `markerLayer` that is a marker cluster group when `cluster !== false` and the plugin loaded, and a `plainLayer` for markers with `noCluster: true` (trip endpoints and draggable pins). If `loadMarkerCluster` rejects, keep `markerLayer = L.layerGroup()`; no error banner. In `paint`, clear all three, draw `o.circles` and the backward-compatible `o.circle` into `lineLayer` with `fillOpacity: 0.08`, `weight: 1.5`, and a click handler calling `o.onCircleClick(circle.id)`, then add markers to their layer. Extend the bounds with circle edges as the current single-circle code does. Attach `o.onMapClick` to the Leaflet map's `click` event and pass `e.latlng.lat`/`e.latlng.lng`; call `L.DomEvent.stopPropagation(e.originalEvent)` in the circle and marker click handlers so a place click does not also create a draft point.

Add `.pin-cluster` styles to `style.css`: a circular badge using the accent colour, white text, a border and a compact size. The cluster icon function creates a DOM element with classes `marker-cluster pin-cluster` and the count as `textContent`, never an HTML string.

- [ ] **Step 4: Run the checks to verify they pass**

Run from `scripts/dom-smoke`: `node run.mjs`
Expected: pass, including the cluster option checks.

Start a demo server on a scratch database, then run `BASE=http://localhost:8766 node browser_e2e.mjs` from `scripts/dom-smoke`.
Expected: the map route renders, `.marker-cluster` exists on the normal page, and the blocked-plugin page still shows pins without a page error.

- [ ] **Step 5: Commit**

```bash
git add skoda_mate/static/lib/mapview.js skoda_mate/static/style.css scripts/dom-smoke/run.mjs scripts/dom-smoke/browser_e2e.mjs
git commit -m "feat: cluster crowded maps and fall back to plain pins"
```

---

### Task 8: Places list page with create, edit and delete

**Files:**
- Create: `skoda_mate/static/pages/places.js`
- Modify: `skoda_mate/static/app.js`, `skoda_mate/static/style.css`, `skoda_mate/static/de_backend.js`, `scripts/dom-smoke/run.mjs`
- Test: `scripts/dom-smoke/run.mjs`, `scripts/dom-smoke/browser_e2e.mjs`

**Interfaces:**
- Consumes: `/api/places` from Task 5 and `mapView` circles from Task 7.
- Produces: `PAGES` entry `{ path: 'places', name: 'places', label: 'Places', icon: 'pin' }`.
- Produces: a page that lists places, creates one from a detected parked cluster or a map click, edits all fields and deletes non-home places.
- Produces: `export function placeForm({ place = null, point = null, onSaved } = {})` in `places.js`, reused by the detail page.

- [ ] **Step 1: Add the failing route check**

Add `places` to `run.mjs` routes and to the browser `ROUTES` and sidebar label list. Run `node run.mjs`; expected: FAIL because `static/pages/places.js` is missing.

- [ ] **Step 2: Implement the page**

Fetch `/api/places` and `/api/vehicles/{vid}/map?limit=500` in parallel. Render an `h1` with `t('Places')`, a short intro, an `Add place` button, a map with all places as circles and markers, a card list with name, kind chip, radius, `visit_count`, `day_count` and `last_seen`, and a `Detected places` card built from parked clusters whose `place_id` is null. Every row links to `#/places/{id}`. A home place still named `Home` is displayed as `t('Home')`; any user-chosen name is shown verbatim.

Use `modal` for the form and put it in an exported `placeForm({ place, point, onSaved })` helper. Fields: `Name`, `Kind` (`Home`, `Work`, `Place`), `Radius (metres)`, `Colour`, `Price per kWh`, `Price per minute`, `Session fee`, `Free`. When editing a home place, show the kind as read-only text instead of a selector, because the backend refuses a kind change. Prefill coordinates from the clicked map point, from the parked cluster, or from `ctx.overview.sections.position` when the car is parked; show the coordinates as read-only text, not as raw inputs. A map click opens the form with that point; clicking again before saving chooses a new point. `Save` posts or puts the full body, calls `onSaved` and closes; `Delete` uses `confirmDialog` and is hidden for a home place.

Use `button`, `card`, `field`, `modal`, `banner`, `empty`, `toast` and `asyncButton` from `lib/ui.js`; build all DOM with `h()`; no `innerHTML`. Format dates with `f.dateTime` and distances with `f.km`.

Add German for every new `t()` string, including `Places`, `Add place`, `Detected places`, `Name this place`, `Radius (metres)`, `Price per minute`, `Session fee`, `Free`, `A free place cannot have a price.`, `Delete place`, `Delete this place?`, `Home cannot be deleted.`, `Place saved`, `Place deleted`, and the field labels. Run `node i18n_coverage.mjs`; expected: no missing entries.

- [ ] **Step 3: Run the checks**

Run from `scripts/dom-smoke`: `node run.mjs` and `node i18n_coverage.mjs`.
Expected: pass.

With the demo server: `BASE=http://localhost:8766 node browser_e2e.mjs`.
Expected: `#/places` fits the phone viewport and the sidebar opens it.

- [ ] **Step 4: Commit**

```bash
git add skoda_mate/static/pages/places.js skoda_mate/static/app.js skoda_mate/static/style.css skoda_mate/static/de_backend.js scripts/dom-smoke/run.mjs scripts/dom-smoke/browser_e2e.mjs
git commit -m "feat: add the places page"
```

---

### Task 9: Place detail page with visits and charges

**Files:**
- Create: `skoda_mate/static/pages/place.js`
- Modify: `skoda_mate/static/app.js`, `skoda_mate/static/style.css`, `scripts/dom-smoke/run.mjs`, `scripts/dom-smoke/browser_e2e.mjs`
- Test: `scripts/dom-smoke/run.mjs`, `scripts/dom-smoke/browser_e2e.mjs`

**Interfaces:**
- Consumes: `GET /api/places/{id}` from Task 5.
- Produces: `PAGES` entry `{ path: 'places/:id', name: 'place', section: 'places' }`; the nav highlights Places.

- [ ] **Step 1: Add the failing detail route**

Add `places/1` to `run.mjs` and browser `ROUTES`. Run `node run.mjs`; expected: FAIL because `static/pages/place.js` is missing.

- [ ] **Step 2: Implement the detail page**

Read `ctx.params[0]`, fetch `/api/places/{id}?tz_offset=${new Date().getTimezoneOffset()}`, and render a back link to `#/places`, the name and kind chip, a map with the place circle, and a stat row with `Visits`, `Days`, `Parked time`, `Charged`, `Cost` (use `f.duration`, `f.kwh`, `f.money`). Add a table of visits with arrival, departure, duration and open/closed, and a table of recent charges with date, energy and cost, linking each charge to `#/charges/{id}`. Add `Edit` and `Delete` buttons; after delete go back to `#/places`.

Import `placeForm` from `./places.js` for Edit; do not duplicate the form. Reuse `f.dateTime` and `f.money`.

Add German for `Back to places`, `Visits`, `Days`, `Parked time`, `Charged`, `Recent visits`, `Recent charges`, `Arrival`, `Departure`, `Open`, `Closed`, `Edit place`, and `Place not found`. Run `node i18n_coverage.mjs`; expected: pass.

- [ ] **Step 3: Run the checks**

Run from `scripts/dom-smoke`: `node run.mjs`; expected: pass.
With the demo server: `BASE=http://localhost:8766 node browser_e2e.mjs`; expected: `#/places/1` fits and renders visits.

- [ ] **Step 4: Commit**

```bash
git add skoda_mate/static/pages/place.js skoda_mate/static/app.js skoda_mate/static/style.css scripts/dom-smoke/run.mjs scripts/dom-smoke/browser_e2e.mjs
git commit -m "feat: show a place with its visits and charges"
```

---

### Task 10: Map page uses places, circles and clustering

**Files:**
- Modify: `skoda_mate/static/pages/map.js`, `skoda_mate/static/pages/charge.js`
- Test: `scripts/dom-smoke/browser_e2e.mjs`

**Interfaces:**
- Consumes: map response `places`, `place_id`, `geofence_id` from Task 6 and `mapView` circles/cluster from Task 7.
- Produces: map markers named by place, circles for every place, a place list with visit counts and links, and a cap note with a `Show all` action.

- [ ] **Step 1: Add the failing map checks**

In `browser_e2e.mjs`, on `#/map`, check that `#main` contains the home place name and that a marker title or popup contains it, and that `.leaflet-interactive` circles exist. The cap note is covered by the backend `limit` test in Task 6; the demo has fewer points than the page cap, so do not invent a cap check here. Run the browser check; expected: FAIL because names and circles are absent.

- [ ] **Step 2: Implement the page**

Fetch `/api/vehicles/{vid}/map?limit=1000`. Build a `placeById` map from `data.places`. Draw every place as a circle with its colour, fill and click handler that navigates to `#/places/{id}`. Name parked clusters with their `place_id`, charges with their `geofence_id` and trips with their start/end place ids. Keep the layer toggles and dashed trip lines; trip endpoint markers use `noCluster: true`. The place list groups by `place_id` and shows `visit_count`, `day_count` and `last_seen`; rows link to the detail page. When `data.limit` is reached, show `Showing only the newest 1000 per layer.` and a `Show all` button that refetches with `limit=2000`; when 2000 is reached, show `Showing the newest 2000 per layer.`.

In `charge.js`, add an explanation for `cost_basis === 'place'`: `Cost uses the price of this place.`; show the place name when present and link it to `#/places/{id}`. Add the German entries.

- [ ] **Step 3: Run the checks**

Run from `scripts/dom-smoke`: `node run.mjs`, `node i18n_coverage.mjs`, and with the demo server `BASE=http://localhost:8766 node browser_e2e.mjs`.
Expected: pass, including names, circles and clusters.

- [ ] **Step 4: Commit**

```bash
git add skoda_mate/static/pages/map.js skoda_mate/static/pages/charge.js
git commit -m "feat: show named places and clusters on the map"
```

---

### Task 11: Home place in Prices and the legacy settings path

**Files:**
- Modify: `skoda_mate/static/pages/prices.js`, `skoda_mate/routers/settings.py`, `skoda_mate/routers/vehicles.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `/api/places` and `places.upsert_home` from Task 2.
- Produces: `PUT /api/settings` with `tariff.home_lat` and `tariff.home_lon` upserts the home geofence, so old clients and saved settings keep working.
- Produces: `POST /api/vehicles/{vid}/home-here` moves the home geofence as well as returning `home_lat`/`home_lon`.

- [ ] **Step 1: Write the failing settings tests**

```python
def test_home_here_moves_the_home_geofence():
    c, conn, api, vid = connected()
    r = c.post(f"/api/vehicles/{vid}/home-here").json()
    home = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchone()
    assert (home["lat"], home["lon"], r["home_lat"], r["home_lon"]) == (50.11, 8.68, 50.11, 8.68)

def test_settings_home_coordinates_update_the_home_place():
    c, conn, api, vid = connected()
    c.put("/api/settings", json={"tariff": {"home_lat": 50.0, "home_lon": 8.0, "home_radius_m": 200}})
    home = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchone()
    assert (home["lat"], home["lon"], home["radius_m"]) == (50.0, 8.0, 200)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest -q tests/test_web.py -k 'home_here or settings_home' -v`
Expected: FAIL because only the tariff is written.

- [ ] **Step 3: Implement the settings hook**

In `settings.py`, after `costs.clean_tariff` and `set_setting`, if both `home_lat` and `home_lon` are not `None` (zero is a valid coordinate), call `places.upsert_home(conn, lat, lon, new.get("home_radius_m"))` so an omitted radius keeps the existing one. Keep returning the stored tariff with its legacy coordinates. In the existing `home-here` handler (in `routers/vehicles.py`), keep writing the tariff mirror and call `places.upsert_home(conn, lat, lon)` to preserve the current radius. Do not delete a home place when coordinates are cleared; old keys are ignored for matching.

In `prices.js`, keep the three price rows and replace the home map/coordinate editor with a `Home place` card that shows the home name, radius and visit count, a link to `#/places/{id}` labelled `Edit home place`, and the existing `Use current parking position` button. When no home place exists yet, show `Add home place` linking to `#/places` instead of a dead detail link. Remove the coordinate fields, the map and the clear-home action from this page. On `home-here`, refresh the card and show `Home position saved`. Add German for `Home place`, `Edit home place`, `Add home place` and `Home position saved`.

- [ ] **Step 4: Run the tests and frontend checks**

Run: `uv run --extra dev pytest -q tests/test_web.py -k 'home or settings' -v`; expected: pass.
Run from `scripts/dom-smoke`: `node i18n_coverage.mjs`; expected: pass.
Run with the demo server: `BASE=http://localhost:8766 node browser_e2e.mjs`; expected: the Prices page fits and the home card works.

- [ ] **Step 5: Commit**

```bash
git add skoda_mate/static/pages/prices.js skoda_mate/routers/settings.py skoda_mate/routers/vehicles.py tests/test_web.py
git commit -m "feat: edit the home place from the prices page"
```

---

### Task 12: Documentation and full gates

**Files:**
- Create: `docs/PLACES.md`
- Modify: `docs/FEATURE-PARITY.md`, `docs/DASHBOARD.md`, `README.md`
- Test: full gates

**Interfaces:**
- Produces: user and maintainer documentation for places, prices, map clustering and the local-only data flow.

- [ ] **Step 1: Write the documentation**

Write `docs/PLACES.md` with: what a place is, the one-home rule, the smallest-radius matching rule, how edits reassign old rows, the cost precedence, the map cap and clustering fallback, and the local-only privacy note. Update `docs/DASHBOARD.md` with the Places page and the map circle/cluster behaviour. Add one line to `docs/FEATURE-PARITY.md` for named places with per-place prices and visit history. Add one feature bullet to `README.md`; stage only the README hunk for this feature if the pre-existing edit is still uncommitted.

- [ ] **Step 2: Run the full gates**

Run:
```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check
uv run --extra dev mypy
```
Expected: all tests pass, ruff and mypy clean.

From `scripts/dom-smoke`: `node run.mjs` and `node i18n_coverage.mjs`; expected: pass. With a demo server: `BASE=http://localhost:8766 node browser_e2e.mjs`; expected: pass.

Read the staged diff and the new docs once for any benchmark product name or comparison; none may remain.

- [ ] **Step 3: Commit**

```bash
git add docs/PLACES.md docs/FEATURE-PARITY.md docs/DASHBOARD.md
git add -p README.md   # stage only this feature's bullet
git commit -m "docs: document places and map clustering"
```

---

## Self-Review Notes

- Spec coverage: Phase 1 items 1, 2, 3, 7, 9, 10 and the map part of 12 are covered; the remaining phases have their own plans.
- The plan deliberately does not add any API request, background worker or external service.
- Type names used across tasks: `geofence_id`, `start_geofence_id`, `end_geofence_id`, `visit_count`, `day_count`, `charge_count`, `last_seen`, `place_id`, `cost_basis='place'`.
- The five review-focus lines each have a named test or browser check in an owning task.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-26-places-and-map.md`. Please review the plan. Which execution approach would you prefer?

- **Subagent-driven** - a fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough; costs a fresh context per task and per review.
- **Native** - I implement every task myself in this session, then one fresh reviewer checks the whole branch. Cheapest and fastest; no independent review until the end.

For this plan I recommend **Subagent-driven**, because the tasks share exact interfaces (`geofence_id` columns, `place` cost argument, map response fields) and a shipped mismatch would surface only in Phase 2. Does the plan capture what you want, and which approach should we use?
