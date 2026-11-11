"""One-time codes and failed sign-in attempts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import EmailOtp, LoginAttempt


class OtpRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, email: str, purpose: str) -> EmailOtp | None:
        return self._db.scalar(select(EmailOtp).where(EmailOtp.email == email, EmailOtp.purpose == purpose))

    def put(self, email: str, purpose: str, code_hash: str, expires_at: datetime, now: datetime) -> None:
        row = self.get(email, purpose)
        if row is None:
            row = EmailOtp(email=email, purpose=purpose)
            self._db.add(row)
        row.code_hash, row.expires_at, row.last_sent_at, row.attempts = code_hash, expires_at, now, 0
        self._db.commit()

    def bump_attempts(self, row: EmailOtp) -> int:
        row.attempts += 1
        self._db.commit()
        return row.attempts

    def delete(self, row: EmailOtp) -> None:
        self._db.delete(row)
        self._db.commit()


class LoginAttemptRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def count_since(self, key: str, since: datetime) -> int:
        stmt = select(func.count()).select_from(LoginAttempt).where(LoginAttempt.key == key,
                                                                    LoginAttempt.created_at >= since)
        return self._db.scalar(stmt) or 0

    def add(self, keys: list[str], now: datetime, prune_before: datetime) -> None:
        self._db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < prune_before))
        self._db.add_all([LoginAttempt(key=k, created_at=now) for k in keys])
        self._db.commit()

    def clear(self, key: str) -> None:
        self._db.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
        self._db.commit()
