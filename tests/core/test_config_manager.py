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
