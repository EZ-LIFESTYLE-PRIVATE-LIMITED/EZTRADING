from datetime import datetime

import pytest

from tests.fakes import suggestion


@pytest.fixture
def setup(env):
    c = env.client()
    c.put("/api/wallet", json={"deployable": 10_000})
    env.llm.portfolio = {"market_view": "v", "suggestions": [
        suggestion("ITC", "BUY", 10, confidence=0.9, entry_price=400, stop_loss=380, target=440),
        suggestion("INFY", "SELL", 4),
    ]}
    plan = c.post("/api/analyze", json={"style": "swing"}).json()
    return c, plan


def execute(c, plan, sid, **body):
    payload = {"quantity": 1, "order_type": "LIMIT", "price": 400.0}
    payload.update(body)
    return c.post(f"/api/plans/{plan['id']}/suggestions/{sid}/execute", json=payload)


def test_execute_buy_places_order_and_spends_wallet(env, setup):
    c, plan = setup
    r = execute(c, plan, "ITC-BUY", quantity=10, price=401)
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["broker_order_id"].startswith("FAKE-") and order["status"] == "COMPLETE"
    placed = env.brokers[1].orders[-1]
    assert (placed.symbol, placed.side.value, placed.quantity, placed.product.value, placed.price) == ("ITC", "BUY", 10, "CNC", 401)
    assert c.get("/api/wallet").json()["deployable"] == 10_000 - 4010
    statuses = {s["id"]: s["status"] for s in c.get("/api/plan").json()["suggestions"]}
    assert statuses["ITC-BUY"] == "executed"
    assert len(c.get("/api/orders").json()) == 1


def test_double_execute_conflicts(setup):
    c, plan = setup
    assert execute(c, plan, "ITC-BUY").status_code == 200
    assert execute(c, plan, "ITC-BUY").status_code == 409


def test_ignore_then_execute_conflicts(setup):
    c, plan = setup
    assert c.post(f"/api/plans/{plan['id']}/suggestions/ITC-BUY/ignore").status_code == 204
    assert execute(c, plan, "ITC-BUY").status_code == 409


def test_market_order_and_sell_from_holdings(env, setup):
    c, plan = setup
    assert execute(c, plan, "INFY-SELL", quantity=4, order_type="MARKET", price=None).status_code == 200
    assert env.brokers[1].orders[-1].order_type.value == "MARKET"


@pytest.mark.parametrize("body,message", [
    ({"quantity": 11}, "exceed the suggested"),
    ({"price": 600}, "too far"),
    ({"order_type": "LIMIT", "price": None}, "limit price is required"),
])
def test_invalid_orders_rejected(setup, body, message):
    c, plan = setup
    r = execute(c, plan, "ITC-BUY", **body)
    assert r.status_code == 400 and message in r.json()["detail"].lower()


def test_over_budget_rejected(setup):
    c, plan = setup
    c.put("/api/wallet", json={"deployable": 500})
    r = execute(c, plan, "ITC-BUY", quantity=2)
    assert r.status_code == 400 and "budget" in r.json()["detail"]


def test_oversell_rejected_when_holdings_changed(env, setup):
    c, plan = setup
    env.brokers[1]._holdings[0] = env.brokers[1]._holdings[0].model_copy(update={"quantity": 2})
    r = execute(c, plan, "INFY-SELL", quantity=4, order_type="MARKET", price=None)
    assert r.status_code == 400 and "hold only 2" in r.json()["detail"]


def test_stale_plan_rejected(env, setup):
    c, plan = setup
    env.clock.advance(hours=7)  # swing plans expire after 6h (checked before market hours)
    r = execute(c, plan, "ITC-BUY")
    assert r.status_code == 400 and "too old" in r.json()["detail"]


def test_market_closed_rejected(env):
    env.clock.now = datetime(2026, 11, 11, 3, 0)  # 08:30 IST, before open
    c = env.client()
    c.put("/api/wallet", json={"deployable": 10_000})
    env.llm.portfolio = {"market_view": "v", "suggestions": [suggestion("ITC", "BUY", 1)]}
    plan = c.post("/api/analyze", json={"style": "swing"}).json()
    r = execute(c, plan, "ITC-BUY")
    assert r.status_code == 400 and "closed" in r.json()["detail"]


def test_broker_failure_recorded_and_retry_allowed(env, setup):
    c, plan = setup
    execute(c, plan, "ITC-BUY")  # ensure broker exists... then reset state via new plan
    env.llm.portfolio = {"market_view": "v", "suggestions": [suggestion("TCS", "BUY", 1)]}
    plan2 = c.post("/api/analyze", json={"style": "swing"}).json()
    env.brokers[1].fail_next_order = "Insufficient funds"
    r = execute(c, plan2, "TCS-BUY", price=4000)
    assert r.status_code == 502 and "Insufficient" in r.json()["detail"]
    orders = c.get("/api/orders").json()
    assert orders[0]["status"] == "FAILED" and orders[0]["error"] == "Insufficient funds"
    assert execute(c, plan2, "TCS-BUY", price=4000).status_code == 200


def test_intraday_short_uses_mis(env):
    c = env.client()
    c.put("/api/wallet", json={"deployable": 10_000})
    env.llm.portfolio = {"market_view": "v", "suggestions": [
        suggestion("ITC", "SELL", 5, entry_price=400, stop_loss=405, target=390)]}
    plan = c.post("/api/analyze", json={"style": "intraday"}).json()
    assert plan["suggestions"][0]["product"] == "MIS"
    assert execute(c, plan, "ITC-SELL", quantity=5).status_code == 200
    assert env.brokers[1].orders[-1].product.value == "MIS"
    assert c.get("/api/wallet").json()["deployable"] == 10_000  # intraday doesn't consume the wallet


def test_orders_kill_switch(env, setup):
    c, plan = setup
    env.container.settings.orders_enabled = False
    assert c.get("/api/config").json()["orders_enabled"] is False
    r = execute(c, plan, "ITC-BUY", quantity=10, price=401)
    assert r.status_code == 403 and "disabled" in r.json()["detail"]
    assert env.brokers[1].orders == []
    assert c.post(f"/api/plans/{plan['id']}/suggestions/ITC-BUY/ignore").status_code == 204
