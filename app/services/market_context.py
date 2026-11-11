"""Builds the market/symbol context fed to the advisor (Builder).

Fetches price history + news concurrently and computes indicators locally.
Which data is gathered depends on the trading style. Failures for a single
symbol degrade gracefully (indicators/news left empty).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.domain.errors import EZTradingError
from app.domain.models import (
    AdvisorRequest,
    Holding,
    IndicatorSet,
    Interval,
    IntradayIndicators,
    MarketContext,
    SymbolContext,
)
from app.domain.ports import NewsPort, PriceHistoryPort
from app.services.indicators import compute_indicators, compute_intraday
from app.services.styles import TradingStyle

log = logging.getLogger(__name__)
INTRADAY_LOOKBACK_DAYS = 5


class MarketContextBuilder:
    def __init__(
        self,
        prices: PriceHistoryPort,
        news: NewsPort,
        index_name: str,
        news_per_symbol: int = 4,
        market_news_limit: int = 15,
        max_workers: int = 8,
    ) -> None:
        self._prices = prices
        self._news = news
        self._index_name = index_name
        self._news_per_symbol = news_per_symbol
        self._market_news_limit = market_news_limit
        self._max_workers = max_workers

    def build(
        self, style: TradingStyle, budget: float, holdings: list[Holding], watchlist: list[str], market_open: bool
    ) -> AdvisorRequest:
        held = {h.symbol: h for h in holdings}
        universe = list(dict.fromkeys([*held, *watchlist]))  # ordered, unique

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            market_future = pool.submit(self._market, style)
            symbols = list(pool.map(lambda s: self._symbol(style, s, held.get(s)), universe))
            market = market_future.result()

        return AdvisorRequest(
            style=style.key, budget=budget, as_of=datetime.now(), market_open=market_open,
            market=market, symbols=symbols,
        )

    def _market(self, style: TradingStyle) -> MarketContext:
        return MarketContext(
            index_name=self._index_name,
            index_indicators=self._daily(self._index_name, style.daily_history_days),
            index_intraday=self._intraday(self._index_name) if style.intraday else None,
            headlines=self._safe_news(lambda: self._news.market_news(self._market_news_limit)),
        )

    def _symbol(self, style: TradingStyle, symbol: str, holding: Holding | None) -> SymbolContext:
        daily = self._daily(symbol, style.daily_history_days)
        intraday = self._intraday(symbol) if style.intraday else None
        last_price = intraday.last_price if intraday else (daily.last_close if daily else None)
        if holding is not None and holding.last_price > 0:
            last_price = holding.last_price  # broker LTP is the freshest
        return SymbolContext(
            symbol=symbol,
            last_price=last_price,
            held_quantity=holding.quantity if holding else 0,
            average_price=holding.average_price if holding else None,
            indicators=daily,
            intraday=intraday,
            news=self._safe_news(lambda: self._news.symbol_news(symbol, self._news_per_symbol)),
        )

    def _daily(self, symbol: str, days: int) -> IndicatorSet | None:
        try:
            return compute_indicators(self._prices.candles(symbol, Interval.DAY, days))
        except EZTradingError as exc:
            log.warning("No daily indicators for %s: %s", symbol, exc)
            return None

    def _intraday(self, symbol: str) -> IntradayIndicators | None:
        try:
            return compute_intraday(self._prices.candles(symbol, Interval.MIN5, INTRADAY_LOOKBACK_DAYS))
        except EZTradingError as exc:
            log.warning("No intraday indicators for %s: %s", symbol, exc)
            return None

    @staticmethod
    def _safe_news(fetch):
        try:
            return fetch()
        except Exception as exc:  # news is best-effort context
            log.warning("News fetch failed: %s", exc)
            return []
