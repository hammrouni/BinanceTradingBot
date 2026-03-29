import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from config.settings import get_settings
from src.api.routes import status
from src.api.routes.bot import router as bot_router
from src.api.routes.config import router as config_router
from src.api.routes.market import router as market_router
from src.api.routes.trades import router as trades_router
from src.api.websocket import manager, ws_broadcaster
from src.core.bot_engine import BotEngine
from src.core.config_manager import load_config
from src.core.market_processor import market_processor
from src.core.rsi_calculator import RsiCalculator
from src.services.binance_client import BinanceClient
from src.services.data_stream import DataStream
from src.utils.logger import get_logger, setup_logging

settings = get_settings()
setup_logging(
    api_key=settings.prod_binance_api_key,
    api_secret=settings.prod_binance_api_secret,
)
logger = get_logger(__name__)

# Shared queues - bounded to prevent memory leaks under sustained load
kline_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
market_update_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
bot_queue: asyncio.Queue = asyncio.Queue(maxsize=100)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate Binance connection
    client = BinanceClient(settings)
    try:
        await client.connect()
        ok = await client.validate_connection()
        if ok:
            logger.info("Connected to Binance: Data (PROD) & Trading (%s)", settings.trading_env.upper())
        else:
            logger.warning("WARNING: Binance connection failed — could not validate accounts")
    except Exception as e:
        logger.warning("WARNING: Binance connection failed — %s", e)
    finally:
        await client.close()

    # Create a shared client for the bot engine
    bot_client = BinanceClient(settings)
    await bot_client.connect()

    # Load trading config and initialize bot engine
    app.state.config = load_config()
    app.state.settings = settings
    app.state.binance_client = bot_client
    app.state.bot_engine = BotEngine(broadcaster=manager)

    # Start background tasks
    rsi_calc = RsiCalculator()
    stream = DataStream()

    # Get trading pair from config - this is the authoritative source
    trading_pair = app.state.config.trading_pair

    # Pre-seed RSI with historical klines so chart is ready immediately (no 15-min wait)
    app.state.rsi_history = []
    try:
        from binance import AsyncClient as _AsyncClient
        from src.models.market import KlineData
        from src.core.rsi_calculator import RSI_PERIOD

        _CHART_POINTS = 1440  # 1-min intervals = 24 hours
        _fetch_limit = _CHART_POINTS + RSI_PERIOD + 2

        seed_client = await _AsyncClient.create(
            api_key=settings.prod_binance_api_key,
            api_secret=settings.prod_binance_api_secret,
            testnet=False,
        )
        
        # Pull 25 hours ago — this automatically handles pagination if it's over 1000 candles
        klines = await seed_client.get_historical_klines(
            symbol=trading_pair, interval="1m", start_str="25 hours ago UTC"
        )
        await seed_client.close_connection()

        # Exclude the last entry — it's the current (unclosed) candle
        closed_klines = klines[:-1]

        # Compute RSI for each historical kline using a temp calculator
        temp_calc = RsiCalculator()
        rsi_history = []
        for k in closed_klines:
            kd = KlineData(
                open_time=k[0], open=float(k[1]), high=float(k[2]),
                low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                close_time=k[6], is_closed=True,
            )
            rsi_val = temp_calc.add_candle(kd)
            ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if rsi_val is not None:
                rsi_history.append({
                    "timestamp": ts,
                    "rsi":   round(rsi_val, 2),
                    "price": float(k[4]),   # close
                    "open":  float(k[1]),
                    "high":  float(k[2]),
                    "low":   float(k[3]),
                })

        if hasattr(app.state.bot_engine, "market_history"):
            app.state.bot_engine.market_history.extend(rsi_history)

        # Also seed the live calculator with all closed closes so RSI continues without gap
        rsi_calc.seed([float(k[4]) for k in closed_klines])
        
        # Initial balance fetch for the UI
        await app.state.bot_engine.update_balances(bot_client, trading_pair)
        await app.state.bot_engine.reconcile_open_position(bot_client, trading_pair)
        await app.state.bot_engine.update_balances(bot_client, trading_pair)
        
        logger.info("RSI history ready: %d points", len(rsi_history))
    except Exception as e:
        logger.warning("Could not pre-seed RSI history: %s", e)
    
    # bot_client is already initialized and shared via app.state.binance_client
    
    async def process_bot_updates(queue, bot_engine, client, app_ref):
        """Process market updates and feed them to the bot engine."""
        while True:
            try:
                message = await queue.get()
                # Get current config at runtime to pick up any changes
                config = app_ref.state.config
                await bot_engine.process_market_update(
                    rsi=message["payload"]["rsi"],
                    price=message["payload"]["price"],
                    binance_client=client,
                    config=config,
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Bot update processing error: %s", e)
    
    tasks = [
        asyncio.create_task(stream.start(settings, kline_queue, manager, app.state.bot_engine)),
        asyncio.create_task(market_processor(kline_queue, market_update_queue, rsi_calc, bot_queue)),
        asyncio.create_task(ws_broadcaster(market_update_queue)),
        asyncio.create_task(process_bot_updates(bot_queue, app.state.bot_engine, bot_client, app)),
    ]

    yield

    # Shutdown
    stream.stop()
    await bot_client.close()
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="BinanceTradingBot", lifespan=lifespan)


@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Push current bot state immediately so the client doesn't have to wait
    bot = getattr(websocket.app.state, "bot_engine", None)
    if bot:
        await bot._broadcast_state()

    # Push RSI history so the chart is pre-populated on connect
    if bot:
        # deque to list for JSON
        history = list(bot.market_history)
        if history:
            await websocket.send_text(json.dumps({
                "type": "rsi_history",
                "payload": history,
            }))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# REST routes
app.include_router(status.router, prefix="/api/v1")
app.include_router(bot_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(trades_router, prefix="/api/v1")

# Static files LAST
app.mount("/", StaticFiles(directory="static", html=True), name="static")
