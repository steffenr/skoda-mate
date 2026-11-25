import asyncio
import json

import httpx
import pytest

from skoda_mate.client import INCLUDE_ALL, ApiError, SkodaApi, _expiry_soon, normalise_vin, parse_rate, valid_vin

from .fixtures import BEV, VIN

PROBLEM = "https://public.api.connect.skoda-auto.cz/problems/"


def api_with(handler, **kw):
    return SkodaApi("  my-key  ", transport=httpx.MockTransport(handler), clock=lambda: 1000.0, **kw)


def run(coro):
    return asyncio.run(coro)


def test_get_vehicle_sends_key_include_and_reads_rate_headers():
    seen = {}

    def handler(req):
        seen["key"], seen["url"], seen["ua"] = req.headers["x-api-key"], str(req.url), req.headers["user-agent"]
        return httpx.Response(200, json=BEV, headers={"RateLimit-Limit": "20", "RateLimit-Remaining": "17",
                                                      "RateLimit-Reset": "1800", "X-API-Key-Expires-At": "2027-01-01T00:00:00Z"})

    res = run(api_with(handler).get_vehicle(VIN))
    assert seen["key"] == "my-key" and seen["ua"] == "skoda-mate"  # trimmed; no personal data in the UA
    assert seen["url"].endswith(f"/api/v1/vehicles/{VIN}?include=" + ",".join(INCLUDE_ALL).replace(",", "%2C"))
    assert res.data["vehicle"]["vin"] == VIN and res.key_expires_at == "2027-01-01T00:00:00Z"
    assert (res.rate.limit, res.rate.remaining, res.rate.reset_s, res.rate.reset_at()) == (20, 17, 1800, 2800.0)


def test_rate_header_parsing_tolerates_junk_and_absence():
    assert parse_rate({"RateLimit-Remaining": "limit=20, remaining 3"}, 5.0).remaining == 20  # first integer wins
    r = parse_rate({}, 5.0)
    assert (r.limit, r.remaining, r.reset_s, r.reset_at()) == (None, None, None, None)


@pytest.mark.parametrize("status,slug,retryable", [
    (401, "api-key-expired", False), (403, "api-key-not-authorized", False), (403, "operation-not-authorized", False),
    (422, "operation-not-supported", False), (422, "operation-disabled", False),
    (429, "rate-limit-exceeded", True), (429, "vehicle-not-accepting-requests", True)])
def test_problem_json_errors_map_to_kinds(status, slug, retryable):
    def handler(req):
        return httpx.Response(status, headers={"Content-Type": "application/problem+json", "Retry-After": "120",
                                               "RateLimit-Remaining": "0", "RateLimit-Reset": "120"},
                              json={"type": PROBLEM + slug, "title": "t", "status": status, "detail": "because"})

    with pytest.raises(ApiError) as e:
        run(api_with(handler).get_vehicle(VIN))
    err = e.value
    assert (err.status, err.kind, err.detail, err.retry_after, err.retryable) == (status, slug, "because", 120, retryable)
    assert err.rate.remaining == 0 and err.user_message()  # a human sentence exists for every documented type


def test_generic_errors_and_network_failures():
    def about_blank(req):
        return httpx.Response(404, json={"type": "about:blank", "status": 404})

    with pytest.raises(ApiError) as e:
        run(api_with(about_blank).get_vehicle(VIN))
    assert e.value.kind == "http-404" and "VIN" in e.value.user_message() and not e.value.retryable

    def boom(req):
        raise httpx.ConnectError("no route")

    with pytest.raises(ApiError) as e:
        run(api_with(boom).get_vehicle(VIN))
    assert e.value.kind == "network" and e.value.status == 0

    def slow(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ApiError) as e:
        run(api_with(slow).get_vehicle(VIN))
    assert e.value.kind == "timeout" and e.value.retryable

    def html_500(req):
        return httpx.Response(500, text="<html>oops</html>")

    with pytest.raises(ApiError) as e:
        run(api_with(html_500).get_vehicle(VIN))
    assert e.value.kind == "http-500" and e.value.retryable


def test_operations_use_the_documented_paths_methods_and_bodies():
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(202, headers={"RateLimit-Remaining": "9"})

    api = api_with(handler)
    run(api.operate(VIN, "startCharging"))
    run(api.operate(VIN, "setChargingLimit", {"targetStateOfChargeInPercent": 80}))
    run(api.operate(VIN, "setChargeMode", {"chargeMode": "MANUAL"}))
    run(api.operate(VIN, "startAirConditioning", {"targetTemperature": {"value": 21, "unit": "CELSIUS"}}))
    run(api.operate(VIN, "updateChargingProfile", {"id": 7}, id=7))
    run(api.operate(VIN, "stopActiveVentilation"))
    base = f"/api/v1/vehicles/{VIN}"
    assert calls == [("POST", f"{base}/charging/start", None),
                     ("PUT", f"{base}/charging/limit", {"targetStateOfChargeInPercent": 80}),
                     ("PUT", f"{base}/charging/mode", {"chargeMode": "MANUAL"}),
                     ("POST", f"{base}/air-conditioning/start", {"targetTemperature": {"value": 21, "unit": "CELSIUS"}}),
                     ("PUT", f"{base}/charging-profiles/7", {"id": 7}),
                     ("POST", f"{base}/active-ventilation/stop", None)]
    with pytest.raises(ValueError):
        run(api.operate(VIN, "unlockCar"))  # there is no such operation in the official API


def test_every_documented_operation_is_mapped():
    from skoda_mate.client import OPERATIONS

    assert set(OPERATIONS) == {"startCharging", "stopCharging", "setChargingLimit", "setChargeMode", "updateChargingProfile",
                               "startAirConditioning", "stopAirConditioning", "startAuxiliaryHeating", "stopAuxiliaryHeating",
                               "startActiveVentilation", "stopActiveVentilation"}


def test_vin_helpers_and_key_expiry():
    assert normalise_vin(" tmbjb9ny5rf 999999\n") == VIN and valid_vin(VIN)
    assert not valid_vin("TMBJB9NY5RF99999") and not valid_vin("TMBJB9NY5RF99999I") and not valid_vin("")
    from datetime import UTC, datetime

    now = datetime(2026, 11, 23, tzinfo=UTC)
    assert _expiry_soon("2026-12-01T00:00:00Z", now=now) and not _expiry_soon("2027-06-01T00:00:00Z", now=now)
    assert not _expiry_soon(None) and not _expiry_soon("garbage")
