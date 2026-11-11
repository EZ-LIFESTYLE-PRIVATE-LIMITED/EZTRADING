from datetime import datetime

from app.repositories.notifications import PushSubscriptionRepository
from tests.fakes import suggestion


def subscribe(c, endpoint="https://push.example.com/abc"):
    r = c.post("/api/push/subscribe", json={"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}})
    assert r.status_code == 204


def link_telegram(env, c, chat_id=555):
    url = c.post("/api/telegram/link").json()["url"]
    code = url.split("start=")[1]
    hook = env.anonymous().post("/telegram/webhook", json={"message": {"text": f"/start {code}", "chat": {"id": chat_id}}},
                                headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret"})
    assert hook.status_code == 200


def test_plan_notification_sent_once_per_fingerprint(env):
    c = env.client()
    subscribe(c)
    c.put("/api/wallet", json={"deployable": 10_000})
    env.llm.portfolio = {"market_view": "v", "suggestions": [suggestion("ITC", "BUY", 2)]}
    c.post("/api/analyze", json={"style": "swing"})
    c.post("/api/analyze", json={"style": "swing"})  # same actions -> no repeat
    assert len(env.push.sent) == 1
    assert "1 swing action" in env.push.sent[0][1].title and "BUY 2 ITC" in env.push.sent[0][1].body

    env.llm.portfolio = {"market_view": "v", "suggestions": [suggestion("TCS", "BUY", 1)]}
    c.post("/api/analyze", json={"style": "swing"})
    assert len(env.push.sent) == 2


def test_no_notification_without_actions(env):
    c = env.client()
    subscribe(c)
    c.put("/api/wallet", json={"deployable": 10_000})
    env.llm.portfolio = {"market_view": "nothing to do", "suggestions": [suggestion("INFY", "HOLD", 0)]}
    c.post("/api/analyze", json={"style": "swing"})
    assert env.push.sent == []


def test_gone_push_subscription_removed(env):
    c = env.client()
    subscribe(c, "https://push.example.com/dead")
    env.push.gone.add("https://push.example.com/dead")
    assert c.post("/api/notifications/test").json()["channels"] == ["push"]
    with env.container.session_factory() as db:
        assert PushSubscriptionRepository(db).for_user(1) == []


def test_telegram_link_and_delivery(env):
    c = env.client()
    link_telegram(env, c)
    assert env.messenger.sent[-1][0] == "555" and "linked" in env.messenger.sent[-1][1].title
    s = c.get("/api/settings").json()
    assert s["telegram_linked"] is True
    assert c.post("/api/notifications/test").json()["channels"] == ["telegram"]
    c.put("/api/settings", json={"unlink_telegram": True})
    assert c.post("/api/notifications/test").json()["channels"] == []


def test_telegram_webhook_rejects_bad_secret_and_reused_code(env):
    c = env.client()
    url = c.post("/api/telegram/link").json()["url"]
    code = url.split("start=")[1]
    anon = env.anonymous()
    update = {"message": {"text": f"/start {code}", "chat": {"id": 1}}}
    assert anon.post("/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}).status_code == 403
    ok = {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"}
    anon.post("/telegram/webhook", json=update, headers=ok)
    anon.post("/telegram/webhook", json={"message": {"text": f"/start {code}", "chat": {"id": 2}}}, headers=ok)
    assert "expired" in env.messenger.sent[-1][1].body
    assert c.get("/api/settings").json()["telegram_linked"] is True


def test_telegram_plain_start_explains_and_bare_code_links(env):
    c = env.client()
    code = c.post("/api/telegram/link").json()["url"].split("start=")[1]
    anon, ok = env.anonymous(), {"X-Telegram-Bot-Api-Secret-Token": "hook-secret"}
    anon.post("/telegram/webhook", json={"message": {"text": "/start", "chat": {"id": 7}}}, headers=ok)
    assert "Connect Telegram" in env.messenger.sent[-1][1].body and "expired" not in env.messenger.sent[-1][1].body
    assert c.get("/api/settings").json()["telegram_linked"] is False
    anon.post("/telegram/webhook", json={"message": {"text": f"  {code} ", "chat": {"id": 7}}}, headers=ok)
    assert "linked" in env.messenger.sent[-1][1].title
    assert c.get("/api/settings").json()["telegram_linked"] is True


def test_kite_reconnect_notified_once_a_day(env):
    c = env.client()
    subscribe(c)
    with env.container.session_factory() as db:
        services = env.container.for_user(db, 1)
        assert services.notifications.kite_reconnect() == ["push"]
        assert services.notifications.kite_reconnect() == []
        env.clock.now = datetime(2026, 11, 12, 4, 30)
        assert services.notifications.kite_reconnect() == ["push"]
