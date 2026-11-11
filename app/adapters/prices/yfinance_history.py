"""Candles from Yahoo Finance (free fallback; NSE symbols get a .NS suffix)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import yfinance as yf

from app.domain.errors import BrokerError
from app.domain.models import Candle, Interval

IST = ZoneInfo("Asia/Kolkata")

_ALIASES = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK", "SENSEX": "^BSESN"}
_INTERVALS = {Interval.DAY: "1d", Interval.MIN5: "5m"}
_MAX_DAYS = {Interval.DAY: 3650, Interval.MIN5: 59}  # Yahoo serves 5m bars for ~60 days only


def to_yahoo_ticker(symbol: str) -> str:
    return _ALIASES.get(symbol.upper(), f"{symbol.upper()}.NS")


class YFinanceHistory:
    def candles(self, symbol: str, interval: Interval, days: int) -> list[Candle]:
        ticker = to_yahoo_ticker(symbol)
        period = f"{min(days, _MAX_DAYS[interval])}d"
        try:
            df = yf.Ticker(ticker).history(period=period, interval=_INTERVALS[interval], auto_adjust=False)
        except Exception as exc:  # yfinance raises a variety of errors
            raise BrokerError(f"yfinance failed for {ticker}: {exc}") from exc
        if df is None or df.empty:
            raise BrokerError(f"No yfinance data for {ticker}")
        return [
            Candle(
                ts=_to_ist_naive(idx), open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]), volume=float(row.get("Volume", 0) or 0),
            )
            for idx, row in df.iterrows()
        ]


def _to_ist_naive(ts):
    py = ts.to_pydatetime()
    if py.tzinfo is not None:
        py = py.astimezone(IST)
    return py.replace(tzinfo=None)
