from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import shutil
import socket
import sqlite3
import subprocess
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIME_PREFIXES,
    ASSET_DIR,
    BASE_DIR,
    SESSION_COOKIE,
    TMP_DIR,
    ensure_runtime_dirs,
)
from .db import active_playlist, audit, db, get_setting, init_db, now_iso, row_to_dict, rows_to_dicts, set_setting
from .health import integrity_report
from .logging_config import configure_logging
from .security import create_session, hash_password, read_session, verify_password


configure_logging()
init_db()

logger = logging.getLogger(__name__)

try:
    _startup_health = integrity_report()
    if _startup_health["ok"]:
        logger.info("Startup asset integrity check passed")
    else:
        logger.error("Startup asset integrity check found problems: %s", _startup_health)
except Exception:
    logger.exception("Startup asset integrity check failed")

app = FastAPI(title="Pi Player RK", version=__version__)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class LoginRequest(BaseModel):
    username: str
    password: str


class LinkAssetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=4, max_length=2048)
    display_mode: str = "embed"


class AssetUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=4, max_length=2048)
    display_mode: str | None = None


class PlaylistRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PlaylistItemRequest(BaseModel):
    asset_id: str
    duration_seconds: int = Field(default=15, ge=1, le=86400)
    enabled: bool = True


class PlaylistItemUpdateRequest(BaseModel):
    position: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    enabled: bool | None = None


class SettingsRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=120)
    max_upload_mb: int = Field(ge=1, le=2048)


class PasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


def require_user(session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None) -> str:
    username = read_session(session)
    if not username:
        raise HTTPException(status_code=401, detail="Login required")
    return username


def static_html(name: str) -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "static" / name).read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return static_html("admin.html")


@app.get("/player", response_model=None)
def player():
    direct_url = _active_direct_url()
    if direct_url:
        return RedirectResponse(direct_url)
    return static_html("player.html")


@app.post("/api/login")
def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
    with db() as conn:
        username = get_setting(conn, "admin_username", "pi")
        password_hash = get_setting(conn, "admin_password_hash", "")
        if payload.username != username or not password_hash or not verify_password(payload.password, password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        response.set_cookie(SESSION_COOKIE, create_session(username), httponly=True, samesite="lax")
        audit(conn, username, "login")
        return {"ok": True, "username": username}


@app.post("/api/logout")
def logout(response: Response, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    response.delete_cookie(SESSION_COOKIE)
    with db() as conn:
        audit(conn, user, "logout")
    return {"ok": True}


@app.get("/api/session")
def session(user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    return {"username": user}


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Small unauthenticated endpoint suitable for local monitoring/Zabbix."""
    report = integrity_report(verify_checksums=False)
    return {
        "ok": report["ok"],
        "version": __version__,
        "host": socket.gethostname(),
        "checked_at": report["checked_at"],
        "missing_assets": len(report["missing_assets"]),
        "size_mismatch": len(report["size_mismatch"]),
        "orphan_files": len(report["orphan_files"]),
        "temp_files": len(report["temp_files"]),
        "disk_free": report["disk"]["free"],
    }


@app.post("/api/health/integrity-check")
def run_integrity_check(user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    report = integrity_report(verify_checksums=True)
    with db() as conn:
        audit(conn, user, "health.integrity_check", details={"ok": report["ok"]})
    if report["ok"]:
        logger.info("Asset integrity check passed (requested by %s)", user)
    else:
        logger.error("Asset integrity check found problems (requested by %s): %s", user, report)
    return report


@app.get("/api/status")
def status(user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    del user
    with db() as conn:
        playback = row_to_dict(conn.execute("SELECT * FROM playback_state WHERE id = 1").fetchone())
        playlist = active_playlist(conn)
        usage = shutil.disk_usage(ASSET_DIR)
        return {
            "version": __version__,
            "player_name": get_setting(conn, "player_name", "piPlayer"),
            "host": socket.gethostname(),
            "ip_addresses": _ip_addresses(),
            "ssh_port": 22,
            "playback": playback,
            "active_playlist": playlist,
            "asset_count": conn.execute("SELECT COUNT(*) AS count FROM assets WHERE deleted_at IS NULL").fetchone()["count"],
            "disk": {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
            },
        }


@app.get("/api/settings")
def get_settings(user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    del user
    with db() as conn:
        return {
            "player_name": get_setting(conn, "player_name", "piPlayer"),
            "max_upload_mb": int(get_setting(conn, "max_upload_mb", "100") or "100"),
            "admin_username": get_setting(conn, "admin_username", "pi"),
        }


@app.put("/api/settings")
def update_settings(payload: SettingsRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        set_setting(conn, "player_name", payload.player_name)
        set_setting(conn, "max_upload_mb", str(payload.max_upload_mb))
        audit(conn, user, "settings.update", details=payload.model_dump())
        return {
            "player_name": payload.player_name,
            "max_upload_mb": payload.max_upload_mb,
            "admin_username": get_setting(conn, "admin_username", "pi"),
        }


@app.put("/api/settings/password")
def update_password(payload: PasswordRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        set_setting(conn, "admin_username", payload.username)
        set_setting(conn, "admin_password_hash", hash_password(payload.password))
        audit(conn, user, "settings.password_update", details={"username": payload.username})
        return {"ok": True}


@app.get("/api/assets")
def list_assets(user: Annotated[str, Depends(require_user)]) -> list[dict[str, Any]]:
    del user
    with db() as conn:
        rows = conn.execute("SELECT * FROM assets WHERE deleted_at IS NULL ORDER BY created_at DESC").fetchall()
        return [_asset_response(dict(row)) for row in rows]


@app.post("/api/assets/upload")
def upload_asset(
    user: Annotated[str, Depends(require_user)],
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> dict[str, Any]:
    original_name = Path(file.filename or "upload").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only image uploads are supported in v1")
    if file.content_type and not file.content_type.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail="Uploaded file is not an image")

    with db() as conn:
        max_bytes = int(get_setting(conn, "max_upload_mb", "100") or "100") * 1024 * 1024

    asset_id = str(uuid.uuid4())
    tmp_path = TMP_DIR / f"{asset_id}.upload"
    final_path = ASSET_DIR / f"{asset_id}{extension}"
    sha256 = hashlib.sha256()
    size = 0

    try:
        with tmp_path.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Upload exceeds configured limit of {max_bytes // 1024 // 1024} MB")
                sha256.update(chunk)
                target.write(chunk)
        tmp_path.replace(final_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    mime_type = file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    display_name = name.strip() if name and name.strip() else Path(original_name).stem
    created = now_iso()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO assets
            (id, type, name, original_filename, storage_path, url, mime_type, size_bytes, checksum_sha256, created_at, updated_at)
            VALUES (?, 'image', ?, ?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (asset_id, display_name, original_name, str(final_path), mime_type, size, sha256.hexdigest(), created, created),
        )
        audit(conn, user, "asset.upload", "asset", asset_id, {"name": display_name, "bytes": size})
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        logger.info("Uploaded image asset %s (%s bytes)", asset_id, size)
        return _asset_response(dict(row))


@app.post("/api/assets/link")
def create_link_asset(payload: LinkAssetRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    parsed = urlparse(payload.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Website links must start with http:// or https://")
    display_mode = _clean_display_mode(payload.display_mode)
    asset_id = str(uuid.uuid4())
    created = now_iso()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO assets
            (id, type, name, url, display_mode, created_at, updated_at)
            VALUES (?, 'website', ?, ?, ?, ?, ?)
            """,
            (asset_id, payload.name.strip(), payload.url, display_mode, created, created),
        )
        audit(conn, user, "asset.link_create", "asset", asset_id, payload.model_dump())
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return _asset_response(dict(row))


@app.put("/api/assets/{asset_id}")
def update_asset(asset_id: str, payload: AssetUpdateRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        asset = _ensure_asset(conn, asset_id)
        clean_url = payload.url.strip() if payload.url else None
        if asset["type"] == "website":
            if not clean_url:
                raise HTTPException(status_code=400, detail="Website assets require a URL")
            parsed = urlparse(clean_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise HTTPException(status_code=400, detail="Website links must start with http:// or https://")
            display_mode = _clean_display_mode(payload.display_mode or asset["display_mode"])
            conn.execute(
                "UPDATE assets SET name = ?, url = ?, display_mode = ?, updated_at = ? WHERE id = ?",
                (payload.name.strip(), clean_url, display_mode, now_iso(), asset_id),
            )
        else:
            conn.execute("UPDATE assets SET name = ?, updated_at = ? WHERE id = ?", (payload.name.strip(), now_iso(), asset_id))
        audit(conn, user, "asset.update", "asset", asset_id, payload.model_dump())
        return _asset_response(dict(conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()))


@app.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: str, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        row = _ensure_asset(conn, asset_id)
        conn.execute("UPDATE assets SET deleted_at = ?, updated_at = ? WHERE id = ?", (now_iso(), now_iso(), asset_id))
        conn.execute("DELETE FROM playlist_items WHERE asset_id = ?", (asset_id,))
        audit(conn, user, "asset.delete", "asset", asset_id)
    if row["storage_path"]:
        try:
            Path(row["storage_path"]).unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to delete asset file %s", row["storage_path"])
    return {"ok": True}


@app.get("/media/{asset_id}")
def media(asset_id: str) -> FileResponse:
    with db() as conn:
        row = _ensure_asset(conn, asset_id)
    if row["type"] != "image" or not row["storage_path"]:
        raise HTTPException(status_code=404, detail="No local media for asset")
    path = Path(row["storage_path"]).resolve()
    if not path.exists() or ASSET_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Media file missing")
    return FileResponse(path, media_type=row["mime_type"] or "application/octet-stream", filename=row["original_filename"])


@app.get("/api/playlists")
def list_playlists(user: Annotated[str, Depends(require_user)]) -> list[dict[str, Any]]:
    del user
    with db() as conn:
        playlists = rows_to_dicts(conn.execute("SELECT * FROM playlists ORDER BY name").fetchall())
        return [_playlist_response(conn, playlist) for playlist in playlists]


@app.post("/api/playlists")
def create_playlist(payload: PlaylistRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    playlist_id = str(uuid.uuid4())
    created = now_iso()
    with db() as conn:
        conn.execute(
            "INSERT INTO playlists (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (playlist_id, payload.name.strip(), created, created),
        )
        if conn.execute("SELECT COUNT(*) AS count FROM playlists").fetchone()["count"] == 1:
            conn.execute("UPDATE playlists SET is_active = 1 WHERE id = ?", (playlist_id,))
        audit(conn, user, "playlist.create", "playlist", playlist_id, payload.model_dump())
        return _playlist_response(conn, dict(conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()))


@app.put("/api/playlists/{playlist_id}")
def update_playlist(playlist_id: str, payload: PlaylistRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        _ensure_playlist(conn, playlist_id)
        conn.execute("UPDATE playlists SET name = ?, updated_at = ? WHERE id = ?", (payload.name.strip(), now_iso(), playlist_id))
        audit(conn, user, "playlist.update", "playlist", playlist_id, payload.model_dump())
        return _playlist_response(conn, dict(conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()))


@app.delete("/api/playlists/{playlist_id}")
def delete_playlist(playlist_id: str, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        playlist = _ensure_playlist(conn, playlist_id)
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        if playlist["is_active"]:
            replacement = conn.execute("SELECT id FROM playlists ORDER BY created_at LIMIT 1").fetchone()
            if replacement:
                conn.execute("UPDATE playlists SET is_active = 1 WHERE id = ?", (replacement["id"],))
                conn.execute("UPDATE playback_state SET playlist_id = ?, item_id = NULL, updated_at = ? WHERE id = 1", (replacement["id"], now_iso()))
            else:
                conn.execute("UPDATE playback_state SET playlist_id = NULL, item_id = NULL, state = 'stopped', updated_at = ? WHERE id = 1", (now_iso(),))
        audit(conn, user, "playlist.delete", "playlist", playlist_id)
        return {"ok": True}


@app.post("/api/playlists/{playlist_id}/activate")
def activate_playlist(playlist_id: str, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        _ensure_playlist(conn, playlist_id)
        conn.execute("UPDATE playlists SET is_active = 0")
        conn.execute("UPDATE playlists SET is_active = 1, updated_at = ? WHERE id = ?", (now_iso(), playlist_id))
        conn.execute("UPDATE playback_state SET playlist_id = ?, item_id = NULL, state = 'stopped', updated_at = ? WHERE id = 1", (playlist_id, now_iso()))
        audit(conn, user, "playlist.activate", "playlist", playlist_id)
        return {"ok": True}


@app.post("/api/playlists/{playlist_id}/items")
def add_playlist_item(playlist_id: str, payload: PlaylistItemRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    item_id = str(uuid.uuid4())
    created = now_iso()
    with db() as conn:
        _ensure_playlist(conn, playlist_id)
        _ensure_asset(conn, payload.asset_id)
        next_position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS position FROM playlist_items WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()["position"]
        conn.execute(
            """
            INSERT INTO playlist_items
            (id, playlist_id, asset_id, position, duration_seconds, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, playlist_id, payload.asset_id, next_position, payload.duration_seconds, int(payload.enabled), created, created),
        )
        audit(conn, user, "playlist.item_add", "playlist_item", item_id, payload.model_dump())
        return _playlist_response(conn, dict(conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()))


@app.put("/api/playlists/{playlist_id}/items/{item_id}")
def update_playlist_item(playlist_id: str, item_id: str, payload: PlaylistItemUpdateRequest, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        _ensure_playlist_item(conn, playlist_id, item_id)
        fields = []
        values: list[Any] = []
        if payload.position is not None:
            fields.append("position = ?")
            values.append(payload.position)
        if payload.duration_seconds is not None:
            fields.append("duration_seconds = ?")
            values.append(payload.duration_seconds)
        if payload.enabled is not None:
            fields.append("enabled = ?")
            values.append(int(payload.enabled))
        if fields:
            fields.append("updated_at = ?")
            values.append(now_iso())
            values.extend([playlist_id, item_id])
            conn.execute(f"UPDATE playlist_items SET {', '.join(fields)} WHERE playlist_id = ? AND id = ?", values)
        audit(conn, user, "playlist.item_update", "playlist_item", item_id, payload.model_dump(exclude_none=True))
        return _playlist_response(conn, dict(conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()))


@app.delete("/api/playlists/{playlist_id}/items/{item_id}")
def delete_playlist_item(playlist_id: str, item_id: str, user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        _ensure_playlist_item(conn, playlist_id, item_id)
        conn.execute("DELETE FROM playlist_items WHERE playlist_id = ? AND id = ?", (playlist_id, item_id))
        audit(conn, user, "playlist.item_delete", "playlist_item", item_id)
        return _playlist_response(conn, dict(conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()))


@app.post("/api/playback/start")
def playback_start(user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        playlist = active_playlist(conn)
        if not playlist:
            raise HTTPException(status_code=400, detail="Create and activate a playlist first")
        conn.execute("UPDATE playback_state SET playlist_id = ?, state = 'playing', updated_at = ? WHERE id = 1", (playlist["id"], now_iso()))
        audit(conn, user, "playback.start", "playlist", playlist["id"])
        return {"ok": True}


@app.post("/api/playback/stop")
def playback_stop(user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    with db() as conn:
        conn.execute("UPDATE playback_state SET state = 'stopped', updated_at = ? WHERE id = 1", (now_iso(),))
        audit(conn, user, "playback.stop")
        return {"ok": True}


@app.get("/api/player/playlist")
def player_playlist() -> dict[str, Any]:
    with db() as conn:
        playlist = active_playlist(conn)
        playback = row_to_dict(conn.execute("SELECT * FROM playback_state WHERE id = 1").fetchone())
        if not playlist:
            return {"state": playback["state"], "playlist": None, "items": []}
        return {
            "state": playback["state"],
            "playlist": playlist,
            "items": _playlist_items(conn, playlist["id"]),
        }


@app.post("/api/system/restart-player")
def restart_player(user: Annotated[str, Depends(require_user)]) -> dict[str, Any]:
    command = os.environ.get("PI_PLAYER_RESTART_CMD")
    with db() as conn:
        audit(conn, user, "system.restart_player", details={"configured": bool(command)})
    if not command:
        logger.info("Restart requested by %s, no PI_PLAYER_RESTART_CMD configured", user)
        return {"ok": True, "message": "Restart command is not configured in this environment"}
    subprocess.Popen(command, shell=True)
    logger.info("Restart command launched by %s", user)
    return {"ok": True, "message": "Restart command launched"}


@app.get("/api/logs")
def logs(user: Annotated[str, Depends(require_user)]) -> list[dict[str, Any]]:
    del user
    from .config import LOG_DIR

    entries = []
    for path in sorted(LOG_DIR.glob("*.log")):
        entries.append({"name": path.name, "size_bytes": path.stat().st_size})
    return entries


@app.get("/api/logs/{name}/download")
def download_log(name: str, user: Annotated[str, Depends(require_user)]) -> FileResponse:
    del user
    from .config import LOG_DIR

    path = (LOG_DIR / name).resolve()
    if LOG_DIR.resolve() not in path.parents or not path.exists() or path.suffix != ".log":
        raise HTTPException(status_code=404, detail="Log not found")
    return FileResponse(path, filename=name, media_type="text/plain")


def _ensure_asset(conn, asset_id: str):
    row = conn.execute("SELECT * FROM assets WHERE id = ? AND deleted_at IS NULL", (asset_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    return row


def _ensure_playlist(conn, playlist_id: str):
    row = conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return row


def _ensure_playlist_item(conn, playlist_id: str, item_id: str):
    row = conn.execute("SELECT * FROM playlist_items WHERE playlist_id = ? AND id = ?", (playlist_id, item_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Playlist item not found")
    return row


def _asset_response(row: dict[str, Any]) -> dict[str, Any]:
    row["media_url"] = f"/media/{row['id']}" if row["type"] == "image" else None
    if row["type"] == "image":
        path = Path(row["storage_path"]).resolve() if row.get("storage_path") else None
        row["file_present"] = bool(path and path.is_file() and ASSET_DIR.resolve() in path.parents)
    else:
        row["file_present"] = None
    return row


def _playlist_response(conn, playlist: dict[str, Any]) -> dict[str, Any]:
    playlist["items"] = _playlist_items(conn, playlist["id"])
    return playlist


def _playlist_items(conn, playlist_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            playlist_items.*,
            assets.type AS asset_type,
            assets.name AS asset_name,
            assets.url AS asset_url,
            assets.display_mode AS asset_display_mode,
            assets.mime_type AS asset_mime_type,
            assets.storage_path AS asset_storage_path,
            assets.size_bytes AS asset_size_bytes
        FROM playlist_items
        JOIN assets ON assets.id = playlist_items.asset_id
        WHERE playlist_items.playlist_id = ?
          AND assets.deleted_at IS NULL
        ORDER BY playlist_items.position, playlist_items.created_at
        """,
        (playlist_id,),
    ).fetchall()
    items = rows_to_dicts(rows)
    for item in items:
        item["enabled"] = bool(item["enabled"])
        item["media_url"] = f"/media/{item['asset_id']}" if item["asset_type"] == "image" else None
        if item["asset_type"] == "image":
            path = Path(item["asset_storage_path"]).resolve() if item.get("asset_storage_path") else None
            item["asset_file_present"] = bool(path and path.is_file() and ASSET_DIR.resolve() in path.parents)
        else:
            item["asset_file_present"] = None
    return items


def _active_direct_url() -> str | None:
    with db() as conn:
        playback = row_to_dict(conn.execute("SELECT * FROM playback_state WHERE id = 1").fetchone())
        if not playback or playback["state"] != "playing" or not playback["playlist_id"]:
            return None
        row = conn.execute(
            """
            SELECT assets.url
            FROM playlist_items
            JOIN assets ON assets.id = playlist_items.asset_id
            WHERE playlist_items.playlist_id = ?
              AND playlist_items.enabled = 1
              AND assets.deleted_at IS NULL
              AND assets.type = 'website'
              AND assets.display_mode = 'direct'
            ORDER BY playlist_items.position, playlist_items.created_at
            LIMIT 1
            """,
            (playback["playlist_id"],),
        ).fetchone()
        return row["url"] if row else None


def _ip_addresses() -> list[str]:
    addresses = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in addresses:
                addresses.append(ip)
    except socket.gaierror:
        pass
    return addresses


def _clean_display_mode(value: str) -> str:
    if value not in {"embed", "direct"}:
        raise HTTPException(status_code=400, detail="Website display mode must be embed or direct")
    return value


@app.exception_handler(sqlite3.IntegrityError)  # type: ignore[name-defined]
def integrity_error_handler(request, exc):  # noqa: ANN001
    del request
    logger.warning("Database integrity error: %s", exc)
    return JSONResponse(status_code=400, content={"detail": "That name or value already exists"})
