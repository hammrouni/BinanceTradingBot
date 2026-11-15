# AI Agent Service

The `agent-service` is a PHP sidecar that adds LLM-powered analysis to BinanceTradingBot. It runs next to the Python bot in Docker and exposes a small REST API that the bot proxies under `/api/v1/agent/*`.

It is built on [NanoAgent](https://github.com/hammrouni/nanoagentphp) (`hammrouni/nanoagent` on Packagist), a lightweight PHP agent library by the same author. The agents follow NanoAgent's context-builder and conversation patterns; `BaseAgent` talks to the LLM directly over cURL so any OpenAI-compatible endpoint works, including a keyless local Ollama.

## Agents

| Agent | Route (`/api/agents/...`) | What it does |
|---|---|---|
| `TradingAdvisorAgent` | `trading/analyze` | Signal (BUY / SELL / HOLD), confidence, risk notes, TP/SL and config advice |
| `TradeHealthAgent` | `trade-health/analyze` | Rates the open position against recent volatility (ATR) and drawdown |
| `ConfigAuditorAgent` | `config-auditor/analyze` | Checks the active strategy and thresholds against the current market regime |
| `FeeWatchdogAgent` | `fee-watchdog/analyze` | Measures fee drag against profit |
| `SLTPOptimizerAgent` | `sltp-optimizer/analyze` | Compares SL/TP levels with nearby support and resistance |
| `LiquidityScoutAgent` | `liquidity-scout/analyze` | Order-book depth and slippage risk for the configured trade size |
| `StrategyResearcherAgent` | `strategy-researcher/analyze` | Backs the simulator's AI Optimizer (see [simulator.md](simulator.md)) |

Every agent only reasons about the data it is given. The agent service never calls Binance and holds no API keys. Its output is advice: the bot never trades on it automatically.

---

## Architecture

```
┌─────────────────────┐        HTTP POST        ┌──────────────────────┐
│  binance-bot :8000  │ ──────────────────────► │  agent-service :8090 │
│  (Python/FastAPI)   │                         │  (PHP/Apache)        │
└─────────────────────┘                         └──────────┬───────────┘
                                                           │ OpenAI-compatible API
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  LLM (Ollama /  │
                                                  │  OpenAI / etc.) │
                                                  └─────────────────┘
```

Both services share the `bot_net` Docker bridge network. The agent service never touches the Binance API directly — it only reasons about data fed to it.

---

## Configuration

### `.env` variables

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | OpenAI-compatible API base URL |
| `LLM_MODEL` | `gemma4:26b` | Model name to use (set it to a model you have) |
| `LLM_PROVIDER` | `openai` | Provider tag (informational) |
| `LLM_API_KEY` | `ollama` | API key — use `ollama` for local Ollama, real key for OpenAI |

### Switching to OpenAI

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
```

### Switching to a remote Ollama

```env
LLM_BASE_URL=http://<ollama-host>:11434/v1
LLM_MODEL=llama3.1:8b
LLM_API_KEY=ollama
```

---

## Running

```bash
# Start both services
docker compose up --build

# Agent service only
docker compose up agent-service

# Logs
docker compose logs -f agent-service
```

---

## API Reference

Base URL: `http://localhost:8090`

### `GET /api/health`

Returns service status and configured LLM model.

```json
{
  "service": "BinanceTradingBot Agent Service",
  "status": "healthy",
  "version": "1.0.0",
  "agents": ["TradingAdvisorAgent", "TradeHealthAgent", "ConfigAuditorAgent", "FeeWatchdogAgent", "SLTPOptimizerAgent", "LiquidityScoutAgent", "StrategyResearcherAgent"],
  "llm_model": "gemma4:26b",
  "timestamp": 1718000000
}
```

---

### `POST /api/agents/trading/analyze`

Full AI trading analysis. Returns signal, confidence, reasoning, risk notes, and suggested TP/SL prices. The analysis adapts to the bot's active mode (RSI or BC).

#### Request body — RSI mode

```json
{
  "symbol":  "BTCUSDT",
  "rsi":     28.5,
  "price":   84200.0,
  "candles": [
    { "open": 84100, "high": 84350, "low": 83950, "close": 84200, "volume": 12.5 },
    { "open": 84200, "high": 84400, "low": 84150, "close": 84300, "volume": 9.8 }
  ],
  "position": {
    "side":        "LONG",
    "entry_price": 83500.0,
    "quantity":    0.000178,
    "pnl_pct":     0.84
  },
  "config": {
    "mode":     "RSI",
    "rsi_buy":  30,
    "rsi_sell": 70,
    "tp_pct":   1.5,
    "sl_pct":   1.0
  },
  "trade_history": [
    { "direction": "BUY", "entry_price": 82000, "pnl_usd": 1.20, "reason": "rsi_oversold", "executed_at": "2024-06-10T09:00:00" }
  ]
}
```

#### Request body — BC mode

```json
{
  "symbol":  "BTCUSDT",
  "rsi":     56.0,
  "price":   71500.0,
  "candles": [ ],
  "position": null,
  "config": {
    "mode":          "BC",
    "bc_buy_price":  66581.99,
    "bc_sell_price": 73436.73,
    "tp_pct":        3.0,
    "sl_pct":        2.0
  },
  "trade_history": [
    { "direction": "BUY", "entry_price": 66600, "pnl_usd": -0.50, "reason": "bc_target", "executed_at": "2024-06-09T14:00:00" }
  ]
}
```

#### Request fields

| Field | Type | Required | Description |
|---|---|---|---|
| `symbol` | string | no | Trading pair, e.g. `BTCUSDT` |
| `rsi` | float | RSI mode only | Current RSI-14 value |
| `price` | float | **yes** | Current market price |
| `candles` | array | no | Last N 1-min OHLC candles |
| `position` | object\|null | no | Open position snapshot, or `null` if flat |
| `config` | object | no | Bot config snapshot (see below) |
| `trade_history` | array | no | Last N closed trades for win-rate analysis |

#### `config` object fields

| Field | Type | Modes | Description |
|---|---|---|---|
| `mode` | string | all | `"RSI"` or `"BC"` |
| `rsi_buy` | float | RSI | Oversold threshold — buy trigger |
| `rsi_sell` | float | RSI | Overbought threshold — sell trigger |
| `bc_buy_price` | float | BC | Fixed price at which the bot buys |
| `bc_sell_price` | float | BC | Fixed price at which the bot sells |
| `tp_pct` | float | all | Take-profit percentage |
| `sl_pct` | float | all | Stop-loss percentage |

#### Response

```json
{
  "agent":      "TradingAdvisorAgent",
  "symbol":     "BTCUSDT",
  "signal":     "HOLD",
  "confidence": 72,
  "reasoning":  "The current price of $71,500 is between the BC buy target ($66,581.99) and sell target ($73,436.73), sitting 7.4% above the buy level and 2.7% below the sell level. The price trend is sideways with low momentum. No action is warranted until price approaches one of the configured BC levels.",
  "risk_notes": ["Price is close to BC sell target — monitor for reversal"],
  "suggested_tp": 73436.73,
  "suggested_sl": 69900.0,
  "config_advice": {
    "should_change": false,
    "changes": []
  },
  "action_advice": "Wait for price to drop to the BC buy level ($66,581.99) before the bot triggers a buy.",
  "timestamp": 1718000000
}
```

| Field | Type | Description |
|---|---|---|
| `signal` | `BUY` \| `SELL` \| `HOLD` | Recommended action |
| `confidence` | 0–100 | < 50 = uncertain, > 75 = strong conviction |
| `reasoning` | string | 2–3 sentence explanation grounded in actual data |
| `risk_notes` | array | Risk warnings (empty if none) |
| `suggested_tp` | float\|null | Suggested take-profit price (absolute) |
| `suggested_sl` | float\|null | Suggested stop-loss price (absolute) |
| `config_advice` | object | Whether config changes are recommended, and what |
| `action_advice` | string | One actionable sentence for the trader |

#### `config_advice` recommended fields by mode

| Mode | Advisable fields |
|---|---|
| RSI | `rsi_buy`, `rsi_sell`, `tp_pct`, `sl_pct` |
| BC  | `bc_buy_price`, `bc_sell_price`, `tp_pct`, `sl_pct` |

---

## Agents

### `TradingAdvisorAgent`

**File:** `agent-service/agents/TradingAdvisorAgent.php`

Mode-aware trading advisor that adapts its analysis strategy based on `config.mode`:

**RSI mode** — analyzes RSI value against configured thresholds, price action, and trade history to determine if RSI calibration is correct. Recommends changes to `rsi_buy`, `rsi_sell`, `tp_pct`, `sl_pct`.

**BC mode** — analyzes current price relative to the fixed `bc_buy_price` / `bc_sell_price` targets. RSI is not used for entry/exit decisions in this mode and is never suggested as a config change. The agent evaluates whether the BC price levels are well-placed given current market structure and recent trade performance around those levels. Recommends changes to `bc_buy_price`, `bc_sell_price`, `tp_pct`, `sl_pct`.

Both modes use low LLM temperature (0.25) for deterministic, data-driven output. The agent is intentionally conservative:
- Does not invent data it was not given
- Returns `HOLD` when confidence is low
- Always surfaces risk warnings when signal quality is marginal

---

## Adding a New Agent

1. Create `agent-service/agents/YourAgent.php` extending `BaseAgent`
2. Implement `execute(array $input): array`
3. Add a route in `agent-service/public/index.php`

```php
// agent-service/agents/MarketRegimeAgent.php
namespace App\Agents;

class MarketRegimeAgent extends BaseAgent
{
    public function __construct(array $config)
    {
        parent::__construct($config, 'You are a market regime classifier...');
        $this->defaultTemperature = 0.2;
    }

    public function execute(array $input): array
    {
        $result = $this->callLLMForJSON($prompt);
        return $result['data'] ?? ['error' => $result['error']];
    }
}
```

---

## Integration with the Python Bot

Call the agent service from any Python route to augment a decision with AI context:

```python
import httpx

async def get_ai_signal(price: float, candles: list, position: dict | None, config: dict) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "http://agent-service/api/agents/trading/analyze",
            json={
                "symbol":   config.get("trading_pair", "BTCUSDT"),
                "price":    price,
                "candles":  candles,
                "position": position,
                "config": {
                    # RSI mode
                    "mode":     "RSI",
                    "rsi_buy":  config.get("rsi_oversold", 30),
                    "rsi_sell": config.get("rsi_overbought", 70),
                    "tp_pct":   config.get("take_profit_pct", 1.5),
                    "sl_pct":   config.get("stop_loss_pct", 1.0),
                    # BC mode (include when mode == "BC")
                    # "mode":          "BC",
                    # "bc_buy_price":  config.get("bc_buy_price"),
                    # "bc_sell_price": config.get("bc_sell_price"),
                },
            },
        )
        return resp.json()
```

> Inside Docker the service is reachable at `http://agent-service` (container name). From outside Docker use `http://localhost:8090`.

---

## File Structure

```
agent-service/
├── agents/
│   ├── BaseAgent.php               # LLM client, JSON extraction, retry, context injection
│   ├── TradingAdvisorAgent.php
│   ├── TradeHealthAgent.php
│   ├── ConfigAuditorAgent.php
│   ├── FeeWatchdogAgent.php
│   ├── SLTPOptimizerAgent.php
│   ├── LiquidityScoutAgent.php
│   ├── StrategyResearcherAgent.php
│   └── AILogger.php                # Structured LLM call logging (storage/ai-logs, git-ignored)
├── public/index.php                # Router: all HTTP endpoints
├── config.php                      # LLM config from env vars
├── tests/AgentTest.php             # PHPUnit
└── composer.json                   # hammrouni/nanoagent + phpunit

docker/agent.Dockerfile             # PHP 8.4 + Apache image
```

Run the PHP tests with `composer install && vendor/bin/phpunit` inside `agent-service/`.

---

## See Also

- [ai-features.md](ai-features.md): chat, MCP and how the bot uses these agents
- [strategies.md](strategies.md): the strategies the agents reason about
- [configuration.md](configuration.md): LLM environment variables
