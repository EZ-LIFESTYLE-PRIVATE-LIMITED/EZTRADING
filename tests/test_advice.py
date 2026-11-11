import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.adapters.llm.factory import create_llm_client
from app.adapters.llm.gemini_client import GeminiClient
from app.config import Settings
from app.domain.errors import AdvisorError
from app.domain.models import AdvisorPlan, AdvisorRequest, IndicatorSet, MarketContext, NewsItem, SymbolContext
from app.services.advice import prompts
from app.services.advice.llm_advisors import LLMPortfolioAdvisor
from app.services.advice.rules import RulesAdvisor
from app.services.indicators import compute_indicators, compute_intraday
from app.services.styles import STYLES
from tests.fakes import FakeLLMClient, make_candles, make_intraday, suggestion


def request(style="swing", market_open=True):
    return AdvisorRequest(
        style=style, budget=5000, as_of=datetime(2026, 1, 1), market_open=market_open,
        market=MarketContext(index_name="NIFTY 50", headlines=[NewsItem(title="Markets rally", source="ET")]),
        symbols=[SymbolContext(symbol="ITC", last_price=400.0, indicators=compute_indicators(make_candles()),
                               intraday=compute_intraday(make_intraday()),
                               news=[NewsItem(title="ITC results", source="MC")])],
    )


def test_parse_normalises_and_rejects():
    text = json.dumps({"market_view": "ok", "suggestions": [suggestion(" itc ", "BUY", 3, confidence=1.7)]})
    p = prompts.parse_json_model(text, AdvisorPlan)
    assert p.suggestions[0].symbol == "ITC" and p.suggestions[0].confidence == 1.0
    for bad in ["not json", json.dumps({"suggestions": [{"symbol": "X", "action": "MAYBE"}]})]:
        with pytest.raises(AdvisorError):
            prompts.parse_json_model(bad, AdvisorPlan)


def test_portfolio_advisor_sends_style_prompt_and_compact_context():
    llm = FakeLLMClient(portfolio={"market_view": "v", "suggestions": [suggestion("ITC", "BUY", 2)]})
    plan = LLMPortfolioAdvisor(llm, STYLES["intraday"]).advise(request("intraday"))
    system, user = llm.calls[0]
    assert "STYLE: INTRADAY" in system
    payload = json.loads(user.split("\n\n", 1)[1])
    assert payload["symbols"][0]["news"] == ["[] ITC results (MC)"]
    assert "vwap" in payload["symbols"][0]["intraday"]
    assert plan.suggestions[0].quantity == 2


def test_schema_requires_every_property():
    item = prompts.PORTFOLIO_SCHEMA["properties"]["suggestions"]["items"]
    assert set(item["required"]) == set(item["properties"])


def test_rules_advisor_styles():
    req = request("swing")
    req.symbols[0].indicators = IndicatorSet(last_close=400, sma50=380, sma200=350, macd_hist=1.2, rsi14=60, atr14=8)
    swing = RulesAdvisor(STYLES["swing"]).advise(req)
    assert swing.suggestions and swing.suggestions[0].stop_loss < 400 < swing.suggestions[0].target
    intraday = RulesAdvisor(STYLES["intraday"]).advise(request("intraday"))
    assert intraday.suggestions[0].action.value == "BUY"  # rising bars: above VWAP
    closed = RulesAdvisor(STYLES["intraday"]).advise(request("intraday", market_open=False))
    assert closed.suggestions == []


def test_gemini_client_request_shape_and_errors():
    models = SimpleNamespace(calls=[], response=SimpleNamespace(text='{"a":1}', usage_metadata=None, candidates=[]))
    models.generate_content = lambda **kw: models.calls.append(kw) or models.response
    client = GeminiClient(model="gemini-test", api_key="k")
    client._client = SimpleNamespace(models=models)
    assert client.complete_json("sys", "user", {"type": "object"}) == '{"a":1}'
    cfg = models.calls[0]["config"]
    assert cfg.response_mime_type == "application/json" and cfg.system_instruction == "sys"

    def boom(**kw):
        raise errors.ClientError(403, {"error": {"code": 403, "message": "denied", "status": "PERMISSION_DENIED"}})
    models.generate_content = boom
    with pytest.raises(AdvisorError, match="invalid"):
        client.complete_json("s", "u", {})


def test_factory_builds_registered_providers():
    s = Settings(_env_file=None)
    assert create_llm_client("gemini", "gemini-3.6-flash", "k", s).name == "gemini:gemini-3.6-flash"
    assert create_llm_client("claude", "claude-opus-5-5", "k", s).name == "claude:claude-opus-5-5"
    with pytest.raises(ValueError):
        create_llm_client("nope", "m", "k", s)
