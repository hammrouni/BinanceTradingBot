# BinanceTradingBot — User Guide

---

## Table of Contents

1. [What Is This Bot?](#1-what-is-this-bot)
2. [The Trading Algorithm — How It Works](#2-the-trading-algorithm--how-it-works)
3. [Technical Trading Terms Explained](#3-technical-trading-terms-explained)
4. [Interface Walkthrough — Every Section](#4-interface-walkthrough--every-section)
5. [Step-by-Step: First Use](#5-step-by-step-first-use)
6. [Reading the Trade History Tables](#6-reading-the-trade-history-tables)
7. [Common Scenarios](#7-common-scenarios)

---

## 1. What Is This Bot?

BinanceTradingBot is an automated cryptocurrency trading bot that connects to your Binance account and trades a spot pair (e.g. BTC/USDT) on your behalf using high-fidelity production signals.

It uses the **RSI (Relative Strength Index)** to decide both **when to buy** and **when to take profit**, along with a **stop-loss** rule to protect your capital.

---

## 2. The Trading Algorithm — How It Works

The bot follows a logic-based strategy designed to buy low and sell high:

### Step 1 — Monitor Price & RSI
The bot fetches live production data from Binance. Every minute, it calculates the RSI(14) value.

### Step 2 — Buy when RSI crosses DOWN (Oversold)
The bot waits for the RSI to drop below your configured `RSI Oversold` threshold (default: 30).
- **Rule**: If Previous RSI >= 30 AND Current RSI < 30 → **MARKET BUY**.

### Step 3 — Sell for Profit or Safety
The bot will automatically sell your position under two conditions:
1. **Take Profit (Overbought)**: If the RSI rises above your `RSI Overbought` threshold (default: 70), the bot sells to lock in gains.
2. **Stop-Loss**: If the price drops below your configured `Stop-Loss %` (default: 5% below entry), the bot sells to prevent further loss.

---

## 3. Technical Trading Terms Explained

### Dual-Client Architecture
The bot uses your Production API keys for pure market data and your Trading keys (Testnet or Live) for balance and orders. This ensures your signals are always based on the real market, even when practicing.

### Notional Value
Binance requires every trade to be above a certain value (usually $10 in production, $5 in many testnets). If your `Trade Amount` is too low, or if the price drops, an order might fail. The bot now includes safety checks to warn you if an order is too small to execute.

### Lot Size / Precision
Every coin has a different rule for how many decimals you can use (e.g., you can't buy exactly 0.000000001 BTC). The bot automatically adjusts ("floors") your quantities to meet these requirements using a high-precision decimal safety layer.

---

## 4. Interface Walkthrough — Every Section

### 4.1 Controls Panel (Top Left)
Located at the very top for quick access to **Start**, **Stop**, and **Pause** buttons.

### 4.2 Status & Wallets
- **Dual Wallet Display**: See your "Real Prod Wallet" (read-only) and your "Trading Wallet" (Testnet or Live) simultaneously.
- **Environment Badge**: Clearly shows if the "Trading Wallet" is `TESTNET` or `LIVE`.

### 4.3 RSI Chart
- **Signal Markers**: Triangles (signals) and Rectangles (test signals) appear on the chart where trades happened.
- **Dashed Lines**: Show your configured RSI Buy/Sell thresholds.

---

## 5. Step-by-Step: First Use

1. **API Keys**: Set all four keys (Prod ×2, Test/Live ×2) in your `.env` file.
2. **Configure**: Set `RSI Oversold` (Buy point) and `RSI Overbought` (Sell point).
3. **Check Wallet**: Ensure your "Trading Wallet" has enough USDT.
4. **Start**: Click **▶ Start**.

---

## 6. Reading the Trade History Tables

Separate tables provide full transparency:
- **Binance Prod**: Historical trades from your real account.
- **Bot Test**: Trades executed by the bot in the current session.
- **⟳ Refresh**: Sync trades directly from the Binance API.

---

## 7. Common Scenarios

### "Order rejected: NOTIONAL"
Your trade value is too small for Binance. If BTC is at $60,000 and you try to buy/sell $4 worth, it fails. To prevent this, the bot strictly enforces a minimum trade value of **$12.0 USD** (recommended default: **$15.0 USD**), ensuring you consistently stay above Binance's minimum. 

### "Precision error fixed automatically"
The bot detected an invalid decimal count for the pair and corrected it (e.g., from 0.0000701 to 0.00007) to ensure acceptance by the exchange.

---

*BinanceTradingBot — Professional RSI-based spot trading*
