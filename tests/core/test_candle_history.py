"""Closed candles are timestamped from the kline open_time and enter market_history immediately."""
import asyncio
from datetime import datetime, timezone

from src.core.market_processor import market_processor
from src.core.rsi_calculator import RsiCalculator
from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.models.market import KlineData
from tests.core.conftest import make_config

OPEN_MS = 1_700_000_040_000  # 2023-11-14T22:14:00Z
ISO = datetime.fromtimestamp(OPEN_MS / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def test_closed_candle_is_in_history_straight_away_with_open_time_stamp(engine):
    await engine.process_market_update(
        rsi=40.0, price=101.0, config=make_config(), open=100.0, high=102.0, low=99.0, open_time=OPEN_MS)
    assert len(engine.market_history) == 1
    c = engine.market_history[-1]
    assert c["timestamp"] == ISO
    assert (c["open"], c["high"], c["low"], c["price"], c["rsi"]) == (100.0, 102.0, 99.0, 101.0, 40.0)


async def test_consecutive_candles_are_one_per_open_time(engine):
    cfg = make_config()
    await engine.process_market_update(rsi=1.0, price=1.0, config=cfg, open_time=OPEN_MS)
    await engine.process_market_update(rsi=2.0, price=2.0, config=cfg, open_time=OPEN_MS + 60_000)
    assert [c["price"] for c in engine.market_history] == [1.0, 2.0]
    assert engine.market_history[1]["timestamp"] != engine.market_history[0]["timestamp"]


async def test_same_open_time_updates_the_candle_instead_of_duplicating(engine):
    cfg = make_config()
    await engine.process_market_update(rsi=1.0, price=100.0, config=cfg, high=101.0, low=99.0, open_time=OPEN_MS)
    await engine.process_market_update(rsi=2.0, price=102.0, config=cfg, high=103.0, low=98.0, open_time=OPEN_MS)
    assert len(engine.market_history) == 1
    c = engine.market_history[0]
    assert (c["price"], c["high"], c["low"], c["rsi"]) == (102.0, 103.0, 98.0, 2.0)


async def test_without_open_time_ticks_in_the_same_minute_merge(engine, monkeypatch):
    import src.core.bot_engine as be

    times = iter([datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
                  datetime(2026, 1, 1, 0, 0, 40, tzinfo=timezone.utc),
                  datetime(2026, 1, 1, 0, 1, 5, tzinfo=timezone.utc)])

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(be, "datetime", FakeDT)
    cfg = make_config()
    await engine.process_market_update(rsi=50.0, price=100.0, config=cfg, high=101.0, low=99.0)
    await engine.process_market_update(rsi=50.0, price=102.0, config=cfg, high=103.0, low=98.0)
    assert len(engine.market_history) == 1
    await engine.process_market_update(rsi=50.0, price=104.0, config=cfg)
    assert len(engine.market_history) == 2
    first = engine.market_history[0]
    assert first["price"] == 102.0 and first["high"] == 103.0 and first["low"] == 98.0
    assert first["timestamp"] == "2026-01-01T00:00:00Z"


async def test_support_stop_loss_sees_the_just_closed_candle(engine):
    cfg = make_config(stop_loss_pct=None, sl_lookback_candles=3, sl_buffer_pct=0.0)
    for i, low in enumerate([100.0, 99.0, 90.0]):
        await engine.process_market_update(rsi=50.0, price=100.0, config=cfg, low=low,
                                           open_time=OPEN_MS + i * 60_000)
    engine._update_thresholds_after_buy(
        __import__("tests.core.conftest", fromlist=["make_order"]).make_order(price=100.0), cfg)
    assert engine._stop_loss_price == 90.0   # the newest candle's low is part of the lookback


async def test_market_processor_stamps_from_open_time():
    kline_q: asyncio.Queue = asyncio.Queue()
    update_q: asyncio.Queue = asyncio.Queue()
    await kline_q.put(KlineData(open_time=OPEN_MS, open=1, high=2, low=0.5, close=1.5, volume=1,
                                close_time=OPEN_MS + 59_999, is_closed=True))
    task = asyncio.create_task(market_processor(kline_q, update_q, RsiCalculator(), RsiUltraCalculator()))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    payload = (await update_q.get())["payload"]
    assert payload["timestamp"] == ISO
    assert payload["open_time"] == OPEN_MS
