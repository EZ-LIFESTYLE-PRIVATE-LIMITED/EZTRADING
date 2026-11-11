"""Push subscriptions, notification dedupe log and Telegram link codes."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import NotificationLog, PushSubscription, TelegramLinkCode


class PushSubscriptionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
        row = self._db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        if row is None:
            self._db.add(PushSubscription(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth))
        else:  # re-subscribed browser, possibly by another account: take ownership
            row.user_id, row.p256dh, row.auth = user_id, p256dh, auth
        self._db.commit()

    def remove(self, user_id: int, endpoint: str) -> None:
        self._db.execute(delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint))
        self._db.commit()

    def remove_endpoint(self, endpoint: str) -> None:
        self._db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
        self._db.commit()

    def for_user(self, user_id: int) -> list[dict]:
        rows = self._db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
        return [{"endpoint": r.endpoint, "keys": {"p256dh": r.p256dh, "auth": r.auth}} for r in rows]


class NotificationLogRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def last_fingerprint(self, user_id: int, kind: str) -> str | None:
        return self._db.scalar(
            select(NotificationLog.fingerprint)
            .where(NotificationLog.user_id == user_id, NotificationLog.kind == kind)
            .order_by(NotificationLog.created_at.desc(), NotificationLog.id.desc()).limit(1)
        )

    def sent_since(self, user_id: int, kind: str, since: datetime) -> bool:
        return self._db.scalar(select(NotificationLog.id).where(
            NotificationLog.user_id == user_id, NotificationLog.kind == kind, NotificationLog.created_at >= since
        ).limit(1)) is not None

    def record(self, user_id: int, kind: str, fingerprint: str, at: datetime | None = None) -> None:
        self._db.add(NotificationLog(user_id=user_id, kind=kind, fingerprint=fingerprint, created_at=at or utcnow()))
        self._db.commit()


class TelegramLinkRepository:
    TTL = timedelta(minutes=15)

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, user_id: int) -> str:
        code = secrets.token_urlsafe(16)
        self._db.add(TelegramLinkCode(code=code, user_id=user_id, expires_at=utcnow() + self.TTL))
        self._db.commit()
        return code

    def consume(self, code: str) -> int | None:
        row = self._db.get(TelegramLinkCode, code)
        if row is None:
            return None
        self._db.delete(row)
        self._db.commit()
        return row.user_id if row.expires_at >= utcnow() else None
