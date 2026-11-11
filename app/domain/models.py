"""Pure domain models. No I/O, no vendor types."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, computed_field


# --- Portfolio -------------------------------------------------------------
class Holding(BaseModel):
    symbol: str
    exchange: str = "NSE"
    quantity: int
    average_price: float
    last_price: float
    day_change_pct: float = 0.0

    @computed_field
    @property
    def invested(self) -> float:
        return round(self.quantity * self.average_price, 2)

    @computed_field
    @property
    def current_value(self) -> float:
        return round(self.quantity * self.last_price, 2)

    @computed_field
    @property
    def pnl(self) -> float:
        return round(self.current_value - self.invested, 2)

    @computed_field
    @property
    def pnl_pct(self) -> float:
        return round(self.pnl / self.invested * 100, 2) if self.invested else 0.0


class PortfolioSummary(BaseModel):
    holdings: list[Holding]
    total_invested: float
    total_value: float
    total_pnl: float
    total_pnl_pct: float
    fetched_at: datetime

    @classmethod
    def from_holdings(cls, holdings: list[Holding]) -> "PortfolioSummary":
        invested = sum(h.invested for h in holdings)
        value = sum(h.current_value for h in holdings)
        pnl = value - invested
        return cls(
            holdings=sorted(holdings, key=lambda h: h.current_value, reverse=True),
            total_invested=round(invested, 2),
            total_value=round(value, 2),
            total_pnl=round(pnl, 2),
            total_pnl_pct=round(pnl / invested * 100, 2) if invested else 0.0,
            fetched_at=datetime.now(),
        )


# --- Market data -----------------------------------------------------------
class Interval(str, Enum):
    DAY = "day"
    MIN5 = "5minute"


class Candle(BaseModel):
    ts: datetime  # bar start, exchange local time (IST), naive
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class IndicatorSet(BaseModel):
    """Daily-timeframe technical snapshot, computed locally."""

    last_close: float
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    ema20: float | None = None
    rsi14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    atr14: float | None = None
    atr14_pct: float | None = None
    return_1w_pct: float | None = None
    return_1m_pct: float | None = None
    return_3m_pct: float | None = None
    pct_from_52w_high: float | None = None
    pct_from_52w_low: float | None = None
    volume_ratio_20d: float | None = None
    trend: str = "unknown"


class IntradayIndicators(BaseModel):
    """Today's 5-minute snapshot."""

    last_price: float
    day_open: float
    day_change_pct: float
    vwap: float | None = None
    ema9: float | None = None
    ema21: float | None = None
    rsi14: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    prev_day_high: float | None = None
    prev_day_low: float | None = None
    prev_day_close: float | None = None
    volume_vs_prev_day_pct: float | None = None
    bars_today: int = 0


class NewsItem(BaseModel):
    title: str
    source: str = ""
    link: str = ""
    published: datetime | None = None


class SymbolContext(BaseModel):
    symbol: str
    last_price: float | None
    held_quantity: int = 0
    average_price: float | None = None
    indicators: IndicatorSet | None = None
    intraday: IntradayIndicators | None = None
    news: list[NewsItem] = Field(default_factory=list)


class MarketContext(BaseModel):
    index_name: str
    index_indicators: IndicatorSet | None = None
    index_intraday: IntradayIndicators | None = None
    headlines: list[NewsItem] = Field(default_factory=list)


class AdvisorRequest(BaseModel):
    style: str
    budget: float
    as_of: datetime
    market_open: bool
    market: MarketContext
    symbols: list[SymbolContext]


# --- Advice ----------------------------------------------------------------
class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Product(str, Enum):
    MIS = "MIS"  # intraday
    CNC = "CNC"  # delivery


class AdvisorSuggestion(BaseModel):
    """Raw suggestion as produced by an advisor (not yet validated)."""

    symbol: str
    action: Action
    quantity: int = 0
    confidence: float = Field(0.5, ge=0, le=1)
    rationale: str = ""
    entry_price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    horizon: str | None = None


class AdvisorPlan(BaseModel):
    market_view: str = ""
    suggestions: list[AdvisorSuggestion] = Field(default_factory=list)


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    EXECUTED = "executed"
    IGNORED = "ignored"
    FAILED = "failed"


class Suggestion(BaseModel):
    """Validated, priced, actionable suggestion shown to the user."""

    id: str
    symbol: str
    action: Action
    quantity: int
    price: float
    amount: float
    confidence: float
    rationale: str
    product: Product
    entry_price: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    horizon: str | None = None
    status: SuggestionStatus = SuggestionStatus.PENDING

    @property
    def actionable(self) -> bool:
        return self.action is not Action.HOLD


class AllocationPlan(BaseModel):
    id: str
    style: str
    market_view: str
    budget: float
    suggestions: list[Suggestion]
    total_buy: float
    total_sell: float
    cash_left: float
    warnings: list[str] = Field(default_factory=list)
    advisor: str
    generated_at: datetime

    def suggestion(self, suggestion_id: str) -> Suggestion | None:
        return next((s for s in self.suggestions if s.id == suggestion_id), None)

    @property
    def actionable(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.actionable]


# --- Orders ----------------------------------------------------------------
class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"
    side: Action  # BUY or SELL
    quantity: int
    product: Product
    order_type: OrderType
    price: float | None = None


class OrderRecord(BaseModel):
    id: int
    plan_id: str
    suggestion_id: str
    symbol: str
    side: str
    quantity: int
    product: str
    order_type: str
    price: float | None
    est_amount: float
    broker_order_id: str | None
    status: str
    error: str | None
    created_at: datetime


# --- IPO -------------------------------------------------------------------
class Ipo(BaseModel):
    symbol: str
    name: str
    category: str = "Mainboard"  # Mainboard | SME
    status: str = "upcoming"      # open | upcoming | closed
    issue_start: date | None = None
    issue_end: date | None = None
    price_low: float | None = None
    price_high: float | None = None
    lot_size: int | None = None
    issue_size: str | None = None
    subscription_times: float | None = None

    @computed_field
    @property
    def min_investment(self) -> float | None:
        if self.price_high and self.lot_size:
            return round(self.price_high * self.lot_size, 2)
        return None


class IpoVerdict(str, Enum):
    APPLY = "APPLY"
    AVOID = "AVOID"
    NEUTRAL = "NEUTRAL"


class IpoAssessment(BaseModel):
    symbol: str
    verdict: IpoVerdict
    rationale: str = ""
    risks: str = ""
    suggested_lots: int = 0


class IpoAdvice(BaseModel):
    overview: str = ""
    assessments: list[IpoAssessment] = Field(default_factory=list)


class IpoReview(BaseModel):
    ipos: list[Ipo]
    overview: str
    assessments: list[IpoAssessment]
    advisor: str
    budget: float
    generated_at: datetime


# --- Notifications ---------------------------------------------------------
class Notification(BaseModel):
    title: str
    body: str
    url: str = "/"


# --- billing -------------------------------------------------------------------
class CheckoutOrder(BaseModel):
    """What we ask a payment provider to collect."""

    order_id: str
    amount_paise: int
    currency: str = "INR"
    description: str
    customer_email: str
    return_url: str


class CheckoutSession(BaseModel):
    redirect_url: str  # where the browser goes to pay
    provider_ref: str | None = None


class PaymentEvent(BaseModel):
    """A provider's verified answer about one order."""

    order_id: str
    paid: bool
    provider_ref: str | None = None


# --- email ---------------------------------------------------------------------
class EmailMessage(BaseModel):
    to: str
    subject: str
    text: str
