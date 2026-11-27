"""Values Mate derives itself, published on MQTT next to the API's own.

They come from the same functions as the dashboard. What cannot be derived is None, never zero. The ones that scan the
history are kept for a while, so a publish on every poll does not read the whole database.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from . import activity, analytics, costs, places, quality, recorder, stats

_LOG = logging.getLogger(__name__)
CACHE_S = 900  # also dropped as soon as the car has a new event (a trip or charge ended, a plug moved, ...)
PARKED_DAYS = 7


class Values:
    def __init__(self, conn, clock: Callable[[], float] = time.monotonic,
                 utcnow: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.conn, self.clock, self.utcnow = conn, clock, utcnow
        self._cache: dict[int, tuple[int, float, dict]] = {}  # vehicle -> (newest event, computed at, values)

    def for_vin(self, vin: str) -> dict:
        row = self.conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
        if not row:
            return {}
        vid = row["id"]
        return {**self._last_trip(vid), **self._last_charge(vid), "place": self._place(vid), **self._history(vid)}

    def _last(self, table: str, vid: int) -> dict | None:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE vehicle_id=? AND ended_at IS NOT NULL "
                                "ORDER BY started_at DESC LIMIT 1", (vid,)).fetchone()
        return dict(row) if row else None

    def _last_trip(self, vid: int) -> dict:
        t = self._last("trips", vid) or {}
        km = t.get("distance_km")
        return {"last_trip_km": None if km is None else round(km, 1), "last_trip_kwh": t.get("energy_kwh"),
                "last_trip_consumption": t.get("avg_kwh_100km")}

    def _last_charge(self, vid: int) -> dict:
        c = self._last("charges", vid)
        if c is None:
            return {"last_charge_kwh": None, "last_charge_cost": None, "last_charge_place": None}
        place = places.get(self.conn, c["geofence_id"]) if c.get("geofence_id") else None
        cost = costs.charge_cost(c, costs.load_tariff(self.conn), place) or {}
        return {"last_charge_kwh": c.get("energy_kwh"), "last_charge_cost": cost.get("amount"),
                "last_charge_place": place["name"] if place else None}

    def _place(self, vid: int) -> str | None:
        """The named place the car stands in. While it drives, or without a position, that is unknown."""
        s = recorder.last_snapshot(self.conn, vid)
        if s is None or s["in_motion"]:
            return None
        place = places.match(self.conn, s["lat"], s["lon"])
        return place["name"] if place else None

    def _history(self, vid: int) -> dict:
        newest = self.conn.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE vehicle_id=?", (vid,)).fetchone()[0]
        cached = self._cache.get(vid)
        if cached is None or cached[0] != newest or self.clock() - cached[1] >= CACHE_S:
            values: dict = {}
            for compute in (self._parked_loss, self._capacity, self._range, self._quality):
                try:
                    values.update(compute(vid))
                except Exception:  # one value that cannot be worked out must not take the others with it
                    _LOG.exception("could not derive %s", compute.__name__)
            cached = self._cache[vid] = (newest, self.clock(), values)
        keys = ("parked_loss_7d_kwh", "parked_loss_7d_cost", "capacity_estimate_kwh", "range_at_100_km", "quality_issues")
        return {key: cached[2].get(key) for key in keys}

    def _parked_loss(self, vid: int) -> dict:
        now = self.utcnow()
        found = activity.parked_loss(self.conn, vid, (now - timedelta(days=PARKED_DAYS)).isoformat(), now.isoformat(),
                                     capacity_kwh=recorder.battery_kwh(self.conn, vid),
                                     tariff=costs.load_tariff(self.conn))["aggregates"]
        return {"parked_loss_7d_kwh": found["kwh"], "parked_loss_7d_cost": found["cost"]}

    def _capacity(self, vid: int) -> dict:
        return {"capacity_estimate_kwh": stats.battery(self.conn, vid)["estimate_kwh_at_wall"]}

    def _range(self, vid: int) -> dict:
        latest = analytics.projected_range(self.conn, vid)["latest"]
        return {"range_at_100_km": latest["range_km"] if latest else None}

    def _quality(self, vid: int) -> dict:
        """The number of checks on the data-quality card that have something open."""
        found = quality.checks(self.conn, vid, self.utcnow().isoformat(timespec="seconds"))
        return {"quality_issues": sum(1 for c in found if c["visible"] and c["count"])}
