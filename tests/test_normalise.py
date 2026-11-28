from skoda_mate import normalise as n

from .fixtures import BEV, ICE, bev

NOW = "2026-11-23T07:05:00+00:00"


def test_bev_snapshot_and_sections():
    p = n.parse(BEV, NOW)
    s = p.snapshot
    assert s["soc"] == 55 and s["range_km"] == 251.0 and s["charging"] is True and s["charge_state"] == "CHARGING"
    assert s["charge_power_kw"] == 10.8 and s["charge_type"] == "AC" and s["remaining_min"] == 95
    assert s["plug_connected"] is True and s["plug_locked"] is True and s["target_soc"] == 80
    assert s["locked"] is True and s["doors_open"] is False and s["windows_open"] is False and s["lights_on"] is False
    assert s["trunk_open"] is False and s["sunroof_open"] is None  # UNSUPPORTED is unknown, not False
    assert s["mileage_km"] == 12345 and s["in_motion"] is False and s["lat"] == 50.11
    assert s["address"].startswith("Main Street 1") and s["climate_state"] == "OFF" and s["climate_target"] == 21.0
    assert s["captured_at"] == "2026-11-23T07:00:00Z" and s["ts"] == NOW
    assert p.sections["charging"]["settings"]["care_mode"] is False
    assert p.sections["charging"]["settings"]["available_modes"] == ["MANUAL", "TIMER"]
    assert p.sections["profiles"]["profiles"][0]["id"] == 7 and p.sections["info"]["name"] == "My Enyaq"
    assert p.sections["climate"]["window_heating"]["enabled"] is True
    assert p.operations[0] == "startCharging" and "startAuxiliaryHeating" not in p.operations


def test_part_states_from_errors():
    p = n.parse(BEV, NOW)
    ps = p.part_state
    assert ps["charging"] == "present" and ps["fuelStatus"] == "unsupported" and ps["auxiliaryHeating"] == "unsupported"
    d = bev(**{"charging": None})
    d["errors"].append({"type": "CHARGING_UNAVAILABLE", "description": "timeout"})
    d["errors"].append({"type": "ODOMETER_DISABLED"})
    ps = n.parse(d, NOW).part_state
    assert ps["charging"] == "unavailable" and ps["odometer"] == "present"  # an error never hides data that arrived
    assert n.parse({"vehicle": {"vin": "X"}}, NOW).part_state["status"] == "missing"


def test_omitted_charge_state_is_unknown_not_unplugged():
    p = n.parse(bev(**{"charging.status.state": None, "charging.status.plugConnectionState": None}), NOW)
    s = p.snapshot
    assert s["charge_state"] is None and s["charging"] is False
    assert s["plug_connected"] is None  # never defaulted to False
    assert p.sections["charging"]["state"] is None


def test_in_motion_has_no_coordinates():
    p = n.parse(bev(parkingPosition={"state": "IN_MOTION"}), NOW)
    assert p.snapshot["in_motion"] is True and "lat" not in p.snapshot and p.sections["position"]["lat"] is None


def test_ice_vehicle():
    p = n.parse(ICE, NOW)
    s = p.snapshot
    assert s["fuel_pct"] == 62 and s["fuel_range_km"] == 640 and s["range_km"] == 640 and "charging" not in s
    assert p.sections["fuel"]["adblue_range_km"] == 4000 and p.sections["aux"]["duration_s"] == 1800
    assert s["aux_state"] == "OFF" and s["vent_state"] == "OFF" and p.part_state["charging"] == "unsupported"
    assert p.operations == ["startAuxiliaryHeating", "stopAuxiliaryHeating"]


def test_hybrid_keeps_battery_range_and_fuel():
    d = n.parse({"vehicle": {**BEV["vehicle"], "fuelStatus": ICE["vehicle"]["fuelStatus"]}, "errors": []}, NOW)
    assert d.snapshot["range_km"] == 251.0 and d.snapshot["fuel_pct"] == 62 and d.snapshot["soc"] == 55


def test_operations_unknown_vs_empty():
    assert n.parse({"vehicle": {"vin": "X"}}, NOW).operations is None  # could not be determined
    assert n.parse({"vehicle": {"vin": "X", "operations": []}}, NOW).operations == []


def test_a_charging_error_carries_its_reason():
    p = n.parse(bev(**{"charging.status.state": "CHARGING_ERROR", "charging.status.chargingErrorReason": "NO_GRID_VOLTAGE"}), NOW)
    s = p.snapshot
    assert s["charge_state"] == "CHARGING_ERROR" and s["charge_error_reason"] == "NO_GRID_VOLTAGE" and s["charging"] is False
    assert p.sections["charging"]["error_reason"] == "NO_GRID_VOLTAGE"
    assert p.sections["charging"]["state"] == "CHARGING_ERROR"
    # an unknown cause (new values appear over time) is kept as it is; no cause stays unknown
    assert n.parse(bev(**{"charging.status.state": "CHARGING_ERROR", "charging.status.chargingErrorReason": "SOMETHING_NEW"}),
                   NOW).snapshot["charge_error_reason"] == "SOMETHING_NEW"
    assert n.parse(bev(**{"charging.status.state": "CHARGING_ERROR"}), NOW).snapshot["charge_error_reason"] is None
    assert n.parse(BEV, NOW).snapshot["charge_error_reason"] is None


def test_vehicle_dependent_parameters_per_operation():
    p = n.parse(ICE, NOW)
    assert p.operation_params == {"startAuxiliaryHeating": ["targetTemperature"], "stopAuxiliaryHeating": []}
    assert n.parse(BEV, NOW).operation_params["startCharging"] == []
    # no list reported (older data, API before 1.2.0): unknown, which is not the same as "supports none"
    old = n.parse({"vehicle": {"vin": "X", "operations": [{"name": "startAuxiliaryHeating"}]}}, NOW)
    assert old.operations == ["startAuxiliaryHeating"] and old.operation_params == {}
    assert n.parse({"vehicle": {"vin": "X"}}, NOW).operation_params is None


def test_lock_values():
    for raw, exp in (("YES", True), ("NO", False), ("UNKNOWN", None)):
        d = bev()
        d["vehicle"]["status"]["overall"]["locked"] = raw
        assert n.parse(d, NOW).snapshot["locked"] is exp


def test_activity_detection():
    assert n.running_actively(n.parse(BEV, NOW))  # charging
    idle = bev(**{"charging.status.state": "READY_FOR_CHARGING"})
    assert not n.running_actively(n.parse(idle, NOW))
    hot = bev(**{"charging.status.state": "READY_FOR_CHARGING"})
    hot["vehicle"]["airConditioning"]["state"] = "HEATING"
    assert n.running_actively(n.parse(hot, NOW))
    assert n.running_actively(n.parse(bev(parkingPosition={"state": "IN_MOTION"}), NOW))
