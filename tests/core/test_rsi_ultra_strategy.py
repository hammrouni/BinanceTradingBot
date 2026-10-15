"""RSI Ultra strategy: SELL is evaluated before the trade-amount guard; on_reset is real."""
from src.core.strategies import RsiUltraStrategy
from src.core.strategies.base import Signal, TickContext
from tests.core.conftest import make_config

UP = dict(rsi_ultra_raw=40.0, rsi_ultra_signal=39.0, prev_rsi_ultra_raw=38.0, prev_rsi_ultra_signal=39.0)
DOWN = dict(rsi_ultra_raw=60.0, rsi_ultra_signal=61.0, prev_rsi_ultra_raw=62.0, prev_rsi_ultra_signal=61.0)


def ctx(config, *, position=False, **kw):
    return TickContext(price=100.0, rsi=None, config=config, has_open_position=position,
                       buy_lock_held=False, **kw)


def test_sell_cross_fires_without_trade_amount():
    cfg = make_config(trade_amount_usd=None)
    res = RsiUltraStrategy().on_tick(ctx(cfg, position=True, **DOWN))
    assert res.signal == Signal.SELL


def test_buy_still_needs_trade_amount():
    cfg = make_config(trade_amount_usd=None)
    res = RsiUltraStrategy().on_tick(ctx(cfg, **UP))
    assert res.signal == Signal.HOLD and res.reason == "no_trade_amount"


def test_buy_with_amount():
    assert RsiUltraStrategy().on_tick(ctx(make_config(), **UP)).signal == Signal.BUY


def test_a_cross_fires_once_until_reset():
    s = RsiUltraStrategy()
    cfg = make_config()
    assert s.on_tick(ctx(cfg, **UP)).signal == Signal.BUY
    assert s.on_tick(ctx(cfg, **UP)).signal == Signal.HOLD     # same cross seen again: no duplicate
    s.on_reset()
    assert s.on_tick(ctx(cfg, **UP)).signal == Signal.BUY


def test_opposite_cross_rearms_the_signal():
    s = RsiUltraStrategy()
    cfg = make_config()
    assert s.on_tick(ctx(cfg, **UP)).signal == Signal.BUY
    assert s.on_tick(ctx(cfg, position=True, **DOWN)).signal == Signal.SELL
    assert s.on_tick(ctx(cfg, **UP)).signal == Signal.BUY


def test_on_reset_keeps_price_history_for_the_filters():
    s = RsiUltraStrategy()
    s.record_price(1.0)
    s.on_reset()
    assert list(s._price_history) == [1.0]


def test_unactioned_down_cross_still_rearms_the_buy():
    """Down cross with no position emits nothing but must not leave the next up cross suppressed."""
    s = RsiUltraStrategy()
    cfg = make_config()
    assert s.on_tick(ctx(cfg, **UP)).signal == Signal.BUY
    assert s.on_tick(ctx(cfg, position=False, **DOWN)).signal == Signal.HOLD
    assert s.on_tick(ctx(cfg, **UP)).signal == Signal.BUY
