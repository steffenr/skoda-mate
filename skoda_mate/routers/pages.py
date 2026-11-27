"""The three HTML pages and the health probe. The pages themselves decide where to redirect a visitor."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import __version__
from ..deps import ContextDep

router = APIRouter()
HERE = Path(__file__).resolve().parent.parent
INDEX, LOGIN, SETUP = (HERE / n for n in ("index.html", "login.html", "setup.html"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request, ctx: ContextDep):
    if ctx.cfg.demo:
        return INDEX.read_text()
    if not ctx.auth.enabled:
        return RedirectResponse("/setup", status_code=303)
    if not ctx.has_session(request):
        return RedirectResponse("/login", status_code=303)
    if not ctx.configured():
        return RedirectResponse("/setup", status_code=303)
    return INDEX.read_text()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, ctx: ContextDep):
    if not ctx.auth.enabled:
        return RedirectResponse("/setup", status_code=303)
    if ctx.has_session(request):
        return RedirectResponse("/", status_code=303)
    return LOGIN.read_text()


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, ctx: ContextDep):
    if ctx.auth.enabled and not ctx.has_session(request):
        return RedirectResponse("/login", status_code=303)
    return SETUP.read_text()


@router.get("/health")
def health(request: Request, ctx: ContextDep):
    """Public, for Docker's HEALTHCHECK (it only needs the 200); the details only for a signed-in caller."""
    if not ctx.authorized(request):
        return {"ok": True}
    p = ctx.poller
    sts = [p.status(v) for v in p.rt] if p else []
    return {"ok": True, "version": __version__, "connected": p is not None,
            "last_ok": next((s["last_ok"] for s in sts if s.get("last_ok")), None),
            "last_error": next((s["error"] for s in sts if s.get("error")), None),
            "last_error_i18n": next((s.get("error_i18n") for s in sts if s.get("error")), None)}
