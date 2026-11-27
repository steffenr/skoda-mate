# Dashboard developer guide

Vanilla ES modules, no build step, no npm at runtime. Served from `skoda_mate/static/`, shell in `index.html`.

## Facts that shape every page (read first)
The data source is the **official MyŠkoda Public API** (see `docs/superpowers/specs/2026-11-23-official-api-rewrite.md`).
It gives one live reading per request (20 requests/hour/car), **no history**. Therefore:
- **Trips and charges are derived by Mate** from snapshots (odometer, parked/driving state, charging power). Label them
  honestly: trip times are accurate to the poll interval, `approx=1` trips were found only through an odometer jump, energy
  needs the battery capacity the user enters in Settings (`overview.needs_capacity`), costs come from the user's tariff.
- **Not available** (never offer, never fake): lock/unlock, honk, wake-up, route/speed traces, outside temperature,
  maintenance/warnings, battery health (only an *estimate*), push updates. `overview.unavailable` lists them with reasons.
- A missing field means *unknown*, not false/zero. `null` booleans must render as "unknown"/"–", never as "closed"/"off".
- Gate every control and page on `overview.features`, `overview.parts` and `overview.commands[].supported`; show the
  reason (`parts[x].reason`) instead of hiding silently.
- Commands return 202 = "request performed", not "done": say so, then `ctx.refresh()`.

## Shell contract (`static/app.js`)
A page is `static/pages/<name>.js`: `export default async function (root, ctx) { ...; return cleanup? }`.
`ctx`: `api` (get/post/put/patch/del → JSON, throws Error with the server's message), `vid`, `vin`, `params` (regex groups,
e.g. trip id), `query` (URLSearchParams from the hash), `overview` (latest, refreshed every 30 s), `settings`, `currency`,
`nav(path)`, `toast(msg, kind)`, `t`, `f` (format.js), `refresh()` (reload overview + header), `onTick(fn)` (called
every 30 s and after Refresh), `setTitle()`.

Routes live in one table, `PAGES` in `app.js`: `{ path, name, label?, icon?, section?, sepBefore? }`. The sidebar
(`label` present), the router, the nav highlight (`section`) and the preloaded modules all derive from it, so a page is
one entry plus its `pages/<name>.js`. Detail routes reuse a page module with a different pattern and name their section
(`trips/:id` → `trip` in section `trips`).

`''` overview · `trips` · `trips/:id` → `trip` · `charges` · `charges/:id` → `charge` · `battery` · `control` ·
`prices` · `stats` · `map` · `places` · `places/:id` → `place` · `events` · `import` · `settings` · `system` ·
`system/:tab` → `system` (`status|capabilities|calls|diagnostics`). The old `#/capabilities` link redirects to
`system/capabilities`.

## Libraries (`static/lib/`)
`dom.js` h()/svg()/mount()/clear() — **no innerHTML, ever** (names, addresses and notes come from outside).
`ui.js` card, stat, chip, button, asyncButton, banner, empty, loading, field, seg, kv, socBar, table, modal,
confirmDialog, toast. `charts.js` lineChart (`gaps: [{from, to}]` shades stretches without data and draws no line across
them), barChart, sparkline. `mapview.js` mapView (Leaflet from cdnjs, OpenStreetMap tiles, optional marker
clustering, offline fallback).
`car.js` carView. `quality.js` checkLabel/actionLabel, the data-quality names shared by System and the Activity List
tab. `icons.js` icon(name) (see ICON_NAMES). `format.js` km/mi aware formatters (`f.km`, `f.cons`, `f.kwh`,
`f.money`, `f.duration`, `f.dateTime`, `f.dayLabel`, `f.shortPlace`, …). `i18n.js` `t('English')`; add German with
`extendDE({...})` at the top of your page file. `style.css` holds tokens and components; page styles live in
`pages-a.css` / `pages-b.css` (loaded by `index.html`), keep a new rule next to the page it belongs to.

`setup.js` with `setup.html` / `login.html` is the one deliberate exception: it renders before a session (and before
the language setting) exists, so it is English-only and outside `t()` coverage.

## Places and the map
`places.py` owns the geofences, matching, assignment and summaries; `routers/places.py` exposes CRUD, and the map
endpoint in `routers/reports.py` reads them. Trips store `start_geofence_id`/`end_geofence_id`, charges `geofence_id`.
Matching is backend work, never a page: it runs when those rows are written and when a place is created or edited. One
home row (a partial unique index), radius 20–5000 m, smallest radius wins, ties go to the lower id. `assign_all()`
rewrites every trip and charge after a place is created or edited (and once per start), so a moved or shrunk place
never leaves stale links; deleting a place clears the links to it.

`GET /api/places` returns summaries (`visit_count`, `day_count`, `charge_count`, `last_seen`);
`GET /api/places/{id}` adds visits, the newest 100 charges and their totals. Both take `tz_offset` so day counts use the
viewer's local day. The pages are `pages/places.js` (map, list, detected clusters, form exported for reuse) and
`pages/place.js` (detail, reusing that form).

`GET /api/vehicles/{vid}/map?limit=` (1–2000, default 1000) returns `parked`, `charges`, `trips`, `places`, `limit`,
`current` and `tariff`. Parked clusters carry `place_id`; charges and trips carry their geofence ids. The map page asks
for 1000; **Show all** asks for 2000, each layer newest first. `mapView({...})` draws one circle per place, and only a
circle with an `id` is clickable — the legacy ownerless `circle` stays passive. Focusing an item in the list paints
only that item's place circle (none when it has no place); **Show everything** restores all of them. Pins cluster by
default through leaflet.markercluster 1.5.3 (cdnjs, SRI): markers are drawn immediately, the cluster group replaces
them only once the plugin loads, and a failed load leaves the plain pins in place. Markers with `noCluster` (trip
endpoints) or `draggable` stay in a separate plain layer above the clusters. Circles and lines sit in their own layer
under the clusters.

## Activity, parked loss and data quality
The route `#/events` is the **Activity** page (`pages/events.js`) with two tabs: **Timeline** (`GET /timeline`, local
days, `tz_offset`) and **List** (the event log, which also records quality fixes and reviews). Parked loss (`GET
/parked-loss`) feeds the **Parked** tab of Statistics and the parked card on Overview, which fails soft. The **Data
quality** card lives on `#/system` (`pages/system.js`, `GET /quality`, `POST /quality/fix` and `/quality/review`).
`lib/quality.js` also holds `sampleNode`, the translated line for one finding. `lib/ui.js` `modal(title, body,
actions, { onClose })` calls `onClose` once however the dialog closes, and `confirmDialog` resolves `false` on Escape,
a scrim click and Cancel (only the topmost dialog reacts to Escape). All logic is backend work in `activity.py` and
`quality.py`; a page only renders what it gets. What the numbers mean, the fixes and the review rules are in
[ACTIVITY.md](ACTIVITY.md).

Timeline details (`pages/events.js`): a precision note under the legend, a week line from `summary` above the days, and a
day line that adds climate, "not heard from", km and cost (prefixed "at least" when `cost_partial`) only when non-zero.
`lib/dates.js` holds the pure helpers: `dayStartMs` and `barBox` position bars in the server's day (`tz_offset`, never
the browser's midnight, so a DST week is stable) and `monthsAgo` clamps a month step to the month's last day. Only drive
and charge bars with a record are buttons; `tl-estimated` dims estimated intervals. The previous-week button stops at
today minus 30. Statistics keeps its tab bar in loading and error states, shares one period control between its tabs,
remembers the tab and the period in `sessionStorage` (wrapped in try/catch) and asks for `/stats` only on Overview.
`lib/floor.js` is the one place for the "below the detection floor" display (zero median or zero energy), used by the
Overview parked card and the Parked tab. The Overview card draws after the first page paint and again when the
parked-loss answer arrives; if every stand is flagged as an unrecorded charge it shows the quiet line with the count.
Its subtitle stays two translated fragments around the number, because `t()` takes a single argument.

## Quality bar
Mobile first (360 px), keyboard operable, visible focus, labels on inputs, colour never the only signal, respects
`prefers-reduced-motion`, light and dark via the CSS variables only (no hard-coded colours), empty/loading/error states
for every fetch, destructive actions confirmed. Look at `pages/overview.js` for the house style.

## Verifying without a browser
`scripts/dom-smoke` needs Node 26 (`.nvmrc`, `nvm use`) and one `npm ci`. `run.mjs` renders routes in jsdom against a
running server (see its header) and reports console errors, error banners and the rendered text. Use `FULL=1` to print
complete page text. It does not run Leaflet or layout, so also read your own code critically for layout and a11y.

## API (see `skoda_mate/routers/`, shapes in `tests/test_web.py`)
One module per area: `pages`, `auth`, `setup`, `mqtt`, `vehicles`, `trips`, `charges`, `reports`, `places`,
`settings`. They share `AppContext` (`context.py`, via `deps.ContextDep`) for auth, the current vehicle and derived
values.

`GET /api/vehicles` · `GET|PUT /api/settings` · `GET|PUT /api/settings/mqtt` · `POST /api/settings/mqtt/test` ·
`GET|POST /api/places` · `GET|PUT|DELETE /api/places/{id}` ·
`GET /api/vehicles/{id}/overview|capabilities|stats|battery|history|events|map|commands|raw|calls|diagnostics` ·
`GET /api/vehicles/{id}/trips|trips/{tid}|charges|charges/{cid}` · `POST …/refresh` · `POST …/command {name, params}` ·
`POST …/trips/merge` · `POST …/trips/{tid}/unmerge` · `POST …/import/trips` · `PATCH …/charges/{cid}` ·
`PUT /api/trips/{tid}/note` · `PUT /api/vehicles/{id}` (battery_kwh) · `POST …/home-here` ·
`GET …/export/{trips|charges|events|snapshots}.csv` · `GET /api/backup` · `POST /api/login|logout` ·
setup: `GET /api/setup/status`, `POST /api/setup/login|skoda|vehicles`, `DELETE /api/setup/skoda|vehicles/{vin}`,
`PUT /api/setup/spin`.
