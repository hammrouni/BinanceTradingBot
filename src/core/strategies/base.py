"""base.py — Abstract base class for all trading strategies.

A Strategy encapsulates a single trading logic unit.  The BotEngine will
hold a list of active BaseStrategy instances and call them on every market
tick.  Each strategy returns a *signal* (buy / sell / hold) and the Engine
decides whether to execute a trade.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.config import TradingConfig


class Signal(str, Enum):
    BUY  = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TickContext:
    """Immutable snapshot of a single market tick passed to every strategy."""
    price: float
    rsi: float | None
    config: "TradingConfig"
    has_open_position: bool
    buy_lock_held: bool

    # RSI Ultra fields
    rsi_ultra_raw: float | None = None
    rsi_ultra_signal: float | None = None
    prev_rsi_ultra_raw: float | None = None
    prev_rsi_ultra_signal: float | None = None


@dataclass
class StrategyResult:
    """What a strategy decided to do this tick."""
    signal: Signal = Signal.HOLD
    reason: str = ""
    amount_override: float | None = None  # Used by BC mode to pass wallet amount


class BaseStrategy(ABC):
    """Abstract base class that all strategies must implement.

    To add a new strategy:
        1. Create a new file in `src/core/strategies/`.
        2. Subclass `BaseStrategy`.
        3. Implement `name`, `on_tick`, and optionally `on_reset`.
        4. Register it in `src/core/strategies/__init__.py`.
    """

    # ── Identity ────────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this strategy (e.g. 'RSI', 'BC')."""

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    def on_reset(self) -> None:
        """Called when the bot starts, resumes, or stops.  Reset any stateful
        flags here so stale signals don't bleed across sessions."""

    def seed_prices(self, prices) -> None:
        """Replace any internal price buffer with `prices` (oldest first). Default: nothing to seed."""

    @abstractmethod
    def on_tick(self, ctx: TickContext) -> StrategyResult:
        """Evaluate one market tick and return a signal.

        Args:
            ctx: Current tick context (price, RSI, config, position state).

        Returns:
            StrategyResult with signal (BUY / SELL / HOLD) and the optional
            reason string that will be recorded in the trade log.
        """
