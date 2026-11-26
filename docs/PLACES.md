# Places, prices and the map

A place is a named circle on the map: home, work, or anywhere else the car stops. Mate links the trips that end there
and the charges that happen there, so a place page can answer how often the car stands there, how long it stays, how
much energy it takes and what that costs.

Places are stored in Mate's local SQLite database. Naming a place, editing its radius or changing its price never asks
Škoda for anything; the request budget stays the same.

## What a place holds

| Field | Meaning |
|---|---|
| Name | 1 to 60 characters, shown in lists and on the map. The default home is stored as "Home" and shown as "Zuhause" in German. |
| Kind | Home, Work or Place. The kind groups and labels a place; matching treats them alike. |
| Position | Latitude and longitude of the centre, picked on the map or taken from the car's parking position. |
| Radius | 20 to 5000 metres, default 150. The circle drawn on the map is the area the place covers. |
| Colour | One of six palette colours, or the default. It tints the map circle (default accent) and the list dot (default muted). |
| Prices | Price per kWh, price per minute and a session fee, or Free. All optional; see below. |

Places belong to the installation, not to one car: every car in the household matches against the same places. Visit
and charge counts on a place therefore include all cars.

## Adding, editing and deleting

The **Places** page has one map and two lists. It says what the map does: "Click a circle on the map to edit its
place. Click an empty spot to add a place."

- **Add place** uses the car's current parking position when it is parked and reported. While driving or without a
  reported position, Mate asks you to pick the point on the map instead ("The car is not parked. Click the map to
  choose a place.").
- **Clicking an empty spot** on the map opens the same form at that point. In the form, **Pick on the map** closes it
  for the next click and keeps every field you already typed.
- **Detected places** lists parking spots that no place covers yet (grouped within about 100 m). **Name this place**
  opens the form at that spot.
- **Edit** on a row, or a click on a place circle, opens the stored place.

The form holds name, kind, radius, colour, position, the three prices and **Free**. It enforces two rules: "A home
place keeps its kind.", and a free place cannot have a price ("A free place cannot have a price." appears while
**Free** is checked).

Deleting a place asks "Delete this place?" and explains that trips and charges at this place lose their link and that
this cannot be undone. The trips, charges and visits themselves are not deleted. The home place cannot be deleted or
changed to another kind, but its position, name, radius, colour and prices can change.

## One home place

There is exactly one place of kind Home, enforced by the database. It is the place the Prices page points to and the
one whose kind marks a charge as home.

- An older database that still has home coordinates under Prices gets the Home place on the first start after the
  update, with the old radius clamped to 20–5000 m. Home coordinates sent by older clients still move it.
- The home place can be renamed, moved and resized, but not changed to another kind and not deleted.
- **Prices → Home place** shows the home place with its radius and visits, and offers **Edit home place** and **Use
  current parking position**. The second button moves the home centre to where the car is parked now and keeps the
  radius; it needs a parked car with a reported position.
- Saving the prices themselves never moves the home place.
- A new installation has no home place until one is created: **Prices → Home place → Add home place**, or a place
  with kind Home on the Places page.

## How a trip or charge finds its place

Mate measures the distance from the trip endpoint or the charge position to the centre of every place and takes the
closest match within its radius:

- a point matches when its distance is **at most** the radius;
- if several circles overlap, the **smallest radius wins**, so a tight place inside a wide one takes the stop;
- two places with the same radius are decided by the lower id, so the result is stable;
- Home has no priority in matching: a smaller Work place inside the Home circle wins for a point inside both.

A trip has two independent matches, one for its start and one for its end. A charge has one, from its own position. A
point outside every circle gets no place; the trip endpoint or charge stays unlinked until a place covers it.

Matching runs when a place is created or edited, when Mate records, imports or merges a trip or charge, and once at
every start. Creating or editing a place **recomputes every existing trip and charge**, not only new rows, so old
history moves with it. Shrinking a radius can therefore unlink rows that used to be inside; enlarging it can pick up
older ones. Deleting a place clears its links instead of re-matching them, so a row another place also covers stays
unlinked until the next assignment. Nothing is re-matched when a page loads.

## Visits, days and totals

A **visit** is one arrival: a trip that ends inside the place. It lasts until the next trip of that car starts, or
until now while there is no later trip. The place page lists the visits with arrival, departure, duration and whether
the visit is "Open now" or "Closed", and sums their parked time.

Above the visits the place page shows:

| Figure | Meaning |
|---|---|
| Visits | Number of trip endings at the place, all cars. |
| Days | Distinct local days with such an arrival. |
| Parked time | Sum of the visit durations; an open visit counts to now. |
| Charged | Energy of every charge linked to the place. |
| Cost | Cost of every linked charge, calculated with the rules below. |

Each row on the Places page also shows **last seen**, the later of the latest arrival and the latest charge end. The
place detail's **Recent charges** lists the newest 100 charges at the place; **Charged** and **Cost** include all of
them, also charges older than the list. A value Mate cannot know stays unknown ("–") instead of appearing as 0.

## Prices at a place

A place sets its own rate as soon as it has any price or is marked **Free**:

- **Price per kWh** (0–10) multiplies the charge's energy.
- **Price per minute** (0–10) multiplies the charge's duration.
- **Session fee** (0–1000) is added once per charge.
- **Free** means a deliberate zero. A free place cannot carry a price.

So a charge at a place with 0.50 per kWh, 0.02 per minute and a 1.00 session fee, 20 kWh over 60 minutes, costs
20 × 0.50 + 60 × 0.02 + 1.00 = 12.20. If a needed value is missing, the cost is unknown, not zero: a per-kWh price
with no energy, or a per-minute price with no duration, gives no number. A session fee alone still costs the fee.

A place's rate applies to charges at that place. Trip costs continue to use the home price from **Prices**.

## How Mate prices a charge

One order, explicit choices first:

1. **A manual total on the charge** wins over everything ("Cost entered by you. It replaces the calculation.").
2. **The rate of the matched place**, if it sets one (any price field or Free).
3. **Your home or public prices** from the **Prices** page:
   - a **Home** or **Public** choice on the charge decides which one applies;
   - otherwise the kind of the matched place decides: Home uses the home price, Work and Place use public AC or DC;
   - without a place, DC uses the public DC price; AC uses the home price near the saved home position and the public
     AC price otherwise, and with no saved home position it uses the home price as a flagged guess.
4. **A missing value** makes the result unknown rather than zero: no energy under a per-kWh price, no duration under
   a per-minute price, or no energy for a tariff ("No cost: the delivered energy is unknown."). A free place or a
   session fee alone still gives a number.

A Home/Public choice on a charge classifies it; it does not override a rate set on the matched place. The charge page
shows the basis in plain words ("Cost uses the price of this place.", "Calculated: delivered energy × your price",
"Cost is a guess: the place is unknown, so the home price was used."), and a guessed cost is marked with ≈ in lists.

## The map

The **Map** page draws every place as a filled circle in its colour and names the places its parked pins belong to,
with visits, days and last seen. A click on a circle opens that place. Detected clusters without a place keep their
reading count, which measures parking time rather than visits.

Crowded maps cluster their pins:

- pins group into numbered badges and split apart as you zoom in; the plugin is pinned to 1.5.3 from cdnjs with
  integrity hashes;
- trip start and end pins and dragged pins stay outside the clusters, so a start/end pair remains readable;
- if the clustering file cannot load, the map shows plain pins instead; it never goes blank;
- clustering is a browser enhancement: it adds no request to Mate's API and no Škoda request.

By default the map loads the **newest 1000** rows per layer (parked spots, charges, trip start/end). When a layer
reaches that cap, the page says "Showing only the newest 1000 per layer." and offers **Show all**, which raises the
cap to **2000** and, if a layer still fills it, notes "Showing the newest 2000 per layer.". The server accepts a limit
from 1 to 2000.
Layers are drawn from the local database; map tiles come from OpenStreetMap, with Leaflet 1.9.4 also loaded from
cdnjs.

## Local-only data flow

- Places, links, visits and computed costs are local SQL. No place feature calls Škoda, MQTT or another service, so
  the request budget is unchanged.
- Geofences and prices are never sent to Škoda. The car API only receives the normal read requests and the commands
  you trigger.
- A map is the one place where the browser talks to the outside world: Leaflet and the clustering plugin come from
  cdnjs, and map tiles come from OpenStreetMap. These requests reveal your IP address and the map area you are looking
  at, not place names, prices or visit history. No map, no such request.
- "Show my position" uses the browser's geolocation; the position stays in the browser.
- Like every other setting, places are in the SQLite database, so a database backup includes them.

See also: [the dashboard developer guide](DASHBOARD.md) for the API and page contract.
