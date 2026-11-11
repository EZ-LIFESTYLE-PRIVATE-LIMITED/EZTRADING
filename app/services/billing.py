"""Premium checkout: coupons, pricing, handing off to the payment provider, and fulfilment."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Callable

from pydantic import BaseModel

from app.config import Settings
from app.db.models import Coupon
from app.domain.errors import NotFoundError, ValidationError
from app.domain.models import CheckoutOrder, PaymentEvent
from app.domain.ports import PaymentGatewayPort
from app.repositories.billing import BillingOrderRepository, CouponRepository
from app.services.entitlements import EntitlementService

log = logging.getLogger(__name__)

COUPON_KINDS = {"percent", "flat", "free_days"}


class Quote(BaseModel):
    price_inr: int
    discount_inr: int
    total_inr: int
    free_days: int = 0  # >0 for a free-trial coupon: no payment, premium for this many days
    coupon: str | None = None
    summary: str


class CheckoutResult(BaseModel):
    status: str  # "activated" (no payment needed) | "redirect" (go to the payment page)
    redirect_url: str | None = None
    premium_until: datetime | None = None


class BillingOrderView(BaseModel):
    id: str
    amount_inr: float
    discount_inr: float
    coupon: str | None
    status: str
    provider: str


class BillingService:
    """App-wide (not per-user) so payment webhooks, which carry no session, can fulfil orders."""

    def __init__(self, settings: Settings, coupons: CouponRepository, orders: BillingOrderRepository,
                 entitlements: EntitlementService, gateway: PaymentGatewayPort,
                 clock: Callable[[], datetime]) -> None:
        self._settings = settings
        self._coupons = coupons
        self._orders = orders
        self._entitlements = entitlements
        self._gateway = gateway
        self._clock = clock

    @property
    def gateway(self) -> PaymentGatewayPort:
        return self._gateway

    # --- pricing -----------------------------------------------------------
    def quote(self, user_id: int, coupon_code: str | None) -> Quote:
        price = self._settings.premium_price_inr
        days = self._settings.premium_period_days
        if not (coupon_code or "").strip():
            return Quote(price_inr=price, discount_inr=0, total_inr=price, summary=f"₹{price} for {days} days")
        coupon = self._valid_coupon(user_id, coupon_code)
        if coupon.kind == "free_days":
            return Quote(price_inr=price, discount_inr=price, total_inr=0, free_days=coupon.value, coupon=coupon.code,
                         summary=f"{coupon.value} days of Premium free")
        discount = round(price * coupon.value / 100) if coupon.kind == "percent" else coupon.value
        discount = max(0, min(price, discount))
        off = f"{coupon.value}% off" if coupon.kind == "percent" else f"₹{discount} off"
        return Quote(price_inr=price, discount_inr=discount, total_inr=price - discount, coupon=coupon.code,
                     summary=f"{off}: ₹{price - discount} for {days} days")

    def _valid_coupon(self, user_id: int, code: str) -> Coupon:
        coupon = self._coupons.get(code)
        if coupon is None or not coupon.active or coupon.kind not in COUPON_KINDS:
            raise ValidationError("This coupon code isn't valid")
        if coupon.valid_until is not None and coupon.valid_until < self._clock():
            raise ValidationError("This coupon has expired")
        if coupon.max_redemptions is not None and self._coupons.redemptions(coupon.code) >= coupon.max_redemptions:
            raise ValidationError("This coupon has been fully used")
        if self._coupons.redeemed_by(coupon.code, user_id):
            raise ValidationError("You've already used this coupon")
        return coupon

    # --- checkout ----------------------------------------------------------
    def checkout(self, user_id: int, email: str, coupon_code: str | None) -> CheckoutResult:
        quote = self.quote(user_id, coupon_code)
        if quote.free_days or quote.total_inr == 0:
            if quote.coupon and not self._coupons.redeem(quote.coupon, user_id):
                raise ValidationError("You've already used this coupon")
            days = quote.free_days or self._settings.premium_period_days
            until = self._entitlements.grant(user_id, days, source="coupon", reference=quote.coupon)
            log.info("Premium activated by coupon %s for user %s until %s", quote.coupon, user_id, until)
            return CheckoutResult(status="activated", premium_until=until)

        order = self._orders.add(
            id=uuid.uuid4().hex, user_id=user_id, plan=self._settings.premium_plan,
            amount_paise=quote.total_inr * 100, discount_paise=quote.discount_inr * 100, coupon_code=quote.coupon,
            status="created", provider=self._gateway.name,
        )
        session = self._gateway.create_checkout(CheckoutOrder(
            order_id=order.id, amount_paise=order.amount_paise, description="EZTrading Premium",
            customer_email=email,
            return_url=f"{self._settings.public_base_url.rstrip('/')}/billing.html?order={order.id}",
        ))
        if session.provider_ref:
            self._orders.mark(order, "created", session.provider_ref)
        return CheckoutResult(status="redirect", redirect_url=session.redirect_url)

    def order(self, user_id: int, order_id: str) -> BillingOrderView:
        row = self._orders.get(order_id)
        if row is None or row.user_id != user_id:
            raise NotFoundError("Order not found")
        return BillingOrderView(id=row.id, amount_inr=row.amount_paise / 100, discount_inr=row.discount_paise / 100,
                                coupon=row.coupon_code, status=row.status, provider=row.provider)

    # --- fulfilment (webhooks / stub page) -----------------------------------
    def fulfil(self, event: PaymentEvent) -> str:
        """Apply a verified payment result. Idempotent: a repeated 'paid' never grants twice."""
        row = self._orders.get(event.order_id)
        if row is None:
            raise NotFoundError("Order not found")
        if row.status != "created":
            return row.status
        if not event.paid:
            self._orders.mark(row, "failed", event.provider_ref)
            return "failed"
        if not self._orders.transition(row.id, "created", "paid", event.provider_ref):
            return "paid"  # a concurrent webhook got there first
        if row.coupon_code:
            self._coupons.redeem(row.coupon_code, row.user_id)
        until = self._entitlements.grant(row.user_id, self._settings.premium_period_days, source="payment",
                                         reference=row.id)
        log.info("Premium paid: order %s user %s until %s", row.id, row.user_id, until)
        return "paid"

    def ensure_welcome_coupon(self) -> None:
        code = self._settings.welcome_coupon.strip()
        if code:
            self._coupons.ensure(code, kind="free_days", value=self._settings.welcome_coupon_days,
                                 max_redemptions=None, valid_until=None, active=True)
