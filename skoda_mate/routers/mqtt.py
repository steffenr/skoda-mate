"""MQTT / Home Assistant settings: read, save (applied immediately) and test without saving."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from .. import ha_mqtt, mqtt_config
from ..deps import ContextDep

router = APIRouter(prefix="/api/settings/mqtt")


@router.get("")
async def mqtt_get(ctx: ContextDep):
    return ctx.cloud.mqtt_payload()


@router.put("")
async def mqtt_put(body: dict, ctx: ContextDep):
    try:
        mqtt_config.save(ctx.conn, ctx.box, body)
    except mqtt_config.MqttConfigError as e:
        raise HTTPException(400, str(e)) from e
    ctx.cloud.apply_mqtt()
    return ctx.cloud.mqtt_payload()


@router.post("/test")
async def mqtt_test(body: dict, ctx: ContextDep):
    """Try the values on the form without saving or changing anything. A blank password means the stored one, but only
    for the broker it was stored for (otherwise a changed address would hand it to any host)."""
    stored = ctx.cloud.mqtt_config()
    try:
        clean = mqtt_config.validate({**body, "enabled": False})
    except mqtt_config.MqttConfigError as e:
        raise HTTPException(400, str(e)) from e
    if not clean["host"]:
        raise HTTPException(400, "Enter the broker address first.")
    if body.get("password"):
        password = str(body["password"])
    elif body.get("clear_password"):
        password = ""
    else:
        try:
            password = mqtt_config.stored_password_for(stored, clean)
        except mqtt_config.MqttConfigError:  # the only reason: the broker changed; answer with the fixed text, not the exception
            return {"ok": False, "message": mqtt_config.PASSWORD_AGAIN}
    return await asyncio.to_thread(ha_mqtt.probe, clean["host"], clean["port"], clean["user"], password,
                                   clean["tls"], clean["tls_insecure"])
