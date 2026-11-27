"""Automation: the user's webhooks, their deliveries, and the low-battery threshold of the `soc.low` event."""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException

from .. import automation, store, webhooks
from ..deps import ContextDep

router = APIRouter(prefix="/api/webhooks")

BAD_THRESHOLD = "The low-battery threshold must be a whole number from 5 to 50."


@contextmanager
def _answering() -> Iterator[None]:
    """The store's refusals as 404 / 400 with their message."""
    try:
        yield
    except webhooks.WebhookNotFound as e:
        raise HTTPException(404, str(e)) from e
    except webhooks.WebhookError as e:
        raise HTTPException(400, str(e)) from e


@router.get("")
def overview(ctx: ContextDep):
    return {"webhooks": webhooks.listing(ctx.conn, ctx.box),
            "event_groups": [{"group": g, "events": list(names)} for g, names in automation.EVENT_GROUPS],
            "soc_low_threshold": automation.soc_low_threshold(ctx.conn), "soc_low_range": list(automation.SOC_LOW_RANGE)}


@router.post("")
def create(body: dict, ctx: ContextDep):
    with _answering():
        webhook, secret = webhooks.create(ctx.conn, ctx.box, body)
    return {"webhook": webhook, "secret": secret}


@router.put("/options")  # before /{webhook_id}, which would otherwise claim the path
def options(body: dict, ctx: ContextDep):
    value = body.get("soc_low_threshold")
    low, high = automation.SOC_LOW_RANGE
    if type(value) is not int or not low <= value <= high:
        raise HTTPException(400, BAD_THRESHOLD)
    store.set_setting(ctx.conn, automation.SOC_LOW_KEY, str(value))
    ctx.conn.commit()
    return {"soc_low_threshold": value}


@router.put("/{webhook_id}")
def update(webhook_id: int, body: dict, ctx: ContextDep):
    with _answering():
        return webhooks.update(ctx.conn, ctx.box, webhook_id, body)


@router.delete("/{webhook_id}")
def delete(webhook_id: int, ctx: ContextDep):
    with _answering():
        webhooks.delete(ctx.conn, webhook_id)
    return {"ok": True}


@router.post("/{webhook_id}/secret")
def new_secret(webhook_id: int, ctx: ContextDep):
    with _answering():
        return {"secret": webhooks.rotate(ctx.conn, ctx.box, webhook_id)}


@router.post("/{webhook_id}/test")
async def send_test(webhook_id: int, ctx: ContextDep):
    with _answering():
        return await ctx.cloud.webhooks.send_test(webhook_id)


@router.get("/{webhook_id}/deliveries")
def deliveries(webhook_id: int, ctx: ContextDep):
    with _answering():
        return {"deliveries": webhooks.deliveries(ctx.conn, webhook_id)}


@router.post("/deliveries/{delivery_id}/retry")
def retry(delivery_id: int, ctx: ContextDep):
    with _answering():
        result = webhooks.retry(ctx.conn, delivery_id, time.time())
    ctx.cloud.webhooks.wake()
    return result
