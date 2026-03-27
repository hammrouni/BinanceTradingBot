# BinanceTradingBot

An automated cryptocurrency trading bot that implements a **Spot RSI Signal Strategy**. It features a real-time web dashboard for monitoring trades, adjusting configuration, and tracking PnL — all without touching Binance manually.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Bot](#running-the-bot)
- [Using the Dashboard](#using-the-dashboard)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Safety Notes](#safety-notes)

---

## How It Works

The bot monitors 1-minute candlestick data from Binance via WebSocket and applies a logic-based RSI signal strategy:

1. **Dual-Signal Strategy** — The bot triggers actions based on Relative Strength Index (RSI) thresholds:
   - **Buy Signal (Oversold)**: When RSI drops below the `rsi_oversold` threshold (e.g. 30), the bot executes a market buy.
   - **Sell Signal (Overbought)**: When RSI rises above the `rsi_overbought` threshold (e.g. 70), the bot executes a market sell to take profit.
2. **Stop-Loss** — If the price falls below a configured percentage (default: 5%) from your entry price, the bot automatically sells to protect your capital.
3. **No Leverage** — Strictly Spot trading. You own the actual assets and cannot be liquidated.

---

## Architecture

To ensure the highest accuracy for signals while allowing for safe testing, the bot uses a **Dual-Client Architecture**:

- **Market Data Client (PROD)**: Always connects to Binance Production to fetch high-fidelity, real-time price and RSI data.
- **Trading Client (TESTNET or LIVE)**: Connects to your choice of environment (Testnet for practice, Live for real trading) to execute orders and manage wallets.

**Why?** This allows you to test your strategy on the Testnet using **real production price signals**, which is much more accurate than using Testnet's own low-volume price data.

---

## Requirements

- Python **3.10** or higher
- A [Binance account](https://www.binance.com) with API access
- **Two sets of API keys** (highly recommended):
  - 1x Production API Key (for market data)
  - 1x Testnet API Key (for safe testing) OR 1x Live Trading Key

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/BinanceTradingBot.git
cd BinanceTradingBot
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create the data directory

```bash
mkdir data
```

---

## Configuration

### Step 1 — Set up API credentials

Copy the example environment file and fill in your credentials for both Production (data) and Trading (execution):

```bash
cp .env.example .env
```

Edit your `.env` file:

```env
# MARKET DATA (Always PROD)
PROD_BINANCE_API_KEY=xxx
PROD_BINANCE_API_SECRET=xxx

# TRADING (TESTNET or LIVE)
TEST_BINANCE_API_KEY=xxx
TEST_BINANCE_API_SECRET=xxx
LIVE_BINANCE_API_KEY=
LIVE_BINANCE_API_SECRET=

# GLOBAL SETTINGS
TRADING_ENV=testnet # or 'live'
```

---

### Step 2 — Trading parameters (via Dashboard)

Parameters are stored in `data/config.json` and can be updated live through the dashboard without restarting the bot.

| Parameter | Default | Description |
|---|---|---|
| `trading_pair` | `BTCUSDT` | Cryptocurrency pair (e.g. ETHUSDT) |
| `trade_amount_usd` | `15.0` | USD amount per buy order (minimum enforced: 12.0) |
| `rsi_oversold` | `30` | RSI level that triggers a BUY (Dynamic) |
| `rsi_overbought` | `70` | RSI level that triggers a SELL (Dynamic) |
| `stop_loss_pct` | `5.0` | Stop-loss percentage below entry price |

---

## Running the Bot

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Access the dashboard at `http://localhost:8000`.

---

## Using the Dashboard

### Dashboard Layout

**Left Panel — Bot Controls & Wallets**
- **Controls (Top)** — Start, Pause, Resume, and Stop buttons for immediate access.
- **Bot Status** — Real-time indicator and uptime counter.
- **Dual Wallets** — Simultaneously monitor your **Real Portfolio** and your **Trading Wallet** (Testnet or Live).
- **Configuration** — Update RSI thresholds and pair settings live.

**Right Panel — Market & Trades**
- **Price & RSI** — Live ticker and 1-minute RSI value.
- **RSI Chart** — Interactive chart with your custom Buy/Sell thresholds and signal markers.
- **Trade History** — Separate tables for Production and Test history with manual **Refresh (⟳)** buttons.

---

## API Reference

All REST endpoints are prefixed with `/api/v1`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/status` | Bot state, uptime, and open position |
| `POST` | `/bot/start` | Start the bot (from STOPPED or ERROR) |
| `POST` | `/bot/pause` | Pause the bot (from RUNNING) |
| `POST` | `/bot/resume` | Resume the bot (from PAUSED) |
| `POST` | `/bot/stop` | Stop the bot (from RUNNING or PAUSED) |
| `GET` | `/config` | Get current trading configuration |
| `PUT` | `/config` | Update trading configuration live |
| `GET` | `/trades` | Get production trade history with PnL |
| `GET` | `/trades/test` | Get test trade history with PnL |

**WebSocket**: `ws://<host>/ws/dashboard` — real-time market updates, bot status, trade events, and RSI history.

---

## Project Structure

```
BinanceTradingBot/
├── main.py                  # FastAPI app, lifespan, WebSocket endpoint
├── config/
│   └── settings.py          # Environment/API key management (Pydantic)
├── src/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── bot.py       # Start/Pause/Resume/Stop endpoints
│   │   │   ├── config.py    # Config GET/PUT endpoints
│   │   │   ├── status.py    # Bot status endpoint
│   │   │   └── trades.py    # Trade history endpoints
│   │   └── websocket.py     # ConnectionManager + broadcaster
│   ├── core/
│   │   ├── bot_engine.py    # Trading state machine & signal logic
│   │   ├── config_manager.py# Config file I/O
│   │   ├── market_processor.py # Kline → RSI pipeline
│   │   ├── pnl_calculator.py# FIFO PnL pairing
│   │   ├── rsi_calculator.py# RSI(14) computation
│   │   ├── trade_logger.py  # JSONL trade persistence
│   │   └── trade_reader.py  # Read local trade logs
│   ├── models/
│   │   ├── config.py        # TradingConfig (Pydantic)
│   │   ├── market.py        # KlineData model
│   │   └── trade.py         # TradeRecord model
│   ├── services/
│   │   ├── binance_client.py# Dual-client Binance wrapper
│   │   └── data_stream.py   # WebSocket kline stream
│   └── utils/
│       ├── logger.py        # Logging + credential filter
│       └── retry.py         # Exponential backoff with jitter
├── static/                  # Dashboard (HTML/CSS/JS)
├── data/                    # Runtime: config.json, trades.jsonl, bot_state.json
├── .env.example             # API key template
└── requirements.txt
```

---

## Testing

### 1. Connection Test

Verify your API keys work:

```bash
python test_connection.py
```

### 2. Unit Tests

```bash
python -m pytest tests/
```

### 3. Testnet Simulation

Always start with `TRADING_ENV=testnet` in your `.env` file. Monitor trades on the dashboard and verify signals match expected RSI behavior before switching to `live`.

---

## Safety Notes

- **Always start on testnet.** Verify your strategy triggers before switching to `live`.
- **Never enable withdrawal permissions** on your API keys. Trading permission is all the bot needs.
- **Precision Guard**: The bot automatically floors your order quantities to match Binance requirements, preventing "Illegal character" or "too many decimals" errors.
- **RSI Strategy**: This is an edge-triggered bot; it waits for RSI to *cross* your threshold, preventing multiple rapid buys in a single dip.
- **Financial Risk**: Automated trading is risky. Only trade what you can afford to lose. This is not financial advice.
- **Never commit your `.env` file.** It is listed in `.gitignore` by default.
- **Stop-loss is not guaranteed** in extreme market conditions (flash crashes, exchange outages). Only trade amounts you can afford to lose.
- **This is not financial advice.** Automated trading carries risk. Use responsibly.
