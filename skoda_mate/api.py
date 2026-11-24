"""JSON API for the dashboard (everything under /api/vehicles/... and /api/settings). Mounted by web.py,
behind the same login guard as the rest of the app."""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Callable

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import __version__, commands, costs, features, importer, merge, recorder, stats, store

INFERRED_SOURCES = ("inferred", "import-trip")  # charges that were read off other data, not measured while charging
MAX_IMPORT_CHARS, MAX_IMPORT_FILES = 8_000_000, 12
TYPICAL_WALLBOX_KW = 11.0  # a home AC charger: only used to say how long an inferred charge probably took

HIDDEN_SECTIONS = {"raw", "operations", "part_state", "api_errors"}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def curve_gaps(curve: list[dict], estimated_end: str | None) -> list[dict]:
    """Stretches of a charge without readings, which the curve leaves open instead of drawing a line across: holes
    longer than recorder.MAX_GAP_H between two readings, and the time from the last reading to an estimated end."""
    gaps = [{"from": a["t"], "to": b["t"]} for a, b in zip(curve, curve[1:])
            if recorder._hours(a["t"], b["t"]) > recorder.MAX_GAP_H]
    if estimated_end and curve and curve[-1]["t"] < estimated_end:
        gaps.append({"from": curve[-1]["t"], "to": estimated_end})
    return gaps


def csv_cell(v):
    """A CSV export value. Text that a spreadsheet would run as a formula (a note or place name starting with "=",
    "+", "-", "@", tab or CR) gets a leading apostrophe; numbers, including negative ones, are left as they are."""
    if v is None:
        return ""
    if isinstance(v, str) and v.startswith(FORMULA_START):
        return "'" + v
    return v


class CommandBody(BaseModel):
    name: str
    params: dict = {}


class NoteBody(BaseModel):
    note: str = ""


class ChargePatch(BaseModel):
    place_kind: str | None = None  # home | public | "" (auto)
    cost_manual: float | None = None
    clear_cost: bool = False
    note: str | None = None


class ImportBody(BaseModel):
    files: list[dict]  # [{name, text}] read in the browser
    tz: str = "UTC"  # the export has local times without a zone
    dry_run: bool = True


class SettingsBody(BaseModel):
    tariff: dict | None = None
    battery_kwh: dict | None = None  # {vehicle_id: kWh}
    poll_idle_s: int | None = None
    poll_active_s: int | None = None
    command_reserve: int | None = None
    units: str | None = None
    language: str | None = None
    theme: str | None = None
    battery_kwh_default: float | None = None


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


BOOL_COLS = ("charging", "locked", "doors_open", "windows_open", "trunk_open", "bonnet_open", "sunroof_open", "lights_on",
             "plug_connected", "plug_locked", "in_motion", "reachable", "ignition_on", "battery_protection")


def local_bound(day: str | None, tz_offset: int = 0, end: bool = False) -> str | None:
    """A date filter from the browser -> a UTC ISO string comparable with the stored timestamps.

    `day` is a local date (YYYY-MM-DD) or a full ISO datetime; `tz_offset` is JS `getTimezoneOffset()` (minutes,
    UTC minus local). A `to` date means "through the end of that day", so its bound is the next local midnight."""
    if not day:
        return None
    if "T" in day:
        return day
    try:
        d = datetime.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, f"bad date {day!r}, expected YYYY-MM-DD")
    d = d + timedelta(days=1 if end else 0, minutes=tz_offset)
    return d.replace(tzinfo=UTC).isoformat()


def snap_out(row) -> dict | None:
    """A snapshot row for the dashboard: SQLite stores booleans as 0/1 (NULL = the car did not say); send real
    true/false/null so the UI can tell 'unknown' from 'false'."""
    if row is None:
        return None
    d = dict(row)
    for c in BOOL_COLS:
        if d.get(c) is not None:
            d[c] = bool(d[c])
    return d


def redact(raw: dict) -> dict:
    """A copy of the raw API answer that is safe to attach to a bug report."""
    d = json.loads(json.dumps(raw))
    v = d.get("vehicle") or {}
    if v.get("vin"):
        v["vin"] = v["vin"][:3] + "*" * 11 + v["vin"][-3:]
    for k in ("licensePlate", "name", "renderUrl"):
        if k in v:
            v[k] = "<redacted>"
    pos = v.get("parkingPosition") or {}
    if "gpsCoordinates" in pos:
        pos["gpsCoordinates"] = {"latitude": None, "longitude": None, "note": "redacted"}
    if "formattedAddress" in pos:
        pos["formattedAddress"] = "<redacted>"
    cp = v.get("chargingProfiles") or {}
    for p in cp.get("profiles", []):
        p["name"] = "<redacted>"  # profile names are user-chosen and often a place ("Home", "Office")
    if isinstance(cp.get("currentVehiclePositionProfile"), dict):
        cp["currentVehiclePositionProfile"]["name"] = "<redacted>"
    return d


def register(app, ctx) -> None:
    """`ctx` provides conn(), poller(), now_iso(), and the tariff/settings helpers (see web.py)."""
    r = APIRouter(prefix="/api")

    def vehicle(vid: int) -> dict:
        v = ctx.conn().execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone()
        if not v:
            raise HTTPException(404, "no such vehicle")
        return dict(v)

    def trip_out(t: dict, tariff: dict, detail: bool = False) -> dict:
        t["cost"] = costs.trip_cost(t, tariff)
        route = t.pop("route_json", None)
        if detail:
            t["route"] = json.loads(route) if route else []
        t["open"] = t["ended_at"] is None
        mj = t.pop("merged_json", None)
        t["merged_parts"] = len(json.loads(mj)) if mj else 0
        return t

    def charge_out(c: dict, tariff: dict) -> dict:
        cc = costs.charge_cost(c, tariff)
        c["cost"], c["cost_basis"], c["place_kind_resolved"] = cc["amount"], cc["basis"], cc["kind"]
        c["open"] = c["ended_at"] is None
        c["inferred"] = c.get("source") in INFERRED_SOURCES  # read off the battery level / a trip export, not measured live
        # A charge imported from a trip export knows only how much the level ROSE, not the levels before and after.
        c["soc_gained"] = None
        if c.get("source") == "import-trip":
            g = ctx.conn().execute("SELECT public_soc_gained FROM trips WHERE vehicle_id=? AND started_at=?", (c["vehicle_id"], c["started_at"])).fetchone()
            c["soc_gained"] = g["public_soc_gained"] if g else None
        # Average power only means something when the duration is the time spent charging. For an inferred charge the
        # "duration" is the whole window the car stood there (e.g. overnight), so energy / window would be nonsense
        # (2 kW for a charger that really ran at 11 kW). Say how long it takes at a typical wallbox instead.
        c["avg_power_kw"] = (None if c["inferred"] else round(c["energy_kwh"] / (c["duration_min"] / 60), 1)
                             if c.get("duration_min") and c.get("energy_kwh") else None)
        c["max_power_kw"] = None if c["inferred"] else c.get("max_power_kw")
        c["hours_at_typical_wallbox"] = round(c["energy_kwh"] / TYPICAL_WALLBOX_KW, 1) if c["inferred"] and c.get("energy_kwh") else None
        c["typical_wallbox_kw"] = TYPICAL_WALLBOX_KW
        c["inferred_reason"] = inferred_reason(c) if c["inferred"] and c.get("source") == "inferred" else None
        return c

    def inferred_reason(c: dict) -> str:
        """Why Mate never saw this charge live: it was not recording yet, or it had no poll / no charging poll in the window."""
        row = ctx.conn().execute("SELECT MIN(recorded_at) first FROM snapshots WHERE vehicle_id=?", (c["vehicle_id"],)).fetchone()
        end = c.get("ended_at") or c["started_at"]
        if not row["first"] or row["first"] > end:
            return "before_recording"
        n = ctx.conn().execute("SELECT COUNT(*) FROM snapshots WHERE vehicle_id=? AND recorded_at BETWEEN ? AND ?",
                               (c["vehicle_id"], c["started_at"], end)).fetchone()[0]
        return "no_polls" if n == 0 else "not_charging"

    # ------------------------------------------------------------------ vehicles
    @r.get("/vehicles")
    def vehicles():
        out = []
        for v in rows(ctx.conn().execute("SELECT * FROM vehicles ORDER BY id")):
            snap = recorder.last_snapshot(ctx.conn(), v["id"])
            sec = store.load_sections(ctx.conn(), v["id"])
            v["info"] = sec.get("info")
            v["active"] = bool(ctx.poller() and v["vin"] in ctx.poller().rt)  # False = history only (the car was removed)
            v["soc"] = snap["soc"] if snap else None
            out.append(v)
        return out

    @r.put("/vehicles/{vid}")
    def update_vehicle(vid: int, body: dict):
        vehicle(vid)
        kwh = body.get("battery_kwh")
        if kwh is not None:
            try:
                kwh = None if kwh == "" else float(kwh)
            except (TypeError, ValueError):
                raise HTTPException(400, "battery_kwh must be a number")
            if kwh is not None and not 10 <= kwh <= 200:
                raise HTTPException(400, "battery_kwh must be between 10 and 200")
            ctx.conn().execute("UPDATE vehicles SET battery_kwh=? WHERE id=?", (kwh, vid))
            ctx.conn().commit()
        return {"ok": True}

    @r.get("/vehicles/{vid}/overview")
    def overview(vid: int):
        v = vehicle(vid)
        conn = ctx.conn()
        snap = recorder.last_snapshot(conn, vid)
        sec = store.load_sections(conn, vid)
        ops = (sec.get("operations") or {}).get("list")
        part_state = sec.get("part_state")
        poller = ctx.poller()
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
            "last_charge": charge_out(dict(last_charge), tariff) if last_charge else None,
            "tariff": tariff, "commands": commands.catalogue(ops), "unavailable": features.UNAVAILABLE,
            "needs_capacity": recorder.battery_kwh(conn, vid) is None,
            "demo": bool(getattr(ctx, "demo", False)),
        }

    @r.get("/vehicles/{vid}/capabilities")
    def capabilities_(vid: int):
        """Every operation and data field of the official API, with what this car supports and reports right now."""
        v = vehicle(vid)
        sec = store.load_sections(ctx.conn(), vid)
        p = ctx.poller()
        st = p.status(v["vin"]) if p else {}
        return features.capabilities((sec.get("operations") or {}).get("list"), sec.get("part_state"), sec,
                                     snap_out(recorder.last_snapshot(ctx.conn(), vid)),
                                     (st.get("budget") or {}).get("limit"), st.get("key_expires_at"))

    @r.post("/vehicles/{vid}/refresh")
    async def refresh(vid: int):
        v = vehicle(vid)
        p = ctx.poller()
        if p is None or v["vin"] not in p.rt:
            raise HTTPException(503, "Not connected to MyŠkoda yet. Open Settings.")
        res = await p.poll(v["vin"], reason="manual")
        res["poller"] = p.status(v["vin"])
        return res

    # ------------------------------------------------------------------ trips
    @r.get("/vehicles/{vid}/trips")
    def trips(vid: int, frm: str | None = Query(None, alias="from"), to: str | None = None, q: str | None = None,
              min_km: float | None = None, limit: int = Query(50, le=500), offset: int = 0, tz_offset: int = 0):
        vehicle(vid)
        where, args = ["vehicle_id=?", "ended_at IS NOT NULL"], [vid]
        if frm:
            where.append("COALESCE(started_at, ended_at) >= ?"); args.append(local_bound(frm, tz_offset))
        if to:
            where.append("COALESCE(started_at, ended_at) < ?"); args.append(local_bound(to, tz_offset, end=True))
        if min_km is not None:
            where.append("distance_km >= ?"); args.append(min_km)
        if q:
            where.append("(start_place LIKE ? OR end_place LIKE ? OR note LIKE ?)"); args += [f"%{q}%"] * 3
        w = " AND ".join(where)
        total = ctx.conn().execute(f"SELECT COUNT(*) FROM trips WHERE {w}", args).fetchone()[0]
        items = rows(ctx.conn().execute(f"SELECT * FROM trips WHERE {w} ORDER BY COALESCE(started_at, ended_at) DESC LIMIT ? OFFSET ?",
                                        [*args, limit, offset]))
        tariff = ctx.tariff()
        return {"total": total, "items": [trip_out(t, tariff) for t in items]}

    @r.get("/vehicles/{vid}/trips/{tid}")
    def trip(vid: int, tid: int):
        t = ctx.conn().execute("SELECT * FROM trips WHERE id=? AND vehicle_id=?", (tid, vid)).fetchone()
        if not t:
            raise HTTPException(404, "no such trip")
        t = trip_out(dict(t), ctx.tariff(), detail=True)
        t["charge_during"] = rows(ctx.conn().execute(
            "SELECT id, started_at, energy_kwh FROM charges WHERE vehicle_id=? AND started_at BETWEEN ? AND ?",
            (vid, t["started_at"] or "", t["ended_at"] or "")))
        return t

    @r.post("/vehicles/{vid}/trips/merge")
    def merge_trips(vid: int, body: dict):
        """Merge trips that a short stop split apart (consecutive, at most a few hours apart). Can be undone."""
        vehicle(vid)
        try:
            tid = merge.merge(ctx.conn(), vid, list(body.get("ids") or []))
        except (merge.MergeError, TypeError, ValueError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "id": tid}

    @r.post("/vehicles/{vid}/trips/{tid}/unmerge")
    def unmerge_trip(vid: int, tid: int):
        vehicle(vid)
        try:
            return {"ok": True, "ids": merge.unmerge(ctx.conn(), vid, tid)}
        except merge.MergeError as e:
            raise HTTPException(400, str(e))

    @r.post("/vehicles/{vid}/import/trips")
    def import_trips(vid: int, body: ImportBody):
        """Import the MyŠkoda app's trip export (CSV). `dry_run` (the default) reports what would happen and writes nothing."""
        v = vehicle(vid)
        if len(body.files) > MAX_IMPORT_FILES:
            raise HTTPException(400, f"At most {MAX_IMPORT_FILES} files at once.")
        if sum(len(str(f.get("text") or "")) for f in body.files) > MAX_IMPORT_CHARS:
            raise HTTPException(413, "The files are too large (limit 8 MB in total).")
        try:
            return importer.run(ctx.conn(), vid, v["vin"], body.files, body.tz, body.dry_run)
        except importer.ImportError_ as e:
            raise HTTPException(400, str(e))

    @r.put("/trips/{tid}/note")
    def trip_note(tid: int, body: NoteBody):
        ctx.conn().execute("UPDATE trips SET note=? WHERE id=?", (body.note[:500], tid))
        ctx.conn().commit()
        return {"ok": True}

    # ------------------------------------------------------------------ charges
    @r.get("/vehicles/{vid}/charges")
    def charges(vid: int, frm: str | None = Query(None, alias="from"), to: str | None = None, kind: str | None = None,
                limit: int = Query(50, le=500), offset: int = 0, tz_offset: int = 0):
        vehicle(vid)
        where, args = ["vehicle_id=?"], [vid]
        if frm:
            where.append("started_at >= ?"); args.append(local_bound(frm, tz_offset))
        if to:
            where.append("started_at < ?"); args.append(local_bound(to, tz_offset, end=True))
        if kind in ("AC", "DC"):
            where.append("charge_type=?"); args.append(kind)
        w = " AND ".join(where)
        tariff = ctx.tariff()
        if kind in ("home", "public"):
            # Home/public is resolved in Python (position vs home), so filter BEFORE paging or total/offset are wrong.
            everything = [charge_out(c, tariff) for c in rows(ctx.conn().execute(
                f"SELECT * FROM charges WHERE {w} ORDER BY started_at DESC", args))]
            matching = [c for c in everything if c["place_kind_resolved"] == kind]
            return {"total": len(matching), "items": matching[offset:offset + limit]}
        items = [charge_out(c, tariff) for c in rows(ctx.conn().execute(
            f"SELECT * FROM charges WHERE {w} ORDER BY started_at DESC LIMIT ? OFFSET ?", [*args, limit, offset]))]
        total = ctx.conn().execute(f"SELECT COUNT(*) FROM charges WHERE {w}", args).fetchone()[0]
        return {"total": total, "items": items}

    @r.get("/vehicles/{vid}/charges/{cid}")
    def charge(vid: int, cid: int):
        c = ctx.conn().execute("SELECT * FROM charges WHERE id=? AND vehicle_id=?", (cid, vid)).fetchone()
        if not c:
            raise HTTPException(404, "no such charge")
        c = charge_out(dict(c), ctx.tariff())
        end = c["ended_at"] or ctx.now_iso()
        c["curve"] = rows(ctx.conn().execute(
            "SELECT recorded_at t, soc, charge_power_kw p, remaining_min rem FROM snapshots WHERE vehicle_id=? "
            "AND recorded_at BETWEEN ? AND ? ORDER BY recorded_at", (vid, c["started_at"], end)))
        c["curve_gaps"] = curve_gaps(c["curve"], c["ended_at"] if c.get("end_estimated") else None)
        # A charge imported from a trip export has no position of its own: it happened somewhere on that trip.
        c["trip_route"] = None
        if c.get("source") == "import-trip":
            t = ctx.conn().execute("SELECT id, start_lat, start_lon, end_lat, end_lon, start_place, end_place FROM trips "
                                   "WHERE vehicle_id=? AND started_at=?", (vid, c["started_at"])).fetchone()
            if t and t["start_lat"] is not None and t["end_lat"] is not None:
                c["trip_route"] = dict(t)
        return c

    @r.patch("/vehicles/{vid}/charges/{cid}")
    def patch_charge(vid: int, cid: int, body: ChargePatch):
        sets, args = [], []
        if body.place_kind is not None:
            if body.place_kind not in ("home", "public", ""):
                raise HTTPException(400, "place_kind must be home, public or empty")
            sets.append("place_kind=?"); args.append(body.place_kind or None)
        if body.clear_cost:
            sets.append("cost_manual=NULL")
        elif body.cost_manual is not None:
            if not 0 <= body.cost_manual <= 10000:
                raise HTTPException(400, "cost out of range")
            sets.append("cost_manual=?"); args.append(body.cost_manual)
        if body.note is not None:
            sets.append("note=?"); args.append(body.note[:500])
        if sets:
            ctx.conn().execute(f"UPDATE charges SET {','.join(sets)} WHERE id=? AND vehicle_id=?", [*args, cid, vid])
            ctx.conn().commit()
        return charge(vid, cid)

    # ------------------------------------------------------------------ analysis
    @r.get("/vehicles/{vid}/stats")
    def statistics_(vid: int):
        vehicle(vid)
        t = ctx.tariff()
        return {"totals": stats.totals(ctx.conn(), vid, t), "monthly": stats.monthly(ctx.conn(), vid, t), "currency": t["currency"]}

    @r.get("/vehicles/{vid}/battery")
    def battery(vid: int, hours: int = Query(168, ge=1, le=24 * 365)):
        vehicle(vid)
        sec = store.load_sections(ctx.conn(), vid)
        b = stats.battery(ctx.conn(), vid)
        b["history"] = stats.soc_history(ctx.conn(), vid, hours, ctx.now_iso())
        b["charging"] = sec.get("charging")
        b["profiles"] = sec.get("profiles")
        return b

    @r.get("/vehicles/{vid}/history")
    def history(vid: int, hours: int = Query(48, ge=1, le=24 * 365)):
        vehicle(vid)
        return stats.soc_history(ctx.conn(), vid, hours, ctx.now_iso())

    @r.get("/vehicles/{vid}/events")
    def events(vid: int, kind: str | None = None, q: str | None = None, frm: str | None = Query(None, alias="from"),
               to: str | None = None, limit: int = Query(100, le=1000), offset: int = 0, tz_offset: int = 0):
        vehicle(vid)
        where, args = ["vehicle_id=?"], [vid]
        if kind:
            where.append("kind=?"); args.append(kind)
        if q:
            where.append("(kind LIKE ? OR detail LIKE ?)"); args += [f"%{q}%"] * 2
        if frm:
            where.append("at >= ?"); args.append(local_bound(frm, tz_offset))
        if to:
            where.append("at < ?"); args.append(local_bound(to, tz_offset, end=True))
        w = " AND ".join(where)
        return {"total": ctx.conn().execute(f"SELECT COUNT(*) FROM events WHERE {w}", args).fetchone()[0],
                "kinds": [x[0] for x in ctx.conn().execute("SELECT DISTINCT kind FROM events WHERE vehicle_id=? ORDER BY kind", (vid,))],
                "items": rows(ctx.conn().execute(f"SELECT * FROM events WHERE {w} ORDER BY at DESC, id DESC LIMIT ? OFFSET ?",
                                                 [*args, limit, offset]))}

    @r.get("/vehicles/{vid}/map")
    def map_(vid: int):
        vehicle(vid)
        sec = store.load_sections(ctx.conn(), vid)
        return {**stats.map_points(ctx.conn(), vid), "current": sec.get("position"), "tariff": ctx.tariff()}

    # ------------------------------------------------------------------ commands
    @r.get("/vehicles/{vid}/commands")
    def command_list(vid: int, limit: int = Query(30, le=200)):
        vehicle(vid)
        sec = store.load_sections(ctx.conn(), vid)
        ops = (sec.get("operations") or {}).get("list")
        log = rows(ctx.conn().execute("SELECT * FROM commands WHERE vehicle_id=? ORDER BY id DESC LIMIT ?", (vid, limit)))
        for c in log:
            c["params"] = json.loads(c["params"]) if c.get("params") else None
        p = ctx.poller()
        return {"catalogue": commands.catalogue(ops), "log": log, "spin_set": ctx.spin_set(),
                "budget": p.status(vehicle(vid)["vin"]).get("budget") if p else None}

    @r.post("/vehicles/{vid}/command")
    async def command(vid: int, body: CommandBody):
        v = vehicle(vid)
        p = ctx.poller()
        if p is None:
            raise HTTPException(503, "Not connected to MyŠkoda yet. Open Settings.")
        try:
            return await p.run_command(v["vin"], body.name, body.params)
        except commands.CommandError as e:
            raise HTTPException(400, str(e))

    # ------------------------------------------------------------------ diagnostics, export, backup
    @r.get("/vehicles/{vid}/raw")
    def raw(vid: int):
        """The last answer exactly as Škoda sent it (your own data: contains VIN and position)."""
        vehicle(vid)
        return (store.load_sections(ctx.conn(), vid).get("raw") or {})

    @r.get("/vehicles/{vid}/diagnostics")
    def diagnostics(vid: int):
        v = vehicle(vid)
        p = ctx.poller()
        sec = store.load_sections(ctx.conn(), vid)
        calls = rows(ctx.conn().execute("SELECT at, endpoint, ok, error FROM api_calls WHERE vehicle_id=? ORDER BY at DESC LIMIT 60", (vid,)))
        cmds = rows(ctx.conn().execute("SELECT at, name, ok, kind, http_status FROM commands WHERE vehicle_id=? ORDER BY id DESC LIMIT 30", (vid,)))
        bundle = {"app": "skoda-mate", "version": __version__, "generated": ctx.now_iso(),
                  "poller": p.status(v["vin"]) if p else None, "parts": sec.get("part_state"),
                  "operations": (sec.get("operations") or {}).get("list"), "api_errors": (sec.get("api_errors") or {}).get("list"),
                  "api_calls": calls, "commands": cmds, "response_redacted": redact(sec.get("raw") or {})}
        return Response(json.dumps(bundle, indent=1), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="skoda-mate-diagnostics.json"'})

    @r.get("/vehicles/{vid}/calls")
    def calls(vid: int, limit: int = Query(25, ge=1, le=500), offset: int = Query(0, ge=0), failed: bool = False):
        vehicle(vid)
        where = "vehicle_id=?" + (" AND ok=0" if failed else "")
        total = ctx.conn().execute(f"SELECT COUNT(*) FROM api_calls WHERE {where}", (vid,)).fetchone()[0]
        items = rows(ctx.conn().execute(f"SELECT at, endpoint, ok, error FROM api_calls WHERE {where} ORDER BY at DESC, rowid DESC LIMIT ? OFFSET ?", (vid, limit, offset)))
        for c in items:  # stored as epoch seconds for the budget arithmetic; every other timestamp in the API is ISO
            c["at"] = datetime.fromtimestamp(c["at"], UTC).isoformat()
        return {"total": total, "items": items}

    @r.get("/vehicles/{vid}/export/{what}.csv")
    def export(vid: int, what: str):
        vehicle(vid)
        table = {"trips": "trips", "charges": "charges", "events": "events", "snapshots": "snapshots"}.get(what)
        if table is None:
            raise HTTPException(404, "unknown export")
        cur = ctx.conn().execute(f"SELECT * FROM {table} WHERE vehicle_id=? ORDER BY 1", (vid,))
        cols = [d[0] for d in cur.description if d[0] not in ("route_json",)]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for row in cur:
            w.writerow([csv_cell(row[c]) for c in cols])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="skoda-mate-{what}.csv"'})

    @r.get("/backup")
    def backup():
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        import sqlite3

        dst = sqlite3.connect(path)
        ctx.conn().backup(dst)  # a consistent copy even while the poller writes
        dst.close()
        name = f"skoda-mate-{datetime.now(UTC):%Y%m%d-%H%M}.db"
        return FileResponse(path, media_type="application/octet-stream", filename=name,
                            background=BackgroundTask(os.unlink, path))

    # ------------------------------------------------------------------ settings
    @r.get("/settings")
    def get_settings():
        conn = ctx.conn()
        idle, active = ctx.poller().intervals() if ctx.poller() else (1200, 300)
        return {"tariff": ctx.tariff(), "poll_idle_s": idle, "poll_active_s": active, "poll_min_s": 180,
                "command_reserve": store.int_setting(conn, "command_reserve", 4, 0, 10),
                "units": store.setting(conn, "units", "km"), "language": store.setting(conn, "language", "en"),
                "theme": store.setting(conn, "theme", "auto"),
                "battery_kwh_default": store.setting(conn, "battery_kwh"),
                "vehicles": [{"id": v["id"], "name": v["name"], "vin": v["vin"], "battery_kwh": v["battery_kwh"]}
                             for v in rows(conn.execute("SELECT * FROM vehicles ORDER BY id"))]}

    @r.put("/settings")
    def put_settings(body: SettingsBody):
        conn = ctx.conn()
        if body.tariff is not None:
            try:
                new = costs.clean_tariff(body.tariff)
            except (ValueError, TypeError) as e:
                raise HTTPException(400, str(e))
            store_tariff = {**ctx.tariff(), **new}
            conn.execute("INSERT INTO settings(key,value) VALUES('tariff',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (json.dumps(store_tariff),))
        for key, val, lo, hi in (("poll_idle_s", body.poll_idle_s, 180, 6 * 3600), ("poll_active_s", body.poll_active_s, 180, 3600),
                                 ("command_reserve", body.command_reserve, 0, 10)):
            if val is not None:
                if not lo <= val <= hi:
                    raise HTTPException(400, f"{key} must be between {lo} and {hi}")
                conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (key, str(val)))
        for key, val, allowed in (("units", body.units, ("km", "mi")), ("language", body.language, ("en", "de")),
                                  ("theme", body.theme, ("auto", "light", "dark"))):
            if val is not None:
                if val not in allowed:
                    raise HTTPException(400, f"{key} must be one of {', '.join(allowed)}")
                conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, val))
        if body.battery_kwh_default is not None:
            if not 10 <= body.battery_kwh_default <= 200:
                raise HTTPException(400, "battery_kwh must be between 10 and 200")
            conn.execute("INSERT INTO settings(key,value) VALUES('battery_kwh',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (str(body.battery_kwh_default),))
        conn.commit()
        p = ctx.poller()
        if p:
            for rt in p.rt.values():
                rt.budget.configure(reserve=store.int_setting(conn, "command_reserve", 4, 0, 10))
        return get_settings()

    @r.post("/vehicles/{vid}/home-here")
    def home_here(vid: int, charge_id: int | None = None):
        """Set the home position (for Home vs Public charges) to a charge's location, else to where the car is parked."""
        vehicle(vid)
        if charge_id is not None:
            c = ctx.conn().execute("SELECT lat, lon FROM charges WHERE id=? AND vehicle_id=?", (charge_id, vid)).fetchone()
            if not c or c["lat"] is None:
                raise HTTPException(400, "That charge has no known location.")
            pos = {"lat": c["lat"], "lon": c["lon"]}
        else:
            pos = (store.load_sections(ctx.conn(), vid).get("position") or {})
        if pos.get("lat") is None:
            raise HTTPException(400, "The car's position is not known yet (it is moving or not reported).")
        t = {**ctx.tariff(), "home_lat": pos["lat"], "home_lon": pos["lon"]}
        ctx.conn().execute("INSERT INTO settings(key,value) VALUES('tariff',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           (json.dumps(t),))
        ctx.conn().commit()
        return {"ok": True, "home_lat": pos["lat"], "home_lon": pos["lon"]}

    app.include_router(r)
