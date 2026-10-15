"""
Parameter simulation: grid search and single runs over candle history.

The trading logic is NOT implemented here. Every run goes through the replay harness (core/replay.py),
which drives the same strategy classes, shared filters and risk helpers as the live BotEngine, so the
simulator cannot drift from live trading. This module only expands parameter grids, picks the BC
reference, and shapes the API responses.
"""
from typing import Optional

from src.core.replay import causal_reference, config_for_sim, replay, valid_rows
from src.core.sim_metrics import compute_metrics
from src.services.history_loader import compute_ultra_series


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


def _run(rows, mode, config_params, initial_balance, fee_pct, intrabar, bc_offsets=None, bc_reference=None):
    """One replay -> (metrics dict, raw ReplayResult)."""
    config = config_for_sim(mode, **config_params)
    res = replay(rows, config, initial_balance=initial_balance, fee_pct=fee_pct, intrabar=intrabar,
                 bc_offsets=bc_offsets, bc_reference=bc_reference)
    return compute_metrics(res.trades, initial_balance, res.final_balance, res.max_drawdown_pct), res


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
    # BC: fixed prices (as live), or offsets from the causal reference (as the grid search)
    bc_buy_price: Optional[float] = None,
    bc_sell_price: Optional[float] = None,
    bc_buy_offset_pct: Optional[float] = None,
    bc_sell_offset_pct: Optional[float] = None,
    # RSI Ultra (periods None = use the Ultra values already in market_history)
    rsi_ultra_zone_mid: Optional[float] = 50.0,
    rsi_ultra_period: Optional[int] = None,
    rsi_ultra_signal_period: Optional[int] = None,
    intrabar: bool = True,
):
    """Run one simulation pass and return metrics + the full events list."""
    valid_history = valid_rows(market_history)
    if not valid_history:
        return {"status": "error", "message": "No valid market data"}
    if mode not in ("rsi", "rsi_ultra", "bc"):
        return {"status": "error", "message": f"Unknown mode: {mode}"}

    bc_offsets = None
    if mode == "bc":
        if bc_buy_offset_pct is not None and bc_sell_offset_pct is not None:
            bc_offsets = (bc_buy_offset_pct, bc_sell_offset_pct)
        elif bc_buy_price is None or bc_sell_price is None:
            return {"status": "error", "message": "bc_buy_price and bc_sell_price are required for BC mode"}

    if mode == "rsi_ultra" and rsi_ultra_period is not None and rsi_ultra_signal_period is not None:
        valid_history = _with_ultra(valid_history, rsi_ultra_period, rsi_ultra_signal_period)

    params = dict(
        trade_amount_usd=trade_amount_usd, stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct, rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought,
        price_bounce_ticks=price_bounce_ticks, bear_trend_candles=bear_trend_candles,
        bear_trend_pct=bear_trend_pct, ma_filter_period=ma_filter_period, ema_fast_period=ema_fast_period,
        ema_slow_period=ema_slow_period, bc_buy_price=bc_buy_price, bc_sell_price=bc_sell_price,
        rsi_ultra_zone_mid=rsi_ultra_zone_mid,
    )
    result, res = _run(valid_history, mode, params, initial_balance, fee_pct, intrabar, bc_offsets=bc_offsets)
    result["events"] = res.events
    result["status"] = "ok"
    result["mode"] = mode
    result["fee_pct"] = fee_pct
    return result


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
    intrabar: bool = True,
):
    """
    Run grid search simulation over all parameter combinations.
    Returns top 50 results ranked by total_pnl descending.
    Raises ValueError on invalid inputs.
    """
    if not market_history:
        return {"status": "error", "message": "No market history available"}

    valid_history = valid_rows(market_history)
    if not valid_history:
        return {"status": "error", "message": "No valid market data"}

    filters = dict(
        price_bounce_ticks=price_bounce_ticks, bear_trend_candles=bear_trend_candles,
        bear_trend_pct=bear_trend_pct, ma_filter_period=ma_filter_period,
        ema_fast_period=ema_fast_period, ema_slow_period=ema_slow_period,
    )

    def run_combo(history, combo, extra, **kw):
        params = dict(trade_amount_usd=trade_amount_usd, stop_loss_pct=combo['stop_loss_pct'],
                      take_profit_pct=combo['take_profit_pct'], trailing_stop_pct=combo.get('trailing_stop_pct'),
                      **filters, **extra)
        metrics, _ = _run(history, mode, params, initial_balance, fee_pct, intrabar, **kw)
        return metrics

    def exits(combo):
        return {
            'stop_loss_pct': combo['stop_loss_pct'],
            'take_profit_pct': combo['take_profit_pct'],
            'trailing_stop_pct': combo.get('trailing_stop_pct'),
        }

    if mode == "rsi":
        combos = generate_param_combinations(
            rsi_oversold_range, rsi_overbought_range, stop_loss_range, take_profit_range, trailing_stop_range)
        if not combos:
            return {"status": "error", "message": "No valid parameter combinations generated. Check that oversold < overbought and ranges are valid."}

        results = []
        for combo in combos:
            metrics = run_combo(valid_history, combo, dict(
                rsi_oversold=combo['rsi_oversold'], rsi_overbought=combo['rsi_overbought']))
            results.append({
                'strategy': 'RSI',
                'rsi_oversold': combo['rsi_oversold'],
                'rsi_overbought': combo['rsi_overbought'],
                **exits(combo),
                **metrics,
            })

    elif mode == "rsi_ultra":
        combos = generate_ultra_param_combinations(
            rsi_ultra_period_range, rsi_ultra_signal_period_range, rsi_ultra_zone_mid_range,
            stop_loss_range, take_profit_range, trailing_stop_range)
        if not combos:
            return {"status": "error", "message": "No valid RSI Ultra parameter combinations generated."}

        results = []
        ultra_cache: dict[tuple, list[dict]] = {}  # (period, signal_period) -> history with Ultra values
        for combo in combos:
            key = (combo['rsi_ultra_period'], combo['rsi_ultra_signal_period'])
            if key not in ultra_cache:
                ultra_cache[key] = _with_ultra(valid_history, *key)
            metrics = run_combo(ultra_cache[key], combo, dict(rsi_ultra_zone_mid=combo['rsi_ultra_zone_mid']))
            results.append({
                'strategy': 'RSI_ULTRA',
                'rsi_ultra_period': combo['rsi_ultra_period'],
                'rsi_ultra_signal_period': combo['rsi_ultra_signal_period'],
                'rsi_ultra_zone_mid': combo['rsi_ultra_zone_mid'],
                **exits(combo),
                **metrics,
            })

    elif mode == "bc":
        combos = generate_bc_param_combinations(
            bc_buy_offset_range, bc_sell_offset_range, stop_loss_range, take_profit_range, trailing_stop_range)
        if not combos:
            return {"status": "error", "message": "No valid BC parameter combinations generated."}

        # Targets are offsets from a CAUSAL reference (median of the previous 24h at every candle), so a
        # target never uses prices from the future. The row's bc_*_price / ref_price are the targets as
        # of the end of the window, i.e. what the offsets mean if applied to the live bot now.
        reference = causal_reference(valid_history)
        recent = sorted(p['price'] for p in valid_history[-1440:])
        ref_now = recent[len(recent) // 2]

        results = []
        for combo in combos:
            buy_off = combo['bc_buy_offset_pct']
            sell_off = combo['bc_sell_offset_pct']
            metrics = run_combo(valid_history, combo, {}, bc_offsets=(buy_off, sell_off), bc_reference=reference)
            results.append({
                'strategy': 'BC',
                'bc_buy_offset_pct': buy_off,
                'bc_sell_offset_pct': sell_off,
                'bc_buy_price': round(ref_now * (1 - buy_off / 100), 8),
                'bc_sell_price': round(ref_now * (1 + sell_off / 100), 8),
                'ref_price': round(ref_now, 8),
                **exits(combo),
                **metrics,
            })

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
