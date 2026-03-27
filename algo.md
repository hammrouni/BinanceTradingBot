# RSI Signal-Driven Spot Strategy

The BinanceTradingBot implements a **Spot RSI Signal Strategy** designed for automated, logic-based accumulation and profit-taking in the cryptocurrency market. It is optimized for safety, strictly using the Spot market (no leverage) and high-fidelity production data for signals.

### 1. The Strategy: Double-Threshold RSI Signals

Traditional DCA (Dollar-Cost Averaging) buys at fixed time intervals. This strategy is smarter: it uses the Relative Strength Index (RSI) to time market entries and exits.

- **Accumulation (BUY)**: The bot waits for the RSI(14) to drop into the "Oversold" zone (e.g. < 30). This ensures you are buying into market fear when the price is relatively discounted.
- **Profit-Taking (SELL)**: The bot monitors for an "Overbought" condition (e.g. > 70). When reached, it executes a market sell to lock in gains and reset for the next cycle.
- **Safety (STOP-LOSS)**: A hard stop-loss is always active (e.g. 5% below entry). This caps the maximum downside of any single trade.

### 2. Dual-Client Architecture

A key technical advantage of this bot is its **Dual-Client Architecture**. Market signals are derived from your **Production API keys** (live Binance data) while trades are executed on your **Trading Keys** (Testnet or Live).

**Why this matters:**
Signal data on the Binance Testnet is often low-volume and disconnected from real market movements. By using production data for calculation, your Testnet simulation is 100% accurate to what would happen in a live environment.

### 3. Safety Mechanisms: Precision & Notional Filters

The bot handles two critical Binance exchange filters automatically:

- **Lot Size Filter (Precision)**: The bot automatically checks each pair's `stepSize` (e.g. 0.00001 BTC precision) and "floors" your order quantity to stay within valid limits. We use a high-precision decimal buffer to prevent floating-point binary artifacts.
- **Notional Filter (Min Value)**: Binance requires a minimum trade value (usually $10). The bot fetches `minNotional` and validates your order before sending it, preventing partial fills or common error rejections.

### 4. Optimal Strategy Configuration

For a risk-averse approach on a $100 account, we recommend:

```json
{
  "trading_pair": "BTCUSDT",
  "trade_amount_usd": 15.0, 
  "rsi_oversold": 30,
  "rsi_overbought": 70,
  "stop_loss_pct": 5.0
}
```

*Note: We recommend $15.0 instead of $10 to ensure you stay firmly above the Exchange Notional limit and cleanly bypass any partial fill issues. The engine strictly enforces a minimum of $12.0.*

---
*Educational Note: RSI strategies work best in trending markets. If the RSI stays low for an extended period, the bot will buy once and then wait for an Overbought signal or Stop-Loss trigger.*