# BinanceTradingBot

An automated cryptocurrency trading bot that implements a **Spot DCA (Dollar-Cost Averaging) strategy enhanced with RSI (Relative Strength Index) signals**. It features a real-time web dashboard for monitoring trades, adjusting configuration, and tracking PnL — all without touching Binance manually.

---

## Table of Contents

- [How It Works](#how-it-works)
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

The bot monitors BTC/USDT (configurable) 1-minute candlestick data from Binance via WebSocket and applies the following strategy:

1. **Buy Signal** — When RSI drops below the configured threshold (default: 30, i.e. oversold), the bot places a market buy order for the configured USD amount.
2. **Stop-Loss** — If the price falls a configured percentage below the entry price (default: 5%), the bot automatically sells the position to cap losses.
3. **No Leverage** — Only Spot trading is used. You own the actual coins and cannot be liquidated.

The dashboard displays live price, RSI chart, bot status, trade history, and realized PnL — updated in real-time via WebSocket.

---

## Requirements

- Python **3.10** or higher
- A [Binance account](https://www.binance.com) with API access
  - For safe testing: use the [Binance Testnet](https://testnet.binance.vision)
- Git (to clone the repository)

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

> Note: `pandas-ta` is installed from a custom Git fork. Ensure you have Git available in your PATH.

### 4. Create the data directory

```bash
mkdir data
```

This directory stores `config.json` (trading settings) and `trades.jsonl` (trade history).

---

## Configuration

### Step 1 — Set up API credentials

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
TRADING_ENV=testnet
```

| Variable | Description | Values |
|---|---|---|
| `BINANCE_API_KEY` | Your Binance API key | String |
| `BINANCE_API_SECRET` | Your Binance API secret | String |
| `TRADING_ENV` | Trading environment | `testnet` or `live` |

> **Start with `testnet` to test without risking real funds.**
> Switch to `live` only when you are confident in the bot's behavior.

#### How to get API keys

**Testnet (recommended for testing):**
1. Go to [testnet.binance.vision](https://testnet.binance.vision)
2. Log in with GitHub
3. Generate API Key and Secret

**Live (real trading):**
1. Log in to [binance.com](https://www.binance.com)
2. Go to Profile → API Management
3. Create a new API key
4. Enable **Spot & Margin Trading** permission only — do NOT enable withdrawal

---

### Step 2 — Trading parameters (via Dashboard or API)

Trading parameters are stored in `data/config.json` and can be updated live through the dashboard or the REST API without restarting the bot.

| Parameter | Default | Description |
|---|---|---|
| `trading_pair` | `BTCUSDT` | Cryptocurrency pair to trade |
| `trade_amount_usd` | `5.0` | USD amount per buy order (must be > 0) |
| `rsi_threshold` | `30` | RSI level that triggers a buy (1–100) |
| `stop_loss_pct` | `5.0` | Stop-loss percentage below entry price (0.1–50.0) |

---

## Running the Bot

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Or for development with auto-reload:

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

On startup the bot will:
- Validate the Binance API connection
- Load trading configuration from `data/config.json`
- Start background tasks for market data streaming and processing
- Serve the dashboard at `http://localhost:8000`

---

## Using the Dashboard

Open your browser and go to:

```
http://localhost:8000
```

### Dashboard Layout

**Left Panel — Bot Controls**
- **Status indicator** — shows `STOPPED`, `RUNNING`, or `PAUSED`
- **Start / Pause / Resume** buttons
- **Configuration form** — update trading pair, amount, RSI threshold, and stop-loss percentage live

**Right Panel — Market & Trades**
- **Current price** — live BTC/USDT (or configured pair) price
- **RSI value** — current 14-period RSI
- **RSI chart** — scrolling chart of RSI over time
- **Trade history table** — all executed trades with entry price, quantity, and PnL

**Error Banner**
- Displays API failures or connection issues at the top of the page
- Shows a history of the last 20 errors with timestamps

### Typical Workflow

1. Open the dashboard at `http://localhost:8000`
2. Review the default configuration in the left panel and adjust if needed
3. Click **Start** to activate the bot
4. Monitor price and RSI in the right panel
5. Trades appear in the trade history table as they execute
6. Click **Pause** to temporarily stop the bot without losing state
7. Click **Resume** to continue from where it left off

---

## API Reference

The bot exposes a REST API for programmatic control.

### Status

```
GET /api/v1/status
```
Returns bot status and uptime.

### Bot Control

```
POST /api/v1/bot/start
POST /api/v1/bot/pause
POST /api/v1/bot/resume
```

### Configuration

```
GET  /api/v1/config
PUT  /api/v1/config
```

Example PUT body:
```json
{
  "trading_pair": "BTCUSDT",
  "trade_amount_usd": 10.0,
  "rsi_threshold": 28,
  "stop_loss_pct": 4.0
}
```

### Trades

```
GET /api/v1/trades
```
Returns trade history with PnL calculations.

### WebSocket

```
ws://localhost:8000/ws/dashboard
```
Real-time stream of market updates, trade events, bot state changes, and errors.

---

## Project Structure

```
BinanceTradingBot/
├── main.py                   # FastAPI app entry point
├── requirements.txt          # Python dependencies
├── pytest.ini                # Test configuration
├── .env.example              # Environment variable template
├── .env                      # Your credentials (do not commit)
├── data/
│   ├── config.json           # Trading configuration (auto-created)
│   └── trades.jsonl          # Trade history log (auto-created)
├── logs/
│   └── bot.log               # Rotating application logs
├── static/
│   ├── index.html            # Dashboard UI
│   ├── css/dashboard.css     # Dashboard styles
│   └── js/
│       ├── api.js            # REST API client
│       ├── chart.js          # RSI chart rendering
│       └── dashboard.js      # WebSocket and UI logic
├── src/
│   ├── api/
│   │   ├── routes/           # REST route handlers
│   │   └── websocket.py      # WebSocket connection manager
│   ├── core/
│   │   ├── bot_engine.py     # Trading state machine and order logic
│   │   ├── market_processor.py # Kline processing and RSI calculation
│   │   ├── rsi_calculator.py # 14-period RSI using 150-candle window
│   │   ├── pnl_calculator.py # FIFO buy/sell matching for PnL
│   │   ├── trade_logger.py   # Async trade persistence
│   │   └── config_manager.py # Load/save config.json
│   ├── models/               # Pydantic data models
│   ├── services/
│   │   ├── binance_client.py # Binance API wrapper
│   │   └── data_stream.py    # Binance WebSocket kline listener
│   └── utils/
│       ├── logger.py         # Logging setup with credential filtering
│       └── retry.py          # Exponential backoff retry decorator
└── tests/                    # pytest test suite
```

---

## Testing

Run the full test suite:

```bash
pytest
```

Run with verbose output:

```bash
pytest -v
```

Tests use `pytest-asyncio` for async coverage and `httpx` for API endpoint testing. All tests run against mocked Binance clients — no real API calls are made.

---

## Safety Notes

- **Always start on testnet.** The bot is designed to be safe, but test thoroughly before switching to `live`.
- **Never enable withdrawal permissions** on your Binance API key. The bot only needs Spot trading permission.
- **Never commit your `.env` file.** It is listed in `.gitignore` by default.
- **Stop-loss is not guaranteed** in extreme market conditions (flash crashes, exchange outages). Only trade amounts you can afford to lose.
- **This is not financial advice.** Automated trading carries risk. Use responsibly.
