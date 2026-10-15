from collections import deque

from src.core.strategies.filters import buy_filters_pass
from src.core.strategies.base import BaseStrategy, Signal, StrategyResult, TickContext
from src.utils.logger import get_logger

logger = get_logger(__name__)

class RsiUltraStrategy(BaseStrategy):
    """
    RSI Ultra Strategy:
    - Fast crossover strategy using EMA-smoothed RSI and an EMA signal line.
    - Uses HLC3 (High + Low + Close / 3) instead of just Close.
    - BUY when RSI Ultra crosses ABOVE its Signal line AND is below a midpoint (e.g. 50).
    - SELL when RSI Ultra crosses BELOW its Signal line AND is above a midpoint (e.g. 50).
    - Optional buy filters from `active_filters` (BOUNCE, BEAR, MA, EMA_TREND), see filters.py.
    """

    def __init__(self) -> None:
        self._price_history: deque[float] = deque(maxlen=1000)
        # Direction of the last crossover this strategy signalled ("up" / "down" / None), so the
        # same cross is never signalled twice; the opposite cross (or a reset) re-arms it.
        self._last_cross: str | None = None

    @property
    def name(self) -> str:
        return "RSI_ULTRA"

    def on_reset(self) -> None:
        # The price history is kept on purpose: the MA/EMA filters need it to stay warm.
        self._last_cross = None

    def record_price(self, price: float) -> None:
        """Called by BotEngine each tick to keep price history current."""
        self._price_history.append(price)

    def on_tick(self, ctx: TickContext) -> StrategyResult:
        raw = ctx.rsi_ultra_raw      # current RSI Ultra value
        signal = ctx.rsi_ultra_signal   # current signal line (EMA of RSI)
        p_raw = ctx.prev_rsi_ultra_raw    # previous RSI Ultra value
        p_sig = ctx.prev_rsi_ultra_signal # previous signal line value

        # Guard: not enough data yet
        if any(v is None for v in [raw, signal, p_raw, p_sig]):
            return StrategyResult(signal=Signal.HOLD, reason="rsi_ultra_warming_up")

        cross = "up" if (p_raw < p_sig and raw > signal) else "down" if (p_raw > p_sig and raw < signal) else None
        repeated = cross is not None and cross == self._last_cross
        if cross is not None:
            self._last_cross = cross

        mid = ctx.config.rsi_ultra_zone_mid

        # SELL first: closing a position needs no trade amount.
        # Crossover downward in the upper zone.
        if cross == "down" and not repeated and raw > mid and ctx.has_open_position:
            return StrategyResult(signal=Signal.SELL, reason=f"rsi_ultra_sell_cross@{raw:.1f}")

        # Guard: trade amount required for BUY
        if not ctx.config.trade_amount_usd:
            return StrategyResult(signal=Signal.HOLD, reason="no_trade_amount")

        # BUY: crossover upward in the lower zone
        if (cross == "up" and not repeated
                and raw < mid
                and not ctx.has_open_position
                and not ctx.buy_lock_held
                and buy_filters_pass(self._price_history, ctx.price, ctx.config)):
            return StrategyResult(signal=Signal.BUY, reason=f"rsi_ultra_buy_cross@{raw:.1f}")

        return StrategyResult(signal=Signal.HOLD, reason="rsi_ultra_no_signal")
