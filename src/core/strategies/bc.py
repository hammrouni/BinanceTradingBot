"""bc.py — BC (Buying-Charging) trading strategy.

Buys when price reaches a fixed target and sells when price reaches a fixed sell target.
"""

from __future__ import annotations

from src.utils.logger import get_logger
from .base import BaseStrategy, Signal, StrategyResult, TickContext

logger = get_logger(__name__, quiet=True)


class BCStrategy(BaseStrategy):
    """Price-target strategy (BC Mode).

    Configurable parameters (on TradingConfig):
        - bc_buy_price          : Fixed buy target
        - bc_sell_price         : Fixed sell target
    """

    @property
    def name(self) -> str:
        return "BC"

    def __init__(self) -> None:
        self._last_bc_buy_triggered: bool = False
        self._last_bc_sell_triggered: bool = False

    def on_reset(self) -> None:
        self._last_bc_buy_triggered = False
        self._last_bc_sell_triggered = False

    def on_tick(self, ctx: TickContext) -> StrategyResult:
        config = ctx.config
        price = ctx.price

        bc_buy = getattr(config, 'bc_buy_price', None)
        bc_sell = getattr(config, 'bc_sell_price', None)

        result = StrategyResult()

        # ── BUY signal ──────────────────────────────────────────────────────────
        if (
            not ctx.has_open_position
            and not ctx.buy_lock_held
            and bc_buy is not None
            and price <= bc_buy
            and not self._last_bc_buy_triggered
        ):
            logger.info("BC Mode: price %.2f reached buy target %.2f", price, bc_buy)
            result = StrategyResult(signal=Signal.BUY, reason="bc_buy_target")

        # ── SELL signal ─────────────────────────────────────────────────────────
        elif (
            ctx.has_open_position
            and bc_sell is not None
            and price >= bc_sell
            and not self._last_bc_sell_triggered
        ):
            logger.info("BC Mode: price %.2f reached sell target %.2f", price, bc_sell)
            result = StrategyResult(signal=Signal.SELL, reason="bc_sell_target")

        # Update triggers for next tick to avoid multiple signals for same target crossing
        self._last_bc_buy_triggered = bc_buy is not None and price <= bc_buy
        self._last_bc_sell_triggered = bc_sell is not None and price >= bc_sell

        return result
