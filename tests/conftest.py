from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

import app.db.models  # noqa: F401
from app.adapters.broker.fake_broker import FakeBroker
from app.adapters.ipo.fake_ipo import FakeIpoSource
from app.adapters.news.rss_news import NullNews
from app.config import Settings
from app.container import AppContainer, build_app_container
from app.db.base import Base, make_engine, make_session_factory
from app.domain.models import Holding
from app.main import create_app
from tests.fakes import Clock, FakeLLMClient, RecordingMessenger, RecordingPush, StaticPrices


@dataclass
class Env:
    container: AppContainer
    llm: FakeLLMClient
    push: RecordingPush
    messenger: RecordingMessenger
    clock: Clock
    brokers: dict[int, FakeBroker]

    def client(self, email: str = "a@example.com") -> TestClient:
        c = TestClient(create_app(self.container), headers={"X-Requested-With": "fetch"})
        r = c.post("/auth/dev-login", json={"email": email})
        assert r.status_code == 200, r.text
        return c

    def anonymous(self) -> TestClient:
        return TestClient(create_app(self.container))


def default_holdings() -> list[Holding]:
    return [Holding(symbol="INFY", quantity=10, average_price=1400, last_price=1500)]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, env="development", dev_login=True, broker="fake", watchlist="ITC,TCS",
        gemini_api_key="server-gemini-key", default_advisor="gemini:gemini-3.6-flash",
        telegram_bot_token="t", telegram_bot_username="ezt_bot", telegram_webhook_secret="hook-secret",
        manual_analyze_cooldown_seconds=0,
    )


@pytest.fixture
def env(settings, monkeypatch) -> Env:
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    llm = FakeLLMClient()
    monkeypatch.setattr("app.services.advisor_resolver.create_llm_client", lambda *a, **k: llm)
    brokers: dict[int, FakeBroker] = {}
    clock, push, messenger = Clock(), RecordingPush(), RecordingMessenger()

    def broker_factory(db, user_id):
        if user_id not in brokers:
            broker = FakeBroker(holdings=default_holdings())
            broker.set_prices({"ITC": 400.0, "TCS": 4000.0})
            brokers[user_id] = broker
        return brokers[user_id]

    container = build_app_container(
        settings,
        session_factory=make_session_factory(engine),
        news=NullNews(),
        ipo_source=FakeIpoSource(),
        push_sender=push,
        messenger=messenger,
        clock=clock,
        broker_factory=broker_factory,
        price_override=StaticPrices(),
    )
    return Env(container=container, llm=llm, push=push, messenger=messenger, clock=clock, brokers=brokers)
