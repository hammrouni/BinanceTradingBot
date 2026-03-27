# BinanceTradingBot — User Guide

---

## Table of Contents

1. [What Is This Bot?](#1-what-is-this-bot)
2. [The Trading Algorithm — How It Works](#2-the-trading-algorithm--how-it-works)
3. [Technical Trading Terms Explained](#3-technical-trading-terms-explained)
4. [Interface Walkthrough — Every Section](#4-interface-walkthrough--every-section)
5. [Step-by-Step: First Use](#5-step-by-step-first-use)
6. [Reading the Trade History Table](#6-reading-the-trade-history-table)
7. [Reading the Open Position Card](#7-reading-the-open-position-card)
8. [Common Scenarios](#8-common-scenarios)

---

## 1. What Is This Bot?

BinanceTradingBot is an automated cryptocurrency trading bot that connects to your Binance account and trades a spot pair (e.g. BTC/USDT) on your behalf, 24/7, without requiring you to watch the screen.

It uses a single indicator — the **RSI (Relative Strength Index)** — to decide **when to buy**, and a **stop-loss** rule to decide **when to sell**. Every trade is logged and shown in the dashboard in real time.

---

## 2. The Trading Algorithm — How It Works

The bot follows a simple, rule-based strategy with three steps:

### Step 1 — Monitor RSI continuously

Every 1-minute candle that closes on Binance is processed. The bot calculates the RSI(14) value from the last 14 closed candles. This number (0–100) tells the bot how "tired" or "overheated" the market is.

### Step 2 — Buy when RSI crosses DOWN below the threshold (edge-triggered)

The bot **only buys once per oversold event**. The exact rule is:

```
Previous RSI >= threshold  AND  Current RSI < threshold
→ Execute a MARKET BUY
```

This is called **edge-triggered**: the bot waits for the RSI to *enter* the oversold zone, not just be inside it. This prevents it from buying repeatedly while the RSI stays low.

**Example:** RSI threshold = 45. RSI was 48 last candle, now it's 42 → BUY. Next candle RSI is 40 → no action (already in oversold zone).

### Step 3 — Sell automatically when stop-loss is hit

After a buy, the bot calculates a stop-loss price:

```
Stop-Loss Price = Entry Price × (1 - Stop-Loss% / 100)
```

**Example:** Entry price = $68,954. Stop-Loss = 5%. → Stop-Loss price = $68,954 × 0.95 = **$65,506.44**

Every new price tick is checked. If `current price < stop-loss price`, the bot executes a **MARKET SELL** immediately.

> The stop-loss fires even when the bot is **Paused** — it always protects your open position.

### Full Decision Flow

```
[New 1-min candle closes]
        │
        ▼
[Calculate RSI(14)]
        │
        ├─ Open position? → Is price < stop-loss? → YES → SELL (market order)
        │
        └─ No open position + Bot RUNNING?
                │
                └─ RSI just crossed below threshold? → YES → BUY (market order)
                                                     → NO  → Wait
```

---

## 3. Technical Trading Terms Explained

### RSI — Relative Strength Index
A momentum indicator between 0 and 100 that measures how fast prices have been rising or falling.
- **Above 70** → "Overbought" — asset may be overpriced, often precedes a pullback.
- **Below 30** → "Oversold" — asset may be underpriced, often precedes a recovery.
- **30–70** → "Neutral" zone — no extreme signal.
- This bot uses **RSI(14)** — calculated over 14 one-minute candles.

### RSI Period (14)
The number of candles used to compute the RSI. The bot needs at least 15 closed candles before it can produce a valid RSI value. On startup, historical data is automatically fetched so the chart is populated immediately.

### RSI Threshold
The value you configure as your buy trigger. Default is 30 (classic oversold). The bot buys when RSI drops *below* this value for the first time. A higher threshold (e.g. 45) means the bot buys more frequently; a lower threshold (e.g. 20) means it waits for deeper dips.

### Oversold
When the RSI is below your threshold (or below 30 in classic usage). It signals the asset has been sold aggressively and may bounce.

### Overbought
When the RSI is above 70. It signals the asset has been bought aggressively and may pull back.

### Stop-Loss
A pre-set price level at which you automatically sell to limit your loss. If you buy at $68,954 with a 5% stop-loss, you will automatically sell if the price drops to $65,506 — capping your maximum loss at 5%.

### Market Order
An order that executes immediately at the current best available market price. The bot uses market orders for both buys and sells to guarantee execution.

### Trading Pair / Spot Pair
Two assets being traded against each other. `BTCUSDT` means you are buying Bitcoin (BTC) using USDT (Tether, a stablecoin pegged to the US Dollar). This is a **spot** trade — you own the actual asset.

### Candle / Kline
A single time-period bar on a price chart. Each 1-minute candle summarizes: open price, high price, low price, close price, and volume for that minute. The bot uses **close prices** to calculate RSI.

### Entry Price
The price at which the bot executed the buy order. This is the reference for calculating your stop-loss and P&L.

### Quantity (QTY)
The amount of the asset purchased. Since you trade a fixed USD amount, the quantity will vary:
`Quantity = Trade Amount (USD) ÷ Price`
At $68,954 with a $5 trade: `5 / 68954 = 0.000070 BTC`

### P&L — Profit and Loss
The financial result of a completed trade (buy + sell pair).
- **Positive P&L** (green) → the sell price was higher than the buy price → profit.
- **Negative P&L** (red) → the sell price was lower than the buy price → loss.
- A BUY row shows `—` because the trade is still open (P&L not yet realised).

### Unrealized P&L
The current gain or loss on an **open** position that has not been sold yet. It updates in real time as the price moves. It becomes "realized" only after the sell executes.

### Uptime
How long the bot has been in the RUNNING state since the last Start. Resets when you Stop or Pause the bot.

### WebSocket
A persistent, live connection between your browser and the bot server. It pushes real-time updates (price, RSI, trades) instantly without you needing to refresh the page. Shown as the **Live** dot in the top-right corner.

---

## 4. Interface Walkthrough — Every Section

---

### 4.1 Header Bar

![Header Bar](help/{D7D743CF-9A57-4435-A99D-EC3E8D4973D3}.png)

| Element | What It Shows | What It Means |
|---|---|---|
| **BinanceTradingBot** | App name | — |
| **PRICE** | Current live price of the trading pair | Updates every ~1 second via WebSocket |
| **RSI (14)** | Current RSI value | Computed from the last 14 closed 1-min candles |
| **STATUS** | Bot state: `Running` / `Stopped` / `Paused` | Green = active and trading |

When the bot is **stopped**, PRICE and RSI show `—` (dashes) until market data loads.

---

### 4.2 Connection Indicator (top-right)

| Indicator | Meaning |
|---|---|
| 🟢 **Live** | WebSocket connected — receiving real-time data |
| 🟡 **Connecting...** | Browser is trying to connect to the server |
| 🔴 **Disconnected** | Connection lost — data is stale |

---

### 4.3 Market Overview Card (right panel, top)

![Market Overview](help/{BD3D48ED-9F40-41C0-B43B-135EF63FF777}.png)

Displays the current **live price** (large, gold text) and the **RSI value** with a zone label:

| RSI Zone Label | RSI Range | Meaning |
|---|---|---|
| **OVERSOLD** | Below threshold | Potential buy signal zone |
| **NEUTRAL** | 30–70 | No extreme signal |
| **OVERBOUGHT** | Above 70 | Potential pullback zone |

---

### 4.4 Bot Status Card (left panel)

**When stopped:**

![Bot Status Stopped](help/{286EE5E2-FF78-4060-AF52-44BC84179AC8}.png)

- Grey dot + "Stopped" text
- Start button is shown (green)

**When running:**

![Bot Status Running](help/{C6FA6A8B-308B-48A8-AAF2-3E2E9E476C91}.png)

- Green dot + "Running" text
- **Uptime** counter shows how long the bot has been active
- Pause button is shown (yellow)

---

### 4.5 Controls Card (left panel)

Three buttons, only one visible at a time:

| Button | Color | When Shown | What It Does |
|---|---|---|---|
| **▶ Start** | Green | Bot is Stopped | Activates the bot — it will begin scanning RSI and trading |
| **⏸ Pause** | Yellow | Bot is Running | Halts new buys, but stop-loss remains active on any open position |
| **▶ Resume** | Green | Bot is Paused | Resumes full trading activity |

---

### 4.6 Configuration Card (left panel)

![Configuration](help/{5EA43447-521B-49C1-9E4A-FBF23331AFFA}.png)

| Field | Default | Valid Range | Effect |
|---|---|---|---|
| **Trading Pair** | `BTCUSDT` | Any valid Binance spot symbol | The market the bot will trade |
| **Trade Amount (USD)** | `5` | > 0 | How many USD to spend per buy order |
| **RSI Threshold** | `45` | 1–100 (typical: 30) | RSI must drop *below* this to trigger a buy |
| **Stop-Loss %** | `5` | 0.1–50 | Maximum loss % allowed before auto-sell |

Click **Save Configuration** to apply. Changes take effect on the next market tick — you do not need to restart the bot.

---

### 4.7 Open Position Card (left panel)

Appears automatically when a buy has been executed and disappears after the sell.

![Open Position](help/{E774AABF-A3D5-421F-84A1-987F41E8FE9A}.png)

| Field | Meaning |
|---|---|
| **PAIR** | The trading pair in this position (e.g. BTCUSDT) |
| **QUANTITY** | How much crypto was bought (e.g. 0.000070 BTC) |
| **ENTRY PRICE** | The price at which the buy was executed |
| **STOP-LOSS** | The price at which the bot will auto-sell (shown in red as a warning) |
| **CURRENT PRICE** | Live price, updated every tick |
| **UNREALIZED P&L** | Current profit/loss if the position were closed right now |

- **Red P&L** → position is currently at a loss
- **Green P&L** → position is currently at a profit

---

### 4.8 RSI Chart (right panel)

**Empty on startup (bot not yet running):**

![RSI Chart Empty](help/{4D9CE76F-5074-49B6-942B-821221AE3865}.png)

**Live with data:**

![RSI Chart Live](help/{ED6256B6-79BD-4F30-935F-938E33BC2EF9}.png)

The chart shows the last 60 minutes of RSI values in real time.

| Chart Element | Color | Meaning |
|---|---|---|
| **RSI line** | Blue | The live RSI(14) value over time |
| **Oversold line** | Red dashed | The RSI buy threshold you configured |
| **Overbought line** | Green dashed | RSI = 70 (classic overbought level) |
| **Buy dot** | Orange | A buy order was executed at this point in time |
| **Red shaded zone** | Below 30 | Classic oversold territory |
| **Green shaded zone** | Above 70 | Classic overbought territory |

**Hovering** over the chart shows a tooltip:

![Tooltip RSI](help/{DAAA3155-94D8-4311-8824-78D33BEB842E}.png)

Shows the exact time and RSI value at that point.

![Tooltip Buy Signal](help/{44DA9021-2C14-483C-B5F5-2A1A27085F4B}.png)

When hovering over an orange dot, the tooltip reads **"Buy signal executed"** with the RSI value at the moment of the trade.

---

### 4.9 Trade History Table (right panel)

![Trade History](help/{31D49343-E22A-4ABB-96D7-E56DBC5D4017}.png)

Shows every trade executed this session, most recent first.

| Column | Meaning |
|---|---|
| **TIME** | When the trade executed (relative, e.g. "12m ago") |
| **SIDE** | BUY (green) or SELL (red) |
| **AMOUNT** | USD value of the trade |
| **PRICE** | Execution price |
| **QTY** | Quantity of crypto bought or sold |
| **P&L** | Profit/Loss for completed sell trades; `—` for open buys |

**Top-right summary:**
- **N trades** — total number of trades executed
- **PnL: $X.XX** — total realized profit/loss across all completed trades (green = profit, red = loss)

---

## 5. Step-by-Step: First Use

1. **Configure** — Fill in Trading Pair, Trade Amount, RSI Threshold, Stop-Loss %, click **Save Configuration**.
2. **Check the RSI Chart** — Wait for the blue RSI line to appear (pre-seeded from historical data on load).
3. **Start the bot** — Click **▶ Start**. The status dot turns green and the uptime counter begins.
4. **Watch the chart** — The blue RSI line updates every minute. An orange dot appears when a buy fires.
5. **Monitor Open Position** — When a buy executes, the Open Position card appears showing your entry price, stop-loss level, and live P&L.
6. **Sell happens automatically** — If the price drops to the stop-loss level, the bot sells immediately. The Open Position card disappears and a SELL row appears in Trade History with the P&L.
7. **Pause anytime** — Click **⏸ Pause** to stop new buys without closing your open position.

---

## 6. Reading the Trade History Table

**Example rows:**

| TIME | SIDE | AMOUNT | PRICE | QTY | P&L |
|---|---|---|---|---|---|
| 12m ago | **BUY** | $5.00 | $68,904.14 | 0.000070 | — |
| 2h ago | **SELL** | $4.70 | $47,000.00 | 0.000100 | **$-0.30** |
| 2h ago | **BUY** | $5.00 | $50,000.00 | 0.000100 | — |

- The BUY at 12m ago shows `—` in P&L — this is the **current open position**, not yet sold.
- The SELL at 2h ago shows `$-0.30` — the bot bought at $50,000 and sold at $47,000, losing $0.30.
- P&L is only calculated on matched sell trades.

---

## 7. Reading the Open Position Card

When the card shows:
```
ENTRY PRICE    $68,954.15      STOP-LOSS     $65,506.44
CURRENT PRICE  $68,952.31      UNREALIZED P&L  $-0.00
```

- The bot bought BTC at **$68,954.15**
- If price falls to **$65,506.44** (5% below entry) → auto-sell triggers
- Current price is $68,952.31 — almost identical to entry → P&L is ~$0
- As price rises above entry → Unrealized P&L turns **green**
- As price falls below entry (but above stop-loss) → Unrealized P&L turns **red**

---

## 8. Common Scenarios

### "The bot is Running but not buying"
- RSI has not crossed below your threshold yet. This is normal — the bot waits for a genuine oversold signal.
- Try raising the RSI Threshold slightly (e.g. from 30 to 45) to trigger more frequently.

### "The bot bought and immediately stopped"
- The bot is in ERROR state due to an API issue. Check the Error Log section (appears at the bottom of the right panel when errors exist). Restart the bot after resolving the issue.

### "I see a SELL but no matching BUY"
- The session was restarted mid-trade. The bot persists its open position to disk and restored it, then the stop-loss fired.

### "RSI shows — in the header"
- The bot needs at least 15 closed 1-minute candles to compute RSI. Wait 1–2 minutes after the page loads. Historical data is pre-seeded so this should resolve quickly.

### "I want to stop trading without losing my position"
- Click **⏸ Pause**. The bot will not open new trades, but the stop-loss on your open position remains fully active.

---

*BinanceTradingBot — automated RSI-based spot trading on Binance*
