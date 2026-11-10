from __future__ import annotations

import hashlib
import os
import secrets
import time
import platform
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .db import audit, db, get_setting, set_setting
from .main import app, require_user, static_html
from .security import hash_password, verify_password

HELPER = os.environ.get("PI_PLAYER_SYSTEM_HELPER", "/usr/local/sbin/pi-player-system")
HOST_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
NTP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")
NTP_CONFIG = Path("/etc/systemd/timesyncd.conf.d/50-pi-player.conf")


class FirstSetupRequest(BaseModel):
    bootstrap_username: str
    bootstrap_password: str
    admin_username: str = Field(min_length=2, max_length=64)
    admin_password: str = Field(min_length=9, max_length=256)
    create_support_user: bool = False
    support_username: str | None = Field(default=None, max_length=31)
    support_password: str | None = Field(default=None, max_length=256)
    hostname: str = Field(default="pi-player", min_length=1, max_length=63)
    ntp_server: str | None = Field(default=None, max_length=253)


class SetupRebootRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class HostnameRequest(BaseModel):
    hostname: str = Field(min_length=1, max_length=63)


class NetworkRequest(BaseModel):
    mode: Literal["dhcp", "static"]
    interface: str = "eth0"
    address: str | None = None
    prefix: int | None = Field(default=None, ge=1, le=32)
    gateway: str | None = None
    dns: list[str] = Field(default_factory=list, max_length=3)


def _run_helper(*args: str, stdin_data: str | None = None) -> None:
    try:
        subprocess.run(["sudo", HELPER, *args], check=True, timeout=30, capture_output=True, text=True, input=stdin_data)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "System operation failed").strip()
        raise HTTPException(status_code=500, detail=detail[-500:]) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail="System helper is unavailable") from exc


def _validate_hostname(value: str) -> str:
    value = value.strip().lower()
    if not HOST_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail="Invalid hostname")
    return value


def _validate_support_user(value: str) -> str:
    value = value.strip().lower()
    if not USER_RE.fullmatch(value) or value in {"root", "pi-player", "pi"}:
        raise HTTPException(status_code=400, detail="Choose a different support username")
    return value


def _configured_ntp_server() -> str:
    """Return a single configured appliance NTP server, if present."""
    try:
        lines = NTP_CONFIG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if line.startswith("NTP="):
            return line.partition("=")[2].strip().split()[0] if line.partition("=")[2].strip() else ""
    return ""


def _validate_ntp_server(value: str | None) -> str:
    server = (value or "").strip()
    if server and not NTP_RE.fullmatch(server):
        raise HTTPException(status_code=400, detail="Invalid NTP server")
    return server


def _ipv4_addresses() -> list[str]:
    result: list[str] = []
    try:
        output = subprocess.check_output(["hostname", "-I"], text=True, timeout=2)
        for token in output.split():
            if ":" not in token and not token.startswith("127."):
                result.append(token)
    except Exception:
        pass
    return result


@app.get("/setup", response_model=None)
def setup_page():
    return static_html("setup.html")


@app.get("/api/setup/status")
def setup_status() -> dict:
    with db() as conn:
        required = get_setting(conn, "setup_required", "0") == "1"
    return {"setup_required": required, "hostname": socket.gethostname(), "ip_addresses": _ipv4_addresses(), "ntp_server": _configured_ntp_server()}


@app.post("/api/setup/complete")
def complete_setup(payload: FirstSetupRequest) -> dict:
    hostname = _validate_hostname(payload.hostname)
    ntp_server = _validate_ntp_server(payload.ntp_server)
    support_user = None
    if payload.create_support_user:
        if not payload.support_username or not payload.support_password:
            raise HTTPException(status_code=400, detail="SSH username and password are required when creating a support account")
        if len(payload.support_password) < 9:
            raise HTTPException(status_code=400, detail="SSH support password must contain at least 9 characters")
        support_user = _validate_support_user(payload.support_username)
    with db() as conn:
        if get_setting(conn, "setup_required", "0") != "1":
            raise HTTPException(status_code=409, detail="First-time setup has already been completed")
        expected_user = get_setting(conn, "admin_username", "pi") or "pi"
        expected_hash = get_setting(conn, "admin_password_hash", "") or ""
        if payload.bootstrap_username != expected_user or not verify_password(payload.bootstrap_password, expected_hash):
            raise HTTPException(status_code=401, detail="Temporary credentials are incorrect")

    # OS changes happen through a narrowly-scoped root helper. If either fails,
    # web credentials are left unchanged so setup can be retried safely.
    if hostname != socket.gethostname().lower():
        _run_helper("hostname", hostname)
    if ntp_server and ntp_server != _configured_ntp_server():
        _run_helper("ntp", ntp_server)
    if support_user is not None:
        _run_helper("support-user", support_user, stdin_data=payload.support_password + "\n")

    reboot_token = secrets.token_urlsafe(32)
    with db() as conn:
        set_setting(conn, "setup_reboot_token_hash", hashlib.sha256(reboot_token.encode()).hexdigest())
        set_setting(conn, "setup_reboot_token_expiry", str(int(time.time()) + 900))
        set_setting(conn, "admin_username", payload.admin_username.strip())
        set_setting(conn, "admin_password_hash", hash_password(payload.admin_password))
        set_setting(conn, "player_name", hostname)
        set_setting(conn, "setup_required", "0")
        audit(conn, payload.admin_username.strip(), "appliance.first_setup", "system", hostname, {"support_user_created": support_user is not None, "support_user": support_user, "ntp_configured": bool(ntp_server)})
    return {"ok": True, "hostname": hostname, "reboot_token": reboot_token, "message": "Initial security setup complete. Restart the player to apply settings."}


@app.post("/api/setup/reboot")
def reboot_after_setup(payload: SetupRebootRequest) -> dict:
    """One-time restart following successful setup, without a persistent reboot token."""
    with db() as conn:
        token_hash = get_setting(conn, "setup_reboot_token_hash", "") or ""
        try:
            expiry = int(get_setting(conn, "setup_reboot_token_expiry", "0") or "0")
        except ValueError:
            expiry = 0
        if (get_setting(conn, "setup_required", "1") != "0"
                or not token_hash or time.time() > expiry
                or not secrets.compare_digest(hashlib.sha256(payload.token.encode()).hexdigest(), token_hash)):
            raise HTTPException(status_code=403, detail="Setup reboot authorization has expired or is invalid")
        set_setting(conn, "setup_reboot_token_hash", "")
        set_setting(conn, "setup_reboot_token_expiry", "0")
        audit(conn, "setup", "appliance.setup_reboot", "system", socket.gethostname())
    _run_helper("reboot")
    return {"ok": True, "message": "Reboot requested"}



@app.get("/api/system/info")
def system_info(user: Annotated[str, Depends(require_user)]) -> dict:
    disk = shutil.disk_usage("/")
    model = "Unknown"
    model_path = Path("/proc/device-tree/model")
    if model_path.exists():
        model = model_path.read_text(errors="ignore").rstrip("\x00\n")
    temp_c = None
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if temp_path.exists():
        try:
            temp_c = round(int(temp_path.read_text().strip()) / 1000, 1)
        except ValueError:
            pass
    return {
        "hostname": socket.gethostname(),
        "ip_addresses": _ipv4_addresses(),
        "model": model,
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
        "cpu_temperature_c": temp_c,
        "ssh_enabled": subprocess.run(["systemctl", "is-enabled", "ssh"], capture_output=True).returncode == 0,
    }


@app.put("/api/system/hostname")
def change_hostname(payload: HostnameRequest, user: Annotated[str, Depends(require_user)]) -> dict:
    hostname = _validate_hostname(payload.hostname)
    _run_helper("hostname", hostname)
    with db() as conn:
        set_setting(conn, "player_name", hostname)
        audit(conn, user, "system.hostname", "system", hostname)
    return {"ok": True, "hostname": hostname, "reboot_recommended": True}


@app.put("/api/system/network")
def change_network(payload: NetworkRequest, user: Annotated[str, Depends(require_user)]) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,32}", payload.interface):
        raise HTTPException(status_code=400, detail="Invalid network interface")
    if payload.mode == "dhcp":
        _run_helper("network-dhcp", payload.interface)
    else:
        if not payload.address or payload.prefix is None or not payload.gateway:
            raise HTTPException(status_code=400, detail="Static mode requires address, prefix and gateway")
        dns = ",".join(payload.dns)
        _run_helper("network-static", payload.interface, payload.address, str(payload.prefix), payload.gateway, dns)
    with db() as conn:
        audit(conn, user, "system.network", "system", payload.interface, payload.model_dump())
    return {"ok": True, "message": "Network configuration applied. Your browser connection may move to the new address."}
