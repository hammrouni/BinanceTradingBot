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
    assert body["data"]["rsi_threshold"] == 30


@pytest.mark.asyncio
async def test_put_config_valid_updates():
    new_data = {
        "trading_pair": "ETHUSDT",
        "trade_amount_usd": 10.0,
        "rsi_threshold": 25,
        "stop_loss_pct": 3.0,
    }
    with patch("src.api.routes.config.save_config") as mock_save:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.put("/api/v1/config", json=new_data)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["data"]["rsi_threshold"] == 25
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_put_config_invalid_rsi_returns_422():
    invalid_data = {
        "trading_pair": "BTCUSDT",
        "trade_amount_usd": 5.0,
        "rsi_threshold": 150,
        "stop_loss_pct": 5.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/v1/config", json=invalid_data)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_put_config_invalid_amount_returns_422():
    invalid_data = {
        "trading_pair": "BTCUSDT",
        "trade_amount_usd": 0,
        "rsi_threshold": 30,
        "stop_loss_pct": 5.0,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/v1/config", json=invalid_data)
    assert res.status_code == 422
