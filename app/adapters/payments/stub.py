"""A pretend PSP for development: checkout goes to a local page with "Pay" and "Fail" buttons.

In production it can't succeed (unless PAYMENT_STUB_ALLOW_SUCCESS=true), so nobody gets premium for free.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from app.domain.errors import ForbiddenError, ValidationError
from app.domain.models import CheckoutOrder, CheckoutSession, PaymentEvent

SIGNATURE_HEADER = "x-stub-signature"


class StubPaymentGateway:
    name = "stub"

    def __init__(self, secret: str, can_succeed: bool) -> None:
        self._secret = secret.encode()
        self.can_succeed = can_succeed

    def create_checkout(self, order: CheckoutOrder) -> CheckoutSession:
        return CheckoutSession(redirect_url=f"/billing-stub.html?order={order.order_id}",
                               provider_ref=f"stub_{order.order_id}")

    def complete(self, order_id: str, paid: bool) -> PaymentEvent:
        """What the stub checkout page reports when you click Pay or Fail."""
        if paid and not self.can_succeed:
            raise ForbiddenError("Online payments are coming soon. Use a coupon for now.")
        return PaymentEvent(order_id=order_id, paid=paid, provider_ref=f"stub_{order_id}")

    def sign(self, body: bytes) -> str:
        return hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> PaymentEvent:
        """Same shape a real PSP webhook has: a signed body. Used by tests."""
        if not hmac.compare_digest(headers.get(SIGNATURE_HEADER, ""), self.sign(body)):
            raise ValidationError("Invalid webhook signature")
        data = json.loads(body)
        return self.complete(str(data["order_id"]), bool(data["paid"]))
