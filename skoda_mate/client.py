"""Client for the official MyŠkoda Public API (https://public.api.connect.skoda-auto.cz/docs).

Authentication is an API key (header `X-API-Key`) created in the MyŠkoda app. There is no vehicle
listing endpoint: the VINs are supplied by the user. Every response carries the rate-limit headers,
which are the authoritative quota; errors are RFC 9457 `application/problem+json`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

BASE_URL = "https://public.api.connect.skoda-auto.cz"
USER_AGENT = "skoda-mate"

INCLUDE_ALL = ("info", "status", "fuelStatus", "odometer", "parkingPosition", "airConditioning",
               "auxiliaryHeating", "activeVentilation", "charging", "chargingProfiles", "operations")

# operationId (as listed in `vehicle.operations`) -> (HTTP method, path template)
OPERATIONS: dict[str, tuple[str, str]] = {
    "startCharging": ("POST", "/api/v1/vehicles/{vin}/charging/start"),
    "stopCharging": ("POST", "/api/v1/vehicles/{vin}/charging/stop"),
    "setChargingLimit": ("PUT", "/api/v1/vehicles/{vin}/charging/limit"),
    "setChargeMode": ("PUT", "/api/v1/vehicles/{vin}/charging/mode"),
    "updateChargingProfile": ("PUT", "/api/v1/vehicles/{vin}/charging-profiles/{id}"),
    "startAirConditioning": ("POST", "/api/v1/vehicles/{vin}/air-conditioning/start"),
    "stopAirConditioning": ("POST", "/api/v1/vehicles/{vin}/air-conditioning/stop"),
    "startAuxiliaryHeating": ("POST", "/api/v1/vehicles/{vin}/auxiliary-heating/start"),
    "stopAuxiliaryHeating": ("POST", "/api/v1/vehicles/{vin}/auxiliary-heating/stop"),
    "startActiveVentilation": ("POST", "/api/v1/vehicles/{vin}/active-ventilation/start"),
    "stopActiveVentilation": ("POST", "/api/v1/vehicles/{vin}/active-ventilation/stop"),
}

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # ISO 3779: no I, O, Q


def normalise_vin(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def valid_vin(vin: str) -> bool:
    return bool(VIN_RE.match(vin))


@dataclass
class RateInfo:
    """What the response headers say about the quota (None = header absent)."""
    limit: int | None = None
    remaining: int | None = None
    reset_s: int | None = None
    at: float = 0.0  # when this was observed (epoch s)

    def reset_at(self) -> float | None:
        return None if self.reset_s is None else self.at + self.reset_s


@dataclass
class ApiResult:
    data: dict
    rate: RateInfo
    key_expires_at: str | None = None
    status: int = 200


class ApiError(Exception):
    """A non-2xx answer. `kind` is the problem-type slug (e.g. 'api-key-expired') or 'http-<status>'."""

    def __init__(self, status: int, kind: str, detail: str = "", retry_after: int | None = None,
                 rate: RateInfo | None = None):
        super().__init__(f"{status} {kind}: {detail}" if detail else f"{status} {kind}")
        self.status, self.kind, self.detail, self.retry_after = status, kind, detail, retry_after
        self.rate = rate or RateInfo()

    @property
    def retryable(self) -> bool:
        """Worth trying again later (rate limit, vehicle busy, outage). Auth and capability errors are not."""
        return self.status in (429, 500, 502, 503, 504) or self.kind == "timeout"

    def user_message(self) -> str:
        m = {
            "api-key-expired": "The API key has expired. Create a new one in the MyŠkoda app and enter it under Settings.",
            "api-key-not-authorized": "This API key is not allowed to access that vehicle. "
                                      "Check the key's vehicles in the MyŠkoda app.",
            "operation-not-authorized": "The car refused the operation for the user this key belongs to.",
            "operation-not-supported": "This car does not support that operation.",
            "operation-disabled": "That feature is currently disabled for the car (consent, licence or workshop mode).",
            "rate-limit-exceeded": "Škoda's request limit is used up. Mate waits for it to reset.",
            "vehicle-not-accepting-requests": "The car declined the request (it limits how often it acts, "
                                              "or its battery is low). Try again later.",
            "timeout": "The request timed out.",
        }
        if self.kind in m:
            return m[self.kind]
        if self.status == 401:
            return "Škoda rejected the API key (401). Check that it was copied completely."
        if self.status == 404:
            return "No vehicle with that VIN is reachable with this key."
        return f"Škoda API error {self.status}" + (f": {self.detail}" if self.detail else "")


def _int(headers, name: str) -> int | None:
    v = headers.get(name)
    if v is None:
        return None
    m = re.search(r"-?\d+", v)
    return int(m.group(0)) if m else None


def parse_rate(headers, now: float) -> RateInfo:
    return RateInfo(limit=_int(headers, "RateLimit-Limit"), remaining=_int(headers, "RateLimit-Remaining"),
                    reset_s=_int(headers, "RateLimit-Reset"), at=now)


def problem_kind(resp: httpx.Response) -> tuple[str, str]:
    """(slug, detail) from an application/problem+json body; ('http-<status>', '') when generic."""
    try:
        body = resp.json()
    except Exception:
        return f"http-{resp.status_code}", ""
    t = str(body.get("type") or "about:blank")
    detail = str(body.get("detail") or body.get("title") or "")
    slug = t.rstrip("/").rsplit("/", 1)[-1] if t != "about:blank" else f"http-{resp.status_code}"
    return slug, detail[:300]


def _expiry_soon(iso: str | None, days: int = 14, now: datetime | None = None) -> bool:
    if not iso:
        return False
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return t - (now or datetime.now(UTC)) < timedelta(days=days)


class SkodaApi:
    def __init__(self, api_key: str, base_url: str = BASE_URL, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 30.0, clock=None):
        import time

        self.api_key = api_key.strip()
        self.clock = clock or time.time
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout,
                                       headers={"X-API-Key": self.api_key, "User-Agent": USER_AGENT,
                                                "Accept": "application/json"})

    async def close(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, path: str, **kw) -> ApiResult:
        try:
            resp = await self._http.request(method, path, **kw)
        except httpx.TimeoutException as e:
            raise ApiError(0, "timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise ApiError(0, "network", f"{type(e).__name__}: {e}") from e
        now = self.clock()
        rate = parse_rate(resp.headers, now)
        expires = resp.headers.get("X-API-Key-Expires-At")
        if resp.status_code >= 400:
            slug, detail = problem_kind(resp)
            raise ApiError(resp.status_code, slug, detail, _int(resp.headers, "Retry-After"), rate)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        return ApiResult(data=data, rate=rate, key_expires_at=expires, status=resp.status_code)

    async def get_vehicle(self, vin: str, include: tuple[str, ...] | None = INCLUDE_ALL) -> ApiResult:
        """One request returns every part (the quota cost is per request, not per part).

        With `include` set, parts the car lacks come back as `*_UNSUPPORTED` entries in `errors`, which is
        exactly the information the capability view needs.
        """
        params = {"include": ",".join(include)} if include else None
        return await self._send("GET", f"/api/v1/vehicles/{vin}", params=params)

    async def operate(self, vin: str, operation: str, body: dict | None = None, **path_args) -> ApiResult:
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation {operation!r}")
        method, tmpl = OPERATIONS[operation]
        kw = {"json": body} if body is not None else {}
        return await self._send(method, tmpl.format(vin=vin, **path_args), **kw)
