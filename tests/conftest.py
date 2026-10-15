import os

# Set test credentials before any module-level imports that call get_settings()
# Dummy values so API tests run without a .env or real keys (never real credentials).
os.environ.setdefault("PROD_BINANCE_API_KEY", "dummy_prod_key")
os.environ.setdefault("PROD_BINANCE_API_SECRET", "dummy_prod_secret")
os.environ.setdefault("TEST_BINANCE_API_KEY", "dummy_test_key")
os.environ.setdefault("TEST_BINANCE_API_SECRET", "dummy_test_secret")
os.environ.setdefault("TRADING_ENV", "testnet")

from config.settings import get_settings  # noqa: E402

# Clear the lru_cache so tests start with fresh settings from env vars
get_settings.cache_clear()
