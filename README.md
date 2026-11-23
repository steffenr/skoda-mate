# Škoda Mate

Self-hosted trip tracking, charge logging and remote control for Škoda cars: *TeslaMate for Škoda*, inspired by
[leapmotor-mate](../leapmotor-mate). It runs on Škoda's **official public API** (`public.api.connect.skoda-auto.cz`),
signs in with an **API key** you create in the MyŠkoda app (no e-mail or password of your Škoda account), and keeps the
history in a local SQLite database.

> **Personal use only.** Škoda licenses the public API for private use; it must not be used for commercial services.

## What it does

| Page | Content |
|---|---|
| **Overview** | Car picture (Škoda's render), battery, range, charging state, doors/windows/lock, climate, position, last trip and charge, 48 h battery chart |
| **Trips** | Derived trips with day/month views, search, map, notes, cost, CSV export |
| **Charges** | Detected sessions: energy, AC/DC, Home vs Public, charging curve, cost (your prices or manual), CSV export |
| **Prices** | What a kWh costs at home, on public AC and public DC, plus your home place on a map; one save bar, costs recalculate everywhere |
| **Battery** | SoC history, charging settings and profiles, capacity *estimate* from charges |
| **Control** | Start/stop charging, charge limit and mode, edit charging profiles, climate, auxiliary heater, ventilation |
| **Statistics** | Monthly distance, energy, cost and consumption |
| **Map · Events** | Where the car stood and charged; everything that happened, including every command |
| **Settings · System** | Units, language, battery capacity, polling, API-key status; request budget, data parts, raw data, redacted diagnostics |

Also: Home Assistant via MQTT Discovery, JSON API, CSV export, database backup, a **demo mode**, English and German.

## What the official API can and cannot do (read this)

The API offers **one live reading per request** and a short list of commands. There is **no history**. So:

- **Trips and charges are derived by Mate** from its own readings: a trip from the odometer and the *parked/driving* state,
  a charge from the charging state and the reported power. Times are accurate to the poll interval, very short trips can
  only be found through an odometer jump (marked **≈**), and there is no route line, because the position is not reported
  while driving.
- **Quota: about 20 requests per hour per car.** Mate reads the car every 20 minutes when parked and every 5 minutes while
  charging, climatising or driving (tunable in Settings, never faster than Škoda allows) and keeps 4 requests free for
  commands and the *Refresh now* button. The server's `RateLimit-*` headers are authoritative.
- **Not available**, and therefore not in Mate: lock/unlock, honk/flash, wake-up, outside temperature, maintenance and
  warning lights, battery health (an estimate is shown instead), push updates, sending a destination to the car.
- **Battery capacity** is not reported: enter it in Settings to get energy, consumption and costs.
- **Costs** come from the prices you set under Prices; they are estimates unless you type the real total for a charge.
- The API key **expires**; Mate shows the date and warns two weeks before.

## Run

### Try it first (no account needed)
```bash
uv venv --python 3.13 && uv pip install -e '.[dev]'
DEMO=1 DB_PATH=/tmp/demo.db .venv/bin/uvicorn --factory skoda_mate.web:app
```
Open http://localhost:8000: a fictional Enyaq with 60 days of history.

### With DDEV (recommended)
```bash
ddev start      # first start builds uv + Python 3.13, ~1 min
ddev launch     # https://skoda-mate.ddev.site -> the setup form opens
```
`ddev test` runs the tests, `ddev logs` shows the app log. Data lives in `./data/` (SQLite + `secret.key`).

### With Docker
```bash
docker compose up -d     # http://localhost:8080 -> the setup form opens
```
The app in the container runs as an unprivileged user (uid 10001), with dependency versions pinned by `uv.lock`. On start
the container makes `./data` writable for that user (`chown` to 10001), so a `./data` folder from an older, root-run
version keeps working without manual steps; new database files are created mode 0600. On a volume where `chown` is not
allowed (some NAS/NFS shares), run `sudo chown -R 10001:10001 ./data` once on the host, or set `user: "10001:10001"` in
`docker-compose.yml`. For commands inside the container, add `-u 10001`
(e.g. `docker compose exec -u 10001 skoda-mate python -m skoda_mate reset-password`) so no root-owned files end up in `data/`.

### First-run setup (in the browser, no secrets in environment variables)
1. **Dashboard login:** choose an e-mail and password (8+ characters). Stored as a salted PBKDF2 hash.
2. **API key:** in the MyŠkoda app create an API key for your car ([go.skoda.eu/api-keys](https://go.skoda.eu/api-keys)),
   paste it with your VIN(s). Mate tests it against Škoda immediately and stores it only if it works. Optional: the 4-digit
   S-PIN, needed only to start the auxiliary heater.

The key and the S-PIN are encrypted with a per-install key in `data/secret.key` (mode 0600); a copy of the database alone is
useless, but **back up and protect `data/` as a whole**. Until step 1 is done, nothing but the setup form is reachable;
from outside your home network it also asks for a one-time **setup code** (see [Security](#security)). Scripts can send
`Authorization: Bearer $API_TOKEN` if you set the optional `API_TOKEN` variable.

### Forgot the dashboard password?
Reset it on the command line, where the data lives. The password is asked for twice at a hidden prompt (never as an argument, so it stays out of your shell history). The running app notices at once and signs every old session out; no restart.

```
ddev exec uv run --python 3.13 python -m skoda_mate reset-password          # DDEV
docker compose exec -u 10001 skoda-mate python -m skoda_mate reset-password # Docker
.venv/bin/python -m skoda_mate reset-password                               # local (set DB_PATH like the app)
```

The sign-in e-mail stays as it is. Add `--email you@example.com` to change it, or to create the login if there is none yet. The Škoda API key is not affected.

### Optional environment variables
`DB_PATH`, `COOKIE_SECURE`, `API_TOKEN`, `SETUP_CODE`, `DEMO`, and for Home Assistant `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`,
`MQTT_PASSWORD`, `MQTT_PREFIX`. Logins and keys are never read from the environment.

### Security
- **First run / setup code.** Before a login exists, only the setup form and its two API calls are reachable. From
  this machine or a private address (127/8, 10/8, 172.16/12, 192.168/16, link-local, IPv6 ULA) the login can be created
  right away. From a public address, or through a proxy that forwards a public client (`X-Forwarded-For`), the form
  also asks for a one-time setup code. Mate logs it at start (`docker compose logs skoda-mate`, `ddev logs`) and writes
  it to `setup-code.txt` next to the database (mode 0600; deleted once the login exists). Set `SETUP_CODE=...` to choose
  the code yourself; then no file is written. Alternative: create the login on the command line with
  `python -m skoda_mate reset-password --email you@example.com` (see above).
- **Keep the data folder private.** Do not put `data/` (database, `secret.key`, and `setup-code.txt` during the first
  run) on a network share (SMB/NFS on a NAS that other household users or devices can open) or in a widely readable
  backup location: whoever can read that folder can read the setup code and decrypt the stored Škoda API key and S-PIN.
  Use a private folder only the container uses, and set `SETUP_CODE` if no code file should be written at all.
- **Changing the login** needs the current password, even in a signed-in browser.
- **Signing out signs out every browser and device** (sessions are signed tokens; signing out changes their key).
  Changing the password does the same.
- **Brute force:** 5 wrong passwords or setup codes per address in 5 minutes, and 30 across all addresses, give
  "too many attempts" for 5 minutes. Requests larger than 64 KB are refused before sign-in (12 MB after).
- **HTTPS:** whenever Mate is reachable from beyond your home LAN, put it behind HTTPS (a TLS proxy such as Caddy,
  nginx or Traefik, or the DDEV site). The session cookie gets the `Secure` flag automatically when the proxy sends
  `X-Forwarded-Proto: https`; `COOKIE_SECURE=true` forces it.
- **Behind a reverse proxy**, start uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy ip>` so the brute-force
  limit and the setup-code check see the real client address. Never use `--forwarded-allow-ips='*'`: anyone could then
  pretend to be any address.
- `/health` answers `{"ok": true}` to everyone (for Docker's health check); version and error details only with a
  session or the API token. Every response carries a Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff` and
  `Referrer-Policy: strict-origin-when-cross-origin` (other sites see only Mate's address, never a page path;
  OpenStreetMap's tile servers refuse requests without it).

## Several cars
One installation tracks **up to 5 cars** with one API key (the key must cover all of them: choose all cars when you create it in the MyŠkoda app). Enter the VINs on the setup page, or add and remove cars later under Settings. Each car has its own data, request quota (Škoda counts per car) and battery capacity. As soon as there are two or more, a car switcher appears in the header. Try it without a car: `DEMO=1 DEMO_CARS=2`.

## Home Assistant
Set it up in the dashboard under **Settings → MQTT → Home Assistant**: broker address, port, user and password (stored encrypted), a **Test connection** button and a live status, no restart. Mate then creates a device for each car in Home Assistant through MQTT discovery, with about 40 entities: battery, range, charging, odometer, doors and windows, a map position, Mate's own last trip and last charge values. Control buttons and a charge-limit slider are opt-in: tick **Allow commands from Home Assistant** under Settings → MQTT (starting the auxiliary heater is not available via MQTT). There is deliberately no lock entity: the API cannot lock or unlock.

**Step-by-step instructions, entity list, dashboard and automation examples, troubleshooting: [docs/HOME-ASSISTANT.md](docs/HOME-ASSISTANT.md).**

The `MQTT_*` environment variables still work as a fallback for existing installs; settings saved in the dashboard replace them. Running Mate in Docker or DDEV? Use Home Assistant's IP address as the broker, not `localhost`.

## Development
- Backend: Python 3.12+, FastAPI, httpx, SQLite. `pytest` runs ~235 tests against fixtures shaped like the official OpenAPI schema.
- Frontend: vanilla ES modules, no build step, see [docs/DASHBOARD.md](docs/DASHBOARD.md); the visual design system is in [DESIGN.md](DESIGN.md).
- Working with an AI coding agent: [AGENTS.md](AGENTS.md) lists the commands, checks and project rules.
- `scripts/dom-smoke` renders every dashboard page in jsdom against a running (demo) server.
- `scripts/dom-smoke/a11y_axe.mjs` and `a11y_contrast.mjs` are the accessibility checks (WCAG 2.2 AA with axe-core, and the real contrast ratio of every text element, light and dark). Run them against a demo server after UI changes.
- Feature comparison with leapmotor-mate: [docs/FEATURE-PARITY.md](docs/FEATURE-PARITY.md)
- Design notes: [docs/superpowers/specs](docs/superpowers/specs).
