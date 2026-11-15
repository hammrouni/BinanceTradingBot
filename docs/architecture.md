# Architecture

How the pieces fit together.

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

## Project structure

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
│   │   ├── simulator.py        # Grid search / single run API on top of replay.py
│   │   ├── replay.py           # Replay harness: live strategies + risk.py over candles
│   │   ├── risk.py             # SL / TP / trailing arithmetic shared by engine and simulator
│   │   ├── sim_metrics.py      # Net-of-fee metrics (win rate, Sharpe, profit factor, expectancy)
│   │   ├── pnl_calculator.py   # FIFO P&L
│   │   ├── config_manager.py   # data/config.json I/O
│   │   └── trade_logger.py / trade_reader.py  # data/trades.jsonl
│   ├── mcp_server/             # FastMCP server + shared tool helpers
│   ├── models/                 # TradingConfig, TradeRecord, KlineData, RSI history
│   ├── services/               # binance_client (dual client), data_stream (kline WS), rsi_history_service
│   └── utils/                  # logger (credential filter), retry (backoff)
├── agent-service/              # PHP 8.3 LLM agents (Docker service "agent-service")
├── static/                     # index.html, simulator.html, logs.html, css/, js/{chart,dashboard,simulator,agents}
├── scripts/                    # optimize_config.py (parameter search), test_connection.py (API key check)
├── tests/                      # pytest suite
├── docs/                       # User guides (EN/AR), agent service, strategy notes
└── data/  logs/                # Runtime (git-ignored): config.json, bot_state.json, trades.jsonl, bot.log
```
