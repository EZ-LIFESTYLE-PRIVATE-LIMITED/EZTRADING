"""NSE trading calendar (IST). Pure logic; time is always passed in."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
CLOSE = time(15, 30)
INTRADAY_CUTOFF = time(15, 15)  # brokers start auto-squaring MIS positions around 15:15-15:20


def to_ist(now_utc: datetime) -> datetime:
    aware = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    return aware.astimezone(IST)


class MarketCalendar:
    def __init__(self, holidays: set[date] | None = None) -> None:
        self._holidays = holidays or set()

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self._holidays

    def is_open(self, now_utc: datetime) -> bool:
        local = to_ist(now_utc)
        return self.is_trading_day(local.date()) and OPEN <= local.time() < CLOSE

    def intraday_allowed(self, now_utc: datetime) -> bool:
        local = to_ist(now_utc)
        return self.is_open(now_utc) and local.time() < INTRADAY_CUTOFF

    def today(self, now_utc: datetime) -> date:
        return to_ist(now_utc).date()

    def next_open(self, now_utc: datetime) -> datetime:
        """Next session open as naive UTC (for scheduling)."""
        local = to_ist(now_utc)
        day = local.date()
        if local.time() >= OPEN:
            day += timedelta(days=1)
        while not self.is_trading_day(day):
            day += timedelta(days=1)
        opening = datetime.combine(day, OPEN, tzinfo=IST)
        return opening.astimezone(timezone.utc).replace(tzinfo=None)
