from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .config import ASSET_DIR
from .db import active_playlist, audit, db, ensure_column, now_iso, row_to_dict, rows_to_dicts
from .main import app, require_user, _ensure_playlist_item


class ScheduledPlaylistItemUpdate(BaseModel):
    position: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    enabled: bool | None = None
    schedule_enabled: bool | None = None
    schedule_start_date: date | None = None
    schedule_end_date: date | None = None
    schedule_weekdays: list[int] | None = None
    schedule_start_time: time | None = None
    schedule_end_time: time | None = None

    @field_validator("schedule_weekdays")
    @classmethod
    def valid_weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        unique = sorted(set(value))
        if any(day < 0 or day > 6 for day in unique):
            raise ValueError("Weekdays must use Monday=0 through Sunday=6")
        return unique


def _remove(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", None) or set()))
    ]


def _migrate() -> None:
    with db() as conn:
        ensure_column(conn, "playlist_items", "schedule_enabled", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "playlist_items", "schedule_start_date", "TEXT")
        ensure_column(conn, "playlist_items", "schedule_end_date", "TEXT")
        ensure_column(conn, "playlist_items", "schedule_weekdays", "TEXT")
        ensure_column(conn, "playlist_items", "schedule_start_time", "TEXT")
        ensure_column(conn, "playlist_items", "schedule_end_time", "TEXT")


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_time(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


def _weekdays(value: str | None) -> set[int]:
    if not value:
        return set(range(7))
    return {int(part) for part in value.split(",") if part != ""}


def schedule_matches(item: dict[str, Any], now: datetime | None = None) -> bool:
    if not item.get("schedule_enabled"):
        return True
    now = now or datetime.now().astimezone()
    today = now.date()
    current = now.timetz().replace(tzinfo=None)
    start_date = _parse_date(item.get("schedule_start_date"))
    end_date = _parse_date(item.get("schedule_end_date"))
    if start_date and today < start_date:
        return False
    if end_date and today > end_date:
        return False

    allowed = _weekdays(item.get("schedule_weekdays"))
    start = _parse_time(item.get("schedule_start_time"))
    end = _parse_time(item.get("schedule_end_time"))
    if start and end and start > end:
        # Overnight window: after midnight belongs to the previous day's schedule.
        if current >= start:
            return now.weekday() in allowed
        if current <= end:
            return (now - timedelta(days=1)).weekday() in allowed
        return False
    if now.weekday() not in allowed:
        return False
    if start and current < start:
        return False
    if end and current > end:
        return False
    return True


def _schedule_response(item: dict[str, Any]) -> dict[str, Any]:
    item["enabled"] = bool(item["enabled"])
    item["schedule_enabled"] = bool(item.get("schedule_enabled", 0))
    raw = item.get("schedule_weekdays")
    item["schedule_weekdays"] = sorted(_weekdays(raw)) if raw else list(range(7))
    item["schedule_active_now"] = bool(item["enabled"] and schedule_matches(item))
    return item


_migrate()
_remove("/api/playlists/{playlist_id}/items/{item_id}", "PUT")
_remove("/api/player/playlist", "GET")


@app.put("/api/playlists/{playlist_id}/items/{item_id}")
def update_scheduled_playlist_item(
    playlist_id: str,
    item_id: str,
    payload: ScheduledPlaylistItemUpdate,
    user: Annotated[str, Depends(require_user)],
) -> dict[str, Any]:
    if payload.schedule_start_date and payload.schedule_end_date and payload.schedule_start_date > payload.schedule_end_date:
        raise HTTPException(status_code=400, detail="Schedule start date must be on or before end date")
    with db() as conn:
        _ensure_playlist_item(conn, playlist_id, item_id)
        fields: list[str] = []
        values: list[Any] = []
        mapping = {
            "position": payload.position,
            "duration_seconds": payload.duration_seconds,
            "enabled": int(payload.enabled) if payload.enabled is not None else None,
            "schedule_enabled": int(payload.schedule_enabled) if payload.schedule_enabled is not None else None,
            "schedule_start_date": payload.schedule_start_date.isoformat() if payload.schedule_start_date else None,
            "schedule_end_date": payload.schedule_end_date.isoformat() if payload.schedule_end_date else None,
            "schedule_weekdays": ",".join(str(day) for day in payload.schedule_weekdays) if payload.schedule_weekdays is not None else None,
            "schedule_start_time": payload.schedule_start_time.strftime("%H:%M") if payload.schedule_start_time else None,
            "schedule_end_time": payload.schedule_end_time.strftime("%H:%M") if payload.schedule_end_time else None,
        }
        supplied = payload.model_fields_set
        for column, value in mapping.items():
            if column in supplied:
                fields.append(f"{column}=?")
                values.append(value)
        if fields:
            fields.append("updated_at=?")
            values.append(now_iso())
            values.extend([playlist_id, item_id])
            conn.execute(f"UPDATE playlist_items SET {','.join(fields)} WHERE playlist_id=? AND id=?", values)
        audit(conn, user, "playlist.item_update", "playlist_item", item_id, payload.model_dump(exclude_unset=True, mode="json"))
        playlist = dict(conn.execute("SELECT * FROM playlists WHERE id=?", (playlist_id,)).fetchone())
        rows = conn.execute("""SELECT playlist_items.*, assets.type AS asset_type, assets.name AS asset_name
                             FROM playlist_items JOIN assets ON assets.id=playlist_items.asset_id
                             WHERE playlist_items.playlist_id=? AND assets.deleted_at IS NULL
                             ORDER BY playlist_items.position,playlist_items.created_at""", (playlist_id,)).fetchall()
        playlist["items"] = [_schedule_response(dict(row)) for row in rows]
        return playlist


@app.get("/api/player/playlist")
def scheduled_player_playlist() -> dict[str, Any]:
    with db() as conn:
        playlist = active_playlist(conn)
        playback = row_to_dict(conn.execute("SELECT * FROM playback_state WHERE id=1").fetchone())
        if not playlist:
            return {"state": playback["state"], "playlist": None, "items": []}
        rows = conn.execute("""SELECT playlist_items.*,
                    assets.type asset_type,assets.name asset_name,assets.url asset_url,
                    assets.display_mode asset_display_mode,assets.zoom_percent asset_zoom_percent,
                    assets.reload_seconds asset_reload_seconds,assets.mime_type asset_mime_type,
                    assets.storage_path asset_storage_path,assets.size_bytes asset_size_bytes,
                    assets.video_muted asset_video_muted,assets.video_loop asset_video_loop,
                    assets.pdf_page_seconds asset_pdf_page_seconds,assets.pdf_page_count asset_pdf_page_count,
                    assets.pdf_play_once asset_pdf_play_once
                FROM playlist_items JOIN assets ON assets.id=playlist_items.asset_id
                WHERE playlist_items.playlist_id=? AND assets.deleted_at IS NULL
                ORDER BY playlist_items.position,playlist_items.created_at""", (playlist["id"],)).fetchall()
        items = []
        for row in rows_to_dicts(rows):
            item = _schedule_response(row)
            if not item["schedule_active_now"]:
                continue
            local = item["asset_type"] in {"image", "video", "pdf"}
            item["media_url"] = f"/media/{item['asset_id']}" if local else None
            if local:
                path = Path(item["asset_storage_path"]).resolve() if item.get("asset_storage_path") else None
                item["asset_file_present"] = bool(path and path.is_file() and ASSET_DIR.resolve() in path.parents)
            else:
                item["asset_file_present"] = None
            item["asset_video_muted"] = bool(item.get("asset_video_muted", 1))
            item["asset_video_loop"] = bool(item.get("asset_video_loop", 0))
            items.append(item)
        return {"state": playback["state"], "playlist": playlist, "items": items}
