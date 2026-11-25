"""Everything the routers need from the running installation, built once by `create_app` and stored on `app.state`.

One typed object instead of a bag of closures: the login rules, the first-run setup code and the derived values
(tariff, timestamp) live here, the Škoda/MQTT connection lives in `cloud.py`.
"""
from __future__ import annotations

import hmac
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from . import costs
from .auth import COOKIE, SESSION_TTL, Auth, from_private_network, new_setup_code, normalise_setup_code
from .client import SkodaApi
from .cloud import Cloud
from .config import Config
from .poller import Poller
from .schema import SafeConnection
from .secrets_store import SecretBox

_LOG = logging.getLogger(__name__)
# Pages decide for themselves (they redirect); static assets carry no data; everything else is guarded.
PUBLIC = {"/", "/health", "/login", "/setup", "/api/login", "/api/logout"}


def is_https(request: Request) -> bool:
    """Did this request arrive over HTTPS? A TLS-terminating proxy (DDEV, nginx, Caddy) tells us in X-Forwarded-Proto."""
    fwd = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return fwd == "https" or request.url.scheme == "https"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@dataclass
class AppContext:
    conn: SafeConnection
    cfg: Config
    auth: Auth
    box: SecretBox
    cloud: Cloud
    api_factory: Callable[[str], SkodaApi]
    setup_value: str | None = None  # the one-time first-run code, while it is unused
    setup_file: Path | None = None

    # ------------------------------------------------------------------ derived values
    @property
    def demo(self) -> bool:
        return self.cfg.demo

    @property
    def poller(self) -> Poller | None:
        return self.cloud.poller

    def now_iso(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    def tariff(self) -> dict:
        return costs.load_tariff(self.conn)

    def spin_set(self) -> bool:
        return self.cloud.spin_set()

    def configured(self) -> bool:
        return self.cloud.configured()

    # ------------------------------------------------------------------ first-run setup code
    def setup_code(self) -> str | None:
        """For tests; people read the code from the log or setup-code.txt (see `init_setup_code`)."""
        return self.setup_value

    def init_setup_code(self) -> None:
        """First run: from outside the home network, creating the login needs a one-time code, so a stranger who reaches a
        fresh install first cannot claim it. The code is SETUP_CODE, or generated, logged and written to setup-code.txt in
        the data folder (for container managers that hide logs). From a private address no code is asked: whoever is on
        the LAN could equally read the log. `python -m skoda_mate reset-password --email ...` creates the login without it."""
        if self.auth.enabled or self.cfg.demo:
            self.forget_setup_code()
        elif self.cfg.setup_code:
            self.setup_value = normalise_setup_code(self.cfg.setup_code)
            _LOG.warning("First run: open /setup to create the dashboard login (from outside your network it asks for SETUP_CODE)")
        else:
            c = self.setup_value = new_setup_code()
            if self.setup_file is not None:
                try:
                    fd = os.open(self.setup_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w") as f:
                        f.write(f"{c[:5]}-{c[5:]}\n")
                except OSError as e:
                    _LOG.warning("Could not write %s: %s", self.setup_file, e)
            _LOG.warning("First run: open /setup to create the dashboard login. From outside your network it asks for this "
                         "setup code (also in %s):  %s-%s", self.setup_file or "memory", c[:5], c[5:])

    def forget_setup_code(self) -> None:
        self.setup_value = None
        if self.setup_file is not None:
            self.setup_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------ auth
    def has_session(self, request: Request) -> bool:
        return self.auth.valid_token(request.cookies.get(COOKIE))

    def has_bearer(self, request: Request) -> bool:
        h = request.headers.get("authorization", "")
        return bool(self.cfg.api_token) and hmac.compare_digest(h.encode(), f"Bearer {self.cfg.api_token}".encode())

    def authorized(self, request: Request) -> bool:
        return self.cfg.demo or self.has_session(request) or self.has_bearer(request)

    def needs_setup_code(self, request: Request) -> bool:
        return (not self.auth.enabled and bool(self.setup_value)
                and not from_private_network(client_ip(request), request.headers.get("x-forwarded-for")))

    def guard(self, request: Request) -> None:
        """Every route goes through here (except PUBLIC and static assets)."""
        path = request.url.path
        if path in PUBLIC or path.startswith("/static/"):
            return
        if self.auth.enabled:
            ok = self.has_session(request) or self.has_bearer(request)
        elif self.cfg.demo:  # demo: a fictional car, nothing to protect
            ok = (request.method in ("GET", "HEAD") or path.startswith("/api/setup/")
                  or not self.cfg.api_token or self.has_bearer(request))
        else:  # first run, no login yet: only what creating it needs
            ok = ((path == "/api/setup/status" and request.method in ("GET", "HEAD"))
                  or (path == "/api/setup/login" and request.method == "POST") or self.has_bearer(request))
        if not ok:
            raise HTTPException(401, "not signed in")

    def session_response(self, payload: dict, request: Request) -> JSONResponse:
        # The Secure flag must match the connection: a browser silently drops a Secure cookie received over plain HTTP,
        # which looks like "login works, then I am logged out again". COOKIE_SECURE=true forces it (HTTPS-only setups).
        resp = JSONResponse(payload)
        resp.set_cookie(COOKIE, self.auth.make_token(), max_age=SESSION_TTL, httponly=True,
                        samesite="strict", secure=self.cfg.cookie_secure or is_https(request), path="/")
        return resp
