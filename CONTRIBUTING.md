# Contributing to BinanceTradingBot

Thanks for contributing! This repo is a live-trading tool, so please be
conservative: small, focused, well-tested changes.

## Ground rules

- **Never commit real API keys** — not in `.env`, not in `.env.example`,
  not in test fixtures. Dummies only (`dummy_key`, `your_xxx_api_key`, ...).
- **Start on testnet.** Anything touching order placement must be testable
  with `TRADING_ENV=testnet` and dummy keys (no network calls in tests).
- Keep scope tight. If a change grows beyond its issue, split it.

## Python (main bot)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt ruff
ruff check .
python -m pytest -q
```

- Tests live in `tests/`, mirroring the `src/` layout.
- `tests/conftest.py` sets dummy env vars — keep them in sync with
  `config/settings.py` when you add or rename settings.

## PHP (agent-service)

```bash
cd agent-service
composer install
vendor/bin/phpunit
```

- Agents live in `agent-service/agents/`; deterministic logic is unit-tested
  with the LLM call mocked (`tests/AgentTest.php`).

## Style

- Python: `ruff` (see `ruff.toml`). PHP: PSR-4, follow the existing agents.
- Commits: imperative subject (`fix(engine): ...`, `docs: ...`), one logical
  change per commit.

## Pull requests

1. Fork + branch, or use a local branch.
2. Describe behaviour change, new settings, and risk in the PR body.
3. Tests and `ruff check .` must pass (CI enforces both).
4. No new runtime dependencies without a note in the PR (they must be
   pinned in `requirements.txt` / `composer.json`).
