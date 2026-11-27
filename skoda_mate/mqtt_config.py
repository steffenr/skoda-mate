"""MQTT / Home Assistant settings stored in the database (the password encrypted like the API key).

Environment variables (MQTT_HOST, MQTT_USER, ...) still work as a fallback so existing installs keep running; as soon as
settings are saved in the dashboard they take over.
"""
from __future__ import annotations

import json
import re

from . import messages
from .config import Config
from .secrets_store import SecretBox
from .store import get_setting, set_setting

KEY = "mqtt"
# "commands": accept car commands from MQTT. Off unless the user ticks it: anyone who can publish to the broker could use them.
DEFAULTS = {"enabled": False, "host": "", "port": 1883, "user": "", "prefix": "skoda_mate", "discovery": True, "commands": False,
            "tls": False, "tls_insecure": False, "publish_fields": True}
PASSWORD_AGAIN = messages.MQTT_PASSWORD_AGAIN
PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]{1,253}$")  # names, IPv4, bracketed/plain IPv6


class MqttConfigError(ValueError):
    pass


def validate(data: dict) -> dict:
    """Clean a submitted config (without the password). Raises MqttConfigError with a message for the user."""
    out = dict(DEFAULTS)
    out["enabled"] = bool(data.get("enabled"))
    host = str(data.get("host", "")).strip()
    if host and not HOST_RE.match(host):
        raise MqttConfigError(messages.MQTT_BROKER_ADDRESS)
    out["host"] = host
    try:
        raw_port = data.get("port", 1883)
        port = 1883 if raw_port in (None, "") else int(raw_port)
    except (TypeError, ValueError):
        raise MqttConfigError(messages.MQTT_PORT) from None
    if not 1 <= port <= 65535:
        raise MqttConfigError(messages.MQTT_PORT)
    out["port"] = port
    out["user"] = str(data.get("user", "")).strip()[:128]
    prefix = str(data.get("prefix", "") or DEFAULTS["prefix"]).strip()
    if not PREFIX_RE.match(prefix):
        raise MqttConfigError(messages.MQTT_PREFIX)
    out["prefix"] = prefix
    out["discovery"] = bool(data.get("discovery", True))
    out["commands"] = bool(data.get("commands"))
    out["publish_fields"] = bool(data.get("publish_fields", True))
    out["tls"] = bool(data.get("tls"))
    out["tls_insecure"] = bool(data.get("tls_insecure")) and out["tls"]
    if out["enabled"] and not host:
        raise MqttConfigError(messages.MQTT_BROKER_MISSING)
    return out


def load(conn, box: SecretBox, cfg: Config | None = None) -> dict:
    """The effective config incl. the password, and where it came from: 'db', 'env' or 'none'."""
    raw = get_setting(conn, KEY)
    if raw:
        try:
            d = json.loads(raw)
        except ValueError:
            d = {}
        enc = d.pop("password_enc", "")
        out = {**DEFAULTS, **{k: d[k] for k in DEFAULTS if k in d}}
        out["password"] = (box.decrypt(enc) or "") if enc else ""
        out["password_unreadable"] = bool(enc) and not out["password"]
        out["source"] = "db"
        return out
    if cfg is not None and cfg.mqtt_host:
        return {**DEFAULTS, "enabled": True, "host": cfg.mqtt_host, "port": cfg.mqtt_port, "user": cfg.mqtt_user, "password": cfg.mqtt_password,
                "prefix": cfg.mqtt_prefix, "password_unreadable": False, "source": "env"}
    return {**DEFAULTS, "password": "", "password_unreadable": False, "source": "none"}


def same_broker(a: dict, b: dict) -> bool:
    return (a.get("host"), int(a.get("port") or 0), bool(a.get("tls"))) == (b.get("host"), int(b.get("port") or 0), bool(b.get("tls")))


def stored_password_for(current: dict, clean: dict) -> str:
    """The stored password, but only for the broker it was saved for: otherwise a changed address would send it to any
    host. Raises MqttConfigError (PASSWORD_AGAIN) when there is a stored password and host, port or TLS differ."""
    pw = current.get("password") or ""
    if pw and not same_broker(current, clean):
        raise MqttConfigError(PASSWORD_AGAIN)
    return pw


def save(conn, box: SecretBox, data: dict) -> dict:
    """Validate and store. `password`: a new one; absent = keep the stored one (same broker only); `clear_password`: remove it."""
    clean = validate(data)
    current = load(conn, box)
    if data.get("clear_password"):
        pw = ""
    elif data.get("password"):
        pw = str(data["password"])
    else:
        pw = stored_password_for(current, clean) if current["source"] == "db" else ""
    stored = {**clean, "password_enc": box.encrypt(pw) if pw else ""}
    set_setting(conn, KEY, json.dumps(stored))
    return load(conn, box)


def public_view(conf: dict) -> dict:
    """What the dashboard may see: everything except the password itself."""
    return {**{k: conf[k] for k in DEFAULTS}, "password_set": bool(conf.get("password")) or bool(conf.get("password_unreadable")),
            "password_unreadable": bool(conf.get("password_unreadable")), "source": conf["source"]}
