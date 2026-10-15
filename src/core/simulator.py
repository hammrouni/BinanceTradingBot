"""
Parameter simulation engine for backtesting different trading configs.
Replicates exact logic from bot_engine.py to test parameter combinations.
"""
import math
from typing import Optional

from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.core.strategies.filters import (
    is_below_ma,
    is_bear_trend,
    is_ema_trend_valid,
    is_price_bouncing,
)
from src.models.market import KlineData


def _buy_filters_pass(history, price, bounce_ticks, bear_candles, bear_pct, ma_period, ema_fast, ema_slow) -> bool:
    """The live buy filters (strategies/filters.py); a None parameter disables that filter."""
    return (
        is_price_bouncing(history, bounce_ticks)
        and not is_bear_trend(history, bear_candles, bear_pct)
        and is_below_ma(history, price, ma_period)
        and is_ema_trend_valid(history, ema_fast, ema_slow)
    )


def compute_ultra_series(market_history, period: int, signal_period: int) -> list[tuple]:
    """RSI Ultra (raw, signal) for every point of `market_history` with the given periods.

    Uses the same calculator as the live bot. Points need 'high', 'low' and 'price' (close);
    missing high/low fall back to the price.
    """
    calc = RsiUltraCalculator(rsi_period=int(period), signal_period=int(signal_period))
    out = []
    for p in market_history:
        price = p['price']
        kline = KlineData(
            open_time=0, open=p.get('open') or price, high=p.get('high') or price,
            low=p.get('low') or price, close=price, volume=0.0, close_time=0, is_closed=True,
        )
        out.append(calc.add_candle(kline))
    return out


def _with_ultra(market_history, period, signal_period) -> list[dict]:
    series = compute_ultra_series(market_history, period, signal_period)
    return [{**p, 'rsi_ultra_raw': raw, 'rsi_ultra_signal': sig} for p, (raw, sig) in zip(market_history, series)]



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


def _range_values(r):
    """Convert a [min, max, step] range to a list of values, or [None] if r is None."""
    if r is None:
        return [None]
    min_v, max_v, step = r
    return [round(v, 2) for v in _frange(min_v, max_v, step)]


def generate_param_combinations(
    rsi_oversold_range,
    rsi_overbought_range,
    stop_loss_range,
    take_profit_range,
    trailing_stop_range=None,
):
    """Generate all valid RSI parameter combinations from ranges.
    Each range is [min, max, step] or None to disable.
    Raises ValueError on invalid range inputs.
    """
    for name, r in [
        ("rsi_oversold_range", rsi_oversold_range),
        ("rsi_overbought_range", rsi_overbought_range),
        ("stop_loss_range", stop_loss_range),
        ("take_profit_range", take_profit_range),
        ("trailing_stop_range", trailing_stop_range),
    ]:
        _validate_range(r, name)

    oversold_vals = _range_values(rsi_oversold_range)
    overbought_vals = _range_values(rsi_overbought_range)
    sl_vals = _range_values(stop_loss_range)
    tp_vals = _range_values(take_profit_range)
    ts_vals = _range_values(trailing_stop_range)

    combos = []
    for os_val in oversold_vals:
        for ob_val in overbought_vals:
            # M5: skip nonsensical combos where oversold >= overbought
            if os_val is not None and ob_val is not None and os_val >= ob_val:
                continue
            for sl in sl_vals:
                for tp in tp_vals:
                    for ts in ts_vals:
                        combos.append({
                            'rsi_oversold': os_val,
                            'rsi_overbought': ob_val,
                            'stop_loss_pct': sl,
                            'take_profit_pct': tp,
                            'trailing_stop_pct': ts,
                        })
    return combos


def generate_bc_param_combinations(
    bc_buy_offset_range,
    bc_sell_offset_range,
    stop_loss_range,
    take_profit_range,
    trailing_stop_range=None,
):
    """Generate all valid BC parameter combinations from offset ranges.
    bc_buy_offset_range: % below reference price to place buy target
    bc_sell_offset_range: % above reference price to place sell target
    """
    for name, r in [
        ("bc_buy_offset_range", bc_buy_offset_range),
        ("bc_sell_offset_range", bc_sell_offset_range),
        ("stop_loss_range", stop_loss_range),
        ("take_profit_range", take_profit_range),
        ("trailing_stop_range", trailing_stop_range),
    ]:
        _validate_range(r, name)

    if bc_buy_offset_range is None:
        raise ValueError("bc_buy_offset_range is required for BC simulation")
    if bc_sell_offset_range is None:
        raise ValueError("bc_sell_offset_range is required for BC simulation")

    buy_vals = _range_values(bc_buy_offset_range)
    sell_vals = _range_values(bc_sell_offset_range)
    sl_vals = _range_values(stop_loss_range)
    tp_vals = _range_values(take_profit_range)
    ts_vals = _range_values(trailing_stop_range)

    combos = []
    for buy_off in buy_vals:
        for sell_off in sell_vals:
            for sl in sl_vals:
                for tp in tp_vals:
                    for ts in ts_vals:
                        combos.append({
                            'bc_buy_offset_pct': buy_off,
                            'bc_sell_offset_pct': sell_off,
                            'stop_loss_pct': sl,
                            'take_profit_pct': tp,
                            'trailing_stop_pct': ts,
                        })
    return combos


def generate_ultra_param_combinations(
    rsi_ultra_period_range,
    rsi_ultra_signal_period_range,
    rsi_ultra_zone_mid_range,
    stop_loss_range,
    take_profit_range,
    trailing_stop_range=None,
):
    """Generate all valid RSI Ultra parameter combinations from ranges."""
    for name, r in [
        ("rsi_ultra_period_range", rsi_ultra_period_range),
        ("rsi_ultra_signal_period_range", rsi_ultra_signal_period_range),
        ("rsi_ultra_zone_mid_range", rsi_ultra_zone_mid_range),
        ("stop_loss_range", stop_loss_range),
        ("take_profit_range", take_profit_range),
        ("trailing_stop_range", trailing_stop_range),
    ]:
        _validate_range(r, name)

    period_vals = _range_values(rsi_ultra_period_range)
    signal_vals = _range_values(rsi_ultra_signal_period_range)
    mid_vals    = _range_values(rsi_ultra_zone_mid_range)
    sl_vals     = _range_values(stop_loss_range)
    tp_vals     = _range_values(take_profit_range)
    ts_vals     = _range_values(trailing_stop_range)

    combos = []
    for p in period_vals:
        for sp in signal_vals:
            for mid in mid_vals:
                for sl in sl_vals:
                    for tp in tp_vals:
                        for ts in ts_vals:
                            combos.append({
                                'rsi_ultra_period': p,
                                'rsi_ultra_signal_period': sp,
                                'rsi_ultra_zone_mid': mid,
                                'stop_loss_pct': sl,
                                'take_profit_pct': tp,
                                'trailing_stop_pct': ts,
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
    fee_pct: float = 0.1,
    trailing_stop_pct: Optional[float] = None,
    price_bounce_ticks: Optional[int] = None,
    bear_trend_candles: Optional[int] = None,
    bear_trend_pct: Optional[float] = None,
    ma_filter_period: Optional[int] = None,
    ema_fast_period: Optional[int] = None,
    ema_slow_period: Optional[int] = None,
    collect_events: bool = False,
):
    """
    Simulate RSI trading mode with edge-triggered buy/sell signals.
    Matches exact logic from bot_engine.py process_market_update().
    When collect_events=True, the returned dict includes an 'events' list.
    """
    balance = initial_balance
    position = None  # {entry_price, qty, balance_before_buy, highest_price}
    last_rsi_was_oversold = False
    last_rsi_was_overbought = False
    trades = []
    events = []
    max_drawdown_pct = 0.0  # H4: track per-trade worst loss as % of balance
    price_history = []  # for RSI filter helpers

    for point in market_history:
        price = point.get('price')
        rsi = point.get('rsi')
        ts = point.get('timestamp')

        # M2: reject missing, zero, negative, or NaN prices
        if price is None or price <= 0 or math.isnan(price):
            continue

        price_history.append(price)

        # ─── TRAILING STOP CHECK (before regular SL to prioritise tighter exit) ──
        if position is not None and trailing_stop_pct is not None:
            if price > position.get('highest_price', position['entry_price']):
                position['highest_price'] = price
            ts_price = position['highest_price'] * (1 - trailing_stop_pct / 100)
            if price <= ts_price:
                pnl = (price - position['entry_price']) * position['qty']
                # Fee on Sell
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                if pnl < 0:
                    dd = abs(pnl) / position['balance_before_buy'] * 100
                    max_drawdown_pct = max(max_drawdown_pct, dd)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'trailing_stop', 'pnl': round(pnl, 2)})
                position = None
                continue

        # ─── STOP-LOSS CHECK (always active) ────────────────────────────────
        if position is not None:
            # H3: use `is not None` so stop_loss_pct=0 does not silently disable SL
            sl_price = position['entry_price'] * (1 - stop_loss_pct / 100) if stop_loss_pct is not None else None
            if sl_price is not None and price < sl_price:
                pnl = (price - position['entry_price']) * position['qty']
                # Fee on Sell
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                # H4: drawdown = loss as % of balance before the trade was entered
                if pnl < 0:
                    dd = abs(pnl) / position['balance_before_buy'] * 100
                    max_drawdown_pct = max(max_drawdown_pct, dd)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'stop_loss', 'pnl': round(pnl, 2)})
                position = None
                continue

        # ─── TAKE-PROFIT CHECK (always active) ────────────────────────────────
        if position is not None:
            tp_price = position['entry_price'] * (1 + take_profit_pct / 100) if take_profit_pct and take_profit_pct > 0 else None
            if tp_price is not None and price >= tp_price:
                pnl = (price - position['entry_price']) * position['qty']
                # Fee on Sell
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'take_profit', 'pnl': round(pnl, 2)})
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
            # Fee on Sell
            balance += (price * position['qty']) * (1 - fee_pct / 100)
            trades.append(pnl)
            if pnl < 0:
                dd = abs(pnl) / position['balance_before_buy'] * 100
                max_drawdown_pct = max(max_drawdown_pct, dd)
            if collect_events:
                events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'rsi_overbought', 'pnl': round(pnl, 2)})
            position = None

        # ─── RSI OVERSOLD BUY (edge-triggered) ─────────────────────────────────
        is_oversold = rsi < rsi_oversold if rsi_oversold is not None else False
        if (
            position is None
            and rsi_oversold is not None
            and is_oversold
            and not last_rsi_was_oversold
            and balance >= trade_amount_usd
            and _buy_filters_pass(price_history, price, price_bounce_ticks, bear_trend_candles,
                                  bear_trend_pct, ma_filter_period, ema_fast_period, ema_slow_period)
        ):
            balance_before = balance  # capture BEFORE deducting cost (H4)
            # Fee on Buy: receive less quantity
            qty = (trade_amount_usd * (1 - fee_pct / 100)) / price
            balance -= trade_amount_usd
            position = {
                'entry_price': price,
                'qty': qty,
                'balance_before_buy': balance_before,
                'highest_price': price,
            }
            if collect_events:
                events.append({'timestamp': ts, 'price': price, 'action': 'buy', 'reason': 'rsi_oversold', 'pnl': None})

        last_rsi_was_oversold = is_oversold
        last_rsi_was_overbought = is_overbought

    # Close any open position at final price
    if market_history:
        final_price = market_history[-1].get('price')
        final_ts = market_history[-1].get('timestamp')
        if position and final_price and final_price > 0 and not math.isnan(final_price):
            pnl = (final_price - position['entry_price']) * position['qty']
            # Fee on Sell
            balance += (final_price * position['qty']) * (1 - fee_pct / 100)
            trades.append(pnl)
            if pnl < 0:
                dd = abs(pnl) / position['balance_before_buy'] * 100
                max_drawdown_pct = max(max_drawdown_pct, dd)
            if collect_events:
                events.append({'timestamp': final_ts, 'price': final_price, 'action': 'sell', 'reason': 'end_of_data', 'pnl': round(pnl, 2)})

    metrics = _calc_metrics(trades, balance, initial_balance, max_drawdown_pct)
    if collect_events:
        metrics['events'] = events
    return metrics


def simulate_ultra_mode(
    market_history,
    rsi_ultra_zone_mid: float,
    stop_loss_pct: Optional[float],
    take_profit_pct: Optional[float],
    trade_amount_usd: float,
    initial_balance: float = 1000.0,
    fee_pct: float = 0.1,
    trailing_stop_pct: Optional[float] = None,
    price_bounce_ticks: Optional[int] = None,
    bear_trend_candles: Optional[int] = None,
    bear_trend_pct: Optional[float] = None,
    ma_filter_period: Optional[int] = None,
    ema_fast_period: Optional[int] = None,
    ema_slow_period: Optional[int] = None,
    collect_events: bool = False,
):
    """
    Simulate RSI Ultra crossover mode.
    Requires 'rsi_ultra_raw' and 'rsi_ultra_signal' in market_history.
    """
    balance = initial_balance
    position = None
    trades = []
    events = []
    max_drawdown_pct = 0.0

    # For crossover detection
    prev_raw = None
    prev_sig = None
    price_history = []  # for the shared buy filters

    for point in market_history:
        price = point.get('price')
        raw   = point.get('rsi_ultra_raw')
        sig   = point.get('rsi_ultra_signal')
        ts    = point.get('timestamp')

        if price is None or price <= 0 or math.isnan(price):
            continue

        price_history.append(price)

        # ─── TRAILING / SL / TP (Standard Exit Logic) ────────────────────────
        if position is not None:
            # Trailing Stop
            if trailing_stop_pct is not None:
                if price > position.get('highest_price', position['entry_price']):
                    position['highest_price'] = price
                ts_price = position['highest_price'] * (1 - trailing_stop_pct / 100)
                if price <= ts_price:
                    pnl = (price - position['entry_price']) * position['qty']
                    balance += (price * position['qty']) * (1 - fee_pct / 100)
                    trades.append(pnl)
                    if pnl < 0:
                        dd = abs(pnl) / position['balance_before_buy'] * 100
                        max_drawdown_pct = max(max_drawdown_pct, dd)
                    if collect_events:
                        events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'trailing_stop', 'pnl': round(pnl, 2)})
                    position = None
                    prev_raw, prev_sig = raw, sig
                    continue

            # Stop Loss
            sl_price = position['entry_price'] * (1 - stop_loss_pct / 100) if stop_loss_pct is not None else None
            if sl_price is not None and price < sl_price:
                pnl = (price - position['entry_price']) * position['qty']
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                if pnl < 0:
                    dd = abs(pnl) / position['balance_before_buy'] * 100
                    max_drawdown_pct = max(max_drawdown_pct, dd)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'stop_loss', 'pnl': round(pnl, 2)})
                position = None
                prev_raw, prev_sig = raw, sig
                continue

            # Take Profit
            tp_price = position['entry_price'] * (1 + take_profit_pct / 100) if take_profit_pct and take_profit_pct > 0 else None
            if tp_price is not None and price >= tp_price:
                pnl = (price - position['entry_price']) * position['qty']
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'take_profit', 'pnl': round(pnl, 2)})
                position = None
                prev_raw, prev_sig = raw, sig
                continue

        # ─── ULTRA CROSSOVER ────────────────────────────────────────────────
        if raw is not None and sig is not None and prev_raw is not None and prev_sig is not None:
            # CROSS UP: Buy in Buy Zone
            if prev_raw < prev_sig and raw > sig and raw < rsi_ultra_zone_mid and position is None:
                if balance >= trade_amount_usd and _buy_filters_pass(
                        price_history, price, price_bounce_ticks, bear_trend_candles, bear_trend_pct,
                        ma_filter_period, ema_fast_period, ema_slow_period):
                    balance_before = balance
                    qty = (trade_amount_usd * (1 - fee_pct / 100)) / price
                    balance -= trade_amount_usd
                    position = {
                        'entry_price': price,
                        'qty': qty,
                        'balance_before_buy': balance_before,
                        'highest_price': price,
                    }
                    if collect_events:
                        events.append({'timestamp': ts, 'price': price, 'action': 'buy', 'reason': 'rsi_ultra_crossup', 'pnl': None})

            # CROSS DOWN: Sell in Sell Zone
            elif prev_raw > prev_sig and raw < sig and raw > rsi_ultra_zone_mid and position is not None:
                if not (take_profit_pct and take_profit_pct > 0): # only sell by cross if TP not hit yet
                    pnl = (price - position['entry_price']) * position['qty']
                    balance += (price * position['qty']) * (1 - fee_pct / 100)
                    trades.append(pnl)
                    if pnl < 0:
                        dd = abs(pnl) / position['balance_before_buy'] * 100
                        max_drawdown_pct = max(max_drawdown_pct, dd)
                    if collect_events:
                        events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'rsi_ultra_crossdown', 'pnl': round(pnl, 2)})
                    position = None

        prev_raw, prev_sig = raw, sig

    # Close any open position at final price
    if market_history:
        final_price = market_history[-1].get('price')
        final_ts = market_history[-1].get('timestamp')
        if position and final_price and final_price > 0:
            pnl = (final_price - position['entry_price']) * position['qty']
            balance += (final_price * position['qty']) * (1 - fee_pct / 100)
            trades.append(pnl)
            if collect_events:
                events.append({'timestamp': final_ts, 'price': final_price, 'action': 'sell', 'reason': 'end_of_data', 'pnl': round(pnl, 2)})

    metrics = _calc_metrics(trades, balance, initial_balance, max_drawdown_pct)
    if collect_events:
        metrics['events'] = events
    return metrics


def simulate_bc_mode(
    market_history,
    bc_buy_price: float,
    bc_sell_price: float,
    stop_loss_pct: Optional[float],
    take_profit_pct: Optional[float],
    trade_amount_usd: float,
    initial_balance: float = 1000.0,
    fee_pct: float = 0.1,
    trailing_stop_pct: Optional[float] = None,
    collect_events: bool = False,
):
    """
    Simulate BC (price-target) trading mode with edge-triggered buy/sell signals.
    Buys when price <= bc_buy_price, sells when price >= bc_sell_price.
    Also applies stop-loss, take-profit, and optional trailing stop.
    When collect_events=True, the returned dict includes an 'events' list.
    """
    balance = initial_balance
    position = None  # {entry_price, qty, balance_before_buy, highest_price}
    last_bc_buy_triggered = False
    last_bc_sell_triggered = False
    trades = []
    events = []
    max_drawdown_pct = 0.0

    for point in market_history:
        price = point.get('price')
        ts = point.get('timestamp')

        if price is None or price <= 0 or math.isnan(price):
            continue

        # ─── TRAILING STOP CHECK ─────────────────────────────────────────────
        if position is not None and trailing_stop_pct is not None:
            if price > position.get('highest_price', position['entry_price']):
                position['highest_price'] = price
            ts_price = position['highest_price'] * (1 - trailing_stop_pct / 100)
            if price <= ts_price:
                pnl = (price - position['entry_price']) * position['qty']
                # Fee on Sell
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                if pnl < 0:
                    dd = abs(pnl) / position['balance_before_buy'] * 100
                    max_drawdown_pct = max(max_drawdown_pct, dd)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'trailing_stop', 'pnl': round(pnl, 2)})
                position = None
                last_bc_buy_triggered = False
                last_bc_sell_triggered = False
                continue

        # ─── STOP-LOSS CHECK ────────────────────────────────────────────────
        if position is not None:
            sl_price = position['entry_price'] * (1 - stop_loss_pct / 100) if stop_loss_pct is not None else None
            if sl_price is not None and price < sl_price:
                pnl = (price - position['entry_price']) * position['qty']
                # Fee on Sell
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                if pnl < 0:
                    dd = abs(pnl) / position['balance_before_buy'] * 100
                    max_drawdown_pct = max(max_drawdown_pct, dd)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'stop_loss', 'pnl': round(pnl, 2)})
                position = None
                last_bc_buy_triggered = False
                continue

        # ─── TAKE-PROFIT CHECK ──────────────────────────────────────────────
        if position is not None:
            tp_price = position['entry_price'] * (1 + take_profit_pct / 100) if take_profit_pct and take_profit_pct > 0 else None
            if tp_price is not None and price >= tp_price:
                pnl = (price - position['entry_price']) * position['qty']
                # Fee on Sell
                balance += (price * position['qty']) * (1 - fee_pct / 100)
                trades.append(pnl)
                if collect_events:
                    events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'take_profit', 'pnl': round(pnl, 2)})
                position = None
                continue

        # ─── BC SELL (price-target, only if TP not configured) ───────────────
        bc_sell_triggered = price >= bc_sell_price
        if (
            position is not None
            and (take_profit_pct is None or take_profit_pct <= 0)
            and bc_sell_triggered
            and not last_bc_sell_triggered
        ):
            pnl = (price - position['entry_price']) * position['qty']
            # Fee on Sell
            balance += (price * position['qty']) * (1 - fee_pct / 100)
            trades.append(pnl)
            if pnl < 0:
                dd = abs(pnl) / position['balance_before_buy'] * 100
                max_drawdown_pct = max(max_drawdown_pct, dd)
            if collect_events:
                events.append({'timestamp': ts, 'price': price, 'action': 'sell', 'reason': 'bc_sell_target', 'pnl': round(pnl, 2)})
            position = None

        # ─── BC BUY (edge-triggered) ─────────────────────────────────────────
        bc_buy_triggered = price <= bc_buy_price
        if (
            position is None
            and bc_buy_triggered
            and not last_bc_buy_triggered
            and balance >= trade_amount_usd
        ):
            balance_before = balance
            # Fee on Buy
            qty = (trade_amount_usd * (1 - fee_pct / 100)) / price
            balance -= trade_amount_usd
            position = {
                'entry_price': price,
                'qty': qty,
                'balance_before_buy': balance_before,
                'highest_price': price,
            }
            if collect_events:
                events.append({'timestamp': ts, 'price': price, 'action': 'buy', 'reason': 'bc_buy_target', 'pnl': None})

        last_bc_buy_triggered = bc_buy_triggered
        last_bc_sell_triggered = bc_sell_triggered

    # Close any open position at final price
    if market_history:
        final_price = market_history[-1].get('price')
        final_ts = market_history[-1].get('timestamp')
        if position and final_price and final_price > 0 and not math.isnan(final_price):
            pnl = (final_price - position['entry_price']) * position['qty']
            # Fee on Sell (fixed from previous partial edit)
            balance += (final_price * position['qty']) * (1 - fee_pct / 100)
            trades.append(pnl)
            if pnl < 0:
                dd = abs(pnl) / position['balance_before_buy'] * 100
                max_drawdown_pct = max(max_drawdown_pct, dd)
            if collect_events:
                events.append({'timestamp': final_ts, 'price': final_price, 'action': 'sell', 'reason': 'end_of_data', 'pnl': round(pnl, 2)})

    metrics = _calc_metrics(trades, balance, initial_balance, max_drawdown_pct)
    if collect_events:
        metrics['events'] = events
    return metrics


def simulate_single(
    market_history,
    mode: str,
    initial_balance: float,
    trade_amount_usd: float,
    fee_pct: float = 0.1,
    stop_loss_pct: Optional[float] = None,
    take_profit_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
    # RSI
    rsi_oversold: Optional[int] = None,
    rsi_overbought: Optional[int] = None,
    price_bounce_ticks: Optional[int] = None,
    bear_trend_candles: Optional[int] = None,
    bear_trend_pct: Optional[float] = None,
    ma_filter_period: Optional[int] = None,
    ema_fast_period: Optional[int] = None,
    ema_slow_period: Optional[int] = None,
    # BC
    bc_buy_price: Optional[float] = None,
    bc_sell_price: Optional[float] = None,
    # RSI Ultra (periods None = use the Ultra values already in market_history)
    rsi_ultra_zone_mid: Optional[float] = 50.0,
    rsi_ultra_period: Optional[int] = None,
    rsi_ultra_signal_period: Optional[int] = None,
):
    """Run one simulation pass and return metrics + full events list."""
    valid_history = [
        p for p in market_history
        if p.get('price') and p['price'] > 0 and not math.isnan(p['price'])
    ]
    if not valid_history:
        return {"status": "error", "message": "No valid market data"}

    if mode == "rsi":
        result = simulate_rsi_mode(
            valid_history,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trade_amount_usd=trade_amount_usd,
            initial_balance=initial_balance,
            fee_pct=fee_pct,
            trailing_stop_pct=trailing_stop_pct,
            price_bounce_ticks=price_bounce_ticks,
            bear_trend_candles=bear_trend_candles,
            bear_trend_pct=bear_trend_pct,
            ma_filter_period=ma_filter_period,
            ema_fast_period=ema_fast_period,
            ema_slow_period=ema_slow_period,
            collect_events=True,
        )
    elif mode == "rsi_ultra":
        ultra_history = valid_history
        if rsi_ultra_period is not None and rsi_ultra_signal_period is not None:
            ultra_history = _with_ultra(valid_history, rsi_ultra_period, rsi_ultra_signal_period)
        result = simulate_ultra_mode(
            ultra_history,
            rsi_ultra_zone_mid=rsi_ultra_zone_mid,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trade_amount_usd=trade_amount_usd,
            initial_balance=initial_balance,
            fee_pct=fee_pct,
            trailing_stop_pct=trailing_stop_pct,
            price_bounce_ticks=price_bounce_ticks,
            bear_trend_candles=bear_trend_candles,
            bear_trend_pct=bear_trend_pct,
            ma_filter_period=ma_filter_period,
            ema_fast_period=ema_fast_period,
            ema_slow_period=ema_slow_period,
            collect_events=True,
        )
    elif mode == "bc":
        if bc_buy_price is None or bc_sell_price is None:
            return {"status": "error", "message": "bc_buy_price and bc_sell_price are required for BC mode"}
        result = simulate_bc_mode(
            valid_history,
            bc_buy_price=bc_buy_price,
            bc_sell_price=bc_sell_price,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            trade_amount_usd=trade_amount_usd,
            initial_balance=initial_balance,
            fee_pct=fee_pct,
            trailing_stop_pct=trailing_stop_pct,
            collect_events=True,
        )
    else:
        return {"status": "error", "message": f"Unknown mode: {mode}"}

    result["status"] = "ok"
    result["mode"] = mode
    result["fee_pct"] = fee_pct
    return result


def _calc_metrics(trades, balance, initial_balance, max_drawdown_pct):
    """Calculate common performance metrics from trade list."""
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
    stop_loss_range: list,
    take_profit_range: Optional[list],
    trade_amount_usd: float = 100.0,
    fee_pct: float = 0.1,
    # RSI-specific
    rsi_oversold_range: Optional[list] = None,
    rsi_overbought_range: Optional[list] = None,
    trailing_stop_range: Optional[list] = None,
    price_bounce_ticks: Optional[int] = None,
    bear_trend_candles: Optional[int] = None,
    bear_trend_pct: Optional[float] = None,
    ma_filter_period: Optional[int] = None,
    ema_fast_period: Optional[int] = None,
    ema_slow_period: Optional[int] = None,
    # BC-specific
    bc_buy_offset_range: Optional[list] = None,
    bc_sell_offset_range: Optional[list] = None,
    # RSI Ultra-specific
    rsi_ultra_period_range: Optional[list] = None,
    rsi_ultra_signal_period_range: Optional[list] = None,
    rsi_ultra_zone_mid_range: Optional[list] = None,
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

    if mode == "rsi":
        combos = generate_param_combinations(
            rsi_oversold_range,
            rsi_overbought_range,
            stop_loss_range,
            take_profit_range,
            trailing_stop_range,
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
                fee_pct=fee_pct,
                trailing_stop_pct=combo.get('trailing_stop_pct'),
                price_bounce_ticks=price_bounce_ticks,
                bear_trend_candles=bear_trend_candles,
                bear_trend_pct=bear_trend_pct,
                ma_filter_period=ma_filter_period,
                ema_fast_period=ema_fast_period,
                ema_slow_period=ema_slow_period,
            )

            result = {
                'strategy': 'RSI',
                'rsi_oversold': combo['rsi_oversold'],
                'rsi_overbought': combo['rsi_overbought'],
                'stop_loss_pct': combo['stop_loss_pct'],
                'take_profit_pct': combo['take_profit_pct'],
                'trailing_stop_pct': combo.get('trailing_stop_pct'),
                **metrics,
            }
            results.append(result)

    elif mode == "rsi_ultra":
        combos = generate_ultra_param_combinations(
            rsi_ultra_period_range,
            rsi_ultra_signal_period_range,
            rsi_ultra_zone_mid_range,
            stop_loss_range,
            take_profit_range,
            trailing_stop_range,
        )

        if not combos:
            return {"status": "error", "message": "No valid RSI Ultra parameter combinations generated."}

        results = []
        ultra_cache: dict[tuple, list[dict]] = {}  # (period, signal_period) -> history with Ultra values
        for combo in combos:
            key = (combo['rsi_ultra_period'], combo['rsi_ultra_signal_period'])
            if key not in ultra_cache:
                ultra_cache[key] = _with_ultra(valid_history, *key)
            metrics = simulate_ultra_mode(
                ultra_cache[key],
                rsi_ultra_zone_mid=combo['rsi_ultra_zone_mid'],
                stop_loss_pct=combo['stop_loss_pct'],
                take_profit_pct=combo['take_profit_pct'],
                trade_amount_usd=trade_amount_usd,
                initial_balance=initial_balance,
                fee_pct=fee_pct,
                trailing_stop_pct=combo.get('trailing_stop_pct'),
                price_bounce_ticks=price_bounce_ticks,
                bear_trend_candles=bear_trend_candles,
                bear_trend_pct=bear_trend_pct,
                ma_filter_period=ma_filter_period,
                ema_fast_period=ema_fast_period,
                ema_slow_period=ema_slow_period,
            )

            result = {
                'strategy': 'RSI_ULTRA',
                'rsi_ultra_period': combo['rsi_ultra_period'],
                'rsi_ultra_signal_period': combo['rsi_ultra_signal_period'],
                'rsi_ultra_zone_mid': combo['rsi_ultra_zone_mid'],
                'stop_loss_pct': combo['stop_loss_pct'],
                'take_profit_pct': combo['take_profit_pct'],
                'trailing_stop_pct': combo.get('trailing_stop_pct'),
                **metrics,
            }
            results.append(result)

    elif mode == "bc":
        # Compute reference price: median of all valid prices
        prices = sorted(p['price'] for p in valid_history)
        ref_price = prices[len(prices) // 2]

        combos = generate_bc_param_combinations(
            bc_buy_offset_range,
            bc_sell_offset_range,
            stop_loss_range,
            take_profit_range,
            trailing_stop_range,
        )

        if not combos:
            return {"status": "error", "message": "No valid BC parameter combinations generated."}

        results = []
        for combo in combos:
            buy_off = combo['bc_buy_offset_pct']
            sell_off = combo['bc_sell_offset_pct']
            bc_buy_price = round(ref_price * (1 - buy_off / 100), 2)
            bc_sell_price = round(ref_price * (1 + sell_off / 100), 2)

            metrics = simulate_bc_mode(
                valid_history,
                bc_buy_price=bc_buy_price,
                bc_sell_price=bc_sell_price,
                stop_loss_pct=combo['stop_loss_pct'],
                take_profit_pct=combo['take_profit_pct'],
                trade_amount_usd=trade_amount_usd,
                initial_balance=initial_balance,
                fee_pct=fee_pct,
                trailing_stop_pct=combo.get('trailing_stop_pct'),
            )

            result = {
                'strategy': 'BC',
                'bc_buy_offset_pct': buy_off,
                'bc_sell_offset_pct': sell_off,
                'bc_buy_price': bc_buy_price,
                'bc_sell_price': bc_sell_price,
                'ref_price': round(ref_price, 2),
                'stop_loss_pct': combo['stop_loss_pct'],
                'take_profit_pct': combo['take_profit_pct'],
                'trailing_stop_pct': combo.get('trailing_stop_pct'),
                **metrics,
            }
            results.append(result)

    else:
        return {"status": "error", "message": f"Unknown simulation mode: {mode}"}

    # Sort by total_pnl descending
    results.sort(key=lambda x: x['total_pnl'], reverse=True)

    for i, r in enumerate(results[:50], 1):
        r['rank'] = i

    # Build market_history summary for chart (sample every N points for large datasets)
    chart_data = []
    step = max(1, len(valid_history) // 1000) if len(valid_history) > 1000 else 1
    for p in valid_history[::step]:
        chart_data.append({
            'timestamp': p.get('timestamp'),
            'price': p.get('price'),
            'rsi': p.get('rsi'),
            'rsi_ultra_raw': p.get('rsi_ultra_raw'),
            'rsi_ultra_signal': p.get('rsi_ultra_signal'),
        })

    return {
        "status": "ok",
        "mode": mode,
        "data_points": len(valid_history),
        "total_combinations": len(results),
        "results": results[:50],
        "market_history": chart_data,
        "fee_pct": fee_pct,
    }
