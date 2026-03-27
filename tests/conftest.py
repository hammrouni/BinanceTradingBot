import os

# Set test credentials before any module-level imports that call get_settings()
os.environ.setdefault("BINANCE_API_KEY", "test_key")
os.environ.setdefault("BINANCE_API_SECRET", "test_secret")
os.environ.setdefault("TRADING_ENV", "testnet")

from config.settings import get_settings  # noqa: E402

# Clear the lru_cache so tests start with fresh settings from env vars
get_settings.cache_clear()
