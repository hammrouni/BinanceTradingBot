"""Tests for Stories 1.2 and 6.3: BinanceClient wrapper."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Settings
from src.services.binance_client import BinanceClient, BinanceConnectionError
from src.utils.retry import MaxRetriesExceededError


def make_settings(trading_env="testnet"):
    return Settings.model_validate(
        {
            "binance_api_key": "test_key",
            "binance_api_secret": "test_secret",
            "trading_env": trading_env,
        }
    )


@pytest.mark.asyncio
async def test_binance_client_connect_testnet():
    settings = make_settings("testnet")
    client = BinanceClient(settings)
    mock_async_client = AsyncMock()
    with patch("src.services.binance_client.AsyncClient") as mock_cls:
        mock_cls.create = AsyncMock(return_value=mock_async_client)
        await client.connect()
        mock_cls.create.assert_called_once_with(
            api_key="test_key",
            api_secret="test_secret",
            testnet=True,
        )


@pytest.mark.asyncio
async def test_binance_client_connect_live():
    settings = make_settings("live")
    client = BinanceClient(settings)
    mock_async_client = AsyncMock()
    with patch("src.services.binance_client.AsyncClient") as mock_cls:
        mock_cls.create = AsyncMock(return_value=mock_async_client)
        await client.connect()
        mock_cls.create.assert_called_once_with(
            api_key="test_key",
            api_secret="test_secret",
            testnet=False,
        )


@pytest.mark.asyncio
async def test_validate_connection_returns_true_on_success():
    settings = make_settings()
    client = BinanceClient(settings)
    client._client = AsyncMock()
    client._client.get_account = AsyncMock(return_value={"balances": []})
    result = await client.validate_connection()
    assert result is True


@pytest.mark.asyncio
async def test_validate_connection_returns_false_on_exception():
    from binance.exceptions import BinanceAPIException

    settings = make_settings()
    client = BinanceClient(settings)
    mock_inner = AsyncMock()
    mock_inner.get_account = AsyncMock(
        side_effect=BinanceAPIException(MagicMock(status_code=401), 401, '{"msg":"Unauthorized"}')
    )
    client._client = mock_inner
    result = await client.validate_connection()
    assert result is False


@pytest.mark.asyncio
async def test_close_clears_client():
    settings = make_settings()
    client = BinanceClient(settings)
    mock_inner = AsyncMock()
    mock_inner.close_connection = AsyncMock()
    client._client = mock_inner
    await client.close()
    mock_inner.close_connection.assert_called_once()
    assert client._client is None


# ---------------------------------------------------------------------------
# Story 6.3: BinanceConnectionError + get_current_price
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_price_returns_float():
    settings = make_settings()
    client = BinanceClient(settings)
    client._client = AsyncMock()
    with patch("src.services.binance_client.with_retry", new_callable=AsyncMock) as mock_retry:
        mock_retry.return_value = {"price": "42000.50"}
        price = await client.get_current_price("BTCUSDT")
    assert price == 42000.50


@pytest.mark.asyncio
async def test_get_current_price_raises_connection_error_on_max_retries():
    """MaxRetriesExceededError must be re-raised as BinanceConnectionError."""
    settings = make_settings()
    client = BinanceClient(settings)
    client._client = AsyncMock()
    inner_exc = ConnectionError("timeout")
    with patch("src.services.binance_client.with_retry", new_callable=AsyncMock) as mock_retry:
        mock_retry.side_effect = MaxRetriesExceededError(inner_exc)
        with pytest.raises(BinanceConnectionError):
            await client.get_current_price("BTCUSDT")
