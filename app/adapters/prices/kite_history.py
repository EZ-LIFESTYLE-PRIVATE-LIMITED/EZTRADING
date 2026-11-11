"""Candles from the Kite historical API (needs the Kite historical-data add-on)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.adapters.broker.kite_broker import instrument_key
from app.adapters.broker.kite_session import KiteSession
from app.domain.models import Candle, Interval


class KiteHistory:
    def __init__(self, session: KiteSession) -> None:
        self._session = session
        self._tokens: dict[str, int] = {}

    def candles(self, symbol: str, interval: Interval, days: int) -> list[Candle]:
        token = self._token_for(symbol)
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=days)
        rows = self._session.call(lambda k: k.historical_data(token, from_dt, to_dt, interval.value))
        return [
            Candle(ts=_naive(r["date"]), open=r["open"], high=r["high"], low=r["low"],
                   close=r["close"], volume=r.get("volume", 0) or 0)
            for r in rows
        ]

    def _token_for(self, symbol: str) -> int:
        if symbol not in self._tokens:
            key = instrument_key(symbol)
            self._tokens[symbol] = int(self._session.ltp([key])[key]["instrument_token"])
        return self._tokens[symbol]


def _naive(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)
