"""Tests for Story 5.1: Trade Execution Logging to JSONL."""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.trade import TradeRecord
from src.core.trade_logger import log_trade
from src.services.binance_client import OrderResult


def make_order_result(price=50000.0, qty=0.0001, pair="BTCUSDT") -> OrderResult:
    return OrderResult(
        order_id="ord123",
        pair=pair,
        quantity=qty,
        price=price,
        executed_at=datetime(2026, 3, 26, 12, 0, 0, tzinfo=timezone.utc),
    )


# --- TradeRecord model tests ---

def test_trade_record_default_id_generated():
    r = TradeRecord(
        executed_at="2026-03-26T12:00:00Z",
        pair="BTCUSDT",
        direction="buy",
        amount_usd=5.0,
        quantity=0.0001,
        entry_price=50000.0,
        order_id="ord123",
    )
    assert r.id is not None
    assert len(r.id) == 36  # uuid4 format


def test_trade_record_from_order_result_buy():
    result = make_order_result()
    record = TradeRecord.from_order_result(result, direction="buy", amount_usd=5.0)
    assert record.direction == "buy"
    assert record.pair == "BTCUSDT"
    assert record.entry_price == 50000.0
    assert record.quantity == 0.0001
    assert record.order_id == "ord123"
    assert record.amount_usd == 5.0
    assert record.executed_at == "2026-03-26T12:00:00Z"


def test_trade_record_from_order_result_sell():
    result = make_order_result(price=48000.0)
    record = TradeRecord.from_order_result(result, direction="sell", amount_usd=5.0)
    assert record.direction == "sell"
    assert record.entry_price == 48000.0


def test_trade_record_no_credential_fields():
    record = TradeRecord.from_order_result(make_order_result(), direction="buy", amount_usd=5.0)
    data = record.model_dump()
    assert "binance_api_key" not in data
    assert "binance_api_secret" not in data


# --- trade_logger tests ---

@pytest.mark.asyncio
async def test_log_trade_creates_file_and_appends(tmp_path):
    trades_path = tmp_path / "trades.jsonl"
    record = TradeRecord.from_order_result(make_order_result(), direction="buy", amount_usd=5.0)

    with patch("src.core.trade_logger.TRADES_PATH", trades_path):
        await log_trade(record)

    assert trades_path.exists()
    lines = trades_path.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["direction"] == "buy"
    assert parsed["pair"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_log_trade_appends_not_overwrites(tmp_path):
    trades_path = tmp_path / "trades.jsonl"
    r1 = TradeRecord.from_order_result(make_order_result(price=50000.0), direction="buy", amount_usd=5.0)
    r2 = TradeRecord.from_order_result(make_order_result(price=48000.0), direction="sell", amount_usd=5.0)

    with patch("src.core.trade_logger.TRADES_PATH", trades_path):
        await log_trade(r1)
        await log_trade(r2)

    lines = trades_path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["direction"] == "buy"
    assert json.loads(lines[1])["direction"] == "sell"


@pytest.mark.asyncio
async def test_log_trade_creates_parent_dir(tmp_path):
    trades_path = tmp_path / "data" / "trades.jsonl"
    record = TradeRecord.from_order_result(make_order_result(), direction="buy", amount_usd=5.0)

    with patch("src.core.trade_logger.TRADES_PATH", trades_path):
        await log_trade(record)

    assert trades_path.exists()


@pytest.mark.asyncio
async def test_log_trade_does_not_raise_on_failure(tmp_path):
    """If write fails (e.g., permission error), log_trade should swallow the error."""
    record = TradeRecord.from_order_result(make_order_result(), direction="buy", amount_usd=5.0)

    with patch("src.core.trade_logger.TRADES_PATH", Path("/invalid_path/that_cannot/be_created.jsonl")):
        # Should not raise
        await log_trade(record)
