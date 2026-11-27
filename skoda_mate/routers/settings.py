"""Settings: tariff, poll intervals, units, language, theme and the battery capacity per car."""
from __future__ import annotations

import json
import math
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import costs, languages, places, store
from ..deps import ContextDep
from ..presenters import rows
from ..store import get_setting, set_setting

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
    # A stored code that is not offered (a downgrade, a hand edit) reads as English.
    language = languages.BY_CODE.get(get_setting(conn, "language", "en"), languages.DEFAULT)
    return {"tariff": ctx.tariff(), "poll_idle_s": idle, "poll_active_s": active, "poll_min_s": 180,
            "command_reserve": store.int_setting(conn, "command_reserve", 4, 0, 10),
            "units": get_setting(conn, "units", "km"), "language": language.code, "locale": language.locale,
            "languages": [asdict(x) for x in languages.LANGUAGES],
            "theme": get_setting(conn, "theme", "auto"),
            "battery_kwh_default": get_setting(conn, "battery_kwh"),
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
        set_setting(conn, "tariff", json.dumps({**ctx.tariff(), **new}))
        # Legacy clients still send the home coordinates with the tariff; keep the home place in step. An omitted,
        # cleared or non-finite coordinate is not a home: it leaves the place alone (SQLite stores NaN as NULL).
        lat, lon = new.get("home_lat"), new.get("home_lon")
        if lat is not None and lon is not None and math.isfinite(lat) and math.isfinite(lon):
            places.upsert_home(conn, lat, lon, new.get("home_radius_m"))
    for key, val, lo, hi in (("poll_idle_s", body.poll_idle_s, 180, 6 * 3600), ("poll_active_s", body.poll_active_s, 180, 3600),
                             ("command_reserve", body.command_reserve, 0, 10)):
        if val is not None:
            if not lo <= val <= hi:
                raise HTTPException(400, f"{key} must be between {lo} and {hi}")
            set_setting(conn, key, str(val))
    for key, choice, allowed in (("units", body.units, ("km", "mi")), ("language", body.language, tuple(languages.BY_CODE)),
                                 ("theme", body.theme, ("auto", "light", "dark"))):
        if choice is not None:
            if choice not in allowed:
                raise HTTPException(400, f"{key} must be one of {', '.join(allowed)}")
            set_setting(conn, key, choice)
    if body.battery_kwh_default is not None:
        if not 10 <= body.battery_kwh_default <= 200:
            raise HTTPException(400, "battery_kwh must be between 10 and 200")
        set_setting(conn, "battery_kwh", str(body.battery_kwh_default))
    conn.commit()
    p = ctx.poller
    if p:
        for rt in p.rt.values():
            rt.budget.configure(reserve=store.int_setting(conn, "command_reserve", 4, 0, 10))
    return get_settings(ctx)
