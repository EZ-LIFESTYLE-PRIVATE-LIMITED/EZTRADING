"""Orchestrates one analysis run: context -> advisor -> validation -> persistence -> notification."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable

from app.domain.errors import NotFoundError, ValidationError
from app.domain.models import AllocationPlan
from app.domain.ports import BrokerPort
from app.repositories.trading import PlanRepository
from app.repositories.users import SettingsRepository
from app.services.account_service import WalletService
from app.services.advisor_resolver import AdvisorResolver
from app.services.limits import AnalyzeLimiter
from app.services.market_context import MarketContextBuilder
from app.services.market_hours import MarketCalendar
from app.services.notification_service import NotificationService, plan_fingerprint
from app.services.plan_validator import PlanValidator
from app.services.styles import get_style

log = logging.getLogger(__name__)


class AnalysisService:
    def __init__(
        self,
        user_id: int,
        broker: BrokerPort,
        wallet: WalletService,
        context_builder: MarketContextBuilder,
        resolver: AdvisorResolver,
        settings_repo: SettingsRepository,
        plans: PlanRepository,
        notifications: NotificationService,
        calendar: MarketCalendar,
        limiter: AnalyzeLimiter,
        watchlist: list[str],
        clock: Callable[[], datetime],
    ) -> None:
        self._user_id = user_id
        self._broker = broker
        self._wallet = wallet
        self._context = context_builder
        self._resolver = resolver
        self._settings = settings_repo
        self._plans = plans
        self._notifications = notifications
        self._calendar = calendar
        self._limiter = limiter
        self._watchlist = watchlist
        self._clock = clock
        self._validator = PlanValidator()

    def analyze(self, style_key: str | None = None, manual: bool = True) -> AllocationPlan:
        user_settings = self._settings.get(self._user_id)
        style = get_style(style_key or user_settings.default_style)
        with self._limiter.acquire(self._user_id, enforce_cooldown=manual):
            holdings = self._broker.holdings()
            budget = self._wallet.deployable()
            if budget <= 0 and not holdings:
                raise ValidationError("Set an amount in the wallet or hold some stocks before analysing")

            now = self._clock()
            market_open = self._calendar.intraday_allowed(now) if style.intraday else self._calendar.is_open(now)
            request = self._context.build(style, budget, holdings, self._watchlist, market_open)
            advisor = self._resolver.portfolio_advisor(user_settings.advisor_id, style)
            log.info("Analysis started: user=%s style=%s advisor=%s symbols=%d", self._user_id, style.key,
                     advisor.name, len(request.symbols))
            started = time.monotonic()
            raw = advisor.advise(request)
            plan = self._validator.validate(raw, request.symbols, budget, advisor.name, style)
            log.info("Analysis finished in %.1fs: user=%s suggestions=%d", time.monotonic() - started,
                     self._user_id, len(plan.suggestions))

        fingerprint = plan_fingerprint(plan)
        self._plans.save(plan, fingerprint, created_at=self._clock())
        try:
            self._notifications.plan_ready(plan, fingerprint)
        except Exception:  # a notification failure must not lose the plan
            log.exception("Notification failed for user %s", self._user_id)
        return plan

    def latest(self) -> AllocationPlan | None:
        return self._plans.latest()

    def dismiss(self, plan_id: str) -> None:
        if not self._plans.dismiss(plan_id):
            raise NotFoundError("Plan not found")
