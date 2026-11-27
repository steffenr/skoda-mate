# Feature parity with leapmotor-mate

Status per leapmotor-mate feature (from its README), checked against the official MyŠkoda API (contract 1.1.0, 12 operations).
**Done** = in Škoda Mate. **Adapted** = in Škoda Mate, but derived or estimated because the API gives no such data.
**Not possible** = the API offers nothing for it (verified against the live OpenAPI spec; `scripts/check_contract.py`).
**Not built** = possible with the data we have, deliberately left out so far.

| leapmotor-mate | Škoda Mate | Status |
|---|---|---|
| Overview: live status, battery, range, car picture, map | Overview with Škoda's render, battery, range, charging, doors/windows/lock, climate, position | Done |
| "Is the data fresh / trustworthy" indicator | Header shows when the car last reported and the next check; request budget chip; key-expiry and error banners | Done |
| Trips with route map, distance, energy, efficiency | Trips list/month view, detail with start/end map, cost, notes, search, CSV | Adapted (derived from odometer + parked/driving, or imported from the app's CSV; no route line, the API gives no position while driving) |
| Trip history from before the app started | CSV import with duplicate protection and export instructions | Done (the app seems to keep only ~7 months) |
| Consumption measured by the car | Imported trips carry the car's own kWh and kWh/100 km | Adapted |
| Elevation, outside temperature | – | Not possible (not in the API) |
| Calendar, search, filters | Month view, search, date range, min distance | Done |
| Trip merging | Merge with the next trip, undo, safe against re-imports | Done |
| Notes on trips and charges | Notes on both | Done |
| Drive mode / One-Pedal tags | – | Not possible |
| Events timeline | Activity page: event list with filters and every command logged, plus a day timeline of drive, charge, climate and parked time ([details](ACTIVITY.md)) | Done (times are accurate to the poll interval; unknown when readings are missing) |
| Vampire drain (parked loss) | Statistics, Parked tab and an Overview card: stands of 6 h or more, kWh per day, cost | Adapted (whole-percent readings: short stands fall below the detection floor; unrecorded charges are excluded) |
| Data-quality check | System card with severity, Fix for open trips, open charges and near-duplicate trips (the card's fixes lose nothing, "Undo merge" restores; the card explains each fix before it runs; exact start-and-end copies are removed by the startup clean-up), Mark as reviewed / Undo | Done (new) |
| Charges: AC/DC, energy, curve, cost | Charges list/detail, curve, cost (tariff or manual), Home vs Public | Adapted (measured when seen live, otherwise inferred from battery levels and clearly marked) |
| Recover missed charges | Automatic inference from trips and readings, runs at start and after imports | Done |
| Prices: flat / time-of-use / dynamic / custom | Flat home / public AC / public DC prices, manual cost per charge | Partly (no time-of-use or dynamic prices) |
| Battery health (SoH) | Capacity estimate from long AC charges | Adapted (Škoda reports no health value) |
| Charging-station names, find chargers | – | Not possible (not in the API) |
| Wallbox integration, V2L | – | Not possible |
| Home position | Home place on Prices: radius, visits, Use current parking position; edited on Places | Done |
| Named places with per-place prices and visit history | Places page and detail: name, kind, radius, colour, per-place prices; visits, days, parked time, energy and cost | Done (new) |
| Remote control: locks, windows, trunk, find car | – | Not possible (no lock/unlock/honk in the API) |
| Climate | Start/stop with temperature, without-external-power option | Done |
| Seat / steering-wheel heating | – | Not possible |
| Charging control | Start/stop, charge limit, charge mode, charging profiles editor | Done (beyond leapmotor-mate) |
| Auxiliary heater, ventilation | Both, with S-PIN | Done |
| Navigation: send destination | – | Not possible |
| Vehicle software update info | – | Not possible |
| Statistics (monthly, cost, consumption) | Statistics with odometer-based distance, coverage note and info popup | Done |
| Charging insight (power, curve, cost per kWh, where and when) | Statistics, Charging tab ([details](INSIGHTS.md#charging)) | Adapted (power and curve only from charges Mate measured) |
| Driving insight (destinations, trip lengths, consumption trend) | Statistics, Driving tab, with a yearly distance projection after 60 days ([details](INSIGHTS.md#driving)) | Adapted (no speed, route or elevation: the API reports none) |
| Range trend | Battery page, projected range at 100 % ([details](INSIGHTS.md#projected-range)) | Adapted (from the range the car reports; not battery health) |
| Home Assistant via MQTT | Discovery with ~40 entities (sensors, tracker, Mate's own trip and charge values; buttons and charge-limit slider opt-in via "Allow commands from Home Assistant", no aux-heater start); set up in the dashboard with connection test and live status, reconnects by itself | Done |
| Automation: MQTT field and event topics, webhooks | One retained topic per value, an event topic, and signed webhooks with retries and a delivery log under Settings → Automation ([details](WEBHOOKS.md)) | Done (events only for what Mate watched, not for inferred charges) |
| Settings: units, language, theme | km/mi, seventeen languages, light/dark/auto | Done |
| Login, setup wizard | First-run setup, dashboard login, encrypted API key | Done |
| Diagnostics bundle, raw data | System page, redacted download, raw viewer | Done |
| Backup / export | Database backup, CSV exports | Done |
| Demo mode | `DEMO=1` | Done |
| Languages | Seventeen: Catalan, Chinese (Simplified), Danish, Dutch, English, Finnish, French, German, Hungarian, Italian, Japanese, Korean, Norwegian, Spanish, Swedish, Turkish, Ukrainian (leapmotor-mate has 9) | Partly |
| Capabilities overview | Capabilities page: every operation and field, this car's support | Done (new) |

Trip merging (with undo, import-safe) was built later.

Deliberately not built:
- **Time-of-use / dynamic prices:** they need the real charging power over time. Charges Mate did not watch (the usual case) only have a time window, so such a price would be a guess shown as a number. Worth adding once most charges are measured live.
- **Native review for the new languages:** about 1,400 texts per language, where wrong translations look finished and mislead. The catalogs are complete and checked for placeholders and plurals, but this batch is machine-drafted; [TRANSLATIONS.md](TRANSLATIONS.md) tracks the review state until a speaker checks each language.
