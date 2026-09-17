"""Dependency-free symmetric encryption for stored provider credentials.

Uses a PBKDF2 keystream XOR — real symmetric encryption tied to SECRET_KEY, not
obfuscation. For production, prefer environment variables (see README §8), which
are never written to the database at all.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from app.config import SECRET_KEY

PREFIX = "enc1:"


def _keystream(key: bytes, salt: bytes, length: int) -> bytes:
    out = bytearray()
    block = b""
    counter = 0
    while len(out) < length:
        block = hashlib.pbkdf2_hmac("sha256", key + counter.to_bytes(4, "big"), salt, 20_000, dklen=32)
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    salt = os.urandom(16)
    raw = plaintext.encode()
    stream = _keystream(SECRET_KEY.encode(), salt, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream))
    mac = hmac.new(SECRET_KEY.encode(), salt + cipher, hashlib.sha256).digest()[:16]
    return PREFIX + base64.urlsafe_b64encode(salt + mac + cipher).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    if not token.startswith(PREFIX):
        return token  # legacy plaintext value
    try:
        blob = base64.urlsafe_b64decode(token[len(PREFIX):].encode())
        salt, mac, cipher = blob[:16], blob[16:32], blob[32:]
        expected = hmac.new(SECRET_KEY.encode(), salt + cipher, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(mac, expected):
            return ""
        stream = _keystream(SECRET_KEY.encode(), salt, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode()
    except Exception:
        return ""


def mask(token: str) -> str:
    """Never render a secret in the UI — show shape only."""
    value = decrypt(token)
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}{'•' * 8}{value[-4:]}"
