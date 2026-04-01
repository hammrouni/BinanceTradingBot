"""Tests for Story 3.1: Trading Configuration Model and File Persistence."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.models.config import TradingConfig
from src.core.config_manager import load_config, save_config


# --- TradingConfig model tests ---

def test_default_values():
    c = TradingConfig()
    assert c.trading_pair == "BTCUSDT"
    assert c.trade_amount_usd == 15.0
    assert c.rsi_oversold == 30
    assert c.rsi_overbought == 70
    assert c.stop_loss_pct == 5.0
    assert c.take_profit_pct == 2.0


def test_rsi_oversold_valid_bounds():
    assert TradingConfig(rsi_oversold=1).rsi_oversold == 1
    assert TradingConfig(rsi_oversold=100).rsi_oversold == 100


def test_rsi_oversold_invalid_raises():
    with pytest.raises(ValidationError):
        TradingConfig(rsi_oversold=0)
    with pytest.raises(ValidationError):
        TradingConfig(rsi_oversold=101)


def test_rsi_overbought_valid_bounds():
    assert TradingConfig(rsi_overbought=1).rsi_overbought == 1
    assert TradingConfig(rsi_overbought=100).rsi_overbought == 100


def test_rsi_overbought_invalid_raises():
    with pytest.raises(ValidationError):
        TradingConfig(rsi_overbought=0)
    with pytest.raises(ValidationError):
        TradingConfig(rsi_overbought=101)


def test_trade_amount_coerced_to_minimum():
    # Coerced to 12.0 minimum
    assert TradingConfig(trade_amount_usd=0).trade_amount_usd == 12.0
    assert TradingConfig(trade_amount_usd=5.0).trade_amount_usd == 12.0
    assert TradingConfig(trade_amount_usd=15.0).trade_amount_usd == 15.0


def test_stop_loss_pct_valid_bounds():
    assert TradingConfig(stop_loss_pct=0.1).stop_loss_pct == 0.1
    assert TradingConfig(stop_loss_pct=50.0).stop_loss_pct == 50.0


def test_stop_loss_pct_invalid_raises():
    with pytest.raises(ValidationError):
        TradingConfig(stop_loss_pct=0.0)
    with pytest.raises(ValidationError):
        TradingConfig(stop_loss_pct=51.0)


def test_take_profit_pct_valid_bounds():
    assert TradingConfig(take_profit_pct=0.0).take_profit_pct == 0.0
    assert TradingConfig(take_profit_pct=0.1).take_profit_pct == 0.1
    assert TradingConfig(take_profit_pct=100.0).take_profit_pct == 100.0


def test_take_profit_pct_invalid_raises():
    with pytest.raises(ValidationError):
        TradingConfig(take_profit_pct=-0.1)
    with pytest.raises(ValidationError):
        TradingConfig(take_profit_pct=100.1)


# --- config_manager load/save tests ---

def test_load_config_creates_defaults_when_missing(tmp_path):
    config_path = tmp_path / "config.json"
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        config = load_config()
    assert config.trading_pair == "BTCUSDT"
    assert config_path.exists()


def test_load_config_reads_existing_file(tmp_path):
    config_path = tmp_path / "config.json"
    data = {"trading_pair": "ETHUSDT", "trade_amount_usd": 15.0,
            "rsi_oversold": 25, "rsi_overbought": 75, "stop_loss_pct": 3.0}
    config_path.write_text(json.dumps(data))
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        config = load_config()
    assert config.trading_pair == "ETHUSDT"
    assert config.rsi_oversold == 25
    assert config.rsi_overbought == 75


def test_save_config_writes_json(tmp_path):
    config_path = tmp_path / "config.json"
    config = TradingConfig(trading_pair="ETHUSDT", trade_amount_usd=20.0,
                           rsi_oversold=35, rsi_overbought=65, stop_loss_pct=4.0)
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(config)
    saved = json.loads(config_path.read_text())
    assert saved["trading_pair"] == "ETHUSDT"
    assert saved["rsi_oversold"] == 35
    assert saved["rsi_overbought"] == 65


def test_save_config_no_credentials(tmp_path):
    config_path = tmp_path / "config.json"
    config = TradingConfig()
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(config)
    saved = json.loads(config_path.read_text())
    assert "binance_api_key" not in saved
    assert "binance_api_secret" not in saved


def test_load_save_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    original = TradingConfig(rsi_oversold=20, rsi_overbought=80, trade_amount_usd=15.0)
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(original)
        loaded = load_config()
    assert loaded.rsi_oversold == 20
    assert loaded.rsi_overbought == 80
    assert loaded.trade_amount_usd == 15.0


# ─── Strategy / Filter field tests ───────────────────────────────────────────

def test_active_modes_default_is_rsi():
    c = TradingConfig()
    assert c.active_modes == ["RSI"]


def test_active_modes_bc():
    c = TradingConfig(active_modes=["BC"], bc_buy_price=67000.0, bc_sell_price=69000.0)
    assert c.active_modes == ["BC"]
    assert c.bc_buy_price == 67000.0
    assert c.bc_sell_price == 69000.0


def test_active_filters_default_is_empty():
    c = TradingConfig()
    assert c.active_filters == []


def test_active_filters_multiple():
    c = TradingConfig(active_filters=["BOUNCE", "BEAR"])
    assert "BOUNCE" in c.active_filters
    assert "BEAR" in c.active_filters


def test_bb_period_optional():
    c = TradingConfig()
    assert c.bb_period is None
    c2 = TradingConfig(bb_period=20)
    assert c2.bb_period == 20


def test_min_bc_price_optional():
    c = TradingConfig()
    assert c.min_bc_price is None
    c2 = TradingConfig(min_bc_price=65000.0)
    assert c2.min_bc_price == 65000.0


def test_active_modes_rsi_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    original = TradingConfig(active_modes=["RSI"], rsi_oversold=28, rsi_overbought=72)
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(original)
        loaded = load_config()
    assert loaded.active_modes == ["RSI"]
    assert loaded.rsi_oversold == 28
    assert loaded.rsi_overbought == 72


def test_active_modes_bc_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    original = TradingConfig(
        active_modes=["BC"],
        bc_buy_price=66500.0,
        bc_sell_price=68000.0,
        stop_loss_pct=3.0,
    )
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(original)
        loaded = load_config()
    assert loaded.active_modes == ["BC"]
    assert loaded.bc_buy_price == 66500.0
    assert loaded.bc_sell_price == 68000.0


def test_active_filters_with_bear_and_bounce_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    original = TradingConfig(
        active_modes=["RSI"],
        active_filters=["BOUNCE", "BEAR"],
        price_bounce_ticks=3,
        bear_trend_candles=5,
        bear_trend_pct=1.5,
    )
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(original)
        loaded = load_config()
    assert loaded.active_filters == ["BOUNCE", "BEAR"]
    assert loaded.price_bounce_ticks == 3
    assert loaded.bear_trend_candles == 5
    assert loaded.bear_trend_pct == 1.5


def test_bb_period_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    original = TradingConfig(active_filters=["BB"], bb_period=20)
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(original)
        loaded = load_config()
    assert loaded.bb_period == 20
    assert "BB" in loaded.active_filters


def test_full_strategy_filter_roundtrip(tmp_path):
    """Full config with strategy + all filters persists and reloads correctly."""
    config_path = tmp_path / "config.json"
    original = TradingConfig(
        trading_pair="ETHUSDT",
        active_modes=["RSI"],
        active_filters=["BB", "BOUNCE", "BEAR"],
        rsi_oversold=25,
        rsi_overbought=75,
        bb_period=14,
        price_bounce_ticks=2,
        bear_trend_candles=4,
        bear_trend_pct=2.0,
        trailing_stop_pct=1.5,
        stop_loss_pct=4.0,
        take_profit_pct=3.0,
    )
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(original)
        loaded = load_config()
    assert loaded.trading_pair == "ETHUSDT"
    assert loaded.active_modes == ["RSI"]
    assert set(loaded.active_filters) == {"BB", "BOUNCE", "BEAR"}
    assert loaded.rsi_oversold == 25
    assert loaded.rsi_overbought == 75
    assert loaded.bb_period == 14
    assert loaded.price_bounce_ticks == 2
    assert loaded.bear_trend_candles == 4
    assert loaded.bear_trend_pct == 2.0
    assert loaded.trailing_stop_pct == 1.5
