from collections import deque

import pandas as pd
import pandas_ta as ta

from src.models.market import KlineData
from src.utils.logger import get_logger

logger = get_logger(__name__)

RSI_PERIOD = 14
DEQUE_SIZE = 150


class RsiCalculator:
    def __init__(self) -> None:
        self._closes: deque[float] = deque(maxlen=DEQUE_SIZE)
        self._current_rsi: float | None = None

    def seed(self, closes: list[float]) -> None:
        """Pre-populate with historical closes so RSI is available immediately on startup."""
        for c in closes:
            self._closes.append(c)
        logger.info("RSI seeded with %d historical closes", len(closes))

    def add_candle(self, kline: KlineData) -> float | None:
        self._closes.append(kline.close)
        if len(self._closes) < RSI_PERIOD + 1:
            return None
        series = pd.Series(list(self._closes))
        rsi_series = ta.rsi(series, length=RSI_PERIOD)
        if rsi_series is None or rsi_series.empty:
            return None
        last_val = rsi_series.iloc[-1]
        if pd.isna(last_val):
            return None
        self._current_rsi = float(last_val)
        logger.info("RSI calculated: %.2f (%d candles)", self._current_rsi, len(self._closes))
        return self._current_rsi

    @property
    def current_rsi(self) -> float | None:
        return self._current_rsi
