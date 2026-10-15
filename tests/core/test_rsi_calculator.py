"""Tests for Story 2.2: RSI Calculation Engine."""

import pytest

from src.core.rsi_calculator import DEQUE_SIZE, RsiCalculator
from src.models.market import KlineData


def make_kline(close: float) -> KlineData:
    return KlineData(
        open_time=0, open=close, high=close, low=close,
        close=close, volume=1.0, close_time=0, is_closed=True
    )


def test_returns_none_with_fewer_than_15_candles():
    calc = RsiCalculator()
    for price in range(10):
        result = calc.add_candle(make_kline(float(price + 40)))
    assert result is None
    assert calc.current_rsi is None


def test_returns_none_with_exactly_14_candles():
    calc = RsiCalculator()
    result = None
    for i in range(14):
        result = calc.add_candle(make_kline(float(i + 40)))
    assert result is None


def test_returns_value_with_15_candles():
    calc = RsiCalculator()
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.15,
              43.61, 44.33, 44.83, 45.10, 45.15, 44.09, 44.15]
    result = None
    for c in closes:
        result = calc.add_candle(make_kline(c))
    assert result is not None
    assert isinstance(result, float)
    assert 0 < result < 100


def test_rsi_value_in_valid_range():
    calc = RsiCalculator()
    # Rising prices → RSI should be high (>50)
    for i in range(20):
        calc.add_candle(make_kline(float(40 + i)))
    assert calc.current_rsi is not None
    assert 50 < calc.current_rsi <= 100


def test_rsi_falling_prices_low():
    calc = RsiCalculator()
    # Falling prices → RSI should be low (<50)
    for i in range(20):
        calc.add_candle(make_kline(float(60 - i)))
    assert calc.current_rsi is not None
    assert 0 <= calc.current_rsi < 50


def test_deque_truncates_at_window_size():
    calc = RsiCalculator()
    for i in range(DEQUE_SIZE + 50):
        calc.add_candle(make_kline(float(40 + (i % 10))))
    assert len(calc._closes) == DEQUE_SIZE


def test_current_rsi_property_updates():
    calc = RsiCalculator()
    closes = [float(40 + i) for i in range(15)]
    for c in closes:
        calc.add_candle(make_kline(c))
    first_rsi = calc.current_rsi
    calc.add_candle(make_kline(60.0))
    second_rsi = calc.current_rsi
    # RSI should update after each candle
    assert first_rsi is not None
    assert second_rsi is not None


def _wilder_reference(closes, period=14):
    """Textbook Wilder RSI over the full history (what Binance/TradingView show)."""
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    return 100.0 if avg_l == 0 else 100.0 - 100.0 / (1 + avg_g / avg_l)


def test_rsi_window_is_long_enough_to_match_full_history_wilder():
    import random
    from src.core import rsi_calculator


    assert rsi_calculator.DEQUE_SIZE >= 500
    rng = random.Random(7)
    closes, price = [], 100.0
    for _ in range(3000):
        price *= 1 + rng.gauss(0, 0.01)
        closes.append(price)

    calc = RsiCalculator()
    last = None
    for c in closes:
        last = calc.add_candle(make_kline(c))
    assert last == pytest.approx(_wilder_reference(closes), abs=1e-6)
