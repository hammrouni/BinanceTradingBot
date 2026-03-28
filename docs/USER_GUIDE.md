# BinanceTradingBot — Comprehensive User Guide

![Banner](help/ED6256B6-79BD-4F30-935F-938E33BC2EF9.png)

Welcome to the **BinanceTradingBot** user guide. This document explains how the bot works, the trading terms used, and a walkthrough of all features to help you trade cryptocurrency safely and effectively.

---

## 1. What Is This Bot?

BinanceTradingBot is an automated spot trading system designed for Binance. It uses the **Relative Strength Index (RSI)** to identify market momentum and execute trades on your behalf. 

### Key Features:
- **Dual-Client Architecture**: Uses production market data for the highest accuracy, even when trading on the Testnet.
- **RSI Strategy**: Automated Buy/Sell based on configurable momentum thresholds.
- **Safety First**: Integrated Stop-Loss and strict enforcement of Binance's Notional Value rules.
- **Real-Time Dashboard**: High-fidelity RSI charts and live balance tracking.

---

## 2. Technical Trading Terms Explained

Understanding these terms is essential for configuring the bot correctly:

### 2.1 RSI (Relative Strength Index)
RSI is a momentum oscillator that measures the speed and change of price movements. It ranges from 0 to 100.
- **Oversold (< 30)**: Indicates the asset may be undervalued (Potential Buy Signal).
- **Overbought (> 70)**: Indicates the asset may be overvalued (Potential Sell Signal).

### 2.2 Notional Value
The total value of an order (Price × Quantity). Binance enforces a **Minimum Notional Value** (typically $5 - $10 USD depending on the pair). If your trade is below this, it will be rejected.
> [!TIP]
> This bot recommends a minimum trade amount of **$15.00 USD** to account for price fluctuations.

### 2.3 Lot Size & Precision
Each trading pair has specific rules for decimals:
- **Price Precision**: The number of digits allowed after the decimal point for the price.
- **Lot Size (Qty Precision)**: The minimum increment for the quantity you can buy.
The bot automatically "floors" these values to ensure compliance with Binance rules.

### 2.4 Stop-Loss
A safety mechanism that automatically sells your position if the price drops by a certain percentage (e.g., 5%) from your entry point to prevent further capital loss.

---

## 3. Interface Walkthrough

### 3.1 Market Analysis (RSI Chart)
The main chart provides a visual representation of market momentum and trade signals.

![RSI Chart](help/DAAA3155-94D8-4311-8824-78D33BEB842E.png)

- **Blue Line**: Current RSI(14) value.
- **Dashed Lines**: Your configured Overbought (Green) and Oversold (Red) thresholds.
- **Markers**: Triangular icons indicate where the bot executed a Buy or Sell.

### 3.2 Open Position Details
When an active trade is in progress, you can monitor its performance in real-time.

![Open Position](help/87C999C0-5052-404B-A97F-1BCB63BE9BF0.png)

- **Entry Price**: The price at which you bought the asset.
- **Stop-Loss Price**: The calculated exit point for safety.
- **Unrealized P&L**: Your current profit or loss if you were to sell immediately.

### 3.3 Wallet & Status
Monitor your account balances across both **Production** (Real) and **Trading** (Test/Live) environments.

- **Status Indicator**: Shows if the bot is `RUNNING`, `PAUSED`, or `STOPPED`.
- **Environment Badge**: Clearly distinguishes between `TESTNET` and `LIVE` trading.

### 3.4 Trade History
Detailed logs of every execution, including fees and final P&L.

![Trade History](help/31D49343-E22A-4ABB-96D7-E56DBC5D4017.png)

---

## 4. Configuration Guide

To start trading, update your `.env` file with your Binance API credentials:

```env
# Production Keys (For Market Data)
PROD_BINANCE_API_KEY=your_key
PROD_BINANCE_API_SECRET=your_secret

# Trading Keys (Can be Testnet or Live)
TRADING_BINANCE_API_KEY=your_key
TRADING_BINANCE_API_SECRET=your_secret
TRADING_ENV=testnet # or live
```

### Strategic Settings:
- **Trading Pair**: The coin you want to trade (e.g., `BTCUSDT`).
- **RSI Thresholds**: Default is 30 (Buy) and 70 (Sell).
- **Stop-Loss %**: Maximum loss you are willing to take per trade.
- **Trade Amount**: The USD value per trade (Minimum $12.00).

---

## 5. Troubleshooting Common Errors

### "Order rejected: MIN_NOTIONAL"
- **Cause**: Your trade amount is too small.
- **Fix**: Increase the `TRADE_AMOUNT_USD` in your settings to at least $15.00.

### "Account has insufficient balance"
- **Cause**: You don't have enough USDT (for Buy) or the target coin (for Sell).
- **Fix**: Deposit funds into your Binance Trading account or switch to Testnet.

### "Signature is invalid"
- **Cause**: Incorrect API Key or Secret.
- **Fix**: Double-check your `.env` file for typos and ensure the keys have the correct permissions.

---

*BinanceTradingBot — Automated Precision for Crypto Traders*
