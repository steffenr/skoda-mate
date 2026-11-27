"""The car list and one car's overview, capabilities and manual refresh."""
from __future__ import annotations

from fastapi import APIRouter

from .. import commands, features, messages, recorder, store
from ..deps import ContextDep
from ..presenters import HIDDEN_SECTIONS, charge_out, rows, snap_out, trip_out, vehicle

router = APIRouter()


@router.get("/api/vehicles")
def vehicles(ctx: ContextDep):
    out = []
    for v in rows(ctx.conn.execute("SELECT * FROM vehicles ORDER BY id")):
        snap = recorder.last_snapshot(ctx.conn, v["id"])
        sec = store.load_sections(ctx.conn, v["id"])
        v["info"] = sec.get("info")
        v["active"] = bool(ctx.poller and v["vin"] in ctx.poller.rt)  # False = history only (the car was removed)
        v["soc"] = snap["soc"] if snap else None
        out.append(v)
    return out


@router.put("/api/vehicles/{vid}")
def update_vehicle(vid: int, body: dict, ctx: ContextDep):
    vehicle(ctx.conn, vid)
    kwh = body.get("battery_kwh")
    if kwh is not None:
        try:
            kwh = None if kwh == "" else float(kwh)
        except (TypeError, ValueError):
            raise messages.UserError(400, messages.BATTERY_NUMBER) from None
        if kwh is not None and not 10 <= kwh <= 200:
            raise messages.UserError(400, messages.BATTERY_RANGE)
        ctx.conn.execute("UPDATE vehicles SET battery_kwh=? WHERE id=?", (kwh, vid))
        ctx.conn.commit()
    return {"ok": True}


@router.get("/api/vehicles/{vid}/overview")
def overview(vid: int, ctx: ContextDep):
    v = vehicle(ctx.conn, vid)
    conn = ctx.conn
    snap = recorder.last_snapshot(conn, vid)
    sec = store.load_sections(conn, vid)
    ops = (sec.get("operations") or {}).get("list")
    part_state = sec.get("part_state")
    poller = ctx.poller
    tariff = ctx.tariff()
    last_trip = conn.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 1", (vid,)).fetchone()
    last_charge = conn.execute("SELECT * FROM charges WHERE vehicle_id=? ORDER BY started_at DESC LIMIT 1", (vid,)).fetchone()
    open_trip = recorder.open_trip(conn, vid)
    return {
        "vehicle": {**v, "capacity_kwh": recorder.battery_kwh(conn, vid)},
        "snapshot": snap_out(snap),
        "sections": {k: val for k, val in sec.items() if k not in HIDDEN_SECTIONS},
        "operations": ops, "parts": features.parts(part_state), "features": features.features(ops, part_state),
        "api_errors": (sec.get("api_errors") or {}).get("list", []),
        "poller": poller.status(v["vin"]) if poller else None,
        "last_trip": trip_out(dict(last_trip), tariff) if last_trip else None,
        "open_trip": trip_out(dict(open_trip), tariff) if open_trip else None,
        "last_charge": charge_out(dict(last_charge), tariff, conn) if last_charge else None,
        "tariff": tariff, "commands": commands.catalogue(ops), "unavailable": features.UNAVAILABLE,
        "needs_capacity": recorder.battery_kwh(conn, vid) is None,
        "demo": ctx.demo,
    }


@router.get("/api/vehicles/{vid}/capabilities")
def capabilities(vid: int, ctx: ContextDep):
    """Every operation and data field of the official API, with what this car supports and reports right now."""
    v = vehicle(ctx.conn, vid)
    sec = store.load_sections(ctx.conn, vid)
    p = ctx.poller
    st = p.status(v["vin"]) if p else {}
    return features.capabilities((sec.get("operations") or {}).get("list"), sec.get("part_state"), sec,
                                 snap_out(recorder.last_snapshot(ctx.conn, vid)),
                                 (st.get("budget") or {}).get("limit"), st.get("key_expires_at"))


@router.post("/api/vehicles/{vid}/refresh")
async def refresh(vid: int, ctx: ContextDep):
    v = vehicle(ctx.conn, vid)
    p = ctx.poller
    if p is None or v["vin"] not in p.rt:
        raise messages.UserError(503, messages.NOT_CONNECTED)
    res = await p.poll(v["vin"], reason="manual")
    res["poller"] = p.status(v["vin"])
    return res
