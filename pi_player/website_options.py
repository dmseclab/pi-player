from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .db import audit, db, now_iso
from .main import _asset_response, _ensure_asset, active_playlist, app, require_user, row_to_dict, rows_to_dicts


class WebsiteSettingsRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=4, max_length=2048)
    display_mode: str = "embed"
    zoom_percent: int = Field(default=100, ge=50, le=200)
    reload_seconds: int = Field(default=0, ge=0, le=86400)


def _remove_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", None) or set()))
    ]


with db() as conn:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assets)").fetchall()}
    if "zoom_percent" not in columns:
        conn.execute("ALTER TABLE assets ADD COLUMN zoom_percent INTEGER NOT NULL DEFAULT 100")
    if "reload_seconds" not in columns:
        conn.execute("ALTER TABLE assets ADD COLUMN reload_seconds INTEGER NOT NULL DEFAULT 0")


@app.put("/api/assets/{asset_id}/website-settings")
def update_website_settings(
    asset_id: str,
    payload: WebsiteSettingsRequest,
    user: Annotated[str, Depends(require_user)],
) -> dict[str, Any]:
    with db() as conn:
        asset = _ensure_asset(conn, asset_id)
        if asset["type"] != "website":
            raise HTTPException(status_code=400, detail="Website settings can only be applied to website assets")
        parsed = urlparse(payload.url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Website links must start with http:// or https://")
        if payload.display_mode not in {"embed", "direct"}:
            raise HTTPException(status_code=400, detail="Website display mode must be embed or direct")
        conn.execute(
            """UPDATE assets
               SET name = ?, url = ?, display_mode = ?, zoom_percent = ?, reload_seconds = ?, updated_at = ?
               WHERE id = ?""",
            (
                payload.name.strip(),
                payload.url.strip(),
                payload.display_mode,
                payload.zoom_percent,
                payload.reload_seconds,
                now_iso(),
                asset_id,
            ),
        )
        audit(conn, user, "asset.website_settings_update", "asset", asset_id, payload.model_dump())
        row = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return _asset_response(dict(row))


_remove_route("/api/player/playlist", "GET")


@app.get("/api/player/playlist")
def player_playlist_with_website_options() -> dict[str, Any]:
    with db() as conn:
        playlist = active_playlist(conn)
        playback = row_to_dict(conn.execute("SELECT * FROM playback_state WHERE id = 1").fetchone())
        if not playlist:
            return {"state": playback["state"], "playlist": None, "items": []}
        rows = conn.execute(
            """
            SELECT
                playlist_items.*,
                assets.type AS asset_type,
                assets.name AS asset_name,
                assets.url AS asset_url,
                assets.display_mode AS asset_display_mode,
                assets.zoom_percent AS asset_zoom_percent,
                assets.reload_seconds AS asset_reload_seconds,
                assets.mime_type AS asset_mime_type,
                assets.storage_path AS asset_storage_path,
                assets.size_bytes AS asset_size_bytes
            FROM playlist_items
            JOIN assets ON assets.id = playlist_items.asset_id
            WHERE playlist_items.playlist_id = ?
              AND assets.deleted_at IS NULL
            ORDER BY playlist_items.position, playlist_items.created_at
            """,
            (playlist["id"],),
        ).fetchall()
        items = rows_to_dicts(rows)
        from .config import ASSET_DIR
        from pathlib import Path
        for item in items:
            item["enabled"] = bool(item["enabled"])
            item["media_url"] = f"/media/{item['asset_id']}" if item["asset_type"] == "image" else None
            if item["asset_type"] == "image":
                path = Path(item["asset_storage_path"]).resolve() if item.get("asset_storage_path") else None
                item["asset_file_present"] = bool(path and path.is_file() and ASSET_DIR.resolve() in path.parents)
            else:
                item["asset_file_present"] = None
        return {"state": playback["state"], "playlist": playlist, "items": items}
