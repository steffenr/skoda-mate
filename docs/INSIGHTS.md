# Insight: charging, driving and projected range

**Statistics → Charging** and **Statistics → Driving**, plus the **Projected range** card on the Battery page. Everything is
worked out from rows Mate already stored. Opening these views costs no request against Škoda's quota.

## Periods and time

The 6 and 12 month choices start on the first day of a month, so they line up with the monthly table on the Overview tab.
That table groups by UTC month, while the period starts at your local midnight, so a charge or trip in the first or last
hours of a month can fall on the other side of the line. Over **all**, the totals match. Only finished trips and charges
count.

Heatmaps use your local weekday and hour. A trip found only through an odometer jump (marked ≈) and an inferred or
imported charge have no measured start time, so they are left out of the heatmaps and counted below them.

## Charging

| Figure | What it is |
| --- | --- |
| Energy, cost | All charges, including inferred and imported ones. Cost follows the [price order](PLACES.md). |
| "at least" | Some charges in the sum have no known cost (usually unknown energy). They are not counted as zero. |
| Cost per kWh | Cost divided by energy, over charges where both are known. |
| Measured share | The share of the energy that Mate saw being charged. The rest was inferred or imported. |
| Average power | Energy divided by charging time, for measured charges with both. A charge whose end Mate had to estimate is left out. AC and DC are never mixed. |
| Peak power | The highest power read during a measured charge. With readings every few minutes the true peak can be higher. |
| Charge curve | The mean of the power readings in each 5 % step of charge level, AC and DC separately. A step with fewer than three readings is hidden. |
| Home, public, other | "Other" is a charge Mate cannot place: no home position yet and not DC. |
| Session fees | The session fees inside the cost, from places that charge one. A manual cost replaces them. |

A period with only inferred charges shows energy and cost, and no power or curve.

## Driving

- **Top destinations** use the name of the [place](PLACES.md) a trip ended in, else the address, else "Unknown place".
- **Trip lengths** are counted in the steps 0–5, 5–20, 20–50, 50–100 and 100 km or more.
- **Average duration** leaves out trips with estimated times.
- **Consumption trend** is the monthly consumption of the Overview tab.
- **Projected distance per year** is a projection: the odometer distance over the last 365 days of readings (or less),
  scaled to a year. It appears only after 60 days between the first and last reading, whatever period is selected.

There is no speed, route or elevation figure: Škoda's API reports none of them.

## Projected range

The question is "what range would 100 % give today, and is it drifting?" Mate takes the range the car reports and scales
it to a full battery (`range ÷ charge level × 100`). **This is not battery health.** The car's own range estimate reacts
to temperature, load and recent driving, none of which Mate knows.

- Readings need a charge level of at least 20 % and a positive range, and the result has to lie between 200 and 1000 km.
- Outliers: each reading is compared with the median of the readings within 15 days either side. It is kept when it is
  within three median absolute deviations (at least 1 % of that median counts as one deviation). The window moves with
  the date, so a cold winter is not thrown out for differing from summer. The card shows how many were left out.
- The value shown is the median of the latest day with readings.
- **Trend per year** is a straight-line fit through the daily medians. It needs 10 days with readings spread over at
  least 60 days. Over less than a year it mostly shows the season.
- **First to last 90 days** compares the medians of those two windows. It appears only when they do not overlap and each
  has readings on at least 20 days.

The **capacity estimate** is a separate card with a separate method (wall energy per 100 % from long AC charges). Mate
combines neither into a score.

## API

`GET /api/vehicles/{id}/insights/charging` and `…/insights/driving` take `from`, `to` (local `YYYY-MM-DD`, both optional)
and `tz_offset` (JavaScript's `getTimezoneOffset()`). `GET /api/vehicles/{id}/battery` includes `projected_range` and
takes `tz_offset`. All three need a session or the API token.
