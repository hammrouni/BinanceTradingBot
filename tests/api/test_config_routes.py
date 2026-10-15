"""Tests for Story 3.2: Configuration REST API."""
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from src.models.config import TradingConfig


def default_config():
    return TradingConfig()


@pytest.mark.asyncio
async def test_get_config_returns_defaults():
    with patch("src.api.routes.config.load_config", return_value=default_config()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/api/v1/config")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["data"]["trading_pair"] == "BTCUSDT"
    assert body["data"]["rsi_oversold"] == 30
    assert body["data"]["rsi_overbought"] == 70


@pytest.mark.asyncio
async def test_put_config_valid_updates():
    new_data = {
        "trading_pair": "ETHUSDT",
        "trade_amount_usd": 15.0,
        "rsi_oversold": 25,
        "rsi_overbought": 75,
        "stop_loss_pct": 3.0,
        "take_profit_pct": 2.5,
    }
    with patch("src.services.config_service.save_config") as mock_save:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.put("/api/v1/config", json=new_data)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["data"]["rsi_oversold"] == 25
    assert body["data"]["rsi_overbought"] == 75
    assert body["data"]["take_profit_pct"] == 2.5
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_put_config_invalid_rsi_returns_422():
    invalid_data = {
        "trading_pair": "BTCUSDT",
        "trade_amount_usd": 15.0,
        "rsi_oversold": 150,
        "stop_loss_pct": 5.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/v1/config", json=invalid_data)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_put_config_amount_coerced_returns_200():
    low_data = {
        "trading_pair": "BTCUSDT",
        "trade_amount_usd": 5,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 2.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/v1/config", json=low_data)
    assert res.status_code == 200
    body = res.json()
    assert body["data"]["trade_amount_usd"] == 12.0
