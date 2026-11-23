"""FastAPI app: pages, login, first-run setup, cloud lifecycle. Data endpoints live in api.py."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from . import api as data_api
from . import commands, costs, ha_mqtt, mqtt_config, recorder, schema
from .auth import COOKIE, SESSION_TTL, Auth, SetupError, from_private_network, new_setup_code, normalise_setup_code
from .client import SkodaApi, normalise_vin, valid_vin
from .config import Config
from .poller import Poller
from .secrets_store import (SecretBox, clear_api_login, load_api_login, save_api_login, stored_vins)

_LOG = logging.getLogger(__name__)
HERE = Path(__file__).parent
INDEX, LOGIN, SETUP = (HERE / n for n in ("index.html", "login.html", "setup.html"))
# Pages decide for themselves (they redirect); static assets carry no data; everything else is guarded.
PUBLIC = {"/", "/health", "/login", "/setup", "/api/login", "/api/logout"}
MAX_VINS = 5
# FastAPI reads and parses a JSON body before the guard runs, so the size limit sits in front of everything. Signed-in
# callers get room for the 8 MB history import (JSON-escaped); anyone else only needs a login form.
MAX_BODY, MAX_ANON_BODY = 12 * 1024 * 1024, 64 * 1024
# Scripts are ES modules from /static, Leaflet (JS, CSS, its images) from cdnjs, map tiles from OpenStreetMap, the car
# picture (the API's renderUrl) from Škoda's iprenders blob storage; if Škoda moves it, the drawn silhouette shows. Inline
# styles stay allowed: charts and Leaflet set style attributes. No inline scripts anywhere.
CSP = ("default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com; "
       "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
       "img-src 'self' data: blob: https://tile.openstreetmap.org https://cdnjs.cloudflare.com https://iprenders.blob.core.windows.net; "
       "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
# Referrer: cross-origin requests carry only the origin, never a path. Not "same-origin"/"no-referrer": OpenStreetMap's
# tile servers answer requests without a Referer with 403 "Access blocked" (their tile usage policy).
SECURITY_HEADERS = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"x-frame-options", b"DENY")]
NO_CSP = ("/docs", "/redoc")  # FastAPI's API docs load their own scripts from a CDN


class LoginBody(BaseModel):
    email: str
    password: str


class SetupLoginBody(LoginBody):
    current_password: str | None = None  # required to change an existing login
    setup_code: str | None = None  # required to create the first one from a public address (log / setup-code.txt)


class BodyLimit:
    """Pure ASGI middleware: 413 for bodies over the limit, before any route parses them. Declared sizes are checked up
    front; a chunked body (no Content-Length) is read here up to the limit and then handed on."""

    def __init__(self, app, authorized, limit: int = MAX_BODY, anon_limit: int = MAX_ANON_BODY):
        self.app, self.authorized, self.limit, self.anon_limit = app, authorized, limit, anon_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        # the session check only runs for bodies a stranger may not send (most requests have none or a small one)
        limit = lambda: self.limit if self.authorized(Request(scope)) else self.anon_limit  # noqa: E731
        if declared is not None:
            if not declared.isdigit() or (int(declared) > self.anon_limit and int(declared) > limit()):
                return await self.too_large(scope, send)
        elif b"chunked" in headers.get(b"transfer-encoding", b"").lower():
            limit, body, more = limit(), bytearray(), True
            while more:
                msg = await receive()
                if msg["type"] != "http.request":
                    return  # client went away
                body += msg.get("body", b"")
                more = msg.get("more_body", False)
                if len(body) > limit:
                    return await self.too_large(scope, send)
            replayed = False

            async def replay():
                nonlocal replayed
                if replayed:
                    return await receive()
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            return await self.app(scope, replay, send)
        await self.app(scope, receive, send)

    @staticmethod
    async def too_large(scope, send):
        await JSONResponse({"detail": "The request is too large."}, status_code=413)(scope, None, send)


class SecurityHeaders:
    """Pure ASGI middleware: the same protective headers on every response (pages, API, static files)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        csp = not scope["path"].startswith(NO_CSP)

        async def send_with_headers(msg):
            if msg["type"] == "http.response.start":
                msg["headers"] = [*msg.get("headers", []), *SECURITY_HEADERS,
                                  *([(b"content-security-policy", CSP.encode())] if csp else [])]
            await send(msg)

        await self.app(scope, receive, send_with_headers)


class ApiLoginBody(BaseModel):
    api_key: str
    vins: str | list[str]
    spin: str | None = None


class SpinBody(BaseModel):
    spin: str = ""


def parse_vins(raw) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw or ""))
    out = []
    for item in items:
        v = normalise_vin(item)
        if not v:
            continue
        if not valid_vin(v):
            raise ValueError(f"'{item.strip()}' is not a valid VIN (17 characters, letters and digits, no I, O or Q).")
        if v not in out:
            out.append(v)
    if not out:
        raise ValueError("Enter at least one VIN.")
    if len(out) > MAX_VINS:
        raise ValueError(f"At most {MAX_VINS} vehicles.")
    return out


def create_app(cfg: Config | None = None, conn=None, poller: Poller | None = None, api_factory=SkodaApi) -> FastAPI:
    """`conn`, `poller` and `api_factory` can be injected (tests). Otherwise the dashboard login and the Škoda API key
    come from the database, where the /setup form put them (never from environment variables)."""
    cfg = cfg or Config.from_env()
    conn = conn or schema.connect(cfg.db_path)
    key_path = None if cfg.db_path == ":memory:" else str(Path(cfg.db_path).with_name("secret.key"))
    box = SecretBox(key_path)
    login = Auth(box.key, conn)
    for v in conn.execute("SELECT id FROM vehicles").fetchall():  # backfill charges that can be read off existing trips/readings
        recorder.infer_charges(conn, v["id"])
    state: dict = {"poller": poller, "task": None, "api": None, "publisher": None}

    def spin() -> str:
        creds = load_api_login(conn, box)
        return creds[2] if creds else ""

    # ------------------------------------------------------------------ cloud lifecycle
    def mqtt_effective() -> dict:
        return mqtt_config.load(conn, box, cfg)

    def mqtt_extras(vin: str) -> dict:
        """Values Mate derives itself, published next to the API's own: the last finished trip and charge."""
        row = conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
        out: dict = {}
        if not row:
            return out
        tariff = costs.load_tariff(conn)
        t = conn.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NOT NULL ORDER BY started_at DESC LIMIT 1", (row["id"],)).fetchone()
        if t:
            t = dict(t)
            out.update(last_trip_km=round(t["distance_km"], 1) if t.get("distance_km") is not None else None,
                       last_trip_kwh=t.get("energy_kwh"), last_trip_consumption=t.get("avg_kwh_100km"))
        c = conn.execute("SELECT * FROM charges WHERE vehicle_id=? AND ended_at IS NOT NULL ORDER BY started_at DESC LIMIT 1", (row["id"],)).fetchone()
        if c:
            c = dict(c)
            out.update(last_charge_kwh=c.get("energy_kwh"), last_charge_cost=(costs.charge_cost(c, tariff) or {}).get("amount"))
        return out

    def make_publisher(p: Poller):
        conf = mqtt_effective()
        state["mqtt_error"] = None
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
                conf["host"], conf["port"], conf["user"], conf["password"], conf["prefix"], tls=conf["tls"], tls_insecure=conf["tls_insecure"],
                discovery=conf["discovery"], commands=conf["commands"], extras=mqtt_extras,
                currency=lambda: costs.load_tariff(conn).get("currency", "EUR"),
                on_command=lambda vin, name, params: asyncio.run_coroutine_threadsafe(run_mqtt_command(vin, name, params), loop))
            return holder["pub"]
        except Exception as e:  # e.g. a TLS setup problem: the dashboard shows it instead of Mate failing
            _LOG.warning("MQTT could not start: %s", e)
            state["mqtt_error"] = str(e)
            return None

    def vehicle_name(vin: str):
        return (conn.execute("SELECT name FROM vehicles WHERE vin=?", (vin,)).fetchone() or [None])[0]

    def apply_mqtt() -> None:
        """Take new MQTT settings into use right away (no restart): replace the publisher and announce the cars again."""
        p = state["poller"]
        if p is None:
            return
        old, p.publisher = p.publisher, None
        if old:
            old.close()
        pub = make_publisher(p)
        p.publisher = pub
        if pub:
            for vin in list(p.rt):
                pub.announce(vin, vehicle_name(vin))
                vid = conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin,)).fetchone()
                last = recorder.last_snapshot(conn, vid["id"]) if vid else None
                if last:
                    pub.publish_state(vin, dict(last))

    def start_cloud(api, vins: list[str], p: Poller | None = None) -> Poller:
        p = p or Poller(conn, api, spin_getter=spin)
        for vin in vins:
            vid = recorder.upsert_vehicle(conn, vin)
            if vin not in p.rt:
                p.add_vehicle(vin, vid)
        p.publisher = make_publisher(p)
        if p.publisher:
            for vin in vins:
                p.publisher.announce(vin, vehicle_name(vin))
        state.update(poller=p, api=api, task=asyncio.create_task(p.run()))
        return p

    async def stop_cloud() -> None:
        p, task, api = state["poller"], state["task"], state["api"]
        if p and task:
            p.stop()
            await task
        if p and p.publisher:
            p.publisher.close()
        if api:
            await api.close()
        state.update(poller=None, task=None, api=None)

    @asynccontextmanager
    async def lifespan(app):
        if cfg.demo and state["poller"] is None:
            from . import demo

            if not conn.execute("SELECT 1 FROM vehicles WHERE vin=?", (demo.DEMO_VIN,)).fetchone():
                demo.seed(conn)
            if cfg.demo_cars >= 2 and not conn.execute("SELECT 1 FROM vehicles WHERE vin=?", (demo.DEMO_VIN2,)).fetchone():
                demo.seed(conn, rng_seed=11, vin=demo.DEMO_VIN2, name=demo.SECOND["name"], plate=demo.SECOND["plate"], model=demo.SECOND["model"])
            last = recorder.last_snapshot(conn, conn.execute("SELECT id FROM vehicles WHERE vin=?", (demo.DEMO_VIN,)).fetchone()["id"])
            start_cloud(demo.DemoApi(odo=(last["mileage_km"] if last and last["mileage_km"] else 14820),
                                     soc=(last["soc"] if last and last["soc"] is not None else 64.0)),
                        [demo.DEMO_VIN, *([demo.DEMO_VIN2] if cfg.demo_cars >= 2 else [])])
        creds = None if (state["poller"] is not None or cfg.demo) else load_api_login(conn, box)
        if creds:
            start_cloud(api_factory(creds[0]), creds[1])
        yield
        await stop_cloud()

    # First run: from outside the home network, creating the login needs a one-time code, so a stranger who reaches a
    # fresh install first cannot claim it. The code is SETUP_CODE, or generated, logged and written to setup-code.txt in
    # the data folder (for container managers that hide logs). From a private address no code is asked: whoever is on
    # the LAN could equally read the log. `python -m skoda_mate reset-password --email ...` creates the login without it.
    code_file = None if cfg.db_path == ":memory:" else Path(cfg.db_path).with_name("setup-code.txt")

    def forget_setup_code() -> None:
        state["setup_code"] = None
        if code_file is not None:
            code_file.unlink(missing_ok=True)

    if login.enabled or cfg.demo:
        forget_setup_code()
    elif cfg.setup_code:
        state["setup_code"] = normalise_setup_code(cfg.setup_code)
        _LOG.warning("First run: open /setup to create the dashboard login (from outside your network it asks for SETUP_CODE)")
    else:
        c = state["setup_code"] = new_setup_code()
        if code_file is not None:
            try:
                fd = os.open(code_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(f"{c[:5]}-{c[5:]}\n")
            except OSError as e:
                _LOG.warning("Could not write %s: %s", code_file, e)
        _LOG.warning("First run: open /setup to create the dashboard login. From outside your network it asks for this "
                     "setup code (also in %s):  %s-%s", code_file or "memory", c[:5], c[5:])

    # ------------------------------------------------------------------ auth
    def has_session(request: Request) -> bool:
        return login.valid_token(request.cookies.get(COOKIE))

    def has_bearer(request: Request) -> bool:
        h = request.headers.get("authorization", "")
        return bool(cfg.api_token) and hmac.compare_digest(h.encode(), f"Bearer {cfg.api_token}".encode())

    def authorized(request: Request) -> bool:
        return cfg.demo or has_session(request) or has_bearer(request)

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    def needs_setup_code(request: Request) -> bool:
        return (not login.enabled and bool(state["setup_code"])
                and not from_private_network(client_ip(request), request.headers.get("x-forwarded-for")))

    def guard(request: Request):
        """Every route goes through here (except PUBLIC and static assets)."""
        path = request.url.path
        if path in PUBLIC or path.startswith("/static/"):
            return
        if login.enabled:
            ok = has_session(request) or has_bearer(request)
        elif cfg.demo:  # demo: a fictional car, nothing to protect
            ok = request.method in ("GET", "HEAD") or path.startswith("/api/setup/") or not cfg.api_token or has_bearer(request)
        else:  # first run, no login yet: only what creating it needs
            ok = ((path == "/api/setup/status" and request.method in ("GET", "HEAD"))
                  or (path == "/api/setup/login" and request.method == "POST") or has_bearer(request))
        if not ok:
            raise HTTPException(401, "not signed in")

    app = FastAPI(title="Škoda Mate", lifespan=lifespan, dependencies=[Depends(guard)])
    # Added last = runs first: headers wrap everything, and the size check runs before any body is parsed.
    app.add_middleware(BodyLimit, authorized=authorized)
    app.add_middleware(SecurityHeaders)
    app.state.setup_code = lambda: state["setup_code"]  # for tests; people read it from the log
    static_dir = HERE / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def is_https(request: Request) -> bool:
        """Did this request arrive over HTTPS? A TLS-terminating proxy (DDEV, nginx, Caddy) tells us in X-Forwarded-Proto."""
        fwd = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        return fwd == "https" or request.url.scheme == "https"

    def session_response(payload: dict, request: Request) -> JSONResponse:
        # The Secure flag must match the connection: a browser silently drops a Secure cookie received over plain HTTP,
        # which looks like "login works, then I am logged out again". COOKIE_SECURE=true forces it (HTTPS-only setups).
        resp = JSONResponse(payload)
        resp.set_cookie(COOKIE, login.make_token(), max_age=SESSION_TTL, httponly=True,
                        samesite="strict", secure=cfg.cookie_secure or is_https(request), path="/")
        return resp

    def skoda_configured() -> bool:
        return state["poller"] is not None or load_api_login(conn, box) is not None

    # ------------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if cfg.demo:
            return INDEX.read_text()
        if not login.enabled:
            return RedirectResponse("/setup", status_code=303)
        if not has_session(request):
            return RedirectResponse("/login", status_code=303)
        if not skoda_configured():
            return RedirectResponse("/setup", status_code=303)
        return INDEX.read_text()

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if not login.enabled:
            return RedirectResponse("/setup", status_code=303)
        if has_session(request):
            return RedirectResponse("/", status_code=303)
        return LOGIN.read_text()

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page(request: Request):
        if login.enabled and not has_session(request):
            return RedirectResponse("/login", status_code=303)
        return SETUP.read_text()

    @app.post("/api/login")
    def do_login(body: LoginBody, request: Request):
        if not login.enabled:
            raise HTTPException(404, "login is not enabled")
        ip = client_ip(request)
        if login.locked(ip):
            raise HTTPException(429, "too many attempts")
        if not login.check(body.email, body.password):
            login.fail(ip)
            raise HTTPException(401, "wrong e-mail or password")
        login.clear(ip)
        return session_response({"ok": True}, request)

    @app.post("/api/logout")
    def do_logout(request: Request):
        """Signs out every browser, not just this one: sessions are stateless tokens, so revoking means a new key."""
        if has_session(request):  # a stranger without a session cannot sign the owner out
            login.revoke_sessions(conn)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/health")
    def health(request: Request):
        """Public, for Docker's HEALTHCHECK (it only needs the 200); the details only for a signed-in caller."""
        if not authorized(request):
            return {"ok": True}
        p = state["poller"]
        sts = [p.status(v) for v in p.rt] if p else []
        return {"ok": True, "version": __version__, "connected": p is not None,
                "last_ok": next((s["last_ok"] for s in sts if s.get("last_ok")), None),
                "last_error": next((s["error"] for s in sts if s.get("error")), None)}

    # ------------------------------------------------------------------ setup
    @app.get("/api/setup/status")
    def setup_status(request: Request):
        if login.enabled and state["setup_code"]:  # the login was created on the command line meanwhile
            forget_setup_code()
        creds = load_api_login(conn, box)
        p = state["poller"]
        vehicles = []
        for vin in (creds[1] if creds else stored_vins(conn)) if (login.enabled or cfg.demo) else []:  # nothing for strangers
            st = p.status(vin) if p else {"known": False}
            vehicles.append({"vin": vin, "name": (conn.execute("SELECT name FROM vehicles WHERE vin=?", (vin,)).fetchone() or [None])[0],
                             "key_expires_at": st.get("key_expires_at"), "error": st.get("error"),
                             "error_kind": st.get("error_kind"), "blocked": st.get("blocked", False), "last_ok": st.get("last_ok")})
        return {"login_set": login.enabled, "login_email": login.email, "skoda_set": skoda_configured(),
                "key_readable": creds is not None or not stored_vins(conn), "vehicles": vehicles,
                "spin_set": bool(creds and creds[2]), "connected": p is not None,
                "setup_code_required": needs_setup_code(request)}

    @app.post("/api/setup/login")
    def setup_login(body: SetupLoginBody, request: Request):
        """Create (first run; from a public address only with the setup code) or change the dashboard login (the guard
        demands a session, and this the current password: a borrowed, still signed-in browser must not be enough to take
        it over). Wrong codes and passwords count towards the same throttle as /api/login."""
        ip = client_ip(request)
        if login.locked(ip):
            raise HTTPException(429, "too many attempts")
        if login.enabled:
            if not login.check(login.email, body.current_password or ""):
                login.fail(ip)
                raise HTTPException(403, "The current password is wrong.")
        elif needs_setup_code(request) and not hmac.compare_digest(normalise_setup_code(body.setup_code).encode(), state["setup_code"].encode()):
            login.fail(ip)
            raise HTTPException(403, "Wrong setup code. It is in Mate's log and in setup-code.txt in the data folder (or it is your SETUP_CODE).")
        try:
            login.set_credentials(conn, body.email, body.password)
        except SetupError as e:
            raise HTTPException(400, str(e))
        login.clear(ip)
        forget_setup_code()  # used up; setup-code.txt goes too
        return session_response({"ok": True}, request)  # signs the caller in with the new credentials

    @app.post("/api/setup/skoda")
    async def setup_skoda(body: ApiLoginBody):
        """Try the API key against every VIN for real; only a working combination is stored."""
        if cfg.demo:
            raise HTTPException(400, "Demo mode: no account needed. Start without DEMO=1 to connect your car.")
        if not login.enabled:
            raise HTTPException(400, "Create the dashboard login first.")
        key = body.api_key.strip()
        if len(key) < 8 or re.search(r"\s", key):
            raise HTTPException(400, "That does not look like an API key. Copy it completely from the MyŠkoda app.")
        try:
            vins = parse_vins(body.vins)
        except ValueError as e:
            raise HTTPException(400, str(e))
        pin = None if body.spin is None else body.spin.strip()
        if pin and not (pin.isdigit() and len(pin) == 4):
            raise HTTPException(400, "The S-PIN is 4 digits (leave it empty if you do not use the auxiliary heater).")
        new_api = api_factory(key)
        trial = Poller(conn, new_api, spin_getter=lambda: pin or "")
        created = []
        for vin in vins:
            if not conn.execute("SELECT 1 FROM vehicles WHERE vin=?", (vin,)).fetchone():
                created.append(vin)
            trial.add_vehicle(vin, recorder.upsert_vehicle(conn, vin))
        for vin in vins:
            res = await trial.poll(vin, reason="setup")
            if not res["ok"]:
                await new_api.close()
                for v in created:  # leave nothing behind for a VIN that never answered
                    conn.execute("DELETE FROM vehicles WHERE vin=? AND id NOT IN (SELECT vehicle_id FROM snapshots)", (v,))
                conn.commit()
                raise HTTPException(400, f"{vin[:3]}…{vin[-4:]}: {res['error']}")
        await stop_cloud()  # only now: a failed attempt above must not disturb a working connection
        save_api_login(conn, box, key, vins, pin)  # pin=None keeps a previously stored S-PIN
        start_cloud(new_api, vins, trial)  # the trial poller already holds fresh data and its next poll time
        return {"ok": True, "vehicles": [{"vin": v, "key_expires_at": trial.rt[v].key_expires_at} for v in vins]}

    @app.post("/api/setup/vehicles")
    async def setup_add_vehicle(body: dict):
        """Add another car to this installation with the API key already stored (the key must cover that VIN)."""
        creds = load_api_login(conn, box)
        p = state["poller"]
        if not creds or p is None:
            raise HTTPException(400, "Connect your API key first.")
        try:
            (vin,) = parse_vins(body.get("vin", ""))
        except ValueError as e:
            raise HTTPException(400, str(e) if "VIN" in str(e) or "valid" in str(e) else "Enter exactly one VIN.")
        if vin in creds[1]:
            raise HTTPException(400, "That car is already connected.")
        if len(creds[1]) >= MAX_VINS:
            raise HTTPException(400, f"At most {MAX_VINS} vehicles.")
        vid = recorder.upsert_vehicle(conn, vin)
        p.add_vehicle(vin, vid)
        res = await p.poll(vin, reason="setup")  # one real request proves the key covers this car
        if not res["ok"]:
            p.remove_vehicle(vin)
            if not conn.execute("SELECT 1 FROM snapshots WHERE vehicle_id=?", (vid,)).fetchone():
                conn.execute("DELETE FROM vehicles WHERE id=?", (vid,))
                conn.commit()
            raise HTTPException(400, f"{vin[:3]}…{vin[-4:]}: {res['error']}")
        save_api_login(conn, box, creds[0], [*creds[1], vin], None)
        if p.publisher:
            p.publisher.announce(vin, (conn.execute("SELECT name FROM vehicles WHERE vin=?", (vin,)).fetchone() or [None])[0])
        return {"ok": True, "id": vid}

    @app.delete("/api/setup/vehicles/{vin}")
    async def setup_remove_vehicle(vin: str):
        """Stop reading one car. Its history stays in the database (and comes back if the car is added again)."""
        creds = load_api_login(conn, box)
        p = state["poller"]
        vin = normalise_vin(vin)
        if not creds or vin not in creds[1]:
            raise HTTPException(404, "That car is not connected.")
        if len(creds[1]) == 1:
            raise HTTPException(400, "This is the only car. Use Disconnect to remove the API key.")
        save_api_login(conn, box, creds[0], [v for v in creds[1] if v != vin], None)
        if p is not None:
            p.remove_vehicle(vin)
        return {"ok": True}

    @app.put("/api/setup/spin")
    def setup_spin(body: SpinBody):
        pin = body.spin.strip()
        if pin and not (pin.isdigit() and len(pin) == 4):
            raise HTTPException(400, "The S-PIN is 4 digits.")
        creds = load_api_login(conn, box)
        if not creds:
            raise HTTPException(400, "Connect your API key first.")
        save_api_login(conn, box, creds[0], creds[1], pin)
        return {"ok": True, "spin_set": bool(pin)}

    @app.delete("/api/setup/skoda")
    async def setup_skoda_forget():
        await stop_cloud()
        clear_api_login(conn)
        return {"ok": True}

    # ------------------------------------------------------------------ MQTT / Home Assistant settings
    def mqtt_payload() -> dict:
        conf = mqtt_effective()
        p = state["poller"]
        pub = p.publisher if p else None
        if pub:
            status = pub.status()
        elif not (conf["enabled"] and conf["host"]):
            status = {"state": "disabled", "error": None, "entities": 0, "vehicles": 0}
        elif state.get("mqtt_error"):
            status = {"state": "error", "error": state["mqtt_error"], "entities": 0, "vehicles": 0}
        else:  # enabled, but Mate is not connected to Škoda yet: nothing to publish and no publisher to run
            status = {"state": "waiting", "error": None, "entities": 0, "vehicles": 0}
        return {"config": mqtt_config.public_view(conf), "status": status, "discovery_prefix": ha_mqtt.DISCOVERY_PREFIX,
                "entities_per_car": len(ha_mqtt.discovery("x", "VIN", None, commands=conf["commands"]))}

    @app.get("/api/settings/mqtt")
    async def mqtt_get():
        return mqtt_payload()

    @app.put("/api/settings/mqtt")
    async def mqtt_put(body: dict):
        try:
            mqtt_config.save(conn, box, body)
        except mqtt_config.MqttConfigError as e:
            raise HTTPException(400, str(e))
        apply_mqtt()
        return mqtt_payload()

    @app.post("/api/settings/mqtt/test")
    async def mqtt_test(body: dict):
        """Try the values on the form without saving or changing anything. A blank password means the stored one, but only
        for the broker it was stored for (otherwise a changed address would hand it to any host)."""
        stored = mqtt_effective()
        try:
            clean = mqtt_config.validate({**body, "enabled": False})
        except mqtt_config.MqttConfigError as e:
            raise HTTPException(400, str(e))
        if not clean["host"]:
            raise HTTPException(400, "Enter the broker address first.")
        if body.get("password"):
            password = str(body["password"])
        elif body.get("clear_password"):
            password = ""
        else:
            try:
                password = mqtt_config.stored_password_for(stored, clean)
            except mqtt_config.MqttConfigError as e:
                return {"ok": False, "message": str(e)}
        res = await asyncio.to_thread(ha_mqtt.probe, clean["host"], clean["port"], clean["user"], password, clean["tls"], clean["tls_insecure"])
        return res

    class Ctx:
        demo = cfg.demo

        def conn(self):
            return conn

        def poller(self):
            return state["poller"]

        def now_iso(self):
            return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

        def tariff(self):
            return costs.load_tariff(conn)

        def spin_set(self):
            return bool(spin())

    data_api.register(app, Ctx())
    return app


def app():  # uvicorn --factory skoda_mate.web:app
    return create_app()
