"""AI optimizer: candidate sanitising, ranking, verdict, and a tiny end-to-end evaluation."""
import math

import pytest

from src.services import strategy_research as sr


def _rows(n=2400):
    # Oscillating price so RSI crosses its bands.
    out = []
    for i in range(n):
        p = 100 + 3 * math.sin(i / 40) + 0.5 * math.sin(i / 7)
        out.append({"price": p, "open": p, "high": p * 1.001, "low": p * 0.999, "volume": 1.0,
                    "rsi": 50.0 + 30 * math.sin(i / 40), "rsi_ultra_raw": 50.0, "rsi_ultra_signal": 50.0,
                    "timestamp": f"t{i}"})
    return out


def test_sanitize_clamps_and_drops_unknown_keys():
    c = sr.sanitize_candidate({"mode": "RSI", "rsi_oversold": 2, "rsi_overbought": 99, "stop_loss_pct": 50,
                               "take_profit_pct": 0.1, "evil": "rm -rf", "reason": "x" * 500}, ["rsi"])
    assert c["params"] == {"rsi_oversold": 5, "rsi_overbought": 95, "stop_loss_pct": 10, "take_profit_pct": 0.5}
    assert "evil" not in c["params"] and len(c["note"]) == 200 and c["source"] == "web-ai"


@pytest.mark.parametrize("raw", [None, "RSI", {"mode": "scalp"}, {"mode": "RSI"}])
def test_sanitize_rejects_garbage(raw):
    assert sr.sanitize_candidate(raw, ["rsi"]) is None


def test_sanitize_respects_selected_modes_and_bad_filters():
    base = {"mode": "BC", "bc_buy_offset_pct": 1, "bc_sell_offset_pct": 1, "stop_loss_pct": 1, "take_profit_pct": 1}
    assert sr.sanitize_candidate(base, ["rsi"]) is None
    rsi = {"mode": "rsi", "rsi_oversold": 20, "rsi_overbought": 80, "stop_loss_pct": 2, "take_profit_pct": 2,
           "ema_fast_period": 50, "ema_slow_period": 20, "bear_trend_candles": 30}
    p = sr.sanitize_candidate(rsi, ["rsi"])["params"]
    assert "ema_fast_period" not in p and "bear_trend_candles" not in p       # incomplete / inverted filters dropped
    assert sr.sanitize_candidate({**rsi, "rsi_oversold": 45, "rsi_overbought": 55}, ["rsi"])["params"]["rsi_overbought"] == 55


def test_grid_counts_and_dedupe():
    assert len(sr.grid_candidates(["rsi"])) == 4 * 3 * 3 * 4 * 3
    both = sr.grid_candidates(["rsi"]) * 2
    assert len(sr._dedupe(both)) == len(sr.grid_candidates(["rsi"]))


def test_evaluate_rank_and_verdict_end_to_end():
    rows = _rows()
    cands = sr.grid_candidates(["rsi"])[:6] + sr.grid_candidates(["rsi_ultra"])[:2] + sr.grid_candidates(["bc"])[:2]
    scored = sr.evaluate(rows, cands, fee_pct=0.1, trade_usd=100)
    assert len(scored) == 10
    _, n_train = sr._windows(rows)
    ranked = sr.rank(scored, n_train)
    assert [s["rank"] for s in ranked] == list(range(1, 11))
    assert {"train_mean_pct", "holdout_mean_pct", "max_drawdown_pct"} <= set(ranked[0])
    v, _ = sr.verdict(ranked[0])
    assert v in ("CANDIDATE", "NO_EDGE")


def test_verdict_needs_unseen_profit_and_trades():
    good = {"eligible": True, "train_mean_pct": 1.0, "train_profitable_pct": 70, "holdout_mean_pct": 0.5, "holdout_trades": 3}
    assert sr.verdict(good)[0] == "CANDIDATE"
    assert sr.verdict({**good, "holdout_mean_pct": -0.1})[0] == "NO_EDGE"
    assert sr.verdict({**good, "holdout_trades": 1})[0] == "NO_EDGE"
    assert sr.verdict({**good, "train_profitable_pct": 40})[0] == "NO_EDGE"
    assert sr.verdict(None)[0] == "NO_EDGE"


def test_clean_strips_markup_and_control_chars():
    assert sr._clean("<b>Hi</b>\x00 there\n\n<script>x</script>", 50) == "Hi there x"
