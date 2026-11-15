# AI Features

All AI features are optional and use any OpenAI-compatible endpoint.

- **Chat** (`POST /api/v1/chat/message`): asks the LLM with read-only tools (status, config, trades, P&L, balances, market summary, logs, crypto RSS news). It replies in `agent_language`. LLM calls are async and capped at 60 s (`LLM_TIMEOUT` above 60 is ignored), so a slow model never blocks trading.
- **MCP server** (`/mcp/sse`): exposes status, config (read **and update**), trades and RSS to external MCP clients such as Claude Desktop. Config updates go through the same validated path as the dashboard (`PUT /config`): they apply to the running bot immediately and are recorded in the RSI threshold history.
- **P&L figures** in chat/MCP/agents are computed with the FIFO pairing used by the trade history and are already net of fees.
- **News feeds**: `read_rss_feed` accepts only the built-in names (`coindesk`, `cointelegraph`, `bitcoin_magazine`, `decrypt`, `theblock`, `cryptopanic`); arbitrary URLs are refused.
- **Prompt size**: agents receive a candle summary (ATR, range, swing highs/lows) plus the last 60 candles instead of 24 h of raw candles.
- **Safe rendering**: all LLM/agent text is HTML-escaped in the dashboard (`static/js/utils/escape.js`).
- **Agent service** (PHP, `agent-service/`), proxied by `/api/v1/agent/*`. It is built on [NanoAgent](https://github.com/hammrouni/nanoagentphp) (`hammrouni/nanoagent`), a small PHP agent library by the same author, and runs as its own Docker service. The agents are advisory only: nothing they return is applied without a click in the UI.
  - `trading`: signal, confidence and TP/SL suggestion
  - `trade-health`: assessment of the open position
  - `config-auditor`: checks thresholds against current volatility
  - `fee-watchdog`: fee drag analysis
  - `sltp-optimizer`: SL/TP placement vs. recent structure
  - `liquidity-scout`: order-book depth vs. trade size
  - `strategy-researcher`: powers the simulator's [AI Optimizer](simulator.md#ai-optimizer)

See [agent-service.md](agent-service.md) for the service API, configuration and how to add an agent.
