"""Places: the named geofences the map and the charge prices work with."""
from __future__ import annotations

import math
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import messages, places
from ..deps import ContextDep

router = APIRouter()

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


class PlaceIn(BaseModel):
    name: str
    kind: str = "place"
    lat: float
    lon: float
    radius_m: int = 150
    color: str | None = None
    price_kwh: float | None = None
    price_minute: float | None = None
    session_fee: float | None = None
    free: bool = False


def _payload(body: PlaceIn) -> dict:
    """The checked place fields the data layer stores; the API is the only place that validates them."""
    name = body.name.strip()
    if not 1 <= len(name) <= 60:
        raise messages.UserError(400, messages.PLACE_NAME)
    if body.kind not in places.KINDS:
        raise messages.UserError(400, messages.PLACE_KIND)
    if not math.isfinite(body.lat) or not -90 <= body.lat <= 90:
        raise messages.UserError(400, messages.PLACE_LATITUDE)
    if not math.isfinite(body.lon) or not -180 <= body.lon <= 180:
        raise messages.UserError(400, messages.PLACE_LONGITUDE)
    if not places.MIN_RADIUS_M <= body.radius_m <= places.MAX_RADIUS_M:
        raise messages.UserError(400, messages.PLACE_RADIUS)
    color = body.color.strip() if body.color is not None else None
    if color is not None and not _HEX.fullmatch(color):
        raise messages.UserError(400, messages.PLACE_COLOUR)
    for value, maximum, message in (
            (body.price_kwh, 1000, messages.PLACE_PRICE_KWH),
            (body.price_minute, 1000, messages.PLACE_PRICE_MINUTE),
            (body.session_fee, 10000, messages.PLACE_SESSION_FEE)):
        if value is not None and not (math.isfinite(value) and 0 <= value <= maximum):
            raise messages.UserError(400, message)
    if body.free and any(v is not None for v in (body.price_kwh, body.price_minute, body.session_fee)):
        raise messages.UserError(400, messages.PLACE_FREE_WITH_PRICE)
    return {"name": name, "kind": body.kind, "lat": body.lat, "lon": body.lon, "radius_m": body.radius_m,
            "color": color, "price_kwh": body.price_kwh, "price_minute": body.price_minute,
            "session_fee": body.session_fee, "free": body.free}


def _fail(exc: places.PlaceError) -> HTTPException:
    return messages.UserError(exc.status, exc)


@router.get("/api/places")
def list_places(ctx: ContextDep, tz_offset: int = Query(0, ge=-840, le=840)):
    return {"items": places.summaries(ctx.conn, tz_offset)}


@router.post("/api/places")
def create_place(body: PlaceIn, ctx: ContextDep):
    try:
        return places.create(ctx.conn, _payload(body))
    except places.PlaceError as exc:
        raise _fail(exc) from exc


@router.get("/api/places/{place_id}")
def place_detail(place_id: int, ctx: ContextDep, tz_offset: int = Query(0, ge=-840, le=840)):
    found = places.detail(ctx.conn, place_id, ctx.now_iso(), tz_offset)
    if found is None:
        raise messages.UserError(404, messages.PLACE_NOT_FOUND)
    return found


@router.put("/api/places/{place_id}")
def update_place(place_id: int, body: PlaceIn, ctx: ContextDep):
    try:
        return places.update(ctx.conn, place_id, _payload(body))
    except places.PlaceError as exc:
        raise _fail(exc) from exc


@router.delete("/api/places/{place_id}")
def delete_place(place_id: int, ctx: ContextDep):
    try:
        return {"ok": True, **places.delete(ctx.conn, place_id)}
    except places.PlaceError as exc:
        raise _fail(exc) from exc
