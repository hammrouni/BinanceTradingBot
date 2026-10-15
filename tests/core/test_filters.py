"""Shared buy filters (strategies/filters.py) on known price series."""
import pytest

from src.core.strategies import filters as f
from tests.core.conftest import make_config


def test_bounce_needs_last_price_above_the_one_n_ticks_ago():
    assert f.is_price_bouncing([10, 9, 8, 9, 10, 11], 3) is True      # 11 > 8
    assert f.is_price_bouncing([10, 11, 12, 11, 10, 9], 3) is False
    assert f.is_price_bouncing([5, 5, 5, 5], 3) is False              # flat is not a bounce


def test_bounce_does_not_block_without_enough_data_or_when_disabled():
    assert f.is_price_bouncing([1, 2], 5) is True
    assert f.is_price_bouncing([3, 2, 1], None) is True


def test_bounce_compares_distinct_prices_not_a_duplicate():
    # Regression for P1-2: with every price recorded twice, "last vs 1 tick ago" compared a price to itself.
    assert f.is_price_bouncing([100, 99, 101], 1) is True
    assert f.is_price_bouncing([100, 101, 99], 1) is False


def test_bear_trend_blocks_on_drop_over_window():
    series = [100, 99, 98, 97, 96]
    assert f.is_bear_trend(series, 5, 3.0) is True      # 100 -> 96 = 4%
    assert f.is_bear_trend(series, 5, 5.0) is False
    assert f.is_bear_trend(series, 50, 1.0) is False    # not enough data
    assert f.is_bear_trend(series, None, 1.0) is False  # disabled


def test_ma_filter_requires_price_below_sma():
    series = [10, 10, 10, 10, 6]
    assert f.is_below_ma(series, 6, 5) is True          # SMA 9.2
    assert f.is_below_ma(series, 10, 5) is False
    assert f.is_below_ma(series, 10, None) is True
    assert f.is_below_ma(series, 10, 50) is True        # warm-up: don't block


def test_ema_trend_requires_fast_above_slow():
    rising = list(range(1, 31))
    falling = list(reversed(rising))
    assert f.is_ema_trend_valid(rising, 3, 10) is True
    assert f.is_ema_trend_valid(falling, 3, 10) is False
    assert f.is_ema_trend_valid(falling, None, 10) is True
    assert f.is_ema_trend_valid(falling, 3, 100) is True


def test_calc_ema_seeds_with_sma():
    assert f.calc_ema([2, 4, 6], 3) == pytest.approx(4.0)
    assert f.calc_ema([2, 4, 6, 10], 3) == pytest.approx(10 * 0.5 + 4 * 0.5)


def test_buy_filters_apply_only_when_toggled_on():
    falling = [100, 99, 98, 97, 96, 95]
    cfg_params = dict(bear_trend_candles=5, bear_trend_pct=1.0, price_bounce_ticks=2)
    off = make_config(active_filters=[], **cfg_params)
    assert f.buy_filters_pass(falling, 95, off) is True
    only_bear = make_config(active_filters=["BEAR"], **cfg_params)
    assert f.buy_filters_pass(falling, 95, only_bear) is False
    only_bounce = make_config(active_filters=["BOUNCE"], **cfg_params)
    assert f.buy_filters_pass(falling, 95, only_bounce) is False
    rising = [95, 96, 97, 98]
    assert f.buy_filters_pass(rising, 98, only_bounce) is True


def test_ma_and_ema_toggles():
    falling = list(range(60, 0, -1))
    cfg = dict(ma_filter_period=5, ema_fast_period=3, ema_slow_period=10)
    assert f.buy_filters_pass(falling, 1, make_config(active_filters=["MA"], **cfg)) is True       # price below MA
    assert f.buy_filters_pass(falling, 1, make_config(active_filters=["EMA_TREND"], **cfg)) is False
    assert f.buy_filters_pass(falling, 1, make_config(active_filters=[], **cfg)) is True
