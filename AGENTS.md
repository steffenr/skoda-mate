# AGENTS.md

Škoda Mate: a self-hosted trip, charge and remote-control dashboard for Škoda cars, built on the official MyŠkoda Public API
(FastAPI + SQLite backend in `skoda_mate/`, vanilla ES-module frontend in `skoda_mate/static/`, no build step).

## Read before changing

- Any dashboard page or `static/lib/` code: [docs/DASHBOARD.md](docs/DASHBOARD.md) (shell contract, helpers, data facts).
- Anything visual (colour, type, spacing, components, motion, copy): [DESIGN.md](DESIGN.md).
- MQTT / Home Assistant: [docs/HOME-ASSISTANT.md](docs/HOME-ASSISTANT.md).
- Why the API shapes everything: `docs/superpowers/specs/2026-11-23-official-api-rewrite.md`.

## Commands

- Tests: `uv run --extra dev pytest -q` (in DDEV: `ddev test`). Keep the suite green; every fix gets a test.
- Lint and types, both gates: `uv run --extra dev ruff check` and `uv run --extra dev mypy` (37 source files).
- Demo server (fictional car, no account, no network):
  `DEMO=1 DB_PATH=<scratch>/demo.db uv run uvicorn --factory skoda_mate.web:app --port 8766` (add `DEMO_CARS=2` for two cars).
- Frontend checks, against a demo server, from `scripts/dom-smoke` (`npm install` once; Chromium at
  `/Applications/Chromium.app` or `CHROME=`):
  `BASE=http://localhost:8766 node browser_e2e.mjs` (phone fit + click-through), `node i18n_coverage.mjs`,
  `node a11y_axe.mjs http://localhost:8766`, `node a11y_contrast.mjs http://localhost:8766`.
- Contract check against Škoda's OpenAPI: `.venv/bin/python scripts/check_contract.py`.
- CI (`.github/workflows/ci.yml`) runs the same four things: `test` (ruff, mypy, pytest with coverage), `frontend`
  (jsdom unit checks and `i18n_coverage.mjs`), `browser` (demo server plus `run.mjs`, `browser_e2e.mjs`, axe and
  contrast). The a11y scripts report rather than gate; keep their output in the artifacts worth reading.

## Rules

- **Official API only.** Talk to `public.api.connect.skoda-auto.cz` through `client.py`; offer only operations in its
  `OPERATIONS` contract (no lock/unlock, honk or wake-up exists). The myskoda library is end-of-life.
- **Request budget.** Škoda allows ~20 requests per hour per car. Every new call goes through the poller's budget
  (`budget.py`); tests use `FakeApi` and fixtures shaped like the OpenAPI schema, never the network.
- **Secrets** (API key, S-PIN, MQTT password) are stored encrypted with `SecretBox`, and the dashboard password only as a
  hash. Logins come from the setup form; keep them out of environment variables, logs and API responses.
- **Security headers stay strict.** Pages load code only from `/static` (no inline `<script>`), and the DOM is built with
  `h()` (text nodes). The headers live in `middleware.py`; a new external host (CDN, image, tiles) goes into `CSP` there,
  together with a test in `tests/test_auth.py`; CDN files carry SRI hashes.
- **Backend layout.** `web.py` only wires the app; endpoints are one module per area under `routers/` and take
  `ContextDep` (`context.AppContext`). Shared shaping of API responses belongs in `presenters.py`, the Škoda/MQTT
  lifecycle in `cloud.py`. Do not put endpoints back into `web.py`.
- **MQTT commands** stay opt-in and allowlisted; starting the auxiliary heater (S-PIN) stays dashboard-only.
- **Translations.** Every visible frontend string is `t('English')` with a German entry; backend messages shown to users
  get their German entry in `static/de_backend.js`, keyed by the exact English text. Nav labels are `label:` entries in
  the `PAGES` table (`static/app.js`); `i18n_coverage.mjs` checks those too. Setup and login are English-only on purpose
  (they render before the session and the language setting exist).
- **Routes.** One table, `PAGES` in `static/app.js`: a page is one entry plus `static/pages/<name>.js`. Sidebar, router,
  nav highlight and preloading all derive from it, so never add a second list.
- **Docs in sync.** README for env vars, setup and security; `docs/HOME-ASSISTANT.md` for entities and topics;
  `docs/FEATURE-PARITY.md` when a feature lands or is ruled out; `docs/UNRAID.md` plus `unraid/` when the port, the data
  path or an environment variable changes (template and compose file mirror the image). The published image name
  (`steffenr/skoda-mate`) and its tags live in README, `docker-compose.yml`, `unraid/` and `docs/UNRAID.md`; change them
  everywhere at once.
- **Real data.** `data/` holds the live database and `secret.key`. Run demos and experiments on a scratch database.
- **License.** AGPL-3.0-only, copyright Steffen Rühlmann. Keep `LICENSE` verbatim and the leapmotor-mate / Silvio Bressani
  attribution in the README (inspiration only, no shared code).
