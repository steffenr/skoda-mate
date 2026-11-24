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
- Demo server (fictional car, no account, no network):
  `DEMO=1 DB_PATH=<scratch>/demo.db uv run uvicorn --factory skoda_mate.web:app --port 8766` (add `DEMO_CARS=2` for two cars).
- Frontend checks, against a demo server, from `scripts/dom-smoke` (`npm install` once; Chromium at
  `/Applications/Chromium.app` or `CHROME=`):
  `BASE=http://localhost:8766 node browser_e2e.mjs` (phone fit + click-through), `node i18n_coverage.mjs`,
  `node a11y_axe.mjs http://localhost:8766`, `node a11y_contrast.mjs http://localhost:8766`.
- Contract check against Škoda's OpenAPI: `.venv/bin/python scripts/check_contract.py`.

## Rules

- **Official API only.** Talk to `public.api.connect.skoda-auto.cz` through `client.py`; offer only operations in its
  `OPERATIONS` contract (no lock/unlock, honk or wake-up exists). The myskoda library is end-of-life.
- **Request budget.** Škoda allows ~20 requests per hour per car. Every new call goes through the poller's budget
  (`budget.py`); tests use `FakeApi` and fixtures shaped like the OpenAPI schema, never the network.
- **Secrets** (API key, S-PIN, MQTT password) are stored encrypted with `SecretBox`, and the dashboard password only as a
  hash. Logins come from the setup form; keep them out of environment variables, logs and API responses.
- **Security headers stay strict.** Pages load code only from `/static` (no inline `<script>`), and the DOM is built with
  `h()` (text nodes). A new external host (CDN, image, tiles) is added to `CSP` in `web.py` together with a test in
  `tests/test_auth.py`; CDN files carry SRI hashes.
- **MQTT commands** stay opt-in and allowlisted; starting the auxiliary heater (S-PIN) stays dashboard-only.
- **Translations.** Every visible frontend string is `t('English')` with a German entry; backend messages shown to users
  get their German entry in `static/de_backend.js`, keyed by the exact English text.
- **Docs in sync.** README for env vars, setup and security; `docs/HOME-ASSISTANT.md` for entities and topics;
  `docs/FEATURE-PARITY.md` when a feature lands or is ruled out.
- **Real data.** `data/` holds the live database and `secret.key`. Run demos and experiments on a scratch database.
- **License.** AGPL-3.0-only, copyright Steffen Rühlmann. Keep `LICENSE` verbatim and the leapmotor-mate / Silvio Bressani
  attribution in the README (inspiration only, no shared code).
