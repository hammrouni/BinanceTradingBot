from fastapi import APIRouter, Request

from src.core.config_manager import load_config, save_config
from src.models.config import TradingConfig

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_config():
    config = load_config()
    return {"status": "ok", "data": config.model_dump()}


@router.put("")
async def update_config(new_config: TradingConfig, request: Request):
    save_config(new_config)
    # Update the running bot's config
    request.app.state.config = new_config
    return {"status": "ok", "data": new_config.model_dump()}
