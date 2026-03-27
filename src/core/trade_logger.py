import asyncio
from pathlib import Path

from src.models.trade import TradeRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)

TRADES_PATH = Path("data/trades.jsonl")


async def log_trade(record: TradeRecord) -> None:
    try:
        await asyncio.to_thread(_write_trade, record)
    except Exception as e:
        logger.error("Failed to write trade log: %s", e)


def _write_trade(record: TradeRecord) -> None:
    TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADES_PATH, "a") as f:
        f.write(record.model_dump_json() + "\n")
