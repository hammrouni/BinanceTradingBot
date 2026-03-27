from pathlib import Path

from src.models.trade import TradeRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)

TRADES_PATH = Path("data/trades.jsonl")


def read_trades(limit: int = 50) -> list[TradeRecord]:
    if not TRADES_PATH.exists():
        return []
    records: list[TradeRecord] = []
    with open(TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(TradeRecord.model_validate_json(line))
            except Exception as e:
                logger.warning("Skipping malformed trade log line: %s", e)
    records.reverse()  # newest first
    return records[:limit]
