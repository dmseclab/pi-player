from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

from .extended_app import app
from . import playlist_backup as _playlist_backup  # noqa: F401
from . import website_options as _website_options  # noqa: F401
from . import appliance as _appliance  # noqa: F401
from . import player_info as _player_info  # noqa: F401
from .db import db, get_setting


_SETUP_ALLOWED = (
    "/setup",
    "/api/setup/",
    "/api/health",
    "/api/player/",
    "/player",
    "/static/",
    "/favicon.ico",
)


@app.middleware("http")
async def enforce_first_time_setup(request: Request, call_next):
    path = request.url.path
    with db() as conn:
        setup_required = get_setting(conn, "setup_required", "0") == "1"

    if setup_required:
        allowed = path == "/setup" or any(path.startswith(prefix) for prefix in _SETUP_ALLOWED)
        if not allowed:
            if path.startswith("/api/"):
                return RedirectResponse(url="/setup", status_code=307)
            return RedirectResponse(url="/setup", status_code=303)

    return await call_next(request)


__all__ = ["app"]
