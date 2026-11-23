import pytest

from skoda_mate import commands as c

from .fixtures import BEV


def test_no_lock_honk_or_wakeup_commands_exist():
    assert not {"lock", "unlock", "honk_flash", "flash", "wakeup"} & set(c.COMMANDS)  # not in the official API


def test_simple_bodies():
    assert c.build("start_charging", None) == ("startCharging", None, {})
    assert c.build("set_charge_limit", {"percent": "80"}) == ("setChargingLimit", {"targetStateOfChargeInPercent": 80}, {})
    assert c.build("set_charge_mode", {"mode": "timer"})[1] == {"chargeMode": "TIMER"}
    op, body, _ = c.build("start_climate", {"temperature": 21.3, "without_external_power": True})
    assert op == "startAirConditioning" and body == {"targetTemperature": {"value": 21.5, "unit": "CELSIUS"},
                                                     "airConditioningWithoutExternalPower": True}
    assert c.build("stop_ventilation", {})[0] == "stopActiveVentilation"


@pytest.mark.parametrize("name,params", [
    ("set_charge_limit", {}), ("set_charge_limit", {"percent": 0}), ("set_charge_limit", {"percent": 101}),
    ("set_charge_limit", {"percent": "abc"}), ("set_charge_mode", {"mode": "TURBO"}),
    ("start_climate", {}), ("start_climate", {"temperature": 5}), ("start_climate", {"temperature": 99}),
    ("nonsense", {})])
def test_bad_parameters_are_rejected_before_anything_is_sent(name, params):
    with pytest.raises(c.CommandError):
        c.build(name, params)


def test_aux_heating_needs_spin_and_validates():
    with pytest.raises(c.CommandError, match="S-PIN"):
        c.build("start_aux_heating", {"temperature": 21})
    op, body, _ = c.build("start_aux_heating", {"temperature": 22, "duration_min": 30, "mode": "heating"}, spin="1234")
    assert op == "startAuxiliaryHeating"
    assert body == {"spin": "1234", "targetTemperature": {"value": 22.0, "unit": "CELSIUS"}, "durationInSeconds": 1800,
                    "startMode": "HEATING"}
    assert c.build("start_aux_heating", {}, spin="1234")[1] == {"spin": "1234"}
    for bad in ({"duration_min": 2}, {"duration_min": 90}, {"mode": "BAKE"}):
        with pytest.raises(c.CommandError):
            c.build("start_aux_heating", bad, spin="1234")


def test_support_check_uses_the_cars_operation_list():
    ops = ["startCharging", "stopCharging"]
    c.check_supported("start_charging", ops)
    with pytest.raises(c.CommandError, match="does not support"):
        c.check_supported("start_climate", ops)
    c.check_supported("start_climate", None)  # unknown list: let the API decide (it answers 422 if unsupported)
    with pytest.raises(c.CommandError):
        c.check_supported("unlock", ops)


def raw():
    return BEV["vehicle"]["chargingProfiles"]


def test_profile_update_edits_a_copy_of_the_cars_profile():
    op, body, args = c.build("update_charging_profile", {"profile_id": 7, "target_soc": 70, "max_current": "reduced",
                                                         "auto_unlock": "permanent", "min_soc_enabled": False}, raw_profiles=raw())
    assert op == "updateChargingProfile" and args == {"id": 7}
    assert body["id"] == 7 and body["name"] == "Home"
    assert body["settings"]["targetStateOfChargeInPercent"] == 70 and body["settings"]["maxChargingCurrent"] == "REDUCED"
    assert body["settings"]["autoUnlockPlugWhenCharged"] == "PERMANENT"
    assert body["settings"]["minBatteryStateOfCharge"] == {"enabled": False, "minimumBatteryStateOfChargeInPercent": 20}
    assert body["preferredChargingTimes"] == raw()["profiles"][0]["preferredChargingTimes"]  # untouched parts survive
    assert raw()["profiles"][0]["settings"]["targetStateOfChargeInPercent"] == 90  # the original is not mutated


def test_profile_times_and_timers():
    _, body, _ = c.build("update_charging_profile", {
        "profile_id": 7,
        "charging_times": [{"id": 1, "enabled": True, "start": "21:00", "end": "05:30"}],
        "timers": [{"id": 1, "enabled": True, "type": "recurring", "time": "06:45", "recurring_on": ["monday", "friday"]},
                   {"id": 2, "enabled": False, "type": "ONE_OFF", "time": "08:00", "one_off_day": "sunday"}]}, raw_profiles=raw())
    assert body["preferredChargingTimes"] == [{"id": 1, "enabled": True, "startTime": "21:00", "endTime": "05:30"}]
    assert body["timers"][0] == {"id": 1, "enabled": True, "type": "RECURRING", "time": "06:45",
                                 "recurringOn": ["MONDAY", "FRIDAY"]}
    assert body["timers"][1]["oneOffDay"] == "SUNDAY"


@pytest.mark.parametrize("params", [
    {}, {"profile_id": 99}, {"profile_id": "x"}, {"profile_id": 7, "target_soc": 500}, {"profile_id": 7, "max_current": "LOTS"},
    {"profile_id": 7, "auto_unlock": "SOMETIMES"}, {"profile_id": 7, "name": "  "},
    {"profile_id": 7, "charging_times": [{"id": 1, "start": "25:00", "end": "05:00"}]},
    {"profile_id": 7, "timers": [{"id": 1, "type": "WEEKLY"}]},
    {"profile_id": 7, "timers": [{"id": 1, "type": "RECURRING", "recurring_on": ["FUNDAY"]}]}])
def test_profile_validation(params):
    with pytest.raises(c.CommandError):
        c.build("update_charging_profile", params, raw_profiles=raw())


def test_catalogue_marks_support():
    cat = {x["name"]: x for x in c.catalogue(["startCharging"])}
    assert cat["start_charging"]["supported"] is True and cat["start_climate"]["supported"] is False
    assert cat["start_aux_heating"]["needs_spin"] is True
    assert all(x["supported"] is None for x in c.catalogue(None))
