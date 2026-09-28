"""Password hashing, signed session tokens and permission checks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from .config import settings

PERMISSIONS = [
    "personnel.view", "personnel.edit",
    "device.view", "device.control",
    "attendance.view", "attendance.edit", "attendance.approve",
    "reports.view",
    "system.admin",
]

_ITER = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(user_id: int, pw_hash: str, hours: int | None = None) -> str:
    """Token = payload.signature. Changing the password (hash) invalidates tokens."""
    exp = int(time.time()) + 3600 * (hours or settings.session_hours)
    payload = _b64(json.dumps({"u": user_id, "e": exp, "p": pw_hash[-8:]}).encode())
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest()
    return payload + "." + _b64(sig)


def read_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".")
        good = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(good), sig):
            return None
        data = json.loads(_unb64(payload))
        if data["e"] < time.time():
            return None
        return data
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def user_permissions(user) -> set[str]:
    if user.is_superuser:
        return set(PERMISSIONS)
    if not user.role:
        return set()
    try:
        return set(json.loads(user.role.permissions or "[]"))
    except json.JSONDecodeError:
        return set()
