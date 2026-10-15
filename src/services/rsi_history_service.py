import json
from pathlib import Path
from typing import List, Literal, Optional
from datetime import datetime, timezone
from src.models.rsi_history import RsiThresholdHistoryEntry
from src.utils.fs import atomic_write_json
from src.utils.logger import get_logger

logger = get_logger(__name__)

HISTORY_PATH = Path("data/rsi_threshold_history.json")

def _load_raw_history() -> List[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with open(HISTORY_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load RSI threshold history: {e}")
        return []

def _save_raw_history(entries: List[dict]) -> None:
    try:
        atomic_write_json(HISTORY_PATH, entries)
    except Exception as e:
        logger.error(f"Failed to save RSI threshold history: {e}")

def add_rsi_threshold(type: Literal["oversold", "overbought"], value: int | None, timestamp: Optional[str] = None) -> RsiThresholdHistoryEntry:
    entry = RsiThresholdHistoryEntry(
        type=type,
        value=value,
        timestamp=timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    history = _load_raw_history()
    history.append(entry.model_dump())
    # Sort by timestamp to ensure stepwise logic logic works correctly
    history.sort(key=lambda x: x["timestamp"])
    _save_raw_history(history)
    logger.info(f"Added RSI threshold history entry: {type}={value} at {entry.timestamp}")
    return entry

def get_rsi_threshold_history(type: Optional[Literal["oversold", "overbought"]] = None) -> List[RsiThresholdHistoryEntry]:
    history = _load_raw_history()
    entries = [RsiThresholdHistoryEntry(**item) for item in history]
    if type:
        entries = [e for e in entries if e.type == type]
    return entries

def clear_rsi_threshold_history(type: Optional[Literal["oversold", "overbought"]] = None) -> None:
    if not type:
        _save_raw_history([])
        logger.info("Cleared all RSI threshold history")
    else:
        history = _load_raw_history()
        filtered = [item for item in history if item["type"] != type]
        _save_raw_history(filtered)
        logger.info(f"Cleared RSI threshold history for type: {type}")

def seed_initial_history(config) -> None:
    """Seed initial history from current config if history is empty."""
    history = _load_raw_history()
    if not history:
        logger.info("Seeding initial RSI threshold history from config")
        # Use an older timestamp for seed to ensure it covers historical chart data
        # Let's say 30 days ago or a fixed old date.
        seed_ts = "2020-01-01T00:00:00Z"
        add_rsi_threshold("oversold", config.rsi_oversold, timestamp=seed_ts)
        add_rsi_threshold("overbought", config.rsi_overbought, timestamp=seed_ts)
