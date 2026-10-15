# BinanceTradingBot

An automated **spot-only** cryptocurrency trading bot for Binance. It trades 1-minute candles with three interchangeable strategies (RSI, RSI Ultra, BC price targets), protects positions with stop-loss / trailing-stop / take-profit, and comes with a real-time web dashboard, a strategy simulator, an AI chat assistant, and optional LLM "micro-agents" for analysis.

> ⚠️ **Status:** an October 2026 code review found several safety issues that should be fixed before you trade real money. Read [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md) and the [Known limitations](#known-limitations) section first.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Bot](#running-the-bot)
- [Using the Dashboard](#using-the-dashboard)
- [AI Features](#ai-features)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Safety Notes](#safety-notes)

---

## How It Works

The bot subscribes to Binance **1-minute klines** over WebSocket. Every closed candle updates RSI(14) and RSI Ultra, then goes to the bot engine. The engine runs exactly **one active strategy**, chosen with `active_modes` in the dashboard.

### Strategies

| Mode (`active_modes`) | Buy | Sell (signal) |
|---|---|---|
| `RSI` | RSI crosses **below** `rsi_oversold` (edge-triggered: one buy per dip), and the optional filters pass | RSI crosses **above** `rsi_overbought` |
| `RSI_ULTRA` | RSI Ultra (EMA-RSI on HLC3) crosses **above** its signal line while below `rsi_ultra_zone_mid` | RSI Ultra crosses **below** its signal line while above `rsi_ultra_zone_mid` |
| `BC` | Price reaches **`bc_buy_price`** or lower (edge-triggered) | Price reaches **`bc_sell_price`** or higher |

All automatic buys spend `trade_amount_usd`, which is **required in every mode, including BC**. Values below $12 are raised to $12 to satisfy Binance's minimum notional. A **manual buy** with an empty trade amount spends all free USDT in the trading wallet.

### Optional buy filters (RSI mode; MA/EMA also in RSI Ultra)

| Field | Effect |
|---|---|
| `price_bounce_ticks` | Price must be higher than it was N candles ago (the bounce has started) |
| `bear_trend_candles` + `bear_trend_pct` | Block buys if price fell more than X% over the last N candles |
| `ma_filter_period` | Buy only when price < SMA(N) |
| `ema_fast_period` + `ema_slow_period` | Buy only when EMA(fast) > EMA(slow) |
| `min_move_pct` | Block all buys when `take_profit_pct` is below this value |

### Risk management (all modes)

| Field | Effect |
|---|---|
| `stop_loss_pct` | Sell when price < entry × (1 − SL%) |
| `sl_lookback_candles` + `sl_buffer_pct` | Alternative SL: lowest low of the last N candles minus the buffer % (overrides `stop_loss_pct`) |
| `trailing_stop_pct` | Ratchets the SL upward as price rises; it never moves down |
| `take_profit_pct` | Sell when price ≥ entry × (1 + TP%). `0` or empty disables it |

Stop-loss and take-profit stay active while the bot is **PAUSED**. They are **not** checked while STOPPED or in ERROR, and they are evaluated on candle **close** prices only (see [Known limitations](#known-limitations)).

### Bot states

`STOPPED → RUNNING ⇄ PAUSED → STOPPED`, plus `ERROR` (restart with **Start**). The state and open position are saved in `data/bot_state.json` and **restored on restart**: a bot that was RUNNING resumes trading automatically.

---

## Architecture

```
Binance PROD WS (1m klines) ─► DataStream ─► market_processor (RSI, RSI Ultra)
                                   │                    │
                                   │ per-tick price     ├─► ws_broadcaster ─► Dashboard (WebSocket)
                                   ▼                    ▼
                               Dashboard          BotEngine ─► Strategy (RSI | RSI_ULTRA | BC)
                                                      │
                                                      ├─► TradeExecutor ─► Binance TRADING client (testnet | live)
                                                      └─► PositionManager (recover / reconcile with wallet)

FastAPI also serves: REST API (/api/v1), chat (/api/v1/chat), MCP server (/mcp/sse), static dashboard (/)
PHP agent-service (port 8090): LLM micro-agents, called through /api/v1/agent/*
```

**Dual-client design**

- **Market data client (PROD)**: always Binance production, so signals use real liquidity and prices, even when you trade on testnet.
- **Trading client (TESTNET or LIVE)**: places the orders and holds the trading wallet. Selected by `TRADING_ENV`.

---

## Requirements

- Python **3.10+** (Docker image uses 3.12)
- Binance API keys:
  - a **production** key for market data (read-only is enough)
  - a **testnet** key from <https://testnet.binance.vision> and/or a **live** trading key
- Optional: Docker + Docker Compose, and an OpenAI-compatible LLM (Ollama, Groq, OpenAI) for the AI features

---

## Installation

```bash
git clone https://github.com/hammrouni/BinanceTradingBot.git
cd BinanceTradingBot
python -m venv venv
```

Activate the venv: `venv\Scripts\activate` on Windows, `source venv/bin/activate` on macOS/Linux. Then:

```bash
pip install -r requirements.txt
```

> If startup fails with `No module named 'mcp.server.fastmcp'`, pip installed `mcp` 2.x. Pin the 1.x line:

```bash
pip install "mcp[cli]<2"
```

---

## Configuration

### Step 1: environment (`.env`)

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `PROD_BINANCE_API_KEY` / `_SECRET` | yes | Production keys, used for market data and the "real portfolio" view |
| `TEST_BINANCE_API_KEY` / `_SECRET` | yes | Testnet trading keys |
| `LIVE_BINANCE_API_KEY` / `_SECRET` | no | Live trading keys; falls back to the PROD keys when `TRADING_ENV=live` |
| `TRADING_ENV` | no | `testnet` (default) or `live` (**real money**) |
| `TRADING_PAIR` | no | Pair for the market-data stream (default `BTCUSDT`). **Keep it equal to the dashboard pair** |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT`, `LLM_MAX_TOKENS` | no | OpenAI-compatible LLM for the chat and the agents |
| `AGENT_SERVICE_URL` | no | URL of the PHP agent service (default `http://localhost:8090`) |

Never commit `.env`. Only `.env.example` (placeholders) belongs in git.

### Step 2: trading parameters (dashboard)

Trading parameters live in `data/config.json` and change live from the dashboard (**Save**). No restart is needed, except for the pair (see Known limitations).

| Parameter | Default | Description |
|---|---|---|
| `trading_pair` | `BTCUSDT` | Spot pair (USDT quote) |
| `active_modes` | `["RSI"]` | Strategy: `RSI`, `RSI_ULTRA` or `BC` |
| `trade_amount_usd` | `15.0` | USD per automatic buy (min 12) |
| `rsi_oversold` / `rsi_overbought` | `30` / `70` | RSI buy / sell thresholds (1–100) |
| `rsi_ultra_period` / `rsi_ultra_signal_period` | `14` / `9` | RSI Ultra lengths (*currently not applied to live trading*) |
| `rsi_ultra_zone_mid` | `50` | RSI Ultra midpoint for buy/sell zones |
| `bc_buy_price` / `bc_sell_price` | `null` | BC mode price targets (draggable lines on the chart) |
| `stop_loss_pct` | `5.0` | 0.1–50 |
| `take_profit_pct` | `2.0` | 0 = disabled, else 0.1–100 |
| `trailing_stop_pct` | `null` | 0.1–50 |
| `sl_lookback_candles` / `sl_buffer_pct` | `null` / `0.1` | Support-level stop-loss |
| `price_bounce_ticks` | `null` | 1–20 |
| `bear_trend_candles` / `bear_trend_pct` | `null` | 3–500 / 0.1–20 |
| `ma_filter_period`, `ema_fast_period`, `ema_slow_period` | `null` | 2–500 |
| `min_move_pct` | `null` | 0.1–10 |
| `agent_language` / `agent_theme` | `EN` / `technical` | AI answers: `EN`/`FR`/`AR`; `technical`/`simple`/`detailed` |
| `min_bc_price` | `null` | **Legacy.** If set, it still anchors take-profit in every mode; clear it in `data/config.json` |
| `active_filters`, `bb_period` | `[]` / `null` | Saved by the UI but **not used by the engine yet** |

---

## Running the Bot

### Option 1: Python

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

`run.bat` does the same on Windows, but binds to `0.0.0.0`, which exposes the bot to your network.

### Option 2: Docker Compose (bot + agent service)

```bash
docker compose up -d --build
```

```bash
docker compose logs -f
```

`./data` and `./logs` are mounted for persistence. The dashboard is at <http://localhost:8000> and the agent service at <http://localhost:8090>.

> There is **no authentication**. Do not expose ports 8000/8090 beyond your own machine.

---

## Using the Dashboard

| Page | URL | Purpose |
|---|---|---|
| Dashboard | `/` | Live price/RSI, candlestick chart with SL/TP/entry/BC lines, bot controls, wallets, config, open position, trade history, AI panel, chat |
| Simulator | `/simulator.html` | Grid-search backtest (1–7 days of 1m data) for RSI / RSI Ultra / BC; replay a parameter set on the chart; "run current config" |
| Logs | `/logs.html` | Filter and search `logs/bot.log` |

Tips:
- In BC mode, drag the BC buy/sell lines on the chart; the config auto-saves.
- **Manual Buy / Manual Sell** work in any bot state. Manual sell closes the bot's open position.
- Trade history has two tables: **prod** (from your Binance production account) and **test** (from the local `data/trades.jsonl`).

---

## AI Features

All AI features are optional and use any OpenAI-compatible endpoint.

- **Chat** (`POST /api/v1/chat/message`): asks the LLM with read-only tools (status, config, trades, P&L, balances, market summary, logs, crypto RSS news). It replies in `agent_language`.
- **MCP server** (`/mcp/sse`): exposes status, config (read **and update**), trades and RSS to external MCP clients such as Claude Desktop.
- **Agent service** (PHP, `agent-service/`), proxied by `/api/v1/agent/*`:
  - `trading`: full signal + confidence + TP/SL suggestion
  - `trade-health`: assessment of the open position
  - `config-auditor`: checks thresholds against current volatility
  - `fee-watchdog`: fee drag analysis
  - `sltp-optimizer`: SL/TP placement vs. recent structure
  - `liquidity-scout`: order-book depth vs. trade size

See [docs/agent-service.md](docs/agent-service.md) and [docs/agents.md](docs/agents.md).

---

## API Reference

All REST endpoints are prefixed with `/api/v1`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/status` | Bot state, uptime, open position (with SL/TP), balances |
| `POST` | `/refresh-wallet` | Re-fetch balances from Binance and broadcast |
| `POST` | `/bot/start` · `/bot/pause` · `/bot/resume` · `/bot/stop` | State transitions (409 if invalid) |
| `POST` | `/bot/manual-buy` · `/bot/manual-sell` | Manual market orders |
| `GET` / `PUT` | `/config` | Read / replace the trading config (PUT refreshes SL/TP of an open position) |
| `GET` / `POST` / `DELETE` | `/config/rsi-history` | RSI threshold change history |
| `GET` | `/trades` | Production trade history (Binance) with FIFO P&L |
| `GET` | `/trades/test` | Local trade log (`data/trades.jsonl`) with FIFO P&L |
| `GET` | `/market/history` | Last 24h of 1m candles + RSI kept in memory |
| `GET` | `/market/orderbook?symbol=&limit=` | Order book snapshot |
| `GET` | `/logs?level=&search=&limit=&offset=` | Parsed log lines |
| `POST` | `/simulator/data` · `/simulator/run` · `/simulator/run-current` · `/simulator/trades` | Load history, grid search, simulate current config, replay with events |
| `POST` | `/agent/{trading\|trade-health\|config-auditor\|fee-watchdog\|sltp-optimizer\|liquidity-scout}/analyze` | AI agents (needs the agent service) |
| `POST` | `/chat/message` | AI chat |

**WebSocket** `ws://<host>/ws/dashboard` message types: `market_update`, `rsi_history`, `bot_status`, `trade_executed`, `error`.

**MCP (SSE)**: `http://<host>/mcp/sse`.

---

## Project Structure

```
BinanceTradingBot/
├── main.py                     # FastAPI app, lifespan (seed history, start tasks), WebSocket, mounts
├── config/settings.py          # .env settings (Pydantic)
├── src/
│   ├── api/
│   │   ├── routes/             # bot, config, status, trades, logs, market, simulator, agent, chat
│   │   └── websocket.py        # ConnectionManager + broadcaster
│   ├── core/
│   │   ├── bot_engine.py       # Orchestrator: state machine, SL/TP/trailing, strategy dispatch
│   │   ├── strategies/         # base.py, rsi.py, rsi_ultra.py, bc.py
│   │   ├── executor.py         # Market buy/sell + trade logging + broadcast
│   │   ├── position_manager.py # Recover / reconcile the open position with the wallet
│   │   ├── market_processor.py # Closed kline → RSI / RSI Ultra → queues
│   │   ├── rsi_calculator.py   # RSI(14)
│   │   ├── rsi_ultra_calculator.py
│   │   ├── simulator.py        # Backtest / grid search
│   │   ├── pnl_calculator.py   # FIFO P&L
│   │   ├── config_manager.py   # data/config.json I/O
│   │   └── trade_logger.py / trade_reader.py  # data/trades.jsonl
│   ├── mcp_server/             # FastMCP server + shared tool helpers
│   ├── models/                 # TradingConfig, TradeRecord, KlineData, RSI history
│   ├── services/               # binance_client (dual client), data_stream (kline WS), rsi_history_service
│   └── utils/                  # logger (credential filter), retry (backoff)
├── agent-service/              # PHP 8.2 LLM agents (Docker service "agent-service")
├── static/                     # index.html, simulator.html, logs.html, css/, js/{chart,dashboard,simulator,agents}
├── scripts/                    # Connection / balance / API diagnostics
├── tests/                      # pytest suite
├── docs/                       # User guides (EN/AR), agent docs, CODE_REVIEW.md
└── data/  logs/                # Runtime (git-ignored): config.json, bot_state.json, trades.jsonl, bot.log
```

---

## Testing

Check that your API keys work:

```bash
python scripts/test_connection.py
```

Run the unit tests. They import `main.py`, so the `.env` variables must exist; dummy values are fine:

```bash
python -m pytest tests/
```

**Current baseline (2026-10-15): 130 passed / 48 failed.** The failing tests in `tests/core/test_bot_engine.py` and `test_optional_config.py` still target the engine API from before the strategy refactor. Rewriting them is Phase 5 in [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md).

Always validate a strategy on **testnet** (and in the simulator) before switching `TRADING_ENV=live`.

---

## Known limitations

These are tracked, with fixes, in [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md):

- **No authentication** on the API, WebSocket or MCP endpoints. Keep the bot on localhost.
- Stop-loss / take-profit are checked on **1-minute candle closes**, so price can move past them within the candle.
- A failed balance call can make the bot **forget its open position**. Reconciliation also adopts the **whole wallet balance** of the base asset as the position, including coins you held before.
- Reconnecting the dashboard or refreshing the wallet **resets a trailing stop** to its initial level.
- Changing `trading_pair` in the dashboard does **not** switch the market-data stream. Set `TRADING_PAIR` in `.env` to match and restart.
- The `rsi_ultra_period` / `rsi_ultra_signal_period` settings and the filter toggles (`active_filters`, `bb_period`) have no effect yet.
- The bot restores the RUNNING state after a restart and trades immediately.

---

## Safety Notes

- **Start on testnet.** Verify the behaviour before switching to `live`.
- **Never enable withdrawal permission** on API keys. Use IP whitelisting.
- **Never commit `.env`** or real keys, including in `.env.example`.
- **Precision guard:** sell quantities are floored to the symbol's LOT_SIZE, and orders below MIN_NOTIONAL are rejected before they are sent.
- **Edge-triggered signals:** the bot waits for a threshold to be *crossed*, so it does not buy repeatedly within a single dip.
- **Stop-loss is not guaranteed** during flash crashes or exchange outages.
- **This is not financial advice.** Automated trading is risky. Only trade what you can afford to lose.
