from __future__ import annotations

import logging
import logging.handlers

from .config import LOG_DIR, ensure_runtime_dirs


def configure_logging() -> None:
    ensure_runtime_dirs()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    app_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    app_handler.setFormatter(formatter)

    error_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "error.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(app_handler)
    root.addHandler(error_handler)
    root.addHandler(logging.StreamHandler())
