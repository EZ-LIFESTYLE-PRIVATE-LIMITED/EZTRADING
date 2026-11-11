"""Premium plan, coupons, checkout, and payment-provider webhooks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import csrf_guard, get_app, get_db, get_services
from app.container import AppContainer, UserServices
from app.domain.errors import NotFoundError
from app.services.billing import BillingOrderView, CheckoutResult, Quote
from app.services.entitlements import PremiumStatus

api = APIRouter(prefix="/api/billing", dependencies=[Depends(csrf_guard)])
webhooks = APIRouter(prefix="/billing")


class BillingInfo(BaseModel):
    premium: PremiumStatus
    plan_name: str
    price_inr: int
    period_days: int
    provider: str
    payments_available: bool  # False when only the stub runs in production


class CouponBody(BaseModel):
    coupon: str | None = None


class StubCompleteBody(BaseModel):
    order_id: str
    paid: bool


@api.get("", response_model=BillingInfo)
def billing_info(services: UserServices = Depends(get_services), app: AppContainer = Depends(get_app)) -> BillingInfo:
    s, gateway = app.settings, app.payment_gateway
    return BillingInfo(
        premium=services.entitlements.status(services.user_id), plan_name="Premium", price_inr=s.premium_price_inr,
        period_days=s.premium_period_days, provider=gateway.name,
        payments_available=getattr(gateway, "can_succeed", True),
    )


@api.post("/quote", response_model=Quote)
def quote(body: CouponBody, services: UserServices = Depends(get_services), app: AppContainer = Depends(get_app),
          db: Session = Depends(get_db)) -> Quote:
    return app.billing(db).quote(services.user_id, body.coupon)


@api.post("/checkout", response_model=CheckoutResult)
def checkout(body: CouponBody, services: UserServices = Depends(get_services), app: AppContainer = Depends(get_app),
             db: Session = Depends(get_db)) -> CheckoutResult:
    user = app.users(db).get(services.user_id)
    return app.billing(db).checkout(services.user_id, user.email, body.coupon)


@api.get("/orders/{order_id}", response_model=BillingOrderView)
def get_order(order_id: str, services: UserServices = Depends(get_services), app: AppContainer = Depends(get_app),
              db: Session = Depends(get_db)) -> BillingOrderView:
    return app.billing(db).order(services.user_id, order_id)


@api.post("/stub/complete")
def stub_complete(body: StubCompleteBody, services: UserServices = Depends(get_services),
                  app: AppContainer = Depends(get_app), db: Session = Depends(get_db)) -> dict:
    """The stub PSP's 'payment page' result. Only exists while PAYMENT_PROVIDER=stub."""
    gateway = app.payment_gateway
    if gateway.name != "stub":
        raise NotFoundError("Not available")
    billing = app.billing(db)
    billing.order(services.user_id, body.order_id)  # must be this user's order
    return {"status": billing.fulfil(gateway.complete(body.order_id, body.paid))}


@webhooks.post("/webhook/{provider}")
async def payment_webhook(provider: str, request: Request, app: AppContainer = Depends(get_app),
                          db: Session = Depends(get_db)) -> dict:
    gateway = app.payment_gateway
    if provider != gateway.name:
        raise NotFoundError("Unknown payment provider")
    event = gateway.parse_webhook({k.lower(): v for k, v in request.headers.items()}, await request.body())
    return {"status": app.billing(db).fulfil(event)}
