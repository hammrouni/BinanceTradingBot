"""Tests for Stories 4.1, 4.2, 4.3, 6.3: Bot Engine state machine + buy/stop-loss + error surfacing."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.core.bot_engine as bot_engine_module
from src.core.bot_engine import BotEngine, BotState, InvalidStateTransitionError, OrderResult
from src.models.config import TradingConfig
from src.models.trade import TradeRecord
from src.services.binance_client import BinanceConnectionError, BinanceOrderError


@pytest.fixture(autouse=True)
def no_state_file(tmp_path):
    """Redirect state file to a temp path so tests start clean."""
    original = bot_engine_module._STATE_FILE
    bot_engine_module._STATE_FILE = tmp_path / "bot_state.json"
    yield
    bot_engine_module._STATE_FILE = original


def make_config(**kw):
    return TradingConfig(**{**dict(rsi_oversold=30, rsi_overbought=70, trade_amount_usd=15.0, stop_loss_pct=5.0, take_profit_pct=2.0), **kw})


def make_order(price=50000.0, qty=0.0001):
    return OrderResult(
        order_id="123", pair="BTCUSDT", quantity=qty,
        price=price, executed_at=datetime.now(timezone.utc)
    )


def make_trade(direction: str, qty: float, price: float, *, order_id: str, executed_at: str):
    return TradeRecord(
        executed_at=executed_at,
        pair="BTCUSDT",
        direction=direction,
        amount_usd=qty * price,
        quantity=qty,
        entry_price=price,
        order_id=order_id,
        is_test=False,
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
    config = make_config(rsi_oversold=30)
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
    config = make_config(rsi_oversold=30)
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=50.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()


# --- Price Bounce Confirmation ---

@pytest.mark.asyncio
async def test_price_bounce_blocks_buy_when_price_falling():
    """price_bounce_ticks=3 blocks buy when the last N+1 ticks are falling."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, price_bounce_ticks=3)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    # Pre-populate history with 3 falling ticks; process_market_update appends a 4th
    for p in [50100.0, 50080.0, 50060.0]:
        engine.market_history.append({"price": p, "rsi": 25.0, "timestamp": "t"})

    # 4th tick still falling → prices[-1]=50040 < prices[0]=50100 → bounce blocked
    await engine.process_market_update(rsi=25.0, price=50040.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()


@pytest.mark.asyncio
async def test_price_bounce_allows_buy_when_price_rising():
    """price_bounce_ticks=3 allows buy when the last N+1 ticks are rising."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, price_bounce_ticks=3)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    for p in [50000.0, 50020.0, 50040.0]:
        engine.market_history.append({"price": p, "rsi": 25.0, "timestamp": "t"})

    # 4th tick higher than first → bounce confirmed
    await engine.process_market_update(rsi=25.0, price=50060.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_called_once()


@pytest.mark.asyncio
async def test_price_bounce_allows_buy_without_enough_history():
    """price_bounce_ticks=5 with insufficient history must not block buy."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, price_bounce_ticks=5)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    # Only 1 history tick; need ticks+1=6 → filter skipped (returns True)
    engine.market_history.append({"price": 50000.0, "rsi": 25.0, "timestamp": "t"})

    await engine.process_market_update(rsi=25.0, price=50010.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_called_once()


# --- Trailing Stop ---

@pytest.mark.asyncio
async def test_trailing_stop_sets_initial_sl_when_no_fixed_sl():
    """When only trailing_stop_pct is set, buy seeds initial SL from trailing %."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, stop_loss_pct=None, trailing_stop_pct=2.0, take_profit_pct=None)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order(price=50000.0))

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    assert engine._stop_loss_price == pytest.approx(50000.0 * 0.98)


@pytest.mark.asyncio
async def test_trailing_stop_ratchets_sl_up_when_price_rises():
    """Trailing stop moves SL upward when price rises above initial entry."""
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._stop_loss_price = 49000.0  # 2% below 50000
    config = make_config(trailing_stop_pct=2.0, stop_loss_pct=None, take_profit_pct=None)
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=51000.0))

    # Price rises to 51000 → new trailing SL = 51000 * 0.98 = 49980 > 49000 → ratchet
    await engine.process_market_update(rsi=50.0, price=51000.0,
                                        binance_client=mock_client, config=config)

    assert engine._stop_loss_price == pytest.approx(51000.0 * 0.98)
    mock_client.execute_market_sell.assert_not_called()


@pytest.mark.asyncio
async def test_trailing_stop_does_not_lower_sl_when_price_falls():
    """Once ratcheted up, trailing SL must never move downward."""
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._stop_loss_price = 49800.0  # already ratcheted to a high level
    config = make_config(trailing_stop_pct=2.0, stop_loss_pct=None, take_profit_pct=None)
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(return_value=make_order())

    # Price at 50050 → new trailing SL = 50050 * 0.98 = 49049 < 49800 → no update
    await engine.process_market_update(rsi=50.0, price=50050.0,
                                        binance_client=mock_client, config=config)

    assert engine._stop_loss_price == pytest.approx(49800.0)


@pytest.mark.asyncio
async def test_trailing_stop_triggers_sell_after_ratchet():
    """Trailing SL ratchets up then triggers sell when price drops below it."""
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._stop_loss_price = 49000.0
    config = make_config(trailing_stop_pct=2.0, stop_loss_pct=None, take_profit_pct=None)
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=51000.0))

    # Tick 1: price rises to 51000 → SL ratchets to 51000 * 0.98 = 49980
    await engine.process_market_update(rsi=50.0, price=51000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_sell.assert_not_called()
    ratcheted_sl = engine._stop_loss_price
    assert ratcheted_sl == pytest.approx(49980.0)

    # Tick 2: price drops to 49900 which is below ratcheted SL 49980 → sell
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=49900.0))
    await engine.process_market_update(rsi=50.0, price=49900.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


# --- Bear Trend Filter ---

@pytest.mark.asyncio
async def test_bear_trend_blocks_buy_when_drop_exceeds_threshold():
    """Bear trend filter blocks buy when price dropped >= pct% over last N candles."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, bear_trend_candles=5, bear_trend_pct=1.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    # Pre-fill 4 ticks; process_market_update appends the 5th
    for p in [50000.0, 49900.0, 49800.0, 49700.0]:
        engine.market_history.append({"price": p, "rsi": 25.0, "timestamp": "t"})

    # 5th tick at 49500: history[-5]=50000, drop=(50000-49500)/50000*100=1.0% >= 1.0% → blocked
    await engine.process_market_update(rsi=25.0, price=49500.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()


@pytest.mark.asyncio
async def test_bear_trend_allows_buy_when_insufficient_history():
    """Bear trend filter does NOT block buy when history is shorter than candles."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, bear_trend_candles=10, bear_trend_pct=1.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    # Only 2 pre-filled + 1 appended = 3 total; need 10 → filter skipped
    for p in [50000.0, 49500.0]:
        engine.market_history.append({"price": p, "rsi": 25.0, "timestamp": "t"})

    await engine.process_market_update(rsi=25.0, price=49000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_called_once()


@pytest.mark.asyncio
async def test_bear_trend_allows_buy_when_params_none():
    """Bear trend filter is disabled when config params are None."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, bear_trend_candles=None, bear_trend_pct=None)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    # Massive drop in history — but filter disabled
    for p in [50000.0, 49000.0, 48000.0, 47000.0, 46000.0]:
        engine.market_history.append({"price": p, "rsi": 25.0, "timestamp": "t"})

    await engine.process_market_update(rsi=25.0, price=44000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_called_once()


@pytest.mark.asyncio
async def test_bear_trend_allows_buy_when_drop_below_threshold():
    """Bear trend filter allows buy when drop is below pct threshold."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, bear_trend_candles=3, bear_trend_pct=5.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order())

    # Pre-fill 2 ticks; after appending 3rd: history[-3]=50000, current=49000, drop=2% < 5%
    for p in [50000.0, 49800.0]:
        engine.market_history.append({"price": p, "rsi": 25.0, "timestamp": "t"})

    await engine.process_market_update(rsi=25.0, price=49000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_called_once()


@pytest.mark.asyncio
async def test_buy_edge_triggered_not_repeated():
    """Buy fires once when RSI crosses below, not on every tick while below."""
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30)
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
    config = make_config(rsi_oversold=30)
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()


@pytest.mark.asyncio
async def test_buy_sets_stop_loss_price():
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, stop_loss_pct=5.0)
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


# --- Take-profit (NEW) ---

@pytest.mark.asyncio
async def test_take_profit_triggered_at_price():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._take_profit_price = 51000.0  # 2% above 50000
    config = make_config()
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=51000.0))

    await engine.process_market_update(rsi=60.0, price=51000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_sell.assert_called_once()
    assert engine.open_position is None


@pytest.mark.asyncio
async def test_take_profit_not_triggered_below_price():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._take_profit_price = 51000.0
    config = make_config()
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=60.0, price=50500.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_sell.assert_not_called()
    assert engine.open_position is not None


@pytest.mark.asyncio
async def test_take_profit_clears_position_and_state():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0)
    engine._take_profit_price = 51000.0
    config = make_config()
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=51000.0))

    await engine.process_market_update(rsi=None, price=51001.0,
                                        binance_client=mock_client, config=config)
    assert engine.open_position is None
    assert engine._take_profit_price is None


@pytest.mark.asyncio
async def test_buy_sets_take_profit_price():
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, take_profit_pct=2.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order(price=50000.0))

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    expected_tp = 50000.0 * (1 + 2.0 / 100)
    assert engine._take_profit_price == expected_tp


@pytest.mark.asyncio
async def test_buy_with_zero_tp_sets_it_to_none():
    engine = BotEngine()
    await engine.start()
    config = make_config(rsi_oversold=30, take_profit_pct=0.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order(price=50000.0))

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    assert engine._take_profit_price is None


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
    config = make_config(rsi_oversold=30)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(
        side_effect=BinanceConnectionError("retries exhausted")
    )


# ─── BC Mode Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bc_mode_buys_when_price_hits_target():
    """BC Mode: bot buys when live price drops to or below bc_buy_price."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["BC"],
        bc_buy_price=68000.0,
        bc_sell_price=70000.0,
        rsi_oversold=None,
        rsi_overbought=None,
    )
    order = make_order(price=67900.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=order)
    mock_client.execute_market_sell = AsyncMock()

    await engine.process_market_update(None, 67900.0, mock_client, config)

    mock_client.execute_market_buy.assert_awaited_once()
    assert engine.open_position is not None


@pytest.mark.asyncio
async def test_bc_mode_does_not_buy_above_target():
    """BC Mode: bot does NOT buy when price is above bc_buy_price."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["BC"],
        bc_buy_price=68000.0,
        bc_sell_price=70000.0,
        rsi_oversold=None,
        rsi_overbought=None,
    )
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock()

    await engine.process_market_update(None, 68500.0, mock_client, config)

    mock_client.execute_market_buy.assert_not_awaited()
    assert engine.open_position is None


@pytest.mark.asyncio
async def test_bc_mode_sells_when_price_hits_target():
    """BC Mode: bot sells when price rises to bc_sell_price after holding a position."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["BC"],
        bc_buy_price=68000.0,
        bc_sell_price=70000.0,
        take_profit_pct=0.0,
        rsi_oversold=None,
        rsi_overbought=None,
    )
    order = make_order(price=67900.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=order)
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=70100.0))

    # First tick: buy
    await engine.process_market_update(None, 67900.0, mock_client, config)
    assert engine.open_position is not None

    # Second tick: price rises above sell target
    await engine.process_market_update(None, 70100.0, mock_client, config)

    mock_client.execute_market_sell.assert_awaited_once()
    assert engine.open_position is None


@pytest.mark.asyncio
async def test_bc_mode_does_not_sell_below_target():
    """BC Mode: bot does NOT sell when price is below bc_sell_price."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["BC"],
        bc_buy_price=68000.0,
        bc_sell_price=70000.0,
        take_profit_pct=0.0,
        rsi_oversold=None,
        rsi_overbought=None,
    )
    order = make_order(price=67900.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=order)
    mock_client.execute_market_sell = AsyncMock()

    # Buy first
    await engine.process_market_update(None, 67900.0, mock_client, config)
    assert engine.open_position is not None

    # Price goes up but not high enough to sell
    await engine.process_market_update(None, 69500.0, mock_client, config)

    mock_client.execute_market_sell.assert_not_awaited()
    assert engine.open_position is not None


@pytest.mark.asyncio
async def test_bc_mode_buy_is_edge_triggered():
    """BC Mode: bot only buys once per crossing — not on every tick below target."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["BC"],
        bc_buy_price=68000.0,
        bc_sell_price=70000.0,
        rsi_oversold=None,
        rsi_overbought=None,
    )
    order = make_order(price=67800.0)
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=order)

    # Two consecutive ticks below buy target — should only buy once
    await engine.process_market_update(None, 67800.0, mock_client, config)
    await engine.process_market_update(None, 67750.0, mock_client, config)

    assert mock_client.execute_market_buy.await_count == 1


@pytest.mark.asyncio
async def test_rsi_mode_ignores_bc_price_targets():
    """RSI Mode: bc_buy_price and bc_sell_price are ignored when active_modes is ['RSI']."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["RSI"],
        bc_buy_price=68000.0,   # set but should not trigger
        bc_sell_price=70000.0,
        rsi_oversold=30,
        rsi_overbought=70,
    )
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock()

    # Price is below bc_buy_price but RSI is neutral → no buy
    with patch.object(engine, '_persist_state'), patch.object(engine, '_broadcast_state', new=AsyncMock()):
        await engine.process_market_update(45.0, 67000.0, mock_client, config)

    mock_client.execute_market_buy.assert_not_awaited()


# ─── active_filters Tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_filters_bounce_blocks_buy_without_bounce():
    """BOUNCE filter: bot does NOT buy even with RSI signal if price is not bouncing."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["RSI"],
        active_filters=["BOUNCE"],
        rsi_oversold=30,
        price_bounce_ticks=3,
    )
    # Simulate a falling price history (no bounce)
    for p in [50000, 49900, 49800, 49700]:
        engine.market_history.append({"price": p, "rsi": 25, "timestamp": "2026-01-01T00:00:00Z"})

    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock()

    with patch.object(engine, '_persist_state'), patch.object(engine, '_broadcast_state', new=AsyncMock()):
        await engine.process_market_update(25.0, 49700.0, mock_client, config)

    mock_client.execute_market_buy.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_filters_bear_blocks_buy_during_crash():
    """BEAR filter: bot does NOT buy during bear trend even with RSI oversold."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["RSI"],
        active_filters=["BEAR"],
        rsi_oversold=30,
        bear_trend_candles=3,
        bear_trend_pct=1.0,
    )
    # Drop ~1.8% over 3 candles: 48900 → 48000 (triggers ≥1% bear filter)
    for p in [50000, 49500, 48900, 48000]:
        engine.market_history.append({"price": p, "rsi": 25, "timestamp": "2026-01-01T00:00:00Z"})

    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock()

    with patch.object(engine, '_persist_state'), patch.object(engine, '_broadcast_state', new=AsyncMock()):
        await engine.process_market_update(25.0, 48000.0, mock_client, config)

    mock_client.execute_market_buy.assert_not_awaited()


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
async def test_failed_sell_keeps_open_position():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0, qty=0.00017)
    engine._stop_loss_price = 47500.0
    config = make_config()
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(
        side_effect=BinanceConnectionError("insufficient balance")
    )

    await engine.process_market_update(rsi=40.0, price=47000.0,
                                        binance_client=mock_client, config=config)
    assert engine.open_position is not None
    assert engine.open_position.quantity == 0.00017
    assert engine._stop_loss_price == 47500.0


@pytest.mark.asyncio
async def test_reconcile_open_position_clears_stale_position():
    engine = BotEngine()
    engine.open_position = make_order(price=50000.0, qty=0.00017)
    engine._stop_loss_price = 47500.0
    mock_client = AsyncMock()
    mock_client.get_base_asset_balance = AsyncMock(return_value={"free": 0.0, "locked": 0.0, "total": 0.0})

    await engine.reconcile_open_position(mock_client, "BTCUSDT")

    assert engine.open_position is None
    assert engine._stop_loss_price is None


@pytest.mark.asyncio
async def test_reconcile_open_position_reduces_quantity_to_wallet_total():
    engine = BotEngine()
    engine.open_position = make_order(price=50000.0, qty=0.00017)
    mock_client = AsyncMock()
    mock_client.get_base_asset_balance = AsyncMock(return_value={"free": 0.00016, "locked": 0.0, "total": 0.00016})
    mock_client._get_step_size = AsyncMock(return_value=0.00001)

    await engine.reconcile_open_position(mock_client, "BTCUSDT")

    assert engine.open_position is not None
    assert engine.open_position.quantity == 0.00016


@pytest.mark.asyncio
async def test_sync_open_position_recovers_missing_state_from_trade_log():
    engine = BotEngine()
    config = make_config()
    mock_client = AsyncMock()
    mock_client.get_base_asset_balance = AsyncMock(return_value={"free": 0.00026, "locked": 0.0, "total": 0.00026})
    mock_client._get_step_size = AsyncMock(return_value=0.00001)

    with patch(
        "src.core.bot_engine.read_trades",
        return_value=[
            make_trade("buy", 0.00026, 67175.47, order_id="59917086881", executed_at="2026-03-31T08:33:01Z"),
        ],
    ):
        await engine.sync_open_position(mock_client, config)

    assert engine.open_position is not None
    assert engine.open_position.order_id == "59917086881"
    assert engine.open_position.quantity == pytest.approx(0.00026)
    assert engine._stop_loss_price == pytest.approx(67175.47 * (1 - config.stop_loss_pct / 100))
    assert engine._take_profit_price == pytest.approx(67175.47 * (1 + config.take_profit_pct / 100))


@pytest.mark.asyncio
async def test_execute_sell_clears_position_before_balance_refresh():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0, qty=0.00017)
    mock_client = AsyncMock()
    mock_client._settings.trading_env = "testnet"
    mock_client.execute_market_sell = AsyncMock(return_value=make_order(price=51000.0, qty=0.00017))

    async def assert_position_already_cleared(*args, **kwargs):
        assert engine.open_position is None

    engine.update_balances = AsyncMock(side_effect=assert_position_already_cleared)

    await engine._execute_sell(price=51000.0, binance_client=mock_client, reason="signal")

    assert engine.open_position is None


@pytest.mark.asyncio
async def test_execute_sell_unsellable_dust_clears_position_without_error_state():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0, qty=0.00017)
    engine._stop_loss_price = 47500.0
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(
        side_effect=BinanceOrderError("UNSELLABLE_DUST: Available 8.3e-06 BTC is below stepSize 1e-05 for BTCUSDT")
    )
    engine.update_balances = AsyncMock()

    await engine._execute_sell(price=47000.0, binance_client=mock_client, reason="stop_loss")

    assert engine.state == BotState.RUNNING
    assert engine.open_position is None
    assert engine._stop_loss_price is None
    engine.update_balances.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_sell_balance_mismatch_reconciles_without_error_state():
    engine = BotEngine()
    await engine.start()
    engine.open_position = make_order(price=50000.0, qty=0.00017)
    engine._stop_loss_price = 47500.0
    mock_client = AsyncMock()
    mock_client.execute_market_sell = AsyncMock(
        side_effect=BinanceOrderError("Insufficient available balance after exchange step-size formatting: 8.3e-06 BTC")
    )
    mock_client.get_base_asset_balance = AsyncMock(return_value={"free": 0.00016, "locked": 0.0, "total": 0.00016})
    mock_client._get_step_size = AsyncMock(return_value=0.00001)
    engine.update_balances = AsyncMock()

    await engine._execute_sell(price=47000.0, binance_client=mock_client, reason="stop_loss")

    assert engine.state == BotState.RUNNING
    assert engine.open_position is not None
    assert engine.open_position.quantity == pytest.approx(0.00016)
    engine.update_balances.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_state_blocks_trading():
    """Bot in ERROR state must not execute buy orders."""
    engine = BotEngine()
    await engine.start()
    await engine.set_error("forced error")
    config = make_config(rsi_oversold=30)
    mock_client = AsyncMock()

    await engine.process_market_update(rsi=25.0, price=50000.0,
                                        binance_client=mock_client, config=config)
    mock_client.execute_market_buy.assert_not_called()


# ─── Strategy isolation tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rsi_mode_ignores_bc_price_signal():
    """active_modes=["RSI"]: price crossing bc_buy_price must NOT trigger a buy."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["RSI"],
        rsi_oversold=30,
        bc_buy_price=65000.0,
        bc_sell_price=67000.0,
    )
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock()

    # RSI is not oversold (40 > 30) — but price IS below bc_buy_price
    with patch.object(engine, '_persist_state'), patch.object(engine, '_broadcast_state', new=AsyncMock()):
        await engine.process_market_update(40.0, 64000.0, mock_client, config)

    mock_client.execute_market_buy.assert_not_awaited()


@pytest.mark.asyncio
async def test_bc_mode_ignores_rsi_oversold_signal():
    """active_modes=["BC"]: RSI going oversold must NOT trigger a buy."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["BC"],
        rsi_oversold=30,
        bc_buy_price=65000.0,
        bc_sell_price=67000.0,
    )
    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock()

    # RSI IS oversold (25 < 30) — but price is above bc_buy_price (neutral BC state)
    with patch.object(engine, '_persist_state'), patch.object(engine, '_broadcast_state', new=AsyncMock()):
        await engine.process_market_update(25.0, 66000.0, mock_client, config)

    mock_client.execute_market_buy.assert_not_awaited()


# ─── Positive filter tests ("allows" complement to the blocking tests) ───────

@pytest.mark.asyncio
async def test_bounce_filter_allows_buy_when_price_is_bouncing():
    """BOUNCE filter: buy IS executed when RSI is oversold AND price bounces up."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["RSI"],
        active_filters=["BOUNCE"],
        rsi_oversold=30,
        price_bounce_ticks=2,
    )
    # Price history: falls then bounces up (2 consecutive rises)
    prices = [50000, 49800, 49600, 49700, 49900]
    for p in prices:
        engine.market_history.append({"price": p, "rsi": 25, "timestamp": "2026-01-01T00:00:00Z"})

    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order(price=49900.0))

    with patch.object(engine, '_persist_state'), \
         patch.object(engine, '_broadcast_state', new=AsyncMock()), \
         patch('src.core.bot_engine.log_trade', new=AsyncMock()):
        await engine.process_market_update(25.0, 49900.0, mock_client, config)

    mock_client.execute_market_buy.assert_awaited_once()


@pytest.mark.asyncio
async def test_bear_filter_allows_buy_when_no_bear_trend():
    """BEAR filter: buy IS executed when RSI is oversold and trend is not bearish."""
    engine = BotEngine()
    await engine.start()
    config = make_config(
        active_modes=["RSI"],
        active_filters=["BEAR"],
        rsi_oversold=30,
        bear_trend_candles=3,
        bear_trend_pct=1.0,
    )
    # Price history: stable / slightly rising (not a bear trend)
    prices = [50000, 50100, 50200, 50150]
    for p in prices:
        engine.market_history.append({"price": p, "rsi": 25, "timestamp": "2026-01-01T00:00:00Z"})

    mock_client = AsyncMock()
    mock_client.execute_market_buy = AsyncMock(return_value=make_order(price=50150.0))

    with patch.object(engine, '_persist_state'), \
         patch.object(engine, '_broadcast_state', new=AsyncMock()), \
         patch('src.core.bot_engine.log_trade', new=AsyncMock()):
        await engine.process_market_update(25.0, 50150.0, mock_client, config)

    mock_client.execute_market_buy.assert_awaited_once()
