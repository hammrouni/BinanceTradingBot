import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.models.config import TradingConfig
from src.utils.fs import atomic_write_json
from src.utils.logger import get_logger

logger = get_logger(__name__, quiet=True)

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
        migrated = migrate_legacy_config(data)
        config = TradingConfig(**data)
    except Exception as e:  # unreadable JSON, wrong shape or invalid values
        return _recover_from_corrupt_config(e)

    # Auto-save/Migrate if config on disk is missing fields from the current model or had legacy ones
    if migrated or any(k not in data for k in config.model_fields.keys()):
        save_config(config)
        logger.info("Config file migrated to current model version")

    logger.info(
        "Config loaded: pair=%s, RSI Oversold=%s, RSI Overbought=%s",
        config.trading_pair,
        config.rsi_oversold,
        config.rsi_overbought,
    )
    return config


def migrate_legacy_config(data: dict) -> bool:
    """Upgrade a raw config dict in place. Returns True if anything changed.

    - min_bc_price -> bc_buy_price (only when bc_buy_price is not set). In BC mode the old field also
      anchored the take profit, so those configs get tp_anchor="bc_buy"; in other modes it is dropped
      (it used to leak into RSI take-profit).
    - bb_period: the Bollinger filter never existed in the backend; the field is dropped.
    - min_move_pct larger than take_profit_pct: the old engine silently blocked every buy; the model now
      rejects it, so the stale value is cleared instead of resetting the whole config.
    """
    changed = False
    if "min_bc_price" in data:
        legacy = data.pop("min_bc_price")
        if legacy is not None and data.get("bc_buy_price") is None:
            data["bc_buy_price"] = float(legacy)
            if "BC" in (data.get("active_modes") or []) and "tp_anchor" not in data:
                data["tp_anchor"] = "bc_buy"
            logger.warning("Config migrated: min_bc_price=%s -> bc_buy_price", legacy)
        changed = True
    if "bb_period" in data:
        data.pop("bb_period")
        changed = True
    min_move = data.get("min_move_pct")
    if min_move is not None:
        take_profit = data.get("take_profit_pct")
        if take_profit is None or take_profit < min_move:
            logger.warning("Config migrated: min_move_pct=%s > take_profit_pct=%s, min_move_pct cleared",
                           min_move, take_profit)
            data["min_move_pct"] = None
            changed = True
    return changed


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
