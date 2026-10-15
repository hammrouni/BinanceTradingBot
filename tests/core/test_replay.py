"""Replay harness: the simulator runs the live strategy classes and the shared risk helpers."""
from src.core.replay import config_for_sim, replay
from tests.core.conftest import make_config


def rows(prices, rsi=None, spread=0.0):
    return [{"timestamp": f"2024-01-01T00:{i:02d}:00Z", "price": p, "open": p,
             "high": p + spread, "low": p - spread,
             "rsi": None if rsi is None else rsi[i]} for i, p in enumerate(prices)]


def run(h, fee_pct=0.0, initial_balance=1000.0, intrabar=True, **cfg):
    return replay(h, make_config(**cfg), initial_balance=initial_balance, fee_pct=fee_pct, intrabar=intrabar)


# 50 -> oversold edge at index 1 -> buy at the close of candle 1
BUY_RSI = [50, 20, 40, 40, 40]
PRICES5 = [100, 100, 100, 100, 100]


def test_rsi_roundtrip_signal_buy_and_sell():
    h = rows([100, 100, 100, 110, 110], rsi=[50, 20, 40, 80, 80])
    r = run(h, stop_loss_pct=None, take_profit_pct=None)
    assert [(t.reason_in, t.reason_out) for t in r.trades] == [("buy_signal", "signal")]
    t = r.trades[0]
    assert (t.entry_price, t.exit_price) == (100, 110)
    assert abs(t.net_pnl - 1.5) < 1e-9            # 15 USD at +10%


def test_overbought_sells_even_when_take_profit_is_set():
    # live behaviour (P1-17): the old simulator only sold on RSI when TP was unset
    h = rows([100, 100, 100, 101, 101], rsi=[50, 20, 40, 80, 80])
    r = run(h, stop_loss_pct=None, take_profit_pct=50.0)
    assert r.trades[0].reason_out == "signal"


def test_bc_sells_at_target_even_when_take_profit_is_set():
    h = rows([100, 95, 96, 105, 105])
    r = run(h, active_modes=["BC"], bc_buy_price=96.0, bc_sell_price=104.0, stop_loss_pct=None, take_profit_pct=50.0)
    assert [(t.entry_price, t.exit_price, t.reason_out) for t in r.trades] == [(95, 105, "bc_sell_target")]


def test_fees_make_a_small_price_gain_a_losing_trade():
    h = rows([100, 100, 100, 100.05, 100.05], rsi=[50, 20, 40, 80, 80])
    r = run(h, fee_pct=0.1, stop_loss_pct=None, take_profit_pct=None, trade_amount_usd=100.0)
    t = r.trades[0]
    assert t.net_pnl < 0                       # +0.05% price, -0.2% fees
    assert abs((r.final_balance - 1000.0) - t.net_pnl) < 1e-9
    assert t.fees > 0


def test_close_based_stop_loss():
    h = rows([100, 100, 100, 94, 94], rsi=[50, 20, 40, 40, 40])
    r = run(h, stop_loss_pct=5.0, take_profit_pct=None)
    assert [(t.exit_price, t.reason_out) for t in r.trades] == [(94, "stop_loss")]


def test_intrabar_low_triggers_stop_at_the_stop_price():
    h = rows(PRICES5, rsi=BUY_RSI)
    h[3]["low"] = 90.0                           # wick through the 95 stop, close back at 100
    r = run(h, stop_loss_pct=5.0, take_profit_pct=None)
    assert [(t.exit_price, t.reason_out) for t in r.trades] == [(95.0, "stop_loss")]
    assert r.trades[0].exit_time == h[3]["timestamp"]


def test_without_intrabar_the_wick_is_ignored():
    h = rows(PRICES5, rsi=BUY_RSI)
    h[3]["low"] = 90.0
    r = run(h, intrabar=False, stop_loss_pct=5.0, take_profit_pct=None)
    assert [t.reason_out for t in r.trades] == ["end_of_data"]


def test_intrabar_gap_below_stop_fills_at_the_open():
    h = rows(PRICES5, rsi=BUY_RSI)
    h[3].update(open=92.0, low=91.0)
    r = run(h, stop_loss_pct=5.0, take_profit_pct=None)
    assert r.trades[0].exit_price == 92.0


def test_intrabar_high_triggers_take_profit_at_target():
    h = rows(PRICES5, rsi=BUY_RSI)
    h[3]["high"] = 110.0
    r = run(h, stop_loss_pct=5.0, take_profit_pct=2.0)
    assert [(t.exit_price, t.reason_out) for t in r.trades] == [(102.0, "take_profit")]


def test_same_candle_touching_stop_and_target_takes_the_stop():
    h = rows(PRICES5, rsi=BUY_RSI)
    h[3].update(high=110.0, low=90.0)
    r = run(h, stop_loss_pct=5.0, take_profit_pct=2.0)
    assert [(t.exit_price, t.reason_out) for t in r.trades] == [(95.0, "stop_loss")]


def test_entry_candle_is_not_subject_to_intrabar_exits():
    h = rows(PRICES5, rsi=BUY_RSI)
    h[1].update(low=50.0, high=200.0)            # the wicky candle is the one that triggers the buy
    r = run(h, stop_loss_pct=5.0, take_profit_pct=2.0)
    assert [t.reason_out for t in r.trades] == ["end_of_data"]


def test_trailing_stop_ratchets_then_fires_pessimistically():
    # entry 100, trail 2%: a candle reaching 110 lifts the stop to 107.8; its low of 105 then hits it
    h = rows(PRICES5, rsi=BUY_RSI)
    h[3].update(high=110.0, low=105.0)
    r = run(h, stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    t = r.trades[0]
    assert t.reason_out == "stop_loss" and abs(t.exit_price - 107.8) < 1e-9


def test_open_position_is_closed_at_the_last_price():
    h = rows([100, 100, 100, 103], rsi=[50, 20, 40, 40])
    r = run(h, stop_loss_pct=None, take_profit_pct=None)
    assert r.trades[0].reason_out == "end_of_data" and r.trades[0].exit_price == 103


def test_buy_needs_enough_balance():
    h = rows([100, 100, 100, 110, 110], rsi=[50, 20, 40, 80, 80])
    r = run(h, initial_balance=10.0, trade_amount_usd=15.0, stop_loss_pct=None, take_profit_pct=None)
    assert r.trades == [] and r.final_balance == 10.0


def test_bear_filter_blocks_the_buy():
    h = rows([100, 99, 98, 97, 96, 95], rsi=[50, 50, 50, 50, 50, 20])
    assert len(run(h, stop_loss_pct=None, take_profit_pct=None).trades) == 1
    blocked = run(h, stop_loss_pct=None, take_profit_pct=None,
                  active_filters=["BEAR"], bear_trend_candles=5, bear_trend_pct=1.0)
    assert blocked.trades == []


def test_support_level_stop_uses_recent_candle_lows():
    h = rows(PRICES5, rsi=BUY_RSI)
    h[0]["low"], h[1]["low"] = 97.0, 98.0
    h[2]["low"] = 98.5
    h[3]["low"] = 97.5                           # support = min(lows of the 3 candles ending at the entry) = 97
    r = run(h, sl_lookback_candles=3, sl_buffer_pct=0.0, stop_loss_pct=None, take_profit_pct=None)
    assert r.trades[0].reason_out == "end_of_data"
    h[3]["low"] = 96.0
    r = run(h, sl_lookback_candles=3, sl_buffer_pct=0.0, stop_loss_pct=None, take_profit_pct=None)
    assert (r.trades[0].exit_price, r.trades[0].reason_out) == (97.0, "stop_loss")


def test_events_have_the_shape_the_chart_expects():
    h = rows([100, 100, 100, 110, 110], rsi=[50, 20, 40, 80, 80])
    r = run(h, stop_loss_pct=None, take_profit_pct=None)
    assert [e["action"] for e in r.events] == ["buy", "sell"]
    assert set(r.events[0]) == {"timestamp", "price", "action", "reason", "pnl"}
    assert r.events[0]["pnl"] is None and r.events[1]["pnl"] == round(r.trades[0].net_pnl, 2)


def test_drawdown_is_measured_on_the_equity_curve():
    h = rows([100, 100, 100, 90, 100, 100], rsi=[50, 20, 40, 40, 40, 40])
    r = run(h, initial_balance=100.0, trade_amount_usd=50.0, stop_loss_pct=None, take_profit_pct=None)
    assert abs(r.max_drawdown_pct - 5.0) < 1e-6   # 50 USD position loses 10% = 5 USD of 100


def test_config_for_sim_maps_params_to_live_config():
    cfg = config_for_sim("rsi", trade_amount_usd=5.0, rsi_oversold=25, rsi_overbought=75,
                         stop_loss_pct=1.0, take_profit_pct=None, trailing_stop_pct=None,
                         price_bounce_ticks=2, bear_trend_candles=None, bear_trend_pct=None,
                         ma_filter_period=None, ema_fast_period=3, ema_slow_period=9)
    assert cfg.active_modes == ["RSI"] and cfg.trade_amount_usd == 5.0   # not coerced to the live 12 USD floor
    assert sorted(cfg.active_filters) == ["BOUNCE", "EMA_TREND"]
    assert config_for_sim("bc").active_modes == ["BC"]
    assert config_for_sim("rsi_ultra").active_modes == ["RSI_ULTRA"]
