from fastapi import APIRouter, Request, Query
from typing import Optional, Literal

from src.core.config_manager import load_config, save_config
from src.models.config import TradingConfig
from src.services.rsi_history_service import (
    get_rsi_threshold_history, 
    add_rsi_threshold, 
    clear_rsi_threshold_history,
    seed_initial_history
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_config(request: Request):
    config = load_config()
    # Seed history if it's the first time
    seed_initial_history(config)
    
    # Include trading_env from settings for UI environment detection
    settings = getattr(request.app.state, "settings", None)
    data = config.model_dump()
    if settings:
        data["trading_env"] = settings.trading_env
    return {"status": "ok", "data": data}


@router.put("")
async def update_config(new_config: TradingConfig, request: Request):
    old_config = load_config()
    
    # Check for RSI threshold changes and record in history
    if new_config.rsi_oversold != old_config.rsi_oversold:
        add_rsi_threshold("oversold", new_config.rsi_oversold)
    if new_config.rsi_overbought != old_config.rsi_overbought:
        add_rsi_threshold("overbought", new_config.rsi_overbought)
        
    save_config(new_config)
    # Update the running bot's config
    request.app.state.config = new_config
    
    # Refresh thresholds for any open position
    bot = getattr(request.app.state, "bot_engine", None)
    if bot:
        await bot.refresh_thresholds(new_config)

    return {"status": "ok", "data": new_config.model_dump()}


@router.get("/rsi-history")
async def get_rsi_history(type: Optional[Literal["oversold", "overbought"]] = Query(None)):
    history = get_rsi_threshold_history(type)
    return {"status": "ok", "data": [h.model_dump() for h in history]}


@router.post("/rsi-history")
async def add_rsi_history_entry(type: Literal["oversold", "overbought"], value: int, timestamp: Optional[str] = None):
    entry = add_rsi_threshold(type, value, timestamp)
    return {"status": "ok", "data": entry.model_dump()}


@router.delete("/rsi-history")
async def clear_rsi_history(type: Optional[Literal["oversold", "overbought"]] = Query(None)):
    clear_rsi_threshold_history(type)
    return {"status": "ok", "message": "History cleared"}
