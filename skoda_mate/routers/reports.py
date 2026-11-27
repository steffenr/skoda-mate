"""Read-only views over the recorded data: statistics, battery, history, events, map, command log, diagnostics,
CSV export and the database backup."""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.background import BackgroundTask

from .. import __version__, activity, commands, places, recorder, stats, store
from ..deps import ContextDep
from ..presenters import csv_cell, local_bound, local_day, redact, rows, snap_out, vehicle

router = APIRouter()


class CommandBody(BaseModel):
    name: str
    params: dict = {}


@router.get("/api/vehicles/{vid}/stats")
def statistics(vid: int, ctx: ContextDep):
    vehicle(ctx.conn, vid)
    t = ctx.tariff()
    return {"totals": stats.totals(ctx.conn, vid, t), "monthly": stats.monthly(ctx.conn, vid, t), "currency": t["currency"]}


@router.get("/api/vehicles/{vid}/battery")
def battery(vid: int, ctx: ContextDep, hours: int = Query(168, ge=1, le=24 * 365)):
    vehicle(ctx.conn, vid)
    sec = store.load_sections(ctx.conn, vid)
    b = stats.battery(ctx.conn, vid)
    b["history"] = stats.soc_history(ctx.conn, vid, hours, ctx.now_iso())
    b["charging"] = sec.get("charging")
    b["profiles"] = sec.get("profiles")
    return b


@router.get("/api/vehicles/{vid}/history")
def history(vid: int, ctx: ContextDep, hours: int = Query(48, ge=1, le=24 * 365)):
    vehicle(ctx.conn, vid)
    return stats.soc_history(ctx.conn, vid, hours, ctx.now_iso())


@router.get("/api/vehicles/{vid}/events")
def events(vid: int, ctx: ContextDep, kind: str | None = None, q: str | None = None,
           frm: str | None = Query(None, alias="from"), to: str | None = None, limit: int = Query(100, le=1000),
           offset: int = 0, tz_offset: int = 0):
    vehicle(ctx.conn, vid)
    where: list[str] = ["vehicle_id=?"]
    args: list = [vid]
    if kind:
        where.append("kind=?")
        args.append(kind)
    if q:
        where.append("(kind LIKE ? OR detail LIKE ?)")
        args += [f"%{q}%"] * 2
    if frm:
        where.append("at >= ?")
        args.append(local_bound(frm, tz_offset))
    if to:
        where.append("at < ?")
        args.append(local_bound(to, tz_offset, end=True))
    w = " AND ".join(where)
    return {"total": ctx.conn.execute(f"SELECT COUNT(*) FROM events WHERE {w}", args).fetchone()[0],
            "kinds": [x[0] for x in ctx.conn.execute("SELECT DISTINCT kind FROM events WHERE vehicle_id=? ORDER BY kind", (vid,))],
            "items": rows(ctx.conn.execute(f"SELECT * FROM events WHERE {w} ORDER BY at DESC, id DESC LIMIT ? OFFSET ?",
                                            [*args, limit, offset]))}


@router.get("/api/vehicles/{vid}/timeline")
def timeline_view(vid: int, ctx: ContextDep, from_: str | None = Query(None, alias="from"),
                  to: str | None = None, tz_offset: int = Query(0, ge=-840, le=840)):
    vehicle(ctx.conn, vid)
    now = datetime.fromisoformat(ctx.now_iso())
    try:
        to_day = to or (now - timedelta(minutes=tz_offset)).date().isoformat()
        to_date = local_day(to_day)  # app's 400, not FastAPI's raw isoformat message, before the default arithmetic
        from_day = from_ or (to_date - timedelta(days=6)).isoformat()
        return activity.timeline(ctx.conn, vid, from_day, to_day, tz_offset, now, ctx.tariff())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/vehicles/{vid}/parked-loss")
def parked_loss_view(vid: int, ctx: ContextDep, from_: str | None = Query(None, alias="from"),
                     to: str | None = None, min_hours: float = 6, tz_offset: int = Query(0, ge=-840, le=840)):
    vehicle(ctx.conn, vid)
    if not 1 <= min_hours <= 168:
        raise HTTPException(400, "min_hours must be between 1 and 168.")
    now = datetime.fromisoformat(ctx.now_iso())
    to_day = to or (now - timedelta(minutes=tz_offset)).date().isoformat()
    try:
        from_day = from_ or (local_day(to_day) - timedelta(days=29)).isoformat()
    except ValueError as e:  # the app's message for a malformed `to`, as the timeline route gives
        raise HTTPException(400, str(e)) from e
    from_iso, to_iso = local_bound(from_day, tz_offset), local_bound(to_day, tz_offset, end=True)
    assert from_iso is not None and to_iso is not None
    try:
        return activity.parked_loss(ctx.conn, vid, from_iso, to_iso, min_hours,
                                    recorder.battery_kwh(ctx.conn, vid), ctx.tariff())
    except activity.RangeError as e:  # a reversed range; no length cap, the computation is linear in the readings
        raise HTTPException(400, str(e)) from e


@router.get("/api/vehicles/{vid}/map")
def map_(vid: int, ctx: ContextDep, limit: int = Query(1000, ge=1, le=2000),
         tz_offset: int = Query(0, ge=-840, le=840)):
    vehicle(ctx.conn, vid)
    sec = store.load_sections(ctx.conn, vid)
    return {**stats.map_points(ctx.conn, vid, limit), "places": places.summaries(ctx.conn, tz_offset), "limit": limit,
            "current": sec.get("position"), "tariff": ctx.tariff()}


@router.get("/api/vehicles/{vid}/commands")
def command_list(vid: int, ctx: ContextDep, limit: int = Query(30, le=200)):
    v = vehicle(ctx.conn, vid)
    sec = store.load_sections(ctx.conn, vid)
    ops = (sec.get("operations") or {}).get("list")
    log = rows(ctx.conn.execute("SELECT * FROM commands WHERE vehicle_id=? ORDER BY id DESC LIMIT ?", (vid, limit)))
    for c in log:
        c["params"] = json.loads(c["params"]) if c.get("params") else None
    p = ctx.poller
    return {"catalogue": commands.catalogue(ops), "log": log, "spin_set": ctx.spin_set(),
            "budget": p.status(v["vin"]).get("budget") if p else None}


@router.post("/api/vehicles/{vid}/command")
async def command(vid: int, body: CommandBody, ctx: ContextDep):
    v = vehicle(ctx.conn, vid)
    p = ctx.poller
    if p is None:
        raise HTTPException(503, "Not connected to MyŠkoda yet. Open Settings.")
    try:
        return await p.run_command(v["vin"], body.name, body.params)
    except commands.CommandError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/vehicles/{vid}/raw")
def raw(vid: int, ctx: ContextDep):
    """The last answer exactly as Škoda sent it (your own data: contains VIN and position)."""
    vehicle(ctx.conn, vid)
    return (store.load_sections(ctx.conn, vid).get("raw") or {})


@router.get("/api/vehicles/{vid}/diagnostics")
def diagnostics(vid: int, ctx: ContextDep):
    v = vehicle(ctx.conn, vid)
    p = ctx.poller
    sec = store.load_sections(ctx.conn, vid)
    calls = rows(ctx.conn.execute("SELECT at, endpoint, ok, error FROM api_calls WHERE vehicle_id=? ORDER BY at DESC LIMIT 60", (vid,)))
    cmds = rows(ctx.conn.execute("SELECT at, name, ok, kind, http_status FROM commands WHERE vehicle_id=? ORDER BY id DESC LIMIT 30", (vid,)))
    bundle = {"app": "skoda-mate", "version": __version__, "generated": ctx.now_iso(),
              "poller": p.status(v["vin"]) if p else None, "parts": sec.get("part_state"),
              "operations": (sec.get("operations") or {}).get("list"), "api_errors": (sec.get("api_errors") or {}).get("list"),
              "api_calls": calls, "commands": cmds, "response_redacted": redact(sec.get("raw") or {})}
    return Response(json.dumps(bundle, indent=1), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="skoda-mate-diagnostics.json"'})


@router.get("/api/vehicles/{vid}/calls")
def calls(vid: int, ctx: ContextDep, limit: int = Query(25, ge=1, le=500), offset: int = Query(0, ge=0),
          failed: bool = False):
    vehicle(ctx.conn, vid)
    where = "vehicle_id=?" + (" AND ok=0" if failed else "")
    total = ctx.conn.execute(f"SELECT COUNT(*) FROM api_calls WHERE {where}", (vid,)).fetchone()[0]
    items = rows(ctx.conn.execute(f"SELECT at, endpoint, ok, error FROM api_calls WHERE {where} "
                                  "ORDER BY at DESC, rowid DESC LIMIT ? OFFSET ?", (vid, limit, offset)))
    for c in items:  # stored as epoch seconds for the budget arithmetic; every other timestamp in the API is ISO
        c["at"] = datetime.fromtimestamp(c["at"], UTC).isoformat()
    return {"total": total, "items": items}


@router.get("/api/vehicles/{vid}/export/{what}.csv")
def export(vid: int, what: str, ctx: ContextDep):
    vehicle(ctx.conn, vid)
    table = {"trips": "trips", "charges": "charges", "events": "events", "snapshots": "snapshots"}.get(what)
    if table is None:
        raise HTTPException(404, "unknown export")
    cur = ctx.conn.execute(f"SELECT * FROM {table} WHERE vehicle_id=? ORDER BY 1", (vid,))
    cols = [d[0] for d in cur.description if d[0] not in ("route_json",)]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for row in cur:
        w.writerow([csv_cell(row[c]) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="skoda-mate-{what}.csv"'})


@router.get("/api/backup")
def backup(ctx: ContextDep):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    dst = sqlite3.connect(path)
    ctx.conn.backup(dst)  # a consistent copy even while the poller writes
    dst.close()
    name = f"skoda-mate-{datetime.now(UTC):%Y%m%d-%H%M}.db"
    return FileResponse(path, media_type="application/octet-stream", filename=name,
                        background=BackgroundTask(os.unlink, path))


__all__ = ["router", "snap_out"]
