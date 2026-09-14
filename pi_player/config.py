from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _path_from_env(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser().resolve()


DATA_DIR = _path_from_env("PI_PLAYER_DATA_DIR", BASE_DIR / "data")
ASSET_DIR = DATA_DIR / "assets"
TMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "pi_player.sqlite3"
LOG_DIR = _path_from_env("PI_PLAYER_LOG_DIR", DATA_DIR / "logs")

SESSION_COOKIE = "pi_player_session"
SESSION_SECRET = os.environ.get("PI_PLAYER_SESSION_SECRET", "dev-session-secret-change-me")

DEFAULT_USERNAME = os.environ.get("PI_PLAYER_DEFAULT_USER", "pi")
DEFAULT_PASSWORD = os.environ.get("PI_PLAYER_DEFAULT_PASSWORD", "pi")
DEFAULT_MAX_UPLOAD_MB = int(os.environ.get("PI_PLAYER_MAX_UPLOAD_MB", "100"))

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_IMAGE_MIME_PREFIXES = ("image/",)


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
