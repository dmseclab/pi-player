from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .db import audit, db, get_setting, set_setting
from .main import app, require_user

DEFAULT_BRANDING = {
    "product_name": "Pi Player",
    "company_name": "",
    "primary_color": "#0F2F2B",
    "secondary_color": "#7FAFA8",
    "support_name": "",
    "support_email": "",
    "support_url": "",
    "footer_text": "",
    "show_powered_by": True,
}

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandingSettingsRequest(BaseModel):
    product_name: str = Field(min_length=1, max_length=80)
    company_name: str = Field(default="", max_length=120)
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


def _branding_from_db(conn) -> dict[str, Any]:
    return {
        "product_name": get_setting(conn, "branding_product_name", DEFAULT_BRANDING["product_name"]) or DEFAULT_BRANDING["product_name"],
        "company_name": get_setting(conn, "branding_company_name", DEFAULT_BRANDING["company_name"]) or "",
        "primary_color": get_setting(conn, "branding_primary_color", DEFAULT_BRANDING["primary_color"]) or DEFAULT_BRANDING["primary_color"],
        "secondary_color": get_setting(conn, "branding_secondary_color", DEFAULT_BRANDING["secondary_color"]) or DEFAULT_BRANDING["secondary_color"],
        "support_name": get_setting(conn, "branding_support_name", DEFAULT_BRANDING["support_name"]) or "",
        "support_email": get_setting(conn, "branding_support_email", DEFAULT_BRANDING["support_email"]) or "",
        "support_url": get_setting(conn, "branding_support_url", DEFAULT_BRANDING["support_url"]) or "",
        "footer_text": get_setting(conn, "branding_footer_text", DEFAULT_BRANDING["footer_text"]) or "",
        "show_powered_by": (get_setting(conn, "branding_show_powered_by", "1") or "1") == "1",
        "logo_configured": bool(get_setting(conn, "branding_logo_path", "")),
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
