"""Test doubles shared across tests."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

from app.domain.models import Candle, Interval, Notification


def make_candles(n: int = 260, start: float = 100.0, drift: float = 0.3) -> list[Candle]:
    """Deterministic gently-trending daily series with a small oscillation."""
    day0 = datetime(2025, 1, 1)
    return [
        Candle(ts=day0 + timedelta(days=i), open=c - 0.5, high=c + 1, low=c - 1, close=c, volume=1000 + 10 * i)
        for i, c in ((i, start + drift * i + 2 * math.sin(i / 3)) for i in range(n))
    ]


def make_intraday(days: int = 2, start: float = 100.0, step: float = 0.05) -> list[Candle]:
    """5-minute bars 09:15-15:25 for `days` sessions, steadily rising."""
    bars, price = [], start
    for d in range(days):
        t = datetime(2026, 11, 10 + d, 9, 15)
        while t.hour < 15 or (t.hour == 15 and t.minute < 30):
            bars.append(Candle(ts=t, open=price, high=price + 0.2, low=price - 0.2, close=price + step, volume=1000))
            price += step
            t += timedelta(minutes=5)
    return bars


class StaticPrices:
    def __init__(self, daily: list[Candle] | None = None, intraday: list[Candle] | None = None) -> None:
        self._daily = daily or make_candles()
        self._intraday = intraday or make_intraday()

    def candles(self, symbol: str, interval: Interval, days: int) -> list[Candle]:
        return self._intraday if interval is Interval.MIN5 else self._daily


class FakeLLMClient:
    """Returns scripted JSON; records prompts it was given."""

    name = "fake:llm"

    def __init__(self, portfolio: dict | None = None, ipo: dict | None = None) -> None:
        self.portfolio = portfolio or {"market_view": "flat", "suggestions": []}
        self.ipo = ipo or {"overview": "quiet", "assessments": []}
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, schema: dict) -> str:
        self.calls.append((system, user))
        return json.dumps(self.ipo if "IPO" in system else self.portfolio)


def suggestion(symbol: str, action: str, qty: int, confidence: float = 0.7, **levels) -> dict:
    base = {"symbol": symbol, "action": action, "quantity": qty, "confidence": confidence, "rationale": "r",
            "entry_price": None, "stop_loss": None, "target": None, "horizon": None}
    base.update(levels)
    return base


class RecordingPush:
    def __init__(self, gone: set[str] | None = None) -> None:
        self.sent: list[tuple[str, Notification]] = []
        self.gone = gone or set()

    def send(self, subscription: dict, notification: Notification) -> bool:
        self.sent.append((subscription["endpoint"], notification))
        return subscription["endpoint"] not in self.gone


class RecordingMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Notification]] = []

    def send(self, chat_id: str, notification: Notification) -> None:
        self.sent.append((chat_id, notification))


class Clock:
    """Controllable naive-UTC clock. Default: Wed 2026-11-11 10:00 IST (market open)."""

    def __init__(self, now: datetime = datetime(2026, 11, 11, 4, 30)) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)
