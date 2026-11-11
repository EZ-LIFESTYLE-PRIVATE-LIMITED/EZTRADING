from datetime import date, datetime

from app.domain.errors import BrokerAuthError
from app.services.market_hours import MarketCalendar
from tests.fakes import suggestion


def test_market_calendar():
    cal = MarketCalendar({date(2026, 11, 13)})
    wed_10am_ist = datetime(2026, 11, 11, 4, 30)
    assert cal.is_open(wed_10am_ist)
    assert not cal.is_open(datetime(2026, 11, 11, 3, 30))   # 09:00 IST
    assert not cal.is_open(datetime(2026, 11, 11, 10, 0))   # 15:30 IST
    assert cal.is_open(datetime(2026, 11, 11, 9, 50)) and not cal.intraday_allowed(datetime(2026, 11, 11, 9, 50))  # 15:20
    assert not cal.is_open(datetime(2026, 11, 13, 4, 30))   # holiday
    assert not cal.is_open(datetime(2026, 11, 14, 4, 30))   # Saturday
    assert cal.next_open(datetime(2026, 11, 12, 11, 0)) == datetime(2026, 11, 16, 3, 45)  # Thu eve -> Mon (Fri holiday)


def enable_auto(env, email="a@example.com", style="swing", interval=30):
    c = env.client(email)
    c.put("/api/wallet", json={"deployable": 10_000})
    c.post("/api/push/subscribe", json={"endpoint": f"https://push.example.com/{email}", "keys": {"p256dh": "p", "auth": "a"}})
    assert c.post("/api/schedules", json={"style": style, "interval_min": interval}).status_code == 201
    return c


def test_auto_runner_runs_due_users_once_per_interval(env):
    c = enable_auto(env)
    env.llm.portfolio = {"market_view": "v", "suggestions": [suggestion("ITC", "BUY", 2)]}
    runner = env.container.auto_runner()

    assert runner.tick() == [1]
    assert c.get("/api/plan").json()["suggestions"][0]["symbol"] == "ITC"
    assert len(env.push.sent) == 1
    assert runner.tick() == []           # not due yet
    env.clock.advance(minutes=31)
    assert runner.tick() == [1]
    assert len(env.push.sent) == 1        # same actions -> deduped


def test_auto_runner_skips_closed_market_and_disabled_users(env):
    enable_auto(env)
    env.client("b@example.com")  # auto disabled
    runner = env.container.auto_runner()
    env.clock.now = datetime(2026, 11, 14, 4, 30)  # Saturday
    assert runner.tick() == []
    env.clock.now = datetime(2026, 11, 16, 4, 30)  # Monday
    assert runner.tick() == [1]


def test_auto_runner_runs_each_schedule_on_its_own_interval(env):
    c = enable_auto(env, style="swing", interval=60)
    c.post("/api/schedules", json={"style": "intraday", "interval_min": 15})
    c.post("/api/schedules", json={"style": "positional", "interval_min": 60, "enabled": False})
    styles: list[str] = []
    original = env.container.auto_target

    def spy(db, user_id):
        target = original(db, user_id)
        real = target.analyze
        target.analyze = lambda style=None, manual=True: (styles.append(style), real(style, manual=manual))[1]
        return target

    env.container.auto_target = spy
    runner = env.container.auto_runner()
    env.llm.portfolio = {"market_view": "v", "suggestions": []}

    assert runner.tick() == [1]
    assert styles == ["swing", "intraday"]          # disabled positional never runs
    env.clock.advance(minutes=16)
    runner.tick()
    assert styles == ["swing", "intraday", "intraday"]
    env.clock.advance(minutes=45)
    runner.tick()
    assert styles[-2:] == ["swing", "intraday"]


def test_auto_runner_notifies_on_expired_kite(env):
    enable_auto(env)
    env.client()  # ensure broker created
    broker = env.brokers[1]
    broker.holdings = lambda: (_ for _ in ()).throw(BrokerAuthError("expired"))
    env.container.auto_runner().tick()
    assert "reconnect Kite" in env.push.sent[-1][1].title


def test_auto_target_has_no_order_capability(env):
    env.client()
    with env.container.session_factory() as db:
        target = env.container.auto_target(db, 1)
        assert not hasattr(target, "orders")
