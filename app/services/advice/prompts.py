"""Provider-neutral prompts, JSON schemas and request serialisation for advisor tasks."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.domain.errors import AdvisorError
from app.domain.models import AdvisorRequest, Ipo

M = TypeVar("M", bound=BaseModel)

_NULLABLE_NUMBER = {"type": ["number", "null"]}

PORTFOLIO_SYSTEM = """\
You are a disciplined equity trading analyst for the Indian stock market (NSE).
You receive: the user's holdings, a cash budget they are willing to deploy now, locally computed
technical indicators for each stock, recent news headlines per stock, a broad-market snapshot
(index trend + market headlines), whether the market is open, and a TRADING STYLE with its own rules.

Produce an allocation plan:
- BUY: only stocks in the provided universe. Whole-share quantities. The total cost of all BUYs
  (quantity x last_price) must not exceed the budget. Leaving cash unallocated is fine and often right.
- SELL / HOLD: as defined by the trading style below.
- If nothing is compelling, return no trades and explain why in market_view. "No action" is a valid plan.

Weigh evidence: trend, momentum, volatility, key levels, volume confirmation, and whether news is a real
catalyst or noise. Factor in the market regime. Prefer diversification. Each rationale: 1-3 concrete
sentences citing the indicators/news that drove the call. confidence is 0..1. Prices are in INR.
Use null for entry_price/stop_loss/target/horizon when not applicable.
This is decision support; the user confirms every order themselves."""

PORTFOLIO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "market_view": {"type": "string"},
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
                    "quantity": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                    "entry_price": _NULLABLE_NUMBER,
                    "stop_loss": _NULLABLE_NUMBER,
                    "target": _NULLABLE_NUMBER,
                    "horizon": {"type": ["string", "null"]},
                },
                "required": ["symbol", "action", "quantity", "confidence", "rationale",
                             "entry_price", "stop_loss", "target", "horizon"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["market_view", "suggestions"],
    "additionalProperties": False,
}

IPO_SYSTEM = """\
You are an analyst evaluating Indian IPOs (NSE mainboard and SME) for a retail investor.
For each IPO you receive the issue details (price band, lot size, dates, issue size, subscription
multiple if known), recent news headlines, the investor's available budget and the current market mood.

For each IPO return a verdict:
- APPLY: fundamentals/news look reasonable, demand is healthy, pricing not stretched.
- AVOID: red flags (weak business, aggressive pricing, poor demand, governance concerns, very risky SME).
- NEUTRAL: not enough information or a coin-flip; say what to watch.
SME IPOs carry high lot sizes and liquidity risk; be stricter. Subscription data matters most near close.
suggested_lots: retail lots to apply for (0 for AVOID/NEUTRAL); lots x lot_size x price_high must fit
the budget. Keep rationale and risks to 1-3 sentences each. overview: 2-3 sentences on the IPO market.
This is decision support, not investment advice."""

IPO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["APPLY", "AVOID", "NEUTRAL"]},
                    "rationale": {"type": "string"},
                    "risks": {"type": "string"},
                    "suggested_lots": {"type": "integer"},
                },
                "required": ["symbol", "verdict", "rationale", "risks", "suggested_lots"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "assessments"],
    "additionalProperties": False,
}


def portfolio_system_prompt(style_prompt: str) -> str:
    return f"{PORTFOLIO_SYSTEM}\n\n{style_prompt}"


def portfolio_user_prompt(request: AdvisorRequest) -> str:
    """Serialise compactly (drop nulls, flatten news) to keep tokens down."""
    payload = request.model_dump(mode="json", exclude_none=True)
    for sym in payload["symbols"]:
        sym["news"] = [headline(n) for n in sym.get("news", [])]
    payload["market"]["headlines"] = [headline(n) for n in payload["market"].get("headlines", [])]
    return "Here is the current context as JSON. Return the allocation plan.\n\n" + _compact(payload)


def ipo_user_prompt(ipos: list[Ipo], news: dict[str, list[str]], budget: float, market_headlines: list[str]) -> str:
    payload = {
        "budget": budget,
        "market_headlines": market_headlines,
        "ipos": [{**i.model_dump(mode="json", exclude_none=True), "news": news.get(i.symbol, [])} for i in ipos],
    }
    return "Evaluate these IPOs. Context as JSON:\n\n" + _compact(payload)


def headline(news: Any) -> str:
    data = news if isinstance(news, dict) else news.model_dump(mode="json")
    when = (data.get("published") or "")[:10]
    src = data.get("source") or ""
    return f"[{when}] {data['title']} ({src})".strip()


def parse_json_model(text: str, model: type[M]) -> M:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdvisorError(f"Advisor returned invalid JSON: {exc}") from exc
    if isinstance(data, dict):
        _normalise(data)
    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        raise AdvisorError(f"Advisor returned an unexpected shape: {exc}") from exc


def _normalise(data: dict) -> None:
    for key in ("suggestions", "assessments"):
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("symbol"), str):
                item["symbol"] = item["symbol"].strip().upper()
            if isinstance(item.get("confidence"), (int, float)):
                item["confidence"] = min(max(float(item["confidence"]), 0.0), 1.0)
            if isinstance(item.get("suggested_lots"), int):
                item["suggested_lots"] = max(item["suggested_lots"], 0)


def _compact(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"))
