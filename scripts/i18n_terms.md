# Terms and rules for translators

Škoda Mate is a self-hosted web dashboard for Škoda cars (electric, hybrid and combustion). It records trips and charging
from what Škoda's official programming interface reports, shows the car's state and can send a few remote commands.
**Mate** is the app's short name. It polls the car a limited number of times per hour; much of the text explains what
can and cannot be known because of that.

Choose one word in your language for each term, record it in your glossary, and use it everywhere.

| English | What it means here |
|---|---|
| trip | one journey by car, from start to parking |
| charge, charging session | one session of putting energy into the battery; "charge" the noun means this, never a fee |
| charging | the activity; as a state of the car ("is charging now") some languages need another word |
| charge level, state of charge (SoC) | how full the battery is, in percent |
| charge limit, target charge | the level at which charging stops |
| charging profile | settings the car applies at a saved charging location |
| charge mode | how the car decides when to charge (manually, on a timer, at preferred times) |
| range | how far the car can still drive; in a chart's controls "Range" is the time period shown |
| odometer | the car's total distance counter |
| consumption | energy used per 100 km |
| climate control, pre-conditioning | heating or cooling the cabin before driving |
| auxiliary heater | a separate heater (fuel or electric), which needs the S-PIN |
| ventilation | moving air through the cabin without heating or cooling |
| window heating | defrosting the front or rear window |
| plug, cable | the charging cable and its plug; "plugged in" means the cable is connected |
| battery care | a charging limit that is kinder to the battery |
| place | a spot the user saved (home, work, any other), with a radius; "home place" is the one marked as home |
| home, public | charging at the user's home place, or anywhere else |
| parked loss | battery energy lost while the car stood still |
| reading | one answer from the car: its state at that moment |
| polling, request | asking Škoda for a reading; Škoda allows about 20 requests per hour |
| inferred, estimated, approximate | worked out by Mate, not measured; keep these three apart |
| data quality, finding | checks over the recorded data, and what a check found |
| webhook, delivery, event | a message Mate sends to another system; one attempt to send it; what happened |
| API key, S-PIN | the secret from the MyŠkoda app; the 4-digit code of the car |
| dashboard login | the e-mail and password of this web page |

## Stays as it is

- Product names: Škoda, MyŠkoda, Mate, Home Assistant, Mosquitto, MQTT, Node-RED, n8n. They may be inflected the way
  your language inflects names, as long as the name stays recognisable.
- Home Assistant's own menu paths and button names (such as "Settings → Devices & services"): use your language's
  official Home Assistant labels only if you are sure of them; otherwise keep them in English and say so in your open
  questions.
- Units and abbreviations: km, mi, kWh, kW, h, min, s, %, °C, AC, DC, SoC, VIN (unless your language has its own usual
  abbreviation), TLS, URL, API, CSV, S-PIN.
- Machine text: MQTT topic paths such as `{prefix}/VIN/events`, settings such as `DEMO=1`, field names in quotes such as
  'auto_unlock', and API values in capitals such as PERMANENT or MONDAY.
- `{placeholders}`: same names, placed where your grammar needs them.

## Style

- Plain, short sentences that say what happened and what to do next. Buttons, tabs, chips and table heads as short as
  the English: they sit in narrow columns on a phone.
- Use your language's own quotation marks, punctuation and capitalisation rules.
- Pick the form of address (informal or formal) that a modern consumer app in your language would use, say why in your
  glossary, and keep it everywhere.
- A text that starts in lower case continues a line; keep it lower case unless your grammar requires a capital.
- The note and the code line are context. Never translate them into the result.
