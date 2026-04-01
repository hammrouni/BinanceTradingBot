import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List

from src.core.simulator import run_simulation
from src.core.rsi_calculator import RsiCalculator, RSI_PERIOD

router = APIRouter()


class SimulationRequest(BaseModel):
    mode: str = "rsi"
    initial_balance: float = Field(default=1000.0, gt=0)
    trade_amount_usd: float = Field(default=100.0, gt=0)
    rsi_oversold_range: Optional[List[float]] = [20, 50, 5]
    rsi_overbought_range: Optional[List[float]] = [60, 90, 5]
    stop_loss_range: List[float] = [0.5, 5.0, 0.5]
    take_profit_range: Optional[List[float]] = [0.3, 3.0, 0.3]
    historical_days: int = Field(default=1, ge=1, le=7)

    @model_validator(mode="after")
    def validate_fields(self):
        # H2: trade amount must not exceed initial balance
        if self.trade_amount_usd > self.initial_balance:
            raise ValueError(
                f"trade_amount_usd ({self.trade_amount_usd}) cannot exceed initial_balance ({self.initial_balance})"
            )
        # M6: validate range steps are positive and min <= max for non-null ranges
        for name, r in [
            ("rsi_oversold_range", self.rsi_oversold_range),
            ("rsi_overbought_range", self.rsi_overbought_range),
            ("stop_loss_range", self.stop_loss_range),
            ("take_profit_range", self.take_profit_range),
        ]:
            if r is None:
                continue
            if len(r) != 3:
                raise ValueError(f"{name}: must have exactly 3 elements [min, max, step]")
            min_v, max_v, step = r
            if step <= 0:
                raise ValueError(f"{name}: step must be > 0 (got {step})")
            if min_v > max_v:
                raise ValueError(f"{name}: min ({min_v}) must be <= max ({max_v})")
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
    
    klines = await seed_client.get_historical_klines(
        symbol=trading_pair, 
        interval="1m", 
        start_str=f"{fetch_hours} hours ago UTC",
        limit=fetch_limit,
    )
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
        
        # Sample for chart display
        chart_data = []
        step = max(1, len(market_history) // 200) if len(market_history) > 200 else 1
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
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@router.post("/simulator/run")
async def run_simulator(request: Request, sim_request: SimulationRequest):
    """Run parameter simulation with grid search."""
    # D2: only RSI mode is supported
    if sim_request.mode != "rsi":
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "BC mode simulation not yet supported"},
        )

    bot = getattr(request.app.state, "bot_engine", None)
    if bot is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "Bot engine not found"},
        )

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
            
            klines = await seed_client.get_historical_klines(
                symbol=trading_pair, 
                interval="1m", 
                start_str=f"{fetch_hours} hours ago UTC",
                limit=fetch_limit,
            )
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
        except Exception as e:
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
            rsi_oversold_range=sim_request.rsi_oversold_range,
            rsi_overbought_range=sim_request.rsi_overbought_range,
            stop_loss_range=sim_request.stop_loss_range,
            take_profit_range=sim_request.take_profit_range,
            trade_amount_usd=sim_request.trade_amount_usd,
        )
        return result
    except Exception as e:
        # M3: return HTTP 500, not 200, on unexpected errors
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )
