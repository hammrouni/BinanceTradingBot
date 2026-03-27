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
    assert c.trade_amount_usd == 5.0
    assert c.rsi_threshold == 30
    assert c.stop_loss_pct == 5.0


def test_rsi_threshold_valid_bounds():
    assert TradingConfig(rsi_threshold=1).rsi_threshold == 1
    assert TradingConfig(rsi_threshold=100).rsi_threshold == 100


def test_rsi_threshold_invalid_raises():
    with pytest.raises(ValidationError):
        TradingConfig(rsi_threshold=0)
    with pytest.raises(ValidationError):
        TradingConfig(rsi_threshold=101)


def test_trade_amount_must_be_positive():
    with pytest.raises(ValidationError):
        TradingConfig(trade_amount_usd=0)
    with pytest.raises(ValidationError):
        TradingConfig(trade_amount_usd=-1.0)


def test_stop_loss_pct_valid_bounds():
    assert TradingConfig(stop_loss_pct=0.1).stop_loss_pct == 0.1
    assert TradingConfig(stop_loss_pct=50.0).stop_loss_pct == 50.0


def test_stop_loss_pct_invalid_raises():
    with pytest.raises(ValidationError):
        TradingConfig(stop_loss_pct=0.0)
    with pytest.raises(ValidationError):
        TradingConfig(stop_loss_pct=51.0)


# --- config_manager load/save tests ---

def test_load_config_creates_defaults_when_missing(tmp_path):
    config_path = tmp_path / "config.json"
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        config = load_config()
    assert config.trading_pair == "BTCUSDT"
    assert config_path.exists()


def test_load_config_reads_existing_file(tmp_path):
    config_path = tmp_path / "config.json"
    data = {"trading_pair": "ETHUSDT", "trade_amount_usd": 10.0,
            "rsi_threshold": 25, "stop_loss_pct": 3.0}
    config_path.write_text(json.dumps(data))
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        config = load_config()
    assert config.trading_pair == "ETHUSDT"
    assert config.rsi_threshold == 25


def test_save_config_writes_json(tmp_path):
    config_path = tmp_path / "config.json"
    config = TradingConfig(trading_pair="ETHUSDT", trade_amount_usd=20.0,
                           rsi_threshold=35, stop_loss_pct=4.0)
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(config)
    saved = json.loads(config_path.read_text())
    assert saved["trading_pair"] == "ETHUSDT"
    assert saved["rsi_threshold"] == 35


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
    original = TradingConfig(rsi_threshold=20, trade_amount_usd=15.0)
    with patch("src.core.config_manager.CONFIG_PATH", config_path):
        save_config(original)
        loaded = load_config()
    assert loaded.rsi_threshold == 20
    assert loaded.trade_amount_usd == 15.0
