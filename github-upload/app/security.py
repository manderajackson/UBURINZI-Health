"""Tiny, dependency-free auth: PBKDF2 password hashes + signed session cookies."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request

from app.config import SECRET_KEY

SESSION_COOKIE = "uburinzi_session"
SESSION_HOURS = 12


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return hmac.compare_digest(dk.hex(), digest)


# ------------------------------------------------------------------- sessions
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def create_session_token(user_id: int, role: str, name: str) -> str:
    payload = {
        "uid": user_id,
        "role": role,
        "name": name,
        "exp": (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat(),
    }
    raw = _b64(json.dumps(payload).encode())
    return f"{raw}.{_sign(raw)}"


def read_session_token(token: str) -> dict | None:
    try:
        raw, sig = token.split(".")
        if not hmac.compare_digest(_sign(raw), sig):
            return None
        payload = json.loads(_unb64(raw))
        if datetime.fromisoformat(payload["exp"]) < datetime.now(timezone.utc):
            return None
        return payload
    except Exception:
        return None


def get_current_user(request: Request, db):
    from app.models import User

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = read_session_token(token)
    if not payload:
        return None
    return db.get(User, payload["uid"])


def csrf_token() -> str:
    return secrets.token_hex(16)
