from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import DATA_DIR
from .db import audit, db, get_setting, set_setting
from .main import app, require_user

DEFAULT_BRANDING = {
    "product_name": "Pi Player",
    "company_name": "",
    "display_message": "",
    "primary_color": "#0F2F2B",
    "secondary_color": "#7FAFA8",
    "support_name": "",
    "support_email": "",
    "support_url": "",
    "footer_text": "",
    "show_powered_by": True,
}

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
BRANDING_DIR = DATA_DIR / "branding"
MAX_LOGO_BYTES = 2 * 1024 * 1024
_LOGO_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_ALLOWED_LOGO_FILES = {f"logo{suffix}" for suffix in _LOGO_TYPES}


class BrandingSettingsRequest(BaseModel):
    product_name: str = Field(min_length=1, max_length=80)
    company_name: str = Field(default="", max_length=120)
    display_message: str = Field(default="", max_length=120)
    primary_color: str = Field(default=DEFAULT_BRANDING["primary_color"], min_length=7, max_length=7)
    secondary_color: str = Field(default=DEFAULT_BRANDING["secondary_color"], min_length=7, max_length=7)
    support_name: str = Field(default="", max_length=120)
    support_email: str = Field(default="", max_length=254)
    support_url: str = Field(default="", max_length=2048)
    footer_text: str = Field(default="", max_length=240)
    show_powered_by: bool = True


def _clean_text(value: str) -> str:
    return value.strip()


def _clean_color(value: str, label: str) -> str:
    color = value.strip().upper()
    if not _COLOR_RE.fullmatch(color):
        raise HTTPException(status_code=400, detail=f"{label} must use #RRGGBB format")
    return color


def _content_matches_logo_type(suffix: str, content: bytes) -> bool:
    if suffix == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    if suffix == ".webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def _stored_logo_path(conn) -> Path | None:
    filename = (get_setting(conn, "branding_logo_path", "") or "").strip()
    if filename not in _ALLOWED_LOGO_FILES:
        return None
    path = BRANDING_DIR / filename
    return path if path.is_file() else None


def _branding_from_db(conn) -> dict[str, Any]:
    logo_path = _stored_logo_path(conn)
    return {
        "product_name": get_setting(conn, "branding_product_name", DEFAULT_BRANDING["product_name"]) or DEFAULT_BRANDING["product_name"],
        "company_name": get_setting(conn, "branding_company_name", DEFAULT_BRANDING["company_name"]) or "",
        "display_message": get_setting(conn, "branding_display_message", DEFAULT_BRANDING["display_message"]) or "",
        "primary_color": get_setting(conn, "branding_primary_color", DEFAULT_BRANDING["primary_color"]) or DEFAULT_BRANDING["primary_color"],
        "secondary_color": get_setting(conn, "branding_secondary_color", DEFAULT_BRANDING["secondary_color"]) or DEFAULT_BRANDING["secondary_color"],
        "support_name": get_setting(conn, "branding_support_name", DEFAULT_BRANDING["support_name"]) or "",
        "support_email": get_setting(conn, "branding_support_email", DEFAULT_BRANDING["support_email"]) or "",
        "support_url": get_setting(conn, "branding_support_url", DEFAULT_BRANDING["support_url"]) or "",
        "footer_text": get_setting(conn, "branding_footer_text", DEFAULT_BRANDING["footer_text"]) or "",
        "show_powered_by": (get_setting(conn, "branding_show_powered_by", "1") or "1") == "1",
        "logo_configured": logo_path is not None,
        "logo_url": "/api/branding/logo" if logo_path is not None else "",
    }


@app.get("/api/branding")
def get_branding() -> dict[str, Any]:
    """Public branding used by local login, startup and management surfaces."""
    with db() as conn:
        return _branding_from_db(conn)


@app.put("/api/branding")
def update_branding(
    payload: BrandingSettingsRequest,
    user: Annotated[str, Depends(require_user)],
) -> dict[str, Any]:
    product_name = _clean_text(payload.product_name)
    if not product_name:
        raise HTTPException(status_code=400, detail="Product name is required")

    values = {
        "branding_product_name": product_name,
        "branding_company_name": _clean_text(payload.company_name),
        "branding_display_message": _clean_text(payload.display_message),
        "branding_primary_color": _clean_color(payload.primary_color, "Primary colour"),
        "branding_secondary_color": _clean_color(payload.secondary_color, "Secondary colour"),
        "branding_support_name": _clean_text(payload.support_name),
        "branding_support_email": _clean_text(payload.support_email),
        "branding_support_url": _clean_text(payload.support_url),
        "branding_footer_text": _clean_text(payload.footer_text),
        "branding_show_powered_by": "1" if payload.show_powered_by else "0",
    }

    with db() as conn:
        for key, value in values.items():
            set_setting(conn, key, value)
        audit(
            conn,
            user,
            "branding.update",
            details={
                "product_name": product_name,
                "company_name": values["branding_company_name"],
                "primary_color": values["branding_primary_color"],
                "secondary_color": values["branding_secondary_color"],
                "show_powered_by": payload.show_powered_by,
            },
        )
        return _branding_from_db(conn)


@app.get("/api/branding/logo")
def get_branding_logo():
    """Serve the configured logo to public local management surfaces."""
    with db() as conn:
        path = _stored_logo_path(conn)
    if path is None:
        raise HTTPException(status_code=404, detail="Branding logo is not configured")
    media_type = _LOGO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})


@app.post("/api/branding/logo")
async def upload_branding_logo(
    user: Annotated[str, Depends(require_user)],
    file: UploadFile = File(...),
) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    expected_type = _LOGO_TYPES.get(suffix)
    if expected_type is None:
        raise HTTPException(status_code=400, detail="Logo must be PNG, JPEG or WebP")
    if file.content_type and file.content_type.lower() != expected_type:
        raise HTTPException(status_code=400, detail="Logo file type does not match its extension")

    content = await file.read(MAX_LOGO_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Logo file is empty")
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Logo must be 2 MB or smaller")
    if not _content_matches_logo_type(suffix, content):
        raise HTTPException(status_code=400, detail="Logo content does not match its file type")

    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    destination = BRANDING_DIR / f"logo{suffix}"
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".logo-upload-", suffix=".tmp", dir=BRANDING_DIR)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    with db() as conn:
        previous = _stored_logo_path(conn)
        set_setting(conn, "branding_logo_path", destination.name)
        audit(conn, user, "branding.logo.upload", details={"filename": file.filename or "", "size_bytes": len(content)})
        result = _branding_from_db(conn)

    if previous is not None and previous != destination:
        try:
            previous.unlink(missing_ok=True)
        except OSError:
            pass
    return result


@app.delete("/api/branding/logo")
def delete_branding_logo(
    user: Annotated[str, Depends(require_user)],
) -> dict[str, Any]:
    with db() as conn:
        path = _stored_logo_path(conn)
        set_setting(conn, "branding_logo_path", "")
        audit(conn, user, "branding.logo.delete")
        result = _branding_from_db(conn)

    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return result
