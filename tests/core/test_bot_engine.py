"""Tests for Stories 4.1, 4.2, 4.3, 6.3: Bot Engine state machine + buy/stop-loss + error surfacing."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.core.bot_engine as bot_engine_module
from src.core.bot_engine import BotEngine, BotState, InvalidStateTransitionError, OrderResult
from src.models.config import TradingConfig
from src.services.binance_client import BinanceConnectionError


@pytest.fixture(autouse=True)
def no_state_file(tmp_path):
    """Redirect state file to a temp path so tests start clean."""
    original = bot_engine_module._STATE_FILE
    bot_engine_module._STATE_FILE = tmp_path / "bot_state.json"
    yield
    bot_engine_module._STATE_FILE = original


def make_config(**kw):
    return TradingConfig(**{**dict(rsi_threshold=30, trade_amount_usd=5.0, stop_loss_pct=5.0), **kw})


def make_order(price=50000.0, qty=0.0001):
    return OrderResult(
        order_id="123", pair="BTCUSDT", quantity=qty,
        price=price, executed_at=datetime.now(timezone.utc)
    )


# --- State machine (4.1) ---

@pytest.mark.asyncio
async def test_initial_state_is_stopped():
    engine = BotEngine()
    assert engine.state == BotState.STOPPED
    assert not engine.is_active


@pytest.mark.asyncio
async def test_start_transitions_to_running():
    engine = BotEngine()
    await engine.start()
    assert engine.state == BotState.RUNNING
    assert engine.is_active


@pytest.mark.asyncio
async def test_pause_transitions_to_paused():
    engine = BotEngine()
    await engine.start()
    await engine.pause()
    assert engine.state == BotState.PAUSED
    assert not engine.is_active


@pytest.mark.asyncio
async def test_resume_transitions_to_running():
    engine = BotEngine()
    await engine.start()
    await engine.pause()
    await engine.resume()
    assert engine.state == BotState.RUNNING


@pytest.mark.asyncio
async def test_set_error_sets_error_state():
    engine = BotEngine()
    await engine.start()
    await engine.set_error("test error")
    assert engine.state == BotState.ERROR


@pytest.mark.asyncio
async def test_start_from_error_allowed():
    engine = BotEngine()
    await engine.start()
    await engine.set_error("test")
    await engine.start()
    assert engine.state == BotState.RUNNING


@pytest.mark.asyncio
async def test_invalid_transition_raises():
    engine = BotEngine()
    with pytest.raises(InvalidStateTransitionError):
        await engine.pause()  # can't pause when STOPPED
    with pytest.raises(InvalidStateTransitionError):
        await engine.resume()  # can't resume when STOPPED


@pytest.mark.asyncio
async def test_start_when_running_raises():
    engine = BotEngine()
    await engine.start()
    with pytest.raises(InvalidStateTransitionError):
        await engine.start()  # can't start when already RUNNING


def test_uptime_zero_before_start():
    engine = BotEngine()
    assert engine.get_uptime_seconds() == 0.0


@pytest.mark.asyncio
async def test_uptime_positive_after_start():
    engine = BotEngine()
    await engine.start()
    assert engine.get_uptime_seconds() >= 0.0


# --- Buy signal (4.2) ---

@pytest.mark.asyncio
async def test_buy_triggered_on_rsi_below_threshold():
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_threshold=30)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_called_once()
    assert engine.open_position is not None


@pytest.mark.asyncio
async def test_buy_not_triggered_above_threshold():
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_threshold=30)
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=50.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()


@pytest.mark.asyncio
async def test_buy_edge_triggered_not_repeated():
    """Buy fires once when RSI crosses below, not on every tick while below."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_threshold=30)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    # First tick below threshold → buy
    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    assert mock_client.execute_market_buy.call_count == 1

    # Second tick still below → no second buy (position already open)
    await engine.process_market_update(rsi=24.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    assert mock_client.execute_market_buy.call_count == 1


@pytest.mark.asyncio
async def test_buy_not_triggered_when_paused():
    engine = BotEngine()
    await engine.start()
    await engine.pause()
    config = make_config(rsi_threshold=30)
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()


@pytest.mark.asyncio
async def test_buy_sets_stop_loss_price():
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_threshold=30, stop_loss_pct=5.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order(price=50000.0))

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    expected_sl = 50000.0 * (1 - 5.0 / 100)
    assert engine._stop_loss_price == expected_sl


# --- Stop-loss (4.3) ---

@pytest.mark.asyncio
async def test_stop_loss_triggered_below_price():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._stop_loss_price = 47500.0  # 5% below 50000
    config = make_config()
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=47000.0))

    await engine.process_market_update(rsi=40.0, price=47000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


@pytest.mark.asyncio
async def test_stop_loss_not_triggered_above_price():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._stop_loss_price = 47500.0
    config = make_config()
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=40.0, price=49000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_sell.assert_not_called()
    assert engine.open_position is not None


@pytest.mark.asyncio
async def test_stop_loss_clears_position():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._stop_loss_price = 47500.0
    config = make_config()
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=47000.0))

    await engine.process_market_update(rsi=None, price=47000.0,
                                        binance_client=mock_client, config=config)
    assert engine.open_position is None
    assert engine._stop_loss_price is None


# ---------------------------------------------------------------------------
# Story 6.3: API failure detection — error broadcast + BinanceConnectionError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_error_broadcasts_bot_status_and_error_events():
    """set_error() must broadcast both bot_status and error WS events."""
    broadcaster = AsyncMock()
    broadcaster.broadcast = AsyncMock()
    engine = BotEngine(broadcaster=broadcaster)
    await engine.start()
    await engine.set_error("API timeout")

    call_types = [c.args[0]["type"] for c in broadcaster.broadcast.call_args_list]
    assert "bot_status" in call_types, f"Expected bot_status broadcast, got: {call_types}"
    assert "error" in call_types, f"Expected error broadcast, got: {call_types}"


@pytest.mark.asyncio
async def test_set_error_broadcast_error_payload():
    """error broadcast must have code=API_FAILURE and the correct message."""
    broadcaster = AsyncMock()
    broadcaster.broadcast = AsyncMock()
    engine = BotEngine(broadcaster=broadcaster)
    await engine.set_error("connection failed")

    error_calls = [
        c.args[0] for c in broadcaster.broadcast.call_args_list
        if c.args[0].get("type") == "error"
    ]
    assert error_calls, "No error broadcast found"
    payload = error_calls[0]["payload"]
    assert payload["code"] == "API_FAILURE"
    assert payload["message"] == "connection failed"


@pytest.mark.asyncio
async def test_binance_connection_error_on_buy_triggers_set_error():
    """BinanceConnectionError from execute_market_buy → bot transitions to ERROR state."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_threshold=30)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(
        side_effect=BinanceConnectionError("retries exhausted")
    )

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    assert engine.state == BotState.ERROR


@pytest.mark.asyncio
async def test_binance_connection_error_on_sell_triggers_set_error():
    """BinanceConnectionError from execute_market_sell → bot transitions to ERROR state."""
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._stop_loss_price = 47500.0
    config = make_config()
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(
        side_effect=BinanceConnectionError("retries exhausted")
    )

    await engine.process_market_update(rsi=40.0, price=47000.0,
                                        binance_client=mock_client, config=config)
    assert engine.state == BotState.ERROR


@pytest.mark.asyncio
async def test_error_state_blocks_trading():
    """Bot in ERROR state must not execute buy orders."""
    engine = BotEngine()
    await engine.start()
    await engine.set_error("forced error")
    config = make_config(rsi_threshold=30)
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()
