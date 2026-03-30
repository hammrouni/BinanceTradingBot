import asyncio
import logging

from binance import AsyncClient, BinanceSocketManager

from src.models.market import KlineData
from src.utils.logger import get_logger

logger = get_logger(__name__)

SYMBOL = "BTCUSDT"
INTERVAL = "1m"

WS_RECV_TIMEOUT = 90.0          # seconds — detect stale connections (increased for 1m interval)
WS_INITIAL_RECONNECT_DELAY = 2  # seconds
WS_MAX_RECONNECT_DELAY = 30     # seconds


class DataStream:
    def __init__(self) -> None:
        self._running = False

    async def start(
        self,
        settings,
        queue: asyncio.Queue,
        broadcaster=None,
        bot_engine=None,
    ) -> None:
        self._running = True
        # Get trading pair - use settings initially, config changes require restart
        symbol = getattr(settings, 'trading_pair', None) or "BTCUSDT"
        attempt = 0
        first_connect = True
        while self._running:
            client = None
            try:
                # Use live WebSocket for market data (testnet WS doesn't have real-time data)
                # Trading still uses testnet via BinanceClient
                client = await AsyncClient.create(
                    api_key=settings.prod_binance_api_key,
                    api_secret=settings.prod_binance_api_secret,
                    testnet=False,  # Always use live WebSocket for market data
                )
                bm = BinanceSocketManager(client)
                async with bm.kline_socket(symbol=symbol, interval=INTERVAL) as stream:
                    attempt = 0  # reset on successful connect
                    if first_connect:
                        logger.info("Connecting to Binance kline stream: %s", symbol)
                        first_connect = False
                    else:
                        logger.info("Binance WebSocket reconnected")
                        if broadcaster and bot_engine:
                            from datetime import datetime, timezone
                            await broadcaster.broadcast({
                                "type": "bot_status",
                                "payload": {"state": bot_engine.state.value},
                                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            })
                    while self._running:
                        msg = await asyncio.wait_for(stream.recv(), timeout=WS_RECV_TIMEOUT)
                        if msg is None:
                            break
                        kline = self._parse_kline(msg)
                        if not kline:
                            continue

                        # Real-time UI update: broadcast every tick (every ~2s)
                        if broadcaster:
                            from datetime import datetime, timezone
                            await broadcaster.broadcast({
                                "type": "market_update",
                                "payload": {
                                    "price": kline.close,
                                    "rsi": None,  # RSI only updates on closed klines
                                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                },
                                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            })

                        # Trading logic: only process closed klines for RSI and orders
                        if kline.is_closed:
                            await queue.put(kline)
                            logger.debug("Kline closed: close=%.2f", kline.close)
            except asyncio.CancelledError:
                self._running = False
                raise
            except Exception as e:
                first_connect = False  # next successful connect is a reconnect
                delay = min(WS_INITIAL_RECONNECT_DELAY * (2 ** attempt), WS_MAX_RECONNECT_DELAY)
                logger.warning(
                    "Binance WS disconnected (%s). Reconnecting in %ss (attempt %d)",
                    type(e).__name__, delay, attempt + 1,
                )
                await asyncio.sleep(delay)
                attempt += 1
            finally:
                if client:
                    try:
                        await client.close_connection()
                    except Exception as e:
                        logger.debug("Failed to close data stream client: %s", e)

    def _parse_kline(self, msg: dict) -> KlineData | None:
        try:
            k = msg["k"]
            return KlineData(
                open_time=k["t"],
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
                close_time=k["T"],
                is_closed=k["x"],
            )
        except (KeyError, ValueError, TypeError):
            return None

    def stop(self) -> None:
        self._running = False
