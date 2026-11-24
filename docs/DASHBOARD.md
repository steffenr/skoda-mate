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
every 30 s and after Refresh), `setTitle()`. Routes: `''` overview · `trips` · `trips/:id` → `trip` · `charges` ·
`charges/:id` → `charge` · `battery` · `control` · `stats` · `map` · `events` · `settings` · `system`.

## Libraries (`static/lib/`)
`dom.js` h()/svg()/mount()/clear() — **no innerHTML, ever** (names, addresses and notes come from outside).
`ui.js` card, stat, chip, button, asyncButton, banner, empty, loading, field, seg, kv, socBar, table, modal,
confirmDialog, toast. `charts.js` lineChart (`gaps: [{from, to}]` shades stretches without data and draws no line across
them), barChart, sparkline. `mapview.js` mapView (Leaflet from CDN, offline fallback).
`car.js` carView. `icons.js` icon(name) (see ICON_NAMES). `format.js` km/mi aware formatters (`f.km`, `f.cons`, `f.kwh`,
`f.money`, `f.duration`, `f.dateTime`, `f.dayLabel`, `f.shortPlace`, …). `i18n.js` `t('English')`; add German with
`extendDE({...})` at the top of your page file. `style.css` holds tokens and components; page CSS goes in your own file.

## Quality bar
Mobile first (360 px), keyboard operable, visible focus, labels on inputs, colour never the only signal, respects
`prefers-reduced-motion`, light and dark via the CSS variables only (no hard-coded colours), empty/loading/error states
for every fetch, destructive actions confirmed. Look at `pages/overview.js` for the house style.

## Verifying without a browser
`scripts/dom-smoke/run.mjs` renders routes in jsdom against a running server (see its header) and reports console errors,
error banners and the rendered text. Use `FULL=1` to print complete page text. It does not run Leaflet or layout, so also
read your own code critically for layout and a11y.

## API (see `skoda_mate/api.py`, shapes in `tests/test_web.py`)
`GET /api/vehicles/{id}/overview|trips|trips/{tid}|charges|charges/{cid}|stats|battery|history|events|map|commands|raw|calls|diagnostics`
· `POST …/refresh` · `POST …/command {name, params}` · `PATCH …/charges/{cid}` · `PUT /api/trips/{tid}/note` ·
`GET|PUT /api/settings` · `PUT /api/vehicles/{id}` (battery_kwh) · `POST …/home-here` · `GET …/export/{trips|charges|events|snapshots}.csv` ·
`GET /api/backup` · setup: `GET /api/setup/status`, `PUT /api/setup/spin`, `DELETE /api/setup/skoda`.
