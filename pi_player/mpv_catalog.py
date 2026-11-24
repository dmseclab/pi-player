"""Offline Phase 2B-2 catalog eligibility against the real Pi Player schema.

No API, service or database migration. This is a read-only lookup, NOT a
complete authorization capability: the future broker must bind an authenticated
Unix connection and current owner epoch and revalidate at FD handoff.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta

from pi_player.mpv_broker import BrokerError, MediaRecord
from pi_player.db import PLAYBACK_GENERATION_TRIGGER_SQL


@dataclass(frozen=True)
class CatalogVideo:
    record: MediaRecord
    checksum_sha256: str
    size_bytes: int
    revision: str
    display_mode: str = 'fit'
    muted: bool = True
    loop: bool = False


def _parse_date(value):
    return date.fromisoformat(value) if value else None


def _parse_time(value):
    if not value:
        return None
    result = time.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError("Offset schedule times are not supported")
    return result


def _allowed_schedule(row: dict, now: datetime) -> bool:
    """Match the existing scheduling.py recurrence and overnight rules."""
    if row["schedule_enabled"] not in (0, 1):
        return False
    if not row["schedule_enabled"]:
        return True
    try:
        mode = row["schedule_mode"]
        start_date = _parse_date(row["schedule_start_date"])
        end_date = _parse_date(row["schedule_end_date"])
        start = _parse_time(row["schedule_start_time"])
        end = _parse_time(row["schedule_end_time"])
        if mode == "window":
            if not all((start_date, end_date, start is not None, end is not None)):
                return False
            instant = now.replace(tzinfo=None)
            return datetime.combine(start_date, start) <= instant < datetime.combine(end_date, end)
        if mode != "recurring":
            return False
        today = now.date()
        if (start_date and today < start_date) or (end_date and today > end_date):
            return False
        raw = row["schedule_weekdays"]
        days = set(range(7)) if raw in (None, "") else {int(n) for n in raw.split(",")}
        if not days or any(day not in range(7) for day in days):
            return False
        current = now.timetz().replace(tzinfo=None)
        if start is not None and end is not None and start > end:
            if current >= start:
                return now.weekday() in days
            if current <= end:
                return (now - timedelta(days=1)).weekday() in days
            return False
        return (now.weekday() in days and
                (start is None or current >= start) and
                (end is None or current <= end))
    except (ValueError, TypeError, AttributeError):
        return False


def _canonical(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def lookup_video(conn: sqlite3.Connection, item_id: str, *,
                 asset_root: str, now: datetime) -> CatalogVideo:
    """Read-only active-playlist lookup; the caller supplies trusted local time.

    Expects an already initialized Pi Player SQLite database, including the
    schedule columns installed by scheduling.py. No schema changes are made.
    """
    if not isinstance(conn, sqlite3.Connection):
        raise BrokerError("Trusted SQLite connection required")
    if not _canonical(item_id):
        raise BrokerError("Invalid playlist item identity")
    if type(asset_root) is not str or not os.path.isabs(asset_root):
        raise BrokerError("Invalid trusted asset root")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise BrokerError("Timezone-aware trusted time required")
    # The schema guard MUST execute inside the same SQLite statement/snapshot
    # as eligibility. Never validate schema and grant from separate reads.
    try:
        cursor = conn.execute("""
            SELECT pi.id AS item_id, pi.asset_id, pi.enabled, pi.updated_at AS item_updated,
                   pi.schedule_enabled, pi.schedule_mode, pi.schedule_start_date,
                   pi.schedule_end_date, pi.schedule_weekdays,
                   pi.schedule_start_time, pi.schedule_end_time,
                   pi.position, pi.duration_seconds,
                   p.id AS playlist_id, p.updated_at AS playlist_updated, p.is_active,
                   ps.state AS playback_state, ps.updated_at AS playback_updated,
                   ps.playback_generation,
                   a.type AS asset_type, a.storage_path, a.mime_type,
                   a.size_bytes, a.checksum_sha256, a.updated_at AS asset_updated,
                   a.display_mode, a.video_muted, a.video_loop, a.deleted_at
              FROM playlist_items AS pi
              JOIN playlists AS p ON p.id = pi.playlist_id
              JOIN assets AS a ON a.id = pi.asset_id
              JOIN playback_state AS ps ON ps.id = 1 AND ps.playlist_id = p.id
             WHERE pi.id = ? AND p.is_active = 1 AND a.deleted_at IS NULL
               AND ps.state = 'playing'
               AND (SELECT COUNT(*) FROM playlists WHERE is_active = 1) = 1
               AND (SELECT COUNT(*) FROM playback_state) = 1
               AND EXISTS (
                    SELECT 1 FROM sqlite_master
                     WHERE type = 'trigger'
                       AND name = 'playback_state_bump_generation'
                       AND tbl_name = 'playback_state'
                       AND sql = ?
               )
        """, (item_id, PLAYBACK_GENERATION_TRIGGER_SQL))
        rows = cursor.fetchall()
    except sqlite3.Error as exc:
        raise BrokerError("Catalog unavailable or not initialized") from exc
    if len(rows) != 1:
        raise BrokerError("Playlist item not in active playlist")
    names = [c[0] for c in cursor.description]
    row = dict(zip(names, rows[0]))
    if (row["enabled"] != 1 or row["asset_type"] != "video"
            or type(row["playback_generation"]) is not int
            or row["playback_generation"] < 0
            or not _allowed_schedule(row, now)):
        raise BrokerError("Video item not currently eligible")
    asset_id = row["asset_id"]
    filename = os.path.basename(row["storage_path"] or "")
    if not _canonical(asset_id) or filename not in (asset_id + ".mp4", asset_id + ".webm"):
        raise BrokerError("Asset does not have canonical local video filename")
    if os.path.normpath(row["storage_path"]) != os.path.join(asset_root, filename):
        raise BrokerError("Asset path differs from configured trusted root")
    if row["mime_type"] not in ("video/mp4", "video/webm"):
        raise BrokerError("Unsupported catalog media type")
    if ((filename.endswith(".mp4") and row["mime_type"] != "video/mp4")
            or (filename.endswith(".webm") and row["mime_type"] != "video/webm")):
        raise BrokerError("Video extension and media type disagree")
    digest = row["checksum_sha256"]
    size = row["size_bytes"]
    if (type(digest) is not str or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or type(size) is not int or size <= 0):
        raise BrokerError("Missing immutable media identity metadata")
    identity_fields = [row[key] for key in (
        "playlist_id", "playlist_updated", "playback_state", "playback_updated",
        "playback_generation",
        "item_id", "item_updated", "position", "duration_seconds",
        "asset_id", "asset_updated", "enabled", "schedule_enabled",
        "schedule_mode", "schedule_start_date", "schedule_end_date",
        "schedule_weekdays", "schedule_start_time", "schedule_end_time",
        "display_mode", "video_muted", "video_loop",
        "storage_path", "mime_type", "size_bytes", "checksum_sha256")]
    try:
        revision = hashlib.sha256(json.dumps(
            identity_fields, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeError) as exc:
        raise BrokerError("Invalid catalog revision metadata") from exc
    return CatalogVideo(
        record=MediaRecord(item_id, filename, revision, True, True),
        checksum_sha256=digest, size_bytes=size, revision=revision,
        display_mode=row['display_mode'], muted=row['video_muted'] == 1,
        loop=row['video_loop'] != 0)


def check_opened_media(opened, catalog: CatalogVideo) -> None:
    """Hash the already-open FD, reject replacement or in-place tampering."""
    if opened.item_id != catalog.record.item_id or opened.playlist_revision != catalog.revision:
        raise BrokerError("Descriptor belongs to another catalog grant")
    try:
        info = os.fstat(opened.fd)
        if info.st_size != catalog.size_bytes:
            raise BrokerError("Media size changed")
        digest = hashlib.sha256()
        offset = 0
        while offset < catalog.size_bytes:
            block = os.pread(opened.fd, min(1024 * 1024, catalog.size_bytes - offset), offset)
            if not block:
                raise BrokerError("Unexpected media EOF")
            digest.update(block)
            offset += len(block)
        if digest.hexdigest() != catalog.checksum_sha256:
            raise BrokerError("Media content differs from catalog checksum")
        final = os.fstat(opened.fd)
        identity_before = (info.st_dev, info.st_ino, info.st_size,
                           info.st_mtime_ns, info.st_ctime_ns)
        identity_after = (final.st_dev, final.st_ino, final.st_size,
                          final.st_mtime_ns, final.st_ctime_ns)
        if identity_before != identity_after:
            raise BrokerError("Media object changed during verification")
    except OSError as exc:
        raise BrokerError("Unable to validate opened media") from exc
