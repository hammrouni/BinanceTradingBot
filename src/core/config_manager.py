import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.models.config import TradingConfig
from src.utils.fs import atomic_write_json
from src.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path("data/config.json")


def load_config() -> TradingConfig:
    if not CONFIG_PATH.exists():
        config = TradingConfig()
        save_config(config)
        logger.info("Config file not found — created with defaults")
        return config
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        config = TradingConfig(**data)
    except Exception as e:  # unreadable JSON, wrong shape or invalid values
        return _recover_from_corrupt_config(e)
    
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


def _recover_from_corrupt_config(error: Exception) -> TradingConfig:
    """Keep a copy of the unusable config.json, then continue with defaults."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.corrupt-{stamp}")
    try:
        os.replace(CONFIG_PATH, backup)
    except OSError as e:
        logger.warning("Could not back up corrupt config: %s", e)
    logger.warning(
        "Config file %s is invalid (%s). Backed up to %s and falling back to defaults.",
        CONFIG_PATH, error, backup,
    )
    config = TradingConfig()
    save_config(config)
    return config


def save_config(config: TradingConfig) -> None:
    atomic_write_json(CONFIG_PATH, config.model_dump())
    logger.info("Config saved")
