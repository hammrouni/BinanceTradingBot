"""Tests for Story 2.4: WebSocket broadcaster and market processor."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.websocket import ConnectionManager
from src.core.market_processor import market_processor
from src.core.rsi_calculator import RsiCalculator
from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.models.market import KlineData


def make_kline(close: float = 50000.0) -> KlineData:
    return KlineData(
        open_time=0, open=close, high=close, low=close,
        close=close, volume=1.0, close_time=0, is_closed=True
    )


# --- ConnectionManager tests ---

@pytest.mark.asyncio
async def test_connection_manager_connect_adds_client():
    mgr = ConnectionManager()
    mock_ws = AsyncMock()
    await mgr.connect(mock_ws)
    assert mock_ws in mgr.active
    mock_ws.accept.assert_called_once()


def test_connection_manager_disconnect_removes_client():
    mgr = ConnectionManager()
    mock_ws = MagicMock()
    mgr.active.add(mock_ws)
    mgr.disconnect(mock_ws)
    assert mock_ws not in mgr.active


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_clients():
    mgr = ConnectionManager()
    ws1, ws2 = AsyncMock(), AsyncMock()
    mgr.active = {ws1, ws2}
    await mgr.broadcast({"type": "test"})
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()
    sent = json.loads(ws1.send_text.call_args[0][0])
    assert sent["type"] == "test"


@pytest.mark.asyncio
async def test_broadcast_no_clients_does_not_raise():
    mgr = ConnectionManager()
    await mgr.broadcast({"type": "test"})  # Should not raise


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connection():
    mgr = ConnectionManager()
    dead_ws = AsyncMock()
    dead_ws.send_text.side_effect = Exception("connection closed")
    mgr.active = {dead_ws}
    await mgr.broadcast({"type": "test"})
    assert dead_ws not in mgr.active


# --- market_processor tests ---

@pytest.mark.asyncio
async def test_market_processor_produces_market_update():
    kline_q: asyncio.Queue = asyncio.Queue()
    update_q: asyncio.Queue = asyncio.Queue()
    rsi_calc = RsiCalculator()

    await kline_q.put(make_kline(50000.0))

    async def run_once():
        await market_processor(kline_q, update_q, rsi_calc, RsiUltraCalculator())

    task = asyncio.create_task(run_once())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert not update_q.empty()
    msg = await update_q.get()
    assert msg["type"] == "market_update"
    assert msg["payload"]["pair"] == "BTCUSDT"
    assert msg["payload"]["price"] == 50000.0


@pytest.mark.asyncio
async def test_market_processor_rsi_null_with_few_candles():
    kline_q: asyncio.Queue = asyncio.Queue()
    update_q: asyncio.Queue = asyncio.Queue()
    rsi_calc = RsiCalculator()  # fresh, no candles

    await kline_q.put(make_kline(50000.0))

    task = asyncio.create_task(market_processor(kline_q, update_q, rsi_calc, RsiUltraCalculator()))
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    msg = await update_q.get()
    assert msg["payload"]["rsi"] is None
