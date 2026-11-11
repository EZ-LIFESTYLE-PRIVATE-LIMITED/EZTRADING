"""Composition root: the only place that knows about concrete adapters.

AppContainer  - process-wide singletons (DB, caches, external feeds, senders).
UserServices  - everything scoped to one signed-in user, built per request/job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.broker.fake_broker import FakeBroker
from app.adapters.broker.unconfigured_broker import UnconfiguredBroker
from app.adapters.news.rss_news import RssNews
from app.adapters.notify.telegram import NullMessenger, TelegramMessenger
from app.adapters.notify.webpush import NullPushSender, WebPushSender
from app.adapters.prices.composite import CachedPriceHistory, FallbackPriceHistory, PriceCache
from app.adapters.prices.yfinance_history import YFinanceHistory
from app.config import Settings
from app.db.base import make_engine, make_session_factory, run_migrations, utcnow
from app.domain.models import Interval
from app.adapters.email import create_email_sender
from app.adapters.payments import create_payment_gateway
from app.domain.ports import (
    BrokerPort,
    EmailSenderPort,
    IpoSourcePort,
    MessengerPort,
    NewsPort,
    PaymentGatewayPort,
    PriceHistoryPort,
    PushSenderPort,
)
from app.repositories.auth import LoginAttemptRepository, OtpRepository
from app.repositories.billing import BillingOrderRepository, CouponRepository, SubscriptionRepository
from app.repositories.notifications import NotificationLogRepository, PushSubscriptionRepository, TelegramLinkRepository
from app.repositories.trading import OrderRepository, PlanRepository, SuggestionActionRepository
from app.repositories.users import (
    CredentialRepository,
    KiteTokenRepository,
    ScheduleRepository,
    SettingsRepository,
    UserRepository,
    WalletRepository,
)
from app.security.crypto import SecretBox
from app.services.account_service import PortfolioService, SettingsService, WalletService
from app.services.advisor_resolver import AdvisorResolver
from app.services.analysis_service import AnalysisService
from app.services.auto_runner import AutoAnalysisRunner
from app.services.billing import BillingService
from app.services.password_auth import PasswordAuthService
from app.services.entitlements import EntitlementService
from app.services.ipo_service import IpoService
from app.services.limits import AnalyzeLimiter
from app.services.market_context import MarketContextBuilder
from app.services.schedule_service import ScheduleService
from app.services.market_hours import MarketCalendar
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.services.telegram_link import TelegramLinker

BrokerFactory = Callable[[Session, int], BrokerPort]


@dataclass
class UserServices:
    user_id: int
    broker: BrokerPort
    resolver: AdvisorResolver
    settings: SettingsService
    schedules: ScheduleService
    wallet: WalletService
    portfolio: PortfolioService
    analysis: AnalysisService
    orders: OrderService
    notifications: NotificationService
    ipo: IpoService
    entitlements: EntitlementService


@dataclass
class AutoTarget:
    """The only capabilities the scheduler gets: analyse and notify (no OrderService)."""

    analysis: AnalysisService
    notifications: NotificationService

    def analyze(self, style_key: str | None = None, manual: bool = True):
        return self.analysis.analyze(style_key, manual=manual)

    def kite_reconnect(self) -> list[str]:
        return self.notifications.kite_reconnect()


@dataclass
class AppContainer:
    settings: Settings
    session_factory: sessionmaker
    box: SecretBox
    calendar: MarketCalendar
    news: NewsPort
    ipo_source: IpoSourcePort
    push_sender: PushSenderPort
    messenger: MessengerPort
    price_cache: PriceCache
    limiter: AnalyzeLimiter
    payment_gateway: PaymentGatewayPort
    email_sender: EmailSenderPort
    clock: Callable[[], datetime] = utcnow
    broker_factory: BrokerFactory | None = None
    price_override: PriceHistoryPort | None = None
    _fake_brokers: dict[int, FakeBroker] = field(default_factory=dict)

    # --- per-user ----------------------------------------------------------
    def for_user(self, db: Session, user_id: int) -> UserServices:
        s = self.settings
        settings_repo = SettingsRepository(db)
        credentials = CredentialRepository(db, self.box, user_id)
        kite_tokens = KiteTokenRepository(db, self.box, user_id, self.calendar.today(self.clock()))
        broker, kite_session = self._broker(db, user_id, credentials, kite_tokens)
        entitlements = self.entitlements(db)
        resolver = AdvisorResolver(s, credentials, allow_server_keys=entitlements.allows_server_keys(user_id))
        wallet = WalletService(WalletRepository(db, user_id), broker)
        notifications = NotificationService(
            user_id, settings_repo, PushSubscriptionRepository(db), NotificationLogRepository(db),
            self.push_sender, self.messenger, self.clock,
        )
        plans = PlanRepository(db, user_id)
        analysis = AnalysisService(
            user_id=user_id, broker=broker, wallet=wallet,
            context_builder=MarketContextBuilder(
                prices=self._prices(kite_session), news=self.news, index_name=s.market_index,
                news_per_symbol=s.news_per_symbol, market_news_limit=s.market_news_limit, max_workers=s.max_workers,
            ),
            resolver=resolver, settings_repo=settings_repo, plans=plans, notifications=notifications,
            calendar=self.calendar, limiter=self.limiter, watchlist=s.watchlist_symbols, clock=self.clock,
        )
        return UserServices(
            user_id=user_id,
            broker=broker,
            resolver=resolver,
            settings=SettingsService(user_id, s, settings_repo, credentials, kite_tokens, resolver),
            schedules=ScheduleService(user_id, ScheduleRepository(db), self.clock),
            wallet=wallet,
            portfolio=PortfolioService(broker),
            analysis=analysis,
            orders=OrderService(broker, plans, SuggestionActionRepository(db), OrderRepository(db, user_id),
                                wallet, self.calendar, self.clock, enabled=s.orders_enabled),
            notifications=notifications,
            ipo=IpoService(user_id, self.ipo_source, self.news, resolver, wallet, settings_repo),
            entitlements=entitlements,
        )

    def auto_target(self, db: Session, user_id: int) -> AutoTarget:
        services = self.for_user(db, user_id)
        return AutoTarget(analysis=services.analysis, notifications=services.notifications)

    def auto_runner(self) -> AutoAnalysisRunner:
        return AutoAnalysisRunner(self.session_factory, self.auto_target, self.calendar, self.clock,
                                  max_workers=max(1, self.settings.max_workers // 2))

    def entitlements(self, db: Session) -> EntitlementService:
        return EntitlementService(SubscriptionRepository(db), self.settings, self.clock)

    def billing(self, db: Session) -> BillingService:
        return BillingService(self.settings, CouponRepository(db), BillingOrderRepository(db), self.entitlements(db),
                              self.payment_gateway, self.clock)

    def password_auth(self, db: Session) -> PasswordAuthService:
        return PasswordAuthService(self.settings, UserRepository(db), OtpRepository(db), LoginAttemptRepository(db),
                                   self.email_sender, self.clock)

    def users(self, db: Session) -> UserRepository:
        return UserRepository(db)

    def telegram_linker(self, db: Session) -> TelegramLinker:
        return TelegramLinker(TelegramLinkRepository(db), SettingsRepository(db), self.messenger,
                              self.settings.telegram_bot_username)

    # --- internals ---------------------------------------------------------
    def _broker(self, db: Session, user_id: int, credentials: CredentialRepository, tokens: KiteTokenRepository):
        if self.broker_factory is not None:
            return self.broker_factory(db, user_id), None
        if self.settings.broker.lower() == "fake":
            return self._fake_brokers.setdefault(user_id, FakeBroker()), None
        creds = credentials.get("kite")
        if not creds:
            return UnconfiguredBroker(), None
        from app.adapters.broker.kite_broker import KiteBroker
        from app.adapters.broker.kite_session import KiteSession

        session = KiteSession(creds["api_key"], creds["api_secret"], tokens)
        return KiteBroker(session), session

    def _prices(self, kite_session) -> PriceHistoryPort:
        if self.price_override is not None:
            return self.price_override
        sources: list[PriceHistoryPort] = []
        if kite_session is not None and kite_session.is_authenticated():
            from app.adapters.prices.kite_history import KiteHistory

            sources.append(KiteHistory(kite_session))
        sources.append(YFinanceHistory())
        return CachedPriceHistory(FallbackPriceHistory(sources), self.price_cache)


def build_app_container(settings: Settings, **overrides) -> AppContainer:
    """Build real adapters; tests pass overrides (session_factory, news, ipo_source, ...)."""
    if "session_factory" not in overrides:
        if not settings.is_production:
            run_migrations(settings.database_url)  # production runs `alembic upgrade head` in the entrypoint
        overrides["session_factory"] = make_session_factory(make_engine(settings.database_url))
    defaults = dict(
        box=SecretBox.from_settings(settings),
        calendar=MarketCalendar(settings.holiday_dates),
        news=RssNews(settings.market_feed_urls, timeout=settings.news_timeout_seconds),
        ipo_source=_ipo_source(settings),
        push_sender=WebPushSender(settings.vapid_private_key, settings.vapid_subject)
        if settings.push_enabled else NullPushSender(),
        messenger=TelegramMessenger(settings.telegram_bot_token, settings.public_base_url)
        if settings.telegram_enabled else NullMessenger(),
        price_cache=PriceCache({Interval.DAY: settings.price_cache_ttl_seconds,
                                Interval.MIN5: settings.intraday_cache_ttl_seconds}),
        limiter=AnalyzeLimiter(settings.manual_analyze_cooldown_seconds),
        payment_gateway=create_payment_gateway(settings),
        email_sender=create_email_sender(settings),
    )
    defaults.update(overrides)
    container = AppContainer(settings=settings, **defaults)
    with container.session_factory() as db:
        container.billing(db).ensure_welcome_coupon()
    return container


def _ipo_source(settings: Settings) -> IpoSourcePort:
    if settings.ipo_source.lower() == "fake":
        from app.adapters.ipo.fake_ipo import FakeIpoSource

        return FakeIpoSource()
    from app.adapters.ipo.nse_ipo import NseIpoSource

    return NseIpoSource(ttl_seconds=settings.ipo_cache_ttl_seconds)
