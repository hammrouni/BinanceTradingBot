"""Tests for Story 1.2: Secure Credential Loading & Binance Connection."""
import pytest
from pydantic import ValidationError

from config.settings import Settings


def make_settings(**overrides):
    defaults = dict(
        prod_binance_api_key="prod_key",
        prod_binance_api_secret="prod_secret",
        test_binance_api_key="test_key",
        test_binance_api_secret="test_secret",
        trading_env="testnet",
    )
    defaults.update(overrides)
    return Settings.model_validate(defaults)


def test_settings_loads_valid_values():
    s = make_settings()
    assert s.test_binance_api_key == "test_key"
    assert s.test_binance_api_secret == "test_secret"
    assert s.trading_env == "testnet"


def test_settings_live_env_accepted():
    s = make_settings(trading_env="live")
    assert s.trading_env == "live"


def test_settings_invalid_trading_env_raises():
    with pytest.raises(ValidationError):
        make_settings(trading_env="staging")


def test_settings_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_missing_api_secret_raises(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
