"""Phase 3: chat endpoint."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.routes import chat
from src.core.bot_engine import OrderResult
from src.models.config import TradingConfig
from src.models.trade import TradeRecord


def _request(bot):
    app = SimpleNamespace(state=SimpleNamespace(bot_engine=bot, config=TradingConfig()))
    return SimpleNamespace(app=app)


async def test_get_bot_status_with_open_position_does_not_crash():
    pos = OrderResult("1", "BTCUSDT", 0.001, 50000.0, datetime(2026, 1, 1, tzinfo=timezone.utc))
    bot = SimpleNamespace(state="RUNNING", market_history=[{"price": 50100, "rsi": 40}], open_position=pos,
                          _stop_loss_price=49000, _take_profit_price=51000)
    with patch("src.core.config_manager.load_config", return_value=TradingConfig()):
        out = await chat._execute_tool("get_bot_status", {}, _request(bot))
    assert out["open_position"]["price"] == 50000.0
    json.dumps(out, default=str)


async def test_pnl_summary_tool_uses_calculated_pnl(tmp_path):
    rows = [
        TradeRecord(id="b", executed_at="2026-01-01T10:00:00Z", pair="BTCUSDT", direction="buy", amount_usd=100,
                    quantity=1, entry_price=100, order_id="o", fee_usd=0.1),
        TradeRecord(id="s", executed_at="2026-01-01T11:00:00Z", pair="BTCUSDT", direction="sell", amount_usd=110,
                    quantity=1, entry_price=110, order_id="o", fee_usd=0.1),
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(r.model_dump_json() for r in rows))
    with patch("src.core.trade_reader.TRADES_PATH", path), \
         patch("src.core.config_manager.load_config", return_value=TradingConfig()):
        out = await chat._execute_tool("get_pnl_summary", {}, _request(None))
    assert out["total_pnl_usd"] == pytest.approx(9.8)
    assert out["net_pnl_usd"] == pytest.approx(9.8)


async def test_chat_uses_async_client_with_capped_timeout():
    msg = SimpleNamespace(content="hello", tool_calls=None)
    create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=msg)]))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    ctor = MagicMock(return_value=fake_client)
    settings = SimpleNamespace(llm_base_url="http://x", llm_model="m", llm_api_key="k", llm_timeout=600, llm_max_tokens=100)
    req = _request(None)
    req.app.state.settings = settings
    with patch("openai.AsyncOpenAI", ctor):
        res = await chat.chat_message(chat.ChatRequest(message="hi"), req)
    assert ctor.call_args.kwargs["timeout"] <= 60
    create.assert_awaited()
    assert b"hello" in res.body


async def test_chat_rss_tool_awaits_async_helper():
    with patch("src.mcp_server.tools.tool_read_rss_feed", new=AsyncMock(return_value=[{"title": "t"}])) as m, \
         patch("src.core.config_manager.load_config", return_value=TradingConfig()):
        out = await chat._execute_tool("read_rss_feed", {"url_or_name": "coindesk"}, _request(None))
    assert out == [{"title": "t"}]
    m.assert_awaited_once()
