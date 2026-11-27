"""First-run setup: create the dashboard login, connect a Škoda API key, add or remove cars, set the S-PIN."""
from __future__ import annotations

import hmac
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import messages, recorder
from ..auth import SetupError, normalise_setup_code
from ..client import normalise_vin, valid_vin
from ..context import client_ip
from ..deps import ContextDep
from ..poller import Poller
from ..secrets_store import clear_api_login, load_api_login, save_api_login, stored_vins

router = APIRouter(prefix="/api/setup")
MAX_VINS = 5


class ApiLoginBody(BaseModel):
    api_key: str
    vins: str | list[str]
    spin: str | None = None


class SpinBody(BaseModel):
    spin: str = ""


class SetupLoginBody(BaseModel):
    email: str
    password: str
    current_password: str | None = None  # required to change an existing login
    setup_code: str | None = None  # required to create the first one from a public address (log / setup-code.txt)


def parse_vins(raw) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw or ""))
    out = []
    for item in items:
        v = normalise_vin(item)
        if not v:
            continue
        if not valid_vin(v):
            raise ValueError(messages.INVALID_VIN(vin=item.strip()))
        if v not in out:
            out.append(v)
    if not out:
        raise ValueError(messages.ENTER_VIN)
    if len(out) > MAX_VINS:
        raise ValueError(messages.TOO_MANY_VEHICLES(n=MAX_VINS))
    return out


@router.get("/status")
def setup_status(request: Request, ctx: ContextDep):
    if ctx.auth.enabled and ctx.setup_value:  # the login was created on the command line meanwhile
        ctx.forget_setup_code()
    creds = load_api_login(ctx.conn, ctx.box)
    p = ctx.poller
    vehicles = []
    for vin in (creds[1] if creds else stored_vins(ctx.conn)) if (ctx.auth.enabled or ctx.demo) else []:  # nothing for strangers
        st = p.status(vin) if p else {"known": False}
        vehicles.append({"vin": vin, "name": (ctx.conn.execute("SELECT name FROM vehicles WHERE vin=?", (vin,)).fetchone() or [None])[0],
                         "key_expires_at": st.get("key_expires_at"), "error": st.get("error"), "error_i18n": st.get("error_i18n"),
                         "error_kind": st.get("error_kind"), "blocked": st.get("blocked", False), "last_ok": st.get("last_ok")})
    return {"login_set": ctx.auth.enabled, "login_email": ctx.auth.email, "skoda_set": ctx.configured(),
            "key_readable": creds is not None or not stored_vins(ctx.conn), "vehicles": vehicles,
            "spin_set": bool(creds and creds[2]), "connected": p is not None,
            "setup_code_required": ctx.needs_setup_code(request)}


@router.post("/login")
def setup_login(body: SetupLoginBody, request: Request, ctx: ContextDep):
    """Create (first run; from a public address only with the setup code) or change the dashboard login (the guard
    demands a session, and this the current password: a borrowed, still signed-in browser must not be enough to take
    it over). Wrong codes and passwords count towards the same throttle as /api/login."""
    ip = client_ip(request)
    if ctx.auth.locked(ip):
        raise HTTPException(429, "too many attempts")
    if ctx.auth.enabled:
        if not ctx.auth.check(ctx.auth.email, body.current_password or ""):
            ctx.auth.fail(ip)
            raise HTTPException(403, "The current password is wrong.")
    elif (ctx.needs_setup_code(request)
          and not hmac.compare_digest(normalise_setup_code(body.setup_code).encode(), (ctx.setup_value or "").encode())):
        ctx.auth.fail(ip)
        raise HTTPException(403, "Wrong setup code. It is in Mate's log and in setup-code.txt in the data folder (or it is your SETUP_CODE).")
    try:
        ctx.auth.set_credentials(ctx.conn, body.email, body.password)
    except SetupError as e:
        raise messages.UserError(400, e) from e
    ctx.auth.clear(ip)
    ctx.forget_setup_code()  # used up; setup-code.txt goes too
    return ctx.session_response({"ok": True}, request)  # signs the caller in with the new credentials


@router.post("/skoda")
async def setup_skoda(body: ApiLoginBody, ctx: ContextDep):
    """Try the API key against every VIN for real; only a working combination is stored."""
    if ctx.demo:
        raise messages.UserError(400, messages.DEMO_NO_ACCOUNT)
    if not ctx.auth.enabled:
        raise messages.UserError(400, messages.CREATE_LOGIN_FIRST)
    key = body.api_key.strip()
    if len(key) < 8 or re.search(r"\s", key):
        raise messages.UserError(400, messages.NOT_AN_API_KEY)
    try:
        vins = parse_vins(body.vins)
    except ValueError as e:
        raise messages.UserError(400, e) from e
    pin = None if body.spin is None else body.spin.strip()
    if pin and not (pin.isdigit() and len(pin) == 4):
        raise messages.UserError(400, messages.SPIN_DIGITS_OR_EMPTY)
    new_api = ctx.api_factory(key)
    trial = Poller(ctx.conn, new_api, spin_getter=lambda: pin or "")
    created = []
    for vin in vins:
        if not ctx.conn.execute("SELECT 1 FROM vehicles WHERE vin=?", (vin,)).fetchone():
            created.append(vin)
        trial.add_vehicle(vin, recorder.upsert_vehicle(ctx.conn, vin))
    for vin in vins:
        res = await trial.poll(vin, reason="setup")
        if not res["ok"]:
            await new_api.close()
            for v in created:  # leave nothing behind for a VIN that never answered
                ctx.conn.execute("DELETE FROM vehicles WHERE vin=? AND id NOT IN (SELECT vehicle_id FROM snapshots)", (v,))
            ctx.conn.commit()
            raise messages.UserError(400, messages.VIN_ERROR(vin=f"{vin[:3]}…{vin[-4:]}", error=messages.from_i18n(res["error_i18n"])))
    await ctx.cloud.stop()  # only now: a failed attempt above must not disturb a working connection
    save_api_login(ctx.conn, ctx.box, key, vins, pin)  # pin=None keeps a previously stored S-PIN
    ctx.cloud.start(new_api, vins, trial)  # the trial poller already holds fresh data and its next poll time
    return {"ok": True, "vehicles": [{"vin": v, "key_expires_at": trial.rt[v].key_expires_at} for v in vins]}


@router.post("/vehicles")
async def setup_add_vehicle(body: dict, ctx: ContextDep):
    """Add another car to this installation with the API key already stored (the key must cover that VIN)."""
    creds = load_api_login(ctx.conn, ctx.box)
    p = ctx.poller
    if not creds or p is None:
        raise messages.UserError(400, messages.CONNECT_KEY_FIRST)
    try:
        (vin,) = parse_vins(body.get("vin", ""))
    except ValueError as e:
        raise messages.UserError(400, e if "VIN" in str(e) or "valid" in str(e) else messages.ENTER_ONE_VIN) from e
    if vin in creds[1]:
        raise messages.UserError(400, messages.CAR_ALREADY_CONNECTED)
    if len(creds[1]) >= MAX_VINS:
        raise messages.UserError(400, messages.TOO_MANY_VEHICLES(n=MAX_VINS))
    vid = recorder.upsert_vehicle(ctx.conn, vin)
    p.add_vehicle(vin, vid)
    res = await p.poll(vin, reason="setup")  # one real request proves the key covers this car
    if not res["ok"]:
        p.remove_vehicle(vin)
        if not ctx.conn.execute("SELECT 1 FROM snapshots WHERE vehicle_id=?", (vid,)).fetchone():
            ctx.conn.execute("DELETE FROM vehicles WHERE id=?", (vid,))
            ctx.conn.commit()
        raise messages.UserError(400, messages.VIN_ERROR(vin=f"{vin[:3]}…{vin[-4:]}", error=messages.from_i18n(res["error_i18n"])))
    save_api_login(ctx.conn, ctx.box, creds[0], [*creds[1], vin], None)
    if p.publisher:
        p.publisher.announce(vin, ctx.cloud.vehicle_name(vin))
    return {"ok": True, "id": vid}


@router.delete("/vehicles/{vin}")
async def setup_remove_vehicle(vin: str, ctx: ContextDep):
    """Stop reading one car. Its history stays in the database (and comes back if the car is added again)."""
    creds = load_api_login(ctx.conn, ctx.box)
    vin = normalise_vin(vin)
    if not creds or vin not in creds[1]:
        raise messages.UserError(404, messages.CAR_NOT_CONNECTED)
    if len(creds[1]) == 1:
        raise messages.UserError(400, messages.ONLY_CAR)
    save_api_login(ctx.conn, ctx.box, creds[0], [v for v in creds[1] if v != vin], None)
    if ctx.poller is not None:
        ctx.poller.remove_vehicle(vin)
    return {"ok": True}


@router.put("/spin")
def setup_spin(body: SpinBody, ctx: ContextDep):
    pin = body.spin.strip()
    if pin and not (pin.isdigit() and len(pin) == 4):
        raise messages.UserError(400, messages.SPIN_DIGITS)
    creds = load_api_login(ctx.conn, ctx.box)
    if not creds:
        raise messages.UserError(400, messages.CONNECT_KEY_FIRST)
    save_api_login(ctx.conn, ctx.box, creds[0], creds[1], pin)
    return {"ok": True, "spin_set": bool(pin)}


@router.delete("/skoda")
async def setup_skoda_forget(ctx: ContextDep):
    await ctx.cloud.stop()
    clear_api_login(ctx.conn)
    return {"ok": True}
