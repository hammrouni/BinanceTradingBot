import json
from pathlib import Path

from src.models.config import TradingConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path("data/config.json")


def load_config() -> TradingConfig:
    if not CONFIG_PATH.exists():
        config = TradingConfig()
        save_config(config)
        logger.info("Config file not found — created with defaults")
        return config
    with open(CONFIG_PATH) as f:
        data = json.load(f)
    config = TradingConfig(**data)
    
    # Auto-save if config was transparently upgraded/coerced
    if config.trade_amount_usd != data.get("trade_amount_usd"):
        save_config(config)

    logger.info(
        "Config loaded: pair=%s, RSI Oversold=%d, RSI Overbought=%d",
        config.trading_pair,
        config.rsi_oversold,
        config.rsi_overbought,
    )
    return config


def save_config(config: TradingConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config.model_dump(), f, indent=2)
    logger.info("Config saved")
