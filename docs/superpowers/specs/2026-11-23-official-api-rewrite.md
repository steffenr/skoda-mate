# Rewrite onto the official MyŠkoda Public API

**Why:** the `myskoda` library (private API, behind homeassistant-myskoda) is EOL. The official contract is at
https://public.api.connect.skoda-auto.cz/docs (OpenAPI: `/v3/api-docs`, v1.1.0). Everything built on `myskoda` is replaced.

## What the official API is
- **Auth:** `X-API-Key` header. Key created in the MyŠkoda app (expires; `X-API-Key-Expires-At` on every response), bound to
  the VINs chosen at creation. There is **no vehicle list**: the user enters VIN(s). No e-mail/password anywhere.
- **Read:** one call, `GET /api/v1/vehicles/{vin}[?include=…]`, returns info (name, plate, render URL), status (doors,
  windows, lights, lock), fuelStatus, odometer, parkingPosition (state PARKED/IN_MOTION + coordinates only when parked),
  airConditioning, auxiliaryHeating, activeVentilation, charging (status + settings), chargingProfiles, operations
  (what the car supports) and `errors` (omitted parts). Fetching everything costs the same single request as one part.
- **Commands (HTTP 202):** start/stop charging · set charging limit · set charge mode · update charging profile ·
  start/stop air conditioning · start/stop auxiliary heating (needs the S-PIN) · start/stop active ventilation.
- **Limits:** 20 requests/hour/VIN; `RateLimit-Limit/Remaining/Reset` headers are authoritative; 429 + `Retry-After`.
  Errors are RFC 9457 problem+json. **Personal use only.**

## Consequences
| leapmotor-mate feature | Skoda-mate |
|---|---|
| Overview, car picture (`renderUrl`), lock/doors/windows/lights | yes (read-only; **no lock/unlock**) |
| Charge control, limit, mode, profiles | yes (all official commands) |
| Climate / aux heating / ventilation start-stop | yes (no seat/steering heating, no timers) |
| Trips, trip statistics | **derived by Mate** from odometer + PARKED/IN_MOTION snapshots (no route line, times ±poll interval) |
| Charges, charging curve, cost | **derived** from charging state + `chargePowerInKw` integration |
| Battery health | **estimate** (needs battery capacity: not in the API, set in Settings) |
| Outside temperature, maintenance, warnings, OTA, driving score, honk, wake-up, history import, push events | **not available** (shown honestly on a card) |

## Design
- One poll = one request (all parts). Adaptive interval (active 5 min / idle 20 min, user-tunable), never beyond the
  rate-limit headers; 4 slots reserved for commands; "Refresh now" costs one request.
- Keep: recorder (snapshots → events, charges, trips), SQLite, FastAPI, first-run setup + dashboard login, ddev, HA MQTT.
- Setup form asks for: API key, VIN(s), optional S-PIN (aux heating only). Stored encrypted.
- Dashboard: SPA with the capability-gated pages above; every number says whether it is measured or derived.
