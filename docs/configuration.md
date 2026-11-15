# Configuration

## Step 1: environment (`.env`)

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `PROD_BINANCE_API_KEY` / `_SECRET` | yes | Production keys, used for market data and the "real portfolio" view |
| `TEST_BINANCE_API_KEY` / `_SECRET` | yes | Testnet trading keys |
| `LIVE_BINANCE_API_KEY` / `_SECRET` | no | Live trading keys; falls back to the PROD keys when `TRADING_ENV=live` |
| `TRADING_ENV` | no | `testnet` (default) or `live` (**real money**) |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TIMEOUT`, `LLM_MAX_TOKENS` | no | OpenAI-compatible LLM for the chat and the agents |
| `SEARXNG_URL` | no | Web research for the AI Optimizer. Docker sets it to the project's own private SearXNG (`binance-searxng`, no host port, `searxng/settings.yml`); empty disables it |
| `BRAVE_API_KEY` | no | Brave Search key for the Simulator's AI Optimizer web research (empty = quant.stackexchange.com fallback) |
| `LLM_JSON_MODE` | no | `1` (default): PHP agents request JSON output (`response_format`); `0` if the LLM server rejects it |
| `DASHBOARD_TOKEN` | no | Shared secret for the API, WebSocket and MCP (empty = no auth) |
| `RESTORE_RUNNING_ON_RESTART` | no | `true` resumes trading after a restart; default `false` restores PAUSED |
| `CORS_ALLOWED_ORIGINS` | no | Origins allowed by the PHP agent service (default: the local bot) |
| `AGENT_SERVICE_URL` | no | URL of the PHP agent service (default `http://localhost:8090`) |

Never commit `.env`. Only `.env.example` (placeholders) belongs in git.

## Step 2: trading parameters (dashboard)

Trading parameters live in `data/config.json` and change live from the dashboard (**Save**). No restart is needed. Changing `trading_pair` restarts the kline stream and reseeds RSI/history; it is refused (HTTP 409) while a position is open. Changing the RSI Ultra periods rebuilds the Ultra calculator and recomputes the chart history.

| Parameter | Default | Description |
|---|---|---|
| `trading_pair` | `BTCUSDT` | Spot pair (USDT quote) |
| `active_modes` | `["RSI"]` | Strategy: `RSI`, `RSI_ULTRA` or `BC` |
| `trade_amount_usd` | `15.0` | USD per automatic buy (min 12). May be empty in RSI/RSI Ultra (no buys) but not in BC unless `bc_use_full_balance` |
| `rsi_oversold` / `rsi_overbought` | `30` / `70` | RSI buy / sell thresholds (1–100) |
| `rsi_ultra_period` / `rsi_ultra_signal_period` | `14` / `9` | RSI Ultra lengths (1–500), applied live |
| `rsi_ultra_zone_mid` | `50` | RSI Ultra midpoint for buy/sell zones |
| `bc_buy_price` / `bc_sell_price` | `null` | BC mode price targets (draggable lines on the chart) |
| `bc_use_full_balance` | `false` | BC mode: spend all free USDT per buy instead of `trade_amount_usd` |
| `stop_loss_pct` | `5.0` | 0.1–50 |
| `take_profit_pct` | `2.0` | 0 = disabled, else 0.1–100 |
| `trailing_stop_pct` | `null` | 0.1–50 |
| `sl_lookback_candles` / `sl_buffer_pct` | `null` / `0.1` | Support-level stop-loss |
| `price_bounce_ticks` | `null` | 1–20 |
| `bear_trend_candles` / `bear_trend_pct` | `null` | 3–500 / 0.1–20 |
| `ma_filter_period`, `ema_fast_period`, `ema_slow_period` | `null` | 2–500 |
| `active_filters` | `[]` | Subset of `BOUNCE`, `BEAR`, `MA`, `EMA_TREND`: which buy filters apply |
| `min_move_pct` | `null` | 0.1–10; `take_profit_pct` must be ≥ this value |
| `agent_language` / `agent_theme` | `EN` / `technical` | AI answers: `EN`/`FR`/`AR`; `technical`/`simple`/`detailed` |

**Legacy fields.** `min_bc_price` was migrated once on load into `bc_buy_price` (with `tp_anchor: "bc_buy"` when BC mode was active) and no longer exists. `bb_period` was dropped, and a stored `min_move_pct` larger than `take_profit_pct` is cleared on load instead of resetting the whole config.

