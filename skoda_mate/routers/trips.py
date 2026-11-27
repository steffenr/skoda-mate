"""Trips: list, detail, merge/unmerge, note and the MyŠkoda CSV import."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import importer, merge, messages
from ..deps import ContextDep
from ..presenters import local_bound, rows, trip_out, vehicle

router = APIRouter()
MAX_IMPORT_CHARS, MAX_IMPORT_FILES = 8_000_000, 12


class ImportBody(BaseModel):
    files: list[dict]  # [{name, text}] read in the browser
    tz: str = "UTC"  # the export has local times without a zone
    dry_run: bool = True


class NoteBody(BaseModel):
    note: str = ""


@router.get("/api/vehicles/{vid}/trips")
def trips(vid: int, ctx: ContextDep, frm: str | None = Query(None, alias="from"), to: str | None = None,
          q: str | None = None, min_km: float | None = None, limit: int = Query(50, le=500), offset: int = 0,
          tz_offset: int = 0):
    vehicle(ctx.conn, vid)
    where: list[str] = ["vehicle_id=?", "ended_at IS NOT NULL"]
    args: list = [vid]
    if frm:
        where.append("COALESCE(started_at, ended_at) >= ?")
        args.append(local_bound(frm, tz_offset))
    if to:
        where.append("COALESCE(started_at, ended_at) < ?")
        args.append(local_bound(to, tz_offset, end=True))
    if min_km is not None:
        where.append("distance_km >= ?")
        args.append(min_km)
    if q:
        where.append("(start_place LIKE ? OR end_place LIKE ? OR note LIKE ?)")
        args += [f"%{q}%"] * 3
    w = " AND ".join(where)
    total = ctx.conn.execute(f"SELECT COUNT(*) FROM trips WHERE {w}", args).fetchone()[0]
    items = rows(ctx.conn.execute(f"SELECT * FROM trips WHERE {w} ORDER BY COALESCE(started_at, ended_at) DESC LIMIT ? OFFSET ?",
                                  [*args, limit, offset]))
    tariff = ctx.tariff()
    return {"total": total, "items": [trip_out(t, tariff) for t in items]}


@router.get("/api/vehicles/{vid}/trips/{tid}")
def trip(vid: int, tid: int, ctx: ContextDep):
    t = ctx.conn.execute("SELECT * FROM trips WHERE id=? AND vehicle_id=?", (tid, vid)).fetchone()
    if not t:
        raise HTTPException(404, "no such trip")
    t = trip_out(dict(t), ctx.tariff(), detail=True)
    t["charge_during"] = rows(ctx.conn.execute(
        "SELECT id, started_at, energy_kwh FROM charges WHERE vehicle_id=? AND started_at BETWEEN ? AND ?",
        (vid, t["started_at"] or "", t["ended_at"] or "")))
    return t


@router.post("/api/vehicles/{vid}/trips/merge")
def merge_trips(vid: int, body: dict, ctx: ContextDep):
    """Merge trips that a short stop split apart (consecutive, at most a few hours apart). Can be undone."""
    vehicle(ctx.conn, vid)
    try:
        tid = merge.merge(ctx.conn, vid, list(body.get("ids") or []))
    except (merge.MergeError, TypeError, ValueError) as e:
        raise messages.UserError(400, e) from e
    return {"ok": True, "id": tid}


@router.post("/api/vehicles/{vid}/trips/{tid}/unmerge")
def unmerge_trip(vid: int, tid: int, ctx: ContextDep):
    vehicle(ctx.conn, vid)
    try:
        return {"ok": True, "ids": merge.unmerge(ctx.conn, vid, tid)}
    except merge.MergeError as e:
        raise messages.UserError(400, e) from e


@router.post("/api/vehicles/{vid}/import/trips")
def import_trips(vid: int, body: ImportBody, ctx: ContextDep):
    """Import the MyŠkoda app's trip export (CSV). `dry_run` (the default) reports what would happen and writes nothing."""
    v = vehicle(ctx.conn, vid)
    if len(body.files) > MAX_IMPORT_FILES:
        raise messages.UserError(400, messages.IMPORT_TOO_MANY_FILES(n=MAX_IMPORT_FILES))
    if sum(len(str(f.get("text") or "")) for f in body.files) > MAX_IMPORT_CHARS:
        raise messages.UserError(413, messages.IMPORT_TOO_LARGE)
    try:
        return importer.run(ctx.conn, vid, v["vin"], body.files, body.tz, body.dry_run)
    except importer.ImportError_ as e:
        raise messages.UserError(400, e) from e


@router.put("/api/trips/{tid}/note")
def trip_note(tid: int, body: NoteBody, ctx: ContextDep):
    ctx.conn.execute("UPDATE trips SET note=? WHERE id=?", (body.note[:500], tid))
    ctx.conn.commit()
    return {"ok": True}
