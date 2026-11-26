"""Charges: list, detail (with the power curve), manual corrections, and "use this place as home"."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import places, store
from ..deps import ContextDep
from ..presenters import charge_out, curve_gaps, local_bound, rows, vehicle
from ..store import set_setting

router = APIRouter()


class ChargePatch(BaseModel):
    place_kind: str | None = None  # home | public | "" (auto)
    cost_manual: float | None = None
    clear_cost: bool = False
    note: str | None = None


@router.get("/api/vehicles/{vid}/charges")
def charges(vid: int, ctx: ContextDep, frm: str | None = Query(None, alias="from"), to: str | None = None,
            kind: str | None = None, limit: int = Query(50, le=500), offset: int = 0, tz_offset: int = 0):
    vehicle(ctx.conn, vid)
    where: list[str] = ["vehicle_id=?"]
    args: list = [vid]
    if frm:
        where.append("started_at >= ?")
        args.append(local_bound(frm, tz_offset))
    if to:
        where.append("started_at < ?")
        args.append(local_bound(to, tz_offset, end=True))
    if kind in ("AC", "DC"):
        where.append("charge_type=?")
        args.append(kind)
    w = " AND ".join(where)
    tariff = ctx.tariff()
    if kind in ("home", "public"):
        # Home/public is resolved in Python (position vs home), so filter BEFORE paging or total/offset are wrong.
        everything = [charge_out(c, tariff, ctx.conn) for c in rows(ctx.conn.execute(
            f"SELECT * FROM charges WHERE {w} ORDER BY started_at DESC", args))]
        matching = [c for c in everything if c["place_kind_resolved"] == kind]
        return {"total": len(matching), "items": matching[offset:offset + limit]}
    items = [charge_out(c, tariff, ctx.conn) for c in rows(ctx.conn.execute(
        f"SELECT * FROM charges WHERE {w} ORDER BY started_at DESC LIMIT ? OFFSET ?", [*args, limit, offset]))]
    total = ctx.conn.execute(f"SELECT COUNT(*) FROM charges WHERE {w}", args).fetchone()[0]
    return {"total": total, "items": items}


@router.get("/api/vehicles/{vid}/charges/{cid}")
def charge(vid: int, cid: int, ctx: ContextDep):
    c = ctx.conn.execute("SELECT * FROM charges WHERE id=? AND vehicle_id=?", (cid, vid)).fetchone()
    if not c:
        raise HTTPException(404, "no such charge")
    c = charge_out(dict(c), ctx.tariff(), ctx.conn)
    end = c["ended_at"] or ctx.now_iso()
    c["curve"] = rows(ctx.conn.execute(
        "SELECT recorded_at t, soc, charge_power_kw p, remaining_min rem FROM snapshots WHERE vehicle_id=? "
        "AND recorded_at BETWEEN ? AND ? ORDER BY recorded_at", (vid, c["started_at"], end)))
    c["curve_gaps"] = curve_gaps(c["curve"], c["ended_at"] if c.get("end_estimated") else None)
    # A charge imported from a trip export has no position of its own: it happened somewhere on that trip.
    c["trip_route"] = None
    if c.get("source") == "import-trip":
        t = ctx.conn.execute("SELECT id, start_lat, start_lon, end_lat, end_lon, start_place, end_place FROM trips "
                             "WHERE vehicle_id=? AND started_at=?", (vid, c["started_at"])).fetchone()
        if t and t["start_lat"] is not None and t["end_lat"] is not None:
            c["trip_route"] = dict(t)
    return c


@router.patch("/api/vehicles/{vid}/charges/{cid}")
def patch_charge(vid: int, cid: int, body: ChargePatch, ctx: ContextDep):
    sets: list[str] = []
    args: list = []
    if body.place_kind is not None:
        if body.place_kind not in ("home", "public", ""):
            raise HTTPException(400, "place_kind must be home, public or empty")
        sets.append("place_kind=?")
        args.append(body.place_kind or None)
    if body.clear_cost:
        sets.append("cost_manual=NULL")
    elif body.cost_manual is not None:
        if not 0 <= body.cost_manual <= 10000:
            raise HTTPException(400, "cost out of range")
        sets.append("cost_manual=?")
        args.append(body.cost_manual)
    if body.note is not None:
        sets.append("note=?")
        args.append(body.note[:500])
    if sets:
        ctx.conn.execute(f"UPDATE charges SET {','.join(sets)} WHERE id=? AND vehicle_id=?", [*args, cid, vid])
        ctx.conn.commit()
    return charge(vid, cid, ctx)


@router.post("/api/vehicles/{vid}/home-here")
def home_here(vid: int, ctx: ContextDep, charge_id: int | None = None):
    """Set the home position (for Home vs Public charges) to a charge's location, else to where the car is parked."""
    vehicle(ctx.conn, vid)
    if charge_id is not None:
        c = ctx.conn.execute("SELECT lat, lon FROM charges WHERE id=? AND vehicle_id=?", (charge_id, vid)).fetchone()
        if not c or c["lat"] is None:
            raise HTTPException(400, "That charge has no known location.")
        pos = {"lat": c["lat"], "lon": c["lon"]}
    else:
        pos = (store.load_sections(ctx.conn, vid).get("position") or {})
    if pos.get("lat") is None or pos.get("lon") is None:
        raise HTTPException(400, "The car's position is not known yet (it is moving or not reported).")
    set_setting(ctx.conn, "tariff", json.dumps({**ctx.tariff(), "home_lat": pos["lat"], "home_lon": pos["lon"]}))
    places.upsert_home(ctx.conn, pos["lat"], pos["lon"])  # no radius: the home place keeps the one it has
    return {"ok": True, "home_lat": pos["lat"], "home_lon": pos["lon"]}
