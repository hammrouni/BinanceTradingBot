import asyncio
from datetime import datetime, timezone

from src.core.rsi_calculator import RsiCalculator
from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def market_processor(
    kline_queue: asyncio.Queue,
    market_update_queue: asyncio.Queue,
    rsi_calculator: RsiCalculator,
    rsi_ultra_calculator: RsiUltraCalculator,
    bot_queue: asyncio.Queue | None = None,
) -> None:
    while True:
        try:
            kline = await kline_queue.get()
            rsi = rsi_calculator.add_candle(kline)
            rsi_ultra_raw, rsi_ultra_signal = rsi_ultra_calculator.add_candle(kline)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            message = {
                "type": "market_update",
                "payload": {
                    "pair":      kline.pair if hasattr(kline, 'pair') else "BTCUSDT",
                    "price":     kline.close,
                    "open":      kline.open,
                    "high":      kline.high,
                    "low":       kline.low,
                    "rsi":       rsi,
                    "rsi_ultra_raw": rsi_ultra_raw,
                    "rsi_ultra_signal": rsi_ultra_signal,
                    "timestamp": now,
                },
                "timestamp": now,
            }
            await market_update_queue.put(message)
            if bot_queue is not None:
                await bot_queue.put(message)
            logger.debug(
                "Market update queued: price=%.2f rsi=%s",
                kline.close,
                f"{rsi:.2f}" if rsi is not None else "None",
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("market_processor error: %s", e, exc_info=True)
