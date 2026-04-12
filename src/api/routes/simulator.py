import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from src.core.simulator import run_simulation, simulate_single
from src.core.rsi_calculator import RsiCalculator, RSI_PERIOD

router = APIRouter()


class SimulationRequest(BaseModel):
    mode: str = "rsi"  # "rsi" or "bc"
    initial_balance: float = Field(default=1000.0, gt=0)
    trade_amount_usd: float = Field(default=100.0, gt=0)
    fee_pct: float = Field(default=0.1, ge=0.0, le=5.0)
    historical_days: int = Field(default=1, ge=1, le=7)
    # Optional pre-fetched market history for caching/offline use
    market_history: Optional[List[Dict[str, Any]]] = None

    # Shared exit controls
    stop_loss_range: List[float] = [0.5, 5.0, 0.5]
    take_profit_range: Optional[List[float]] = None  # Disabled by default to reduce dimensionality
    trailing_stop_range: Optional[List[float]] = None

    # RSI-specific ranges
    rsi_oversold_range: Optional[List[float]] = [20, 50, 5]
    rsi_overbought_range: Optional[List[float]] = [60, 90, 5]

    # RSI filter fixed values (not ranges — avoids combinatorial explosion)
    price_bounce_ticks: Optional[int] = Field(default=None, ge=1, le=20)
    bear_trend_candles: Optional[int] = Field(default=None, ge=3, le=500)
    bear_trend_pct: Optional[float] = Field(default=None, ge=0.1, le=20.0)

    # BC-specific ranges (offset % from reference price)
    bc_buy_offset_range: Optional[List[float]] = [1.0, 5.0, 0.5]   # % below ref price
    bc_sell_offset_range: Optional[List[float]] = [1.0, 5.0, 0.5]  # % above ref price

    @model_validator(mode="after")
    def validate_fields(self):
        # H2: trade amount must not exceed initial balance
        if self.trade_amount_usd > self.initial_balance:
            raise ValueError(
                f"trade_amount_usd ({self.trade_amount_usd}) cannot exceed initial_balance ({self.initial_balance})"
            )

        # Validate all range fields
        ranges_to_check = [
            ("stop_loss_range", self.stop_loss_range),
            ("take_profit_range", self.take_profit_range),
            ("trailing_stop_range", self.trailing_stop_range),
        ]
        if self.mode == "rsi":
            ranges_to_check += [
                ("rsi_oversold_range", self.rsi_oversold_range),
                ("rsi_overbought_range", self.rsi_overbought_range),
            ]
        elif self.mode == "bc":
            ranges_to_check += [
                ("bc_buy_offset_range", self.bc_buy_offset_range),
                ("bc_sell_offset_range", self.bc_sell_offset_range),
            ]

        for name, r in ranges_to_check:
            if r is None:
                continue
            if len(r) != 3:
                raise ValueError(f"{name}: must have exactly 3 elements [min, max, step]")
            min_v, max_v, step = r
            if step <= 0:
                raise ValueError(f"{name}: step must be > 0 (got {step})")
            if min_v > max_v:
                raise ValueError(f"{name}: min ({min_v}) must be <= max ({max_v})")

        # bear_trend requires both candles and pct
        if (self.bear_trend_candles is None) != (self.bear_trend_pct is None):
            raise ValueError("bear_trend_candles and bear_trend_pct must both be set or both be null")

        return self


async def _get_historical_data(request: Request, historical_days: int):
    """Helper to fetch historical klines from Binance."""
    from binance import AsyncClient as _AsyncClient
    from src.models.market import KlineData
    from config.settings import get_settings

    settings = get_settings()
    config = getattr(request.app.state, "config", None)
    trading_pair = config.trading_pair if config else "BTCUSDT"

    needed_points = historical_days * 1440
    fetch_hours = historical_days * 24 + 2
    fetch_limit = needed_points + RSI_PERIOD + 2

    seed_client = await _AsyncClient.create(
        api_key=settings.prod_binance_api_key,
        api_secret=settings.prod_binance_api_secret,
        testnet=False,
    )

    klines = []
    # Fetch in batches of 1000 until we have the required range
    current_start = int((datetime.now(timezone.utc).timestamp() - (historical_days * 24 * 3600)) * 1000)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    for _ in range(15): # Max 15 batches
        batch = await seed_client.get_klines(
            symbol=trading_pair,
            interval="1m",
            startTime=current_start,
            limit=1000
        )
        if not batch:
            break
        
        klines.extend(batch)
        if batch[-1][0] >= now_ms - 120000: # Within 2 mins of now
            break
        
        current_start = batch[-1][0] + 60000
        if len(klines) >= needed_points:
            break

    await seed_client.close_connection()
    if not klines:
        return []

    closed_klines = klines[:-1]
    temp_calc = RsiCalculator()

    market_history = []
    for k in closed_klines:
        kd = KlineData(
            open_time=k[0], open=float(k[1]), high=float(k[2]),
            low=float(k[3]), close=float(k[4]), volume=float(k[5]),
            close_time=k[6], is_closed=True,
        )
        rsi_val = temp_calc.add_candle(kd)
        ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if rsi_val is not None:
            market_history.append({
                "timestamp": ts,
                "rsi": round(rsi_val, 2),
                "price": float(k[4]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "volume": float(k[5]),
            })

    return market_history


@router.post("/simulator/data")
async def get_historical_data(request: Request, sim_request: SimulationRequest):
    """Load historical data for chart display (no simulation)."""
    try:
        market_history = await _get_historical_data(request, sim_request.historical_days)

        if not market_history:
            return JSONResponse(
                status_code=422,
                content={"status": "error", "message": "No market history available"},
            )

        # Sample for chart display (up to 1000 points for better resolution on 7d)
        chart_data = []
        step = max(1, len(market_history) // 1000) if len(market_history) > 1000 else 1
        for p in market_history[::step]:
            chart_data.append({
                'timestamp': p.get('timestamp'),
                'price': p.get('price'),
                'rsi': p.get('rsi'),
            })

        return {
            "status": "ok",
            "data_points": len(market_history),
            "market_history": chart_data,
            "full_market_history": market_history  # Return full resolution data for caching
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@router.post("/simulator/run")
async def run_simulator(request: Request, sim_request: SimulationRequest):
    """Run parameter simulation with grid search."""
    if sim_request.mode not in ("rsi", "bc"):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Unsupported mode: {sim_request.mode}. Use 'rsi' or 'bc'."},
        )

    bot = getattr(request.app.state, "bot_engine", None)
    if bot is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Bot engine not found"},
        )

    # Use pre-fetched market history if provided (for caching/offline use)
    if sim_request.market_history is not None:
        market_history = sim_request.market_history
    else:
        # Get historical data - either from bot's market_history or fetch fresh
        market_history = list(bot.market_history)

        # If we need more data than what's available, fetch from Binance
        needed_points = sim_request.historical_days * 1440  # minutes in a day
        if len(market_history) < needed_points:
            try:
                from binance import AsyncClient as _AsyncClient
                from src.models.market import KlineData
                from src.core.rsi_calculator import RSI_PERIOD
                from config.settings import get_settings

                settings = get_settings()
                trading_pair = getattr(request.app.state.config, "trading_pair", "BTCUSDT")

                fetch_hours = sim_request.historical_days * 24 + 2
                fetch_limit = needed_points + RSI_PERIOD + 2

                seed_client = await _AsyncClient.create(
                    api_key=settings.prod_binance_api_key,
                    api_secret=settings.prod_binance_api_secret,
                    testnet=False,
                )

                klines = []
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                current_start = int((now_ms/1000 - (sim_request.historical_days * 24 * 3600)) * 1000)
                for _ in range(15):
                    batch = await seed_client.get_klines(
                        symbol=trading_pair, interval="1m",
                        startTime=current_start, limit=1000
                    )
                    if not batch: break
                    klines.extend(batch)
                    if batch[-1][0] >= now_ms - 120000: break
                    current_start = batch[-1][0] + 60000
                    if len(klines) >= needed_points: break
                
                await seed_client.close_connection()

                if klines:
                    closed_klines = klines[:-1]
                    temp_calc = RsiCalculator()
                    from datetime import datetime, timezone

                    market_history = []
                    for k in closed_klines:
                        kd = KlineData(
                            open_time=k[0], open=float(k[1]), high=float(k[2]),
                            low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                            close_time=k[6], is_closed=True,
                        )
                        rsi_val = temp_calc.add_candle(kd)
                        ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        if rsi_val is not None:
                            market_history.append({
                                "timestamp": ts,
                                "rsi": round(rsi_val, 2),
                                "price": float(k[4]),
                                "open": float(k[1]),
                                "high": float(k[2]),
                                "low": float(k[3]),
                                "volume": float(k[5]),
                            })
            except Exception:
                # Fall back to bot's market_history if fetch fails
                market_history = list(bot.market_history)

    if not market_history:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "No market history available"},
        )

    try:
        # C2: offload CPU-bound grid search to a thread to avoid blocking the event loop
        result = await asyncio.to_thread(
            run_simulation,
            market_history=market_history,
            mode=sim_request.mode,
            initial_balance=sim_request.initial_balance,
            stop_loss_range=sim_request.stop_loss_range,
            take_profit_range=sim_request.take_profit_range,
            trade_amount_usd=sim_request.trade_amount_usd,
            fee_pct=sim_request.fee_pct,
            # RSI
            rsi_oversold_range=sim_request.rsi_oversold_range,
            rsi_overbought_range=sim_request.rsi_overbought_range,
            trailing_stop_range=sim_request.trailing_stop_range,
            price_bounce_ticks=sim_request.price_bounce_ticks,
            bear_trend_candles=sim_request.bear_trend_candles,
            bear_trend_pct=sim_request.bear_trend_pct,
            # BC
            bc_buy_offset_range=sim_request.bc_buy_offset_range,
            bc_sell_offset_range=sim_request.bc_sell_offset_range,
        )
        return result
    except ValueError as e:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": str(e)},
        )
    except Exception as e:
        # M3: return HTTP 500, not 200, on unexpected errors
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


class TradeReplayRequest(BaseModel):
    mode: str = "rsi"
    historical_days: int = Field(default=1, ge=1, le=7)
    initial_balance: float = Field(default=1000.0, gt=0)
    trade_amount_usd: float = Field(default=100.0, gt=0)
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    fee_pct: float = Field(default=0.1, ge=0.0, le=5.0)
    # RSI
    rsi_oversold: Optional[int] = None
    rsi_overbought: Optional[int] = None
    price_bounce_ticks: Optional[int] = None
    bear_trend_candles: Optional[int] = None
    bear_trend_pct: Optional[float] = None
    # BC
    bc_buy_price: Optional[float] = None
    bc_sell_price: Optional[float] = None


class RunCurrentRequest(BaseModel):
    historical_days: int = Field(default=1, ge=1, le=7)
    initial_balance: float = Field(default=1000.0, gt=0)
    fee_pct: float = Field(default=0.1, ge=0.0, le=5.0)


@router.post("/simulator/run-current")
async def run_current_config(request: Request, body: RunCurrentRequest):
    """Run a single simulation pass using the currently saved trading config."""
    bot = getattr(request.app.state, "bot_engine", None)
    config = getattr(request.app.state, "config", None)
    if bot is None or config is None:
        return JSONResponse(status_code=503, content={"status": "error", "message": "Bot not ready"})

    market_history = list(bot.market_history)
    needed_points = body.historical_days * 1440
    if len(market_history) < needed_points:
        try:
            from binance import AsyncClient as _AsyncClient
            from src.models.market import KlineData
            from config.settings import get_settings
            settings = get_settings()
            fetch_hours = body.historical_days * 24 + 2
            seed_client = await _AsyncClient.create(
                api_key=settings.prod_binance_api_key,
                api_secret=settings.prod_binance_api_secret,
                testnet=False,
            )
            klines = []
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            current_start = int((now_ms/1000 - (body.historical_days * 24 * 3600)) * 1000)
            for _ in range(15):
                batch = await seed_client.get_klines(
                    symbol=config.trading_pair, interval="1m",
                    startTime=current_start, limit=1000
                )
                if not batch: break
                klines.extend(batch)
                if batch[-1][0] >= now_ms - 120000: break
                current_start = batch[-1][0] + 60000
                if len(klines) >= needed_points: break
            
            await seed_client.close_connection()
            if klines:
                temp_calc = RsiCalculator()
                market_history = []
                for k in klines[:-1]:
                    kd = KlineData(
                        open_time=k[0], open=float(k[1]), high=float(k[2]),
                        low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                        close_time=k[6], is_closed=True,
                    )
                    rsi_val = temp_calc.add_candle(kd)
                    ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if rsi_val is not None:
                        market_history.append({
                            "timestamp": ts, "rsi": round(rsi_val, 2),
                            "price": float(k[4]), "open": float(k[1]),
                            "high": float(k[2]), "low": float(k[3]),
                        })
        except Exception as e:
            return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

    if not market_history:
        return JSONResponse(status_code=422, content={"status": "error", "message": "No market history available"})

    active_modes = getattr(config, "active_modes", ["RSI"]) or ["RSI"]
    mode = "bc" if "BC" in active_modes else "rsi"
    trade_amount = getattr(config, "trade_amount_usd", None) or 100.0
    initial_balance = max(body.initial_balance, trade_amount * 2)

    # Validate essential params are present before running
    if mode == "rsi":
        if getattr(config, "rsi_oversold", None) is None:
            return JSONResponse(status_code=422, content={
                "status": "error",
                "message": "RSI Oversold threshold is not set in your config. Set it and save before running simulation."
            })
    elif mode == "bc":
        bc_buy = getattr(config, "bc_buy_price", None) or getattr(config, "min_bc_price", None)
        bc_sell = getattr(config, "bc_sell_price", None)
        if not bc_buy or not bc_sell:
            return JSONResponse(status_code=422, content={
                "status": "error",
                "message": "BC Buy Price and BC Sell Price must both be set in your config before running simulation."
            })

    try:
        result = await asyncio.to_thread(
            simulate_single,
            market_history=market_history,
            mode=mode,
            initial_balance=initial_balance,
            trade_amount_usd=trade_amount,
            fee_pct=body.fee_pct,
            stop_loss_pct=getattr(config, "stop_loss_pct", None),
            take_profit_pct=getattr(config, "take_profit_pct", None),
            trailing_stop_pct=getattr(config, "trailing_stop_pct", None),
            rsi_oversold=getattr(config, "rsi_oversold", None),
            rsi_overbought=getattr(config, "rsi_overbought", None),
            price_bounce_ticks=getattr(config, "price_bounce_ticks", None),
            bear_trend_candles=getattr(config, "bear_trend_candles", None),
            bear_trend_pct=getattr(config, "bear_trend_pct", None),
            bc_buy_price=getattr(config, "bc_buy_price", None) or getattr(config, "min_bc_price", None),
            bc_sell_price=getattr(config, "bc_sell_price", None),
        )
        # Include the params used so the frontend can display them
        result["used_config"] = {
            "mode": mode,
            "rsi_oversold": getattr(config, "rsi_oversold", None),
            "rsi_overbought": getattr(config, "rsi_overbought", None),
            "bc_buy_price": getattr(config, "bc_buy_price", None) or getattr(config, "min_bc_price", None),
            "bc_sell_price": getattr(config, "bc_sell_price", None),
            "stop_loss_pct": getattr(config, "stop_loss_pct", None),
            "take_profit_pct": getattr(config, "take_profit_pct", None),
            "trailing_stop_pct": getattr(config, "trailing_stop_pct", None),
            "trade_amount_usd": trade_amount,
            "initial_balance": initial_balance,
            "data_points": len(market_history),
        }
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/simulator/trades")
async def get_trade_events(request: Request, replay: TradeReplayRequest):
    """Replay a single parameter set and return per-trade events for chart overlay."""
    bot = getattr(request.app.state, "bot_engine", None)
    if bot is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Bot engine not found"},
        )

    market_history = list(bot.market_history)
    needed_points = replay.historical_days * 1440

    if len(market_history) < needed_points:
        try:
            from binance import AsyncClient as _AsyncClient
            from src.models.market import KlineData
            from config.settings import get_settings

            settings = get_settings()
            trading_pair = getattr(request.app.state.config, "trading_pair", "BTCUSDT")
            fetch_hours = replay.historical_days * 24 + 2
            fetch_limit = needed_points + RSI_PERIOD + 2

            seed_client = await _AsyncClient.create(
                api_key=settings.prod_binance_api_key,
                api_secret=settings.prod_binance_api_secret,
                testnet=False,
            )
            klines = []
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            current_start = int((now_ms/1000 - (replay.historical_days * 24 * 3600)) * 1000)
            for _ in range(15):
                batch = await seed_client.get_klines(
                    symbol=trading_pair, interval="1m",
                    startTime=current_start, limit=1000
                )
                if not batch: break
                klines.extend(batch)
                if batch[-1][0] >= now_ms - 120000: break
                current_start = batch[-1][0] + 60000
                if len(klines) >= (replay.historical_days * 1440): break

            await seed_client.close_connection()

            if klines:
                closed_klines = klines[:-1]
                temp_calc = RsiCalculator()
                market_history = []
                for k in closed_klines:
                    kd = KlineData(
                        open_time=k[0], open=float(k[1]), high=float(k[2]),
                        low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                        close_time=k[6], is_closed=True,
                    )
                    rsi_val = temp_calc.add_candle(kd)
                    ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if rsi_val is not None:
                        market_history.append({
                            "timestamp": ts,
                            "rsi": round(rsi_val, 2),
                            "price": float(k[4]),
                        })
        except Exception:
            market_history = list(bot.market_history)

    if not market_history:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "No market history available"},
        )

    try:
        result = await asyncio.to_thread(
            simulate_single,
            market_history=market_history,
            mode=replay.mode,
            initial_balance=replay.initial_balance,
            trade_amount_usd=replay.trade_amount_usd,
            fee_pct=replay.fee_pct,
            stop_loss_pct=replay.stop_loss_pct,
            take_profit_pct=replay.take_profit_pct,
            trailing_stop_pct=replay.trailing_stop_pct,
            rsi_oversold=replay.rsi_oversold,
            rsi_overbought=replay.rsi_overbought,
            price_bounce_ticks=replay.price_bounce_ticks,
            bear_trend_candles=replay.bear_trend_candles,
            bear_trend_pct=replay.bear_trend_pct,
            bc_buy_price=replay.bc_buy_price,
            bc_sell_price=replay.bc_sell_price,
        )
        return result
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )
