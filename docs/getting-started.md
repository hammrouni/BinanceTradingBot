# Getting Started

## Requirements

- Python **3.10+** (Docker image uses 3.12)
- Binance API keys:
  - a **production** key for market data (read-only is enough)
  - a **testnet** key from <https://testnet.binance.vision> and/or a **live** trading key
- Optional: Docker + Docker Compose, and an OpenAI-compatible LLM (Ollama, Groq, OpenAI) for the AI features

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

## Running the Bot

### Option 1: Python

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

`run.bat` does the same on Windows (it binds to `127.0.0.1`). Only use `--host 0.0.0.0` if you set `DASHBOARD_TOKEN` and understand that the bot can then be reached from your network.

Install dependencies with `pip install -r requirements.txt` (add `-r requirements-dev.txt` for the tests).

### Option 2: Docker Compose (bot + agent service)

```bash
docker compose up -d --build
```

```bash
docker compose logs -f
```

`./data` and `./logs` are mounted for persistence. The dashboard is at <http://localhost:8000> and the agent service at <http://localhost:8090>. Both ports are published on `127.0.0.1` only. The agent service gets its LLM settings from the compose environment; `.env` is not mounted into it.

### Dashboard token (optional)

Set `DASHBOARD_TOKEN` in `.env` to require a shared secret on `/api/v1/*`, `/ws/dashboard` and `/mcp`. Send it in the `X-Dashboard-Token` header or the `dashboard_token` cookie. The dashboard asks for it on the first `401` and stores it in the browser (`localStorage` plus a `SameSite=Strict` cookie for the WebSocket). `GET /api/v1/health` and the static files stay open. MCP clients must send the header. When `DASHBOARD_TOKEN` is empty, auth is off, so keep the default `127.0.0.1` binding.

The agent service allows CORS only from `CORS_ALLOWED_ORIGINS` (default `http://localhost:8000,http://127.0.0.1:8000`) and has no authentication of its own: do not expose port 8090.

## Using the Dashboard

| Page | URL | Purpose |
|---|---|---|
| Dashboard | `/` | Live price/RSI, candlestick chart with SL/TP/entry/BC lines, bot controls, wallets, config, open position, trade history, AI panel, chat |
| Simulator | `/simulator.html` | Grid-search backtest (1–7 days of 1m data) for RSI / RSI Ultra / BC; replay a parameter set on the chart; "run current config"; see [simulator.md](simulator.md) |
| Logs | `/logs.html` | Filter and search `logs/bot.log` |

Tips:
- In BC mode, drag the BC buy/sell lines on the chart; the config auto-saves.
- **Manual Buy / Manual Sell** work in any bot state. Manual sell closes the bot's open position.
- Trade history has two tables: **prod** (from your Binance production account) and **test** (from the local `data/trades.jsonl`).

