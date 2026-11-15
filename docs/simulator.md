# Simulator and AI Optimizer

`/simulator.html` replays 1-7 days of 1-minute candles (public Binance production market data only) through **the same code as the live bot**: the strategy classes in `src/core/strategies/`, the shared buy filters (`filters.py`) and the SL / trailing / TP arithmetic in `src/core/risk.py`. `src/core/replay.py` just feeds each candle to them as a `TickContext`, so there is no separate "simulator version" of RSI, RSI Ultra, BC or the filters. `tests/core/test_replay_parity.py` checks it: the same candles through a real `BotEngine` and through the harness produce identical trades.

- **Candle history** comes from one place, `src/services/history_loader.py` (also used to seed the live bot): paginated 1m klines, RSI(14) and RSI Ultra with the periods of your saved config, warm-up candles stripped. If the bot's own candle history already covers the window it is used instead of a fetch.
- **Intra-candle exits.** A position opened at a candle close is exposed to the following candles' high and low. If one candle touches both the stop and the target the **stop wins**; the trailing stop is first lifted by the candle's high (the high is assumed to come before the low). Stops fill at the stop price (at the open if the candle gaps through it), targets at the target price.
- **Fees** are charged on both the buy and the sell (`Fee %` field). Every number is net of fees: a trade that gains 0.05% with 0.1% fees per side is a loss and counts as one.
- **BC mode** grid offsets apply to a *rolling reference*: the median close of the previous 24 h at each candle (no BC signal during the first 30 candles). The old whole-window median leaked future prices into the targets. The `Buy $` / `Sell $` columns show the targets as of the end of the window; **Apply** saves those as fixed prices.
- **Metrics:** PnL, win rate (net PnL > 0), max drawdown (equity curve, peak to trough), **Sharpe** (per trade: mean / stdev of net trade returns, not annualised; shown as a dash with fewer than two trades), **PF** (profit factor = gross profit / gross loss, infinity when nothing was lost) and **Expect $** (average net PnL per trade).
- RSI-overbought and BC-sell targets sell even when a take-profit is set, exactly like live.

## AI Optimizer

The **AI Optimizer** card on `/simulator.html` searches for settings that win *consistently* instead of once (code: `src/services/strategy_research.py`, agent: `agent-service/agents/StrategyResearcherAgent.php`). Start it with **Find best config**; it runs as a background job (2-5 min):

1. Loads 6-14 days of candles for the bot's pair.
2. Builds ~600 candidates: a grid for RSI (with EMA-trend / bear-block filters), RSI Ultra and BC, plus up to 8 settings the LLM proposes after reading web-search snippets (the bundled private SearXNG container, else Brave Search with `BRAVE_API_KEY`, else quant.stackexchange.com excerpts).
3. Replays **every** candidate, with fees, on separate day-windows through the same replay harness as the simulator. The AI's ideas get no shortcut: the backtest decides.
4. Ranks on the early ~70% of the windows and re-checks the best on the later, unseen windows. It reports **Candidate found** only if the best setting is profitable on both and traded enough; otherwise **No reliable edge found** (a common, honest answer in a falling market).
5. The LLM writes a plain-language summary; it cannot change any number.

Safety: web text is untrusted (stripped of markup, passed to the LLM as data only, no arbitrary URL is ever fetched); AI output is whitelisted and clamped to fixed ranges; nothing is applied until you click **Apply** on a row. Returns are % of the trade size per day-window, after fees. A "Candidate" is still only a candidate: forward-test it on testnet first.

