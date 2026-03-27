import asyncio
import random

from binance.exceptions import BinanceAPIException

from src.utils.logger import get_logger

logger = get_logger(__name__)

NON_RETRYABLE_CODES = {400, 401, 403, 404}
RETRYABLE_CODES = {429, 418, 1003}


class MaxRetriesExceededError(Exception):
    def __init__(self, last_exception: Exception):
        self.last_exception = last_exception
        super().__init__(f"Max retries exceeded: {last_exception}")


async def with_retry(func, *args, max_retries: int = 3, base_delay: float = 1.0, **kwargs):
    """Retry async callable with exponential backoff + jitter. For read operations only."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except BinanceAPIException as e:
            if e.status_code in NON_RETRYABLE_CODES:
                raise
            if e.status_code not in RETRYABLE_CODES:
                raise
            last_exc = e
        except (asyncio.TimeoutError, OSError, ConnectionError) as e:
            last_exc = e
        except Exception:
            raise  # unexpected errors are not retried

        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                "Binance API retry %d/%d after %.1fs — %s",
                attempt + 1, max_retries, delay, type(last_exc).__name__,
            )
            await asyncio.sleep(delay)

    raise MaxRetriesExceededError(last_exc)
