# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-16

First stable release. Covers everything built since the initial commit.

### Added

- **Trading engine** with pluggable strategies and a separate order executor.
- **Strategies**: RSI, RSI Ultra (HLC3 input, crossover signals), and BC price-target mode.
- **Buy filters**: MA and EMA trend filters, minimum move percentage, shared across strategies and selectable via `active_filters`.
- **Risk controls**: take-profit, stop-loss (including support-level stop-loss), trailing logic, nullable thresholds so each can be turned off, TP anchor and BC sizing options. Arithmetic lives in `core/risk.py`.
- **Live dashboard**: candlestick and RSI charts with trade markers, live price/RSI ticker, wallet and multi-environment balances, net-worth view, per-trade fees and net PnL, trade reasons, preset dropdown, log viewer.
- **Manual trading** via API and UI, plus wallet refresh.
- **Simulator** that replays history through the live strategies, with an **AI Optimizer** that ranks candidate settings by replay.
- **AI features**: PHP/Apache `agent-service` with multi-agent trading advisor, language and theme options, LLM chat and RSS news (restricted to known feeds).
- **Runtime changes**: trading pair and RSI Ultra period follow config changes without restart; thresholds refresh live.
- **Optional token auth** for the API and a locked-down agent service.
- **Tooling**: Dockerfile and `docker-compose.yml`, GitHub Actions CI (Python and PHP jobs), ruff config, `scripts/` connection check, `run.sh` / `run.bat`.
- **Docs**: landing-page README, `docs/` guides (getting started, configuration, strategies, simulator, safety, API, architecture, AI features, development), user guides in English and Arabic, `CONTRIBUTING.md`.

### Changed

- Agent image moved to PHP 8.4; dependency pins refreshed.
- RSI uses a 500-candle window so Wilder RSI matches Binance and TradingView.
- Candles are stamped with kline `open_time`; closed candles are published immediately.
- WebSocket broadcast is concurrent with a per-client timeout.
- Chat and RSS handling are async and share one config service.
- Removed the Bollinger Band filter; `min_bc_price` is migrated automatically.

### Fixed

- **Fund safety**: hardened order handling, kept position when balance lookup fails on stop-loss, `quoteOrderQty` rounding, assets taken from `symbol_info`, retry logic splits HTTP status from Binance error codes.
- **Persistence**: JSON writes are atomic; a corrupt config is recovered instead of crashing.
- **Recovery**: positions recovered on testnet; PnL paired per pair and environment.
- **Security**: dependencies pinned, CDN scripts pinned with SRI hashes, LLM and agent text escaped before insertion into the dashboard, every configured secret masked in logs.
- **Strategies**: RSI Ultra SELL evaluated before the amount guard; `on_reset` implemented.
- **Agents**: real fees and PnL, true 24h volatility, RSI history and summarised candles.

### Security

- Never commit API keys. Use `.env` (see `.env.example`) and testnet first. See [docs/safety.md](docs/safety.md).

[1.0.0]: https://github.com/hammrouni/BinanceTradingBot/releases/tag/v1.0.0
