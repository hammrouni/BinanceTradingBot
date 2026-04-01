"""
Parameter simulation engine for backtesting different trading configs.
Replicates exact logic from bot_engine.py to test parameter combinations.
"""
import math
from typing import Optional


def _frange(start, stop, step):
    """Float range generator using integer indexing to avoid IEEE 754 drift (M4)."""
    i = 0
    while True:
        val = round(start + i * step, 10)
        if val > stop:
            break
        yield val
        i += 1


def _validate_range(r, name: str):
    """Validate a [min, max, step] range triple. Raises ValueError on bad input (C1, H1)."""
    if r is None:
        return
    if len(r) != 3:
        raise ValueError(f"{name}: range must have exactly 3 elements [min, max, step]")
    min_v, max_v, step = r
    if step <= 0:
        raise ValueError(f"{name}: step must be > 0 (got {step})")
    if min_v > max_v:
        raise ValueError(f"{name}: min ({min_v}) must be <= max ({max_v})")


def generate_param_combinations(rsi_oversold_range, rsi_overbought_range, stop_loss_range, take_profit_range):
    """Generate all valid parameter combinations from ranges.
    Each range is [min, max, step] or None to disable.
    Raises ValueError on invalid range inputs.
    """
    for name, r in [
        ("rsi_oversold_range", rsi_oversold_range),
        ("rsi_overbought_range", rsi_overbought_range),
        ("stop_loss_range", stop_loss_range),
        ("take_profit_range", take_profit_range),
    ]:
        _validate_range(r, name)

    def range_values(r):
        if r is None:
            return [None]
        min_v, max_v, step = r
        return [round(v, 2) for v in _frange(min_v, max_v, step)]

    oversold_vals = range_values(rsi_oversold_range)
    overbought_vals = range_values(rsi_overbought_range)
    sl_vals = range_values(stop_loss_range)
    tp_vals = range_values(take_profit_range)

    combos = []
    for os_val in oversold_vals:
        for ob_val in overbought_vals:
            # M5: skip nonsensical combos where oversold >= overbought
            if os_val is not None and ob_val is not None and os_val >= ob_val:
                continue
            for sl in sl_vals:
                for tp in tp_vals:
                    combos.append({
                        'rsi_oversold': os_val,
                        'rsi_overbought': ob_val,
                        'stop_loss_pct': sl,
                        'take_profit_pct': tp,
                    })
    return combos


def simulate_rsi_mode(
    market_history,
    rsi_oversold: Optional[int],
    rsi_overbought: Optional[int],
    stop_loss_pct: Optional[float],
    take_profit_pct: Optional[float],
    trade_amount_usd: float,
    initial_balance: float = 1000.0,
):
    """
    Simulate RSI trading mode with edge-triggered buy/sell signals.
    Matches exact logic from bot_engine.py process_market_update().
    """
    balance = initial_balance
    position = None  # {entry_price, qty, balance_before_buy}
    last_rsi_was_oversold = False
    last_rsi_was_overbought = False
    trades = []
    max_drawdown_pct = 0.0  # H4: track per-trade worst loss as % of balance

    for point in market_history:
        price = point.get('price')
        rsi = point.get('rsi')

        # M2: reject missing, zero, negative, or NaN prices
        if price is None or price <= 0 or math.isnan(price):
            continue

        # ─── STOP-LOSS CHECK (always active) ────────────────────────────────
        if position is not None:
            # H3: use `is not None` so stop_loss_pct=0 does not silently disable SL
            sl_price = position['entry_price'] * (1 - stop_loss_pct / 100) if stop_loss_pct is not None else None
            if sl_price is not None and price < sl_price:
                pnl = (price - position['entry_price']) * position['qty']
                balance += price * position['qty']
                trades.append(pnl)
                # H4: drawdown = loss as % of balance before the trade was entered
                if pnl < 0:
                    dd = abs(pnl) / position['balance_before_buy'] * 100
                    max_drawdown_pct = max(max_drawdown_pct, dd)
                position = None
                continue

        # ─── TAKE-PROFIT CHECK (always active) ────────────────────────────────
        if position is not None:
            tp_price = position['entry_price'] * (1 + take_profit_pct / 100) if take_profit_pct and take_profit_pct > 0 else None
            if tp_price is not None and price >= tp_price:
                pnl = (price - position['entry_price']) * position['qty']
                balance += price * position['qty']
                trades.append(pnl)
                position = None
                continue

        # Skip RSI signals if no RSI data
        if rsi is None or math.isnan(rsi):
            continue

        # ─── RSI OVERBOUGHT SELL (only if TP not configured) ─────────────────
        is_overbought = rsi > rsi_overbought if rsi_overbought is not None else False
        if (
            position is not None
            and rsi_overbought is not None
            and (take_profit_pct is None or take_profit_pct <= 0)  # TP not configured
            and is_overbought
            and not last_rsi_was_overbought
        ):
            pnl = (price - position['entry_price']) * position['qty']
            balance += price * position['qty']
            trades.append(pnl)
            if pnl < 0:
                dd = abs(pnl) / position['balance_before_buy'] * 100
                max_drawdown_pct = max(max_drawdown_pct, dd)
            position = None

        # ─── RSI OVERSOLD BUY (edge-triggered) ─────────────────────────────────
        is_oversold = rsi < rsi_oversold if rsi_oversold is not None else False
        if (
            position is None
            and rsi_oversold is not None
            and is_oversold
            and not last_rsi_was_oversold
            and balance >= trade_amount_usd
        ):
            qty = trade_amount_usd / price
            balance_before = balance  # capture BEFORE deducting cost (H4)
            balance -= trade_amount_usd
            position = {
                'entry_price': price,
                'qty': qty,
                'balance_before_buy': balance_before,
            }

        last_rsi_was_oversold = is_oversold
        last_rsi_was_overbought = is_overbought

    # Close any open position at final price
    if market_history:
        final_price = market_history[-1].get('price')
        if position and final_price and final_price > 0 and not math.isnan(final_price):
            pnl = (final_price - position['entry_price']) * position['qty']
            balance += final_price * position['qty']
            trades.append(pnl)
            if pnl < 0:
                dd = abs(pnl) / position['balance_before_buy'] * 100
                max_drawdown_pct = max(max_drawdown_pct, dd)

    # Calculate metrics
    total_pnl = balance - initial_balance
    total_pnl_pct = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0
    win_count = sum(1 for t in trades if t > 0)   # M1: strictly profitable only (> 0, not >= 0)
    win_rate = (win_count / len(trades) * 100) if trades else 0

    return {
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'win_rate': round(win_rate, 2),
        'trade_count': len(trades),
        'winning_trades': win_count,
        'losing_trades': len(trades) - win_count,
        'max_drawdown_pct': round(max_drawdown_pct, 2),
        'final_balance': round(balance, 2),
    }


def run_simulation(
    market_history,
    mode: str,
    initial_balance: float,
    rsi_oversold_range: Optional[list],
    rsi_overbought_range: Optional[list],
    stop_loss_range: list,
    take_profit_range: Optional[list],
    trade_amount_usd: float = 100.0,
):
    """
    Run grid search simulation over all parameter combinations.
    Returns top 50 results ranked by total_pnl descending.
    Raises ValueError on invalid inputs.
    """
    if not market_history:
        return {"status": "error", "message": "No market history available"}

    # M2: filter invalid prices (NaN, zero, negative, None)
    valid_history = [
        p for p in market_history
        if p.get('price') and p['price'] > 0 and not math.isnan(p['price'])
    ]
    if not valid_history:
        return {"status": "error", "message": "No valid market data"}

    # generate_param_combinations raises ValueError on bad ranges (C1, H1)
    combos = generate_param_combinations(
        rsi_oversold_range,
        rsi_overbought_range,
        stop_loss_range,
        take_profit_range,
    )

    if not combos:
        return {"status": "error", "message": "No valid parameter combinations generated. Check that oversold < overbought and ranges are valid."}

    results = []
    for combo in combos:
        metrics = simulate_rsi_mode(
            valid_history,
            rsi_oversold=combo['rsi_oversold'],
            rsi_overbought=combo['rsi_overbought'],
            stop_loss_pct=combo['stop_loss_pct'],
            take_profit_pct=combo['take_profit_pct'],
            trade_amount_usd=trade_amount_usd,
            initial_balance=initial_balance,
        )

        result = {
            'rsi_oversold': combo['rsi_oversold'],
            'rsi_overbought': combo['rsi_overbought'],
            'stop_loss_pct': combo['stop_loss_pct'],
            'take_profit_pct': combo['take_profit_pct'],
            **metrics,
        }
        results.append(result)

    # Sort by total_pnl descending
    results.sort(key=lambda x: x['total_pnl'], reverse=True)

    for i, r in enumerate(results[:50], 1):
        r['rank'] = i

    # Build market_history summary for chart (sample every N points for large datasets)
    chart_data = []
    step = max(1, len(valid_history) // 200) if len(valid_history) > 200 else 1
    for p in valid_history[::step]:
        chart_data.append({
            'timestamp': p.get('timestamp'),
            'price': p.get('price'),
            'rsi': p.get('rsi'),
        })

    return {
        "status": "ok",
        "data_points": len(valid_history),
        "total_combinations": len(combos),
        "results": results[:50],
        "market_history": chart_data,
    }
