# Skoda Mate – design (short)

**Intent:** self-hosted "TeslaMate for Skoda", derived from leapmotor-mate's architecture, using the
`myskoda` PyPI library (the cloud client behind homeassistant-myskoda) instead of the Home Assistant layer.

**Goals:** poll MySkoda cloud -> SQLite; detect charge sessions from state; import trips from cloud trip
statistics; web dashboard + JSON API; remote commands; Home Assistant via MQTT Discovery.
**Non-goals (v0):** leapmotor-specific features (SoH, wallbox, tariffs, i18n, maps), multi-user auth.
**Anti-goal:** copying leapmotor code that only makes sense for its cloud.

**Approaches considered:** (A) full port of 39k lines - rejected, mostly Leapmotor-specific;
(B) lean rewrite keeping the poller/recorder/web/mqtt split, pure logic separated from IO - chosen;
(C) just a HA add-on over the integration - rejected, no history store.
(All calls above are mine, made because the user's /goal opted out of questions.)

**Parts:** `schema` (sqlite) · `client` (myskoda wrapper -> normalised snapshot, commands) ·
`recorder` (charge detection, trip upsert, events) · `poller` (async loop, refresh on MQTT events) ·
`ha_mqtt` (discovery payloads) · `web` (FastAPI) · Docker.
**Python 3.13+** (myskoda requirement). Commands needing S-PIN (lock/unlock) read `SKODA_SPIN`.
