"""Volatile kiosk telemetry; no heartbeat writes to the signage database."""
from collections import deque
from threading import Lock
from time import monotonic
from typing import Annotated, Literal
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from .db import active_playlist, db, now_iso
from .main import app, require_user

_started=monotonic()
_lock=Lock()
_runtime={'asset_id':None,'asset_name':None,'asset_type':None,'phase':'waiting','page':None,
          'last_seen':None,'last_transition':None,'last_progress':None,'playlist_error':None}
_last_seen=None
_errors=deque(maxlen=20)

class Report(BaseModel):
    event: Literal['heartbeat','selected','ready','progress','error','playlist_error','playlist_ok','idle']
    asset_id: str | None = Field(default=None,max_length=80)
    page: int | None = Field(default=None,ge=1,le=10000)
    message: str | None = Field(default=None,max_length=500)

@app.post('/api/player/report')
def report(payload:Report,request:Request):
    # A remote admin preview must not claim to be the physical kiosk.
    if not request.client or request.client.host not in {'127.0.0.1','::1','testclient'}:
        raise HTTPException(403,'Kiosk telemetry is local only')
    global _last_seen
    asset=None
    if payload.asset_id:
        with db() as conn:
            asset=conn.execute('SELECT id,name,type FROM assets WHERE id=? AND deleted_at IS NULL',(payload.asset_id,)).fetchone()
        if not asset: raise HTTPException(404,'Asset not found')
    with _lock:
        _last_seen=monotonic()
        _runtime['last_seen']=now_iso()
        if payload.event=='selected' and asset:
            _runtime.update(asset_id=asset['id'],asset_name=asset['name'],asset_type=asset['type'],phase='loading',page=None)
        elif payload.event in {'ready','progress'} and payload.asset_id == _runtime['asset_id']:
            _runtime['phase']='displaying'
            _runtime['last_progress']=now_iso()
            if payload.page: _runtime['page']=payload.page
            if payload.event=='ready': _runtime['last_transition']=now_iso()
        elif payload.event=='error':
            _runtime['phase']='skipping'
            _errors.appendleft({'at':now_iso(),'asset_id':payload.asset_id,'asset_name':asset['name'] if asset else None,'message':payload.message})
        elif payload.event=='playlist_error': _runtime['playlist_error']=payload.message
        elif payload.event=='playlist_ok': _runtime['playlist_error']=None
        elif payload.event=='idle': _runtime.update(phase='idle',asset_id=None,asset_name=None,asset_type=None,page=None)
    return {'ok':True}

def snapshot():
    with db() as conn:
        playlist=active_playlist(conn)
        playback=conn.execute('SELECT state FROM playback_state WHERE id=1').fetchone()
        enabled=conn.execute('SELECT COUNT(*) FROM playlist_items JOIN assets ON assets.id=playlist_items.asset_id WHERE playlist_id=? AND enabled=1 AND deleted_at IS NULL',(playlist['id'] if playlist else '',)).fetchone()[0]
    with _lock:
        age=round(monotonic()-_last_seen,1) if _last_seen is not None else None
        expected=bool(playlist and enabled and playback['state']=='playing')
        stalled=expected and (age>90 if age is not None else monotonic()-_started>120)
        return {**_runtime,'heartbeat_age_seconds':age,'expected_playing':expected,'stalled':stalled,'errors':list(_errors)}

@app.get('/api/player/watchdog')
def watchdog_status():
    status=snapshot()
    return {'stalled':status['stalled'],'heartbeat_age_seconds':status['heartbeat_age_seconds']}

@app.get('/api/playback/status')
def playback_status(user:Annotated[str,Depends(require_user)]):
    return snapshot()
