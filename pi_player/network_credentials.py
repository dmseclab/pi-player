"""Candidate root-private wireless credential storage and keyfile rendering.

No CLI, no automatic provisioning, no application/database integration.
The future root-owned controller must serialize reads and mutations under its
exclusive lock and provision the private directory before constructing a store.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from .network_policy import HOTSPOT_SSID, HOTSPOT_ADDRESS, generate_hotspot_password, validate_hotspot_credentials
from .network_wireless import CLIENT_NAME, CLIENT_UUID, HOTSPOT_NAME, HOTSPOT_UUID

STORE_DIR = Path("/etc/pi-player/network/credentials")
STORE_FILE = "wireless.json"


@dataclass(frozen=True)
class Credentials:
    ssid: str
    password: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.ssid, str) or not isinstance(self.password, str):
            raise ValueError("Invalid wireless credential types")
        validate_hotspot_credentials(self.ssid, self.password)


@dataclass(frozen=True)
class WirelessCredentials:
    hotspot: Credentials
    client: Credentials | None = None

    def public_status(self):
        """Intentionally excludes both passwords, including derived PSKs."""
        return {"hotspot_ssid": self.hotspot.ssid, "client_configured": self.client is not None,
                "client_ssid": self.client.ssid if self.client else None}


def encode_credentials(value):
    def encode(item):
        return None if item is None else {"ssid": item.ssid, "password": item.password}
    if not isinstance(value, WirelessCredentials) or not isinstance(value.hotspot, Credentials):
        raise ValueError("Invalid wireless credential record")
    if value.client is not None and not isinstance(value.client, Credentials):
        raise ValueError("Invalid client credential record")
    return json.dumps({"version": 1, "hotspot": encode(value.hotspot),
                       "client": encode(value.client)}, ensure_ascii=True).encode("utf-8") + b"\n"


def decode_credentials(data):
    def decode(item):
        if not isinstance(item, dict) or set(item) != {"ssid", "password"}:
            raise ValueError("Invalid wireless credential entry")
        return Credentials(item["ssid"], item["password"])
    try:
        value = json.loads(data)
        if not isinstance(value, dict) or set(value) != {"version", "hotspot", "client"} or type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("Invalid credential schema")
        return WirelessCredentials(decode(value["hotspot"]),
                                   None if value["client"] is None else decode(value["client"]))
    except (ValueError, TypeError, UnicodeError):
        # JSON decoding errors can carry the original secret-bearing document.
        raise ValueError("Invalid wireless credential record") from None


class CredentialStore:
    def __init__(self, directory=STORE_DIR, *, owner_uid=0):
        self.directory = Path(directory)
        self.owner_uid = owner_uid

    def _open_dir(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != self.owner_uid or stat.S_IMODE(info.st_mode) != 0o700:
            os.close(fd)
            raise PermissionError("Credential directory must be private and owned by controller")
        return fd

    def _read(self, directory_fd):
        fd = os.open(STORE_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise PermissionError("Credential file must be private and owned by controller")
            data = stream.read(4097)
            if len(data) > 4096:
                raise ValueError("Credential record too large")
            return decode_credentials(data)

    def load(self):
        fd = self._open_dir()
        try:
            return self._read(fd)
        finally:
            os.close(fd)

    def _write(self, directory_fd, value, *, replace):
        data = encode_credentials(value)
        temporary = ".wireless-" + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                if os.fstat(stream.fileno()).st_uid != self.owner_uid:
                    raise PermissionError("Credential file owner mismatch")
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, STORE_FILE, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            else:
                # Never replace a previously provisioned credential.
                os.link(temporary, STORE_FILE, src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd, follow_symlinks=False)
                os.unlink(temporary, dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass

    def provision(self):
        """Generate once; invalid existing files fail closed, never reset."""
        fd = self._open_dir()
        try:
            try:
                return self._read(fd)
            except FileNotFoundError:
                value = WirelessCredentials(Credentials(HOTSPOT_SSID, generate_hotspot_password()))
                self._write(fd, value, replace=False)
                return value
        finally:
            os.close(fd)

    def save(self, value):
        """Explicit authenticated change by the future controller only."""
        fd = self._open_dir()
        try:
            self._read(fd)
            self._write(fd, value, replace=True)
        finally:
            os.close(fd)

    def regenerate_hotspot(self):
        """Explicit reset; preserve client configuration and hotspot SSID."""
        old = self.load()
        value = WirelessCredentials(Credentials(old.hotspot.ssid, generate_hotspot_password()), old.client)
        self.save(value)
        return value


def render_profile(credentials, *, hotspot):
    """Return a secret-bearing NetworkManager keyfile, never log this output.

    Encode the SSID as a byte list to avoid keyfile escaping/injection issues.
    WPA2 PSK derivation is standard PBKDF2-HMAC-SHA1 (4096 rounds, 256 bits).
    The derived PSK is itself a credential and must be protected identically.
    """
    if not isinstance(credentials, Credentials) or type(hotspot) is not bool:
        raise ValueError("Invalid profile input")
    ssid = credentials.ssid.encode("utf-8")
    ssid_bytes = "".join(f"{byte};" for byte in ssid)
    psk = hashlib.pbkdf2_hmac("sha1", credentials.password.encode("ascii"), ssid, 4096, 32).hex()
    name, profile = (HOTSPOT_NAME, HOTSPOT_UUID) if hotspot else (CLIENT_NAME, CLIENT_UUID)
    lines = [
        "[connection]", f"id={name}", f"uuid={profile}", "type=wifi",
        "interface-name=wlan0", "autoconnect=false", "[wifi]",
        f"mode={'ap' if hotspot else 'infrastructure'}", f"ssid={ssid_bytes}",
    ]
    if hotspot:
        lines += ["band=bg", "channel=6", "ap-isolation=1"]
    lines += ["[wifi-security]", "key-mgmt=wpa-psk", "proto=rsn;",
              "pairwise=ccmp;", "group=ccmp;", "wps-method=1", "psk-flags=0", f"psk={psk}", "[ipv4]"]
    if hotspot:
        lines += ["method=manual", f"address1={HOTSPOT_ADDRESS}", "never-default=true", "may-fail=false"]
    else:
        lines += ["method=auto", "may-fail=false"]
    lines += ["[ipv6]", "method=disabled", ""]
    return "\n".join(lines)
