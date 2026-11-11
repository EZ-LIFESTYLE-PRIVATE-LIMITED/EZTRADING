"""Advisor tasks that work with any LLMClientPort (Gemini, Claude, ...)."""

from __future__ import annotations

from app.domain.models import AdvisorPlan, AdvisorRequest, Ipo, IpoAdvice
from app.domain.ports import LLMClientPort
from app.services.advice import prompts
from app.services.styles import TradingStyle


class LLMPortfolioAdvisor:
    def __init__(self, client: LLMClientPort, style: TradingStyle) -> None:
        self._client = client
        self._style = style
        self.name = client.name

    def advise(self, request: AdvisorRequest) -> AdvisorPlan:
        text = self._client.complete_json(
            prompts.portfolio_system_prompt(self._style.prompt),
            prompts.portfolio_user_prompt(request),
            prompts.PORTFOLIO_SCHEMA,
        )
        return prompts.parse_json_model(text, AdvisorPlan)


class LLMIpoAdvisor:
    def __init__(self, client: LLMClientPort) -> None:
        self._client = client
        self.name = client.name

    def assess(self, ipos: list[Ipo], news: dict[str, list[str]], budget: float, market_headlines: list[str]) -> IpoAdvice:
        text = self._client.complete_json(
            prompts.IPO_SYSTEM,
            prompts.ipo_user_prompt(ipos, news, budget, market_headlines),
            prompts.IPO_SCHEMA,
        )
        return prompts.parse_json_model(text, IpoAdvice)
