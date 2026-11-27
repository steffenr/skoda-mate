# Danish (da)

## Form of address

Informal "du", because it is what modern Danish consumer and car apps use; "De" would sound stiff and dated.

## Glossary

| English | Danish |
|---|---|
| trip | tur (pl. ture) |
| charge, charging session | opladning (pl. opladninger) |
| charging (activity; state of the car) | opladning (activity); "Lader" (state right now) |
| charge level, state of charge (SoC) | ladeniveau (SoC); "batteriniveau" only in the low-battery warning and event |
| charge limit, target charge | ladegrænse |
| charging profile | ladeprofil |
| charge mode | ladetilstand |
| range | rækkevidde; as the time period in chart controls: periode |
| odometer | kilometertæller (the value on it: kilometerstand) |
| consumption | forbrug |
| climate control, pre-conditioning | klimaanlæg (short: klima); klargøring (of the cabin) |
| auxiliary heater | parkeringsvarmer; the activity "auxiliary heating": parkeringsvarme |
| ventilation | ventilation |
| window heating | rudevarme |
| plug, cable | stik, kabel; plugged in: tilsluttet |
| battery care | batteripleje |
| place | sted; home place: hjemsted |
| home, public | hjemme, offentlig |
| parked loss | tab under parkering |
| reading | aflæsning |
| polling, request | aflæsning (polling), forespørgsel (request) |
| inferred, estimated, approximate | udledt, anslået, omtrentlig ("ca." on the short chip) |
| data quality, finding | datakvalitet, fund |
| webhook, delivery, event | webhook, levering, hændelse |
| API key, S-PIN | API-nøgle, S-PIN |
| dashboard login | dashboard-login |

Home Assistant menu paths and button names in the setup guide stay in English. Quoted labels from this app use the same Danish text as the label itself.

## Open questions

Most important first.

1. Home Assistant menu paths ("Settings → Devices & services …", "Start on boot", "Enable discovery") are left in English, because the exact Danish labels in Home Assistant were not verified. Should they follow Home Assistant's Danish interface?
2. "Timer" (a charging timer) is spelled like the Danish word for "hours" ("Timer"). The plural is "Timere", but the singular label and the heading "Hours" look the same. Is "Tidsplan" preferred for charging timers?
3. "Auxiliary heater" is "parkeringsvarmer". It covers fuel and electric heaters, but should be checked against the term in Škoda's Danish app and manuals.
4. "Polling" and "reading" are both "aflæsning" (settings card, status, interval). This is natural Danish, but loses the English distinction.
5. The quoted column "Odometer Δ" is rendered as "Kilometertæller Δ". The column head itself is not a separate catalog key, so confirm that it is built from the translated word "Odometer".
6. "Connected" is shared by the cable and the MQTT connection, so it is "Tilsluttet", and "Not connected" is "Ikke tilsluttet" also for the Škoda connection. Longer sentences about the Škoda or broker connection use "forbundet" or "forbindelse".
7. "Mate reads a parked car about every {n} minutes" uses the ordinal form "hvert {n}. minut" in both plural forms. It reads slightly oddly for 1. The sentence with {idle} and {active} assumes whole numbers.
8. "{ago}" and "{time}" are assumed to arrive as localised relative or duration text (for example "for 5 minutter siden"). Check the lines "Opdateret {ago}", "næste tjek om {time}" and "næste ledige om {time}" for a doubled "om".
9. "Session fee" is "Startgebyr", the usual Danish word for a fixed fee per charge. "Gebyr pr. opladning" is clearer but longer.
10. "Sessions" in parked-loss texts is "perioder" or "parkeringsperioder", and in charging texts "opladninger".
11. "Off" and "On" as values are "Fra" and "Til", which look the same as "From" and "To". "Slukket" and "Tændt" would not fit every place where they are used.
12. "Home" as a chip, place kind and filter is "Hjemme". As a kind of saved place, "Hjem" might read better, but the key is shared.
13. "Control" (navigation) is "Styring" and "Controls" (Home Assistant guide) is "Betjening".
14. "Capabilities" is "Funktioner". "Muligheder" is the alternative.
15. "This is where home is" is a button, rendered as "Her bor jeg".
16. "State" and "Status" are both "Status". "Mode" is "Tilstand", which also appears in "ladetilstand" and "Batteriets tilstand" (battery health).
17. "Plug in the car" is "Tilslut bilen". Check that it is not read as connecting the car to the app.
18. "Conserving" (battery care holding the level) is "Bevarer", and in the longer status "Holder niveauet (batteripleje)". Both are a little unusual.
19. "Wall energy" is rendered as "energi fra elnettet" (energy from the grid).
20. "Service, inspection" uses "service, syn". In Denmark "syn" means the statutory vehicle test, while a workshop inspection would be "eftersyn".
21. "TLS insecure" is "Usikker TLS". It is a technical checkbox that might be better left in English.
22. "Trunk opened" as a reported value is "Bagagerum åbent" (state), while the event is "Bagagerum åbnet".
23. "{n} Important" is a count of findings: "{n} vigtigt" or "{n} vigtige".
24. "24 h", "7 d" and "30 d" are kept as short chart buttons. Danish also writes "t" and "d" for hours and days, but "h" follows the unit list.
