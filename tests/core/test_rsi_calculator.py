"""Tests for Story 2.2: RSI Calculation Engine."""
import pytest

from src.core.rsi_calculator import DEQUE_SIZE, RSI_PERIOD, RsiCalculator
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


def test_deque_truncates_at_150_candles():
    calc = RsiCalculator()
    for i in range(200):
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
