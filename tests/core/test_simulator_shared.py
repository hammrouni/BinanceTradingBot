"""Simulator uses the shared filters and recomputes RSI Ultra per period combo."""
import math

from src.core import simulator as sim
from src.core.strategies.filters import active_filter_params
from tests.core.conftest import make_config


def _history(prices, rsi):
    return [{"price": p, "rsi": r, "high": p + 0.5, "low": p - 0.5, "timestamp": str(i)}
            for i, (p, r) in enumerate(zip(prices, rsi))]


def _rsi_run(history, **kw):
    return sim.simulate_rsi_mode(history, rsi_oversold=30, rsi_overbought=None, stop_loss_pct=None,
                                 take_profit_pct=None, trade_amount_usd=100.0, collect_events=True, **kw)


def test_simulator_bear_filter_blocks_the_buy():
    prices = [100, 99, 98, 97, 96, 95]
    rsi = [50, 50, 50, 50, 50, 20]
    h = _history(prices, rsi)
    assert _rsi_run(h)["trade_count"] == 1
    blocked = _rsi_run(h, bear_trend_candles=5, bear_trend_pct=1.0)
    assert blocked["trade_count"] == 0 and not blocked["events"]


def test_simulator_ma_and_ema_filters():
    prices = [100] * 10 + [100]
    rsi = [50] * 10 + [20]
    h = _history(prices, rsi)
    assert _rsi_run(h, ma_filter_period=5)["events"] == []        # price == SMA: not below
    falling = list(range(60, 0, -1))
    h2 = _history(falling, [50] * 59 + [20])
    assert _rsi_run(h2, ema_fast_period=3, ema_slow_period=10)["events"] == []
    assert len(_rsi_run(h2)["events"]) >= 1


def test_active_filter_params_only_returns_toggled_filters():
    cfg = make_config(active_filters=["BEAR", "MA"], price_bounce_ticks=3, bear_trend_candles=5,
                      bear_trend_pct=2.0, ma_filter_period=20, ema_fast_period=3, ema_slow_period=9)
    assert active_filter_params(cfg) == {
        "price_bounce_ticks": None, "bear_trend_candles": 5, "bear_trend_pct": 2.0,
        "ma_filter_period": 20, "ema_fast_period": None, "ema_slow_period": None}


def _wavy(n=200):
    return [{"price": 100 + 8 * math.sin(i / 7) + 3 * math.sin(i / 2.3),
             "high": 0, "low": 0, "timestamp": str(i)} for i in range(n)]


def _with_hl(h):
    for p in h:
        p["high"] = p["price"] + 0.4
        p["low"] = p["price"] - 0.4
    return h


def test_ultra_series_depends_on_periods():
    h = _with_hl(_wavy())
    a = sim.compute_ultra_series(h, 14, 9)
    b = sim.compute_ultra_series(h, 5, 3)
    assert len(a) == len(b) == len(h)
    assert a != b
    assert a[-1][0] != b[-1][0]


def test_run_simulation_recomputes_ultra_for_every_period_combo(monkeypatch):
    h = _with_hl(_wavy())
    seen = []
    real = sim.compute_ultra_series

    def spy(history, period, signal_period):
        seen.append((period, signal_period))
        return real(history, period, signal_period)

    monkeypatch.setattr(sim, "compute_ultra_series", spy)
    out = sim.run_simulation(h, "rsi_ultra", 1000.0, stop_loss_range=[1, 1, 1], take_profit_range=None,
                             rsi_ultra_period_range=[5, 14, 9], rsi_ultra_signal_period_range=[3, 9, 6],
                             rsi_ultra_zone_mid_range=[50, 50, 1])
    assert out["status"] == "ok"
    assert set(seen) == {(5, 3), (5, 9), (14, 3), (14, 9)}
    pnls = {(r["rsi_ultra_period"], r["rsi_ultra_signal_period"]): (r["trade_count"], r["total_pnl"])
            for r in out["results"]}
    assert len(set(pnls.values())) > 1, "different periods must give different outcomes"


def test_simulate_single_ultra_uses_configured_periods(monkeypatch):
    h = _with_hl(_wavy())
    seen = []
    real = sim.compute_ultra_series
    monkeypatch.setattr(sim, "compute_ultra_series",
                        lambda hist, p, s: (seen.append((p, s)), real(hist, p, s))[1])
    out = sim.simulate_single(h, "rsi_ultra", 1000.0, 100.0, rsi_ultra_zone_mid=50.0,
                              rsi_ultra_period=6, rsi_ultra_signal_period=4)
    assert out["status"] == "ok"
    assert seen == [(6, 4)]
