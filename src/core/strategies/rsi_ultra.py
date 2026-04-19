from collections import deque

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
    - Optional MA/EMA trend filters (ma_filter_period, ema_fast_period, ema_slow_period).
    """

    def __init__(self) -> None:
        self._price_history: deque[float] = deque(maxlen=1000)

    @property
    def name(self) -> str:
        return "RSI_ULTRA"

    def on_reset(self) -> None:
        pass

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

        # Guard: trade amount required for BUY
        if not ctx.config.trade_amount_usd:
            return StrategyResult(signal=Signal.HOLD, reason="no_trade_amount")

        # BUY Logic: Crossover upward in the lower zone
        # (p_raw < p_sig and raw > signal) -> Cross upward
        # (raw < ctx.config.rsi_ultra_zone_mid) -> Below midpoint filter
        if (p_raw < p_sig and raw > signal        # crossover
                and raw < ctx.config.rsi_ultra_zone_mid
                and not ctx.has_open_position
                and not ctx.buy_lock_held
                and self._is_below_ma(ctx.price, ctx.config.ma_filter_period)
                and self._is_ema_trend_valid(ctx.config.ema_fast_period, ctx.config.ema_slow_period)):
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

    # ── Filter helpers (mirrored from RSIStrategy) ───────────────────────────────

    def _is_below_ma(self, price: float, period: int | None) -> bool:
        """Return True if current price is below SMA(period). Disabled when period is None."""
        if period is None:
            return True
        if len(self._price_history) < period:
            return True
        ma = sum(list(self._price_history)[-period:]) / period
        below = price < ma
        if not below:
            logger.info("MA filter blocked buy: price %.2f >= MA(%d) %.2f", price, period, ma)
        return below

    def _is_ema_trend_valid(self, fast: int | None, slow: int | None) -> bool:
        """Return True if EMA(fast) > EMA(slow). Disabled when either period is None."""
        if fast is None or slow is None:
            return True
        if len(self._price_history) < slow:
            return True
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
        k = 2.0 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema
