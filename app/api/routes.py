"""Thin HTTP layer for signed-in users: parse input, call a service, return a model.

Handlers are plain ``def`` so FastAPI runs blocking I/O in its threadpool.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.entitlements import PremiumStatus
from app.api.deps import csrf_guard, get_app, get_db, get_services
from app.container import AppContainer, UserServices
from app.domain.models import AllocationPlan, Ipo, IpoReview, OrderRecord, PortfolioSummary
from app.repositories.notifications import PushSubscriptionRepository
from app.services.account_service import CredentialInput, SettingsService, SettingsUpdate, SettingsView, WalletState
from app.services.advisor_resolver import AdvisorOptionView
from app.services.order_service import ExecuteRequest
from app.services.schedule_service import ScheduleInput, SchedulePatch, ScheduleView

api = APIRouter(prefix="/api", dependencies=[Depends(csrf_guard)])
public = APIRouter()


# --- public ------------------------------------------------------------------
@public.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@public.get("/api/config")
def public_config(app: AppContainer = Depends(get_app)) -> dict:
    s = app.settings
    return {
        "google_enabled": s.google_enabled,
        "fixed_otp": s.otp_override or None,  # shown on the login page outside production
        "password_login": s.password_login_enabled,
        "push_public_key": s.vapid_public_key if s.push_enabled else None,
        "telegram_enabled": s.telegram_enabled,
        "orders_enabled": s.orders_enabled,
    }


# --- account -----------------------------------------------------------------
class Me(BaseModel):
    id: int
    email: str
    name: str
    picture: str
    premium: PremiumStatus


class StatusResponse(BaseModel):
    broker_configured: bool
    broker_connected: bool
    advisor_id: str
    advisor_label: str
    market_open: bool


@api.get("/me", response_model=Me)
def me(services: UserServices = Depends(get_services), app: AppContainer = Depends(get_app),
       db: Session = Depends(get_db)) -> Me:
    user = app.users(db).get(services.user_id)
    return Me(id=user.id, email=user.email, name=user.name, picture=user.picture,
              premium=services.entitlements.status(user.id))


@api.get("/status", response_model=StatusResponse)
def status(services: UserServices = Depends(get_services), app: AppContainer = Depends(get_app)) -> StatusResponse:
    advisor_id = services.settings.view().advisor_id
    return StatusResponse(
        broker_configured=services.broker.is_configured(),
        broker_connected=services.broker.is_authenticated(),
        advisor_id=advisor_id,
        advisor_label=services.resolver.label(advisor_id),
        market_open=app.calendar.is_open(app.clock()),
    )


@api.get("/advisors", response_model=list[AdvisorOptionView])
def advisors(services: UserServices = Depends(get_services)) -> list[AdvisorOptionView]:
    return services.resolver.options()


@api.get("/styles")
def styles() -> list[dict]:
    return SettingsService.styles()


@api.get("/settings", response_model=SettingsView)
def get_settings(services: UserServices = Depends(get_services)) -> SettingsView:
    return services.settings.view()


@api.put("/settings", response_model=SettingsView)
def put_settings(body: SettingsUpdate, services: UserServices = Depends(get_services)) -> SettingsView:
    return services.settings.update(body)


@api.put("/credentials/{kind}", response_model=SettingsView)
def put_credential(kind: str, body: CredentialInput, services: UserServices = Depends(get_services)) -> SettingsView:
    return services.settings.set_credential(kind, body)


@api.delete("/credentials/{kind}", response_model=SettingsView)
def delete_credential(kind: str, services: UserServices = Depends(get_services)) -> SettingsView:
    return services.settings.delete_credential(kind)


@api.get("/schedules", response_model=list[ScheduleView])
def list_schedules(services: UserServices = Depends(get_services)) -> list[ScheduleView]:
    return services.schedules.list()


@api.post("/schedules", response_model=ScheduleView, status_code=201)
def create_schedule(body: ScheduleInput, services: UserServices = Depends(get_services)) -> ScheduleView:
    return services.schedules.create(body)


@api.put("/schedules/{schedule_id}", response_model=ScheduleView)
def update_schedule(schedule_id: int, body: SchedulePatch,
                    services: UserServices = Depends(get_services)) -> ScheduleView:
    return services.schedules.update(schedule_id, body)


@api.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, services: UserServices = Depends(get_services)) -> None:
    services.schedules.delete(schedule_id)


# --- portfolio & wallet --------------------------------------------------------
class WalletUpdate(BaseModel):
    deployable: float = Field(ge=0)


@api.get("/portfolio", response_model=PortfolioSummary)
def portfolio(services: UserServices = Depends(get_services)) -> PortfolioSummary:
    return services.portfolio.summary()


@api.get("/wallet", response_model=WalletState)
def get_wallet(services: UserServices = Depends(get_services)) -> WalletState:
    return services.wallet.state()


@api.put("/wallet", response_model=WalletState)
def put_wallet(body: WalletUpdate, services: UserServices = Depends(get_services)) -> WalletState:
    return services.wallet.set_deployable(body.deployable)


# --- analysis & orders ---------------------------------------------------------
class AnalyzeRequest(BaseModel):
    style: str | None = None


@api.post("/analyze", response_model=AllocationPlan)
def analyze(body: AnalyzeRequest | None = None, services: UserServices = Depends(get_services)) -> AllocationPlan:
    return services.analysis.analyze((body or AnalyzeRequest()).style)


@api.get("/plan", response_model=AllocationPlan | None)
def latest_plan(services: UserServices = Depends(get_services)) -> AllocationPlan | None:
    return services.analysis.latest()


@api.delete("/plans/{plan_id}", status_code=204)
def dismiss_plan(plan_id: str, services: UserServices = Depends(get_services)) -> None:
    services.analysis.dismiss(plan_id)


@api.post("/plans/{plan_id}/suggestions/{suggestion_id}/execute", response_model=OrderRecord)
def execute(plan_id: str, suggestion_id: str, body: ExecuteRequest,
            services: UserServices = Depends(get_services)) -> OrderRecord:
    return services.orders.execute(plan_id, suggestion_id, body)


@api.post("/plans/{plan_id}/suggestions/{suggestion_id}/ignore", status_code=204)
def ignore(plan_id: str, suggestion_id: str, services: UserServices = Depends(get_services)) -> None:
    services.orders.ignore(plan_id, suggestion_id)


@api.get("/orders", response_model=list[OrderRecord])
def orders(services: UserServices = Depends(get_services)) -> list[OrderRecord]:
    return services.orders.list()


@api.post("/orders/{order_id}/refresh", response_model=OrderRecord)
def refresh_order(order_id: int, services: UserServices = Depends(get_services)) -> OrderRecord:
    return services.orders.refresh(order_id)


# --- IPO -------------------------------------------------------------------------
@api.get("/ipos", response_model=list[Ipo])
def ipos(services: UserServices = Depends(get_services)) -> list[Ipo]:
    return services.ipo.list()


@api.post("/ipos/review", response_model=IpoReview)
def ipo_review(services: UserServices = Depends(get_services)) -> IpoReview:
    return services.ipo.review()


# --- notifications -----------------------------------------------------------------
class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1024)
    keys: PushKeys


class PushUnsubscribe(BaseModel):
    endpoint: str


@api.post("/push/subscribe", status_code=204)
def push_subscribe(body: PushSubscriptionIn, services: UserServices = Depends(get_services),
                   db: Session = Depends(get_db)) -> None:
    if not body.endpoint.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid push endpoint")
    PushSubscriptionRepository(db).add(services.user_id, body.endpoint, body.keys.p256dh, body.keys.auth)


@api.post("/push/unsubscribe", status_code=204)
def push_unsubscribe(body: PushUnsubscribe, services: UserServices = Depends(get_services),
                     db: Session = Depends(get_db)) -> None:
    PushSubscriptionRepository(db).remove(services.user_id, body.endpoint)


@api.post("/telegram/link")
def telegram_link(services: UserServices = Depends(get_services), app: AppContainer = Depends(get_app),
                  db: Session = Depends(get_db)) -> dict:
    if not app.settings.telegram_enabled:
        raise HTTPException(status_code=404, detail="Telegram is not configured on this server")
    return {"url": app.telegram_linker(db).link_url(services.user_id)}


@api.post("/notifications/test")
def test_notification(services: UserServices = Depends(get_services)) -> dict:
    return {"channels": services.notifications.test()}
