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
    
    # Auto-save/Migrate if config on disk is missing fields from the current model
    if any(k not in data for k in config.model_fields.keys()):
        save_config(config)
        logger.info("Config file migrated to current model version")

    logger.info(
        "Config loaded: pair=%s, RSI Oversold=%s, RSI Overbought=%s",
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
