"""Settings: tariff, poll intervals, units, language, theme and the battery capacity per car."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import costs, store
from ..deps import ContextDep
from ..presenters import rows

router = APIRouter()


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


@router.get("/api/settings")
def get_settings(ctx: ContextDep):
    conn = ctx.conn
    idle, active = ctx.poller.intervals() if ctx.poller else (1200, 300)
    return {"tariff": ctx.tariff(), "poll_idle_s": idle, "poll_active_s": active, "poll_min_s": 180,
            "command_reserve": store.int_setting(conn, "command_reserve", 4, 0, 10),
            "units": store.setting(conn, "units", "km"), "language": store.setting(conn, "language", "en"),
            "theme": store.setting(conn, "theme", "auto"),
            "battery_kwh_default": store.setting(conn, "battery_kwh"),
            "vehicles": [{"id": v["id"], "name": v["name"], "vin": v["vin"], "battery_kwh": v["battery_kwh"]}
                         for v in rows(conn.execute("SELECT * FROM vehicles ORDER BY id"))]}


@router.put("/api/settings")
def put_settings(body: SettingsBody, ctx: ContextDep):
    conn = ctx.conn
    if body.tariff is not None:
        try:
            new = costs.clean_tariff(body.tariff)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e)) from e
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
    for key, choice, allowed in (("units", body.units, ("km", "mi")), ("language", body.language, ("en", "de")),
                                 ("theme", body.theme, ("auto", "light", "dark"))):
        if choice is not None:
            if choice not in allowed:
                raise HTTPException(400, f"{key} must be one of {', '.join(allowed)}")
            conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, choice))
    if body.battery_kwh_default is not None:
        if not 10 <= body.battery_kwh_default <= 200:
            raise HTTPException(400, "battery_kwh must be between 10 and 200")
        conn.execute("INSERT INTO settings(key,value) VALUES('battery_kwh',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (str(body.battery_kwh_default),))
    conn.commit()
    p = ctx.poller
    if p:
        for rt in p.rt.values():
            rt.budget.configure(reserve=store.int_setting(conn, "command_reserve", 4, 0, 10))
    return get_settings(ctx)
