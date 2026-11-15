"""rsi.py — RSI-based trading strategy.

Buys when RSI crosses below the oversold threshold (with optional price-bounce
and bear-trend filters) and sells when RSI crosses above the overbought level.
"""

from __future__ import annotations

from collections import deque

from src.utils.logger import get_logger
from .filters import buy_filters_pass
from .base import BaseStrategy, Signal, StrategyResult, TickContext

logger = get_logger(__name__, quiet=True)


class RSIStrategy(BaseStrategy):
    """Momentum strategy driven by the Relative Strength Index (RSI).

    Configurable parameters (all on TradingConfig):
        - rsi_oversold          : Buy trigger (RSI < threshold)
        - rsi_overbought        : Sell trigger (RSI > threshold)
        - active_filters        : Which buy filters apply (BOUNCE, BEAR, MA, EMA_TREND); see filters.py
        - price_bounce_ticks    : BOUNCE – price must be ticking UP for N periods
        - bear_trend_candles    : BEAR – block buy if price dropped pct% over N candles
        - bear_trend_pct        : Used together with bear_trend_candles
        - trade_amount_usd      : Must be set for RSI buys
    """

    @property
    def name(self) -> str:
        return "RSI"

    def __init__(self) -> None:
        self._last_rsi_was_oversold: bool = False
        self._last_rsi_was_overbought: bool = False
        # Fed once per tick by BotEngine through record_price() (on_tick never appends).
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
            and buy_filters_pass(self._price_history, ctx.price, config)
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

    # ── Allow BotEngine to sync the shared price history ─────────────────────────

    def seed_prices(self, prices) -> None:
        self._price_history.clear()
        self._price_history.extend(prices)

    def record_price(self, price: float) -> None:
        """Called by BotEngine to keep this strategy's price buffer current."""
        self._price_history.append(price)
