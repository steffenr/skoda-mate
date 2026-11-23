"""Environment configuration. Logins and passwords are NOT read from here: they are entered in the
browser (/setup) and stored in the database (Škoda password encrypted, dashboard password hashed)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    db_path: str = "/data/skoda_mate.db"
    poll_seconds: int = 300
    poll_seconds_active: int = 60  # while charging
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    mqtt_prefix: str = "skoda_mate"
    api_token: str = ""  # optional: scripts may send "Authorization: Bearer <token>" instead of a session
    cookie_secure: bool = False  # set true when served over HTTPS
    setup_code: str = ""  # optional: your own first-run setup code instead of a generated one (asked only from public addresses)
    demo_cars: int = 1  # DEMO_CARS=2 adds a second fictional car to the demo, to try switching between cars
    demo: bool = False  # DEMO=1: a fictional car and 60 days of history, no account, no network (try it / develop)

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        g = env.get
        return cls(
            db_path=g("DB_PATH", "/data/skoda_mate.db"),
            poll_seconds=int(g("POLL_SECONDS", "300")),
            poll_seconds_active=int(g("POLL_SECONDS_ACTIVE", "60")),
            mqtt_host=g("MQTT_HOST", ""), mqtt_port=int(g("MQTT_PORT", "1883")),
            mqtt_user=g("MQTT_USER", ""), mqtt_password=g("MQTT_PASSWORD", ""),
            mqtt_prefix=g("MQTT_PREFIX", "skoda_mate"), api_token=g("API_TOKEN", ""),
            cookie_secure=g("COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
            setup_code=g("SETUP_CODE", ""),
            demo_cars=int(g("DEMO_CARS", "1") or 1),
            demo=g("DEMO", "").lower() in ("1", "true", "yes"),
        )
