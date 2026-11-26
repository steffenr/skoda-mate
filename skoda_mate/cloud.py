"""The Škoda connection's lifecycle: the poller task, its HTTP client and the MQTT publisher.

`create_app` builds one `Cloud`; the routers reach it through `AppContext`. Every method is safe when nothing is
connected (fresh install, demo mode, a rejected API key), so routes can call `cloud.apply_mqtt()` or ask for
`cloud.poller` without checking the boot state first.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from . import commands, costs, ha_mqtt, mqtt_config, places, recorder
from .client import SkodaApi
from .config import Config
from .poller import Poller
from .secrets_store import SecretBox, load_api_login

_LOG = logging.getLogger(__name__)


class Cloud:
    def __init__(self, conn, box: SecretBox, cfg: Config, poller: Poller | None = None):
        self.conn, self.box, self.cfg = conn, box, cfg
        self.poller = poller  # None = not connected (yet); tests inject one
        self.task: asyncio.Task | None = None
        self.api: SkodaApi | None = None
        self.mqtt_error: str | None = None  # why the publisher could not start (shown on the Settings page)

    # ------------------------------------------------------------------ credentials
    def spin(self) -> str:
        creds = load_api_login(self.conn, self.box)
        return creds[2] if creds else ""

    def spin_set(self) -> bool:
        return bool(self.spin())

    def configured(self) -> bool:
        """Is there an API key (connected now, or stored for the next start)?"""
        return self.poller is not None or load_api_login(self.conn, self.box) is not None

    def vehicle_name(self, vin: str):
        row = self.conn.execute("SELECT name FROM vehicles WHERE vin=?", (vin,)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ lifecycle
    def start(self, api, vins: list[str], poller: Poller | None = None) -> Poller:
        p = poller or Poller(self.conn, api, spin_getter=self.spin)
        for vin in vins:
            vid = recorder.upsert_vehicle(self.conn, vin)
            if vin not in p.rt:
                p.add_vehicle(vin, vid)
        p.publisher = self._make_publisher(p)
        if p.publisher:
            for vin in vins:
                p.publisher.announce(vin, self.vehicle_name(vin))
        self.poller, self.api, self.task = p, api, asyncio.create_task(p.run())
        return p

    async def start_saved(self, api_factory: Callable[[str], SkodaApi]) -> Poller | None:
        """Connect with the API key stored in the database (the normal start, unless demo mode or a poller was injected)."""
        if self.poller is not None or self.cfg.demo:
            return None
        creds = load_api_login(self.conn, self.box)
        return self.start(api_factory(creds[0]), creds[1]) if creds else None

    async def stop(self) -> None:
        p, task, api = self.poller, self.task, self.api
        if p and task:
            p.stop()
            await task
        if p and p.publisher:
            p.publisher.close()
        if api:
            await api.close()
        self.poller, self.task, self.api = None, None, None

    # ------------------------------------------------------------------ MQTT / Home Assistant
    def mqtt_config(self) -> dict:
        return mqtt_config.load(self.conn, self.box, self.cfg)

    def mqtt_payload(self) -> dict:
        """The Settings page's view: the effective config (password hidden), the publisher's state, and how many entities
        each car gets with the current command setting."""
        conf = self.mqtt_config()
        p = self.poller
        pub = p.publisher if p else None
        if pub:
            status = pub.status()
        elif not (conf["enabled"] and conf["host"]):
            status = {"state": "disabled", "error": None, "entities": 0, "vehicles": 0}
        elif self.mqtt_error:
            status = {"state": "error", "error": self.mqtt_error, "entities": 0, "vehicles": 0}
        else:  # enabled, but Mate is not connected to Škoda yet: nothing to publish and no publisher to run
            status = {"state": "waiting", "error": None, "entities": 0, "vehicles": 0}
        return {"config": mqtt_config.public_view(conf), "status": status, "discovery_prefix": ha_mqtt.DISCOVERY_PREFIX,
                "entities_per_car": len(ha_mqtt.discovery("x", "VIN", None, commands=conf["commands"]))}

    def _extras(self, vin: str) -> dict:
        """Values Mate derives itself, published next to the API's own: the last finished trip and charge."""
        row = self.conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
        out: dict = {}
        if not row:
            return out
        tariff = costs.load_tariff(self.conn)
        t = self.conn.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NOT NULL "
                              "ORDER BY started_at DESC LIMIT 1", (row["id"],)).fetchone()
        if t:
            t = dict(t)
            out.update(last_trip_km=round(t["distance_km"], 1) if t.get("distance_km") is not None else None,
                       last_trip_kwh=t.get("energy_kwh"), last_trip_consumption=t.get("avg_kwh_100km"))
        c = self.conn.execute("SELECT * FROM charges WHERE vehicle_id=? AND ended_at IS NOT NULL "
                              "ORDER BY started_at DESC LIMIT 1", (row["id"],)).fetchone()
        if c:
            c = dict(c)
            place = places.get(self.conn, c["geofence_id"]) if c.get("geofence_id") else None
            out.update(last_charge_kwh=c.get("energy_kwh"),
                       last_charge_cost=(costs.charge_cost(c, tariff, place) or {}).get("amount"))
        return out

    def _make_publisher(self, p: Poller):
        conf = self.mqtt_config()
        self.mqtt_error = None
        if not (conf["enabled"] and conf["host"]):
            return None
        loop = asyncio.get_running_loop()
        holder: dict = {}

        async def run_mqtt_command(vin, name, params):
            """Every outcome goes back to Home Assistant (cmd_result / "Last command"); refusals also into Mate's log."""
            pub = holder.get("pub")
            try:
                res = await p.run_command(vin, name, params, source="mqtt")  # logs sent / failed itself
                status, error = ("sent", None) if res.get("ok") else ("failed", res.get("error"))
            except commands.CommandError as e:
                p.log_rejected(vin, name, params, str(e), "mqtt")
                status, error = "rejected", str(e)
            except Exception as e:  # never lost silently in an unread future
                _LOG.exception("MQTT command %s for %s failed", name, vin)
                status, error = "failed", f"{type(e).__name__}: {e}"
            if status != "sent":
                _LOG.warning("MQTT command %s for %s %s: %s", name, vin, status, error)
            if pub:
                pub.publish_result(vin, name, status, error)

        try:
            holder["pub"] = ha_mqtt.Publisher(
                conf["host"], conf["port"], conf["user"], conf["password"], conf["prefix"], tls=conf["tls"],
                tls_insecure=conf["tls_insecure"], discovery=conf["discovery"], commands=conf["commands"],
                extras=self._extras, currency=lambda: costs.load_tariff(self.conn).get("currency", "EUR"),
                on_command=lambda vin, name, params: asyncio.run_coroutine_threadsafe(run_mqtt_command(vin, name, params), loop))
            return holder["pub"]
        except Exception as e:  # e.g. a TLS setup problem: the dashboard shows it instead of Mate failing
            _LOG.warning("MQTT could not start: %s", e)
            self.mqtt_error = str(e)
            return None

    def apply_mqtt(self) -> None:
        """Take new MQTT settings into use right away (no restart): replace the publisher and announce the cars again."""
        p = self.poller
        if p is None:
            return
        old, p.publisher = p.publisher, None
        if old:
            old.close()
        pub = p.publisher = self._make_publisher(p)
        if pub:
            for vin in list(p.rt):
                pub.announce(vin, self.vehicle_name(vin))
                vid = self.conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
                last = recorder.last_snapshot(self.conn, vid["id"]) if vid else None
                if last:
                    pub.publish_state(vin, dict(last))
