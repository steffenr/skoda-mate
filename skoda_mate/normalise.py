"""Official API JSON -> a flat snapshot (DB columns) plus sections for the dashboard.

Rules from the API documentation that matter here:
* a missing field means *unknown*, never a specific value (e.g. an omitted charging `state` does NOT mean
  the cable is unplugged), so absent values stay None and are never defaulted;
* parts the car lacks or could not deliver are absent and described in `errors`;
* `carCapturedTimestamp` is when the car last reported, not when we asked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Parts and the `errors[].type` prefix that names them.
PARTS = {"status": "VEHICLE_STATUS", "fuelStatus": "FUEL_STATUS", "odometer": "ODOMETER",
         "parkingPosition": "PARKING_POSITION", "airConditioning": "AIR_CONDITIONING",
         "auxiliaryHeating": "AUXILIARY_HEATING", "activeVentilation": "ACTIVE_VENTILATION",
         "charging": "CHARGING", "chargingProfiles": "CHARGING_PROFILES"}


@dataclass
class Parsed:
    snapshot: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)  # key -> JSON-able dict
    operations: list[str] | None = None  # None = could not be determined
    errors: list[dict] = field(default_factory=list)
    part_state: dict = field(default_factory=dict)  # part -> present | unsupported | disabled | unavailable | missing
    captured_at: str | None = None


def _g(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _yes(v, true):
    return None if v in (None, "UNKNOWN", "UNSUPPORTED") else v == true


def _latest(*stamps) -> str | None:
    s = [x for x in stamps if x]
    return max(s) if s else None  # ISO-8601 UTC strings sort chronologically


def _engine(e: dict) -> dict | None:
    """One engine of a hybrid / combustion car (ELECTRIC, GASOLINE, DIESEL, CNG, LPG, UNKNOWN)."""
    if not e:
        return None
    return {"engine_type": e.get("engineType"), "soc": e.get("currentSoCInPercent"),
            "fuel_pct": e.get("currentFuelLevelInPercent"), "range_km": e.get("remainingRangeInKm")}


def part_states(vehicle: dict, errors: list[dict]) -> dict:
    out = {}
    for part, prefix in PARTS.items():
        kinds = {e.get("type", "") for e in errors}
        if vehicle.get(part) is not None:
            out[part] = "present"
        elif prefix + "_UNSUPPORTED" in kinds:
            out[part] = "unsupported"
        elif prefix + "_DISABLED" in kinds:
            out[part] = "disabled"
        elif prefix + "_UNAVAILABLE" in kinds:
            out[part] = "unavailable"
        else:
            out[part] = "missing"  # absent without an error: not supported (include was omitted)
    return out


def parse(resp: dict, now_iso: str) -> Parsed:
    v = resp.get("vehicle") or {}
    errors = [{"type": e.get("type"), "description": e.get("description")} for e in (resp.get("errors") or [])]
    p = Parsed(errors=errors, part_state=part_states(v, errors))
    if "operations" in v:
        p.operations = [o.get("name") for o in (v.get("operations") or []) if o.get("name")]

    snap: dict = {}
    ch, fuel, st, ac, aux, vent = (v.get(k) for k in ("charging", "fuelStatus", "status", "airConditioning",
                                                      "auxiliaryHeating", "activeVentilation"))
    park, odo = v.get("parkingPosition"), v.get("odometer")

    # --- charging / battery
    if ch is not None:
        cs = ch.get("status") or {}
        state = cs.get("state")
        range_m = _g(cs, "battery", "remainingCruisingRangeInMeters")
        snap.update({
            "soc": _g(cs, "battery", "stateOfChargeInPercent"),
            "range_km": None if range_m is None else round(range_m / 1000, 1),
            "charging": state == "CHARGING",
            "charge_state": state,  # may be None: unknown, not "unplugged"
            "charge_power_kw": cs.get("chargePowerInKw"), "charge_type": cs.get("chargeType"),
            "remaining_min": cs.get("remainingTimeToFullyChargedInMinutes"),
            "fully_charged_at": cs.get("fullyChargedAt"), "charging_rate_kmh": cs.get("chargingRateInKilometersPerHour"),
            "plug_connected": _yes(cs.get("plugConnectionState"), "CONNECTED"),
            "plug_locked": _yes(cs.get("plugLockState"), "LOCKED"),
            "target_soc": _g(ch, "settings", "targetStateOfChargeInPercent"),
        })
        s = ch.get("settings") or {}
        p.sections["charging"] = {
            "state": state, "type": cs.get("chargeType"), "power_kw": cs.get("chargePowerInKw"),
            "rate_kmh": cs.get("chargingRateInKilometersPerHour"), "remaining_min": cs.get("remainingTimeToFullyChargedInMinutes"),
            "fully_charged_at": cs.get("fullyChargedAt"), "plug_connection": cs.get("plugConnectionState"),
            "plug_lock": cs.get("plugLockState"), "soc": snap["soc"], "range_km": snap["range_km"],
            "in_saved_location": ch.get("isVehicleInSavedLocation"), "captured_at": ch.get("carCapturedTimestamp"),
            "settings": {"target_soc": s.get("targetStateOfChargeInPercent"),
                         "care_target_soc": s.get("batteryCareModeTargetValueInPercent"),
                         "preferred_mode": s.get("preferredChargeMode"),
                         "available_modes": s.get("availableChargeModes") or [],
                         "care_mode": None if s.get("chargingCareMode") is None else s.get("chargingCareMode") == "ACTIVATED",
                         "auto_unlock_plug": s.get("autoUnlockPlugWhenCharged"),
                         "max_current": s.get("maxChargeCurrentAc"), "max_current_a": s.get("maxChargeCurrentAcAmpere")},
        }

    # --- fuel (ICE / hybrid)
    if fuel is not None:
        prim, sec = fuel.get("primaryEngineRange") or {}, fuel.get("secondaryEngineRange") or {}
        fuelish = next((e for e in (prim, sec) if e.get("currentFuelLevelInPercent") is not None), {})
        snap.update({"fuel_pct": fuelish.get("currentFuelLevelInPercent"), "fuel_range_km": fuelish.get("remainingRangeInKm")})
        if snap.get("range_km") is None:  # BEV range lives in `charging`; for ICE/hybrid use the total
            snap["range_km"] = fuel.get("totalRangeInKm")
        p.sections["fuel"] = {"car_type": fuel.get("carType"), "total_range_km": fuel.get("totalRangeInKm"),
                              "adblue_range_km": fuel.get("adBlueRange"), "primary": _engine(prim),
                              "secondary": _engine(sec), "captured_at": fuel.get("carCapturedTimestamp")}
        if snap.get("soc") is None:
            snap["soc"] = next((e.get("currentSoCInPercent") for e in (prim, sec) if e.get("currentSoCInPercent") is not None), None)

    # --- doors / windows / lights
    if st is not None:
        o, d = st.get("overall") or {}, st.get("detail") or {}
        snap.update({
            "locked": _yes(o.get("locked"), "YES"), "doors_open": _yes(o.get("doors"), "OPEN"),
            "windows_open": _yes(o.get("windows"), "OPEN"), "lights_on": _yes(o.get("lights"), "ON"),
            "trunk_open": _yes(d.get("trunk"), "OPEN"), "bonnet_open": _yes(d.get("bonnet"), "OPEN"),
            "sunroof_open": _yes(d.get("sunroof"), "OPEN"),
        })
        p.sections["status"] = {"doors_locked": o.get("doorsLocked"), "locked": o.get("locked"), "doors": o.get("doors"),
                                "windows": o.get("windows"), "lights": o.get("lights"),
                                "reliable_lock": o.get("reliableLockStatus"), "trunk": d.get("trunk"),
                                "bonnet": d.get("bonnet"), "sunroof": d.get("sunroof"),
                                "captured_at": st.get("carCapturedTimestamp")}

    # --- odometer / position
    if odo is not None:
        snap["mileage_km"] = odo.get("mileageInKm")
        p.sections["odometer"] = {"mileage_km": odo.get("mileageInKm"), "captured_at": odo.get("carCapturedTimestamp")}
    if park is not None:
        snap["in_motion"] = park.get("state") == "IN_MOTION" if park.get("state") else None
        snap["park_captured_at"] = park.get("carCapturedTimestamp")
        c = park.get("gpsCoordinates") or {}
        if c.get("latitude") is not None and c.get("longitude") is not None:
            snap["lat"], snap["lon"] = c["latitude"], c["longitude"]
            snap["address"] = park.get("formattedAddress")
        p.sections["position"] = {"state": park.get("state"), "lat": c.get("latitude"), "lon": c.get("longitude"),
                                  "address": park.get("formattedAddress"), "captured_at": park.get("carCapturedTimestamp")}

    # --- climate, aux heating, ventilation
    if ac is not None:
        snap["climate_state"] = ac.get("state")
        snap["climate_target"] = _g(ac, "targetTemperature", "value")
        wh = ac.get("windowHeating") or {}
        p.sections["climate"] = {
            "state": ac.get("state"), "target": ac.get("targetTemperature"), "unit": _g(ac, "targetTemperature", "unit"),
            "reach_at": ac.get("estimatedReachOfTargetTemperatureAt"),
            "without_external_power": ac.get("airConditioningWithoutExternalPower"),
            "at_unlock": ac.get("airConditioningAtUnlock"),
            "window_heating": {"enabled": wh.get("enabled"), "front": wh.get("front"), "rear": wh.get("rear")},
            "running": ac.get("state") in ("COOLING", "HEATING", "HEATING_AUXILIARY", "VENTILATION"),
            "captured_at": ac.get("carCapturedTimestamp")}
    if aux is not None:
        snap["aux_state"] = aux.get("state")
        p.sections["aux"] = {"state": aux.get("state"), "start_mode": aux.get("startMode"),
                             "duration_s": aux.get("durationInSeconds"), "target": aux.get("targetTemperature"),
                             "reach_at": aux.get("estimatedReachOfTargetTemperatureAt"),
                             "running": aux.get("state") in ("PREHEATING", "HEATING_AUXILIARY", "VENTILATION"),
                             "captured_at": aux.get("carCapturedTimestamp")}
    if vent is not None:
        snap["vent_state"] = vent.get("state")
        p.sections["ventilation"] = {"state": vent.get("state"), "duration_s": vent.get("durationInSeconds"),
                                     "running": vent.get("state") in ("PREHEATING", "VENTILATION"),
                                     "captured_at": vent.get("carCapturedTimestamp")}

    # --- charging profiles (kept raw as well: updating one needs the full object back)
    cp = v.get("chargingProfiles")
    if cp is not None:
        cur = cp.get("currentVehiclePositionProfile")
        p.sections["profiles"] = {"profiles": cp.get("profiles") or [],
                                  "current": None if cur is None else {"id": cur.get("id"), "name": cur.get("name"),
                                                                       "target_soc": cur.get("targetStateOfChargeInPercent"),
                                                                       "next_charging_time": cur.get("nextChargingTime")},
                                  "captured_at": cp.get("carCapturedTimestamp")}

    # --- info
    p.sections["info"] = {"vin": v.get("vin"), "name": v.get("name"), "license_plate": v.get("licensePlate"),
                          "render_url": v.get("renderUrl")}

    p.captured_at = _latest(*(_g(v, k, "carCapturedTimestamp") for k in
                              ("status", "fuelStatus", "odometer", "parkingPosition", "airConditioning",
                               "auxiliaryHeating", "activeVentilation", "charging", "chargingProfiles")))
    snap["captured_at"] = p.captured_at
    snap["ts"] = now_iso
    # Keep Nones out only for "unknown" columns we never want to overwrite with NULL elsewhere; the recorder
    # stores every snapshot as reported, so None here honestly means "the car did not say".
    p.snapshot = snap
    return p


def running_actively(parsed: Parsed) -> bool:
    """Charging, climate, heater, ventilation or driving: worth polling more often."""
    s = parsed.snapshot
    return bool(s.get("charging") or s.get("in_motion")
                or any((parsed.sections.get(k) or {}).get("running") for k in ("climate", "aux", "ventilation")))
