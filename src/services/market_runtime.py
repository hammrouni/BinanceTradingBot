"""market_runtime.py — Keeps the live market feed consistent with the trading config.

Owns the pieces that depend on the trading pair and the RSI Ultra periods:
the kline stream, the RSI / RSI Ultra calculators, the engine's candle history and the
strategies' price buffers. The config route calls it when the pair or the Ultra periods change.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable

from src.core.rsi_calculator import RsiCalculator
from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.models.config import TradingConfig
from src.models.market import KlineData
from src.utils.logger import get_logger

logger = get_logger(__name__)

# How many seeded closes are handed to the strategies' filter buffers.
STRATEGY_PRICE_SEED = 300

FetchKlines = Callable[[str], Awaitable[list]]


def make_prod_kline_fetcher(settings) -> FetchKlines:
    """Fetcher for the last 25 hours of 1m klines of a symbol from Binance production (market data only)."""

    async def fetch(symbol: str) -> list:
        from binance import AsyncClient

        client = await AsyncClient.create(
            api_key=settings.prod_binance_api_key,
            api_secret=settings.prod_binance_api_secret,
            testnet=False,
        )
        try:
            return await client.get_historical_klines(
                symbol=symbol, interval="1m", start_str="25 hours ago UTC")
        finally:
            await client.close_connection()

    return fetch


def _kline_from_row(k: list) -> KlineData:
    return KlineData(
        open_time=k[0], open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
        volume=float(k[5]), close_time=k[6], is_closed=True,
    )


class MarketRuntime:
    def __init__(
        self,
        engine,
        rsi_calc: RsiCalculator,
        ultra_calc: RsiUltraCalculator,
        stream,
        kline_queue: asyncio.Queue,
        fetch_klines: FetchKlines,
        other_queues: Iterable[asyncio.Queue] = (),
    ) -> None:
        self._engine = engine
        self._rsi_calc = rsi_calc
        self._ultra_calc = ultra_calc
        self._stream = stream
        self._queues = [kline_queue, *other_queues]
        self._fetch = fetch_klines

    async def seed(self, config: TradingConfig) -> int:
        """Fetch history for config.trading_pair and (re)seed calculators, candle history and strategies."""
        klines = await self._fetch(config.trading_pair)
        return self._apply(klines, config)

    async def change_pair(self, config: TradingConfig) -> int:
        """Switch the whole market feed to config.trading_pair.

        The history is fetched first: if that fails nothing has changed. After the await everything
        runs synchronously, so no kline of the old pair can be processed in between.
        """
        klines = await self._fetch(config.trading_pair)
        for q in self._queues:
            while not q.empty():
                q.get_nowait()
        self._stream.set_symbol(config.trading_pair)
        count = self._apply(klines, config)
        logger.info("Market feed switched to %s (%d candles seeded)", config.trading_pair, count)
        return count

    def reconfigure_ultra(self, config: TradingConfig) -> bool:
        """Rebuild the RSI Ultra calculator when its periods changed and recompute the stored history.

        Returns True when something changed.
        """
        period, signal = config.rsi_ultra_period, config.rsi_ultra_signal_period
        if (self._ultra_calc._rsi_period, self._ultra_calc._signal_period) == (period, signal):
            return False
        self._ultra_calc.reconfigure(period, signal)
        for row in self._engine.market_history:
            price = row["price"]
            raw, sig = self._ultra_calc.add_candle(KlineData(
                open_time=0, open=row.get("open", price), high=row.get("high", price),
                low=row.get("low", price), close=price, volume=0.0, close_time=0, is_closed=True))
            row["rsi_ultra_raw"] = raw
            row["rsi_ultra_signal"] = sig
        self._engine.reset_ultra_state()
        logger.info("RSI Ultra reconfigured: period=%d signal=%d (%d candles replayed)",
                    period, signal, len(self._engine.market_history))
        return True

    # ── internals ────────────────────────────────────────────────────────────────

    def _apply(self, klines: list, config: TradingConfig) -> int:
        closed = klines[:-1]  # the last kline is the current, unclosed candle
        self._ultra_calc.reconfigure(config.rsi_ultra_period, config.rsi_ultra_signal_period)
        self._rsi_calc.reset()

        history = []
        for k in closed:
            kd = _kline_from_row(k)
            rsi_val = self._rsi_calc.add_candle(kd)
            ultra_raw, ultra_sig = self._ultra_calc.add_candle(kd)
            if rsi_val is None:
                continue
            history.append({
                "timestamp": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rsi": round(rsi_val, 2),
                "rsi_ultra_raw": round(ultra_raw, 2) if ultra_raw is not None else None,
                "rsi_ultra_signal": round(ultra_sig, 2) if ultra_sig is not None else None,
                "price": kd.close, "open": kd.open, "high": kd.high, "low": kd.low,
            })

        closes = [float(k[4]) for k in closed]
        self._engine.reset_market_data(history, closes[-STRATEGY_PRICE_SEED:])
        return len(history)
