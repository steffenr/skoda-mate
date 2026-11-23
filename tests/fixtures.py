"""API responses shaped exactly like the official OpenAPI schema (v1.1.0)."""
import copy

VIN = "TMBJB9NY5RF999999"
TS = "2026-11-23T07:00:00Z"

BEV = {
    "vehicle": {
        "vin": VIN, "name": "My Enyaq", "licensePlate": "1MB 1234", "renderUrl": "https://img.example.test/enyaq.png",
        "status": {"overall": {"doorsLocked": "YES", "locked": "YES", "doors": "CLOSED", "windows": "CLOSED",
                               "lights": "OFF", "reliableLockStatus": "LOCKED"},
                   "detail": {"sunroof": "UNSUPPORTED", "trunk": "CLOSED", "bonnet": "CLOSED"}, "carCapturedTimestamp": TS},
        "odometer": {"mileageInKm": 12345, "carCapturedTimestamp": TS},
        "parkingPosition": {"state": "PARKED", "gpsCoordinates": {"latitude": 50.11, "longitude": 8.68},
                            "formattedAddress": "Main Street 1, 60311 Frankfurt, Germany", "carCapturedTimestamp": TS},
        "airConditioning": {"state": "OFF", "targetTemperature": {"value": 21.0, "unit": "CELSIUS"},
                            "airConditioningWithoutExternalPower": True, "airConditioningAtUnlock": False,
                            "windowHeating": {"enabled": True, "front": "OFF", "rear": "OFF"}, "carCapturedTimestamp": TS},
        "charging": {
            "isVehicleInSavedLocation": True, "carCapturedTimestamp": TS,
            "status": {"state": "CHARGING", "chargeType": "AC", "chargePowerInKw": 10.8,
                       "chargingRateInKilometersPerHour": 52.0, "remainingTimeToFullyChargedInMinutes": 95,
                       "fullyChargedAt": "2026-11-23T08:35:00Z", "plugConnectionState": "CONNECTED",
                       "plugLockState": "LOCKED",
                       "battery": {"stateOfChargeInPercent": 55, "remainingCruisingRangeInMeters": 251000}},
            "settings": {"targetStateOfChargeInPercent": 80, "batteryCareModeTargetValueInPercent": 80,
                         "preferredChargeMode": "MANUAL", "availableChargeModes": ["MANUAL", "TIMER"],
                         "chargingCareMode": "DEACTIVATED", "autoUnlockPlugWhenCharged": "PERMANENT",
                         "maxChargeCurrentAc": "MAXIMUM", "maxChargeCurrentAcAmpere": 32}},
        "chargingProfiles": {
            "carCapturedTimestamp": TS,
            "profiles": [{"id": 7, "name": "Home",
                          "settings": {"maxChargingCurrent": "MAXIMUM", "targetStateOfChargeInPercent": 90,
                                       "autoUnlockPlugWhenCharged": "OFF",
                                       "minBatteryStateOfCharge": {"enabled": True, "minimumBatteryStateOfChargeInPercent": 20}},
                          "preferredChargingTimes": [{"id": 1, "enabled": True, "startTime": "22:00", "endTime": "06:00"}],
                          "timers": [{"id": 1, "enabled": False, "time": "07:30", "type": "RECURRING",
                                      "recurringOn": ["MONDAY", "TUESDAY"]}]}],
            "currentVehiclePositionProfile": {"id": 7, "name": "Home", "targetStateOfChargeInPercent": 90,
                                              "nextChargingTime": "22:00"}},
        "operations": [{"name": n} for n in ("startCharging", "stopCharging", "setChargingLimit", "setChargeMode",
                                              "updateChargingProfile", "startAirConditioning", "stopAirConditioning")],
    },
    "errors": [{"type": "FUEL_STATUS_UNSUPPORTED", "description": "Battery-electric vehicle"},
               {"type": "AUXILIARY_HEATING_UNSUPPORTED", "description": "no heater"},
               {"type": "ACTIVE_VENTILATION_UNSUPPORTED", "description": "no ventilation"}],
}

ICE = {
    "vehicle": {
        "vin": VIN, "name": "Octavia",
        "status": BEV["vehicle"]["status"], "odometer": {"mileageInKm": 80000},
        "fuelStatus": {"carType": "DIESEL", "adBlueRange": 4000, "totalRangeInKm": 640,
                       "primaryEngineRange": {"engineType": "DIESEL", "currentFuelLevelInPercent": 62,
                                              "remainingRangeInKm": 640}, "carCapturedTimestamp": TS},
        "auxiliaryHeating": {"state": "OFF", "startMode": "HEATING", "durationInSeconds": 1800,
                             "targetTemperature": {"value": 21, "unit": "CELSIUS"}},
        "activeVentilation": {"state": "OFF", "durationInSeconds": 600},
        "operations": [{"name": "startAuxiliaryHeating"}, {"name": "stopAuxiliaryHeating"}],
    },
    "errors": [{"type": "CHARGING_UNSUPPORTED", "description": "No high-voltage battery"}],
}


def bev(**over):
    """Deep copy of the BEV response with dotted-path overrides, e.g. bev(**{'charging.status.state': None})."""
    d = copy.deepcopy(BEV)
    for path, value in over.items():
        node = d["vehicle"]
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        if value is None:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return d
