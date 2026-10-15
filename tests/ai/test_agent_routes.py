"""Phase 3: agent proxy payloads."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

from src.api.routes import agent
from src.models.config import TradingConfig
from src.models.rsi_history import RsiThresholdHistoryEntry
from src.models.trade import TradeRecord
from src.services.candle_summary import summarize_candles, window_volatility_pct


def _history(n=1440, base=100.0):
    out = []
    for i in range(n):
        p = base + (i % 20) * 0.1
        out.append({"timestamp": f"t{i}", "price": p, "open": p, "high": p + 0.2, "low": p - 0.2, "rsi": 50})
    return out


def _request(history, position=None):
    bot = SimpleNamespace(market_history=history, open_position=position,
                          take_profit_price=105.0, stop_loss_price=95.0)
    app = SimpleNamespace(state=SimpleNamespace(bot_engine=bot, config=TradingConfig()))
    return SimpleNamespace(app=app)


@pytest.fixture
def captured():
    with patch.object(agent, "_call_agent_service", new=AsyncMock(return_value=JSONResponse({"ok": 1}))) as m:
        yield m


def test_summary_limits_candles_and_computes_features():
    out = summarize_candles(_history())
    assert len(out["candles"]) == 60
    s = out["summary"]
    assert s["count"] == 1440 and s["atr_14"] > 0 and s["range_high"] > s["range_low"]
    assert set(out["candles"][0]) >= {"open", "high", "low", "close"}


def test_summary_finds_swings():
    h = _history(30)
    h[10]["high"] = 200.0
    h[20]["low"] = 1.0
    s = summarize_candles(h)["summary"]
    assert 200.0 in s["swing_highs"] and 1.0 in s["swing_lows"]


def test_summary_empty():
    assert summarize_candles([]) == {"summary": {"count": 0}, "candles": []}


def test_window_volatility_uses_highs_and_lows():
    assert window_volatility_pct([{"price": 100, "high": 110, "low": 100}] * 11) == 10.0


async def test_trade_health_sends_summarised_candles(captured):
    pos = SimpleNamespace(price=100.0, quantity=1.0)
    with patch.object(agent, "tool_get_recent_trades", return_value=[]):
        await agent.trade_health_analyze(_request(_history(), pos))
    payload = captured.await_args.args[1]
    assert len(payload["candles_24h"]) == 60
    assert payload["candle_summary"]["count"] == 1440


async def test_sltp_sends_summarised_candles(captured):
    await agent.sltp_optimizer_analyze(_request(_history()))
    payload = captured.await_args.args[1]
    assert len(payload["candles_24h"]) == 60 and "atr_14" in payload["candle_summary"]


async def test_fee_watchdog_reads_fee_usd_and_real_pnl(captured, tmp_path):
    rows = [
        TradeRecord(id="b", executed_at="2026-01-01T10:00:00Z", pair="BTCUSDT", direction="buy", amount_usd=100,
                    quantity=1, entry_price=100, order_id="o", fee_usd=0.1, reason="manual"),
        TradeRecord(id="s", executed_at="2026-01-01T11:00:00Z", pair="BTCUSDT", direction="sell", amount_usd=110,
                    quantity=1, entry_price=110, order_id="o", fee_usd=0.1),
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(r.model_dump_json() for r in rows))
    with patch("src.core.trade_reader.TRADES_PATH", path):
        await agent.fee_watchdog_analyze(_request([]))
    payload = captured.await_args.args[1]
    assert payload["total_fees_usd"] == pytest.approx(0.2)
    assert payload["total_pnl_usd"] == pytest.approx(9.8)
    assert payload["manual_trade_count"] == 1


async def test_config_auditor_true_volatility_and_threshold_history(captured):
    h = _history()
    h[0]["low"] = 90.0  # outside the last 60 candles: only a real 24h window sees it
    entries = [RsiThresholdHistoryEntry(type="oversold", value=25)]
    with patch.object(agent, "get_rsi_threshold_history", return_value=entries):
        await agent.config_auditor_analyze(_request(h))
    payload = captured.await_args.args[1]
    assert payload["volatility_24h_pct"] > 10
    assert payload["volatility_window_minutes"] == 1440
    assert payload["rsi_threshold_history"][0]["value"] == 25
