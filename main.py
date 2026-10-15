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
from src.api.routes.logs import router as logs_router
from src.api.routes.simulator import router as simulator_router
from src.api.routes.agent import router as agent_router
from src.api.routes.chat import router as chat_router
from src.mcp_server.server import mcp
from src.mcp_server.tools import bind_app
from src.api.auth import DashboardTokenMiddleware
from src.api.websocket import manager, ws_broadcaster
from src.core.bot_engine import BotEngine
from src.core.config_manager import load_config
from src.core.market_processor import market_processor
from src.core.rsi_calculator import RsiCalculator
from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.services.binance_client import BinanceClient
from src.services.data_stream import DataStream
from src.services.market_runtime import MarketRuntime, make_prod_kline_fetcher
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
    connection_ok = False
    try:
        await bot_client.connect()
        connection_ok = True
        logger.info("Bot client connected to Binance")
    except Exception as e:
        logger.warning("Bot client could not connect to Binance on startup: %s. Will retry in background.", e)

    # Load trading config and initialize bot engine
    app.state.config = load_config()
    app.state.settings = settings
    app.state.binance_client = bot_client
    app.state.bot_engine = BotEngine(
        broadcaster=manager,
        restore_running=settings.restore_running_on_restart,
    )
    app.state.bot_engine.set_binance_client(bot_client)
    app.state.bot_engine.set_config(app.state.config)

    # Start background task objects
    config = app.state.config
    rsi_calc = RsiCalculator()
    rsi_ultra_calc = RsiUltraCalculator(config.rsi_ultra_period, config.rsi_ultra_signal_period)
    stream = DataStream()
    runtime = MarketRuntime(
        engine=app.state.bot_engine,
        rsi_calc=rsi_calc,
        ultra_calc=rsi_ultra_calc,
        stream=stream,
        kline_queue=kline_queue,
        fetch_klines=make_prod_kline_fetcher(settings),
        other_queues=(bot_queue, market_update_queue),
    )
    app.state.market_runtime = runtime

    # Pre-seed RSI/history for the configured pair and balances only if connection is alive
    if connection_ok:
        try:
            count = await runtime.seed(config)
            # Initial balance fetch for the UI
            await app.state.bot_engine.update_balances(config.trading_pair, config)
            logger.info("RSI history ready: %d points", count)
        except Exception as e:
            logger.warning("Could not pre-seed RSI history: %s", e)
    else:
        logger.info("Skipping RSI pre-seeding and balance fetch (no Binance connection)")

    async def process_bot_updates(queue, bot_engine, app_ref):
        """Process market updates and feed them to the bot engine."""
        while True:
            try:
                message = await queue.get()
                # Get current config at runtime to pick up any changes
                config = app_ref.state.config
                await bot_engine.process_market_update(
                    rsi=message["payload"]["rsi"],
                    rsi_ultra_raw=message["payload"].get("rsi_ultra_raw"),
                    rsi_ultra_signal=message["payload"].get("rsi_ultra_signal"),
                    price=message["payload"]["price"],
                    config=config,
                    open=message["payload"].get("open"),
                    high=message["payload"].get("high"),
                    low=message["payload"].get("low"),
                    open_time=message["payload"].get("open_time"),
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Bot update processing error: %s", e)
    
    tasks = [
        asyncio.create_task(stream.start(settings, kline_queue, manager, app.state.bot_engine,
                            symbol=config.trading_pair)),
        asyncio.create_task(market_processor(kline_queue, market_update_queue, rsi_calc, rsi_ultra_calc, bot_queue,
                                             pair_getter=lambda: app.state.config.trading_pair)),
        asyncio.create_task(ws_broadcaster(market_update_queue)),
        asyncio.create_task(process_bot_updates(bot_queue, app.state.bot_engine, app)),
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
app.add_middleware(DashboardTokenMiddleware)


@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Push current bot state immediately so the client doesn't have to wait
    bot = getattr(websocket.app.state, "bot_engine", None)
    if bot:
        # Trigger an initial balance refresh so F5 shows current Binance data
        # We wrap this in a task so we don't block the initial connection but ensure it happens
        asyncio.create_task(bot.update_balances(
            websocket.app.state.config.trading_pair,
            websocket.app.state.config,
        ))
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
app.include_router(logs_router, prefix="/api/v1")
app.include_router(simulator_router, prefix="/api/v1")
app.include_router(market_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")

# MCP server — SSE transport for external clients (e.g. Claude Desktop)
# Connect at: http://localhost:8000/mcp/sse
bind_app(app)
app.mount("/mcp", mcp.sse_app())

# Static files LAST
app.mount("/", StaticFiles(directory="static", html=True), name="static")
