import asyncio
import json

import pytest

from skoda_mate import commands, recorder, schema, store
from skoda_mate.client import ApiError, RateInfo
from skoda_mate.poller import Poller

from .fixtures import BEV, VIN, bev
from .helpers import Clock, FakeApi


def setup(responses=None, spin=""):
    clock = Clock()
    conn = schema.connect(":memory:")
    api = FakeApi(responses, clock)
    p = Poller(conn, api, spin_getter=lambda: spin, clock=clock)
    vid = recorder.upsert_vehicle(conn, VIN, "Enyaq")
    p.add_vehicle(VIN, vid)
    return p, api, conn, clock, vid


def run(coro):
    return asyncio.run(coro)


def err(status, kind, retry_after=None, remaining=None):
    return ApiError(status, kind, "x", retry_after, RateInfo(20, remaining, 100, 0))


def test_one_poll_is_one_request_and_stores_everything():
    p, api, conn, clock, vid = setup()
    assert run(p.poll(VIN))["ok"]
    assert api.calls == [("get", VIN)]  # all parts in a single request
    snap = recorder.last_snapshot(conn, vid)
    assert snap["soc"] == 55 and snap["charging"] == 1 and snap["mileage_km"] == 12345
    sec = store.load_sections(conn, vid)
    assert {"charging", "status", "position", "climate", "profiles", "info", "operations", "part_state", "raw"} <= set(sec)
    assert sec["operations"]["list"][0] == "startCharging"
    assert conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0] == 1
    st = p.status(VIN)
    assert st["key_expires_at"] == "2027-06-01T00:00:00Z" and st["budget"]["used"] == 1 and st["active"] is True


def test_intervals_active_vs_idle_and_user_overrides():
    p, api, conn, clock, vid = setup()
    run(p.poll(VIN))  # charging -> active
    assert p.rt[VIN].next_poll == clock.t + 300
    p.api.responses = [bev(**{"charging.status.state": "READY_FOR_CHARGING"})]
    run(p.poll(VIN))
    assert p.rt[VIN].next_poll == clock.t + 1200  # parked and quiet
    conn.execute("INSERT INTO settings(key,value) VALUES('poll_idle_s','900'),('poll_active_s','1')")
    assert p.intervals() == (900, 180)  # the floor protects the quota: 20/h cannot go faster than 180 s


def test_tick_polls_only_what_is_due():
    p, api, conn, clock, vid = setup()
    assert run(p.tick()) == 1
    assert run(p.tick()) == 0
    clock.advance(301)
    assert run(p.tick()) == 1  # active vehicle: 5 min


def test_budget_stops_background_polls_but_leaves_slots_for_commands():
    p, api, conn, clock, vid = setup()
    for _ in range(16):
        assert run(p.poll(VIN))["ok"]
    r = run(p.poll(VIN))
    assert r["kind"] == "budget" and len(api.calls) == 16  # nothing was sent
    run(p.run_command(VIN, "stop_charging"))  # still possible: the reserve
    assert api.calls[-1][2] == "stopCharging"


def test_manual_refresh_may_use_the_reserve():
    p, api, conn, clock, vid = setup()
    for _ in range(16):
        run(p.poll(VIN))
    assert run(p.poll(VIN, reason="manual"))["ok"]


def test_429_waits_for_retry_after_and_blocks_commands_too():
    p, api, conn, clock, vid = setup([err(429, "rate-limit-exceeded", retry_after=600, remaining=0)])
    r = run(p.poll(VIN))
    assert not r["ok"] and r["kind"] == "rate-limit-exceeded" and r["retryable"]
    assert p.rt[VIN].next_poll == clock.t + 600 and p.rt[VIN].budget.status()["limited"]
    with pytest.raises(commands.CommandError, match="limit"):
        run(p.run_command(VIN, "stop_charging"))
    clock.advance(601)
    p.api.responses = [BEV]
    assert run(p.poll(VIN))["ok"]


def test_vehicle_not_accepting_requests_is_retried_later_without_blocking():
    p, api, conn, clock, vid = setup([err(429, "vehicle-not-accepting-requests", retry_after=120)])
    run(p.poll(VIN))
    assert not p.rt[VIN].blocked and p.rt[VIN].next_poll == clock.t + 120


def test_key_errors_stop_polling_and_do_not_consume_quota():
    p, api, conn, clock, vid = setup([err(401, "api-key-expired")])
    run(p.poll(VIN))
    r = p.rt[VIN]
    assert r.blocked and r.error_kind == "api-key-expired" and "expired" in r.last_error
    assert r.budget.used() == 0 and conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0] == 0  # 401 is free
    assert run(p.tick()) == 0  # not retried
    p.reset_block()  # a new key was entered
    p.api.responses = [BEV]
    assert run(p.tick()) == 1 and not p.rt[VIN].blocked


def test_transient_errors_back_off_exponentially_and_recover():
    p, api, conn, clock, vid = setup([err(503, "http-503"), err(503, "http-503"), BEV])
    run(p.poll(VIN))
    assert p.rt[VIN].next_poll == clock.t + 120 and p.rt[VIN].budget.used() == 1  # a 5xx DOES count (docs)
    run(p.poll(VIN))
    assert p.rt[VIN].next_poll == clock.t + 240
    assert run(p.poll(VIN))["ok"] and p.rt[VIN].backoff == 60 and p.rt[VIN].last_error is None


def test_network_error_does_not_consume_quota():
    p, api, conn, clock, vid = setup([ApiError(0, "network", "no route")])
    run(p.poll(VIN))
    assert p.rt[VIN].budget.used() == 0 and not p.rt[VIN].blocked and p.rt[VIN].next_poll > clock.t


def test_header_quota_is_authoritative():
    p, api, conn, clock, vid = setup()
    api.remaining = 5  # the phone app used the rest of the hour
    run(p.poll(VIN))
    assert p.rt[VIN].budget.status()["header_remaining"] == 4
    assert p.rt[VIN].budget.remaining() == 0  # 4 left, 4 reserved for commands


def test_command_success_is_logged_and_schedules_a_refresh():
    p, api, conn, clock, vid = setup()
    run(p.poll(VIN))
    res = run(p.run_command(VIN, "set_charge_limit", {"percent": 70}))
    assert res["ok"] and res["status"] == 202
    assert api.calls[-1] == ("op", VIN, "setChargingLimit", {"targetStateOfChargeInPercent": 70}, {})
    c = conn.execute("SELECT * FROM commands").fetchone()
    assert c["name"] == "set_charge_limit" and c["ok"] == 1 and json.loads(c["params"]) == {"percent": 70}
    assert p.rt[VIN].next_poll <= clock.t + 45
    assert conn.execute("SELECT detail FROM events WHERE kind='command'").fetchone()[0].startswith("set_charge_limit sent")


def test_command_failure_reports_skodas_reason():
    p, api, conn, clock, vid = setup()
    run(p.poll(VIN))
    api.operate_error = err(422, "operation-disabled")
    res = run(p.run_command(VIN, "stop_charging"))
    disabled = "That feature is currently disabled for the car (consent, licence or workshop mode)."
    assert res == {"ok": False, "kind": "operation-disabled", "status": 422,
                   "error": disabled, "error_i18n": {"message": disabled, "params": {}}}
    c = conn.execute("SELECT * FROM commands").fetchone()
    assert c["ok"] == 0 and c["kind"] == "operation-disabled" and c["http_status"] == 422


def test_unsupported_and_invalid_commands_never_reach_the_api():
    p, api, conn, clock, vid = setup()
    run(p.poll(VIN))
    n = len(api.calls)
    with pytest.raises(commands.CommandError, match="does not support"):
        run(p.run_command(VIN, "start_aux_heating", {}))  # not in this car's operations
    with pytest.raises(commands.CommandError):
        run(p.run_command(VIN, "set_charge_limit", {"percent": 500}))
    with pytest.raises(commands.CommandError):
        run(p.run_command("TMBXXXXXXXXXXXXXX", "stop_charging"))
    assert len(api.calls) == n and p.rt[VIN].budget.used() == 1


def test_aux_fields_the_car_does_not_list_never_reach_the_api():
    d = bev()
    d["vehicle"]["operations"] = [{"name": "startAuxiliaryHeating", "vehicleDependentParameters": [{"name": "targetTemperature"}]}]
    p, api, conn, clock, vid = setup([d], spin="4711")
    run(p.poll(VIN))
    assert p.rt[VIN].operation_params == {"startAuxiliaryHeating": ["targetTemperature"]}
    n = len(api.calls)
    with pytest.raises(commands.CommandError, match="choose between heating and ventilation"):
        run(p.run_command(VIN, "start_aux_heating", {"temperature": 22, "mode": "VENTILATION"}))
    assert len(api.calls) == n and p.rt[VIN].budget.used() == 1  # refused before a request was spent
    run(p.run_command(VIN, "start_aux_heating", {"temperature": 22, "duration_min": 30}))
    assert api.calls[-1][3]["targetTemperature"]["value"] == 22.0 and "startMode" not in api.calls[-1][3]
    # the list survives a restart: it is stored with the operations
    assert store.load_sections(conn, vid)["operations"]["params"] == {"startAuxiliaryHeating": ["targetTemperature"]}


def test_spin_is_used_but_never_logged():
    d = bev()
    d["vehicle"]["operations"] = [{"name": "startAuxiliaryHeating"}]
    p, api, conn, clock, vid = setup([d], spin="4711")
    run(p.poll(VIN))
    run(p.run_command(VIN, "start_aux_heating", {"temperature": 22, "spin": "4711"}))
    assert api.calls[-1][3]["spin"] == "4711"
    logged = conn.execute("SELECT params FROM commands").fetchone()[0]
    assert "4711" not in logged and "4711" not in conn.execute("SELECT detail FROM events WHERE kind='command'").fetchone()[0]


def test_profile_update_uses_the_last_reported_profile():
    p, api, conn, clock, vid = setup()
    run(p.poll(VIN))
    run(p.run_command(VIN, "update_charging_profile", {"profile_id": 7, "target_soc": 60}))
    op = api.calls[-1]
    assert op[2] == "updateChargingProfile" and op[4] == {"id": 7} and op[3]["settings"]["targetStateOfChargeInPercent"] == 60


def test_request_ledger_survives_a_restart():
    p, api, conn, clock, vid = setup()
    for _ in range(5):
        run(p.poll(VIN))
    p2 = Poller(conn, FakeApi(clock=clock), clock=clock)
    p2.add_vehicle(VIN, vid)
    assert p2.rt[VIN].budget.used() == 5


def test_a_restart_does_not_poll_again_before_the_interval_is_up():
    """Issue #8: each restart polled at once, so a few restarts in a row used up Škoda's hourly quota."""
    p, api, conn, clock, vid = setup()
    run(p.poll(VIN))
    clock.advance(30)
    p2 = Poller(conn, FakeApi(clock=clock), clock=clock)
    p2.add_vehicle(VIN, vid)
    assert run(p2.tick()) == 0
    clock.advance(271)  # the active interval (300 s) since the last request
    assert run(p2.tick()) == 1


def test_derived_data_flows_through_polls():
    """Three polls: parked, driving, parked elsewhere -> one derived trip and the position."""
    parked = bev(**{"odometer.mileageInKm": 1000})
    moving = bev(parkingPosition={"state": "IN_MOTION"}, **{"odometer.mileageInKm": 1010})
    moving["vehicle"]["charging"]["status"]["state"] = "READY_FOR_CHARGING"
    arrived = bev(**{"odometer.mileageInKm": 1030})
    arrived["vehicle"]["charging"]["status"]["state"] = "READY_FOR_CHARGING"
    arrived["vehicle"]["parkingPosition"]["gpsCoordinates"] = {"latitude": 50.3, "longitude": 8.9}
    arrived["vehicle"]["parkingPosition"]["formattedAddress"] = "Office"
    p, api, conn, clock, vid = setup([parked, moving, arrived])
    conn.execute("UPDATE vehicles SET battery_kwh=77"); conn.commit()
    for _ in range(3):
        run(p.poll(VIN))
        clock.advance(600)
    t = conn.execute("SELECT * FROM trips").fetchone()
    assert t["distance_km"] == 30 and t["end_place"] == "Office" and t["approx"] == 0
