"""Ports (interfaces) the services depend on.

Concrete adapters live in ``app.adapters`` and are wired in ``app.container``.
Services only ever see these Protocols (Dependency Inversion).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.domain.models import (
    AdvisorPlan,
    AdvisorRequest,
    Candle,
    CheckoutOrder,
    CheckoutSession,
    EmailMessage,
    Holding,
    Interval,
    Ipo,
    NewsItem,
    Notification,
    OrderRequest,
    PaymentEvent,
)


@runtime_checkable
class BrokerPort(Protocol):
    def is_configured(self) -> bool: ...

    def is_authenticated(self) -> bool: ...

    def login_url(self) -> str: ...

    def complete_login(self, request_token: str) -> None: ...

    def holdings(self) -> list[Holding]: ...

    def available_cash(self) -> float | None: ...

    def last_prices(self, symbols: list[str]) -> dict[str, float]: ...

    def place_order(self, order: OrderRequest) -> str: ...

    def order_status(self, broker_order_id: str) -> str: ...


class TokenStore(Protocol):
    """Persists one user's broker access token."""

    def load(self) -> str | None: ...

    def save(self, token: str) -> None: ...

    def clear(self) -> None: ...


@runtime_checkable
class PriceHistoryPort(Protocol):
    def candles(self, symbol: str, interval: Interval, days: int) -> list[Candle]: ...


@runtime_checkable
class NewsPort(Protocol):
    def search(self, query: str, limit: int) -> list[NewsItem]: ...

    def symbol_news(self, symbol: str, limit: int) -> list[NewsItem]: ...

    def market_news(self, limit: int) -> list[NewsItem]: ...


@runtime_checkable
class LLMClientPort(Protocol):
    """A vendor model that returns JSON text matching a JSON schema."""

    name: str

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str: ...


@runtime_checkable
class PortfolioAdvisorPort(Protocol):
    name: str

    def advise(self, request: AdvisorRequest) -> AdvisorPlan: ...


@runtime_checkable
class IpoSourcePort(Protocol):
    def list_ipos(self) -> list[Ipo]: ...


@runtime_checkable
class PushSenderPort(Protocol):
    def send(self, subscription: dict[str, Any], notification: Notification) -> bool:
        """Return False if the subscription is gone and should be deleted."""
        ...


@runtime_checkable
class MessengerPort(Protocol):
    def send(self, chat_id: str, notification: Notification) -> None: ...


@runtime_checkable
class PaymentGatewayPort(Protocol):
    """A payment service provider (PSP). Swap implementations via PAYMENT_PROVIDER."""

    name: str

    def create_checkout(self, order: CheckoutOrder) -> CheckoutSession: ...

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent:
        """Verify the provider's signature and translate its payload. Raise ValidationError if invalid."""
        ...


@runtime_checkable
class EmailSenderPort(Protocol):
    def send(self, message: EmailMessage) -> None: ...
