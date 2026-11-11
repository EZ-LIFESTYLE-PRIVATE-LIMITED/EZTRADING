"""Payment providers (PSPs), chosen by PAYMENT_PROVIDER.

Adding a real PSP (Razorpay, Cashfree, PhonePe, Stripe, ...):
  1. Implement PaymentGatewayPort in app/adapters/payments/<name>.py
     (create_checkout -> hosted payment page URL; parse_webhook -> verify signature, return PaymentEvent).
  2. Register it in _BUILDERS below and add its keys to Settings.
  3. Point the provider's webhook at  https://<domain>/billing/webhook/<name>.
BillingService and the UI need no changes.
"""

from __future__ import annotations

from typing import Callable

from app.config import Settings
from app.domain.ports import PaymentGatewayPort


def _stub(settings: Settings) -> PaymentGatewayPort:
    from app.adapters.payments.stub import StubPaymentGateway

    return StubPaymentGateway(secret=settings.session_secret, can_succeed=settings.payment_stub_can_succeed)


_BUILDERS: dict[str, Callable[[Settings], PaymentGatewayPort]] = {"stub": _stub}


def create_payment_gateway(settings: Settings) -> PaymentGatewayPort:
    name = settings.payment_provider.lower()
    if name not in _BUILDERS:
        raise RuntimeError(f"Unknown PAYMENT_PROVIDER '{settings.payment_provider}'. Known: {', '.join(_BUILDERS)}")
    return _BUILDERS[name](settings)
