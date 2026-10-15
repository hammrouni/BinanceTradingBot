"""filters.py — Buy-side market filters shared by the live strategies and the simulator.

All functions are pure: they take the price history (oldest first, current price last)
and the filter parameters. A filter whose parameter is None is disabled and never blocks.
When there is not yet enough history a filter does not block either.

`buy_filters_pass` additionally honours the dashboard toggles (`config.active_filters`):
a filter only applies when its toggle is on *and* its parameters are set.
"""

from __future__ import annotations

from typing import Sequence

from src.utils.logger import get_logger

logger = get_logger(__name__)

FILTER_BOUNCE = "BOUNCE"
FILTER_BEAR = "BEAR"
FILTER_MA = "MA"
FILTER_EMA_TREND = "EMA_TREND"
KNOWN_FILTERS = (FILTER_BOUNCE, FILTER_BEAR, FILTER_MA, FILTER_EMA_TREND)


def is_price_bouncing(history: Sequence[float], ticks: int | None) -> bool:
    """True if the last price is above the price `ticks` ticks earlier."""
    if ticks is None:
        return True
    if len(history) < ticks + 1:
        return True
    return history[-1] > history[-(ticks + 1)]


def is_bear_trend(history: Sequence[float], candles: int | None, pct: float | None) -> bool:
    """True if price dropped at least `pct`% over the last `candles` ticks."""
    if candles is None or pct is None:
        return False
    if len(history) < candles:
        return False
    past = history[-candles]
    current = history[-1]
    if past <= 0:
        return False
    drop = (past - current) / past * 100
    if drop >= pct:
        logger.info("Bear trend filter active: %.2f%% drop over %d ticks (%.2f → %.2f)",
                    drop, candles, past, current)
        return True
    return False


def is_below_ma(history: Sequence[float], price: float, period: int | None) -> bool:
    """True if `price` is below SMA(period)."""
    if period is None:
        return True
    if len(history) < period:
        return True
    ma = sum(history[-period:]) / period
    below = price < ma
    if not below:
        logger.info("MA filter blocked buy: price %.2f >= MA(%d) %.2f", price, period, ma)
    return below


def calc_ema(prices: Sequence[float], period: int) -> float:
    """EMA over `prices`, seeded with the SMA of the first `period` values."""
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def is_ema_trend_valid(history: Sequence[float], fast: int | None, slow: int | None) -> bool:
    """True if EMA(fast) > EMA(slow) (uptrend confirmation)."""
    if fast is None or slow is None:
        return True
    if len(history) < max(fast, slow):
        return True
    ema_fast = calc_ema(history, fast)
    ema_slow = calc_ema(history, slow)
    valid = ema_fast > ema_slow
    if not valid:
        logger.info("EMA trend filter blocked buy: EMA(%d) %.2f <= EMA(%d) %.2f",
                    fast, ema_fast, slow, ema_slow)
    return valid


def filter_enabled(config, name: str) -> bool:
    return name in (getattr(config, "active_filters", None) or [])


def buy_filters_pass(history: Sequence[float], price: float, config) -> bool:
    """Apply every toggled-on filter of `config` to `history`; False if any blocks the buy."""
    history = list(history)  # deques cannot be sliced
    if filter_enabled(config, FILTER_BOUNCE) and not is_price_bouncing(history, config.price_bounce_ticks):
        return False
    if filter_enabled(config, FILTER_BEAR) and is_bear_trend(
            history, config.bear_trend_candles, config.bear_trend_pct):
        return False
    if filter_enabled(config, FILTER_MA) and not is_below_ma(history, price, config.ma_filter_period):
        return False
    if filter_enabled(config, FILTER_EMA_TREND) and not is_ema_trend_valid(
            history, config.ema_fast_period, config.ema_slow_period):
        return False
    return True


def active_filter_params(config) -> dict:
    """Filter parameters of `config`, with every filter that is toggled off set to None.

    Used where filters are driven by plain keyword arguments (the simulator).
    """
    def pick(name: str, *fields: str) -> dict:
        on = filter_enabled(config, name)
        return {f: (getattr(config, f, None) if on else None) for f in fields}

    return {
        **pick(FILTER_BOUNCE, "price_bounce_ticks"),
        **pick(FILTER_BEAR, "bear_trend_candles", "bear_trend_pct"),
        **pick(FILTER_MA, "ma_filter_period"),
        **pick(FILTER_EMA_TREND, "ema_fast_period", "ema_slow_period"),
    }
