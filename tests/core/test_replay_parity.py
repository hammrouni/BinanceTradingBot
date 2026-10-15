"""Parity: the same candles through a real BotEngine and through the replay harness give identical trades.

The harness (core/replay.py, close-only mode) must make exactly the decisions BotEngine.process_market_update()
makes. The engine runs with a fake executor that fills at the candle close, which is what the harness does.
"""
import functools
import math
import random
from datetime import datetime, timezone

import pytest

from src.core.bot_engine import OrderResult
from src.core.replay import replay
from src.services.history_loader import build_market_history
from tests.core.conftest import make_config

MIN = 60_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % MIN)


def klines(seed: int, n: int = 700, base: float = 100.0):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        c = base + 3 * math.sin(i / 9) + 1.5 * math.sin(i / 3.1) + rng.gauss(0, 0.25)
        t = T0 + i * MIN
        rows.append([t, str(c), str(c + rng.random() * 0.4), str(c - rng.random() * 0.4), str(c), "1.0", t + MIN - 1])
    return rows


class CloseExecutor:
    """Fills every order at `price`, which the driver sets to the current candle's close."""

    def __init__(self):
        self.price = 0.0
        self.last_error = None
        self.calls = []
        self.engine = None

    def _now(self):
        return self.engine.market_history[-1]["timestamp"]

    def _order(self, pair, qty):
        return OrderResult(order_id=str(len(self.calls)), pair=pair, quantity=qty, price=self.price,
                           executed_at=datetime.now(timezone.utc))

    async def execute_buy(self, pair, amount_usd, reason="buy_signal"):
        self.calls.append(("buy", self._now(), self.price, reason))
        return self._order(pair, amount_usd / self.price)

    async def execute_sell(self, pair, quantity, entry_price, reason="signal"):
        self.calls.append(("sell", self._now(), self.price, reason))
        return self._order(pair, quantity)


SCENARIOS = {
    "rsi_sl_tp": dict(rsi_oversold=40, rsi_overbought=60, stop_loss_pct=1.5, take_profit_pct=1.0),
    "rsi_trailing": dict(rsi_oversold=40, rsi_overbought=70, stop_loss_pct=None, trailing_stop_pct=0.8,
                         take_profit_pct=None),
    "rsi_bounce_bear_ma": dict(rsi_oversold=60, rsi_overbought=68, stop_loss_pct=2.0, take_profit_pct=1.2,
                               active_filters=["BOUNCE", "BEAR", "MA"], price_bounce_ticks=1,
                               bear_trend_candles=8, bear_trend_pct=1.5, ma_filter_period=10),
    "rsi_ema_trend": dict(rsi_oversold=50, rsi_overbought=58, stop_loss_pct=2.0, take_profit_pct=1.2,
                          active_filters=["EMA_TREND"], ema_fast_period=3, ema_slow_period=9),
    "rsi_support_sl": dict(rsi_oversold=40, rsi_overbought=65, stop_loss_pct=None, sl_lookback_candles=10,
                           sl_buffer_pct=0.1, take_profit_pct=0.8),
    "ultra": dict(active_modes=["RSI_ULTRA"], rsi_ultra_zone_mid=50.0, stop_loss_pct=1.5, take_profit_pct=None),
    "ultra_filters": dict(active_modes=["RSI_ULTRA"], rsi_ultra_zone_mid=55.0, stop_loss_pct=1.0,
                          take_profit_pct=0.9, active_filters=["MA", "BOUNCE"], ma_filter_period=15,
                          price_bounce_ticks=1),
    "bc": dict(active_modes=["BC"], bc_buy_price=99.0, bc_sell_price=101.0, stop_loss_pct=1.0,
               take_profit_pct=None),
    "bc_tp_anchor": dict(active_modes=["BC"], bc_buy_price=99.0, bc_sell_price=103.0, stop_loss_pct=2.0,
                         take_profit_pct=1.5, tp_anchor="bc_buy"),
}


@functools.lru_cache(maxsize=None)
def history_for(seed: int, ultra_period: int, ultra_signal_period: int):
    return build_market_history(klines(seed), ultra_period=ultra_period, ultra_signal_period=ultra_signal_period)


def _open_time(ts: str) -> int:
    return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("name", sorted(SCENARIOS))
async def test_engine_and_harness_make_identical_trades(engine, name, seed):
    cfg = make_config(**SCENARIOS[name])
    history = history_for(seed, cfg.rsi_ultra_period, cfg.rsi_ultra_signal_period)
    assert len(history) > 300

    # engine side
    ex = CloseExecutor()
    ex.engine = engine
    engine._executor = ex
    await engine.start()
    for row in history:
        ex.price = row["price"]
        await engine.process_market_update(
            rsi=row["rsi"], price=row["price"], config=cfg, open=row["open"], high=row["high"], low=row["low"],
            rsi_ultra_raw=row["rsi_ultra_raw"], rsi_ultra_signal=row["rsi_ultra_signal"],
            open_time=_open_time(row["timestamp"]))

    # harness side
    res = replay(history, cfg, initial_balance=1_000_000.0, fee_pct=0.0, intrabar=False)
    sim = [(e["action"], e["timestamp"], e["price"], e["reason"]) for e in res.events
           if e["reason"] != "end_of_data"]

    assert ex.calls == sim
    assert len(ex.calls) >= 2, f"scenario {name}/{seed} produced no trades: the parity check would be vacuous"
