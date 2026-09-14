from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Optional

from .config import SESSION_SECRET


PBKDF2_ITERATIONS = 260_000
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iter_text, salt_text, digest_text = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_session(username: str) -> str:
    issued_at = str(int(time.time()))
    payload = f"{username}|{issued_at}"
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return f"{_b64encode(payload.encode('utf-8'))}.{_b64encode(signature)}"


def read_session(token: str | None) -> Optional[str]:
    if not token:
        return None
    try:
        payload_text, signature_text = token.split(".", 1)
        decoded = _b64decode(payload_text).decode("utf-8")
        username, issued_text = decoded.split("|", 1)
        issued_at = int(issued_text)
    except (ValueError, TypeError):
        return None

    if time.time() - issued_at > SESSION_MAX_AGE_SECONDS:
        return None

    payload = f"{username}|{issued_text}"
    expected = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    try:
        actual = _b64decode(signature_text)
    except ValueError:
        return None
    if not hmac.compare_digest(actual, expected):
        return None
    return username
