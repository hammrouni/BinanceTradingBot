"""Simulator routes load candles through the shared history loader."""
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from src.models.config import TradingConfig


def rows(n):
    return [{"timestamp": f"t{i}", "price": 100.0 + (i % 7), "rsi": 50.0, "high": 101.0 + (i % 7),
             "low": 99.0 + (i % 7), "open": 100.0, "rsi_ultra_raw": None, "rsi_ultra_signal": None}
            for i in range(n)]


@pytest.fixture
def bot(monkeypatch):
    b = MagicMock()
    b.market_history = deque(rows(50))
    monkeypatch.setattr(app.state, "bot_engine", b, raising=False)
    monkeypatch.setattr(app.state, "config", TradingConfig(
        trading_pair="ETHUSDT", rsi_ultra_period=7, rsi_ultra_signal_period=4), raising=False)
    return b


async def _post(path, payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.post(f"/api/v1/simulator/{path}", json=payload)


async def test_data_route_uses_shared_loader_with_configured_pair_and_periods(bot):
    loader = AsyncMock(return_value=rows(30))
    with patch("src.api.routes.simulator.load_market_history", loader):
        res = await _post("data", {"historical_days": 2})
    assert res.status_code == 200 and res.json()["data_points"] == 30
    args, kwargs = loader.await_args
    assert args[1] == "ETHUSDT" and args[2] == 2 * 1440
    assert kwargs == {"ultra_period": 7, "ultra_signal_period": 4}


async def test_run_current_fetches_when_bot_history_is_short_and_falls_back_on_failure(bot):
    loader = AsyncMock(side_effect=RuntimeError("binance down"))
    with patch("src.api.routes.simulator.load_market_history", loader):
        res = await _post("run-current", {"historical_days": 1})
    loader.assert_awaited_once()
    # falls back to the bot's own 50 candles instead of failing
    assert res.status_code == 200, res.text
    assert res.json()["used_config"]["data_points"] == 50


async def test_bot_history_is_used_without_fetching_when_it_covers_the_window(bot):
    bot.market_history = deque(rows(1500))
    loader = AsyncMock()
    with patch("src.api.routes.simulator.load_market_history", loader):
        res = await _post("run-current", {"historical_days": 1})
    loader.assert_not_awaited()
    assert res.status_code == 200
