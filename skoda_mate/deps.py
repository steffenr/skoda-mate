"""The dependency the routers declare: the running installation's AppContext, from app.state."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from .context import AppContext


def get_context(request: Request) -> AppContext:
    return request.app.state.ctx


ContextDep = Annotated[AppContext, Depends(get_context)]
