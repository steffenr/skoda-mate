"""Sign in and sign out of the dashboard (the sessions themselves live in auth.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..auth import COOKIE
from ..context import client_ip
from ..deps import ContextDep

router = APIRouter()


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/api/login")
def do_login(body: LoginBody, request: Request, ctx: ContextDep):
    if not ctx.auth.enabled:
        raise HTTPException(404, "login is not enabled")
    ip = client_ip(request)
    if ctx.auth.locked(ip):
        raise HTTPException(429, "too many attempts")
    if not ctx.auth.check(body.email, body.password):
        ctx.auth.fail(ip)
        raise HTTPException(401, "wrong e-mail or password")
    ctx.auth.clear(ip)
    return ctx.session_response({"ok": True}, request)


@router.post("/api/logout")
def do_logout(request: Request, ctx: ContextDep):
    """Signs out every browser, not just this one: sessions are stateless tokens, so revoking means a new key."""
    if ctx.has_session(request):  # a stranger without a session cannot sign the owner out
        ctx.auth.revoke_sessions(ctx.conn)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp
