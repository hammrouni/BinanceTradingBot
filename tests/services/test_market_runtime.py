"""MarketRuntime: seeding, pair change and live RSI Ultra reconfiguration."""
import asyncio
import math
from unittest.mock import AsyncMock

import pytest

from src.core.bot_engine import BotEngine
from src.core.rsi_calculator import RsiCalculator
from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.services.market_runtime import MarketRuntime
from tests.core.conftest import make_config


def klines(base: float, n: int = 80, start_ms: int = 1_700_000_000_000):
    """Binance-shaped kline rows [open_time, o, h, l, c, v, close_time]; the last one is unclosed."""
    out = []
    for i in range(n):
        c = base + 5 * math.sin(i / 5) + 2 * math.sin(i / 1.7)
        t = start_ms + i * 60_000
        out.append([t, str(c), str(c + 0.5), str(c - 0.5), str(c), "1.0", t + 59_999])
    return out


class FakeStream:
    def __init__(self):
        self.symbols = []

    def set_symbol(self, symbol):
        self.symbols.append(symbol)


def build(fetch, config=None):
    config = config or make_config()
    engine = BotEngine()
    rsi = RsiCalculator()
    ultra = RsiUltraCalculator(config.rsi_ultra_period, config.rsi_ultra_signal_period)
    q: asyncio.Queue = asyncio.Queue()
    stream = FakeStream()
    rt = MarketRuntime(engine=engine, rsi_calc=rsi, ultra_calc=ultra, stream=stream,
                       kline_queue=q, fetch_klines=fetch)
    return rt, engine, rsi, ultra, q, stream


async def test_seed_fills_history_calculators_and_strategy_prices():
    fetch = AsyncMock(return_value=klines(100.0))
    rt, engine, rsi, ultra, _, _ = build(fetch)
    await rt.seed(make_config(trading_pair="ETHUSDT"))
    fetch.assert_awaited_once_with("ETHUSDT")
    assert len(engine.market_history) > 0
    # the unclosed last kline is dropped
    assert engine.market_history[-1]["price"] == pytest.approx(float(klines(100.0)[-2][4]))
    assert rsi.current_rsi is not None
    assert len(engine._strategies["RSI"]._price_history) > 0


async def test_seeded_candles_use_kline_open_time():
    fetch = AsyncMock(return_value=klines(100.0))
    rt, engine, *_ = build(fetch)
    await rt.seed(make_config())
    first_open_ms = klines(100.0)[0][0]
    from datetime import datetime, timezone
    # the first stored candle is the first one with an RSI value, so it is at or after the first open_time
    ts = datetime.strptime(engine.market_history[0]["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert ts.timestamp() * 1000 >= first_open_ms


async def test_change_pair_restarts_stream_and_reseeds_everything():
    fetch = AsyncMock(side_effect=[klines(100.0), klines(2000.0)])
    cfg = make_config(trading_pair="BTCUSDT")
    rt, engine, rsi, ultra, q, stream = build(fetch, cfg)
    await rt.seed(cfg)
    await q.put("stale kline of the old pair")
    old_prices = list(engine._strategies["RSI"]._price_history)

    await rt.change_pair(make_config(trading_pair="ETHUSDT"))

    assert stream.symbols == ["ETHUSDT"]
    assert q.empty()
    assert fetch.await_args.args == ("ETHUSDT",)
    assert all(c["price"] > 1000 for c in engine.market_history)        # only ETH candles remain
    assert all(p > 1000 for p in engine._strategies["RSI"]._price_history)
    assert list(engine._strategies["RSI"]._price_history) != old_prices
    assert rsi.current_rsi is not None


async def test_failed_fetch_leaves_the_old_pair_untouched():
    fetch = AsyncMock(side_effect=[klines(100.0), RuntimeError("binance down")])
    rt, engine, _, _, _, stream = build(fetch)
    await rt.seed(make_config())
    before = list(engine.market_history)
    with pytest.raises(RuntimeError):
        await rt.change_pair(make_config(trading_pair="ETHUSDT"))
    assert stream.symbols == []
    assert list(engine.market_history) == before


async def test_reconfigure_ultra_rebuilds_calculator_and_history_values():
    fetch = AsyncMock(return_value=klines(100.0, n=200))
    cfg = make_config()
    rt, engine, _, ultra, _, _ = build(fetch, cfg)
    await rt.seed(cfg)
    before = [c["rsi_ultra_raw"] for c in engine.market_history]
    live_before = ultra.current_values

    assert rt.reconfigure_ultra(make_config(rsi_ultra_period=5, rsi_ultra_signal_period=3)) is True

    assert (ultra._rsi_period, ultra._signal_period) == (5, 3)
    after = [c["rsi_ultra_raw"] for c in engine.market_history]
    assert len(after) == len(before) and after != before
    assert ultra.current_values != live_before
    assert after[-1] == pytest.approx(ultra.current_values[0])


async def test_reconfigure_ultra_is_a_noop_when_periods_are_unchanged():
    fetch = AsyncMock(return_value=klines(100.0))
    cfg = make_config()
    rt, engine, _, ultra, _, _ = build(fetch, cfg)
    await rt.seed(cfg)
    snapshot = [dict(c) for c in engine.market_history]
    assert rt.reconfigure_ultra(cfg) is False
    assert [dict(c) for c in engine.market_history] == snapshot
