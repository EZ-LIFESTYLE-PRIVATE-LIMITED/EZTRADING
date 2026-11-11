"""Who has premium, and what premium unlocks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from pydantic import BaseModel

from app.config import Settings
from app.repositories.billing import SubscriptionRepository


class PremiumStatus(BaseModel):
    active: bool
    until: datetime | None
    enforced: bool  # False in development: everyone may use the server's AI keys
    price_inr: int
    period_days: int


class EntitlementService:
    def __init__(self, repo: SubscriptionRepository, settings: Settings, clock: Callable[[], datetime]) -> None:
        self._repo = repo
        self._settings = settings
        self._clock = clock

    def is_premium(self, user_id: int) -> bool:
        return self._repo.active(user_id, self._clock())

    def allows_server_keys(self, user_id: int) -> bool:
        return not self._settings.premium_required or self.is_premium(user_id)

    def status(self, user_id: int) -> PremiumStatus:
        active = self.is_premium(user_id)
        return PremiumStatus(
            active=active,
            until=self._repo.latest_end(user_id) if active else None,
            enforced=self._settings.premium_required,
            price_inr=self._settings.premium_price_inr,
            period_days=self._settings.premium_period_days,
        )

    def grant(self, user_id: int, days: int, source: str, reference: str | None = None) -> datetime:
        """Adds `days` of premium, stacking after any premium the user already has. Returns the new end."""
        now = self._clock()
        current_end = self._repo.latest_end(user_id)
        start = current_end if current_end and current_end > now else now
        end = start + timedelta(days=days)
        self._repo.add(user_id=user_id, plan=self._settings.premium_plan, source=source, reference=reference,
                       starts_at=start, ends_at=end)
        return end
