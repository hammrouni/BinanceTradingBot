"""Phase 1 money-safety regression tests for BotEngine / PositionManager / executor."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.core.position_manager as pm_module
from src.core.bot_engine import BotEngine, BotState, SELL_MAX_FAILURES
from src.services.binance_client import BinanceConnectionError, BinanceOrderError

from .conftest import make_config, make_order, open_position


# -- 1. SL/TP on every tick ------------------------------------------------------

async def test_stop_loss_fires_mid_candle_on_price_tick(engine, fake_client):
    cfg = make_config(stop_loss_pct=5.0, take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)  # SL = 47500
    engine.set_config(cfg)

    await engine.on_price_tick(49000.0)
    fake_client.execute_market_sell.assert_not_called()

    await engine.on_price_tick(47400.0)
    fake_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


async def test_take_profit_fires_on_price_tick(engine, fake_client):
    cfg = make_config(stop_loss_pct=5.0, take_profit_pct=2.0)
    await engine.start()
    open_position(engine, cfg)  # TP = 51000
    engine.set_config(cfg)

    await engine.on_price_tick(51000.0)
    fake_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


async def test_price_tick_never_runs_strategies(engine, fake_client):
    cfg = make_config()
    await engine.start()
    engine.set_config(cfg)
    await engine.on_price_tick(40000.0)  # no position: must be a no-op
    fake_client.execute_market_buy.assert_not_called()
    fake_client.execute_market_sell.assert_not_called()


async def test_price_tick_ratchets_trailing_stop_monotonically(engine):
    cfg = make_config(stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)  # SL = 49000
    engine.set_config(cfg)

    await engine.on_price_tick(51000.0)
    assert engine._stop_loss_price == pytest.approx(51000 * 0.98)
    await engine.on_price_tick(50500.0)  # lower price must not lower the SL
    assert engine._stop_loss_price == pytest.approx(51000 * 0.98)


@pytest.mark.parametrize("state,active", [
    (BotState.RUNNING, True), (BotState.PAUSED, True),
    (BotState.STOPPED, True), (BotState.ERROR, False),
])
async def test_price_tick_protection_by_state(engine, fake_client, state, active):
    cfg = make_config(take_profit_pct=None)
    open_position(engine, cfg)
    engine.set_config(cfg)
    engine.state = state
    await engine.on_price_tick(40000.0)
    assert (fake_client.execute_market_sell.call_count == 1) is active


async def test_candle_update_also_checks_risk(engine, fake_client):
    cfg = make_config(take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)
    await engine.process_market_update(rsi=50.0, price=40000.0, config=cfg)
    fake_client.execute_market_sell.assert_called_once()


# -- 2. Balance failures never clear the position --------------------------------

async def test_position_manager_balance_error_raises(engine, fake_client):
    fake_client.get_base_asset_balance.side_effect = BinanceConnectionError("boom")
    with pytest.raises(BinanceConnectionError):
        await engine._pos_manager.get_base_asset_balance("BTCUSDT")


async def test_failed_balance_fetch_keeps_position(engine, fake_client):
    cfg = make_config()
    open_position(engine, cfg)
    fake_client.get_base_asset_balance.side_effect = BinanceConnectionError("timeout")

    await engine.sync_open_position(cfg)

    assert engine.open_position is not None
    assert engine._stop_loss_price is not None


async def test_confirmed_zero_balance_clears_position(engine, fake_client):
    cfg = make_config()
    open_position(engine, cfg)
    fake_client.get_base_asset_balance.return_value = {"free": 0.0, "locked": 0.0, "total": 0.0}
    await engine.sync_open_position(cfg)
    assert engine.open_position is None


async def test_client_raises_when_symbol_info_unavailable():
    from src.services.binance_client import BinanceClient
    client = BinanceClient(MagicMock(trading_env="testnet"))
    client._data_client = MagicMock()
    client._data_client.get_symbol_info = AsyncMock(side_effect=RuntimeError("down"))
    client._trading_client = MagicMock()
    with pytest.raises(BinanceConnectionError):
        await client.get_base_asset_balance("BTCUSDT")


# -- 3. Bot-owned quantity -------------------------------------------------------

async def test_pre_held_coins_are_not_adopted_or_sold(engine, fake_client):
    cfg = make_config()
    open_position(engine, cfg, qty=0.0001)
    fake_client.get_base_asset_balance.return_value = {"free": 1.5, "locked": 0.0, "total": 1.5}

    await engine.sync_open_position(cfg)
    assert engine.open_position.quantity == pytest.approx(0.0001)

    await engine.manual_sell(cfg)
    sold_qty = fake_client.execute_market_sell.call_args.args[1]
    assert sold_qty == pytest.approx(0.0001)


async def test_quantity_reduced_when_wallet_holds_less(engine, fake_client):
    cfg = make_config()
    open_position(engine, cfg, qty=0.0002)
    fake_client.get_base_asset_balance.return_value = {"free": 0.00015, "locked": 0.0, "total": 0.00015}
    await engine.sync_open_position(cfg)
    assert engine.open_position.quantity == pytest.approx(0.00015)


async def test_recovery_caps_quantity_at_logged_buy(engine, fake_client, monkeypatch):
    from src.models.trade import TradeRecord
    cfg = make_config()
    fake_client.get_base_asset_balance.return_value = {"free": 2.0, "locked": 0.0, "total": 2.0}
    trade = TradeRecord(executed_at="2026-01-01T00:00:00Z", pair="BTCUSDT", direction="buy",
                        amount_usd=5.0, quantity=0.0001, entry_price=50000.0,
                        order_id="9", is_test=True)
    monkeypatch.setattr(pm_module, "read_trades", lambda limit=500: [trade])
    await engine.sync_open_position(cfg)
    assert engine.open_position.quantity == pytest.approx(0.0001)


# -- 4. Shared lock, backoff, ERROR state ----------------------------------------

async def test_concurrent_manual_and_auto_sell_execute_once(engine, fake_client):
    cfg = make_config(take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)
    engine.set_config(cfg)

    async def slow_sell(*a, **k):
        await asyncio.sleep(0.05)
        return make_order(price=47000.0)

    fake_client.execute_market_sell.side_effect = slow_sell
    await asyncio.gather(
        engine.on_price_tick(40000.0), engine.manual_sell(cfg), return_exceptions=True)

    assert fake_client.execute_market_sell.call_count == 1
    assert engine.open_position is None


async def test_concurrent_manual_buys_execute_once(engine, fake_client):
    cfg = make_config()

    async def slow_buy(*a, **k):
        await asyncio.sleep(0.05)
        return make_order()

    fake_client.execute_market_buy.side_effect = slow_buy
    await asyncio.gather(engine.manual_buy(cfg), engine.manual_buy(cfg), return_exceptions=True)
    assert fake_client.execute_market_buy.call_count == 1


async def test_failed_sell_backs_off(engine, fake_client, clock):
    cfg = make_config(take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)
    engine.set_config(cfg)
    fake_client.execute_market_sell.side_effect = BinanceOrderError("NOTIONAL")

    await engine.on_price_tick(40000.0)
    assert fake_client.execute_market_sell.call_count == 1
    await engine.on_price_tick(40000.0)  # inside backoff window
    assert fake_client.execute_market_sell.call_count == 1

    clock.advance(10_000)
    await engine.on_price_tick(40000.0)
    assert fake_client.execute_market_sell.call_count == 2
    assert engine.open_position is not None


async def test_consecutive_sell_failures_move_to_error(engine, fake_client, clock, broadcaster):
    cfg = make_config(take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)
    engine.set_config(cfg)
    fake_client.execute_market_sell.side_effect = BinanceConnectionError("down")

    for _ in range(SELL_MAX_FAILURES):
        clock.advance(10_000)
        await engine.on_price_tick(40000.0)

    assert engine.state == BotState.ERROR
    assert engine.open_position is not None
    types = [c.args[0]["type"] for c in broadcaster.broadcast.call_args_list]
    assert "error" in types


async def test_successful_sell_resets_failure_counter(engine, fake_client, clock):
    cfg = make_config(take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)
    engine.set_config(cfg)
    fake_client.execute_market_sell.side_effect = BinanceOrderError("x")
    await engine.on_price_tick(40000.0)
    assert engine._sell_failures == 1
    clock.advance(10_000)
    fake_client.execute_market_sell.side_effect = None
    await engine.on_price_tick(40000.0)
    assert engine._sell_failures == 0
    assert engine.open_position is None


async def test_set_error_broadcasts_status_and_error(engine, broadcaster):
    await engine.start()
    await engine.set_error("API timeout")
    calls = [c.args[0] for c in broadcaster.broadcast.call_args_list]
    err = [c for c in calls if c["type"] == "error"]
    assert engine.state == BotState.ERROR
    assert "bot_status" in [c["type"] for c in calls]
    assert err and err[0]["payload"]["code"] == "API_FAILURE"
    assert err[0]["payload"]["message"] == "API timeout"


# -- 5. Threshold handling -------------------------------------------------------

async def test_wallet_refresh_does_not_reset_trailing_stop(engine):
    cfg = make_config(stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    await engine.start()
    open_position(engine, cfg)
    engine.set_config(cfg)
    await engine.on_price_tick(55000.0)
    ratcheted = engine._stop_loss_price
    assert ratcheted == pytest.approx(55000 * 0.98)

    await engine.update_balances("BTCUSDT", cfg)  # e.g. dashboard F5 / reconnect

    assert engine._stop_loss_price == pytest.approx(ratcheted)


async def test_refresh_thresholds_keeps_higher_trailing_sl(engine):
    cfg = make_config(stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    open_position(engine, cfg)
    engine._stop_loss_price = 54000.0  # ratcheted
    await engine.refresh_thresholds(make_config(stop_loss_pct=None, trailing_stop_pct=3.0,
                                                take_profit_pct=None))
    assert engine._stop_loss_price == pytest.approx(54000.0)


async def test_refresh_thresholds_applies_new_fixed_sl(engine):
    cfg = make_config(stop_loss_pct=5.0, take_profit_pct=None)
    open_position(engine, cfg)
    await engine.refresh_thresholds(make_config(stop_loss_pct=10.0, take_profit_pct=None))
    assert engine._stop_loss_price == pytest.approx(45000.0)


async def test_refresh_thresholds_noop_when_risk_config_unchanged(engine):
    cfg = make_config(stop_loss_pct=5.0, take_profit_pct=None)
    open_position(engine, cfg)
    engine._stop_loss_price = 48000.0  # manual drift
    await engine.refresh_thresholds(make_config(stop_loss_pct=5.0, take_profit_pct=None, rsi_oversold=20))
    assert engine._stop_loss_price == pytest.approx(48000.0)


async def test_support_sl_frozen_at_entry(engine):
    cfg = make_config(stop_loss_pct=None, take_profit_pct=None,
                      sl_lookback_candles=3, sl_buffer_pct=0.0)
    for low in (49000.0, 48500.0, 49500.0):
        engine.market_history.append({"low": low, "price": 50000.0})
    open_position(engine, cfg)
    assert engine._stop_loss_price == pytest.approx(48500.0)

    for low in (47000.0, 47100.0, 47200.0):  # window slides to lower lows
        engine.market_history.append({"low": low, "price": 47500.0})
    await engine.refresh_thresholds(make_config(stop_loss_pct=None, take_profit_pct=None,
                                                sl_lookback_candles=3, sl_buffer_pct=1.0))
    # buffer changed (config change) -> SL moves, but the support level stays the entry one
    assert engine._stop_loss_price == pytest.approx(48500.0 * 0.99)


# -- 6. Atomic writes / corrupt config -------------------------------------------

def test_atomic_write_json_replaces_file(tmp_path):
    from src.utils.fs import atomic_write_json
    target = tmp_path / "x.json"
    atomic_write_json(target, {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_atomic_write_json_failure_keeps_original(tmp_path):
    from src.utils.fs import atomic_write_json
    target = tmp_path / "x.json"
    atomic_write_json(target, {"a": 1})
    with pytest.raises(TypeError):
        atomic_write_json(target, {"a": object()})
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_corrupt_config_backed_up_and_defaults_used(tmp_path, monkeypatch):
    import src.core.config_manager as cm
    path = tmp_path / "config.json"
    path.write_text("{ not json")
    monkeypatch.setattr(cm, "CONFIG_PATH", path)

    cfg = cm.load_config()

    assert cfg.trading_pair == "BTCUSDT"
    backups = list(tmp_path.glob("config.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_text() == "{ not json"
    assert json.loads(path.read_text())["trading_pair"] == "BTCUSDT"


def test_invalid_config_values_backed_up_and_defaults_used(tmp_path, monkeypatch):
    import src.core.config_manager as cm
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"stop_loss_pct": 9999}))
    monkeypatch.setattr(cm, "CONFIG_PATH", path)
    cfg = cm.load_config()
    assert cfg.stop_loss_pct == 5.0
    assert list(tmp_path.glob("config.json.corrupt-*"))


def test_save_config_is_atomic(tmp_path, monkeypatch):
    import src.core.config_manager as cm
    path = tmp_path / "config.json"
    monkeypatch.setattr(cm, "CONFIG_PATH", path)
    cm.save_config(make_config(stop_loss_pct=7.0))
    assert json.loads(path.read_text())["stop_loss_pct"] == 7.0
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_rsi_history_save_is_atomic(tmp_path, monkeypatch):
    import src.services.rsi_history_service as rh
    monkeypatch.setattr(rh, "HISTORY_PATH", tmp_path / "h.json")
    rh.add_rsi_threshold("oversold", 30)
    assert json.loads((tmp_path / "h.json").read_text())[0]["value"] == 30
    assert [p.name for p in tmp_path.iterdir()] == ["h.json"]


async def test_bot_state_persist_is_atomic_and_roundtrips(engine, isolated_state):
    cfg = make_config()
    open_position(engine, cfg)
    engine._persist_state()
    assert [p.name for p in isolated_state.iterdir()] == ["bot_state.json"]
    restored = BotEngine()
    assert restored.open_position.order_id == "123"
    assert restored._stop_loss_price == pytest.approx(engine._stop_loss_price)


# -- 7. Restart behaviour --------------------------------------------------------

async def test_restart_restores_paused_not_running_by_default(engine):
    await engine.start()
    assert BotEngine().state == BotState.PAUSED


async def test_restart_can_restore_running_when_configured(engine):
    await engine.start()
    assert BotEngine(restore_running=True).state == BotState.RUNNING


async def test_restart_keeps_stopped_stopped(engine):
    await engine.start()
    await engine.stop()
    assert BotEngine(restore_running=True).state == BotState.STOPPED


async def test_restored_position_is_protected_after_restart(fake_client, clock):
    cfg = make_config(take_profit_pct=None)
    first = BotEngine(clock=clock)
    first.set_binance_client(fake_client)
    await first.start()
    open_position(first, cfg)
    first._persist_state()

    second = BotEngine(clock=clock)  # restored PAUSED
    second.set_binance_client(fake_client)
    second.set_config(cfg)
    await second.on_price_tick(40000.0)
    fake_client.execute_market_sell.assert_called_once()
