"""Null Object used when a user has not saved Kite API keys yet."""

from __future__ import annotations

from app.domain.errors import BrokerAuthError
from app.domain.models import Holding, OrderRequest

_MSG = "Add your Kite API key and secret in Settings first"


class UnconfiguredBroker:
    def is_configured(self) -> bool:
        return False

    def is_authenticated(self) -> bool:
        return False

    def login_url(self) -> str:
        raise BrokerAuthError(_MSG)

    def complete_login(self, request_token: str) -> None:
        raise BrokerAuthError(_MSG)

    def holdings(self) -> list[Holding]:
        raise BrokerAuthError(_MSG)

    def available_cash(self) -> float | None:
        return None

    def last_prices(self, symbols: list[str]) -> dict[str, float]:
        raise BrokerAuthError(_MSG)

    def place_order(self, order: OrderRequest) -> str:
        raise BrokerAuthError(_MSG)

    def order_status(self, broker_order_id: str) -> str:
        raise BrokerAuthError(_MSG)
