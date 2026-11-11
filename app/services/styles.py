"""Trading styles (Strategy + registry).

A style decides which data is gathered, which Kite product is used, what the
advisor is asked for, how the plan is validated and how long it stays executable.
Add a style by appending a TradingStyle to STYLES.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.domain.errors import ValidationError
from app.domain.models import Product


@dataclass(frozen=True)
class TradingStyle:
    key: str
    label: str
    description: str
    product: Product
    daily_history_days: int
    intraday: bool                 # fetch 5-minute candles and allow shorts
    requires_stop_loss: bool
    max_plan_age: timedelta        # plans older than this cannot be executed
    min_auto_interval_min: int
    prompt: str


STYLES: dict[str, TradingStyle] = {s.key: s for s in (
    TradingStyle(
        key="intraday",
        label="Intraday",
        description="Same-day trades (MIS), long or short, squared off before 3:15 PM.",
        product=Product.MIS,
        daily_history_days=90,
        intraday=True,
        requires_stop_loss=True,
        max_plan_age=timedelta(minutes=15),
        min_auto_interval_min=5,
        prompt=(
            "STYLE: INTRADAY. Positions are opened and closed today (MIS product, auto-squared ~15:15 IST). "
            "Focus on the 5-minute 'intraday' block: price vs VWAP, EMA9/EMA21 cross, opening range breakout/breakdown, "
            "previous-day high/low/close as levels, intraday RSI and relative volume. Daily indicators give bias only. "
            "BUY = go long; SELL = go short (allowed even if not held) or exit a long. Every BUY/SELL MUST have "
            "entry_price, stop_loss and target with a reward:risk of at least 1.5. Size so that the loss at stop_loss "
            "is at most ~1% of the budget, and the notional (quantity x price) fits the budget. "
            "If the market is closed or momentum is unclear, recommend no trades. Do not use HOLD for intraday."
        ),
    ),
    TradingStyle(
        key="swing",
        label="Swing",
        description="Delivery trades (CNC) held for a few days to a few weeks.",
        product=Product.CNC,
        daily_history_days=365,
        intraday=False,
        requires_stop_loss=False,
        max_plan_age=timedelta(hours=6),
        min_auto_interval_min=30,
        prompt=(
            "STYLE: SWING (holding period days to a few weeks, CNC delivery). Look for pullbacks to rising averages, "
            "breakouts with volume, momentum turns (MACD/RSI), and near-term news catalysts. For each BUY give "
            "entry_price, stop_loss (e.g. below a recent swing low or ~2x ATR) and target, and set horizon. "
            "SELL only stocks that are held (no shorting). Trim/exit held positions whose setup has broken."
        ),
    ),
    TradingStyle(
        key="positional",
        label="Positional",
        description="Longer-term delivery positions held for weeks to months.",
        product=Product.CNC,
        daily_history_days=730,
        intraday=False,
        requires_stop_loss=False,
        max_plan_age=timedelta(days=1),
        min_auto_interval_min=60,
        prompt=(
            "STYLE: POSITIONAL (weeks to months, CNC delivery). Prioritise the primary trend (SMA50/SMA200), "
            "relative strength, distance from 52-week levels, and fundamental/business news. Diversify. "
            "stop_loss/target are optional; set horizon. SELL only stocks that are held (no shorting)."
        ),
    ),
)}

DEFAULT_STYLE = "swing"


def get_style(key: str) -> TradingStyle:
    try:
        return STYLES[key]
    except KeyError:
        raise ValidationError(f"Unknown trading style '{key}'. Choose one of: {', '.join(STYLES)}") from None
