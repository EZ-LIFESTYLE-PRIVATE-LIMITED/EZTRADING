"""Symmetric encryption for secrets at rest (API keys, broker tokens)."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class SecretBox:
    def __init__(self, key: str | bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_settings(cls, settings: Settings) -> "SecretBox":
        if settings.app_encryption_key:
            return cls(settings.app_encryption_key)
        if settings.is_production:
            raise RuntimeError("APP_ENCRYPTION_KEY must be set in production (run scripts/gen_keys.py)")
        # Development convenience: derive a stable key from the session secret.
        digest = hashlib.sha256(settings.session_secret.encode()).digest()
        return cls(base64.urlsafe_b64encode(digest))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Stored secret cannot be decrypted (encryption key changed?)") from exc

    def encrypt_json(self, data: dict[str, Any]) -> str:
        return self.encrypt(json.dumps(data))

    def decrypt_json(self, token: str) -> dict[str, Any]:
        return json.loads(self.decrypt(token))


def mask(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) >= 4 else "••••"
