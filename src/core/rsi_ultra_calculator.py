from collections import deque
import pandas as pd
import pandas_ta as ta
from src.models.market import KlineData
from src.utils.logger import get_logger

logger = get_logger(__name__)

BUFFER_SIZE = 150

class RsiUltraCalculator:
    def __init__(self, rsi_period: int = 14, signal_period: int = 9) -> None:
        self._rsi_period = rsi_period
        self._signal_period = signal_period
        self._hlc3_buffer: deque[float] = deque(maxlen=BUFFER_SIZE)
        self._rsi_buffer: deque[float] = deque(maxlen=BUFFER_SIZE)
        self._rsi_ultra_raw: float | None = None
        self._rsi_ultra_signal: float | None = None

    def add_candle(self, kline: KlineData) -> tuple[float | None, float | None]:
        """
        Calculates RSI Ultra (HLC3-based EMA-RSI) and its signal line.
        Returns (rsi_ultra_raw, rsi_ultra_signal).
        """
        # HLC3 = (High + Low + Close) / 3
        hlc3 = (kline.high + kline.low + kline.close) / 3
        self._hlc3_buffer.append(hlc3)

        # Need enough data for RSI
        if len(self._hlc3_buffer) < self._rsi_period + 1:
            return None, None

        series = pd.Series(list(self._hlc3_buffer))
        
        # Note: pandas_ta rsi defaults to RMA. The plan specifies Ultra should be faster (EMA).
        # We try to use mamode='ema' if supported by the installed pandas_ta version.
        try:
            rsi_series = ta.rsi(series, length=self._rsi_period, mamode="ema")
        except TypeError:
            logger.warning("pandas_ta does not support mamode='ema' — falling back to RMA (less responsive)")
            rsi_series = ta.rsi(series, length=self._rsi_period)

        if rsi_series is None or rsi_series.empty:
            return None, None

        rsi_val = rsi_series.iloc[-1]
        if pd.isna(rsi_val):
            return None, None

        self._rsi_ultra_raw = float(rsi_val)
        self._rsi_buffer.append(self._rsi_ultra_raw)

        # Signal line: EMA of RSI values
        if len(self._rsi_buffer) < self._signal_period:
            return self._rsi_ultra_raw, None

        signal_series = ta.ema(pd.Series(list(self._rsi_buffer)), length=self._signal_period)
        if signal_series is None or signal_series.empty:
            return self._rsi_ultra_raw, None

        signal_val = signal_series.iloc[-1]
        self._rsi_ultra_signal = None if pd.isna(signal_val) else float(signal_val)

        return self._rsi_ultra_raw, self._rsi_ultra_signal

    def reconfigure(self, rsi_period: int, signal_period: int) -> None:
        """Change the periods and clear the buffers; callers replay candles afterwards."""
        self._rsi_period = int(rsi_period)
        self._signal_period = int(signal_period)
        self.reset()

    def reset(self) -> None:
        """Clear buffers."""
        self._hlc3_buffer.clear()
        self._rsi_buffer.clear()
        self._rsi_ultra_raw = None
        self._rsi_ultra_signal = None
        logger.info("RsiUltraCalculator buffers cleared.")

    @property
    def current_values(self) -> tuple[float | None, float | None]:
        return self._rsi_ultra_raw, self._rsi_ultra_signal
