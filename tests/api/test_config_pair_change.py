"""PUT /config on a trading-pair change: 409 with an open position, otherwise restart the market feed."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from src.models.config import TradingConfig


@pytest.fixture
def runtime(monkeypatch):
    bot = MagicMock()
    bot.open_position = None
    bot.refresh_thresholds = AsyncMock()
    rt = MagicMock()
    rt.change_pair = AsyncMock()
    rt.reconfigure_ultra = MagicMock(return_value=False)
    monkeypatch.setattr(app.state, "bot_engine", bot, raising=False)
    monkeypatch.setattr(app.state, "market_runtime", rt, raising=False)
    return bot, rt


async def _put(payload):
    with patch("src.services.config_service.load_config", return_value=TradingConfig()), \
         patch("src.services.config_service.save_config") as save:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.put("/api/v1/config", json=payload)
    return res, save


async def test_pair_change_with_open_position_is_refused(runtime):
    bot, rt = runtime
    bot.open_position = object()
    res, save = await _put({"trading_pair": "ETHUSDT"})
    assert res.status_code == 409
    assert "position" in str(res.json()).lower()
    save.assert_not_called()
    rt.change_pair.assert_not_awaited()


async def test_pair_change_restarts_the_market_feed(runtime):
    _, rt = runtime
    res, save = await _put({"trading_pair": "ETHUSDT"})
    assert res.status_code == 200
    rt.change_pair.assert_awaited_once()
    assert rt.change_pair.await_args.args[0].trading_pair == "ETHUSDT"
    save.assert_called_once()


async def test_same_pair_does_not_touch_the_feed(runtime):
    _, rt = runtime
    res, _ = await _put({"trading_pair": "BTCUSDT", "rsi_oversold": 25})
    assert res.status_code == 200
    rt.change_pair.assert_not_awaited()


async def test_feed_failure_keeps_the_old_config(runtime):
    _, rt = runtime
    rt.change_pair.side_effect = RuntimeError("binance down")
    res, save = await _put({"trading_pair": "ETHUSDT"})
    assert res.status_code == 502
    save.assert_not_called()


async def test_ultra_period_change_reconfigures_the_calculator(runtime):
    _, rt = runtime
    res, _ = await _put({"rsi_ultra_period": 7})
    assert res.status_code == 200
    rt.reconfigure_ultra.assert_called_once()
    assert rt.reconfigure_ultra.call_args.args[0].rsi_ultra_period == 7
