"""P1-15: position recovery and PnL pairing respect the trading pair and the testnet/live environment."""
from unittest.mock import AsyncMock

import pytest

import src.core.position_manager as pm_module
from src.core.pnl_calculator import calculate_pnl
from src.core.position_manager import PositionManager
from src.models.trade import TradeRecord


def trade(direction, price=100.0, qty=0.1, at="2026-01-01T00:00:00Z", pair="BTCUSDT", is_test=True,
          order_id=None, fee=0.0):
    return TradeRecord(executed_at=at, pair=pair, direction=direction, amount_usd=price * qty, quantity=qty,
                       entry_price=price, order_id=order_id or f"{pair}-{direction}-{at}-{is_test}",
                       is_test=is_test, fee_usd=fee)


def manager(env, wallet=0.1):
    client = AsyncMock()
    client._settings.trading_env = env
    client.get_base_asset_balance = AsyncMock(return_value={"free": wallet, "locked": 0.0, "total": wallet})
    client._get_step_size = AsyncMock(return_value=0.00001)
    return PositionManager(client)


def feed(monkeypatch, trades):
    monkeypatch.setattr(pm_module, "read_trades", lambda limit=500: trades)


async def test_testnet_recovers_testnet_trades(monkeypatch):
    feed(monkeypatch, [trade("buy", is_test=True, order_id="T1")])
    pos = await manager("testnet").recover_open_position("BTCUSDT")
    assert pos is not None and pos.order_id == "T1"


async def test_testnet_ignores_live_trades(monkeypatch):
    feed(monkeypatch, [trade("buy", is_test=False, order_id="L1")])
    assert await manager("testnet").recover_open_position("BTCUSDT") is None


async def test_live_recovers_live_trades_and_ignores_testnet(monkeypatch):
    feed(monkeypatch, [trade("buy", is_test=True, order_id="T1"), trade("buy", is_test=False, order_id="L1",
                                                                       at="2026-01-02T00:00:00Z")])
    pos = await manager("live").recover_open_position("BTCUSDT")
    assert pos.order_id == "L1"


async def test_other_pairs_never_close_or_open_the_position(monkeypatch):
    feed(monkeypatch, [
        trade("buy", pair="BTCUSDT", order_id="B1", at="2026-01-01T00:00:00Z"),
        trade("sell", pair="ETHUSDT", order_id="E1", at="2026-01-01T01:00:00Z"),   # not a BTC sell
        trade("buy", pair="ETHUSDT", order_id="E2", at="2026-01-01T02:00:00Z"),
    ])
    pos = await manager("testnet").recover_open_position("BTCUSDT")
    assert pos.order_id == "B1"


async def test_sell_in_the_other_environment_does_not_close_a_buy(monkeypatch):
    feed(monkeypatch, [
        trade("buy", is_test=True, order_id="T1", at="2026-01-01T00:00:00Z"),
        trade("sell", is_test=False, order_id="L-sell", at="2026-01-01T01:00:00Z"),
    ])
    pos = await manager("testnet").recover_open_position("BTCUSDT")
    assert pos is not None and pos.order_id == "T1"


async def test_matched_buy_sell_is_not_recovered(monkeypatch):
    feed(monkeypatch, [trade("buy", order_id="B", at="2026-01-01T00:00:00Z"),
                       trade("sell", order_id="S", at="2026-01-01T01:00:00Z")])
    assert await manager("testnet").recover_open_position("BTCUSDT") is None


# ── PnL pairing ───────────────────────────────────────────────────────────────

def test_pnl_never_pairs_across_pairs():
    out = calculate_pnl([trade("buy", pair="BTCUSDT", at="2026-01-01T00:00:00Z"),
                         trade("sell", price=200.0, pair="ETHUSDT", at="2026-01-01T01:00:00Z")])
    assert all(t.pnl_usd is None for t in out)


def test_pnl_never_pairs_test_with_live():
    out = calculate_pnl([trade("buy", is_test=True, at="2026-01-01T00:00:00Z"),
                         trade("sell", price=200.0, is_test=False, at="2026-01-01T01:00:00Z")])
    assert all(t.pnl_usd is None for t in out)


def test_pnl_pairs_within_each_pair_and_environment_independently():
    trades = [
        trade("buy", price=100, pair="BTCUSDT", at="2026-01-01T00:00:00Z", order_id="b1"),
        trade("buy", price=10, pair="ETHUSDT", at="2026-01-01T00:01:00Z", order_id="e1"),
        trade("sell", price=110, pair="BTCUSDT", at="2026-01-01T01:00:00Z", order_id="b2"),
        trade("sell", price=9, pair="ETHUSDT", at="2026-01-01T01:01:00Z", order_id="e2"),
    ]
    by_id = {t.order_id: t for t in calculate_pnl(trades)}
    assert by_id["b2"].pnl_usd == pytest.approx(1.0)       # (110-100)*0.1
    assert by_id["e2"].pnl_usd == pytest.approx(-0.1)      # (9-10)*0.1
