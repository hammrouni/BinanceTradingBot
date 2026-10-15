"""Tests for Stories 1.2 and 6.3: BinanceClient wrapper."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Settings
from src.services.binance_client import BinanceClient, BinanceConnectionError, BinanceOrderError
from src.utils.retry import MaxRetriesExceededError


def make_settings(trading_env="testnet"):
    return Settings.model_validate(
        {
            "prod_binance_api_key": "prod_key",
            "prod_binance_api_secret": "prod_secret",
            "test_binance_api_key": "test_key",
            "test_binance_api_secret": "test_secret",
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
        mock_cls.create.assert_any_call(
            api_key="test_key",
            api_secret="test_secret",
            testnet=True,
        )
        mock_cls.create.assert_any_call(
            api_key="prod_key",
            api_secret="prod_secret",
            testnet=False,
        )


@pytest.mark.asyncio
async def test_binance_client_connect_live():
    settings = make_settings("live")
    client = BinanceClient(settings)
    mock_async_client = AsyncMock()
    with patch("src.services.binance_client.AsyncClient") as mock_cls:
        mock_cls.create = AsyncMock(return_value=mock_async_client)
        await client.connect()
        mock_cls.create.assert_any_call(
            api_key="prod_key",
            api_secret="prod_secret",
            testnet=False,
        )


@pytest.mark.asyncio
async def test_validate_connection_returns_true_on_success():
    settings = make_settings()
    client = BinanceClient(settings)
    client._data_client = AsyncMock()
    client._trading_client = AsyncMock()
    client._data_client.get_account = AsyncMock(return_value={"balances": []})
    client._trading_client.get_account = AsyncMock(return_value={"balances": []})
    result = await client.validate_connection()
    assert result is True


@pytest.mark.asyncio
async def test_validate_connection_returns_false_on_exception():
    from binance.exceptions import BinanceAPIException

    settings = make_settings()
    client = BinanceClient(settings)
    client._data_client = AsyncMock()
    client._data_client.get_account = AsyncMock(
        side_effect=BinanceAPIException(MagicMock(status_code=401), 401, '{"msg":"Unauthorized"}')
    )
    result = await client.validate_connection()
    assert result is False


@pytest.mark.asyncio
async def test_close_clears_client():
    settings = make_settings()
    client = BinanceClient(settings)
    mock_trading = AsyncMock()
    mock_data = AsyncMock()
    client._trading_client = mock_trading
    client._data_client = mock_data
    await client.close()
    mock_trading.close_connection.assert_called_once()
    mock_data.close_connection.assert_called_once()
    assert client._trading_client is None
    assert client._data_client is None


# ---------------------------------------------------------------------------
# Story 6.3: BinanceConnectionError + get_current_price
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_price_returns_float():
    settings = make_settings()
    client = BinanceClient(settings)
    client._data_client = AsyncMock()
    with patch("src.services.binance_client.with_retry", new_callable=AsyncMock) as mock_retry:
        mock_retry.return_value = {"price": "42000.50"}
        price = await client.get_current_price("BTCUSDT")
    assert price == 42000.50


@pytest.mark.asyncio
async def test_get_current_price_raises_connection_error_on_max_retries():
    """MaxRetriesExceededError must be re-raised as BinanceConnectionError."""
    settings = make_settings()
    client = BinanceClient(settings)
    client._data_client = AsyncMock()
    inner_exc = ConnectionError("timeout")
    with patch("src.services.binance_client.with_retry", new_callable=AsyncMock) as mock_retry:
        mock_retry.side_effect = MaxRetriesExceededError(inner_exc)
        with pytest.raises(BinanceConnectionError):
            await client.get_current_price("BTCUSDT")


@pytest.mark.asyncio
async def test_get_base_asset_balance_returns_free_locked_total():
    settings = MagicMock()
    client = BinanceClient(settings)
    client._data_client = AsyncMock()
    client._data_client.get_symbol_info = AsyncMock(return_value={"baseAsset": "BTC", "filters": []})
    client._trading_client = AsyncMock()
    client._trading_client.get_account = AsyncMock(return_value={
        "balances": [{"asset": "BTC", "free": "0.001", "locked": "0.0002"}]
    })

    balance = await client.get_base_asset_balance("BTCUSDT")

    assert balance["free"] == pytest.approx(0.001)
    assert balance["locked"] == pytest.approx(0.0002)
    assert balance["total"] == pytest.approx(0.0012)


@pytest.mark.asyncio
async def test_execute_market_sell_caps_to_available_balance():
    settings = MagicMock()
    client = BinanceClient(settings)
    client._trading_client = AsyncMock()
    client._trading_client.get_asset_balance = AsyncMock(return_value={"free": "0.00016", "locked": "0"})
    client._trading_client.create_order = AsyncMock(return_value={
        "orderId": 123,
        "executedQty": "0.00016",
        "fills": [{"qty": "0.00016", "price": "67000"}],
    })
    client._data_client = AsyncMock()
    client._data_client.get_symbol_info = AsyncMock(return_value={
        "baseAsset": "BTC",
        "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
            {"filterType": "NOTIONAL", "minNotional": "10"},
        ],
    })
    client.get_current_price = AsyncMock(return_value=71000.0)

    result = await client.execute_market_sell("BTCUSDT", 0.00017)

    client._trading_client.create_order.assert_awaited_once_with(
        symbol="BTCUSDT",
        side="SELL",
        type="MARKET",
        quantity="0.00016",
    )
    assert result.quantity == 0.00016


@pytest.mark.asyncio
async def test_execute_market_sell_raises_when_no_available_balance():
    settings = MagicMock()
    client = BinanceClient(settings)
    client._trading_client = AsyncMock()
    client._trading_client.get_asset_balance = AsyncMock(return_value={"free": "0", "locked": "0"})
    client._data_client = AsyncMock()
    client._data_client.get_symbol_info = AsyncMock(return_value={
        "baseAsset": "BTC",
        "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00001"}],
    })

    with pytest.raises(BinanceOrderError, match="Insufficient available balance"):
        await client.execute_market_sell("BTCUSDT", 0.00017)


@pytest.mark.asyncio
async def test_execute_market_sell_raises_unsellable_dust_below_step_size():
    settings = MagicMock()
    client = BinanceClient(settings)
    client._trading_client = AsyncMock()
    client._trading_client.get_asset_balance = AsyncMock(return_value={"free": "0.0000083", "locked": "0"})
    client._data_client = AsyncMock()
    client._data_client.get_symbol_info = AsyncMock(return_value={
        "baseAsset": "BTC",
        "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00001"}],
    })

    with pytest.raises(BinanceOrderError, match="UNSELLABLE_DUST"):
        await client.execute_market_sell("BTCUSDT", 0.00017)


def _eth_btc_client():
    client = BinanceClient(MagicMock())
    client._data_client = AsyncMock()
    client._data_client.get_symbol_info = AsyncMock(return_value={
        "symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC",
        "quoteAssetPrecision": 8, "filters": [],
    })
    client._trading_client = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_assets_come_from_symbol_info_not_string_replace():
    client = BinanceClient(MagicMock())
    client._data_client = AsyncMock()
    client._data_client.get_symbol_info = AsyncMock(return_value={
        "symbol": "USDTTRY", "baseAsset": "USDT", "quoteAsset": "TRY", "filters": [],
    })
    assert await client._get_assets("USDTTRY") == ("USDT", "TRY")


@pytest.mark.asyncio
async def test_sell_non_usdt_pair_reads_balance_of_real_base_asset():
    client = _eth_btc_client()
    client._trading_client.get_asset_balance = AsyncMock(return_value={"free": "0"})
    with pytest.raises(BinanceOrderError):
        await client.execute_market_sell("ETHBTC", 1.0)
    client._trading_client.get_asset_balance.assert_awaited_once_with(asset="ETH")


@pytest.mark.asyncio
async def test_market_buy_rounds_quote_order_qty_to_quote_precision():
    client = BinanceClient(MagicMock())
    client._data_client = AsyncMock()
    client._data_client.get_symbol_info = AsyncMock(return_value={
        "symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
        "quoteAssetPrecision": 2, "filters": [],
    })
    client._trading_client = AsyncMock()
    client._trading_client.create_order = AsyncMock(return_value={
        "orderId": 1, "executedQty": "0.0002", "fills": [
            {"price": "50000", "qty": "0.0002", "commission": "0", "commissionAsset": "USDT"}],
    })
    await client.execute_market_buy("BTCUSDT", 10.129999)
    kwargs = client._trading_client.create_order.call_args.kwargs
    assert kwargs["quoteOrderQty"] == "10.12"


@pytest.mark.asyncio
async def test_fee_in_base_asset_of_non_usdt_pair_converted_with_trade_price():
    client = _eth_btc_client()
    fee = await client._calculate_fees_usd(
        [{"commission": "0.001", "commissionAsset": "ETH"}], 0.05, "ETHBTC")
    assert fee == pytest.approx(0.00005)
