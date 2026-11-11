"""Print fresh secrets for .env: session secret, encryption key, VAPID key pair, Telegram webhook secret.

Usage: python scripts/gen_keys.py >> .env   (then review the file)
"""

from __future__ import annotations

import base64
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print(f"SESSION_SECRET={secrets.token_urlsafe(48)}")
    print(f"APP_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    print(f"VAPID_PUBLIC_KEY={b64url(public_raw)}")
    print(f"VAPID_PRIVATE_KEY={b64url(private_raw)}")
    print(f"TELEGRAM_WEBHOOK_SECRET={secrets.token_urlsafe(32)}")


if __name__ == "__main__":
    main()
