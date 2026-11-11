import json
from datetime import datetime, timedelta

import pytest

from app.adapters.payments.stub import SIGNATURE_HEADER
from app.repositories.billing import CouponRepository
from tests.fakes import suggestion


@pytest.fixture
def enforced(env):
    env.container.settings.premium_enforced = True
    return env


def _plan(env):
    env.llm.portfolio = {"market_view": "v", "suggestions": [suggestion("ITC", "BUY", 1)]}


def test_server_keys_open_to_everyone_when_not_enforced(env):
    c = env.client()
    options = {o["id"]: o for o in c.get("/api/advisors").json()}
    assert options["gemini:gemini-3.6-flash"]["key_source"] == "server"
    assert c.get("/api/me").json()["premium"] == {
        "active": False, "until": None, "enforced": False, "price_inr": 199, "period_days": 30}


def test_free_user_cannot_use_server_keys_when_enforced(enforced):
    c = enforced.client()
    me = c.get("/api/me").json()
    assert me["premium"]["enforced"] is True and me["premium"]["active"] is False
    assert c.get("/api/settings").json()["advisor_id"] == "rules"  # new users start on Rules
    options = {o["id"]: o for o in c.get("/api/advisors").json()}
    assert options["gemini:gemini-3.6-flash"]["key_source"] == "premium"
    assert options["gemini:gemini-3.6-flash"]["available"] is False
    r = c.put("/api/settings", json={"advisor_id": "gemini:gemini-3.6-flash"})
    assert r.status_code == 403 and "Premium" in r.json()["detail"]
    assert c.get("/api/settings").json()["server_keys_allowed"] is False

    # Their own key works without premium.
    c.put("/api/credentials/gemini", json={"api_key": "user-gemini-key"})
    assert c.put("/api/settings", json={"advisor_id": "gemini:gemini-3.6-flash"}).status_code == 200


def test_analysis_with_server_key_needs_premium(enforced):
    c = enforced.client()
    c.put("/api/wallet", json={"deployable": 5000})
    with enforced.container.session_factory() as db:  # simulate an advisor chosen while they were premium
        from app.repositories.users import SettingsRepository
        SettingsRepository(db).update(1, advisor_id="gemini:gemini-3.6-flash")
    _plan(enforced)
    r = c.post("/api/analyze", json={"style": "swing"})
    assert r.status_code == 403 and "Premium" in r.json()["detail"]


def test_free7_coupon_unlocks_premium_once_and_expires(enforced):
    c = enforced.client()
    q = c.post("/api/billing/quote", json={"coupon": "free7"}).json()
    assert q["free_days"] == 7 and q["total_inr"] == 0
    r = c.post("/api/billing/checkout", json={"coupon": " Free7 "}).json()
    assert r["status"] == "activated"
    assert c.get("/api/me").json()["premium"]["active"] is True
    options = {o["id"]: o for o in c.get("/api/advisors").json()}
    assert options["gemini:gemini-3.6-flash"]["key_source"] == "server"

    again = c.post("/api/billing/checkout", json={"coupon": "FREE7"})
    assert again.status_code == 400 and "already used" in again.json()["detail"]

    enforced.clock.now += timedelta(days=7, minutes=1)
    assert c.get("/api/me").json()["premium"]["active"] is False
    options = {o["id"]: o for o in c.get("/api/advisors").json()}
    assert options["gemini:gemini-3.6-flash"]["key_source"] == "premium"


def test_coupon_validation_and_discounts(enforced):
    c = enforced.client()
    now = enforced.clock()
    with enforced.container.session_factory() as db:
        repo = CouponRepository(db)
        repo.upsert("HALF", kind="percent", value=50, max_redemptions=None, valid_until=None, active=True)
        repo.upsert("FLAT50", kind="flat", value=50, max_redemptions=None, valid_until=None, active=True)
        repo.upsert("OLD", kind="percent", value=10, max_redemptions=None, valid_until=now - timedelta(days=1),
                    active=True)
        repo.upsert("OFF", kind="percent", value=10, max_redemptions=None, valid_until=None, active=False)
        repo.upsert("ONE", kind="free_days", value=3, max_redemptions=1, valid_until=None, active=True)
    assert c.post("/api/billing/quote", json={}).json()["total_inr"] == 199
    assert c.post("/api/billing/quote", json={"coupon": "half"}).json()["total_inr"] == 99  # 199 - round(99.5)
    assert c.post("/api/billing/quote", json={"coupon": "FLAT50"}).json()["total_inr"] == 149
    for code, msg in [("OLD", "expired"), ("OFF", "isn't valid"), ("NOPE", "isn't valid")]:
        r = c.post("/api/billing/quote", json={"coupon": code})
        assert r.status_code == 400 and msg in r.json()["detail"], code
    assert c.post("/api/billing/checkout", json={"coupon": "ONE"}).json()["status"] == "activated"
    other = enforced.client("b@example.com")
    r = other.post("/api/billing/quote", json={"coupon": "ONE"})
    assert r.status_code == 400 and "fully used" in r.json()["detail"]


def test_stub_payment_success_is_idempotent_and_stacks(enforced):
    c = enforced.client()
    c.post("/api/billing/checkout", json={"coupon": "FREE7"})
    r = c.post("/api/billing/checkout", json={}).json()
    assert r["status"] == "redirect" and r["redirect_url"].startswith("/billing-stub.html?order=")
    order_id = r["redirect_url"].split("order=")[1]
    assert c.get(f"/api/billing/orders/{order_id}").json()["amount_inr"] == 199

    other = enforced.client("b@example.com")
    assert other.post("/api/billing/stub/complete", json={"order_id": order_id, "paid": True}).status_code == 404

    assert c.post("/api/billing/stub/complete", json={"order_id": order_id, "paid": True}).json()["status"] == "paid"
    assert c.post("/api/billing/stub/complete", json={"order_id": order_id, "paid": True}).json()["status"] == "paid"
    until = datetime.fromisoformat(c.get("/api/me").json()["premium"]["until"])
    assert until == enforced.clock() + timedelta(days=7 + 30)  # 30 paid days stack after the 7 free ones


def test_stub_payment_failure_and_signed_webhook(enforced):
    c = enforced.client()
    order_id = c.post("/api/billing/checkout", json={}).json()["redirect_url"].split("order=")[1]
    assert c.post("/api/billing/stub/complete", json={"order_id": order_id, "paid": False}).json()["status"] == "failed"
    assert c.get("/api/me").json()["premium"]["active"] is False

    order2 = c.post("/api/billing/checkout", json={}).json()["redirect_url"].split("order=")[1]
    body = json.dumps({"order_id": order2, "paid": True}).encode()
    anon = enforced.anonymous()
    bad = anon.post("/billing/webhook/stub", content=body, headers={SIGNATURE_HEADER: "nope"})
    assert bad.status_code == 400
    sig = enforced.container.payment_gateway.sign(body)
    assert anon.post("/billing/webhook/stub", content=body, headers={SIGNATURE_HEADER: sig}).json()["status"] == "paid"
    assert c.get("/api/me").json()["premium"]["active"] is True


def test_stub_cannot_succeed_in_production(enforced):
    enforced.container.payment_gateway.can_succeed = False
    c = enforced.client()
    assert c.get("/api/billing").json()["payments_available"] is False
    order_id = c.post("/api/billing/checkout", json={}).json()["redirect_url"].split("order=")[1]
    r = c.post("/api/billing/stub/complete", json={"order_id": order_id, "paid": True})
    assert r.status_code == 403
    assert c.get("/api/me").json()["premium"]["active"] is False
    assert c.post("/api/billing/checkout", json={"coupon": "FREE7"}).json()["status"] == "activated"  # coupons still work
