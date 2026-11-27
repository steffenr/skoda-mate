"""Pure ASGI middleware: request size limit and the security headers. No route sees a request before these run."""
from __future__ import annotations

import json

from starlette.requests import Request

from . import messages

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

        def body_limit() -> int:  # the session check only runs for bodies a stranger may not send
            return self.limit if self.authorized(Request(scope)) else self.anon_limit

        if declared is not None:
            if not declared.isdigit() or (int(declared) > self.anon_limit and int(declared) > body_limit()):
                return await self.too_large(scope, send)
        elif b"chunked" in headers.get(b"transfer-encoding", b"").lower():
            limit, body, more = body_limit(), bytearray(), True
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
        body = json.dumps({"detail": messages.REQUEST_TOO_LARGE,
                           "detail_i18n": messages.i18n(messages.REQUEST_TOO_LARGE)}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


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
