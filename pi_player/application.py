from __future__ import annotations

from .extended_app import app
from . import playlist_backup as _playlist_backup  # noqa: F401
from . import website_options as _website_options  # noqa: F401

__all__ = ["app"]
