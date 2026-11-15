# API Reference

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

