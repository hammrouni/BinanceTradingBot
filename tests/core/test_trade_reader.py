"""Tests for Story 5.2: Trade History reader."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.trade import TradeRecord
from src.core.trade_reader import read_trades


def make_jsonl_line(direction="buy", executed_at="2026-03-26T12:00:00Z") -> str:
    record = TradeRecord(
        executed_at=executed_at,
        pair="BTCUSDT",
        direction=direction,
        amount_usd=5.0,
        quantity=0.0001,
        entry_price=50000.0,
        order_id="ord123",
    )
    return record.model_dump_json()


def test_read_trades_returns_empty_if_no_file(tmp_path):
    path = tmp_path / "trades.jsonl"
    with patch("src.core.trade_reader.TRADES_PATH", path):
        result = read_trades()
    assert result == []


def test_read_trades_returns_empty_if_empty_file(tmp_path):
    path = tmp_path / "trades.jsonl"
    path.write_text("")
    with patch("src.core.trade_reader.TRADES_PATH", path):
        result = read_trades()
    assert result == []


def test_read_trades_returns_records_newest_first(tmp_path):
    path = tmp_path / "trades.jsonl"
    lines = [
        make_jsonl_line(direction="buy", executed_at="2026-03-26T10:00:00Z"),
        make_jsonl_line(direction="sell", executed_at="2026-03-26T11:00:00Z"),
    ]
    path.write_text("\n".join(lines) + "\n")
    with patch("src.core.trade_reader.TRADES_PATH", path):
        result = read_trades()
    assert len(result) == 2
    assert result[0].direction == "sell"  # newest first
    assert result[1].direction == "buy"


def test_read_trades_respects_limit(tmp_path):
    path = tmp_path / "trades.jsonl"
    lines = [make_jsonl_line() for _ in range(10)]
    path.write_text("\n".join(lines) + "\n")
    with patch("src.core.trade_reader.TRADES_PATH", path):
        result = read_trades(limit=3)
    assert len(result) == 3


def test_read_trades_skips_malformed_lines(tmp_path):
    path = tmp_path / "trades.jsonl"
    good_line = make_jsonl_line(direction="buy")
    path.write_text(good_line + "\n{bad json\n" + make_jsonl_line(direction="sell") + "\n")
    with patch("src.core.trade_reader.TRADES_PATH", path):
        result = read_trades()
    assert len(result) == 2  # malformed line skipped
