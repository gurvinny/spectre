"""Single-admin authentication helpers (standard library only).

Passwords are hashed with PBKDF2-HMAC-SHA256 (per-user random salt); sessions
are opaque random tokens stored server-side in SQLite with an expiry. No third-
party crypto dependency is required.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 200_000
_ALGO = "sha256"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return ``(hash_hex, salt_hex)`` for *password*."""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"),
                             bytes.fromhex(salt), _ITERATIONS)
    return dk.hex(), salt


def verify_password(password: str, expected_hash: str, salt: str) -> bool:
    """Constant-time verification of *password* against a stored hash."""
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, expected_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
