"""Technical indicators — pure functions over pandas Series. No I/O."""

from __future__ import annotations

import math
from datetime import time

import pandas as pd

from app.domain.models import Candle, IndicatorSet, IntradayIndicators

MIN_CANDLES = 30
OPENING_RANGE_END = time(9, 30)  # first 15 minutes


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical = (high + low + close) / 3
    cum_vol = volume.cumsum()
    return (typical * volume).cumsum() / cum_vol.where(cum_vol != 0)


def pct_change_over(close: pd.Series, bars: int) -> float | None:
    if len(close) <= bars:
        return None
    return (close.iloc[-1] / close.iloc[-1 - bars] - 1) * 100


def classify_trend(last: float, sma50: float | None, sma200: float | None) -> str:
    if sma50 is None:
        return "unknown"
    if sma200 is None:
        return "up" if last > sma50 else "down"
    if last > sma50 > sma200:
        return "strong_up"
    if last < sma50 < sma200:
        return "strong_down"
    if last > sma200:
        return "up"
    return "down"


def _frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame([c.model_dump() for c in candles]).sort_values("ts").reset_index(drop=True)


def compute_indicators(candles: list[Candle]) -> IndicatorSet | None:
    if len(candles) < MIN_CANDLES:
        return None
    df = _frame(candles)
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    last = float(close.iloc[-1])

    macd_line, macd_sig, macd_hist = macd(close)
    s50, s200 = _last(sma(close, 50)), _last(sma(close, 200))
    window_52w = close.tail(252)
    atr_last = _last(atr(high, low, close))
    vol_avg = _last(sma(vol, 20))

    return IndicatorSet(
        last_close=_r(last),
        sma20=_r(_last(sma(close, 20))),
        sma50=_r(s50),
        sma200=_r(s200),
        ema20=_r(_last(ema(close, 20))),
        rsi14=_r(_last(rsi(close))),
        macd=_r(_last(macd_line)),
        macd_signal=_r(_last(macd_sig)),
        macd_hist=_r(_last(macd_hist)),
        atr14=_r(atr_last),
        atr14_pct=_r(atr_last / last * 100) if atr_last else None,
        return_1w_pct=_r(pct_change_over(close, 5)),
        return_1m_pct=_r(pct_change_over(close, 21)),
        return_3m_pct=_r(pct_change_over(close, 63)),
        pct_from_52w_high=_r((last / window_52w.max() - 1) * 100),
        pct_from_52w_low=_r((last / window_52w.min() - 1) * 100),
        volume_ratio_20d=_r(float(vol.iloc[-1]) / vol_avg) if vol_avg else None,
        trend=classify_trend(last, s50, s200),
    )


def compute_intraday(candles: list[Candle]) -> IntradayIndicators | None:
    """Snapshot of the latest session from 5-minute candles spanning several days."""
    if not candles:
        return None
    df = _frame(candles)
    df["day"] = df["ts"].dt.date
    days = sorted(df["day"].unique())
    today = df[df["day"] == days[-1]].reset_index(drop=True)
    prev = df[df["day"] == days[-2]] if len(days) > 1 else None

    close, high, low, vol = today["close"], today["high"], today["low"], today["volume"]
    last = float(close.iloc[-1])
    day_open = float(today["open"].iloc[0])
    opening = today[today["ts"].dt.time < OPENING_RANGE_END]
    vwap_last = _last(vwap(high, low, close, vol)) if vol.sum() > 0 else None
    full = df["close"]  # EMAs/RSI over multi-day series so they're warmed up at the open

    prev_vol = float(prev["volume"].sum()) if prev is not None else 0.0
    return IntradayIndicators(
        last_price=_r(last),
        day_open=_r(day_open),
        day_change_pct=_r((last / float(prev["close"].iloc[-1]) - 1) * 100) if prev is not None else _r((last / day_open - 1) * 100),
        vwap=_r(vwap_last),
        ema9=_r(_last(ema(full, 9))),
        ema21=_r(_last(ema(full, 21))),
        rsi14=_r(_last(rsi(full))),
        opening_range_high=_r(float(opening["high"].max())) if len(opening) else None,
        opening_range_low=_r(float(opening["low"].min())) if len(opening) else None,
        prev_day_high=_r(float(prev["high"].max())) if prev is not None else None,
        prev_day_low=_r(float(prev["low"].min())) if prev is not None else None,
        prev_day_close=_r(float(prev["close"].iloc[-1])) if prev is not None else None,
        volume_vs_prev_day_pct=_r(float(vol.sum()) / prev_vol * 100) if prev_vol else None,
        bars_today=len(today),
    )


def _last(series: pd.Series) -> float | None:
    value = series.iloc[-1] if len(series) else None
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    return float(value)


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)
