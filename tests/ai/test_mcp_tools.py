"""Phase 3: MCP/chat tool helpers (PnL, RSS, config service)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.mcp_server import tools
from src.models.config import TradingConfig
from src.models.trade import TradeRecord


def _trade(direction, price, ts, fee=0.0, qty=1):
    return TradeRecord(
        id=f"{direction}-{ts}", executed_at=ts, pair="BTCUSDT", direction=direction,
        amount_usd=price * qty, quantity=qty, entry_price=price, order_id="o", fee_usd=fee,
    )


@pytest.fixture
def trades_file(tmp_path):
    path = tmp_path / "trades.jsonl"
    rows = [
        _trade("buy", 100.0, "2026-01-01T10:00:00Z", fee=0.01),
        _trade("sell", 110.0, "2026-01-01T11:00:00Z", fee=0.01),  # +10 - 0.02 = 9.98
        _trade("buy", 100.0, "2026-01-01T12:00:00Z", fee=0.01),
        _trade("sell", 90.0, "2026-01-01T13:00:00Z", fee=0.01),   # -10 - 0.02 = -10.02
    ]
    path.write_text("\n".join(r.model_dump_json() for r in rows) + "\n")
    with patch("src.core.trade_reader.TRADES_PATH", path):
        yield path


def test_recent_trades_have_computed_pnl(trades_file):
    trades = tools.tool_get_recent_trades(limit=10)
    assert trades[0]["direction"] == "sell" and trades[0]["pnl_usd"] == -10.02
    assert trades[2]["pnl_usd"] == 9.98


def test_recent_trades_limit_does_not_break_pairing(trades_file):
    trades = tools.tool_get_recent_trades(limit=1)
    assert len(trades) == 1 and trades[0]["pnl_usd"] == -10.02


def test_pnl_summary_does_not_subtract_fees_twice(trades_file):
    s = tools.tool_get_pnl_summary(limit=50)
    assert s["total_pnl_usd"] == pytest.approx(-0.04)   # already net of fees
    assert s["net_pnl_usd"] == pytest.approx(-0.04)
    assert s["total_fees_usd"] == pytest.approx(0.04)
    assert s["wins"] == 1 and s["losses"] == 1 and s["win_rate_pct"] == 50.0


def test_pnl_summary_empty(tmp_path):
    with patch("src.core.trade_reader.TRADES_PATH", tmp_path / "none.jsonl"):
        assert "message" in tools.tool_get_pnl_summary()


def _mock_async_client(response=None):
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    return client


RSS = (b"<rss><channel><item><title>Hi</title><link>http://x/1</link>"
       b"<pubDate>now</pubDate><description>sum</description></item></channel></rss>")


async def test_rss_uses_async_client_for_known_feed():
    resp = httpx.Response(200, content=RSS, headers={"content-type": "application/rss+xml"},
                          request=httpx.Request("GET", "http://x"))
    client = _mock_async_client(resp)
    with patch("httpx.AsyncClient", return_value=client):
        out = await tools.tool_read_rss_feed("coindesk", 5)
    assert out[0]["title"] == "Hi"
    assert client.get.await_args.args[0] == tools.KNOWN_FEEDS["coindesk"]


async def test_rss_rejects_arbitrary_urls():
    client = _mock_async_client()
    with patch("httpx.AsyncClient", return_value=client):
        for bad in ("http://169.254.169.254/latest/meta-data", "http://localhost:8000/api/v1/config", "file:///etc/passwd"):
            out = await tools.tool_read_rss_feed(bad)
            assert "error" in out and "coindesk" in out["error"]
    client.get.assert_not_awaited()


def _app(bot=None, runtime=None):
    return SimpleNamespace(state=SimpleNamespace(config=TradingConfig(), bot_engine=bot, market_runtime=runtime))


async def test_update_config_goes_through_service_and_updates_live_state():
    bot = MagicMock(open_position=None, refresh_thresholds=AsyncMock())
    app = _app(bot, MagicMock(reconfigure_ultra=MagicMock(return_value=False)))
    tools.bind_app(app)
    try:
        with patch("src.services.config_service.load_config", return_value=TradingConfig()), \
             patch("src.services.config_service.save_config") as save, \
             patch("src.services.config_service.add_rsi_threshold") as hist:
            out = await tools.tool_update_config("rsi_oversold", 22)
    finally:
        tools.bind_app(None)
    assert out == {"success": True, "updated": {"rsi_oversold": 22}}
    assert app.state.config.rsi_oversold == 22
    save.assert_called_once()
    hist.assert_called_once_with("oversold", 22)
    bot.refresh_thresholds.assert_awaited_once()


async def test_update_config_rejects_invalid_value_without_saving():
    tools.bind_app(_app())
    try:
        with patch("src.services.config_service.load_config", return_value=TradingConfig()), \
             patch("src.services.config_service.save_config") as save:
            bad = await tools.tool_update_config("rsi_oversold", 999)
            unknown = await tools.tool_update_config("nope", 1)
    finally:
        tools.bind_app(None)
    assert "error" in bad and "error" in unknown
    save.assert_not_called()


async def test_update_config_without_bound_app_errors():
    tools.bind_app(None)
    assert "error" in await tools.tool_update_config("rsi_oversold", 22)


async def test_mcp_read_rss_feed_has_description():
    from src.mcp_server.server import mcp
    listed = {t.name: t for t in await mcp.list_tools()}
    assert "coindesk" in (listed["read_rss_feed"].description or "")
