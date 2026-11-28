"""What this car can do, from what the API itself reports: `vehicle.operations` (remote operations) and the
state of each data part (present / unsupported / disabled / unavailable). The dashboard gates every control and
page on this, so it never offers something the cloud would refuse."""
from __future__ import annotations

from typing import Any

# feature -> operationId(s), any one suffices
OPERATION_FEATURES = {
    "charge_control": ("startCharging", "stopCharging"),
    "charge_limit": ("setChargingLimit",),
    "charge_mode": ("setChargeMode",),
    "charge_profiles": ("updateChargingProfile",),
    "climate": ("startAirConditioning", "stopAirConditioning"),
    "aux_heating": ("startAuxiliaryHeating", "stopAuxiliaryHeating"),
    "ventilation": ("startActiveVentilation", "stopActiveVentilation"),
}

PART_LABELS = {"status": "Doors, windows & lights", "fuelStatus": "Fuel & range", "odometer": "Odometer",
               "parkingPosition": "Position", "airConditioning": "Climate", "auxiliaryHeating": "Auxiliary heater",
               "activeVentilation": "Ventilation", "charging": "Charging & battery", "chargingProfiles": "Charging profiles"}

NOT_SUPPORTED = "Not supported by this car"
NOT_KNOWN_YET = "Supported operations not known yet"

PART_REASONS = {"unsupported": NOT_SUPPORTED, "disabled": "Disabled for this car (consent, licence or workshop mode)",
                "unavailable": "Temporarily unavailable", "missing": "Not reported"}

# What leapmotor-mate offers but the official Škoda API does not. Shown honestly in the dashboard.
UNAVAILABLE = [
    {"key": "lock", "title": "Lock / unlock", "why": "The public API has no lock or unlock operation. The lock state is shown read-only."},
    {"key": "honk", "title": "Honk, flash, wake-up", "why": "Not offered by the public API."},
    {"key": "cloud_trips", "title": "Trip history from the car", "why": "No trip data. Trips are derived by Mate from the odometer and the "
                                                                    "parked/driving state, so times are accurate to the poll interval."},
    {"key": "route", "title": "Driving route and speed trace", "why": "Position is not available while driving, and the quota allows ~20 reads per hour."},
    {"key": "charge_history", "title": "Charging history import", "why": "No history endpoint. Sessions are detected live from the charging status."},
    {"key": "soh", "title": "Battery health (SoH)", "why": "Not reported. Mate shows an estimate from charges, which includes charging losses."},
    {"key": "capacity", "title": "Battery capacity", "why": "Not reported. Enter it in Settings so energy and consumption can be computed."},
    {"key": "outside_temp", "title": "Outside temperature", "why": "Not in the public API, so there is no consumption-versus-temperature chart."},
    {"key": "maintenance", "title": "Service, inspection, warning lights, software version", "why": "Not in the public API."},
    {"key": "seat_heating", "title": "Seat and steering-wheel heating, climate timers", "why": "Not controllable through the public API."},
    {"key": "push", "title": "Live updates", "why": "No push events: Mate polls within Škoda's request limit (about 20 per hour per car)."},
    {"key": "navigation", "title": "Send destination to the car, charger search", "why": "Not offered by the public API."},
]


# ----------------------------------------------------------------------------------------------------------------
# The complete picture of the official API (contract v1.2.0), for the "Capabilities" page. scripts/check_contract.py
# fails if the live contract has an operation or a data field that is not listed here, so this cannot silently rot.

CONTRACT_VERSION = "1.2.0"

# operationId -> what it does, how Mate exposes it
OPERATIONS_CATALOGUE: list[dict[str, Any]] = [
    {"id": "getVehicle", "method": "GET", "path": "/api/v1/vehicles/{vin}", "label": "Read the vehicle", "group": "read",
     "what": "One request returns every data part below, in one go. Mate asks for all of them each time, because the request limit is per request, not per part.",
     "mate": "Overview and every page; polled on the intervals set under Settings → Polling", "page": "overview", "params": "include = which parts (Mate always asks for all)"},
    {"id": "startCharging", "method": "POST", "path": "/api/v1/vehicles/{vin}/charging/start", "label": "Start charging", "group": "charging",
     "what": "Starts a charging session on the connected cable.", "mate": "Control → Charging, Overview quick control", "page": "control", "command": "start_charging", "params": "none"},
    {"id": "stopCharging", "method": "POST", "path": "/api/v1/vehicles/{vin}/charging/stop", "label": "Stop charging", "group": "charging",
     "what": "Stops the running charging session.", "mate": "Control → Charging, Overview quick control", "page": "control", "command": "stop_charging", "params": "none"},
    {"id": "setChargingLimit", "method": "PUT", "path": "/api/v1/vehicles/{vin}/charging/limit", "label": "Set the charge limit", "group": "charging",
     "what": "Sets the target state of charge. Cars usually accept 50 to 100 % in steps of 10.", "mate": "Control → Charge limit", "page": "control", "command": "set_charge_limit", "params": "targetStateOfChargeInPercent (1-100)"},
    {"id": "setChargeMode", "method": "PUT", "path": "/api/v1/vehicles/{vin}/charging/mode", "label": "Change the charge mode", "group": "charging",
     "what": "Chooses how the car charges (manual, timer, preferred times, own current only, …). The car lists the modes it offers.", "mate": "Control → Charge mode", "page": "control", "command": "set_charge_mode", "params": "chargeMode (one of the modes the car offers)"},
    {"id": "updateChargingProfile", "method": "PUT", "path": "/api/v1/vehicles/{vin}/charging-profiles/{id}", "label": "Edit a charging profile", "group": "charging",
     "what": "Changes a saved charging location profile: target level, current, minimum level, preferred charging times, timers, auto-unlock of the plug.", "mate": "Control → Charging profiles", "page": "control", "command": "update_charging_profile", "params": "the whole profile (Mate edits a copy of what the car reported)"},
    {"id": "startAirConditioning", "method": "POST", "path": "/api/v1/vehicles/{vin}/air-conditioning/start", "label": "Start the climate control", "group": "climate",
     "what": "Pre-conditions the cabin to a target temperature, optionally also without an external power connection.", "mate": "Control → Climate, Overview quick control", "page": "control", "command": "start_climate", "params": "targetTemperature (°C), airConditioningWithoutExternalPower"},
    {"id": "stopAirConditioning", "method": "POST", "path": "/api/v1/vehicles/{vin}/air-conditioning/stop", "label": "Stop the climate control", "group": "climate",
     "what": "Stops a running air-conditioning process.", "mate": "Control → Climate", "page": "control", "command": "stop_climate", "params": "none"},
    {"id": "startAuxiliaryHeating", "method": "POST", "path": "/api/v1/vehicles/{vin}/auxiliary-heating/start", "label": "Start the auxiliary heater", "group": "climate",
     "what": "Starts the fuel or electric auxiliary heater (cars that have one). Needs your S-PIN.", "mate": "Control → Auxiliary heater (S-PIN in Settings)", "page": "control", "command": "start_aux_heating", "dependent": ["targetTemperature", "startMode"], "params": "spin, durationInSeconds, and only if the car lists them in vehicleDependentParameters: targetTemperature, startMode (heating or ventilation)"},
    {"id": "stopAuxiliaryHeating", "method": "POST", "path": "/api/v1/vehicles/{vin}/auxiliary-heating/stop", "label": "Stop the auxiliary heater", "group": "climate",
     "what": "Stops the auxiliary heater.", "mate": "Control → Auxiliary heater", "page": "control", "command": "stop_aux_heating", "params": "none"},
    {"id": "startActiveVentilation", "method": "POST", "path": "/api/v1/vehicles/{vin}/active-ventilation/start", "label": "Start the ventilation", "group": "climate",
     "what": "Ventilates the cabin without heating or cooling (cars that have it).", "mate": "Control → Ventilation", "page": "control", "command": "start_ventilation", "params": "none"},
    {"id": "stopActiveVentilation", "method": "POST", "path": "/api/v1/vehicles/{vin}/active-ventilation/stop", "label": "Stop the ventilation", "group": "climate",
     "what": "Stops the ventilation.", "mate": "Control → Ventilation", "page": "control", "command": "stop_ventilation", "params": "none"},
]

# part -> [(api field path, label, where the value is kept ('<section>' in sections or 'snapshot'), key path in it, unit)]
PART_FIELDS = {
    "info": ("Vehicle", [
        ("name", "Name", "info", "name", ""), ("licensePlate", "Licence plate", "info", "license_plate", ""), ("renderUrl", "Picture", "info", "render_url", "url"),
        ("vin", "VIN", "info", "vin", "")]),
    "status": ("Doors, windows & lights", [
        ("status.overall.doorsLocked", "Doors and trunk locked", "status", "doors_locked", ""), ("status.overall.locked", "Locked (all doors)", "status", "locked", ""),
        ("status.overall.doors", "Doors", "status", "doors", ""), ("status.overall.windows", "Side windows", "status", "windows", ""),
        ("status.overall.lights", "Lights", "status", "lights", ""), ("status.overall.reliableLockStatus", "Reliable lock status", "status", "reliable_lock", ""),
        ("status.detail.trunk", "Trunk", "status", "trunk", ""), ("status.detail.bonnet", "Bonnet", "status", "bonnet", ""),
        ("status.detail.sunroof", "Sunroof", "status", "sunroof", ""), ("status.carCapturedTimestamp", "Reported by the car at", "status", "captured_at", "time")]),
    "odometer": ("Odometer", [("odometer.mileageInKm", "Odometer", "snapshot", "mileage_km", "km"),
                              ("odometer.carCapturedTimestamp", "Reported by the car at", "odometer", "captured_at", "time")]),
    "parkingPosition": ("Position", [
        ("parkingPosition.state", "State", "position", "state", ""), ("parkingPosition.gpsCoordinates.latitude", "Latitude", "position", "lat", ""),
        ("parkingPosition.gpsCoordinates.longitude", "Longitude", "position", "lon", ""), ("parkingPosition.formattedAddress", "Address", "position", "address", ""),
        ("parkingPosition.carCapturedTimestamp", "Reported by the car at", "position", "captured_at", "time")]),
    "airConditioning": ("Climate", [
        ("airConditioning.state", "State", "climate", "state", ""), ("airConditioning.targetTemperature.value", "Target temperature", "climate", "target.value", "°C"),
        ("airConditioning.estimatedReachOfTargetTemperatureAt", "Target reached at", "climate", "reach_at", "time"),
        ("airConditioning.airConditioningWithoutExternalPower", "Allowed without external power", "climate", "without_external_power", ""),
        ("airConditioning.airConditioningAtUnlock", "Starts when the car is unlocked", "climate", "at_unlock", ""),
        ("airConditioning.windowHeating.enabled", "Window heating enabled", "climate", "window_heating.enabled", ""),
        ("airConditioning.windowHeating.front", "Front window heating", "climate", "window_heating.front", ""),
        ("airConditioning.windowHeating.rear", "Rear window heating", "climate", "window_heating.rear", ""),
        ("airConditioning.carCapturedTimestamp", "Reported by the car at", "climate", "captured_at", "time")]),
    "auxiliaryHeating": ("Auxiliary heater", [
        ("auxiliaryHeating.state", "State", "aux", "state", ""), ("auxiliaryHeating.startMode", "Start mode", "aux", "start_mode", ""),
        ("auxiliaryHeating.durationInSeconds", "Run time", "aux", "duration_s", "s"), ("auxiliaryHeating.targetTemperature.value", "Target temperature", "aux", "target.value", "°C"),
        ("auxiliaryHeating.estimatedReachOfTargetTemperatureAt", "Target reached at", "aux", "reach_at", "time"),
        ("auxiliaryHeating.carCapturedTimestamp", "Reported by the car at", "aux", "captured_at", "time")]),
    "activeVentilation": ("Ventilation", [
        ("activeVentilation.state", "State", "ventilation", "state", ""), ("activeVentilation.durationInSeconds", "Run time", "ventilation", "duration_s", "s"),
        ("activeVentilation.carCapturedTimestamp", "Reported by the car at", "ventilation", "captured_at", "time")]),
    "charging": ("Charging & battery", [
        ("charging.status.state", "Charging state", "charging", "state", ""), ("charging.status.chargingErrorReason", "Cause of the charging error", "charging", "error_reason", ""),
        ("charging.status.chargeType", "Charge type", "charging", "type", ""),
        ("charging.status.chargePowerInKw", "Charging power", "charging", "power_kw", "kW"), ("charging.status.chargingRateInKilometersPerHour", "Charging rate", "charging", "rate_kmh", "km/h"),
        ("charging.status.remainingTimeToFullyChargedInMinutes", "Time to fully charged", "charging", "remaining_min", "min"),
        ("charging.status.fullyChargedAt", "Fully charged at", "charging", "fully_charged_at", "time"),
        ("charging.status.plugConnectionState", "Plug connection", "charging", "plug_connection", ""), ("charging.status.plugLockState", "Plug lock", "charging", "plug_lock", ""),
        ("charging.status.battery.stateOfChargeInPercent", "Battery level", "charging", "soc", "%"), ("charging.status.battery.remainingCruisingRangeInMeters", "Electric range", "charging", "range_km", "km"),
        ("charging.isVehicleInSavedLocation", "At a saved charging location", "charging", "in_saved_location", ""),
        ("charging.settings.targetStateOfChargeInPercent", "Charge limit", "charging", "settings.target_soc", "%"),
        ("charging.settings.batteryCareModeTargetValueInPercent", "Battery care limit", "charging", "settings.care_target_soc", "%"),
        ("charging.settings.preferredChargeMode", "Preferred charge mode", "charging", "settings.preferred_mode", ""),
        ("charging.settings.availableChargeModes", "Charge modes the car offers", "charging", "settings.available_modes", ""),
        ("charging.settings.chargingCareMode", "Battery care mode", "charging", "settings.care_mode", ""),
        ("charging.settings.autoUnlockPlugWhenCharged", "Unlock the plug when charged", "charging", "settings.auto_unlock_plug", ""),
        ("charging.settings.maxChargeCurrentAc", "Maximum AC current", "charging", "settings.max_current", ""),
        ("charging.settings.maxChargeCurrentAcAmpere", "Maximum AC current", "charging", "settings.max_current_a", "A"),
        ("charging.carCapturedTimestamp", "Reported by the car at", "charging", "captured_at", "time")]),
    "chargingProfiles": ("Charging profiles", [
        ("chargingProfiles.profiles", "Saved profiles", "profiles", "profiles", "count"),
        ("chargingProfiles.currentVehiclePositionProfile.name", "Profile at the current position", "profiles", "current.name", ""),
        ("chargingProfiles.currentVehiclePositionProfile.targetStateOfChargeInPercent", "Target there", "profiles", "current.target_soc", "%"),
        ("chargingProfiles.currentVehiclePositionProfile.nextChargingTime", "Next charging time there", "profiles", "current.next_charging_time", ""),
        ("chargingProfiles.currentVehiclePositionProfile.id", "Profile number there", "profiles", "current.id", ""),
        ("chargingProfiles.carCapturedTimestamp", "Reported by the car at", "profiles", "captured_at", "time")]),
    "fuelStatus": ("Fuel & range (combustion and hybrid cars)", [
        ("fuelStatus.carType", "Car type", "fuel", "car_type", ""), ("fuelStatus.totalRangeInKm", "Total range", "fuel", "total_range_km", "km"),
        ("fuelStatus.adBlueRange", "AdBlue range", "fuel", "adblue_range_km", "km"),
        ("fuelStatus.primaryEngineRange.engineType", "Primary engine", "fuel", "primary.engine_type", ""),
        ("fuelStatus.primaryEngineRange.currentSoCInPercent", "Primary: battery level", "fuel", "primary.soc", "%"),
        ("fuelStatus.primaryEngineRange.currentFuelLevelInPercent", "Primary: fuel level", "fuel", "primary.fuel_pct", "%"),
        ("fuelStatus.primaryEngineRange.remainingRangeInKm", "Primary: range", "fuel", "primary.range_km", "km"),
        ("fuelStatus.secondaryEngineRange.engineType", "Secondary engine", "fuel", "secondary.engine_type", ""),
        ("fuelStatus.secondaryEngineRange.currentSoCInPercent", "Secondary: battery level", "fuel", "secondary.soc", "%"),
        ("fuelStatus.secondaryEngineRange.currentFuelLevelInPercent", "Secondary: fuel level", "fuel", "secondary.fuel_pct", "%"),
        ("fuelStatus.secondaryEngineRange.remainingRangeInKm", "Secondary: range", "fuel", "secondary.range_km", "km"),
        ("fuelStatus.carCapturedTimestamp", "Reported by the car at", "fuel", "captured_at", "time")]),
}

# What Mate adds on top of the API (derived or imported, so never as exact as the car's own numbers).
DERIVED = [
    {"title": "Trips", "how": "Derived from the odometer and the parked/driving state, or imported from the MyŠkoda app's trip export. Times are accurate to the poll interval for derived trips.", "page": "trips"},
    {"title": "Charges", "how": "Measured while Mate sees the car charging; otherwise inferred from the battery level rising between trips or readings (marked “inferred”).", "page": "charges"},
    {"title": "Costs and Home vs Public", "how": "Your tariff and your home position (set on a map in Settings) applied to the charges.", "page": "settings"},
    {"title": "Statistics", "how": "Monthly distance, energy, cost and consumption computed from the trips and charges Mate has stored, plus the odometer for the distance.", "page": "stats"},
    {"title": "Battery capacity estimate", "how": "Wall energy per 100 % of charge from long AC charges.", "page": "battery"},
    {"title": "History import", "how": "Fills the time before Mate started from the trip export of the MyŠkoda app (the app seems to keep only about seven months).", "page": "import"},
    {"title": "Home Assistant", "how": "Sensors, a position tracker, a charge-limit number and buttons for the commands, over MQTT (optional).", "page": "system"},
    {"title": "Maps, events, exports, backup", "how": "Everything Mate has recorded can be browsed, exported as CSV and backed up.", "page": "map"},
]


def _dig(obj, path: str):
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def capabilities(operations: list[str] | None, part_state: dict | None, sections: dict, snapshot: dict | None,
                 rate_limit: int | None = None, key_expires_at: str | None = None,
                 operation_params: dict[str, list[str]] | None = None) -> dict:
    """Everything the API offers, with what THIS car supports and reports right now.

    `operation_params` is each operation's `vehicleDependentParameters`: an operation that has such fields gets `accepts`,
    the ones this car lists (None while it reported no list)."""
    listed = operation_params or {}
    ops = None if operations is None else set(operations)
    op_rows = []
    for o in OPERATIONS_CATALOGUE:
        if o["id"] == "getVehicle":  # reading is what Mate does for every car
            supported: bool | None = True
        elif ops is None:
            supported = None
        else:
            supported = o["id"] in ops
        op_rows.append({**o, "supported": supported, **({"accepts": listed.get(o["id"])} if o.get("dependent") else {})})
    parts = []
    for key, (label, fields) in PART_FIELDS.items():
        st = "present" if key == "info" else (part_state or {}).get(key, "unknown")
        rows = []
        for api, flabel, where, path, unit in fields:
            src = snapshot if where == "snapshot" else sections.get(where)
            val = _dig(src or {}, path)
            if unit == "count" and isinstance(val, list):
                val = len(val)
            rows.append({"api": api, "label": flabel, "value": val, "unit": unit})
        parts.append({"key": key, "label": label, "state": st, "reason": PART_REASONS.get(st) if st not in ("present", "unknown") else None,
                      "fields": rows, "reported": sum(1 for r in rows if r["value"] is not None)})
    return {"contract": {"version": CONTRACT_VERSION, "rate_limit_per_hour": rate_limit or 20, "key_expires_at": key_expires_at,
                         "docs": "https://public.api.connect.skoda-auto.cz/docs"},
            "operations": op_rows, "parts": parts, "derived": DERIVED, "unavailable": UNAVAILABLE,
            "summary": {"operations_supported": sum(1 for o in op_rows if o["supported"] and o["id"] != "getVehicle"),
                        "operations_total": len(op_rows) - 1, "parts_available": sum(1 for p in parts if p["state"] == "present"),
                        "parts_total": len(parts)}}


def features(operations: list[str] | None, part_state: dict | None) -> dict:
    ops = None if operations is None else set(operations)
    out: dict[str, dict] = {}
    for name, needed in OPERATION_FEATURES.items():
        if ops is None:
            out[name] = {"available": None, "reason": NOT_KNOWN_YET}
        elif ops & set(needed):
            out[name] = {"available": True, "reason": None}
        else:
            out[name] = {"available": False, "reason": NOT_SUPPORTED}
    return out


def parts(part_state: dict | None) -> dict:
    out = {}
    for part, label in PART_LABELS.items():
        st = (part_state or {}).get(part)
        out[part] = {"label": label, "state": st or "unknown", "available": st == "present",
                     "reason": None if st == "present" or st is None else PART_REASONS.get(st)}
    return out
