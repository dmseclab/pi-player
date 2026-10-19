import secrets
import socket
import subprocess

from .db import db, get_setting, set_setting
from .main import app


def _ipv4():
    try:
        return [x for x in subprocess.check_output(["hostname", "-I"], text=True, timeout=2).split() if ":" not in x and not x.startswith("127.")]
    except Exception:
        return []


def get_or_create_player_id(conn) -> str:
    """Return the permanent player identity, creating it once when absent."""
    player_id = (get_setting(conn, "player_id", "") or "").strip().upper()
    if player_id:
        return player_id

    player_id = f"PP-{secrets.token_hex(4).upper()}"
    set_setting(conn, "player_id", player_id)
    return player_id


@app.get("/api/player/info")
def player_info():
    with db() as conn:
        return {
            "player_id": get_or_create_player_id(conn),
            "hostname": socket.gethostname(),
            "player_name": get_setting(conn, "player_name", "pi-player") or "pi-player",
            "ip_addresses": _ipv4(),
            "setup_required": get_setting(conn, "setup_required", "0") == "1",
            "admin_port": 8000,
        }
