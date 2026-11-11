"""Scheduled auto-analysis. Runs in the worker process; only analyses and notifies, never trades."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from typing import Callable, Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.domain.errors import BrokerAuthError, EZTradingError
from app.repositories.users import ScheduleRepository
from app.services.market_hours import MarketCalendar
from app.services.styles import get_style

log = logging.getLogger(__name__)


class AutoAnalysisTarget(Protocol):
    """What the runner needs for one user: analysis + notifications. No order service."""

    def analyze(self, style_key: str | None = None, manual: bool = True): ...

    def kite_reconnect(self) -> list[str]: ...


class AutoAnalysisRunner:
    def __init__(
        self,
        session_factory: sessionmaker,
        target_for_user: Callable[[Session, int], AutoAnalysisTarget],
        calendar: MarketCalendar,
        clock: Callable[[], datetime],
        max_workers: int = 4,
    ) -> None:
        self._sessions = session_factory
        self._target_for_user = target_for_user
        self._calendar = calendar
        self._clock = clock
        self._max_workers = max_workers

    def tick(self) -> list[int]:
        """Run every due schedule once. Returns the user ids that were run."""
        now = self._clock()
        if not self._calendar.is_open(now):
            return []
        claimed: dict[int, list[str]] = {}
        with self._sessions() as db:
            repo = ScheduleRepository(db)
            for row in repo.due(now):
                style = get_style(row.style)
                if style.intraday and not self._calendar.intraday_allowed(now):
                    continue
                interval = max(row.interval_min, style.min_auto_interval_min)
                if repo.claim(row.id, row.next_run_at, now + timedelta(minutes=interval)):
                    styles = claimed.setdefault(row.user_id, [])
                    if row.style not in styles:
                        styles.append(row.style)
        if claimed:
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                wait([pool.submit(self._run_user, uid, styles) for uid, styles in claimed.items()])
        return list(claimed)

    def _run_user(self, user_id: int, styles: list[str]) -> None:
        """One user's due styles run sequentially (the per-user analysis lock allows one at a time)."""
        with self._sessions() as db:
            target = self._target_for_user(db, user_id)
            for style in styles:
                try:
                    plan = target.analyze(style, manual=False)
                    log.info("Auto-analysis (%s) for user %s: %d actionable", style, user_id, len(plan.actionable))
                except BrokerAuthError:
                    target.kite_reconnect()
                    return  # every other style would fail the same way
                except EZTradingError as exc:
                    log.warning("Auto-analysis (%s) for user %s failed: %s", style, user_id, exc)
                except Exception:
                    log.exception("Auto-analysis (%s) for user %s crashed", style, user_id)
