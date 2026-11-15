import os

# Set test credentials before any module-level imports that call get_settings()
# Dummy values so API tests run without a .env or real keys (never real credentials).
os.environ.setdefault("PROD_BINANCE_API_KEY", "dummy_prod_key")
os.environ.setdefault("PROD_BINANCE_API_SECRET", "dummy_prod_secret")
os.environ.setdefault("TEST_BINANCE_API_KEY", "dummy_test_key")
os.environ.setdefault("TEST_BINANCE_API_SECRET", "dummy_test_secret")
os.environ.setdefault("TRADING_ENV", "testnet")
# A real .env may define a dashboard token / search endpoints; tests must not depend on them.
os.environ["DASHBOARD_TOKEN"] = ""
os.environ["SEARXNG_URL"] = ""
os.environ["BRAVE_API_KEY"] = ""

from config.settings import get_settings  # noqa: E402

# Clear the lru_cache so tests start with fresh settings from env vars
get_settings.cache_clear()
