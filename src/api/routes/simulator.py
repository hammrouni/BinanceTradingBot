import asyncio
import re
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from config.settings import get_settings
from src.core.simulator import run_simulation, simulate_single
from src.core.strategies.filters import active_filter_params
from src.services import strategy_research
from src.services.history_loader import load_market_history
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class SimulationRequest(BaseModel):
    mode: str = "rsi"  # "rsi", "bc", or "rsi_ultra"
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
    ma_filter_period: Optional[int] = Field(default=None, ge=2, le=500)
    ema_fast_period: Optional[int] = Field(default=None, ge=2, le=500)
    ema_slow_period: Optional[int] = Field(default=None, ge=2, le=500)

    # BC-specific ranges (offset % from reference price)
    bc_buy_offset_range: Optional[List[float]] = [1.0, 5.0, 0.5]   # % below ref price
    bc_sell_offset_range: Optional[List[float]] = [1.0, 5.0, 0.5]  # % above ref price

    # RSI Ultra specific ranges
    rsi_ultra_period_range: Optional[List[float]] = [14, 14, 1]
    rsi_ultra_signal_period_range: Optional[List[float]] = [9, 9, 1]
    rsi_ultra_zone_mid_range: Optional[List[float]] = [45, 55, 5]

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
        elif self.mode == "rsi_ultra":
            ranges_to_check += [
                ("rsi_ultra_period_range", self.rsi_ultra_period_range),
                ("rsi_ultra_signal_period_range", self.rsi_ultra_signal_period_range),
                ("rsi_ultra_zone_mid_range", self.rsi_ultra_zone_mid_range),
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


async def _fetch_history(request: Request, historical_days: int) -> list[dict]:
    """Fetch `historical_days` of candles for the configured pair (shared loader, configured Ultra periods)."""
    config = getattr(request.app.state, "config", None)
    return await load_market_history(
        get_settings(),
        getattr(config, "trading_pair", "BTCUSDT"),
        historical_days * 1440,
        ultra_period=getattr(config, "rsi_ultra_period", 14),
        ultra_signal_period=getattr(config, "rsi_ultra_signal_period", 9),
    )


async def _resolve_history(request: Request, historical_days: int, bot) -> list[dict]:
    """The bot's own candle history when it covers the window, else a fresh fetch (bot history if that fails)."""
    own = list(bot.market_history) if bot is not None else []
    if len(own) >= historical_days * 1440:
        return own
    try:
        fetched = await _fetch_history(request, historical_days)
        if fetched:
            return fetched
    except Exception as e:
        logger.warning("Could not fetch simulator history, using the bot's own candles: %s", e)
    return own


@router.post("/simulator/data")
async def get_historical_data(request: Request, sim_request: SimulationRequest):
    """Load historical data for chart display (no simulation)."""
    try:
        market_history = await _fetch_history(request, sim_request.historical_days)

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
                'rsi_ultra_raw': p.get('rsi_ultra_raw'),
                'rsi_ultra_signal': p.get('rsi_ultra_signal'),
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
    if sim_request.mode not in ("rsi", "bc", "rsi_ultra"):
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
        market_history = await _resolve_history(request, sim_request.historical_days, bot)

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
            ma_filter_period=sim_request.ma_filter_period,
            ema_fast_period=sim_request.ema_fast_period,
            ema_slow_period=sim_request.ema_slow_period,
            # BC
            bc_buy_offset_range=sim_request.bc_buy_offset_range,
            bc_sell_offset_range=sim_request.bc_sell_offset_range,
            # RSI Ultra
            rsi_ultra_period_range=sim_request.rsi_ultra_period_range,
            rsi_ultra_signal_period_range=sim_request.rsi_ultra_signal_period_range,
            rsi_ultra_zone_mid_range=sim_request.rsi_ultra_zone_mid_range,
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
    ma_filter_period: Optional[int] = None
    ema_fast_period: Optional[int] = None
    ema_slow_period: Optional[int] = None
    # BC
    bc_buy_price: Optional[float] = None
    bc_sell_price: Optional[float] = None
    # BC offsets (% from the causal reference): replays a grid-search row exactly; they win over the prices
    bc_buy_offset_pct: Optional[float] = None
    bc_sell_offset_pct: Optional[float] = None
    # RSI Ultra
    rsi_ultra_zone_mid: Optional[float] = None
    rsi_ultra_period: Optional[int] = None
    rsi_ultra_signal_period: Optional[int] = None


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

    market_history = await _resolve_history(request, body.historical_days, bot)

    if not market_history:
        return JSONResponse(status_code=422, content={"status": "error", "message": "No market history available"})

    active_modes = getattr(config, "active_modes", ["RSI"]) or ["RSI"]
    if "BC" in active_modes:
        mode = "bc"
    elif "RSI_ULTRA" in active_modes:
        mode = "rsi_ultra"
    else:
        mode = "rsi"
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
        bc_buy = getattr(config, "bc_buy_price", None)
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
            **active_filter_params(config),
            bc_buy_price=getattr(config, "bc_buy_price", None),
            bc_sell_price=getattr(config, "bc_sell_price", None),
            # RSI Ultra
            rsi_ultra_zone_mid=getattr(config, "rsi_ultra_zone_mid", None),
            rsi_ultra_period=getattr(config, "rsi_ultra_period", None),
            rsi_ultra_signal_period=getattr(config, "rsi_ultra_signal_period", None),
        )
        # Include the params used so the frontend can display them
        result["used_config"] = {
            "mode": mode,
            "rsi_oversold": getattr(config, "rsi_oversold", None),
            "rsi_overbought": getattr(config, "rsi_overbought", None),
            "bc_buy_price": getattr(config, "bc_buy_price", None),
            "bc_sell_price": getattr(config, "bc_sell_price", None),
            "rsi_ultra_zone_mid": getattr(config, "rsi_ultra_zone_mid", None),
            "rsi_ultra_period": getattr(config, "rsi_ultra_period", None),
            "rsi_ultra_signal_period": getattr(config, "rsi_ultra_signal_period", None),
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

    market_history = await _resolve_history(request, replay.historical_days, bot)

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
            ma_filter_period=replay.ma_filter_period,
            ema_fast_period=replay.ema_fast_period,
            ema_slow_period=replay.ema_slow_period,
            bc_buy_price=replay.bc_buy_price,
            bc_sell_price=replay.bc_sell_price,
            bc_buy_offset_pct=replay.bc_buy_offset_pct,
            bc_sell_offset_pct=replay.bc_sell_offset_pct,
            # RSI Ultra
            rsi_ultra_zone_mid=replay.rsi_ultra_zone_mid,
            rsi_ultra_period=replay.rsi_ultra_period,
            rsi_ultra_signal_period=replay.rsi_ultra_signal_period,
        )
        return result
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


# ── AI optimizer (multi-strategy search + web research + out-of-sample check) ──────────────

class AiOptimizeRequest(BaseModel):
    days: int = Field(default=10, ge=4, le=14)
    fee_pct: float = Field(default=0.1, ge=0.0, le=1.0)
    trade_amount_usd: float = Field(default=100.0, gt=0)
    modes: List[Literal["rsi", "rsi_ultra", "bc"]] = ["rsi", "rsi_ultra", "bc"]
    use_web: bool = True
    use_llm: bool = True
    pair: Optional[str] = None


@router.post("/simulator/ai-optimize")
async def ai_optimize_start(request: Request, body: AiOptimizeRequest):
    """Start the AI optimizer as a background job; poll GET /simulator/ai-optimize/{job_id}."""
    config = getattr(request.app.state, "config", None)
    pair = (body.pair or getattr(config, "trading_pair", "BTCUSDT") or "BTCUSDT").upper()
    if not re.fullmatch(r"[A-Z0-9]{5,15}", pair):
        return JSONResponse(status_code=422, content={"status": "error", "message": "Invalid trading pair"})
    if not body.modes:
        return JSONResponse(status_code=422, content={"status": "error", "message": "Pick at least one strategy"})
    job_id = strategy_research.start_job(get_settings(), pair, body.model_dump())
    if job_id is None:
        return JSONResponse(status_code=409, content={"status": "error", "message": "An optimizer job is already running"})
    return {"status": "ok", "job_id": job_id}


@router.get("/simulator/ai-optimize/{job_id}")
async def ai_optimize_status(job_id: str):
    job = strategy_research.JOBS.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "Unknown job"})
    return {"status": "ok", "data": {k: job[k] for k in
            ("id", "state", "phase", "progress", "pair", "warnings", "result", "error")}}
