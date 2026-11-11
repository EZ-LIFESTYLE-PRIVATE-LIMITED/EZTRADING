"""Zerodha Kite broker adapter."""

from __future__ import annotations

from app.adapters.broker.kite_session import KiteSession
from app.domain.models import Holding, OrderRequest, OrderType

EXCHANGE = "NSE"
ORDER_TAG = "eztrading"


def instrument_key(symbol: str, exchange: str = EXCHANGE) -> str:
    return f"{exchange}:{symbol}"


class KiteBroker:
    def __init__(self, session: KiteSession) -> None:
        self._session = session

    def is_configured(self) -> bool:
        return True

    def is_authenticated(self) -> bool:
        return self._session.is_authenticated()

    def login_url(self) -> str:
        return self._session.login_url()

    def complete_login(self, request_token: str) -> None:
        self._session.complete_login(request_token)

    def holdings(self) -> list[Holding]:
        raw = self._session.call(lambda k: k.holdings())
        result = []
        for row in raw:
            qty = int(row.get("quantity", 0)) + int(row.get("t1_quantity", 0))
            if qty <= 0:
                continue
            result.append(Holding(
                symbol=row["tradingsymbol"],
                exchange=row.get("exchange", EXCHANGE),
                quantity=qty,
                average_price=float(row.get("average_price", 0.0)),
                last_price=float(row.get("last_price", 0.0)),
                day_change_pct=float(row.get("day_change_percentage", 0.0) or 0.0),
            ))
        return result

    def available_cash(self) -> float | None:
        margins = self._session.call(lambda k: k.margins("equity"))
        available = margins.get("available", {})
        cash = available.get("live_balance", available.get("cash"))
        return float(cash) if cash is not None else None

    def last_prices(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        payload = self._session.ltp([instrument_key(s) for s in symbols])
        return {key.split(":", 1)[1]: float(v["last_price"]) for key, v in payload.items()}

    def place_order(self, order: OrderRequest) -> str:
        params = dict(
            variety="regular",
            exchange=order.exchange,
            tradingsymbol=order.symbol,
            transaction_type=order.side.value,
            quantity=order.quantity,
            product=order.product.value,
            order_type=order.order_type.value,
            tag=ORDER_TAG,
        )
        if order.order_type is OrderType.LIMIT:
            params["price"] = order.price
        return str(self._session.call(lambda k: k.place_order(**params)))

    def order_status(self, broker_order_id: str) -> str:
        history = self._session.call(lambda k: k.order_history(broker_order_id))
        return str(history[-1]["status"]) if history else "UNKNOWN"
