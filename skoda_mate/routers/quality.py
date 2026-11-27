"""The data-quality report and its repair actions."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import messages, quality
from ..deps import ContextDep
from ..presenters import vehicle

router = APIRouter()


class FixBody(BaseModel):
    action: str


class ReviewBody(BaseModel):
    check: str
    reviewed: bool


@router.get("/api/vehicles/{vid}/quality")
def quality_view(vid: int, ctx: ContextDep):
    vehicle(ctx.conn, vid)
    now = ctx.now_iso()
    return {"checked_at": now, "checks": quality.checks(ctx.conn, vid, now)}


@router.post("/api/vehicles/{vid}/quality/fix")
def quality_fix(vid: int, body: FixBody, ctx: ContextDep):
    vehicle(ctx.conn, vid)
    try:
        return quality.fix(ctx.conn, vid, body.action, ctx.now_iso())
    except ValueError as e:
        raise messages.UserError(400, e) from e


@router.post("/api/vehicles/{vid}/quality/review")
def quality_review(vid: int, body: ReviewBody, ctx: ContextDep):
    vehicle(ctx.conn, vid)
    try:
        return quality.review(ctx.conn, vid, body.check, body.reviewed, ctx.now_iso())
    except ValueError as e:
        raise messages.UserError(400, e) from e
