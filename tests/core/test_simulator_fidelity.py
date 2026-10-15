"""Simulator API on top of the replay harness: BC without look-ahead, net-of-fee metrics, response shapes."""
import math

from src.core import simulator as sim


def wavy(n=400, base=100.0, amp=6.0):
    out = []
    for i in range(n):
        p = base + amp * math.sin(i / 11) + 1.5 * math.sin(i / 3.3)
        out.append({"timestamp": f"2024-01-01T{i // 60:02d}:{i % 60:02d}:00Z", "price": p, "open": p,
                    "high": p + 0.3, "low": p - 0.3, "rsi": 50 + 40 * math.sin(i / 11 + 1.2)})
    return out


def bc_grid(h, **kw):
    return sim.run_simulation(h, "bc", 1000.0, stop_loss_range=[2, 2, 1], take_profit_range=None,
                              bc_buy_offset_range=[1, 3, 1], bc_sell_offset_range=[1, 3, 1],
                              trade_amount_usd=100.0, **kw)


def trades_before(out_events, cutoff):
    return [e for e in out_events if e["timestamp"] < cutoff]


# ── BC look-ahead ─────────────────────────────────────────────────────────────

def test_bc_trades_do_not_depend_on_future_candles():
    h = wavy()
    cut = 250
    future_changed = [dict(p) for p in h]
    for p in future_changed[cut:]:                       # a crash after the cut must not change the past
        p["price"] *= 0.5
        p["open"], p["high"], p["low"] = p["price"], p["price"] + 0.3, p["price"] - 0.3
    kw = dict(mode="bc", initial_balance=1000.0, trade_amount_usd=100.0, stop_loss_pct=2.0,
              bc_buy_offset_pct=1.0, bc_sell_offset_pct=1.0)
    a = sim.simulate_single(h, **kw)
    b = sim.simulate_single(future_changed, **kw)
    cutoff = h[cut]["timestamp"]
    ev_a, ev_b = trades_before(a["events"], cutoff), trades_before(b["events"], cutoff)
    assert ev_a, "expected BC trades before the cut"
    assert ev_a == ev_b


def test_bc_has_no_signal_before_enough_history_for_a_reference():
    h = wavy(20)
    out = sim.simulate_single(h, mode="bc", initial_balance=1000.0, trade_amount_usd=100.0,
                              bc_buy_offset_pct=0.0, bc_sell_offset_pct=50.0)
    assert out["trade_count"] == 0


def test_causal_reference_uses_only_the_past():
    from src.core.replay import causal_reference
    rows = [{"price": float(p)} for p in range(1, 101)]
    ref = causal_reference(rows, lookback=10, min_candles=5)
    assert ref[:5] == [None] * 5
    assert ref[5] == 3.0                                  # median of 1..5
    assert ref[50] == sorted(range(41, 51))[5]            # median of the 10 candles before index 50
    rows2 = rows[:60] + [{"price": 1e9}] * 40
    assert causal_reference(rows2, lookback=10, min_candles=5)[:60] == ref[:60]


def test_bc_grid_rows_keep_their_shape():
    out = bc_grid(wavy())
    assert out["status"] == "ok" and out["results"]
    row = out["results"][0]
    for key in ("bc_buy_offset_pct", "bc_sell_offset_pct", "bc_buy_price", "bc_sell_price", "ref_price", "rank",
                "total_pnl", "win_rate", "trade_count", "max_drawdown_pct"):
        assert key in row
    assert row["bc_buy_price"] < row["ref_price"] < row["bc_sell_price"]


# ── metrics ───────────────────────────────────────────────────────────────────

def test_grid_rows_carry_the_new_metrics():
    h = wavy()
    out = sim.run_simulation(h, "rsi", 1000.0, stop_loss_range=[2, 2, 1], take_profit_range=None,
                             rsi_oversold_range=[30, 40, 10], rsi_overbought_range=[60, 70, 10])
    row = out["results"][0]
    for key in ("sharpe", "profit_factor", "expectancy"):
        assert key in row


def test_win_rate_is_net_of_fees():
    h = [{"timestamp": f"t{i:02d}", "price": p, "rsi": r}
         for i, (p, r) in enumerate(zip([100, 100, 100, 100.05, 100.05], [50, 20, 40, 80, 80]))]
    free = sim.simulate_single(h, "rsi", 1000.0, 100.0, fee_pct=0.0, rsi_oversold=30, rsi_overbought=70)
    paid = sim.simulate_single(h, "rsi", 1000.0, 100.0, fee_pct=0.1, rsi_oversold=30, rsi_overbought=70)
    assert free["win_rate"] == 100 and paid["win_rate"] == 0
    assert paid["total_pnl"] < 0


# ── response shapes (static/js/simulator relies on them) ─────────────────────

def test_simulate_single_shape():
    out = sim.simulate_single(wavy(), "rsi", 1000.0, 100.0, rsi_oversold=40, rsi_overbought=60,
                              stop_loss_pct=2.0)
    assert out["status"] == "ok" and out["mode"] == "rsi" and out["fee_pct"] == 0.1
    for key in ("total_pnl", "total_pnl_pct", "win_rate", "trade_count", "winning_trades", "losing_trades",
                "max_drawdown_pct", "final_balance", "events", "sharpe", "profit_factor", "expectancy"):
        assert key in out
    assert out["events"] and set(out["events"][0]) == {"timestamp", "price", "action", "reason", "pnl"}


def test_simulate_single_errors():
    assert sim.simulate_single([], "rsi", 1000.0, 100.0)["status"] == "error"
    assert sim.simulate_single(wavy(), "nope", 1000.0, 100.0)["status"] == "error"
    assert sim.simulate_single(wavy(), "bc", 1000.0, 100.0)["status"] == "error"   # no BC targets


def test_simulate_single_bc_with_absolute_prices_still_works():
    out = sim.simulate_single(wavy(), "bc", 1000.0, 100.0, bc_buy_price=96.0, bc_sell_price=104.0)
    assert out["status"] == "ok" and out["trade_count"] >= 1


def test_run_simulation_response_shape():
    out = sim.run_simulation(wavy(), "rsi", 1000.0, stop_loss_range=[2, 2, 1], take_profit_range=None,
                             rsi_oversold_range=[30, 40, 10], rsi_overbought_range=[60, 70, 10])
    assert set(out) >= {"status", "mode", "data_points", "total_combinations", "results", "market_history",
                        "fee_pct"}
    assert [r["rank"] for r in out["results"]] == list(range(1, len(out["results"]) + 1))
    pnls = [r["total_pnl"] for r in out["results"]]
    assert pnls == sorted(pnls, reverse=True)


def test_intrabar_flag_changes_outcomes_when_wicks_hit_stops():
    h = wavy()
    for p in h:
        p["low"] = p["price"] - 3.0                      # deep wicks
    kw = dict(mode="rsi", initial_balance=1000.0, trade_amount_usd=100.0, stop_loss_pct=1.0,
              rsi_oversold=40, rsi_overbought=60)
    assert sim.simulate_single(h, intrabar=True, **kw)["total_pnl"] != \
        sim.simulate_single(h, intrabar=False, **kw)["total_pnl"]
