from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .config import ALLOWED_IMAGE_EXTENSIONS, ALLOWED_IMAGE_MIME_PREFIXES, ASSET_DIR, TMP_DIR
from .db import audit, db, get_setting, now_iso
from .main import AssetUpdateRequest, _asset_response, _ensure_asset, app, require_user, static_html

logger = logging.getLogger(__name__)

IMAGE_DISPLAY_MODES = {"fit", "fill", "stretch"}
WEBSITE_DISPLAY_MODES = {"embed", "direct"}


class ImageSettingsRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    display_mode: str = "fit"


def _clean_image_display_mode(value: str | None) -> str:
    mode = (value or "fit").lower()
    if mode not in IMAGE_DISPLAY_MODES:
        raise HTTPException(status_code=400, detail="Image display mode must be fit, fill or stretch")
    return mode


def _clean_website_display_mode(value: str | None) -> str:
    mode = (value or "embed").lower()
    if mode not in WEBSITE_DISPLAY_MODES:
        raise HTTPException(status_code=400, detail="Website display mode must be embed or direct")
    return mode


def _remove_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", None) or set())
        )
    ]


# Existing image records from pre-0.2 builds inherited the website default "embed".
# Normalize them once at startup without touching the asset files or playlist links.
with db() as conn:
    conn.execute(
        """
        UPDATE assets
        SET display_mode = 'fit', updated_at = ?
        WHERE type = 'image'
          AND display_mode NOT IN ('fit', 'fill', 'stretch')
        """,
        (now_iso(),),
    )


_remove_route("/player", "GET")
_remove_route("/api/assets/upload", "POST")
_remove_route("/api/assets/{asset_id}", "PUT")


@app.get("/player", response_model=None)
def player_page():
    """Always keep the local player controller loaded, including for Direct links."""
    return static_html("player.html")


@app.post("/api/assets/upload")
def upload_asset_with_display_mode(
    user: Annotated[str, Depends(require_user)],
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    display_mode: str = Form(default="fit"),
) -> dict[str, Any]:
    image_mode = _clean_image_display_mode(display_mode)
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
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds configured limit of {max_bytes // 1024 // 1024} MB",
                    )
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
            (id, type, name, original_filename, storage_path, url, display_mode,
             mime_type, size_bytes, checksum_sha256, created_at, updated_at)
            VALUES (?, 'image', ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                display_name,
                original_name,
                str(final_path),
                image_mode,
                mime_type,
                size,
                sha256.hexdigest(),
                created,
                created,
            ),
        )
        audit(
            conn,
            user,
            "asset.upload",
            "asset",
            asset_id,
            {"name": display_name, "bytes": size, "display_mode": image_mode},
        )
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        logger.info("Uploaded image asset %s (%s bytes, mode=%s)", asset_id, size, image_mode)
        return _asset_response(dict(row))


@app.put("/api/assets/{asset_id}")
def update_asset_with_display_mode(
    asset_id: str,
    payload: AssetUpdateRequest,
    user: Annotated[str, Depends(require_user)],
) -> dict[str, Any]:
    with db() as conn:
        asset = _ensure_asset(conn, asset_id)

        if asset["type"] == "website":
            clean_url = payload.url.strip() if payload.url else None
            if not clean_url:
                raise HTTPException(status_code=400, detail="Website assets require a URL")
            parsed = urlparse(clean_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise HTTPException(status_code=400, detail="Website links must start with http:// or https://")
            mode = _clean_website_display_mode(payload.display_mode or asset["display_mode"])
            conn.execute(
                "UPDATE assets SET name = ?, url = ?, display_mode = ?, updated_at = ? WHERE id = ?",
                (payload.name.strip(), clean_url, mode, now_iso(), asset_id),
            )
        else:
            current_mode = asset["display_mode"] if asset["display_mode"] in IMAGE_DISPLAY_MODES else "fit"
            mode = _clean_image_display_mode(payload.display_mode or current_mode)
            conn.execute(
                "UPDATE assets SET name = ?, display_mode = ?, updated_at = ? WHERE id = ?",
                (payload.name.strip(), mode, now_iso(), asset_id),
            )

        audit(conn, user, "asset.update", "asset", asset_id, payload.model_dump())
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return _asset_response(dict(row))


@app.put("/api/assets/{asset_id}/image-settings")
def update_image_settings(
    asset_id: str,
    payload: ImageSettingsRequest,
    user: Annotated[str, Depends(require_user)],
) -> dict[str, Any]:
    mode = _clean_image_display_mode(payload.display_mode)
    with db() as conn:
        asset = _ensure_asset(conn, asset_id)
        if asset["type"] != "image":
            raise HTTPException(status_code=400, detail="Image settings can only be applied to image assets")
        conn.execute(
            "UPDATE assets SET name = ?, display_mode = ?, updated_at = ? WHERE id = ?",
            (payload.name.strip(), mode, now_iso(), asset_id),
        )
        audit(
            conn,
            user,
            "asset.image_settings_update",
            "asset",
            asset_id,
            {"name": payload.name.strip(), "display_mode": mode},
        )
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return _asset_response(dict(row))
