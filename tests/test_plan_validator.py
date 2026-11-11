from app.domain.models import Action, AdvisorPlan, AdvisorSuggestion, Product, SymbolContext
from app.services.plan_validator import PlanValidator
from app.services.styles import STYLES

CONTEXTS = [
    SymbolContext(symbol="INFY", last_price=1500.0, held_quantity=10, average_price=1400.0),
    SymbolContext(symbol="TCS", last_price=4000.0),
    SymbolContext(symbol="ITC", last_price=400.0),
    SymbolContext(symbol="NOPRICE", last_price=None),
]


def plan(*items):
    return AdvisorPlan(market_view="view", suggestions=[AdvisorSuggestion(**i) for i in items])


def validate(p, budget=10_000, style="positional"):
    return PlanValidator().validate(p, CONTEXTS, budget, "test", STYLES[style])


def by_symbol(result):
    return {s.symbol: s for s in result.suggestions}


def test_buys_fit_budget_by_confidence():
    result = validate(plan(
        {"symbol": "TCS", "action": "BUY", "quantity": 5, "confidence": 0.9},
        {"symbol": "ITC", "action": "BUY", "quantity": 50, "confidence": 0.5},
    ))
    s = by_symbol(result)
    assert s["TCS"].quantity == 2 and s["ITC"].quantity == 5
    assert result.total_buy == 10_000 and result.cash_left == 0
    assert s["TCS"].id == "TCS-BUY" and s["TCS"].product is Product.CNC
    assert len(result.id) == 32 and result.style == "positional"


def test_delivery_sell_clamped_and_no_shorting():
    result = validate(plan(
        {"symbol": "INFY", "action": "SELL", "quantity": 50},
        {"symbol": "TCS", "action": "SELL", "quantity": 1},
    ))
    s = by_symbol(result)
    assert s["INFY"].quantity == 10 and "TCS" not in s
    assert result.total_sell == 15_000 and result.cash_left == 10_000


def test_unknown_duplicate_unpriced_and_zero_qty_ignored():
    result = validate(plan(
        {"symbol": "XYZ", "action": "BUY", "quantity": 1},
        {"symbol": "NOPRICE", "action": "BUY", "quantity": 1},
        {"symbol": "ITC", "action": "BUY", "quantity": 1},
        {"symbol": "ITC", "action": "BUY", "quantity": 3},
        {"symbol": "TCS", "action": "BUY", "quantity": 0},
    ))
    assert list(by_symbol(result)) == ["ITC"]
    assert len(result.warnings) == 4


def test_wrong_side_levels_removed_for_swing():
    result = validate(plan({"symbol": "ITC", "action": "BUY", "quantity": 1, "stop_loss": 410, "target": 390}),
                      style="swing")
    s = by_symbol(result)["ITC"]
    assert s.stop_loss is None and s.target is None
    assert len(result.warnings) == 2


def test_intraday_requires_stop_loss_and_allows_shorts():
    result = validate(plan(
        {"symbol": "ITC", "action": "SELL", "quantity": 10, "stop_loss": 404, "target": 392, "confidence": 0.8},
        {"symbol": "TCS", "action": "BUY", "quantity": 1},  # no stop-loss -> dropped
        {"symbol": "INFY", "action": "HOLD"},               # HOLD ignored intraday
    ), style="intraday")
    s = by_symbol(result)
    assert list(s) == ["ITC"]
    assert s["ITC"].action is Action.SELL and s["ITC"].product is Product.MIS
    assert result.cash_left == 10_000 - 4_000  # shorts consume budget
    assert any("stop-loss" in w for w in result.warnings)


def test_hold_only_for_held_positions():
    result = validate(plan({"symbol": "INFY", "action": "HOLD"}, {"symbol": "TCS", "action": "HOLD"}))
    assert [(s.symbol, s.action) for s in result.suggestions] == [("INFY", Action.HOLD)]
