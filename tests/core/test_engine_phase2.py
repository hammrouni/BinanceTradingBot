"""Engine behaviour for Phase 2: TP anchoring, BC sizing, min_move no longer blocks buys."""
import pytest

from src.core.bot_engine import InvalidStateTransitionError
from tests.core.conftest import make_config, make_order, open_position


def _bc(**kw):
    base = dict(active_modes=["BC"], bc_buy_price=68000.0, bc_sell_price=75000.0,
                rsi_oversold=None, rsi_overbought=None, stop_loss_pct=None, take_profit_pct=2.0)
    return make_config(**{**base, **kw})


def test_take_profit_anchors_to_entry_by_default(engine):
    cfg = _bc()
    open_position(engine, cfg, price=70000.0)
    assert engine._take_profit_price == pytest.approx(70000.0 * 1.02)


def test_take_profit_anchors_to_bc_buy_when_asked(engine):
    cfg = _bc(tp_anchor="bc_buy")
    open_position(engine, cfg, price=70000.0)
    assert engine._take_profit_price == pytest.approx(68000.0 * 1.02)


async def test_rsi_mode_take_profit_never_uses_bc_price(engine):
    cfg = make_config(take_profit_pct=2.0, bc_buy_price=60000.0)   # tp_anchor defaults to entry
    open_position(engine, cfg, price=50000.0)
    assert engine._take_profit_price == pytest.approx(51000.0)
    assert engine._check_take_profit(60500.0, cfg) is True
    assert engine._check_take_profit(50500.0, cfg) is False


async def test_changing_tp_anchor_rederives_take_profit(engine):
    cfg = _bc()
    open_position(engine, cfg, price=70000.0)
    await engine.refresh_thresholds(_bc(tp_anchor="bc_buy"))
    assert engine._take_profit_price == pytest.approx(68000.0 * 1.02)


# -- BC sizing -------------------------------------------------------------------

async def test_bc_full_balance_spends_free_usdt(engine, fake_client):
    await engine.update_balances("BTCUSDT")
    await engine.start()
    await engine.process_market_update(
        rsi=None, price=67900.0, config=_bc(trade_amount_usd=None, bc_use_full_balance=True))
    assert fake_client.execute_market_buy.call_args.args[1] == pytest.approx(1000.0)


async def test_bc_full_balance_flag_wins_over_amount(engine, fake_client):
    await engine.update_balances("BTCUSDT")
    await engine.start()
    await engine.process_market_update(
        rsi=None, price=67900.0, config=_bc(trade_amount_usd=20.0, bc_use_full_balance=True))
    assert fake_client.execute_market_buy.call_args.args[1] == pytest.approx(1000.0)


async def test_bc_with_amount_buys_that_amount(engine, fake_client):
    await engine.start()
    await engine.process_market_update(rsi=None, price=67900.0, config=_bc(trade_amount_usd=20.0))
    assert fake_client.execute_market_buy.call_args.args[1] == pytest.approx(20.0)


async def test_bc_full_balance_without_usdt_does_not_buy(engine, fake_client):
    fake_client.get_symbol_balances.return_value = {
        "prod": {"assets": {}, "total_net_worth": 0.0},
        "trading": {"assets": {}, "total_net_worth": 0.0}, "trading_env": "testnet"}
    await engine.update_balances("BTCUSDT")
    await engine.start()
    await engine.process_market_update(
        rsi=None, price=67900.0, config=_bc(trade_amount_usd=None, bc_use_full_balance=True))
    fake_client.execute_market_buy.assert_not_called()


async def test_manual_buy_without_amount_needs_the_full_balance_flag(engine, fake_client):
    await engine.update_balances("BTCUSDT")
    with pytest.raises(InvalidStateTransitionError, match="trade_amount_usd"):
        await engine.manual_buy(make_config(trade_amount_usd=None))
    await engine.manual_buy(make_config(trade_amount_usd=None, active_modes=["BC"], bc_use_full_balance=True))
    assert fake_client.execute_market_buy.call_args.args[1] == pytest.approx(1000.0)
