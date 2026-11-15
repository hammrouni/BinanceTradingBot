# Safety Notes and Known Limitations

## Known limitations


- Authentication is optional (`DASHBOARD_TOKEN`). Without it the API, WebSocket and MCP endpoints are open: keep the bot on localhost.
- Stops are checked on live ticks (~2 s), but a market sell can still fill below the stop in a fast move.
- The pair cannot be changed while a position is open (409). After a change the strategies use the seeded 1-minute closes as filter history, so the first minutes behave like the seed, not like live ticks.
- For a custom RSI Ultra period/signal the simulator recomputes Ultra from the candles of the window, so the first `period + signal` candles of a replay have no Ultra value and cannot trade.
- The PHP agent service health endpoint (`/health`) lists all agents but was only syntax-checked, not run, in the last pass.
- Log masking covers log messages, not exception traceback text; secrets of 4 characters or fewer are not masked.
- BC mode with `bc_use_full_balance` spends the entire free USDT balance per buy; there is no reserve.
- The simulator reuses the live strategy and risk code, but does not model slippage, order-book depth, sell-failure backoff or wallet limits; fills are at the candle close, the stop/target level or the open (gaps).


## Safety Notes

- **Start on testnet.** Verify the behaviour before switching to `live`.
- **Never enable withdrawal permission** on API keys. Use IP whitelisting.
- **Never commit `.env`** or real keys, including in `.env.example`.
- **Precision guard:** sell quantities are floored to the symbol's LOT_SIZE, and orders below MIN_NOTIONAL are rejected before they are sent.
- **Edge-triggered signals:** the bot waits for a threshold to be *crossed*, so it does not buy repeatedly within a single dip.
- **Stop-loss is not guaranteed** during flash crashes or exchange outages.
- **This is not financial advice.** Automated trading is risky. Only trade what you can afford to lose.

