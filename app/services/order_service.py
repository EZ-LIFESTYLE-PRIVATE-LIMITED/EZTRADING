"""Executes or ignores individual suggestions. Every order is re-validated server-side.

Only reachable from an explicit user request; the auto-analysis worker never
receives an OrderService, so it structurally cannot trade.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from pydantic import BaseModel, Field

from app.domain.errors import BrokerAuthError, EZTradingError, ForbiddenError, NotFoundError, ValidationError
from app.domain.models import (
    Action,
    AllocationPlan,
    OrderRecord,
    OrderRequest,
    OrderType,
    Product,
    Suggestion,
    SuggestionStatus,
)
from app.domain.ports import BrokerPort
from app.repositories.trading import OrderRepository, PlanRepository, SuggestionActionRepository, to_record
from app.services.account_service import WalletService
from app.services.market_hours import MarketCalendar
from app.services.styles import get_style

log = logging.getLogger(__name__)
LIMIT_PRICE_BAND = 0.20  # reject limit prices more than 20% away from LTP (fat-finger guard)


class ExecuteRequest(BaseModel):
    quantity: int = Field(gt=0)
    order_type: OrderType = OrderType.LIMIT
    price: float | None = Field(default=None, gt=0)


class OrderService:
    def __init__(
        self,
        broker: BrokerPort,
        plans: PlanRepository,
        actions: SuggestionActionRepository,
        orders: OrderRepository,
        wallet: WalletService,
        calendar: MarketCalendar,
        clock: Callable[[], datetime],
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._broker = broker
        self._plans = plans
        self._actions = actions
        self._orders = orders
        self._wallet = wallet
        self._calendar = calendar
        self._clock = clock

    def execute(self, plan_id: str, suggestion_id: str, req: ExecuteRequest) -> OrderRecord:
        if not self._enabled:
            raise ForbiddenError("Trade execution is disabled on this server. Place the order in Kite yourself.")
        plan, suggestion = self._load(plan_id, suggestion_id)
        if not suggestion.actionable:
            raise ValidationError("HOLD suggestions cannot be executed")
        style = get_style(plan.style)
        now = self._clock()

        created = self._plans.created_at(plan_id)
        if created is None or now - created > style.max_plan_age:
            raise ValidationError("This plan is too old to execute. Run Analyze again for fresh prices.")
        if not (self._calendar.intraday_allowed(now) if style.intraday else self._calendar.is_open(now)):
            raise ValidationError("The market is closed for this order type right now")
        if req.quantity > suggestion.quantity:
            raise ValidationError(f"Quantity cannot exceed the suggested {suggestion.quantity}")

        ltp = self._broker.last_prices([suggestion.symbol]).get(suggestion.symbol, suggestion.price)
        price = self._order_price(req, ltp)
        est_amount = round(req.quantity * (price or ltp), 2)
        consumes_budget = suggestion.action is Action.BUY or suggestion.product is Product.MIS
        if consumes_budget:
            self._check_budget(plan, suggestion, est_amount)
        else:
            self._check_holding(suggestion, req.quantity)

        self._actions.claim(plan_id, suggestion_id, SuggestionStatus.EXECUTING)
        row = self._orders.add(
            plan_id=plan_id, suggestion_id=suggestion_id, symbol=suggestion.symbol, side=suggestion.action.value,
            quantity=req.quantity, product=suggestion.product.value, order_type=req.order_type.value,
            price=price, est_amount=est_amount, status="PLACING",
        )
        try:
            broker_id = self._broker.place_order(OrderRequest(
                symbol=suggestion.symbol, side=suggestion.action, quantity=req.quantity,
                product=suggestion.product, order_type=req.order_type, price=price,
            ))
        except EZTradingError as exc:
            self._orders.update(row, status="FAILED", error=str(exc))
            self._actions.set(plan_id, suggestion_id, SuggestionStatus.FAILED)
            log.warning("Order failed for %s: %s", suggestion.symbol, exc)
            raise

        self._orders.update(row, broker_order_id=broker_id, status="PLACED")
        self._actions.set(plan_id, suggestion_id, SuggestionStatus.EXECUTED)
        if suggestion.action is Action.BUY and suggestion.product is Product.CNC:
            self._wallet.spend(est_amount)  # delivery buys use up deployable cash
        return self._refresh_row(row)

    def ignore(self, plan_id: str, suggestion_id: str) -> None:
        self._load(plan_id, suggestion_id)
        self._actions.claim(plan_id, suggestion_id, SuggestionStatus.IGNORED)

    def refresh(self, order_id: int) -> OrderRecord:
        row = self._orders.get_row(order_id)
        if row is None:
            raise NotFoundError("Order not found")
        return self._refresh_row(row)

    def list(self) -> list[OrderRecord]:
        return self._orders.list()

    # --- helpers -------------------------------------------------------------
    def _load(self, plan_id: str, suggestion_id: str) -> tuple[AllocationPlan, Suggestion]:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise NotFoundError("Plan not found")
        suggestion = plan.suggestion(suggestion_id)
        if suggestion is None:
            raise NotFoundError("Suggestion not found")
        return plan, suggestion

    @staticmethod
    def _order_price(req: ExecuteRequest, ltp: float) -> float | None:
        if req.order_type is OrderType.MARKET:
            return None
        if req.price is None:
            raise ValidationError("A limit price is required for LIMIT orders")
        if abs(req.price - ltp) / ltp > LIMIT_PRICE_BAND:
            raise ValidationError(f"Limit price {req.price} is too far from the current price {ltp}")
        return round(req.price, 2)

    def _check_budget(self, plan: AllocationPlan, suggestion: Suggestion, amount: float) -> None:
        if suggestion.product is Product.CNC:
            remaining = self._wallet.deployable()
        else:
            remaining = plan.budget - self._orders.spent_on_plan(plan.id, intraday=True)
        if amount > remaining + 0.01:
            raise ValidationError(f"Order value ₹{amount:,.2f} exceeds your remaining budget ₹{remaining:,.2f}")

    def _check_holding(self, suggestion: Suggestion, quantity: int) -> None:
        held = next((h.quantity for h in self._broker.holdings() if h.symbol == suggestion.symbol), 0)
        if quantity > held:
            raise ValidationError(f"You hold only {held} {suggestion.symbol}")

    def _refresh_row(self, row) -> OrderRecord:
        if row.broker_order_id:
            try:
                status = self._broker.order_status(row.broker_order_id)
                self._orders.update(row, status=status)
            except BrokerAuthError:
                raise
            except EZTradingError as exc:
                log.info("Could not refresh order %s: %s", row.broker_order_id, exc)
        return to_record(row)
