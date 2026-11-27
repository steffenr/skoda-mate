"""Demo mode (DEMO=1): a believable Enyaq without any Škoda account, for trying the dashboard and for development.

`DemoApi` stands in for the HTTP client and answers in the exact shape of the official API; `seed()` writes ~60 days
of history through the same recorder the real poller uses, so every page has something to show. Nothing here talks
to the network.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from . import places, recorder, store
from .client import ApiResult, RateInfo

DEMO_VIN = "TMBDEMO0000000001"
DEMO_VIN2 = "TMBDEMO0000000002"  # second car, only with DEMO_CARS=2 (to try switching between cars)
SECOND: dict[str, Any] = {"name": "Demo Elroq", "plate": "F-DM 2027", "model": "Elroq 85", "soc": 42.0, "odo": 3120}
HOME = (50.1109, 8.6821, "Römerberg 1, 60311 Frankfurt am Main, Germany")
WORK = (50.0686, 8.2386, "Kaiser-Friedrich-Ring 5, 65185 Wiesbaden, Germany")
SHOP = (50.1213, 8.6564, "Zeil 90, 60313 Frankfurt am Main, Germany")
FAR = (49.8728, 8.6512, "Luisenplatz 5, 64283 Darmstadt, Germany")
PLACES = [WORK, SHOP, FAR]
# The real poller reads a parked car every 20 minutes (poller.DEFAULT_IDLE_S). The seed writes one parked reading per
# hour: no false reading gaps (quality, timeline) and unbroken parked runs (activity.RUN_GAP_H), at a third of the rows.
PARKED_EVERY = timedelta(hours=1)
# Standby loss of a parked car (12 V system, connectivity module), drawn per stand. The API reports whole percent, so
# short stands land below the detection floor and longer ones show a measurable loss, as on a real car.
PARKED_DRAIN_PCT_PER_DAY = (0.8, 2.0)


def vehicle_response(now: datetime, soc: float, charging: bool, parked_at=HOME, moving=False, odo=14820,
                     climate="OFF", target_soc=80, vin=DEMO_VIN, name="Demo Enyaq", plate="F-DM 2026") -> dict:
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state = "CHARGING" if charging else "READY_FOR_CHARGING"
    veh = {
        "vin": vin, "name": name, "licensePlate": plate,
        "status": {"overall": {"doorsLocked": "YES", "locked": "YES", "doors": "CLOSED", "windows": "CLOSED", "lights": "OFF",
                               "reliableLockStatus": "LOCKED"},
                   "detail": {"sunroof": "UNSUPPORTED", "trunk": "CLOSED", "bonnet": "CLOSED"}, "carCapturedTimestamp": ts},
        "odometer": {"mileageInKm": int(odo), "carCapturedTimestamp": ts},
        "parkingPosition": {"state": "IN_MOTION"} if moving else {
            "state": "PARKED", "gpsCoordinates": {"latitude": parked_at[0], "longitude": parked_at[1]},
            "formattedAddress": parked_at[2], "carCapturedTimestamp": ts},
        "airConditioning": {"state": climate, "targetTemperature": {"value": 21.0, "unit": "CELSIUS"},
                            "airConditioningWithoutExternalPower": True, "airConditioningAtUnlock": False,
                            "windowHeating": {"enabled": True, "front": "OFF", "rear": "OFF"}, "carCapturedTimestamp": ts},
        "charging": {
            "isVehicleInSavedLocation": parked_at == HOME, "carCapturedTimestamp": ts,
            "status": {"state": state, "chargeType": "AC" if charging else "OFF", "plugConnectionState": "CONNECTED" if parked_at == HOME else "DISCONNECTED",
                       "plugLockState": "LOCKED" if charging else "UNLOCKED",
                       "battery": {"stateOfChargeInPercent": round(soc), "remainingCruisingRangeInMeters": int(soc * 5600)},
                       **({"chargePowerInKw": 10.8, "chargingRateInKilometersPerHour": 56.0,
                           "remainingTimeToFullyChargedInMinutes": int(max(0, (target_soc - soc)) * 0.95)} if charging else {})},
            "settings": {"targetStateOfChargeInPercent": target_soc, "batteryCareModeTargetValueInPercent": 80,
                         "preferredChargeMode": "MANUAL", "availableChargeModes": ["MANUAL", "TIMER", "PREFERRED_CHARGING_TIMES"],
                         "chargingCareMode": "DEACTIVATED", "autoUnlockPlugWhenCharged": "PERMANENT",
                         "maxChargeCurrentAc": "MAXIMUM", "maxChargeCurrentAcAmpere": 16}},
        "chargingProfiles": {
            "carCapturedTimestamp": ts,
            "profiles": [{"id": 1, "name": "Home",
                          "settings": {"maxChargingCurrent": "MAXIMUM", "targetStateOfChargeInPercent": 80, "autoUnlockPlugWhenCharged": "PERMANENT",
                                       "minBatteryStateOfCharge": {"enabled": True, "minimumBatteryStateOfChargeInPercent": 20}},
                          "preferredChargingTimes": [{"id": 1, "enabled": True, "startTime": "22:00", "endTime": "06:00"}],
                          "timers": [{"id": 1, "enabled": False, "time": "07:30", "type": "RECURRING", "recurringOn": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]}]},
                         {"id": 2, "name": "Office",
                          "settings": {"maxChargingCurrent": "REDUCED", "targetStateOfChargeInPercent": 90, "autoUnlockPlugWhenCharged": "OFF",
                                       "minBatteryStateOfCharge": {"enabled": False, "minimumBatteryStateOfChargeInPercent": 20}},
                          "preferredChargingTimes": [], "timers": []}],
            "currentVehiclePositionProfile": {"id": 1, "name": "Home", "targetStateOfChargeInPercent": 80, "nextChargingTime": "22:00"}},
        "operations": [{"name": n} for n in ("startCharging", "stopCharging", "setChargingLimit", "setChargeMode", "updateChargingProfile",
                                              "startAirConditioning", "stopAirConditioning")],
    }
    return {"vehicle": veh, "errors": [
        {"type": "FUEL_STATUS_UNSUPPORTED", "description": "Battery-electric vehicle"},
        {"type": "AUXILIARY_HEATING_UNSUPPORTED", "description": "The vehicle has no auxiliary heater"},
        {"type": "ACTIVE_VENTILATION_UNSUPPORTED", "description": "The vehicle has no active ventilation"}]}


class DemoApi:
    """Evolves a little with wall-clock time: charges at night, drives in the morning, sits parked otherwise."""

    def __init__(self, clock=None, odo: float = 14820, soc: float = 64.0):
        import time

        self.clock = clock or time.time
        self.calls = 0
        self.soc = soc
        self.climate = "OFF"
        self.target = 80
        self.charging_forced: bool | None = None
        self.odo = odo  # continue from the seeded history, or the first reading looks like a 1000 km trip

    async def get_vehicle(self, vin, include=None):
        self.calls += 1
        now = datetime.fromtimestamp(self.clock(), UTC)
        hour = now.hour
        charging = self.charging_forced if self.charging_forced is not None else (hour >= 22 or hour < 5) and self.soc < self.target
        if charging:
            self.soc = min(self.target, self.soc + 1.2)
        if vin == DEMO_VIN2:  # the second demo car just sits parked, with its own level and odometer
            data = vehicle_response(now, SECOND["soc"], False, odo=SECOND["odo"], vin=DEMO_VIN2, name=SECOND["name"], plate=SECOND["plate"])
        else:
            data = vehicle_response(now, self.soc, charging, odo=self.odo, climate=self.climate, target_soc=self.target)
        return ApiResult(data=data, rate=RateInfo(20, max(0, 20 - self.calls % 20), 3000, self.clock()),
                         key_expires_at=(now + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    async def operate(self, vin, operation, body=None, **path_args):
        if operation == "setChargingLimit":
            self.target = int(body["targetStateOfChargeInPercent"])
        elif operation == "startAirConditioning":
            self.climate = "HEATING"
        elif operation == "stopAirConditioning":
            self.climate = "OFF"
        elif operation == "startCharging":
            self.charging_forced = True
        elif operation == "stopCharging":
            self.charging_forced = False
        return ApiResult(data={}, rate=RateInfo(20, 12, 3000, self.clock()), status=202)

    async def close(self):
        pass


def _seed_places(conn) -> None:
    """The four named places the demo drives between. Created before the first snapshot, so every row links."""
    places.upsert_home(conn, HOME[0], HOME[1], 180)
    have = {place["name"] for place in places.list_places(conn)}
    for place_name, coords, kind in (("Work", WORK, "work"), ("Shop", SHOP, "place"), ("Darmstadt", FAR, "place")):
        if place_name not in have:
            places.create(conn, {"name": place_name, "kind": kind, "lat": coords[0], "lon": coords[1], "radius_m": 150})


def _seed_duplicate_trip(conn, vid: int, now: datetime) -> None:
    """Store the newest finished trip of the last week a second time, ending one second later, so the data-quality card
    has a real, important finding. Same start and distance, different end: the quality check groups it, but the
    startup clean-up (`schema.dedupe_trips`, exact start and end only) leaves it alone. Unlike an open trip, it
    survives the live demo's first poll and a restart until the owner uses Fix or Mark as reviewed."""
    row = conn.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NOT NULL AND distance_km IS NOT NULL "
                       "AND started_at >= ? ORDER BY started_at DESC LIMIT 1",
                       (vid, (now - timedelta(days=6)).isoformat())).fetchone()
    if row is None:
        return
    copy = {k: v for k, v in dict(row).items() if k != "id"}
    copy["cloud_id"] = f"{row['cloud_id']}-copy"
    copy["ended_at"] = (datetime.fromisoformat(row["ended_at"]) + timedelta(seconds=1)).isoformat()
    conn.execute(f"INSERT INTO trips({', '.join(copy)}) VALUES({', '.join('?' * len(copy))})", tuple(copy.values()))


def seed(conn, days: int = 60, now: datetime | None = None, rng_seed: int = 7, vin: str = DEMO_VIN, name: str = "Demo Enyaq",
         plate: str = "F-DM 2026", model: str = "Enyaq 85") -> int:
    """Write believable history through the real recorder. Returns the vehicle id."""
    rng = random.Random(rng_seed)
    now = now or datetime.now(UTC)
    vid = recorder.upsert_vehicle(conn, vin, name, model, 77.0)
    store.save_sections(conn, vid, {"info": {"vin": vin, "name": name, "license_plate": plate, "render_url": None}},
                        now.isoformat())
    import json

    conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (json.dumps({"home_lat": HOME[0], "home_lon": HOME[1], "home_kwh": 0.28, "public_ac_kwh": 0.52,
                              "public_dc_kwh": 0.74, "currency": "EUR"}),))
    _seed_places(conn)
    soc, odo = 70.0, 9800.0
    start = (now - timedelta(days=days)).replace(hour=6, minute=0, second=0, microsecond=0)

    last: dict = {}  # the newest reading written: its time, its fields and the unrounded level behind its soc
    drain = random.Random(rng_seed + 1)  # its own stream, so trips and charges stay the same for a given seed

    def write(t, reading, level):
        recorder.ingest(conn, vid, {**reading, "ts": t.isoformat()})
        last.update(t=t, reading=reading, level=level)

    def stand_until(until):
        """Repeat the newest reading every PARKED_EVERY up to `until` while the car stands still (never mid-drive or
        mid-charge, whose own readings are close enough). The battery drains meanwhile, as a parked car's does.

        It drains from the level of the last reading WRITTEN: the schedule may already have moved `soc` on for events
        after `now` that were never written (a 22:00 charge), and those must not leak into the history."""
        nonlocal soc
        if not last or last["reading"]["in_motion"] or last["reading"]["charging"]:
            return
        still = {k: v for k, v in last["reading"].items() if k != "park_captured_at"}
        per_hour = drain.uniform(*PARKED_DRAIN_PCT_PER_DAY) / 24
        level = last["level"]
        t = last["t"] + PARKED_EVERY
        while t < until:
            level -= per_hour
            write(t, {**still, "soc": round(level)}, level)
            t += PARKED_EVERY
        soc = level

    def snap(t, **kw):
        if t > now:  # a day's schedule can run past midnight: that is not history yet, the live demo continues
            return
        stand_until(t)
        # whole percent and whole km, exactly as the API (and the live DemoApi via vehicle_response) reports them
        base = {"soc": round(soc), "charging": False, "mileage_km": int(odo), "in_motion": False,
                "lat": HOME[0], "lon": HOME[1], "address": HOME[2], "locked": True, "plug_connected": False, "charge_state": None,
                "climate_state": "OFF", "climate_target": 21.0}
        base.update(kw)
        write(t, base, soc)

    # One weekday-morning pre-heat in the last week (parked, before the first commute that is written).
    preheat_day = (now - timedelta(days=2)).date()
    while preheat_day.weekday() >= 5:
        preheat_day -= timedelta(days=1)
    preheated = False

    day = start
    here = HOME
    while day < now:
        wk = day.weekday() < 5
        t = day
        snap(t, lat=here[0], lon=here[1], address=here[2])
        if wk:  # commute
            for dest, back in ((WORK, False), (HOME, True)):
                if rng.random() < 0.08:
                    break
                km = round(rng.uniform(34, 41), 1)
                t0 = day.replace(hour=7, minute=rng.randint(10, 50)) if not back else day.replace(hour=17, minute=rng.randint(0, 50))
                if not back and not preheated and day.date() >= preheat_day:
                    preheated = True
                    for lead in (20, 10):  # the car heats itself for the commute: 20 minutes of climate on the timeline
                        snap(t0 - timedelta(minutes=lead), climate_state="HEATING", lat=here[0], lon=here[1], address=here[2])
                snap(t0, lat=here[0], lon=here[1], address=here[2])
                snap(t0 + timedelta(minutes=8), in_motion=True, lat=None, lon=None, address=None)
                soc -= km * rng.uniform(0.27, 0.36)
                odo += km
                end = t0 + timedelta(minutes=round(km * 1.15))
                snap(t0 + timedelta(minutes=round(km * 0.6)), in_motion=True, lat=None, lon=None, address=None)
                snap(end, lat=dest[0], lon=dest[1], address=dest[2], park_captured_at=(end - timedelta(minutes=2)).isoformat())
                here = dest
        elif rng.random() < 0.8:  # weekend errand, sometimes far
            dest = rng.choice([SHOP, SHOP, FAR])
            km = round(rng.uniform(4, 12) if dest is SHOP else rng.uniform(55, 70), 1)
            t0 = day.replace(hour=rng.randint(9, 15), minute=rng.randint(0, 59))
            snap(t0, lat=here[0], lon=here[1], address=here[2])
            snap(t0 + timedelta(minutes=6), in_motion=True, lat=None, lon=None, address=None)
            soc -= km * rng.uniform(0.28, 0.4)
            odo += km
            end = t0 + timedelta(minutes=round(km * 1.3))
            snap(end, lat=dest[0], lon=dest[1], address=dest[2])
            here = dest
        # evening home charge when low (or DC on a long day away)
        if here is not HOME and soc < 35:
            here = HOME
        if soc < 45 or (day.weekday() == 6):
            t = day.replace(hour=22, minute=0)
            target = rng.choice([80, 80, 90])
            kind, kw = ("AC", 10.8)
            if here is FAR:
                kind, kw = "DC", 48.0
            steps = 0
            while soc < target and steps < 40:
                snap(t, charging=True, charge_state="CHARGING", charge_power_kw=kw + rng.uniform(-0.3, 0.3), charge_type=kind,
                     plug_connected=True, target_soc=target, lat=HOME[0], lon=HOME[1], address=HOME[2])
                soc = min(target, soc + kw * 0.5 / 77 * 100 * 0.93)
                t += timedelta(minutes=30)
                steps += 1
            snap(t, charge_state="READY_FOR_CHARGING", plug_connected=True, lat=HOME[0], lon=HOME[1], address=HOME[2])
            here = HOME
        day += timedelta(days=1)
    stand_until(now)  # up to the moment the live demo takes over
    _seed_duplicate_trip(conn, vid, now)
    conn.commit()
    return vid
