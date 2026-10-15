"""Pure risk helpers shared by BotEngine and the replay harness."""
from src.core import risk
from tests.core.conftest import make_config


def test_fixed_percent_sl_and_tp_from_entry():
    t = risk.compute_thresholds(100.0, make_config(stop_loss_pct=5.0, take_profit_pct=2.0))
    assert t.stop_loss == 95.0 and t.take_profit == 102.0 and t.support_level is None


def test_trailing_pct_is_the_initial_sl_when_no_fixed_sl():
    t = risk.compute_thresholds(100.0, make_config(stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None))
    assert t.stop_loss == 98.0 and t.take_profit is None


def test_no_sl_no_trailing_means_no_stop():
    t = risk.compute_thresholds(100.0, make_config(stop_loss_pct=None, take_profit_pct=0))
    assert t.stop_loss is None and t.take_profit is None


def test_zero_percent_stop_is_not_disabled():
    cfg = make_config(stop_loss_pct=5.0)
    cfg.stop_loss_pct = 0.0     # validators forbid it on input; the helper must still treat 0 as "stop at entry"
    assert risk.compute_thresholds(100.0, cfg).stop_loss == 100.0


def test_support_level_sl_uses_lowest_low_and_buffer():
    cfg = make_config(sl_lookback_candles=3, sl_buffer_pct=1.0)
    t = risk.compute_thresholds(100.0, cfg, recent_lows=[98.0, 95.0, 99.0, 97.0])
    assert t.support_level == 95.0                  # lows are the caller's last N candles
    assert abs(t.stop_loss - 95.0 * 0.99) < 1e-9


def test_support_level_is_frozen_unless_fresh_entry():
    cfg = make_config(sl_lookback_candles=3, sl_buffer_pct=0.0)
    t = risk.compute_thresholds(100.0, cfg, recent_lows=[10.0], support_level=90.0, fresh_entry=False)
    assert t.support_level == 90.0 and t.stop_loss == 90.0


def test_support_level_without_candles_falls_back_to_percent_sl():
    t = risk.compute_thresholds(100.0, make_config(sl_lookback_candles=3, stop_loss_pct=5.0), recent_lows=[])
    assert t.stop_loss == 95.0 and t.support_level is None


def test_tp_anchor_bc_buy():
    cfg = make_config(take_profit_pct=10.0, tp_anchor="bc_buy", bc_buy_price=50.0, active_modes=["BC"])
    assert abs(risk.compute_thresholds(100.0, cfg).take_profit - 55.0) < 1e-9


def test_ratchet_only_moves_up_and_only_with_trailing_and_sl():
    assert risk.ratchet_trailing(95.0, 110.0, 2.0) == 110.0 * 0.98
    assert risk.ratchet_trailing(95.0, 90.0, 2.0) == 95.0          # never down
    assert risk.ratchet_trailing(95.0, 110.0, None) == 95.0        # no trailing configured
    assert risk.ratchet_trailing(None, 110.0, 2.0) is None         # nothing to ratchet


def test_hit_predicates_are_strict_like_live():
    assert risk.stop_hit(95.0, 94.99) and not risk.stop_hit(95.0, 95.0)
    assert risk.target_hit(102.0, 102.0) and not risk.target_hit(102.0, 101.99)
    assert not risk.stop_hit(None, 1.0) and not risk.target_hit(None, 1e9)
