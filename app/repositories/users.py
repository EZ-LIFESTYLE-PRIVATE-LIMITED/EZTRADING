"""User-scoped repositories: users, settings, wallet, credentials, broker token."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import AutoSchedule, Credential, KiteSessionRow, User, UserSettings, Wallet
from app.domain.errors import ConflictError
from app.security.crypto import SecretBox

DEV_SUB_PREFIX = "dev:"


class UserRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, user_id: int) -> User | None:
        return self._db.get(User, user_id)

    def by_email(self, email: str) -> User | None:
        return self._db.scalar(select(User).where(User.email == email.strip().lower()))

    def upsert(self, google_sub: str, email: str, name: str, picture: str, default_advisor: str) -> User:
        """Sign-in from Google (or the dev login). The email is already verified by the identity provider."""
        user = self._db.scalar(select(User).where(User.google_sub == google_sub))
        if user is None:
            same_email = self.by_email(email)
            if same_email is not None:
                if same_email.google_sub is None:
                    # An email/password account. Google proves the email is theirs, so link the two.
                    # An unverified sign-up's password may have been set by someone else: drop it.
                    if not same_email.email_verified:
                        same_email.password_hash = None
                elif not same_email.google_sub.startswith(DEV_SUB_PREFIX):
                    raise ConflictError("Another account already uses this email address")
                # (A local dev account is adopted on its first real sign-in, keeping keys, wallet and plans.)
                same_email.google_sub = google_sub
                user = same_email
        if user is None:
            user = self._create(email, name, default_advisor, google_sub=google_sub, picture=picture)
        else:
            user.email, user.name = email.lower(), name or user.name
            user.picture = picture or user.picture
        user.email_verified = True
        self._db.commit()
        return user

    def create_password_user(self, email: str, name: str, password_hash: str, default_advisor: str) -> User:
        user = self._create(email, name, default_advisor, password_hash=password_hash)
        self._db.commit()
        return user

    def update(self, user: User, **fields: Any) -> User:
        for key, value in fields.items():
            setattr(user, key, value)
        self._db.commit()
        return user

    def _create(self, email: str, name: str, default_advisor: str, **fields: Any) -> User:
        user = User(email=email.strip().lower(), name=name, **fields)
        self._db.add(user)
        self._db.flush()
        self._db.add(UserSettings(user_id=user.id, advisor_id=default_advisor))
        self._db.add(Wallet(user_id=user.id, deployable=0.0))
        return user


class SettingsRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, user_id: int) -> UserSettings:
        row = self._db.get(UserSettings, user_id)
        if row is None:
            raise LookupError(f"No settings for user {user_id}")
        return row

    def update(self, user_id: int, **fields: Any) -> UserSettings:
        row = self.get(user_id)
        for key, value in fields.items():
            setattr(row, key, value)
        self._db.commit()
        return row

    def by_telegram_chat(self, chat_id: str) -> UserSettings | None:
        return self._db.scalar(select(UserSettings).where(UserSettings.telegram_chat_id == chat_id))


class ScheduleRepository:
    """Auto-analysis schedules. Per-user methods take user_id so one user can never touch another's rows."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_for_user(self, user_id: int) -> list[AutoSchedule]:
        stmt = select(AutoSchedule).where(AutoSchedule.user_id == user_id).order_by(AutoSchedule.id)
        return list(self._db.scalars(stmt))

    def get(self, user_id: int, schedule_id: int) -> AutoSchedule | None:
        row = self._db.get(AutoSchedule, schedule_id)
        return row if row is not None and row.user_id == user_id else None

    def add(self, user_id: int, **fields: Any) -> AutoSchedule:
        row = AutoSchedule(user_id=user_id, **fields)
        self._db.add(row)
        self._db.commit()
        return row

    def update(self, row: AutoSchedule, **fields: Any) -> AutoSchedule:
        for key, value in fields.items():
            setattr(row, key, value)
        self._db.commit()
        return row

    def delete(self, row: AutoSchedule) -> None:
        self._db.delete(row)
        self._db.commit()

    def due(self, now: datetime) -> list[AutoSchedule]:
        stmt = select(AutoSchedule).where(
            AutoSchedule.enabled.is_(True),
            (AutoSchedule.next_run_at.is_(None)) | (AutoSchedule.next_run_at <= now),
        ).order_by(AutoSchedule.user_id, AutoSchedule.id)
        return list(self._db.scalars(stmt))

    def claim(self, schedule_id: int, expected: datetime | None, next_run: datetime) -> bool:
        """Optimistically move next_run_at forward; False if another worker already did."""
        result = self._db.execute(
            update(AutoSchedule)
            .where(AutoSchedule.id == schedule_id,
                   AutoSchedule.next_run_at.is_(None) if expected is None else AutoSchedule.next_run_at == expected)
            .values(next_run_at=next_run)
        )
        self._db.commit()
        return result.rowcount == 1


class WalletRepository:
    def __init__(self, db: Session, user_id: int) -> None:
        self._db = db
        self._user_id = user_id

    def get(self) -> float:
        row = self._db.get(Wallet, self._user_id)
        return float(row.deployable) if row else 0.0

    def set(self, amount: float) -> None:
        row = self._db.get(Wallet, self._user_id)
        if row is None:
            self._db.add(Wallet(user_id=self._user_id, deployable=amount))
        else:
            row.deployable = amount
        self._db.commit()


class CredentialRepository:
    def __init__(self, db: Session, box: SecretBox, user_id: int) -> None:
        self._db = db
        self._box = box
        self._user_id = user_id

    def _row(self, kind: str) -> Credential | None:
        return self._db.scalar(
            select(Credential).where(Credential.user_id == self._user_id, Credential.kind == kind)
        )

    def set(self, kind: str, secret: dict[str, str], hint: str) -> None:
        row = self._row(kind)
        enc = self._box.encrypt_json(secret)
        if row is None:
            self._db.add(Credential(user_id=self._user_id, kind=kind, secret_enc=enc, hint=hint))
        else:
            row.secret_enc, row.hint = enc, hint
        self._db.commit()

    def get(self, kind: str) -> dict[str, str] | None:
        row = self._row(kind)
        return self._box.decrypt_json(row.secret_enc) if row else None

    def delete(self, kind: str) -> None:
        row = self._row(kind)
        if row is not None:
            self._db.delete(row)
            self._db.commit()

    def hints(self) -> dict[str, str]:
        rows = self._db.scalars(select(Credential).where(Credential.user_id == self._user_id))
        return {r.kind: r.hint for r in rows}


class KiteTokenRepository:
    """TokenStore for one user. Kite tokens expire daily, so only today's token is valid."""

    def __init__(self, db: Session, box: SecretBox, user_id: int, today: date) -> None:
        self._db = db
        self._box = box
        self._user_id = user_id
        self._today = today

    def load(self) -> str | None:
        row = self._db.get(KiteSessionRow, self._user_id)
        if row is None or row.issued_on != self._today:
            return None
        return self._box.decrypt(row.access_token_enc)

    def save(self, token: str) -> None:
        row = self._db.get(KiteSessionRow, self._user_id)
        enc = self._box.encrypt(token)
        if row is None:
            self._db.add(KiteSessionRow(user_id=self._user_id, access_token_enc=enc, issued_on=self._today))
        else:
            row.access_token_enc, row.issued_on = enc, self._today
        self._db.commit()

    def clear(self) -> None:
        row = self._db.get(KiteSessionRow, self._user_id)
        if row is not None:
            self._db.delete(row)
            self._db.commit()
