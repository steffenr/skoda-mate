"""Remote commands the official API offers, with parameter validation and request-body building.

Only what the contract (v1.1.0) defines exists here. In particular there is NO lock/unlock, honk or wake-up:
the dashboard must not pretend otherwise. A car may support only a subset; `vehicle.operations` says which,
and `check_supported()` enforces it before a request (and a quota slot) is spent.
"""
from __future__ import annotations

import copy
import re

CHARGE_MODES = ("MANUAL", "TIMER", "TIMER_CHARGING_WITH_CLIMATISATION", "PREFERRED_CHARGING_TIMES",
                "ONLY_OWN_CURRENT", "IMMEDIATE_DISCHARGING", "HOME_STORAGE_CHARGING")
DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class CommandError(ValueError):
    """Bad parameters or unsupported operation: nothing was sent."""


# command name -> (operationId, label, group, needs_spin)
COMMANDS: dict[str, dict] = {
    "start_charging": {"op": "startCharging", "label": "Start charging", "group": "charging"},
    "stop_charging": {"op": "stopCharging", "label": "Stop charging", "group": "charging"},
    "set_charge_limit": {"op": "setChargingLimit", "label": "Set charge limit", "group": "charging",
                         "params": {"percent": "int 50-100 (cars usually accept steps of 10)"}},
    "set_charge_mode": {"op": "setChargeMode", "label": "Set charge mode", "group": "charging",
                        "params": {"mode": "one of " + ", ".join(CHARGE_MODES)}},
    "update_charging_profile": {"op": "updateChargingProfile", "label": "Update charging profile", "group": "charging",
                                "params": {"profile_id": "int", "name": "str?", "target_soc": "int?",
                                           "max_current": "REDUCED|MAXIMUM?", "auto_unlock": "PERMANENT|OFF?",
                                           "min_soc_enabled": "bool?", "min_soc": "int?",
                                           "charging_times": "[{id,enabled,start,end}]?", "timers": "[...]?"}},
    "start_climate": {"op": "startAirConditioning", "label": "Start climate", "group": "climate",
                      "params": {"temperature": "number 15.5-30 °C", "without_external_power": "bool?"}},
    "stop_climate": {"op": "stopAirConditioning", "label": "Stop climate", "group": "climate"},
    "start_aux_heating": {"op": "startAuxiliaryHeating", "label": "Start auxiliary heating", "group": "climate",
                          "needs_spin": True,
                          "params": {"temperature": "number?", "duration_min": "int 5-60?", "mode": "HEATING|VENTILATION?"}},
    "stop_aux_heating": {"op": "stopAuxiliaryHeating", "label": "Stop auxiliary heating", "group": "climate"},
    "start_ventilation": {"op": "startActiveVentilation", "label": "Start ventilation", "group": "climate"},
    "stop_ventilation": {"op": "stopActiveVentilation", "label": "Stop ventilation", "group": "climate"},
}


def _num(params: dict, key: str, lo: float, hi: float) -> float:
    v = params.get(key)
    if v is None or v == "":
        raise CommandError(f"'{key}' is required")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise CommandError(f"'{key}' must be a number") from None
    if not lo <= f <= hi:
        raise CommandError(f"'{key}' must be between {lo:g} and {hi:g}")
    return f


def _opt_num(params: dict, key: str, lo: float, hi: float) -> float | None:
    """A number the caller may leave out (None then), as opposed to one the operation needs."""
    return None if params.get(key) in (None, "") else _num(params, key, lo, hi)


def check_supported(name: str, operations: list[str] | None) -> None:
    spec = COMMANDS.get(name)
    if spec is None:
        raise CommandError(f"unknown command {name!r}")
    if operations is not None and spec["op"] not in operations:
        raise CommandError("This car does not support that operation.")


def build(name: str, params: dict | None, *, spin: str = "", raw_profiles: dict | None = None
          ) -> tuple[str, dict | None, dict]:
    """-> (operationId, JSON body or None, path args). Raises CommandError on bad input."""
    params = params or {}
    spec = COMMANDS.get(name)
    if spec is None:
        raise CommandError(f"unknown command {name!r}")
    op = spec["op"]

    if name == "set_charge_limit":
        pct = _num(params, "percent", 1, 100)
        return op, {"targetStateOfChargeInPercent": int(pct)}, {}
    if name == "set_charge_mode":
        mode = str(params.get("mode", "")).upper()
        if mode not in CHARGE_MODES:
            raise CommandError("'mode' must be one of " + ", ".join(CHARGE_MODES))
        return op, {"chargeMode": mode}, {}
    if name == "start_climate":
        t = _num(params, "temperature", 15.5, 30)
        body: dict = {"targetTemperature": {"value": round(t * 2) / 2, "unit": "CELSIUS"}}
        if params.get("without_external_power") is not None:
            body["airConditioningWithoutExternalPower"] = bool(params["without_external_power"])
        return op, body, {}
    if name == "start_aux_heating":
        if not spin:
            raise CommandError("The auxiliary heater needs your S-PIN. Add it under Settings.")
        body = {"spin": spin}
        temp = _opt_num(params, "temperature", 15.5, 30)
        if temp is not None:
            body["targetTemperature"] = {"value": round(temp * 2) / 2, "unit": "CELSIUS"}
        d = _opt_num(params, "duration_min", 5, 60)
        if d is not None:
            body["durationInSeconds"] = int(d) * 60
        if params.get("mode"):
            mode = str(params["mode"]).upper()
            if mode not in ("HEATING", "VENTILATION"):
                raise CommandError("'mode' must be HEATING or VENTILATION")
            body["startMode"] = mode
        return op, body, {}
    if name == "update_charging_profile":
        return op, *_profile_body(params, raw_profiles)
    return op, None, {}


def _profile_body(params: dict, raw_profiles: dict | None) -> tuple[dict, dict]:
    """The API takes the whole profile, so edit a copy of the last one the car reported."""
    pid = params.get("profile_id")
    if pid is None:
        raise CommandError("'profile_id' is required")
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise CommandError("'profile_id' must be an integer") from None
    current = next((p for p in (raw_profiles or {}).get("profiles", []) if p.get("id") == pid), None)
    if current is None:
        raise CommandError("Unknown charging profile; refresh the data first.")
    p = copy.deepcopy(current)
    s = p.setdefault("settings", {})
    if params.get("name") is not None:
        name = str(params["name"]).strip()
        if not name:
            raise CommandError("'name' must not be empty")
        p["name"] = name[:60]
    t = _opt_num(params, "target_soc", 1, 100)
    if t is not None:
        s["targetStateOfChargeInPercent"] = int(t)
    if params.get("max_current") is not None:
        if str(params["max_current"]).upper() not in ("REDUCED", "MAXIMUM"):
            raise CommandError("'max_current' must be REDUCED or MAXIMUM")
        s["maxChargingCurrent"] = str(params["max_current"]).upper()
    if params.get("auto_unlock") is not None:
        if str(params["auto_unlock"]).upper() not in ("PERMANENT", "OFF"):
            raise CommandError("'auto_unlock' must be PERMANENT or OFF")
        s["autoUnlockPlugWhenCharged"] = str(params["auto_unlock"]).upper()
    if params.get("min_soc_enabled") is not None or params.get("min_soc") is not None:
        m = s.setdefault("minBatteryStateOfCharge", {})
        if params.get("min_soc_enabled") is not None:
            m["enabled"] = bool(params["min_soc_enabled"])
        ms = _opt_num(params, "min_soc", 1, 100)
        if ms is not None:
            m["minimumBatteryStateOfChargeInPercent"] = int(ms)
    if params.get("charging_times") is not None:
        times = []
        for t_ in params["charging_times"]:
            st, en = str(t_.get("start", "")), str(t_.get("end", ""))
            if not (HHMM.match(st) and HHMM.match(en)):
                raise CommandError("charging times need start and end as HH:mm")
            times.append({"id": int(t_["id"]), "enabled": bool(t_.get("enabled", True)), "startTime": st, "endTime": en})
        p["preferredChargingTimes"] = times
    if params.get("timers") is not None:
        timers = []
        for t_ in params["timers"]:
            tm = t_.get("time")
            if tm is not None and not HHMM.match(str(tm)):
                raise CommandError("timer time must be HH:mm")
            typ = str(t_.get("type", "")).upper()
            if typ not in ("ONE_OFF", "RECURRING"):
                raise CommandError("timer type must be ONE_OFF or RECURRING")
            days = [str(d).upper() for d in (t_.get("recurring_on") or [])]
            if any(d not in DAYS for d in days):
                raise CommandError("timer days must be MONDAY..SUNDAY")
            one = t_.get("one_off_day")
            if one is not None and str(one).upper() not in DAYS:
                raise CommandError("one_off_day must be MONDAY..SUNDAY")
            timer = {"id": int(t_["id"]), "enabled": bool(t_.get("enabled", True)), "type": typ}
            if tm is not None:
                timer["time"] = str(tm)
            if one is not None:
                timer["oneOffDay"] = str(one).upper()
            if days:
                timer["recurringOn"] = days
            timers.append(timer)
        p["timers"] = timers
    return p, {"id": pid}


def catalogue(operations: list[str] | None) -> list[dict]:
    """For the UI: every command with whether this car supports it."""
    out = []
    for name, spec in COMMANDS.items():
        out.append({"name": name, "label": spec["label"], "group": spec["group"],
                    "params": spec.get("params", {}), "needs_spin": bool(spec.get("needs_spin")),
                    "supported": None if operations is None else spec["op"] in operations})
    return out
