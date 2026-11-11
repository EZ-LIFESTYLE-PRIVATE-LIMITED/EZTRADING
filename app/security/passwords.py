"""Password hashing (Argon2id) and one-time-code hashing."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        _hasher.hash(password)  # spend the same time either way, so timing doesn't reveal unknown emails
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(pepper: str, email: str, purpose: str, code: str) -> str:
    """Codes are only 6 digits, so they're keyed with a server secret rather than stored plainly."""
    return hmac.new(pepper.encode(), f"{email}|{purpose}|{code}".encode(), hashlib.sha256).hexdigest()
