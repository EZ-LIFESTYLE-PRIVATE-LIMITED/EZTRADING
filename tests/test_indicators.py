import pandas as pd
import pytest

from app.services.indicators import classify_trend, compute_indicators, compute_intraday, macd, rsi, sma, vwap
from tests.fakes import make_candles, make_intraday


def test_sma_known_values():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert pd.isna(sma(s, 3).iloc[1])


def test_rsi_extremes_and_bounds():
    assert rsi(pd.Series(range(1, 40), dtype=float)).iloc[-1] == pytest.approx(100.0)
    assert rsi(pd.Series(range(40, 0, -1), dtype=float)).iloc[-1] == pytest.approx(0.0)
    values = rsi(pd.Series([c.close for c in make_candles()])).dropna()
    assert ((values >= 0) & (values <= 100)).all()


def test_macd_hist_is_line_minus_signal():
    s = pd.Series([c.close for c in make_candles()])
    line, sig, hist = macd(s)
    assert (hist - (line - sig)).abs().max() < 1e-9


def test_vwap_equal_volume_is_mean_typical_price():
    h, l, c, v = (pd.Series(x, dtype=float) for x in ([3, 5], [1, 3], [2, 4], [10, 10]))
    assert vwap(h, l, c, v).iloc[-1] == pytest.approx(3.0)


@pytest.mark.parametrize(
    "last,s50,s200,expected",
    [(110, 105, 100, "strong_up"), (90, 95, 100, "strong_down"), (102, 105, 100, "up"),
     (98, 95, 100, "down"), (100, None, None, "unknown"), (101, 100, None, "up")],
)
def test_classify_trend(last, s50, s200, expected):
    assert classify_trend(last, s50, s200) == expected


def test_compute_indicators_uptrend():
    ind = compute_indicators(make_candles())
    assert ind.trend == "strong_up"
    assert ind.atr14 > 0
    assert ind.pct_from_52w_high <= 0 <= ind.pct_from_52w_low
    assert compute_indicators(make_candles(10)) is None


def test_compute_intraday_uses_latest_session_and_previous_day():
    bars = make_intraday(days=2)
    it = compute_intraday(bars)
    today = [b for b in bars if b.ts.date() == bars[-1].ts.date()]
    yesterday = [b for b in bars if b.ts.date() != bars[-1].ts.date()]
    assert it.bars_today == len(today)
    assert it.day_open == round(today[0].open, 2)
    assert it.prev_day_close == round(yesterday[-1].close, 2)
    assert it.opening_range_high == round(max(b.high for b in today[:3]), 2)
    assert it.last_price > it.vwap  # steadily rising series
    assert it.ema9 > it.ema21
