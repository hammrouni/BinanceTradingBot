# Development

## Tests and lint

Check that your API keys work:

```bash
python scripts/test_connection.py
```

Run the unit tests. `tests/conftest.py` sets dummy `PROD_`/`TEST_` Binance env vars, so no `.env` or real keys are needed:

```bash
python -m pytest tests/
```

The dashboard escaping helpers have a Node test (needs Node 18+, no npm install); it also runs from pytest when `node` is on the PATH:

```bash
node --test tests/js/xss.test.mjs
```

The whole suite passes (dev dependencies are in `requirements-dev.txt`). CI (`.github/workflows/ci.yml`) runs `ruff check .` and pytest on Python 3.12; run `ruff check .` locally too.

Always validate a strategy on **testnet** (and in the simulator) before switching `TRADING_ENV=live`.
