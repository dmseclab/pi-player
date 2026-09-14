from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .config import ALLOWED_IMAGE_EXTENSIONS, ASSET_DIR, TMP_DIR
from .db import audit, db, get_setting, now_iso
from .main import app, require_user

PACKAGE_FORMAT = "pi-player-playlist"
PACKAGE_VERSION = 1
IMAGE_DISPLAY_MODES = {"fit", "fill", "stretch"}
WEBSITE_DISPLAY_MODES = {"embed", "direct"}


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned or "playlist"


def _unique_playlist_name(conn, requested: str) -> str:
    base = requested.strip() or "Imported Playlist"
    candidate = base
    counter = 2
    while conn.execute("SELECT 1 FROM playlists WHERE name = ?", (candidate,)).fetchone():
        candidate = f"{base} ({counter})"
        counter += 1
    return candidate


def _image_mode(value: str | None) -> str:
    return value if value in IMAGE_DISPLAY_MODES else "fit"


def _website_mode(value: str | None) -> str:
    return value if value in WEBSITE_DISPLAY_MODES else "embed"


def _zoom_percent(value: Any) -> int:
    try:
        zoom = int(value)
    except (TypeError, ValueError):
        return 100
    return min(200, max(50, zoom))


def _reload_seconds(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 0
    return min(86400, max(0, seconds))


@app.get("/api/playlists/{playlist_id}/export")
def export_playlist(
    playlist_id: str,
    user: Annotated[str, Depends(require_user)],
) -> FileResponse:
    export_id = str(uuid.uuid4())
    package_path = TMP_DIR / f"playlist-export-{export_id}.zip"

    with db() as conn:
        playlist_row = conn.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not playlist_row:
            raise HTTPException(status_code=404, detail="Playlist not found")
        playlist = dict(playlist_row)

        rows = conn.execute(
            """
            SELECT
                playlist_items.id AS item_id,
                playlist_items.position,
                playlist_items.duration_seconds,
                playlist_items.enabled,
                assets.*
            FROM playlist_items
            JOIN assets ON assets.id = playlist_items.asset_id
            WHERE playlist_items.playlist_id = ?
              AND assets.deleted_at IS NULL
            ORDER BY playlist_items.position, playlist_items.created_at
            """,
            (playlist_id,),
        ).fetchall()

        assets: dict[str, dict[str, Any]] = {}
        items: list[dict[str, Any]] = []

        for row in rows:
            record = dict(row)
            asset_id = record["id"]
            if asset_id not in assets:
                asset: dict[str, Any] = {
                    "type": record["type"],
                    "name": record["name"],
                    "display_mode": record["display_mode"],
                    "original_filename": record["original_filename"],
                    "url": record["url"],
                    "mime_type": record["mime_type"],
                    "size_bytes": record["size_bytes"],
                    "checksum_sha256": record["checksum_sha256"],
                }
                if record["type"] == "website":
                    asset["zoom_percent"] = _zoom_percent(record.get("zoom_percent"))
                    asset["reload_seconds"] = _reload_seconds(record.get("reload_seconds"))
                if record["type"] == "image":
                    if not record["storage_path"]:
                        raise HTTPException(status_code=409, detail=f"Image asset '{record['name']}' has no storage path")
                    source = Path(record["storage_path"]).resolve()
                    if not source.is_file() or ASSET_DIR.resolve() not in source.parents:
                        raise HTTPException(status_code=409, detail=f"Image asset '{record['name']}' is missing")
                    asset["file"] = f"assets/{asset_id}{source.suffix.lower()}"
                assets[asset_id] = asset

            items.append(
                {
                    "asset_ref": asset_id,
                    "position": record["position"],
                    "duration_seconds": record["duration_seconds"],
                    "enabled": bool(record["enabled"]),
                }
            )

        manifest = {
            "format": PACKAGE_FORMAT,
            "format_version": PACKAGE_VERSION,
            "exported_at": now_iso(),
            "playlist": {"name": playlist["name"]},
            "assets": assets,
            "items": items,
        }

        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
            for asset_ref, asset in assets.items():
                if asset["type"] != "image":
                    continue
                row = conn.execute("SELECT storage_path FROM assets WHERE id = ?", (asset_ref,)).fetchone()
                source = Path(row["storage_path"]).resolve()
                archive.write(source, asset["file"])

        audit(
            conn,
            user,
            "playlist.export",
            "playlist",
            playlist_id,
            {"name": playlist["name"], "items": len(items), "assets": len(assets)},
        )

    filename = f"{_safe_filename(playlist['name'])}.pi-player.zip"
    return FileResponse(
        package_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(package_path.unlink, missing_ok=True),
    )


@app.post("/api/playlists/import")
def import_playlist(
    user: Annotated[str, Depends(require_user)],
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Playlist package must be a .zip file")

    upload_id = str(uuid.uuid4())
    package_path = TMP_DIR / f"playlist-import-{upload_id}.zip"
    created_files: list[Path] = []

    with db() as conn:
        configured_mb = int(get_setting(conn, "max_upload_mb", "100") or "100")
    max_package_bytes = max(250, configured_mb * 20) * 1024 * 1024

    size = 0
    try:
        with package_path.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_package_bytes:
                    raise HTTPException(status_code=413, detail="Playlist package is too large")
                target.write(chunk)

        try:
            archive = zipfile.ZipFile(package_path, "r")
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Invalid playlist package") from exc

        with archive:
            names = set(archive.namelist())
            if "manifest.json" not in names:
                raise HTTPException(status_code=400, detail="Playlist package has no manifest.json")

            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise HTTPException(status_code=400, detail="Playlist manifest is invalid") from exc

            if manifest.get("format") != PACKAGE_FORMAT or manifest.get("format_version") != PACKAGE_VERSION:
                raise HTTPException(status_code=400, detail="Unsupported playlist package format")

            playlist_data = manifest.get("playlist") or {}
            assets_data = manifest.get("assets") or {}
            items_data = manifest.get("items") or []
            if not isinstance(assets_data, dict) or not isinstance(items_data, list):
                raise HTTPException(status_code=400, detail="Playlist manifest structure is invalid")

            total_uncompressed = sum(info.file_size for info in archive.infolist())
            if total_uncompressed > max_package_bytes:
                raise HTTPException(status_code=413, detail="Expanded playlist package is too large")

            asset_map: dict[str, str] = {}
            created = now_iso()

            with db() as conn:
                playlist_name = _unique_playlist_name(conn, str(playlist_data.get("name") or "Imported Playlist"))
                playlist_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO playlists (id, name, is_active, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
                    (playlist_id, playlist_name, created, created),
                )

                for asset_ref, asset in assets_data.items():
                    if not isinstance(asset, dict):
                        raise HTTPException(status_code=400, detail="Playlist asset definition is invalid")
                    asset_type = asset.get("type")
                    asset_id = str(uuid.uuid4())
                    asset_name = str(asset.get("name") or "Imported Asset").strip()[:120]

                    if asset_type == "image":
                        member = str(asset.get("file") or "")
                        if not member.startswith("assets/") or member not in names or ".." in Path(member).parts:
                            raise HTTPException(status_code=400, detail=f"Image file for '{asset_name}' is missing from package")
                        extension = Path(member).suffix.lower()
                        if extension not in ALLOWED_IMAGE_EXTENSIONS:
                            raise HTTPException(status_code=400, detail=f"Unsupported image type in package: {extension}")

                        destination = ASSET_DIR / f"{asset_id}{extension}"
                        sha256 = hashlib.sha256()
                        written = 0
                        with archive.open(member, "r") as source, destination.open("wb") as target:
                            while chunk := source.read(1024 * 1024):
                                written += len(chunk)
                                if written > max_package_bytes:
                                    raise HTTPException(status_code=413, detail="Image in playlist package is too large")
                                sha256.update(chunk)
                                target.write(chunk)
                        created_files.append(destination)

                        expected_checksum = asset.get("checksum_sha256")
                        actual_checksum = sha256.hexdigest()
                        if expected_checksum and expected_checksum != actual_checksum:
                            raise HTTPException(status_code=400, detail=f"Checksum failed for '{asset_name}'")

                        original_filename = Path(str(asset.get("original_filename") or f"image{extension}")).name
                        conn.execute(
                            """
                            INSERT INTO assets
                            (id, type, name, original_filename, storage_path, url, display_mode,
                             mime_type, size_bytes, checksum_sha256, created_at, updated_at)
                            VALUES (?, 'image', ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                asset_id,
                                asset_name,
                                original_filename,
                                str(destination),
                                _image_mode(asset.get("display_mode")),
                                asset.get("mime_type") or "application/octet-stream",
                                written,
                                actual_checksum,
                                created,
                                created,
                            ),
                        )
                    elif asset_type == "website":
                        url = str(asset.get("url") or "").strip()
                        if not url.startswith(("http://", "https://")):
                            raise HTTPException(status_code=400, detail=f"Website '{asset_name}' has an invalid URL")
                        conn.execute(
                            """
                            INSERT INTO assets
                            (id, type, name, url, display_mode, zoom_percent, reload_seconds, created_at, updated_at)
                            VALUES (?, 'website', ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                asset_id,
                                asset_name,
                                url,
                                _website_mode(asset.get("display_mode")),
                                _zoom_percent(asset.get("zoom_percent")),
                                _reload_seconds(asset.get("reload_seconds")),
                                created,
                                created,
                            ),
                        )
                    else:
                        raise HTTPException(status_code=400, detail=f"Unsupported asset type: {asset_type}")

                    asset_map[str(asset_ref)] = asset_id

                for item in items_data:
                    if not isinstance(item, dict):
                        raise HTTPException(status_code=400, detail="Playlist item definition is invalid")
                    asset_id = asset_map.get(str(item.get("asset_ref")))
                    if not asset_id:
                        raise HTTPException(status_code=400, detail="Playlist item references an unknown asset")
                    duration = int(item.get("duration_seconds", 15))
                    if duration < 1 or duration > 86400:
                        raise HTTPException(status_code=400, detail="Playlist item display time is invalid")
                    position = int(item.get("position", 0))
                    item_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO playlist_items
                        (id, playlist_id, asset_id, position, duration_seconds, enabled, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (item_id, playlist_id, asset_id, position, duration, int(bool(item.get("enabled", True))), created, created),
                    )

                audit(
                    conn,
                    user,
                    "playlist.import",
                    "playlist",
                    playlist_id,
                    {"name": playlist_name, "items": len(items_data), "assets": len(assets_data)},
                )

            return {
                "ok": True,
                "playlist_id": playlist_id,
                "playlist_name": playlist_name,
                "items": len(items_data),
                "assets": len(assets_data),
                "active": False,
            }
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
    finally:
        package_path.unlink(missing_ok=True)
