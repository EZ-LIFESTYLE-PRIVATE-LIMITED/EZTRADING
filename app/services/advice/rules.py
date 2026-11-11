"""Deterministic, offline advisor based purely on indicators (advisor id 'rules').

Useful without an API key, for demos and as a baseline. Not news-aware.
"""

from __future__ import annotations

from app.domain.models import Action, AdvisorPlan, AdvisorRequest, AdvisorSuggestion, SymbolContext
from app.services.styles import TradingStyle


class RulesAdvisor:
    name = "rules"

    def __init__(self, style: TradingStyle, max_positions: int = 4) -> None:
        self._style = style
        self._max_positions = max_positions

    def advise(self, request: AdvisorRequest) -> AdvisorPlan:
        if self._style.intraday:
            return self._intraday(request)
        return self._delivery(request)

    # --- swing / positional ------------------------------------------------
    def _delivery(self, request: AdvisorRequest) -> AdvisorPlan:
        suggestions: list[AdvisorSuggestion] = []
        candidates: list[tuple[float, SymbolContext]] = []
        for ctx in request.symbols:
            ind = ctx.indicators
            if ind is None or ctx.last_price is None:
                continue
            score = _daily_score(ctx)
            if ctx.held_quantity > 0:
                if score <= -2:
                    suggestions.append(AdvisorSuggestion(
                        symbol=ctx.symbol, action=Action.SELL, quantity=max(1, ctx.held_quantity // 2),
                        confidence=0.55, rationale=f"Weak technicals (score {score}): trend {ind.trend}, RSI {ind.rsi14}. Trim half.",
                    ))
                    continue
                suggestions.append(AdvisorSuggestion(
                    symbol=ctx.symbol, action=Action.HOLD, confidence=0.5, rationale=f"No strong signal (score {score})."))
            if score >= 2:
                candidates.append((score, ctx))

        for score, ctx, qty in self._size(candidates, request.budget):
            atr = ctx.indicators.atr14 or ctx.last_price * 0.02
            suggestions.append(AdvisorSuggestion(
                symbol=ctx.symbol, action=Action.BUY, quantity=qty, confidence=min(0.4 + 0.1 * score, 0.8),
                rationale=f"Uptrend with healthy momentum (score {score}, RSI {ctx.indicators.rsi14}).",
                entry_price=ctx.last_price, stop_loss=round(ctx.last_price - 2 * atr, 2),
                target=round(ctx.last_price + 3 * atr, 2),
                horizon="2-6 weeks" if self._style.key == "swing" else "2-6 months",
            ))
        return AdvisorPlan(market_view=_market_view(request), suggestions=suggestions)

    # --- intraday ----------------------------------------------------------
    def _intraday(self, request: AdvisorRequest) -> AdvisorPlan:
        if not request.market_open:
            return AdvisorPlan(market_view="Market is closed; no intraday trades.", suggestions=[])
        candidates: list[tuple[float, SymbolContext]] = []
        for ctx in request.symbols:
            it = ctx.intraday
            if it is None or it.vwap is None or it.ema9 is None or it.ema21 is None:
                continue
            if it.last_price > it.vwap and it.ema9 > it.ema21:
                candidates.append((2.0, ctx))
            elif it.last_price < it.vwap and it.ema9 < it.ema21:
                candidates.append((-2.0, ctx))
        suggestions = []
        for score, ctx, qty in self._size([(abs(s), c) for s, c in candidates], request.budget):
            it = ctx.intraday
            long = it.last_price > it.vwap
            risk = max(abs(it.last_price - it.vwap), it.last_price * 0.004)
            suggestions.append(AdvisorSuggestion(
                symbol=ctx.symbol, action=Action.BUY if long else Action.SELL, quantity=qty, confidence=0.5,
                rationale=f"Price {'above' if long else 'below'} VWAP {it.vwap} with EMA9 {'>' if long else '<'} EMA21.",
                entry_price=it.last_price,
                stop_loss=round(it.last_price - risk if long else it.last_price + risk, 2),
                target=round(it.last_price + 2 * risk if long else it.last_price - 2 * risk, 2),
                horizon="today",
            ))
        return AdvisorPlan(market_view=_market_view(request), suggestions=suggestions)

    def _size(self, candidates: list[tuple[float, SymbolContext]], budget: float):
        picks = sorted(candidates, key=lambda t: t[0], reverse=True)[: self._max_positions]
        if not picks:
            return []
        per_pick = budget / len(picks)
        return [(score, ctx, int(per_pick // ctx.last_price)) for score, ctx in picks if per_pick >= ctx.last_price]


def _daily_score(ctx: SymbolContext) -> int:
    ind = ctx.indicators
    score = 0
    if ind.sma50:
        score += 1 if ind.last_close > ind.sma50 else -1
    if ind.sma200:
        score += 1 if ind.last_close > ind.sma200 else -1
    if ind.macd_hist is not None:
        score += 1 if ind.macd_hist > 0 else -1
    if ind.rsi14 is not None and (ind.rsi14 > 75 or ind.rsi14 < 30):
        score -= 1
    return score


def _market_view(request: AdvisorRequest) -> str:
    idx = request.market.index_indicators
    base = f"Rule-based {request.style} plan. News is not considered by this advisor."
    if idx is None:
        return base
    return f"{base} {request.market.index_name} trend: {idx.trend}, RSI {idx.rsi14}."
