from __future__ import annotations

import re
import subprocess
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .appliance import _run_helper
from .db import audit, db, get_setting, set_setting
from .main import app, require_user

NTP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")


class NtpRequest(BaseModel):
    server: str = Field(min_length=1, max_length=253)


def _properties(command: list[str]) -> dict[str, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _ntp_status() -> dict:
    time_props = _properties([
        "timedatectl", "show",
        "--property=NTPSynchronized",
        "--property=NTP",
        "--property=Timezone",
    ])
    sync_props = _properties([
        "timedatectl", "show-timesync",
        "--property=ServerName",
        "--property=ServerAddress",
    ])
    with db() as conn:
        configured = get_setting(conn, "ntp_server", "") or ""
    return {
        "configured_server": configured,
        "synchronized": time_props.get("NTPSynchronized", "no").lower() == "yes",
        "ntp_active": time_props.get("NTP", "no").lower() == "yes",
        "timezone": time_props.get("Timezone", "") or "Unknown",
        "server_name": sync_props.get("ServerName", ""),
        "server_address": sync_props.get("ServerAddress", ""),
        "local_time": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


@app.get("/api/system/ntp")
def get_ntp(user: Annotated[str, Depends(require_user)]) -> dict:
    return _ntp_status()


@app.put("/api/system/ntp")
def set_ntp(payload: NtpRequest, user: Annotated[str, Depends(require_user)]) -> dict:
    server = payload.server.strip()
    if not NTP_RE.fullmatch(server):
        raise HTTPException(status_code=400, detail="Enter a valid NTP IP address or hostname")
    _run_helper("ntp", server)
    with db() as conn:
        set_setting(conn, "ntp_server", server)
        audit(conn, user, "system.ntp", "system", server)
    return {"ok": True, **_ntp_status()}
