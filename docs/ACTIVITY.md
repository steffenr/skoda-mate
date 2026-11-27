# Activity, parked loss and data quality

Three views answer "what did the car do, what did it cost me while parked, and can I trust the numbers":

| View | Where | Source |
|---|---|---|
| Activity timeline | **Activity** page, tab **Timeline** (the **List** tab is the event log) | `skoda_mate/activity.py`, `GET /api/vehicles/{vid}/timeline` |
| Parked loss | **Statistics** tab **Parked**, and the parked card on **Overview** | `skoda_mate/activity.py`, `GET /api/vehicles/{vid}/parked-loss` |
| Data quality | **System** page, **Data quality** card | `skoda_mate/quality.py`, `/api/vehicles/{vid}/quality` |

All three read what Mate already stored. None of them asks Škoda for anything, so the request budget stays the same.

## The timeline

Each day shows one bar of non-overlapping intervals: drive, charge, climate (climate, auxiliary heater and ventilation
together), parked and unknown. Unknown is time with no reading for more than 6 hours; Mate never calls it parked.

**Precedence.** The readings give the base. Charges are laid over them, then trips. Where two claim the same time, a
drive wins over a charge, and a charge wins over anything the readings say. Within a reading the order is drive,
charge, climate, auxiliary heater, ventilation, parked.

**Day line.** Distance and energy belong to the day a trip or charge **started**. A charge that starts at 22:00 shows
its kWh and cost on that day; the next morning shows the charging time but no energy. A day without a charge leaves the
energy out instead of printing "0.0 kWh". A charge without an amount keeps the cost marked as partial.

The line always shows driving time and parked time, plus charged energy (or the charging time). It adds climate time,
"not heard from" time, the distance and the cost only when they are not zero, so no part ever reads "0". A day whose
cost is only partly known (a charge is missing its amount) reads "at least" and the known sum. When that known sum is
zero, the day shows no cost part at all, since "at least 0.00" says nothing. A known cost that rounds to zero in the
currency (under half a cent, as `f.money` prints two decimals) reads "free", never "0.00"; an unknown cost leaves the
part out. One **week line** above the days sums the same parts from the endpoint's `summary`. Intervals marked
estimated are drawn dimmed, and "estimated" is in the bar's label, its tooltip and the text list.

**Bars and days.** A bar is placed inside its day by the day's own start and end, the local midnight the server cut
at from `tz_offset` (the request and the bars use one offset), not the browser's midnight. A week across a
daylight-saving change keeps every bar in place. The times in bar titles, labels and the text list are printed on that
same axis (`clockAt` in `lib/dates.js`, in the app language; a non-finite offset prints a dash), so a time after the
change matches its bar. Only a drive or charge with a record is a button; the other bars are plain labelled
elements. The week buttons walk back until the oldest reachable day, today minus 30 (the last step is shorter), and the
view that shows the current week follows "today" past midnight.

**Precision.** Mate sees the car only when it polls (every 20 minutes parked, about every 5 while driving, charging or
climatising). Interval boundaries are therefore accurate to the poll interval, and a drive shorter than that can fall
between two readings. Intervals whose end was guessed are marked as estimated. A day's minutes are rounded from the
interval boundaries, so the buckets of a day always add up to the time covered, and the week total is the sum of the
rounded day values. The page says so under the legend: "Times are accurate to the poll interval."

**Open trips and charges.** A trip or charge that never ended is drawn up to the first reading that ends it: a parked
reading for a trip, a reading that is definitely not charging (known charge state, or unplugged) for a charge. Those
are the same readings **Close open trips** and **Close open charges** use. Without such a reading it runs to the last
reading so far (a drive in progress). The search for that reading stops at the end of the range shown. Either way the
end is marked as estimated.

## Parked loss

A parked stand is a run of readings with the car neither driving nor charging.

| Rule | Value |
|---|---|
| Minimum stand | 6 hours (the API accepts `min_hours` from 1 to 168) |
| Readings in one stand | no more than 1 hour apart, otherwise the stand ends |
| Loss | first level minus last level of the stand, in percentage points of the battery capacity (Settings) |
| Detection floor | Škoda reports whole percent. A stand with a drop of 0 is "below the detection floor" (one step is the capacity divided by 100), never a decimal loss |
| Unrecorded charge | a rise, or a drop of more than 20 points, is flagged "likely an unrecorded charge" and left out of every total |
| Overlaps | a stand that overlaps a recorded drive or charge is dropped, so a hole in the readings cannot inflate the loss |
| Cost | the loss in kWh at the place's price per kWh (a free place costs nothing), else the home or public price; never a per-minute price or a session fee |

Without a capacity, Mate shows the percentage drop but no kWh or cost. The totals use only valid stands.

The **Parked** tab asks only for parked loss (never for the statistics, so a failing statistics request does not touch
it) and the chosen tab is remembered per viewer for the session. A stand below the detection floor shows the sentence
once per table row, in the kWh column (its rate is a dash). It loads when you open it and when you change the period;
it does not reload every 30 seconds like the other views, because a stand only counts after six hours. A range that
ends before it starts, or a minimum stay of 0 or less, is refused. A stand below the detection floor has no cost, but
its cost basis (place, tariff) is still named like that of any other stand at the same place.

The **Parked** tab shows 50 stands a page, newest first, with **Newer** and **Older** buttons. The figures above the
table always cover the whole period. In the API, `limit` (1–200, default 50) and `offset` select the page of
`sessions`; `total` counts every stand in the period, and `aggregates` (with `flagged`, the likely unrecorded charges)
do not depend on the page.

## Data quality

The card runs a fixed list of checks over the last 30 days and says how many findings each has. Severity is shown as
**Important** or **Info**.

| Check | Severity | Fix |
|---|---|---|
| Trips never ended (open for over 24 h) | Important | Close open trips |
| Charges never ended (open for over 24 h) | Important | Close open charges |
| Duplicate trips (same start and distance, a different end) | Important | Merge duplicates |
| Reading gaps, odometer jumps | Important | none |
| Estimated charge ends, inferred charges, approximate trips, API errors (24 h), missing data sections | Info | none |

**Reading gaps** are two kinds of finding in one count: a gap of more than 6 hours between two readings, and the
**silence** since the newest reading when that is more than 6 hours ago (the car is quiet right now). A gap that began
before the 30-day window counts only when it ends inside the window. A reviewed silence stays reviewed until the car is
heard from again. Odometer jumps use the same window rule. **Missing data sections** leaves out a section the car never
reports (for example the charging section of a combustion car): the poll's part state says "unsupported" or "missing"
for it.

The API also returns a check for **stuck operations** (`visible: false`): nothing records remote operations through the
official API (it answers with a bodiless 202), so it cannot fire today and the card does not list it. Each check item
has a `visible` field (true except for that one) and a summary with the right singular or plural ("1 trip never ended").

The card skips every item with `visible: false` (rows, **Show all checks** and the header counts). A row with no
findings shows a muted "No findings" instead of a severity chip. When any check is reviewed, the header adds a neutral
"n reviewed" chip, so an all-clear card is never ambiguous.

Every sample (the examples under **Review**) carries `label` and `href` for other API clients plus structured fields
with a `kind`; the card builds each line from those fields in the user's language and falls back to `label` only for an
unknown kind:

| `kind` | Fields |
|---|---|
| `trip`, `charge` | `id`, `at` (and `href`) |
| `gap`, `silence` | `from`, `to`, `hours` |
| `odometer` | `from_km`, `to_km`, `at` |
| `api_error` | `endpoint`, `at` |
| `section` | `name` |

When a check has more findings than samples, the panel adds "and N more".

Estimated charges are information only: a guessed end is how most live charges close, so there is nothing to repair.

**Review** on a check lists its findings. **Fix** (offered for open trips, open charges and duplicate trips only) runs
one repair. The Review panel says what the repair does ("What Fix does"), and the confirmation repeats it and lists the
findings it changes:

| Fix | What changes |
|---|---|
| Close open trips | Each trip gets an end: the first reading after its start that shows the car parked, otherwise its last reading. The trip is marked approximate. |
| Close open charges | Each charge gets an end: the first reading after its start that shows the car no longer charging, otherwise its last charging reading. The end is marked estimated. |
| Merge duplicate trips | Each group becomes one trip: the oldest keeps its numbers and the notes of all copies; the copies leave the lists but are saved with it ("Undo merge" on the trip page restores them). |

Every repair is logged on the **List** tab of Activity as "Data fixed" with the
repair and the number of rows it changed (for example "Close open trips: 3 changed"); marking a check as reviewed, or
undoing that, is logged as "Data reviewed".

- **Exact copies go at every start.** Separately from this card, Mate's startup clean-up (`schema.dedupe_trips`)
  silently removes trips with an identical start **and** end. It keeps the lowest id and carries over a note found on a
  removed copy; it does not record the removed rows, so there is no "Undo merge" for them. The quality check and its Fix
  handle what is left: trips with the same start and distance but a different end.
- **Nothing is lost (the card's fixes).** Merging duplicates folds the extra rows into the kept trip's stored parts.
  **Undo merge** on the trip page restores them, and a re-import does not bring them back as new trips. The other fixes
  only end rows that never ended, the way the live recorder would have; they never delete a row. A closed trip is
  marked approximate, a closed charge as estimated.
- **Mark as reviewed** hides what you have looked at without changing any data. A reviewed check counts only findings
  **newer** than the review, so a new problem shows up again, and its **Fix** changes only those newer findings (the
  number the confirmation shows); the reviewed rows stay as they are. For missing data sections the review remembers
  the names; only a different missing section counts afterwards. **Undo** removes the review.

## Demo

`DEMO=1` seeds a week that shows all three: commutes and a night charge, a morning pre-heat (climate), hourly parked
readings with a standby drain of about 1 to 2 % a day, and one trip stored a second time ending one second later (an
exact copy would be removed by the startup clean-up), so that Data quality has an important finding to fix or mark as
reviewed. It stays across restarts of a saved demo database.
