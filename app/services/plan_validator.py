"""Turns a raw advisor plan into a safe, priced AllocationPlan.

Never trust model output: enforce universe, holdings, whole shares, stop-loss
sanity and budget here. Rules depend on the trading style.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.domain.models import Action, AdvisorPlan, AdvisorSuggestion, AllocationPlan, Suggestion, SymbolContext
from app.services.styles import TradingStyle


class PlanValidator:
    def validate(
        self, plan: AdvisorPlan, contexts: list[SymbolContext], budget: float, advisor_name: str, style: TradingStyle
    ) -> AllocationPlan:
        by_symbol = {c.symbol: c for c in contexts}
        warnings: list[str] = []
        seen: set[str] = set()
        exits: list[Suggestion] = []      # sells of held stock (don't consume budget)
        holds: list[Suggestion] = []
        consumers: list[tuple[AdvisorSuggestion, SymbolContext]] = []  # buys (+ intraday shorts)

        for s in plan.suggestions:
            ctx = by_symbol.get(s.symbol)
            if ctx is None:
                warnings.append(f"Ignored {s.action.value} {s.symbol}: not in the analysed universe")
                continue
            if s.symbol in seen:
                warnings.append(f"Ignored duplicate suggestion for {s.symbol}")
                continue
            if ctx.last_price is None or ctx.last_price <= 0:
                warnings.append(f"Ignored {s.symbol}: no current price")
                continue
            seen.add(s.symbol)

            if s.action is Action.HOLD:
                if ctx.held_quantity > 0 and not style.intraday:
                    holds.append(self._priced(s, ctx, 0, style))
                continue
            if s.quantity <= 0:
                warnings.append(f"Ignored {s.action.value} {s.symbol}: quantity must be positive")
                continue

            s = self._check_levels(s, ctx, style, warnings)
            if s is None:
                continue
            if s.action is Action.BUY or style.intraday:
                consumers.append((s, ctx))
            else:
                exit_ = self._validate_exit(s, ctx, style, warnings)
                if exit_:
                    exits.append(exit_)

        funded = self._fit_to_budget(consumers, budget, style, warnings)
        total_buy = round(sum(x.amount for x in funded if x.action is Action.BUY), 2)
        total_sell = round(sum(x.amount for x in [*exits, *funded] if x.action is Action.SELL), 2)
        spent = round(sum(x.amount for x in funded), 2)

        return AllocationPlan(
            id=uuid.uuid4().hex,
            style=style.key,
            market_view=plan.market_view,
            budget=round(budget, 2),
            suggestions=[*funded, *exits, *holds],
            total_buy=total_buy,
            total_sell=total_sell,
            cash_left=round(budget - spent, 2),
            warnings=warnings,
            advisor=advisor_name,
            generated_at=datetime.now(),
        )

    @staticmethod
    def _check_levels(
        s: AdvisorSuggestion, ctx: SymbolContext, style: TradingStyle, warnings: list[str]
    ) -> AdvisorSuggestion | None:
        ref = s.entry_price or ctx.last_price
        long = s.action is Action.BUY
        sl, target = s.stop_loss, s.target
        if sl is not None and (sl <= 0 or (sl >= ref if long else sl <= ref)):
            warnings.append(f"{s.symbol}: stop-loss {sl} is on the wrong side of {ref}; removed")
            sl = None
        if target is not None and (target <= 0 or (target <= ref if long else target >= ref)):
            warnings.append(f"{s.symbol}: target {target} is on the wrong side of {ref}; removed")
            target = None
        if style.requires_stop_loss and sl is None:
            warnings.append(f"Dropped {s.action.value} {s.symbol}: {style.label} trades need a valid stop-loss")
            return None
        return s.model_copy(update={"stop_loss": sl, "target": target})

    def _validate_exit(
        self, s: AdvisorSuggestion, ctx: SymbolContext, style: TradingStyle, warnings: list[str]
    ) -> Suggestion | None:
        if ctx.held_quantity <= 0:
            warnings.append(f"Ignored SELL {s.symbol}: not held (no shorting in {style.label})")
            return None
        qty = s.quantity
        if qty > ctx.held_quantity:
            warnings.append(f"SELL {s.symbol} reduced from {qty} to held quantity {ctx.held_quantity}")
            qty = ctx.held_quantity
        return self._priced(s, ctx, qty, style)

    def _fit_to_budget(
        self,
        requests: list[tuple[AdvisorSuggestion, SymbolContext]],
        budget: float,
        style: TradingStyle,
        warnings: list[str],
    ) -> list[Suggestion]:
        remaining = budget
        funded: list[Suggestion] = []
        for s, ctx in sorted(requests, key=lambda r: r[0].confidence, reverse=True):
            affordable = int(remaining // ctx.last_price)
            qty = min(s.quantity, affordable)
            if qty <= 0:
                warnings.append(f"Dropped {s.action.value} {s.symbol}: exceeds remaining budget")
                continue
            if qty < s.quantity:
                warnings.append(f"{s.action.value} {s.symbol} reduced from {s.quantity} to {qty} to fit budget")
            priced = self._priced(s, ctx, qty, style)
            remaining -= priced.amount
            funded.append(priced)
        return funded

    @staticmethod
    def _priced(s: AdvisorSuggestion, ctx: SymbolContext, qty: int, style: TradingStyle) -> Suggestion:
        price = float(ctx.last_price)
        return Suggestion(
            id=f"{s.symbol}-{s.action.value}",
            symbol=s.symbol, action=s.action, quantity=qty, price=round(price, 2),
            amount=round(qty * price, 2), confidence=round(s.confidence, 2), rationale=s.rationale,
            product=style.product, entry_price=s.entry_price, stop_loss=s.stop_loss, target=s.target,
            horizon=s.horizon,
        )
