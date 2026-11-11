"""Price-history decorators: fallback chain and shared TTL cache.

Both implement PriceHistoryPort and wrap other PriceHistoryPorts, so they can be
stacked freely in the composition root (Decorator / Chain of Responsibility).
"""

from __future__ import annotations

import logging
import threading
import time

from app.domain.errors import EZTradingError
from app.domain.models import Candle, Interval
from app.domain.ports import PriceHistoryPort

log = logging.getLogger(__name__)


class FallbackPriceHistory:
    """Try each source in order; first one that returns data wins."""

    def __init__(self, sources: list[PriceHistoryPort]) -> None:
        if not sources:
            raise ValueError("At least one price source is required")
        self._sources = sources

    def candles(self, symbol: str, interval: Interval, days: int) -> list[Candle]:
        errors: list[str] = []
        for source in self._sources:
            try:
                candles = source.candles(symbol, interval, days)
                if candles:
                    return candles
                errors.append(f"{type(source).__name__}: empty")
            except (EZTradingError, KeyError, ValueError) as exc:
                log.debug("%s failed for %s: %s", type(source).__name__, symbol, exc)
                errors.append(f"{type(source).__name__}: {exc}")
        raise EZTradingError(f"No price history for {symbol}: {'; '.join(errors)}")


class PriceCache:
    """Process-wide cache shared by every user's price chain (market data is the same for all)."""

    def __init__(self, ttl_by_interval: dict[Interval, int]) -> None:
        self._ttl = ttl_by_interval
        self._data: dict[tuple[str, Interval, int], tuple[float, list[Candle]]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, Interval, int]) -> list[Candle] | None:
        with self._lock:
            hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < self._ttl.get(key[1], 0):
            return hit[1]
        return None

    def put(self, key: tuple[str, Interval, int], candles: list[Candle]) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), candles)


class CachedPriceHistory:
    def __init__(self, inner: PriceHistoryPort, cache: PriceCache) -> None:
        self._inner = inner
        self._cache = cache

    def candles(self, symbol: str, interval: Interval, days: int) -> list[Candle]:
        key = (symbol, interval, days)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        candles = self._inner.candles(symbol, interval, days)
        self._cache.put(key, candles)
        return candles
