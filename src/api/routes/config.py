from fastapi import APIRouter, Request, Query
from typing import Optional, Literal

from src.core.config_manager import load_config
from src.services.config_service import apply_config_update
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
    await apply_config_update(new_config, request.app)
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
