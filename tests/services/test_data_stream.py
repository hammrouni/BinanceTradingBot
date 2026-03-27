"""Tests for Stories 2.1 and 6.2: Binance WebSocket Kline Data Stream."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Settings
from src.models.market import KlineData
from src.services.data_stream import (
    DataStream,
    WS_INITIAL_RECONNECT_DELAY,
    WS_MAX_RECONNECT_DELAY,
)


def make_settings():
    return Settings.model_validate(
        {"binance_api_key": "key", "binance_api_secret": "secret", "trading_env": "testnet"}
    )


def make_kline_msg(close: float = 50000.0, is_closed: bool = True) -> dict:
    return {
        "k": {
            "t": 1700000000000,
            "o": "49000.0",
            "h": "51000.0",
            "l": "48000.0",
            "c": str(close),
            "v": "10.5",
            "T": 1700000059999,
            "x": is_closed,
        }
    }


def test_parse_kline_closed_candle():
    stream = DataStream()
    msg = make_kline_msg(close=50000.0, is_closed=True)
    kline = stream._parse_kline(msg)
    assert kline is not None
    assert isinstance(kline, KlineData)
    assert kline.close == 50000.0
    assert kline.is_closed is True


def test_parse_kline_open_candle():
    stream = DataStream()
    msg = make_kline_msg(close=50000.0, is_closed=False)
    kline = stream._parse_kline(msg)
    assert kline is not None
    assert kline.is_closed is False


def test_parse_kline_missing_key_returns_none():
    stream = DataStream()
    kline = stream._parse_kline({})
    assert kline is None


def test_parse_kline_invalid_float_returns_none():
    stream = DataStream()
    msg = make_kline_msg()
    msg["k"]["c"] = "not_a_number"
    kline = stream._parse_kline(msg)
    assert kline is None


@pytest.mark.asyncio
async def test_start_enqueues_only_closed_candles():
    stream = DataStream()
    settings = make_settings()
    queue: asyncio.Queue = asyncio.Queue()

    closed_msg = make_kline_msg(close=50000.0, is_closed=True)
    open_msg = make_kline_msg(close=49000.0, is_closed=False)

    recv_msgs = [open_msg, closed_msg]
    recv_call = 0

    async def fake_recv():
        nonlocal recv_call
        if recv_call < len(recv_msgs):
            msg = recv_msgs[recv_call]
            recv_call += 1
            return msg
        stream.stop()
        return None

    mock_ws = AsyncMock()
    mock_ws.recv = AsyncMock(side_effect=fake_recv)

    mock_socket_ctx = MagicMock()
    mock_socket_ctx.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_socket_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_bm = MagicMock()
    mock_bm.kline_socket = MagicMock(return_value=mock_socket_ctx)

    mock_client = AsyncMock()

    with patch("src.services.data_stream.AsyncClient") as mock_cls, \
         patch("src.services.data_stream.BinanceSocketManager", return_value=mock_bm):
        mock_cls.create = AsyncMock(return_value=mock_client)
        mock_client.close_connection = AsyncMock()

        await asyncio.wait_for(stream.start(settings, queue), timeout=5.0)

    assert queue.qsize() == 1
    item = await queue.get()
    assert item.close == 50000.0
    assert item.is_closed is True


def test_stop_sets_running_false():
    stream = DataStream()
    stream._running = True
    stream.stop()
    assert stream._running is False


def test_kline_data_model_fields():
    kline = KlineData(
        open_time=1700000000000,
        open=49000.0,
        high=51000.0,
        low=48000.0,
        close=50000.0,
        volume=10.5,
        close_time=1700000059999,
        is_closed=True,
    )
    assert kline.close == 50000.0
    assert kline.is_closed is True


# ---------------------------------------------------------------------------
# Story 6.2: WebSocket Auto-Reconnect on Disconnect
# ---------------------------------------------------------------------------


def test_reconnect_delay_constants_exist():
    """WS_INITIAL_RECONNECT_DELAY and WS_MAX_RECONNECT_DELAY constants must exist."""
    assert WS_INITIAL_RECONNECT_DELAY == 2
    assert WS_MAX_RECONNECT_DELAY == 30


def test_reconnect_backoff_schedule():
    """Backoff formula: min(INITIAL * 2**attempt, MAX) → 2, 4, 8, 16, 30, 30."""
    expected = [2, 4, 8, 16, 30, 30]
    for i, exp in enumerate(expected):
        delay = min(WS_INITIAL_RECONNECT_DELAY * (2 ** i), WS_MAX_RECONNECT_DELAY)
        assert delay == exp, f"attempt {i}: expected {exp}s, got {delay}s"


@pytest.mark.asyncio
async def test_reconnect_warning_log_includes_exception_type_and_attempt(caplog):
    """WARNING log must include exception class name and attempt number."""
    stream = DataStream()
    settings = make_settings()
    queue: asyncio.Queue = asyncio.Queue()
    call_count = 0

    async def fake_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("simulated drop")
        stream.stop()
        raise asyncio.CancelledError()

    with patch("src.services.data_stream.AsyncClient") as mock_cls, \
         patch("src.services.data_stream.asyncio.sleep", new_callable=AsyncMock):
        mock_cls.create = AsyncMock(side_effect=fake_create)
        with caplog.at_level(logging.WARNING, logger="src.services.data_stream"):
            try:
                await stream.start(settings, queue)
            except asyncio.CancelledError:
                pass

    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("ConnectionError" in m for m in warning_msgs), (
        f"Expected 'ConnectionError' in warning. Got: {warning_msgs}"
    )
    assert any("attempt 1" in m for m in warning_msgs), (
        f"Expected 'attempt 1' in warning. Got: {warning_msgs}"
    )


@pytest.mark.asyncio
async def test_reconnect_info_log_on_reconnect(caplog):
    """INFO log must say 'Binance WebSocket reconnected' on re-entry after failure."""
    stream = DataStream()
    settings = make_settings()
    queue: asyncio.Queue = asyncio.Queue()

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_stream_ctx.recv = AsyncMock(side_effect=lambda: (stream.stop() or None))

    mock_bm = MagicMock()
    mock_bm.kline_socket = MagicMock(return_value=mock_stream_ctx)
    mock_client = AsyncMock()
    mock_client.close_connection = AsyncMock()

    connect_count = 0

    async def fake_create(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            raise OSError("first connect fails")
        return mock_client

    with patch("src.services.data_stream.AsyncClient") as mock_cls, \
         patch("src.services.data_stream.BinanceSocketManager", return_value=mock_bm), \
         patch("src.services.data_stream.asyncio.sleep", new_callable=AsyncMock):
        mock_cls.create = AsyncMock(side_effect=fake_create)
        with caplog.at_level(logging.INFO, logger="src.services.data_stream"):
            await asyncio.wait_for(stream.start(settings, queue), timeout=5.0)

    info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
    reconnect_logs = [m for m in info_msgs if "Binance WebSocket reconnected" in m]
    assert reconnect_logs, f"Expected 'Binance WebSocket reconnected' INFO log. Got: {info_msgs}"


@pytest.mark.asyncio
async def test_cancelled_error_propagates_out_of_reconnect_loop():
    """asyncio.CancelledError must not be swallowed — it must propagate."""
    stream = DataStream()
    settings = make_settings()
    queue: asyncio.Queue = asyncio.Queue()

    with patch("src.services.data_stream.AsyncClient") as mock_cls:
        mock_cls.create = AsyncMock(side_effect=asyncio.CancelledError)
        with pytest.raises(asyncio.CancelledError):
            await stream.start(settings, queue)


@pytest.mark.asyncio
async def test_timeout_triggers_reconnect_with_backoff():
    """asyncio.TimeoutError from recv (stale connection) must trigger backoff sleep."""
    stream = DataStream()
    settings = make_settings()
    queue: asyncio.Queue = asyncio.Queue()
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)
        stream.stop()

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_stream_ctx.recv = AsyncMock(side_effect=asyncio.TimeoutError)

    mock_bm = MagicMock()
    mock_bm.kline_socket = MagicMock(return_value=mock_stream_ctx)
    mock_client = AsyncMock()
    mock_client.close_connection = AsyncMock()

    with patch("src.services.data_stream.AsyncClient") as mock_cls, \
         patch("src.services.data_stream.BinanceSocketManager", return_value=mock_bm), \
         patch("src.services.data_stream.asyncio.sleep", side_effect=fake_sleep):
        mock_cls.create = AsyncMock(return_value=mock_client)
        await asyncio.wait_for(stream.start(settings, queue), timeout=5.0)

    assert sleep_calls, "Expected asyncio.sleep to be called after TimeoutError"
    assert sleep_calls[0] == WS_INITIAL_RECONNECT_DELAY, (
        f"Expected first backoff={WS_INITIAL_RECONNECT_DELAY}s, got {sleep_calls[0]}s"
    )


@pytest.mark.asyncio
async def test_bot_status_broadcast_on_reconnect():
    """After reconnect, bot_status event must be broadcast to the dashboard."""
    stream = DataStream()
    settings = make_settings()
    queue: asyncio.Queue = asyncio.Queue()
    connect_count = 0

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_stream_ctx.recv = AsyncMock(side_effect=lambda: (stream.stop() or None))

    mock_bm = MagicMock()
    mock_bm.kline_socket = MagicMock(return_value=mock_stream_ctx)
    mock_client = AsyncMock()
    mock_client.close_connection = AsyncMock()

    async def fake_create(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            raise ConnectionError("first attempt fails")
        return mock_client

    mock_broadcaster = AsyncMock()
    mock_broadcaster.broadcast = AsyncMock()
    mock_bot_engine = MagicMock()
    mock_bot_engine.state.value = "idle"

    with patch("src.services.data_stream.AsyncClient") as mock_cls, \
         patch("src.services.data_stream.BinanceSocketManager", return_value=mock_bm), \
         patch("src.services.data_stream.asyncio.sleep", new_callable=AsyncMock):
        mock_cls.create = AsyncMock(side_effect=fake_create)
        await asyncio.wait_for(
            stream.start(settings, queue, broadcaster=mock_broadcaster, bot_engine=mock_bot_engine),
            timeout=5.0,
        )

    mock_broadcaster.broadcast.assert_called_once()
    call_args = mock_broadcaster.broadcast.call_args[0][0]
    assert call_args["type"] == "bot_status"
    assert call_args["payload"]["state"] == "idle"
