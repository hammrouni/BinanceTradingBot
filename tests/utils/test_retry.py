"""Tests for Story 6.1: Binance API retry with exponential backoff."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from binance.exceptions import BinanceAPIException

from src.utils.retry import MaxRetriesExceededError, with_retry


def make_binance_exc(status_code: int) -> BinanceAPIException:
    from unittest.mock import MagicMock
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {"code": -1000, "msg": "test"}
    exc = BinanceAPIException(response, status_code, '{"code": -1000, "msg": "test"}')
    return exc


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt():
    result = await with_retry(AsyncMock(return_value="ok"))
    assert result == "ok"


@pytest.mark.asyncio
async def test_succeeds_on_second_attempt():
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise make_binance_exc(429)
        return "success"

    with patch("src.utils.retry.asyncio.sleep", AsyncMock()):
        result = await with_retry(flaky)
    assert result == "success"
    assert call_count == 2


@pytest.mark.asyncio
async def test_max_retries_raises_max_retries_exceeded():
    async def always_fail():
        raise make_binance_exc(429)

    with patch("src.utils.retry.asyncio.sleep", AsyncMock()):
        with pytest.raises(MaxRetriesExceededError):
            await with_retry(always_fail, max_retries=3)


@pytest.mark.asyncio
async def test_http_400_raises_immediately_no_retry():
    call_count = 0

    async def bad_request():
        nonlocal call_count
        call_count += 1
        raise make_binance_exc(400)

    with patch("src.utils.retry.asyncio.sleep", AsyncMock()):
        with pytest.raises(BinanceAPIException):
            await with_retry(bad_request, max_retries=3)

    assert call_count == 1  # no retry


@pytest.mark.asyncio
async def test_http_401_not_retried():
    call_count = 0

    async def unauthorized():
        nonlocal call_count
        call_count += 1
        raise make_binance_exc(401)

    with pytest.raises(BinanceAPIException):
        await with_retry(unauthorized)
    assert call_count == 1


@pytest.mark.asyncio
async def test_timeout_error_is_retried():
    call_count = 0

    async def timeout_then_ok():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise asyncio.TimeoutError()
        return "recovered"

    with patch("src.utils.retry.asyncio.sleep", AsyncMock()):
        result = await with_retry(timeout_then_ok)
    assert result == "recovered"
    assert call_count == 2


@pytest.mark.asyncio
async def test_sleep_called_between_retries():
    async def fail_twice():
        raise make_binance_exc(429)

    mock_sleep = AsyncMock()
    with patch("src.utils.retry.asyncio.sleep", mock_sleep):
        with pytest.raises(MaxRetriesExceededError):
            await with_retry(fail_twice, max_retries=3)

    assert mock_sleep.call_count == 2  # sleeps between attempts, not after last


@pytest.mark.asyncio
async def test_unexpected_exception_not_retried():
    call_count = 0

    async def raises_value_error():
        nonlocal call_count
        call_count += 1
        raise ValueError("unexpected")

    with pytest.raises(ValueError):
        await with_retry(raises_value_error)
    assert call_count == 1
