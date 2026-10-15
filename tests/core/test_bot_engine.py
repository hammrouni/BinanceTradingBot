"""BotEngine behaviour: state machine, strategy-driven buys/sells, SL/TP, BC mode, recovery.

Written against the current engine: BotEngine delegates to TradeExecutor, PositionManager and the
strategies, so every test drives the engine with a fake Binance client (see conftest.py).
Money-safety regressions live in test_engine_safety.py.
"""
import pytest

from src.core.bot_engine import BotEngine, BotState, InvalidStateTransitionError
from src.core.strategies import RSIStrategy
from src.core.strategies.base import Signal, TickContext
from src.models.trade import TradeRecord
from src.services.binance_client import BinanceConnectionError

import src.core.position_manager as pm_module

from .conftest import make_config, make_order, open_position


# -- State machine ---------------------------------------------------------------

async def test_initial_state_is_stopped():
    engine = BotEngine()
    assert engine.state == BotState.STOPPED
    assert not engine.is_active


async def test_start_pause_resume_stop_cycle():
    engine = BotEngine()
    await engine.start()
    assert engine.state == BotState.RUNNING and engine.is_active
    await engine.pause()
    assert engine.state == BotState.PAUSED and not engine.is_active
    await engine.resume()
    assert engine.state == BotState.RUNNING
    await engine.stop()
    assert engine.state == BotState.STOPPED


async def test_set_error_then_start_allowed():
    engine = BotEngine()
    await engine.start()
    await engine.set_error("test")
    assert engine.state == BotState.ERROR
    await engine.start()
    assert engine.state == BotState.RUNNING


async def test_invalid_transitions_raise():
    engine = BotEngine()
    with pytest.raises(InvalidStateTransitionError):
        await engine.pause()
    with pytest.raises(InvalidStateTransitionError):
        await engine.resume()
    with pytest.raises(InvalidStateTransitionError):
        await engine.stop()
    await engine.start()
    with pytest.raises(InvalidStateTransitionError):
        await engine.start()


async def test_uptime():
    engine = BotEngine()
    assert engine.get_uptime_seconds() == 0
    await engine.start()
    assert engine.get_uptime_seconds() >= 0


# -- RSI buys --------------------------------------------------------------------

async def test_buy_triggered_on_rsi_below_threshold(engine, fake_client):
    await engine.start()
    await engine.process_market_update(rsi=25.0, price=50000.0, config=make_config())
    fake_client.execute_market_buy.assert_called_once()
    assert fake_client.execute_market_buy.call_args.args == ("BTCUSDT", 15.0)
    assert engine.open_position is not None


async def test_buy_not_triggered_above_threshold(engine, fake_client):
    await engine.start()
    await engine.process_market_update(rsi=50.0, price=50000.0, config=make_config())
    fake_client.execute_market_buy.assert_not_called()


async def test_buy_is_edge_triggered(engine, fake_client):
    await engine.start()
    cfg = make_config()
    await engine.process_market_update(rsi=25.0, price=50000.0, config=cfg)
    await engine.process_market_update(rsi=24.0, price=50000.0, config=cfg)
    assert fake_client.execute_market_buy.call_count == 1


@pytest.mark.parametrize("pause", [False, True])
async def test_no_buy_unless_running(engine, fake_client, pause):
    if pause:
        await engine.start()
        await engine.pause()
    await engine.process_market_update(rsi=25.0, price=50000.0, config=make_config())
    fake_client.execute_market_buy.assert_not_called()


async def test_error_state_blocks_trading(engine, fake_client):
    await engine.start()
    await engine.set_error("boom")
    await engine.process_market_update(rsi=25.0, price=50000.0, config=make_config())
    fake_client.execute_market_buy.assert_not_called()


async def test_failed_buy_leaves_no_position(engine, fake_client):
    fake_client.execute_market_buy.side_effect = BinanceConnectionError("down")
    await engine.start()
    await engine.process_market_update(rsi=25.0, price=50000.0, config=make_config())
    assert engine.open_position is None


async def test_buy_sets_stop_loss_and_take_profit(engine):
    await engine.start()
    await engine.process_market_update(
        rsi=25.0, price=50000.0, config=make_config(stop_loss_pct=5.0, take_profit_pct=2.0))
    assert engine._stop_loss_price == pytest.approx(47500.0)
    assert engine._take_profit_price == pytest.approx(51000.0)


async def test_zero_take_profit_disables_it(engine):
    await engine.start()
    await engine.process_market_update(rsi=25.0, price=50000.0, config=make_config(take_profit_pct=0))
    assert engine._take_profit_price is None


async def test_trailing_stop_seeds_initial_sl_when_no_fixed_sl(engine):
    await engine.start()
    cfg = make_config(stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    await engine.process_market_update(rsi=25.0, price=50000.0, config=cfg)
    assert engine._stop_loss_price == pytest.approx(49000.0)


async def test_buy_skipped_without_trade_amount(engine, fake_client):
    await engine.start()
    cfg = make_config(trade_amount_usd=None)
    await engine.process_market_update(rsi=25.0, price=50000.0, config=cfg)
    fake_client.execute_market_buy.assert_not_called()


async def test_buy_skipped_without_rsi_oversold(engine, fake_client):
    await engine.start()
    cfg = make_config(rsi_oversold=None)
    await engine.process_market_update(rsi=5.0, price=50000.0, config=cfg)
    fake_client.execute_market_buy.assert_not_called()


# -- RSI filters (through the engine) --------------------------------------------

def _seed_prices(engine, prices):
    for p in prices:
        engine._strategies["RSI"].record_price(p)


async def test_price_bounce_blocks_buy_while_falling(engine, fake_client):
    await engine.start()
    _seed_prices(engine, [50100.0, 50080.0, 50060.0])
    await engine.process_market_update(rsi=25.0, price=50040.0, config=make_config(price_bounce_ticks=3, active_filters=["BOUNCE"]))
    fake_client.execute_market_buy.assert_not_called()


async def test_price_bounce_allows_buy_while_rising(engine, fake_client):
    await engine.start()
    _seed_prices(engine, [50000.0, 50020.0, 50040.0])
    await engine.process_market_update(rsi=25.0, price=50060.0, config=make_config(price_bounce_ticks=3, active_filters=["BOUNCE"]))
    fake_client.execute_market_buy.assert_called_once()


async def test_price_bounce_does_not_block_without_enough_history(engine, fake_client):
    await engine.start()
    await engine.process_market_update(rsi=25.0, price=50010.0, config=make_config(price_bounce_ticks=15, active_filters=["BOUNCE"]))
    fake_client.execute_market_buy.assert_called_once()


async def test_bear_trend_blocks_buy_after_steep_drop(engine, fake_client):
    await engine.start()
    _seed_prices(engine, [50000.0, 49000.0, 48000.0, 47000.0])
    cfg = make_config(bear_trend_candles=5, bear_trend_pct=1.0, active_filters=["BEAR"])
    await engine.process_market_update(rsi=25.0, price=46000.0, config=cfg)
    fake_client.execute_market_buy.assert_not_called()


async def test_bear_trend_allows_buy_after_gentle_drop(engine, fake_client):
    await engine.start()
    _seed_prices(engine, [50000.0, 49990.0, 49980.0, 49970.0])
    cfg = make_config(bear_trend_candles=3, bear_trend_pct=5.0, active_filters=["BEAR"])
    await engine.process_market_update(rsi=25.0, price=49960.0, config=cfg)
    fake_client.execute_market_buy.assert_called_once()


async def test_bear_trend_disabled_when_params_none(engine, fake_client):
    await engine.start()
    _seed_prices(engine, [50000.0, 49000.0, 48000.0, 47000.0, 46000.0])
    await engine.process_market_update(rsi=25.0, price=44000.0, config=make_config())
    fake_client.execute_market_buy.assert_called_once()


def test_rsi_strategy_signals_directly():
    strategy = RSIStrategy()
    cfg = make_config()

    def ctx(rsi, has_pos=False):
        return TickContext(price=50000.0, rsi=rsi, config=cfg, has_open_position=has_pos, buy_lock_held=False)

    assert strategy.on_tick(ctx(25.0)).signal == Signal.BUY
    assert strategy.on_tick(ctx(24.0)).signal == Signal.HOLD  # still oversold: edge-triggered
    assert strategy.on_tick(ctx(75.0, has_pos=True)).signal == Signal.SELL
    assert strategy.on_tick(ctx(None)).signal == Signal.HOLD


async def test_rsi_overbought_sells_open_position(engine, fake_client):
    await engine.start()
    cfg = make_config(take_profit_pct=None)
    open_position(engine, cfg)
    await engine.process_market_update(rsi=75.0, price=50100.0, config=cfg)
    fake_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


# -- Stop-loss / take-profit on the candle path ----------------------------------

async def test_stop_loss_sells_and_clears_position(engine, fake_client):
    await engine.start()
    cfg = make_config()
    open_position(engine, cfg)
    await engine.process_market_update(rsi=40.0, price=47000.0, config=cfg)
    fake_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None
    assert engine._stop_loss_price is None and engine._take_profit_price is None


async def test_no_sell_while_price_between_sl_and_tp(engine, fake_client):
    await engine.start()
    cfg = make_config()
    open_position(engine, cfg)
    await engine.process_market_update(rsi=40.0, price=49000.0, config=cfg)
    fake_client.execute_market_sell.assert_not_called()
    assert engine.open_position is not None


async def test_take_profit_sells_and_clears_state(engine, fake_client):
    await engine.start()
    cfg = make_config()
    open_position(engine, cfg)
    await engine.process_market_update(rsi=40.0, price=51000.0, config=cfg)
    fake_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


async def test_sl_tp_stay_active_while_paused(engine, fake_client):
    await engine.start()
    await engine.pause()
    cfg = make_config()
    open_position(engine, cfg)
    await engine.process_market_update(rsi=40.0, price=47000.0, config=cfg)
    fake_client.execute_market_sell.assert_called_once()


async def test_sl_tp_disabled_when_none(engine, fake_client):
    await engine.start()
    cfg = make_config(stop_loss_pct=None, take_profit_pct=None)
    open_position(engine, cfg)
    await engine.process_market_update(rsi=40.0, price=10.0, config=cfg)
    fake_client.execute_market_sell.assert_not_called()


async def test_trailing_stop_ratchets_then_sells(engine, fake_client):
    await engine.start()
    cfg = make_config(stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    open_position(engine, cfg)  # SL 49000
    await engine.process_market_update(rsi=50.0, price=51000.0, config=cfg)
    assert engine._stop_loss_price == pytest.approx(49980.0)
    fake_client.execute_market_sell.assert_not_called()
    await engine.process_market_update(rsi=50.0, price=49900.0, config=cfg)
    fake_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


async def test_trailing_stop_never_moves_down(engine):
    await engine.start()
    cfg = make_config(stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    open_position(engine, cfg)
    engine._stop_loss_price = 49800.0
    await engine.process_market_update(rsi=50.0, price=50050.0, config=cfg)
    assert engine._stop_loss_price == pytest.approx(49800.0)


# -- BC mode ---------------------------------------------------------------------

def _bc_config(**kw):
    return make_config(active_modes=["BC"], bc_buy_price=68000.0, bc_sell_price=70000.0,
                       rsi_oversold=None, rsi_overbought=None, stop_loss_pct=None,
                       take_profit_pct=None, **kw)


async def test_bc_buys_at_target(engine, fake_client):
    await engine.start()
    await engine.process_market_update(rsi=None, price=67900.0, config=_bc_config())
    fake_client.execute_market_buy.assert_called_once()
    assert engine.open_position is not None


async def test_bc_does_not_buy_above_target(engine, fake_client):
    await engine.start()
    await engine.process_market_update(rsi=None, price=68500.0, config=_bc_config())
    fake_client.execute_market_buy.assert_not_called()


async def test_bc_sells_at_target(engine, fake_client):
    await engine.start()
    cfg = _bc_config()
    open_position(engine, cfg)
    await engine.process_market_update(rsi=None, price=70100.0, config=cfg)
    fake_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


async def test_bc_does_not_sell_below_target(engine, fake_client):
    await engine.start()
    cfg = _bc_config()
    open_position(engine, cfg)
    await engine.process_market_update(rsi=None, price=69000.0, config=cfg)
    fake_client.execute_market_sell.assert_not_called()


async def test_bc_buy_is_edge_triggered(engine, fake_client):
    await engine.start()
    cfg = _bc_config()
    fake_client.execute_market_buy.side_effect = BinanceConnectionError("down")
    await engine.process_market_update(rsi=None, price=67900.0, config=cfg)
    await engine.process_market_update(rsi=None, price=67800.0, config=cfg)  # still below: no retry
    assert fake_client.execute_market_buy.call_count == 1


# -- Manual controls -------------------------------------------------------------

async def test_manual_buy_and_sell(engine, fake_client):
    cfg = make_config()
    await engine.manual_buy(cfg)
    assert engine.open_position is not None
    await engine.manual_sell(cfg)
    assert engine.open_position is None


async def test_manual_buy_rejected_when_position_open(engine):
    cfg = make_config()
    open_position(engine, cfg)
    with pytest.raises(InvalidStateTransitionError):
        await engine.manual_buy(cfg)


async def test_manual_sell_rejected_without_position(engine):
    with pytest.raises(InvalidStateTransitionError):
        await engine.manual_sell(make_config())


async def test_manual_buy_without_amount_uses_free_usdt(engine, fake_client):
    await engine.update_balances("BTCUSDT")
    await engine.manual_buy(make_config(trade_amount_usd=None, active_modes=["BC"], bc_use_full_balance=True))
    assert fake_client.execute_market_buy.call_args.args[1] == pytest.approx(1000.0)


async def test_manual_buy_without_amount_and_no_usdt_rejected(engine):
    with pytest.raises(InvalidStateTransitionError):
        await engine.manual_buy(make_config(trade_amount_usd=None, active_modes=["BC"], bc_use_full_balance=True))


# -- Failed orders ---------------------------------------------------------------

async def test_failed_sell_keeps_open_position(engine, fake_client):
    await engine.start()
    cfg = make_config()
    open_position(engine, cfg)
    fake_client.execute_market_sell.side_effect = BinanceConnectionError("down")
    await engine.process_market_update(rsi=40.0, price=47000.0, config=cfg)
    assert engine.open_position is not None
    assert engine.state == BotState.RUNNING  # one failure is not fatal


async def test_executor_broadcasts_error_on_failed_sell(engine, fake_client, broadcaster):
    await engine.start()
    cfg = make_config()
    open_position(engine, cfg)
    fake_client.execute_market_sell.side_effect = BinanceConnectionError("down")
    await engine.process_market_update(rsi=40.0, price=47000.0, config=cfg)
    errors = [c.args[0] for c in broadcaster.broadcast.call_args_list if c.args[0]["type"] == "error"]
    assert errors and "Sell order failed" in errors[0]["payload"]["message"]


async def test_sell_balance_mismatch_resyncs_quantity(engine, fake_client):
    from src.services.binance_client import BinanceOrderError
    await engine.start()
    cfg = make_config()
    open_position(engine, cfg, qty=0.0002)
    fake_client.execute_market_sell.side_effect = BinanceOrderError("Insufficient available balance")
    fake_client.get_base_asset_balance.return_value = {"free": 0.00015, "locked": 0.0, "total": 0.00015}
    await engine.process_market_update(rsi=40.0, price=47000.0, config=cfg)
    assert engine.open_position.quantity == pytest.approx(0.00015)
    assert engine.state == BotState.RUNNING


async def test_unsellable_dust_clears_position_without_error_state(engine, fake_client):
    from src.services.binance_client import BinanceOrderError
    await engine.start()
    cfg = make_config()
    open_position(engine, cfg)
    fake_client.execute_market_sell.side_effect = BinanceOrderError("UNSELLABLE_DUST: too small")
    fake_client.get_base_asset_balance.return_value = {"free": 0.000001, "locked": 0.0, "total": 0.000001}
    await engine.process_market_update(rsi=40.0, price=47000.0, config=cfg)
    assert engine.open_position is None
    assert engine.state == BotState.RUNNING


# -- Recovery / reconciliation ---------------------------------------------------

def _buy_trade(qty, price=50000.0, order_id="42", is_test=True):
    return TradeRecord(executed_at="2026-01-01T00:00:00Z", pair="BTCUSDT", direction="buy",
                       amount_usd=qty * price, quantity=qty, entry_price=price,
                       order_id=order_id, is_test=is_test)


async def test_sync_recovers_missing_position_from_trade_log(engine, fake_client, monkeypatch):
    monkeypatch.setattr(pm_module, "read_trades", lambda limit=500: [_buy_trade(0.0001)])
    await engine.sync_open_position(make_config())
    assert engine.open_position.order_id == "42"
    assert engine._stop_loss_price == pytest.approx(50000.0 * 0.95)  # recovered position gets SL/TP


async def test_sync_does_not_recover_without_matching_buy(engine, monkeypatch):
    monkeypatch.setattr(pm_module, "read_trades", lambda limit=500: [])
    await engine.sync_open_position(make_config())
    assert engine.open_position is None


async def test_sync_does_not_recover_dust(engine, fake_client, monkeypatch):
    fake_client.get_base_asset_balance.return_value = {"free": 1e-6, "locked": 0.0, "total": 1e-6}
    monkeypatch.setattr(pm_module, "read_trades", lambda limit=500: [_buy_trade(0.0001)])
    await engine.sync_open_position(make_config())
    assert engine.open_position is None


async def test_sync_clears_position_when_wallet_is_dust(engine, fake_client):
    cfg = make_config()
    open_position(engine, cfg)
    fake_client.get_base_asset_balance.return_value = {"free": 1e-6, "locked": 0.0, "total": 1e-6}
    await engine.sync_open_position(cfg)
    assert engine.open_position is None


async def test_update_balances_caches_and_broadcasts(engine, fake_client, broadcaster):
    await engine.update_balances("BTCUSDT")
    assert engine.balances["trading"]["total_net_worth"] == 1000.0
    assert broadcaster.broadcast.call_args.args[0]["type"] == "bot_status"


async def test_broadcast_state_includes_position_and_thresholds(engine, broadcaster):
    open_position(engine, make_config())
    await engine._broadcast_state()
    payload = broadcaster.broadcast.call_args.args[0]["payload"]
    assert payload["open_position"]["stop_loss_price"] == pytest.approx(47500.0)
    assert payload["open_position"]["take_profit_price"] == pytest.approx(51000.0)
