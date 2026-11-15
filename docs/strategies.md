# Strategies and Risk Management

The bot subscribes to Binance **1-minute klines** over WebSocket. Every closed candle updates RSI(14) and RSI Ultra, then goes to the bot engine. The engine runs exactly **one active strategy**, chosen with `active_modes` in the dashboard.

## Strategies

| Mode (`active_modes`) | Buy | Sell (signal) |
|---|---|---|
| `RSI` | RSI crosses **below** `rsi_oversold` (edge-triggered: one buy per dip), and the optional filters pass | RSI crosses **above** `rsi_overbought` |
| `RSI_ULTRA` | RSI Ultra (EMA-RSI on HLC3) crosses **above** its signal line while below `rsi_ultra_zone_mid` | RSI Ultra crosses **below** its signal line while above `rsi_ultra_zone_mid` |
| `BC` | Price reaches **`bc_buy_price`** or lower (edge-triggered) | Price reaches **`bc_sell_price`** or higher |

Automatic buys spend `trade_amount_usd` (values below $12 are raised to $12 to satisfy Binance's minimum notional). **BC mode** needs either `trade_amount_usd` or the explicit opt-in **`bc_use_full_balance`**, which spends all free USDT on every BC buy (the flag wins over `trade_amount_usd`). Saving a BC config with neither is rejected (HTTP 422). A **manual buy** spends `trade_amount_usd`, or all free USDT when `bc_use_full_balance` is on in BC mode; with neither it is refused.

RSI Ultra sells are evaluated even when `trade_amount_usd` is empty (closing a position never needs an amount); only the buy needs it.

## Optional buy filters (RSI and RSI Ultra)

A filter applies **only when its toggle is ticked** (`active_filters`) **and** its parameters are set. Unticking a filter disables it even if its numbers are still filled in. The same functions drive the live bot and the simulator (`src/core/strategies/filters.py`).

| Toggle (`active_filters`) | Parameters | Effect |
|---|---|---|
| `BOUNCE` | `price_bounce_ticks` | Price must be higher than it was N candles ago (the bounce has started) |
| `BEAR` | `bear_trend_candles` + `bear_trend_pct` | Block buys if price fell at least X% over the last N candles |
| `MA` | `ma_filter_period` | Buy only when price < SMA(N) |
| `EMA_TREND` | `ema_fast_period` + `ema_slow_period` | Buy only when EMA(fast) > EMA(slow) |

The Bollinger-band filter (`BB` / `bb_period`) never existed in the engine and has been removed; old configs that contain it load fine and the entry is dropped. While a filter does not have enough history yet (for example right after a pair change) it does not block.

`min_move_pct` is **config validation**, not a market filter: saving is rejected when `take_profit_pct` is empty/0 or lower than `min_move_pct`.

## Risk management (all modes)

| Field | Effect |
|---|---|
| `stop_loss_pct` | Sell when price < entry × (1 − SL%) |
| `sl_lookback_candles` + `sl_buffer_pct` | Alternative SL: lowest low of the last N candles minus the buffer % (overrides `stop_loss_pct`) |
| `trailing_stop_pct` | Ratchets the SL upward as price rises; it never moves down |
| `take_profit_pct` | Sell when price ≥ anchor × (1 + TP%), where the anchor is set by `tp_anchor`. `0` or empty disables it |
| `tp_anchor` | `entry` (default): the price actually paid. `bc_buy`: the `bc_buy_price` target (requires `bc_buy_price`) |

Stop-loss, take-profit and the trailing stop are checked on **every live price tick** (about every 2 seconds), not just on candle closes. Strategies (RSI, RSI Ultra, BC) still run on closed candles only.

They stay active in **RUNNING, PAUSED and STOPPED** whenever a position is open: pressing *Stop* ends strategy trading, but never leaves a position without its stop. They are inactive in **ERROR**.

The position quantity is what the bot **bought** (from the order fill). Coins you held before are never adopted or sold: the wallet balance can only reduce the quantity (for example after fees), never increase it. A failed balance call never clears a position; only a confirmed zero (or unsellable dust) balance does.

**Thresholds** are computed once at entry. A support-level SL is frozen at the entry-time support. They are recomputed only when you change a risk setting (`stop_loss_pct`, `trailing_stop_pct`, `take_profit_pct`, `sl_*`), never by a wallet refresh or reconnect. With a trailing stop, a config change can raise the SL but never lowers it.

**Failed sells** are retried with exponential backoff (5 s, 10 s, 20 s, 40 s, capped at 60 s). After 5 consecutive failures the bot moves to **ERROR** and shows an error in the dashboard; the position stays open and you must sell manually or fix the cause and press **Start**. Manual and automatic buys and sells share one lock, so two orders never run at once.

## Bot states

`STOPPED → RUNNING ⇄ PAUSED → STOPPED`, plus `ERROR` (restart with **Start**). The state and open position are saved in `data/bot_state.json` (written atomically) and **restored on restart**.

**Restart behaviour:** a bot that was RUNNING comes back **PAUSED**, so it does not start buying until you press **Resume**. Its open position and SL/TP are restored and protected immediately. Set `RESTORE_RUNNING_ON_RESTART=true` in `.env` to restore RUNNING instead. A STOPPED bot stays STOPPED. A corrupt `data/config.json` is moved to `data/config.json.corrupt-<timestamp>` and the defaults are used (see the log).

