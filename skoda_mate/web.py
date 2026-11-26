"""FastAPI app: configuration, lifespan, middleware and router wiring. Nothing else.

The routes live in `routers/` (pages, auth, setup, mqtt, vehicles, trips, charges, reports, places, settings), the
state they share in `context.py`, the Škoda/MQTT connection in `cloud.py`, the row shaping in `presenters.py`.
This module is the only place that knows about all of them.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from . import demo, places, recorder, schema
from .auth import Auth
from .client import SkodaApi
from .cloud import Cloud
from .config import Config
from .context import AppContext
from .middleware import BodyLimit, SecurityHeaders
from .poller import Poller
from .routers import auth as auth_routes
from .routers import charges, mqtt, pages, reports, settings, setup, trips, vehicles
from .routers import places as places_routes
from .secrets_store import SecretBox

_LOG = logging.getLogger(__name__)
HERE = Path(__file__).parent


def create_app(cfg: Config | None = None, conn=None, poller: Poller | None = None, api_factory=SkodaApi) -> FastAPI:
    """`conn`, `poller` and `api_factory` can be injected (tests). Otherwise the dashboard login and the Škoda API key
    come from the database, where the /setup form put them (never from environment variables)."""
    cfg = cfg or Config.from_env()
    conn = conn or schema.connect(cfg.db_path)
    key_path = None if cfg.db_path == ":memory:" else str(Path(cfg.db_path).with_name("secret.key"))
    box = SecretBox(key_path)
    login = Auth(box.key, conn)
    recorder.repair_charge_gaps(conn)  # once: charges recorded before gaps in the readings were handled (issue #8)
    for v in conn.execute("SELECT id FROM vehicles").fetchall():  # backfill charges that can be read off existing trips/readings
        recorder.infer_charges(conn, v["id"])
    places.assign_all(conn)  # once per start: link rows stored before places existed (or before a place was moved)

    ctx = AppContext(
        conn=conn, cfg=cfg, auth=login, box=box, cloud=Cloud(conn, box, cfg, poller), api_factory=api_factory,
        setup_file=None if cfg.db_path == ":memory:" else Path(cfg.db_path).with_name("setup-code.txt"),
    )
    ctx.init_setup_code()

    @asynccontextmanager
    async def lifespan(_app):
        if cfg.demo and ctx.poller is None:
            _start_demo(ctx)
        await ctx.cloud.start_saved(api_factory)
        yield
        await ctx.cloud.stop()

    app = FastAPI(title="Škoda Mate", lifespan=lifespan, dependencies=[Depends(ctx.guard)])
    # Added last = runs first: headers wrap everything, and the size check runs before any body is parsed.
    app.add_middleware(BodyLimit, authorized=ctx.authorized)
    app.add_middleware(SecurityHeaders)
    app.state.ctx = ctx
    app.state.setup_code = ctx.setup_code  # for tests; people read the code from the log
    static_dir = HERE / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    for module in (pages, auth_routes, setup, mqtt, vehicles, trips, charges, reports, places_routes, settings):
        app.include_router(module.router)
    return app


def _start_demo(ctx: AppContext) -> None:
    """DEMO=1: a fictional car (or two) and ~60 days of history, no account and no network."""
    conn = ctx.conn
    if not conn.execute("SELECT 1 FROM vehicles WHERE vin=?", (demo.DEMO_VIN,)).fetchone():
        demo.seed(conn)
    if ctx.cfg.demo_cars >= 2 and not conn.execute("SELECT 1 FROM vehicles WHERE vin=?", (demo.DEMO_VIN2,)).fetchone():
        demo.seed(conn, rng_seed=11, vin=demo.DEMO_VIN2, name=demo.SECOND["name"], plate=demo.SECOND["plate"],
                  model=demo.SECOND["model"])
    last = recorder.last_snapshot(conn, conn.execute("SELECT id FROM vehicles WHERE vin=?", (demo.DEMO_VIN,)).fetchone()["id"])
    vins = [demo.DEMO_VIN, *([demo.DEMO_VIN2] if ctx.cfg.demo_cars >= 2 else [])]
    ctx.cloud.start(demo.DemoApi(odo=(last["mileage_km"] if last and last["mileage_km"] else 14820),
                                 soc=(last["soc"] if last and last["soc"] is not None else 64.0)), vins)


def app():  # uvicorn --factory skoda_mate.web:app
    return create_app()
