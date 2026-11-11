"""Offline broker with sample data, for demos and tests (BROKER=fake)."""

from __future__ import annotations

import itertools

from app.domain.errors import BrokerError
from app.domain.models import Holding, OrderRequest

_SAMPLE = [
    Holding(symbol="INFY", quantity=20, average_price=1450.0, last_price=1520.5, day_change_pct=0.8),
    Holding(symbol="HDFCBANK", quantity=15, average_price=1580.0, last_price=1655.2, day_change_pct=-0.4),
    Holding(symbol="ITC", quantity=100, average_price=410.0, last_price=436.1, day_change_pct=0.2),
    Holding(symbol="TATASTEEL", quantity=120, average_price=172.0, last_price=158.3, day_change_pct=-1.6),
]
_ids = itertools.count(1)


class FakeBroker:
    def __init__(self, holdings: list[Holding] | None = None, cash: float = 50_000.0) -> None:
        self._holdings = list(holdings if holdings is not None else _SAMPLE)
        self._cash = cash
        self._prices: dict[str, float] = {h.symbol: h.last_price for h in self._holdings}
        self.orders: list[OrderRequest] = []
        self.fail_next_order: str | None = None

    def set_prices(self, prices: dict[str, float]) -> None:
        self._prices.update(prices)

    def is_configured(self) -> bool:
        return True

    def is_authenticated(self) -> bool:
        return True

    def login_url(self) -> str:
        return "/"

    def complete_login(self, request_token: str) -> None:
        return None

    def holdings(self) -> list[Holding]:
        return list(self._holdings)

    def available_cash(self) -> float | None:
        return self._cash

    def last_prices(self, symbols: list[str]) -> dict[str, float]:
        return {s: self._prices[s] for s in symbols if s in self._prices}

    def place_order(self, order: OrderRequest) -> str:
        if self.fail_next_order:
            message, self.fail_next_order = self.fail_next_order, None
            raise BrokerError(message)
        self.orders.append(order)
        return f"FAKE-{next(_ids)}"

    def order_status(self, broker_order_id: str) -> str:
        return "COMPLETE"
