"""Decides when to notify a user and fans out to their enabled channels (Composite)."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Callable

from app.domain.models import AllocationPlan, Notification
from app.domain.ports import MessengerPort, PushSenderPort
from app.repositories.notifications import NotificationLogRepository, PushSubscriptionRepository
from app.repositories.users import SettingsRepository

log = logging.getLogger(__name__)

PLAN_KIND = "plan"
KITE_KIND = "kite_reconnect"
MAX_LINES = 6


def plan_fingerprint(plan: AllocationPlan) -> str:
    """Identity of 'what the user is being asked to do'; empty when there's nothing to do."""
    actions = sorted(f"{s.symbol}:{s.action.value}" for s in plan.actionable)
    if not actions:
        return ""
    return hashlib.sha256(f"{plan.style}|{'|'.join(actions)}".encode()).hexdigest()[:32]


class NotificationService:
    def __init__(
        self,
        user_id: int,
        settings_repo: SettingsRepository,
        push_repo: PushSubscriptionRepository,
        log_repo: NotificationLogRepository,
        push_sender: PushSenderPort,
        messenger: MessengerPort,
        clock: Callable[[], datetime],
    ) -> None:
        self._user_id = user_id
        self._settings = settings_repo
        self._push = push_repo
        self._log = log_repo
        self._push_sender = push_sender
        self._messenger = messenger
        self._clock = clock

    def plan_ready(self, plan: AllocationPlan, fingerprint: str) -> list[str]:
        if not fingerprint or self._log.last_fingerprint(self._user_id, PLAN_KIND) == fingerprint:
            return []
        actionable = plan.actionable
        lines = [f"{s.action.value} {s.quantity} {s.symbol} @ ₹{s.price:,.2f}" for s in actionable[:MAX_LINES]]
        if len(actionable) > MAX_LINES:
            lines.append(f"…and {len(actionable) - MAX_LINES} more")
        note = Notification(
            title=f"EZTrading: {len(actionable)} {plan.style} action(s) suggested",
            body="\n".join(lines) + "\nReview and confirm in the app.",
            url="/",
        )
        channels = self.deliver(note)
        self._log.record(self._user_id, PLAN_KIND, fingerprint, at=self._clock())
        return channels

    def kite_reconnect(self) -> list[str]:
        if self._log.sent_since(self._user_id, KITE_KIND, self._clock() - timedelta(hours=20)):
            return []
        channels = self.deliver(Notification(
            title="EZTrading: reconnect Kite",
            body="Your Kite session has expired, so auto-analysis is paused. Open the app and click Connect Kite.",
            url="/",
        ))
        now = self._clock()
        self._log.record(self._user_id, KITE_KIND, now.date().isoformat(), at=now)
        return channels

    def test(self) -> list[str]:
        return self.deliver(Notification(title="EZTrading test", body="Notifications are working.", url="/"))

    def deliver(self, note: Notification) -> list[str]:
        settings = self._settings.get(self._user_id)
        channels: list[str] = []
        if settings.push_enabled:
            subs = self._push.for_user(self._user_id)
            for sub in subs:
                if not self._push_sender.send(sub, note):
                    self._push.remove_endpoint(sub["endpoint"])
            if subs:
                channels.append("push")
        if settings.telegram_enabled and settings.telegram_chat_id:
            self._messenger.send(settings.telegram_chat_id, note)
            channels.append("telegram")
        return channels
