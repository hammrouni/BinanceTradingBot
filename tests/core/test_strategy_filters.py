"""RSI / RSI Ultra strategies: price history is recorded once and filters honour their toggles."""
from src.core.strategies import RSIStrategy, RsiUltraStrategy
from src.core.strategies.base import Signal, TickContext
from tests.core.conftest import make_config


def ctx(price, rsi, config, **kw):
    return TickContext(price=price, rsi=rsi, config=config, has_open_position=False,
                       buy_lock_held=False, **kw)


def test_rsi_on_tick_does_not_record_price():
    s = RSIStrategy()
    s.record_price(100.0)
    s.on_tick(ctx(100.0, 50.0, make_config()))
    s.on_tick(ctx(100.0, 50.0, make_config()))
    assert list(s._price_history) == [100.0]


async def test_engine_records_each_tick_once(engine):
    cfg = make_config()
    for p in (100.0, 101.0, 102.0):
        await engine.process_market_update(rsi=50.0, price=p, config=cfg)
    assert list(engine._strategies["RSI"]._price_history) == [100.0, 101.0, 102.0]


def _feed_falling(s, prices):
    for p in prices:
        s.record_price(p)


def test_rsi_bounce_filter_only_when_toggled():
    prices = [100, 99, 98, 97]
    for toggled, expected in ((["BOUNCE"], Signal.HOLD), ([], Signal.BUY)):
        s = RSIStrategy()
        _feed_falling(s, prices)
        cfg = make_config(price_bounce_ticks=2, active_filters=toggled)
        assert s.on_tick(ctx(97, 20.0, cfg)).signal == expected


def test_rsi_bear_filter_only_when_toggled():
    prices = [100, 99, 98, 97, 96]
    for toggled, expected in ((["BEAR"], Signal.HOLD), ([], Signal.BUY)):
        s = RSIStrategy()
        _feed_falling(s, prices)
        cfg = make_config(bear_trend_candles=5, bear_trend_pct=1.0, active_filters=toggled)
        assert s.on_tick(ctx(96, 20.0, cfg)).signal == expected


def test_ultra_ma_filter_only_when_toggled():
    prices = [10, 10, 10, 10, 10]  # price 10 is not below SMA 10
    for toggled, expected in ((["MA"], Signal.HOLD), ([], Signal.BUY)):
        s = RsiUltraStrategy()
        _feed_falling(s, prices)
        cfg = make_config(ma_filter_period=5, active_filters=toggled)
        res = s.on_tick(ctx(10, None, cfg, rsi_ultra_raw=40.0, rsi_ultra_signal=39.0,
                            prev_rsi_ultra_raw=38.0, prev_rsi_ultra_signal=39.0))
        assert res.signal == expected
