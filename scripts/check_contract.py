"""Check Mate against Škoda's published OpenAPI contract (no API key needed).

    .venv/bin/python scripts/check_contract.py            # fetches /v3/api-docs
    .venv/bin/python scripts/check_contract.py spec.json  # or a saved copy

Validates (1) the response fixtures used by the tests and the demo responses against `VehicleResponse`, and (2) every
request body Mate builds for a command against the operation's request schema. Run it when Škoda bumps the API version.
Needs `jsonschema` (dev only).
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jsonschema import Draft202012Validator  # noqa: E402

from skoda_mate import commands, demo  # noqa: E402
from skoda_mate.client import OPERATIONS  # noqa: E402
from tests.fixtures import BEV, ICE  # noqa: E402

URL = "https://public.api.connect.skoda-auto.cz/v3/api-docs"


def load(arg):
    if arg:
        return json.loads(Path(arg).read_text())
    with urllib.request.urlopen(URL, timeout=30) as r:
        return json.load(r)


def validator(spec, name):
    schema = {"$ref": f"#/components/schemas/{name}", "components": spec["components"]}
    return Draft202012Validator(schema)


def check(label, v, instance, problems):
    errs = sorted(v.iter_errors(instance), key=lambda e: list(e.path))
    for e in errs:
        problems.append(f"{label}: {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:160]}")
    print(f"{'ok  ' if not errs else 'FAIL'} {label}" + (f" ({len(errs)} problems)" if errs else ""))


def main():
    spec = load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"contract: {spec['info'].get('title')} {spec['info'].get('version')}")
    problems: list[str] = []

    resp = validator(spec, "VehicleResponse")
    now = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)
    check("fixture BEV", resp, BEV, problems)
    check("fixture ICE", resp, ICE, problems)
    check("demo parked/charging", resp, demo.vehicle_response(now, 55, True), problems)
    check("demo driving", resp, demo.vehicle_response(now, 55, False, moving=True), problems)

    # request bodies: operationId -> schema name
    body_schema = {"setChargingLimit": "ChargingLimit", "setChargeMode": "ChargeMode",
                   "startAirConditioning": "StartAirConditioningConfiguration",
                   "startAuxiliaryHeating": "StartAuxiliaryHeatingConfiguration", "updateChargingProfile": "ChargingProfile"}
    profiles = BEV["vehicle"]["chargingProfiles"]
    samples = {
        "set_charge_limit": [{"percent": 80}], "set_charge_mode": [{"mode": "TIMER"}],
        "start_climate": [{"temperature": 21.5}, {"temperature": 19, "without_external_power": False}],
        "start_aux_heating": [{}, {"temperature": 22, "duration_min": 30, "mode": "HEATING"}],
        "update_charging_profile": [{"profile_id": 7, "target_soc": 70, "max_current": "REDUCED", "auto_unlock": "OFF",
                                     "min_soc_enabled": False, "min_soc": 30,
                                     "charging_times": [{"id": 1, "enabled": True, "start": "21:00", "end": "05:00"}],
                                     "timers": [{"id": 1, "enabled": True, "type": "recurring", "time": "06:45", "recurring_on": ["monday"]},
                                                {"id": 2, "enabled": False, "type": "one_off", "time": "08:00", "one_off_day": "sunday"}]}],
    }
    for name, cases in samples.items():
        for params in cases:
            op, body, _ = commands.build(name, params, spin="1234", raw_profiles=profiles)
            if op in body_schema:
                check(f"request {name} {json.dumps(params)[:50]}", validator(spec, body_schema[op]), body, problems)
    # every operation Mate knows exists in the contract, with the same method and path
    paths = {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if isinstance(op, dict) and "operationId" in op:
                paths[op["operationId"]] = (method.upper(), path.replace("{id}", "{id}"))
    for op, (method, tmpl) in OPERATIONS.items():
        got = paths.get(op)
        ok = got == (method, tmpl)
        print(f"{'ok  ' if ok else 'FAIL'} operation {op}: {method} {tmpl}" + ("" if ok else f"   contract says {got}"))
        if not ok:
            problems.append(f"operation {op}: {got} != {(method, tmpl)}")
    extra = set(paths) - set(OPERATIONS) - {"getVehicle"}
    if extra:
        problems.append(f"contract has operations Mate does not know: {sorted(extra)}")
        print("NEW  operations in the contract that Mate does not use:", sorted(extra))

    # Field coverage: every property the contract defines must be read by Mate (responses) or sendable (requests).
    src = (Path(__file__).resolve().parent.parent / "skoda_mate")
    consumed = (src / "normalise.py").read_text() + (src / "commands.py").read_text() + (src / "client.py").read_text()
    skip_schemas = {"ProblemDetail"}
    names: dict[str, set[str]] = {}
    leaves: set[str] = set()
    REQUEST_SCHEMAS = {"ChargeMode", "ChargingLimit", "StartAuxiliaryHeatingConfiguration", "StartAirConditioningConfiguration"}
    for sname, s in spec["components"]["schemas"].items():
        if sname in skip_schemas:
            continue
        for prop, pdef in (s.get("properties") or {}).items():
            if pdef.get("writeOnly"):  # e.g. a stray `tings` ($ref to the schema itself): never part of a response
                continue
            names.setdefault(prop, set()).add(sname)
            if "$ref" not in pdef and pdef.get("type") != "object" and sname not in REQUEST_SCHEMAS:
                leaves.add(prop)
    unused = {p: sorted(v) for p, v in names.items() if f'"{p}"' not in consumed and f"'{p}'" not in consumed}
    print(f"\nfield coverage: {len(names) - len(unused)}/{len(names)} contract fields are used by Mate")
    for p, where in sorted(unused.items()):
        print(f"  UNUSED  {p}  (in {', '.join(where)})")
    if unused:
        problems.append(f"{len(unused)} contract field(s) not used: {sorted(unused)}")

    # The Capabilities page must list every operation and every response field of the live contract.
    from skoda_mate import features  # noqa: E402

    listed_ops = {o["id"] for o in features.OPERATIONS_CATALOGUE}
    contract_ops = set(paths)
    for op in sorted(contract_ops - listed_ops):
        problems.append(f"Capabilities page does not list operation {op}")
        print(f"MISSING in Capabilities page: operation {op}")
    for op in sorted(listed_ops - contract_ops):
        problems.append(f"Capabilities page lists {op}, which the contract no longer has")
    listed_fields = {a.split(".")[-1] for _, (_, fl) in features.PART_FIELDS.items() for a, *_ in fl}
    gaps = sorted(p for p in leaves if p not in listed_fields and p not in {
        "profiles", "settings", "status", "battery", "overall", "detail", "doorsLocked", "id", "name", "enabled", "type", "time", "oneOffDay",
        "recurringOn", "preferredChargingTimes", "timers", "minBatteryStateOfCharge", "maxChargingCurrent", "minimumBatteryStateOfChargeInPercent",
        "startTime", "endTime", "unit", "value", "latitude", "longitude", "vehicle", "errors", "operations", "description", "state_"})
    print(f"capabilities page: {len(listed_ops)} operations listed; unlisted response fields: {gaps or 'none'}")
    for p in gaps:
        problems.append(f"Capabilities page does not list field {p}")

    print("\n" + (f"{len(problems)} problem(s):\n  " + "\n  ".join(problems) if problems else "contract OK"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
