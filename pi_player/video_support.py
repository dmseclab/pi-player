from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import ALLOWED_IMAGE_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS, ALLOWED_VIDEO_MIME_TYPES, ASSET_DIR, DB_PATH, TMP_DIR
from .db import active_playlist, audit, db, get_setting, now_iso, row_to_dict, rows_to_dicts, set_setting
from .main import app, require_user, _ensure_asset

IMAGE_MODES={"fit","fill","stretch"}

class VideoSettingsRequest(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    display_mode: str = "fit"
    muted: bool = True
    loop: bool = False

def _remove(path:str,method:str)->None:
    method=method.upper()
    app.router.routes[:]=[r for r in app.router.routes if not (getattr(r,"path",None)==path and method in (getattr(r,"methods",None) or set()))]

def _migrate_assets_table()->None:
    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row
    try:
        sql=(conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='assets'").fetchone() or [""])[0] or ""
        if "'video'" not in sql:
            conn.execute("PRAGMA foreign_keys=OFF")
            cols=[r[1] for r in conn.execute("PRAGMA table_info(assets)").fetchall()]
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""CREATE TABLE assets_video_v1 (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL CHECK (type IN ('image','website','video')),
                name TEXT NOT NULL, original_filename TEXT, storage_path TEXT, url TEXT,
                display_mode TEXT NOT NULL DEFAULT 'embed', mime_type TEXT, size_bytes INTEGER,
                checksum_sha256 TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
                zoom_percent INTEGER NOT NULL DEFAULT 100, reload_seconds INTEGER NOT NULL DEFAULT 0,
                video_muted INTEGER NOT NULL DEFAULT 1, video_loop INTEGER NOT NULL DEFAULT 0
            )""")
            target=["id","type","name","original_filename","storage_path","url","display_mode","mime_type","size_bytes","checksum_sha256","created_at","updated_at","deleted_at","zoom_percent","reload_seconds"]
            common=[c for c in target if c in cols]
            conn.execute(f"INSERT INTO assets_video_v1 ({','.join(common)}) SELECT {','.join(common)} FROM assets")
            conn.execute("DROP TABLE assets")
            conn.execute("ALTER TABLE assets_video_v1 RENAME TO assets")
            conn.commit()
        else:
            cols={r[1] for r in conn.execute("PRAGMA table_info(assets)").fetchall()}
            if "video_muted" not in cols: conn.execute("ALTER TABLE assets ADD COLUMN video_muted INTEGER NOT NULL DEFAULT 1")
            if "video_loop" not in cols: conn.execute("ALTER TABLE assets ADD COLUMN video_loop INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    finally:
        conn.close()

_migrate_assets_table()
with db() as conn:
    if get_setting(conn,"max_upload_mb","100")=="100": set_setting(conn,"max_upload_mb","500")

_remove("/api/assets/upload","POST")
_remove("/media/{asset_id}","GET")
_remove("/api/player/playlist","GET")

@app.post("/api/assets/upload")
def upload_local_asset(user:Annotated[str,Depends(require_user)],file:UploadFile=File(...),name:str|None=Form(default=None),display_mode:str=Form(default="fit"),video_muted:bool=Form(default=True),video_loop:bool=Form(default=False))->dict[str,Any]:
    original=Path(file.filename or "upload").name; ext=Path(original).suffix.lower(); mode=display_mode.lower()
    if mode not in IMAGE_MODES: raise HTTPException(400,"Display mode must be fit, fill or stretch")
    if ext in ALLOWED_IMAGE_EXTENSIONS: asset_type="image"
    elif ext in ALLOWED_VIDEO_EXTENSIONS: asset_type="video"
    else: raise HTTPException(400,"Supported uploads are images, MP4 and WebM video")
    if asset_type=="video" and file.content_type and file.content_type not in ALLOWED_VIDEO_MIME_TYPES and not file.content_type.startswith("video/"):
        raise HTTPException(400,"Uploaded file is not a supported video")
    with db() as conn: max_bytes=int(get_setting(conn,"max_upload_mb","500") or "500")*1024*1024
    asset_id=str(uuid.uuid4()); tmp=TMP_DIR/f"{asset_id}.upload"; final=ASSET_DIR/f"{asset_id}{ext}"; digest=hashlib.sha256(); size=0
    try:
        with tmp.open("wb") as out:
            while chunk:=file.file.read(1024*1024):
                size+=len(chunk)
                if size>max_bytes: raise HTTPException(413,f"Upload exceeds configured limit of {max_bytes//1024//1024} MB")
                digest.update(chunk); out.write(chunk)
        tmp.replace(final)
    finally:
        tmp.unlink(missing_ok=True)
    mime=file.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream"; display=name.strip() if name and name.strip() else Path(original).stem; created=now_iso()
    with db() as conn:
        conn.execute("""INSERT INTO assets (id,type,name,original_filename,storage_path,url,display_mode,mime_type,size_bytes,checksum_sha256,created_at,updated_at,video_muted,video_loop) VALUES (?,?,?,?,?,NULL,?,?,?,?,?,?,?,?)""",
                     (asset_id,asset_type,display,original,str(final),mode,mime,size,digest.hexdigest(),created,created,int(video_muted),int(video_loop)))
        audit(conn,user,"asset.upload","asset",asset_id,{"name":display,"type":asset_type,"bytes":size})
        row=dict(conn.execute("SELECT * FROM assets WHERE id=?",(asset_id,)).fetchone())
    row["media_url"]=f"/media/{asset_id}"; row["file_present"]=True; row["video_muted"]=bool(row["video_muted"]); row["video_loop"]=bool(row["video_loop"]); return row

@app.get("/media/{asset_id}")
def local_media(asset_id:str)->FileResponse:
    with db() as conn: row=_ensure_asset(conn,asset_id)
    if row["type"] not in {"image","video"} or not row["storage_path"]: raise HTTPException(404,"No local media for asset")
    path=Path(row["storage_path"]).resolve()
    if not path.is_file() or ASSET_DIR.resolve() not in path.parents: raise HTTPException(404,"Media file missing")
    response=FileResponse(path,media_type=row["mime_type"] or "application/octet-stream")
    response.headers["Content-Disposition"]=f'inline; filename="{path.name}"'
    response.headers["Cache-Control"]="no-cache"
    return response

@app.put("/api/assets/{asset_id}/video-settings")
def video_settings(asset_id:str,payload:VideoSettingsRequest,user:Annotated[str,Depends(require_user)])->dict[str,Any]:
    if payload.display_mode not in IMAGE_MODES: raise HTTPException(400,"Video display mode must be fit, fill or stretch")
    with db() as conn:
        row=_ensure_asset(conn,asset_id)
        if row["type"]!="video": raise HTTPException(400,"Video settings only apply to video assets")
        conn.execute("UPDATE assets SET name=?,display_mode=?,video_muted=?,video_loop=?,updated_at=? WHERE id=?",(payload.name.strip(),payload.display_mode,int(payload.muted),int(payload.loop),now_iso(),asset_id))
        audit(conn,user,"asset.video_settings_update","asset",asset_id,payload.model_dump())
        result=dict(conn.execute("SELECT * FROM assets WHERE id=?",(asset_id,)).fetchone())
    result["media_url"]=f"/media/{asset_id}"; result["video_muted"]=bool(result["video_muted"]); result["video_loop"]=bool(result["video_loop"]); return result

@app.get("/api/player/playlist")
def player_playlist_video()->dict[str,Any]:
    with db() as conn:
        playlist=active_playlist(conn); playback=row_to_dict(conn.execute("SELECT * FROM playback_state WHERE id=1").fetchone())
        if not playlist:return {"state":playback["state"],"playlist":None,"items":[]}
        rows=conn.execute("""SELECT playlist_items.*,assets.type asset_type,assets.name asset_name,assets.url asset_url,assets.display_mode asset_display_mode,assets.zoom_percent asset_zoom_percent,assets.reload_seconds asset_reload_seconds,assets.mime_type asset_mime_type,assets.storage_path asset_storage_path,assets.size_bytes asset_size_bytes,assets.video_muted asset_video_muted,assets.video_loop asset_video_loop FROM playlist_items JOIN assets ON assets.id=playlist_items.asset_id WHERE playlist_items.playlist_id=? AND assets.deleted_at IS NULL ORDER BY playlist_items.position,playlist_items.created_at""",(playlist["id"],)).fetchall()
        items=rows_to_dicts(rows)
        for item in items:
            item["enabled"]=bool(item["enabled"]); local=item["asset_type"] in {"image","video"}; item["media_url"]=f"/media/{item['asset_id']}" if local else None
            if local:
                p=Path(item["asset_storage_path"]).resolve() if item.get("asset_storage_path") else None; item["asset_file_present"]=bool(p and p.is_file() and ASSET_DIR.resolve() in p.parents)
            else:item["asset_file_present"]=None
            item["asset_video_muted"]=bool(item.get("asset_video_muted",1)); item["asset_video_loop"]=bool(item.get("asset_video_loop",0))
        return {"state":playback["state"],"playlist":playlist,"items":items}
