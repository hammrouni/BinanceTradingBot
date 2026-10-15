"""Phase 2 config model: legacy migration, BB removal, tp_anchor, BC sizing, min_move validation."""
import json

import pytest
from pydantic import ValidationError

import src.core.config_manager as cm
from src.models.config import TradingConfig


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(cm, "CONFIG_PATH", p)
    return p


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


# -- Bollinger bands are gone ----------------------------------------------------

def test_bb_is_not_a_filter_or_a_field():
    c = TradingConfig(active_filters=["BB", "BOUNCE", "bear", "BOUNCE", "NOPE"], bb_period=20)
    assert c.active_filters == ["BOUNCE", "BEAR"]
    assert not hasattr(c, "bb_period")
    assert "bb_period" not in c.model_dump()


# -- min_bc_price migration ------------------------------------------------------

def test_legacy_min_bc_price_moves_into_bc_buy_price_once(cfg_path):
    _write(cfg_path, {"min_bc_price": 65000.0, "active_modes": ["BC"], "bc_sell_price": 70000.0,
                      "trade_amount_usd": 20.0, "take_profit_pct": 2.0})
    c = cm.load_config()
    assert c.bc_buy_price == 65000.0
    assert c.tp_anchor == "bc_buy"                      # BC users keep the BC-anchored take profit
    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "min_bc_price" not in saved and saved["bc_buy_price"] == 65000.0
    assert cm.load_config().bc_buy_price == 65000.0     # idempotent


def test_legacy_min_bc_price_does_not_anchor_tp_in_rsi_mode(cfg_path):
    _write(cfg_path, {"min_bc_price": 65000.0, "active_modes": ["RSI"]})
    c = cm.load_config()
    assert c.tp_anchor == "entry"


def test_existing_bc_buy_price_wins_over_legacy_value(cfg_path):
    _write(cfg_path, {"min_bc_price": 1.0, "bc_buy_price": 64000.0})
    assert cm.load_config().bc_buy_price == 64000.0


def test_min_bc_price_is_no_longer_a_model_field():
    assert not hasattr(TradingConfig(), "min_bc_price")


def test_tp_anchor_bc_buy_requires_a_bc_buy_price():
    with pytest.raises(ValidationError):
        TradingConfig(tp_anchor="bc_buy")
    assert TradingConfig(tp_anchor="bc_buy", bc_buy_price=60000.0).tp_anchor == "bc_buy"
    with pytest.raises(ValidationError):
        TradingConfig(tp_anchor="somewhere")


# -- BC sizing -------------------------------------------------------------------

def test_bc_mode_requires_amount_or_full_balance_flag():
    with pytest.raises(ValidationError, match="bc_use_full_balance"):
        TradingConfig(active_modes=["BC"], trade_amount_usd=None, bc_buy_price=1.0, bc_sell_price=2.0)
    ok = TradingConfig(active_modes=["BC"], trade_amount_usd=None, bc_use_full_balance=True)
    assert ok.bc_use_full_balance is True
    assert TradingConfig(active_modes=["BC"], trade_amount_usd=20.0).trade_amount_usd == 20.0


def test_non_bc_modes_may_leave_the_amount_empty():
    assert TradingConfig(active_modes=["RSI"], trade_amount_usd=None).trade_amount_usd is None
    assert TradingConfig().bc_use_full_balance is False


# -- min_move_pct ----------------------------------------------------------------

def test_min_move_pct_above_take_profit_is_rejected():
    with pytest.raises(ValidationError, match="min_move_pct"):
        TradingConfig(take_profit_pct=1.0, min_move_pct=2.0)
    with pytest.raises(ValidationError, match="min_move_pct"):
        TradingConfig(take_profit_pct=None, min_move_pct=0.5)
    with pytest.raises(ValidationError, match="min_move_pct"):
        TradingConfig(take_profit_pct=0, min_move_pct=0.5)
    assert TradingConfig(take_profit_pct=2.0, min_move_pct=2.0).min_move_pct == 2.0
    assert TradingConfig(take_profit_pct=None, min_move_pct=None).min_move_pct is None


def test_stored_config_with_conflicting_min_move_is_repaired_not_reset(cfg_path):
    _write(cfg_path, {"take_profit_pct": 1.0, "min_move_pct": 2.0, "rsi_oversold": 25})
    c = cm.load_config()
    assert c.rsi_oversold == 25              # the rest of the config survives
    assert c.min_move_pct is None
    assert not list(cfg_path.parent.glob("*.corrupt-*"))
