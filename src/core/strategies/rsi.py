"""rsi.py — RSI-based trading strategy.

Buys when RSI crosses below the oversold threshold (with optional price-bounce
and bear-trend filters) and sells when RSI crosses above the overbought level.
"""

from __future__ import annotations

from collections import deque

from src.utils.logger import get_logger
from .base import BaseStrategy, Signal, StrategyResult, TickContext

logger = get_logger(__name__)


class RSIStrategy(BaseStrategy):
    """Momentum strategy driven by the Relative Strength Index (RSI).

    Configurable parameters (all on TradingConfig):
        - rsi_oversold          : Buy trigger (RSI < threshold)
        - rsi_overbought        : Sell trigger (RSI > threshold)
        - price_bounce_ticks    : Optional – price must be ticking UP for N periods
        - bear_trend_candles    : Optional – block buy if price dropped pct% over N candles
        - bear_trend_pct        : Used together with bear_trend_candles
        - trade_amount_usd      : Must be set for RSI buys
    """

    @property
    def name(self) -> str:
        return "RSI"

    def __init__(self) -> None:
        self._last_rsi_was_oversold: bool = False
        self._last_rsi_was_overbought: bool = False
        # Market history is shared via the engine, but we keep a local copy for
        # the bounce / bear-trend helpers so this strategy is self-contained.
        self._price_history: deque[float] = deque(maxlen=1000)

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    def on_reset(self) -> None:
        self._last_rsi_was_oversold = False
        self._last_rsi_was_overbought = False

    # ── Main tick ────────────────────────────────────────────────────────────────

    def on_tick(self, ctx: TickContext) -> StrategyResult:
        config = ctx.config

        # Must be configured for RSI mode
        if config.rsi_oversold is None and config.rsi_overbought is None:
            return StrategyResult()

        rsi = ctx.rsi
        if rsi is None:
            return StrategyResult()

        # Record price for filter helpers
        self._price_history.append(ctx.price)

        is_oversold   = config.rsi_oversold  is not None and rsi < config.rsi_oversold
        is_overbought = config.rsi_overbought is not None and rsi > config.rsi_overbought

        result = StrategyResult()

        # ── BUY signal ──────────────────────────────────────────────────────────
        if (
            not ctx.has_open_position
            and not ctx.buy_lock_held
            and config.trade_amount_usd is not None
            and config.rsi_oversold is not None
            and is_oversold
            and not self._last_rsi_was_oversold
            and self._is_price_bouncing(config.price_bounce_ticks)
            and not self._is_bear_trend(config.bear_trend_candles, config.bear_trend_pct)
            and self._is_below_ma(ctx.price, config.ma_filter_period)
            and self._is_ema_trend_valid(config.ema_fast_period, config.ema_slow_period)
        ):
            logger.info("RSI Oversold signal detected (%.2f < %s)", rsi, config.rsi_oversold)
            result = StrategyResult(signal=Signal.BUY, reason="buy_signal")

        # ── SELL signal ─────────────────────────────────────────────────────────
        elif (
            ctx.has_open_position
            and config.rsi_overbought is not None
            and is_overbought
            and not self._last_rsi_was_overbought
        ):
            logger.info("RSI Overbought signal detected (%.2f > %s)", rsi, config.rsi_overbought)
            result = StrategyResult(signal=Signal.SELL, reason="signal")

        # Persist edge state for next tick
        self._last_rsi_was_oversold  = is_oversold
        self._last_rsi_was_overbought = is_overbought

        return result

    # ── Filter helpers ───────────────────────────────────────────────────────────

    def _is_price_bouncing(self, ticks: int | None) -> bool:
        """Return True if the last `ticks` prices are trending upward."""
        if ticks is None:
            return True
        if len(self._price_history) < ticks + 1:
            return True  # not enough data — don't block
        prices = list(self._price_history)[-(ticks + 1):]
        return prices[-1] > prices[0]

    def _is_bear_trend(self, candles: int | None, pct: float | None) -> bool:
        """Return True if price dropped more than `pct`% over last `candles` ticks."""
        if candles is None or pct is None:
            return False
        if len(self._price_history) < candles:
            return False
        history = list(self._price_history)
        past    = history[-candles]
        current = history[-1]
        if past <= 0:
            return False
        drop = (past - current) / past * 100
        if drop >= pct:
            logger.info(
                "Bear trend filter active: %.2f%% drop over %d ticks (%.2f → %.2f)",
                drop, candles, past, current,
            )
            return True
        return False

    def _is_below_ma(self, price: float, period: int | None) -> bool:
        """Return True if current price is below the SMA(period).
        When period is None the filter is disabled (always True)."""
        if period is None:
            return True
        if len(self._price_history) < period:
            return True  # not enough data — don't block
        prices = list(self._price_history)[-period:]
        ma = sum(prices) / period
        below = price < ma
        if not below:
            logger.info(
                "MA filter blocked buy: price %.2f >= MA(%d) %.2f",
                price, period, ma,
            )
        return below

    def _is_ema_trend_valid(self, fast: int | None, slow: int | None) -> bool:
        """Return True if EMA(fast) > EMA(slow) — uptrend confirmation.
        When either period is None the filter is disabled (always True)."""
        if fast is None or slow is None:
            return True
        if len(self._price_history) < slow:
            return True  # not enough data — don't block
        prices = list(self._price_history)
        ema_fast = self._calc_ema(prices, fast)
        ema_slow = self._calc_ema(prices, slow)
        valid = ema_fast > ema_slow
        if not valid:
            logger.info(
                "EMA trend filter blocked buy: EMA(%d) %.2f <= EMA(%d) %.2f",
                fast, ema_fast, slow, ema_slow,
            )
        return valid

    @staticmethod
    def _calc_ema(prices: list[float], period: int) -> float:
        """Compute EMA over `prices` with the given `period`."""
        k = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period  # seed with SMA
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema

    # ── Allow BotEngine to sync the shared price history ─────────────────────────

    def record_price(self, price: float) -> None:
        """Called by BotEngine to keep this strategy's price buffer current."""
        self._price_history.append(price)
