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
    """

    @property
    def name(self) -> str:
        return "RSI_ULTRA"

    def on_tick(self, ctx: TickContext) -> StrategyResult:
        raw = ctx.rsi_ultra_raw      # current RSI Ultra value
        signal = ctx.rsi_ultra_signal   # current signal line (EMA of RSI)
        p_raw = ctx.prev_rsi_ultra_raw    # previous RSI Ultra value
        p_sig = ctx.prev_rsi_ultra_signal # previous signal line value

        # Guard: not enough data yet
        if any(v is None for v in [raw, signal, p_raw, p_sig]):
            return StrategyResult(signal=Signal.HOLD, reason="rsi_ultra_warming_up")

        # Guard: trade amount required for BUY
        if not ctx.config.trade_amount_usd:
            return StrategyResult(signal=Signal.HOLD, reason="no_trade_amount")

        # BUY Logic: Crossover upward in the lower zone
        # (p_raw < p_sig and raw > signal) -> Cross upward
        # (raw < ctx.config.rsi_ultra_zone_mid) -> Below midpoint filter
        if (p_raw < p_sig and raw > signal        # crossover
                and raw < ctx.config.rsi_ultra_zone_mid
                and not ctx.has_open_position
                and not ctx.buy_lock_held):
            return StrategyResult(
                signal=Signal.BUY, 
                reason=f"rsi_ultra_buy_cross@{raw:.1f}"
            )

        # SELL Logic: Crossover downward in the upper zone
        # (p_raw > p_sig and raw < signal) -> Cross downward
        # (raw > ctx.config.rsi_ultra_zone_mid) -> Above midpoint filter
        if (p_raw > p_sig and raw < signal         # crossdown
                and raw > ctx.config.rsi_ultra_zone_mid
                and ctx.has_open_position):
            return StrategyResult(
                signal=Signal.SELL, 
                reason=f"rsi_ultra_sell_cross@{raw:.1f}"
            )

        return StrategyResult(signal=Signal.HOLD, reason="rsi_ultra_no_signal")

    def on_reset(self) -> None:
        """Stateless strategy — history is handled by RsiUltraCalculator."""
        pass
