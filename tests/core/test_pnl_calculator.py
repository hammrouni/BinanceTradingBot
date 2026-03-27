"""Tests for Story 5.3: P&L Calculation."""
import pytest

from src.models.trade import TradeRecord
from src.core.pnl_calculator import calculate_pnl


def make_trade(direction, price, qty=0.0001, executed_at="2026-03-26T12:00:00Z", order_id="o1"):
    return TradeRecord(
        executed_at=executed_at,
        pair="BTCUSDT",
        direction=direction,
        amount_usd=5.0,
        quantity=qty,
        entry_price=price,
        order_id=order_id,
    )


def test_pnl_sell_matched_to_buy():
    buy = make_trade("buy", price=50000.0, executed_at="2026-03-26T10:00:00Z")
    sell = make_trade("sell", price=52000.0, qty=0.0001, executed_at="2026-03-26T11:00:00Z")
    result = calculate_pnl([sell, buy])  # input order doesn't matter

    sell_result = next(t for t in result if t.direction == "sell")
    buy_result = next(t for t in result if t.direction == "buy")

    expected_pnl = round((52000.0 - 50000.0) * 0.0001, 2)
    assert sell_result.pnl_usd == pytest.approx(expected_pnl)
    assert buy_result.pnl_usd is None


def test_pnl_buy_without_sell_stays_none():
    buy = make_trade("buy", price=50000.0)
    result = calculate_pnl([buy])
    assert result[0].pnl_usd is None


def test_pnl_sell_without_buy_stays_none():
    sell = make_trade("sell", price=52000.0)
    result = calculate_pnl([sell])
    assert result[0].pnl_usd is None


def test_pnl_negative_on_loss():
    buy = make_trade("buy", price=50000.0, executed_at="2026-03-26T10:00:00Z")
    sell = make_trade("sell", price=48000.0, qty=0.0001, executed_at="2026-03-26T11:00:00Z")
    result = calculate_pnl([buy, sell])
    sell_result = next(t for t in result if t.direction == "sell")
    assert sell_result.pnl_usd < 0


def test_pnl_preserves_original_order():
    buy = make_trade("buy", price=50000.0, executed_at="2026-03-26T10:00:00Z")
    sell = make_trade("sell", price=52000.0, qty=0.0001, executed_at="2026-03-26T11:00:00Z")
    # Input: newest first (sell, buy)
    result = calculate_pnl([sell, buy])
    assert result[0].direction == "sell"
    assert result[1].direction == "buy"


def test_pnl_empty_list():
    assert calculate_pnl([]) == []
