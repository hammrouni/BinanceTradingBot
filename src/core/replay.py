"""replay.py — Candle replay harness: the simulator drives the SAME code as the live BotEngine.

For every candle the harness mirrors BotEngine.process_market_update():
  1. record the close in the strategies' price buffers,
  2. risk exit (trailing ratchet, stop-loss, take-profit) through `core.risk`,
  3. the active strategy classes (`core.strategies.*`) are fed a `TickContext`, with the shared
     filters inside them,
  4. after any sell the strategies are reset exactly like `BotEngine._clear_position()` does.
Nothing about signals, filters or SL/TP is re-implemented here, so a change to a strategy or to
`risk.py` changes live trading and simulation together. tests/core/test_replay_parity.py feeds the
same candles to a real BotEngine and to this harness and requires identical trades.

Candle model (`intrabar=True`, the default): a position opened at a candle's close is exposed to the
NEXT candles' high/low. Within one candle the order of high and low is unknown, so ties resolve
pessimistically:
  - the stop is evaluated first, against the trailing level reached by the candle's HIGH
    (assume the high came before the low);
  - the take-profit is only taken when the stop was not touched;
  - stops fill at the stop level (at the open when the candle gaps through it), targets at the
    target level (at the open when the candle gaps over it).
`intrabar=False` evaluates the close only, which is what BotEngine.process_market_update() does.
Fees are charged on both sides (`fee_pct` each) and every figure is net of them.
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Sequence

from src.core import risk
from src.core.strategies import BCStrategy, RSIStrategy, RsiUltraStrategy
from src.core.strategies.base import Signal, TickContext
from src.core.strategies.filters import (
    FILTER_BEAR, FILTER_BOUNCE, FILTER_EMA_TREND, FILTER_MA,
)
from src.models.config import TradingConfig

MODE_TO_ACTIVE = {"rsi": "RSI", "bc": "BC", "rsi_ultra": "RSI_ULTRA"}

# Causal BC reference: median of the previous BC_REF_LOOKBACK closes (24h of 1m candles, the
# bot's own history size), and no BC signal before BC_REF_MIN_CANDLES candles of history exist.
BC_REF_LOOKBACK = 1440
BC_REF_MIN_CANDLES = 30


@dataclass
class Trade:
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    qty: float
    cost: float          # USD spent on the buy (fee included)
    proceeds: float      # USD received on the sell (fee deducted)
    fees: float          # buy + sell fee in USD
    net_pnl: float       # proceeds - cost
    reason_in: str
    reason_out: str


@dataclass
class ReplayResult:
    trades: list[Trade] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    initial_balance: float = 0.0
    final_balance: float = 0.0
    max_drawdown_pct: float = 0.0


@dataclass
class _Position:
    entry_price: float
    qty: float
    cost: float
    entry_time: str
    reason_in: str
    stop_loss: float | None
    take_profit: float | None


def config_for_sim(
    mode: str,
    *,
    trade_amount_usd: float | None = 100.0,
    rsi_oversold=None, rsi_overbought=None,
    stop_loss_pct=None, take_profit_pct=None, trailing_stop_pct=None,
    price_bounce_ticks=None, bear_trend_candles=None, bear_trend_pct=None,
    ma_filter_period=None, ema_fast_period=None, ema_slow_period=None,
    bc_buy_price=None, bc_sell_price=None,
    rsi_ultra_zone_mid=50.0,
    **extra,
) -> TradingConfig:
    """The live TradingConfig equivalent of simulator parameters.

    Built without validation: the simulator accepts values the dashboard would clamp (a 5 USD trade
    amount, a 0% stop). A filter parameter that is None means the filter is off, so `active_filters`
    is derived from which parameters are set.
    """
    filters = []
    if price_bounce_ticks is not None:
        filters.append(FILTER_BOUNCE)
    if bear_trend_candles is not None and bear_trend_pct is not None:
        filters.append(FILTER_BEAR)
    if ma_filter_period is not None:
        filters.append(FILTER_MA)
    if ema_fast_period is not None and ema_slow_period is not None:
        filters.append(FILTER_EMA_TREND)
    return TradingConfig.model_construct(
        active_modes=[MODE_TO_ACTIVE[mode]], active_filters=filters,
        trade_amount_usd=trade_amount_usd,
        rsi_oversold=rsi_oversold, rsi_overbought=rsi_overbought,
        stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct, trailing_stop_pct=trailing_stop_pct,
        price_bounce_ticks=price_bounce_ticks, bear_trend_candles=bear_trend_candles,
        bear_trend_pct=bear_trend_pct, ma_filter_period=ma_filter_period,
        ema_fast_period=ema_fast_period, ema_slow_period=ema_slow_period,
        bc_buy_price=bc_buy_price, bc_sell_price=bc_sell_price,
        rsi_ultra_zone_mid=rsi_ultra_zone_mid,
        **extra,
    )


def valid_rows(history: Sequence[dict]) -> list[dict]:
    """Rows with a usable close (not None / zero / negative / NaN)."""
    return [p for p in history if p.get("price") and p["price"] > 0 and not math.isnan(p["price"])]


def causal_reference(
    rows: Sequence[dict], lookback: int = BC_REF_LOOKBACK, min_candles: int = BC_REF_MIN_CANDLES,
) -> list[float | None]:
    """Per row, the median close of the up-to-`lookback` rows BEFORE it (None until `min_candles` exist).

    Only past candles are used, so a BC target derived from it can never see the future.
    """
    out: list[float | None] = []
    window: deque[float] = deque()
    ordered: list[float] = []
    for row in rows:
        n = len(ordered)
        out.append(ordered[n // 2] if n >= min_candles else None)
        price = row["price"]
        window.append(price)
        bisect.insort(ordered, price)
        if len(window) > lookback:
            del ordered[bisect.bisect_left(ordered, window.popleft())]
    return out


def _risk_exit(pos: _Position, row: dict, price: float, trailing_pct, intrabar: bool):
    """(fill_price, reason) when the position's SL/TP triggers on this candle, else None.

    Updates pos.stop_loss with the trailing ratchet either way.
    """
    if not intrabar:
        pos.stop_loss = risk.ratchet_trailing(pos.stop_loss, price, trailing_pct)
        if risk.stop_hit(pos.stop_loss, price):
            return price, "stop_loss"
        if risk.target_hit(pos.take_profit, price):
            return price, "take_profit"
        return None

    o = row.get("open") or price
    high = max(row.get("high") or price, price, o)
    low = min(row.get("low") or price, price, o)

    start_stop = pos.stop_loss
    pos.stop_loss = risk.ratchet_trailing(start_stop, high, trailing_pct)   # pessimistic: high first
    if risk.stop_hit(pos.stop_loss, low):
        gapped = start_stop is not None and risk.stop_hit(start_stop, o)
        return (o if gapped else pos.stop_loss), "stop_loss"
    if risk.target_hit(pos.take_profit, high):
        return max(o, pos.take_profit), "take_profit"
    return None


def replay(
    history: Sequence[dict],
    config: TradingConfig,
    *,
    initial_balance: float = 1000.0,
    fee_pct: float = 0.1,
    intrabar: bool = True,
    bc_offsets: tuple[float, float] | None = None,
    bc_reference: Sequence[float | None] | None = None,
) -> ReplayResult:
    """Replay `history` (market_history rows) through the live strategies and risk rules.

    bc_offsets=(buy_pct, sell_pct) turns BC into relative targets: at every candle
    bc_buy_price = ref * (1 - buy/100), bc_sell_price = ref * (1 + sell/100) with ref the causal
    reference (`causal_reference`, or `bc_reference` aligned with the VALID rows when precomputed).
    Without it `config.bc_buy_price` / `bc_sell_price` are the fixed absolute targets, as live.
    """
    config = config.model_copy()   # BC targets are rewritten per candle; never touch the caller's config
    rows = valid_rows(history)
    fee = fee_pct / 100.0
    active_modes = config.active_modes or ["RSI"]
    classes = {"RSI": RSIStrategy, "BC": BCStrategy, "RSI_ULTRA": RsiUltraStrategy}
    strategies = {name: classes[name]() for name in active_modes if name in classes}
    full_balance = bool(getattr(config, "bc_use_full_balance", False)) and "BC" in active_modes

    if bc_offsets is not None and bc_reference is None:
        bc_reference = causal_reference(rows)

    result = ReplayResult(initial_balance=initial_balance)
    balance = initial_balance
    peak = initial_balance
    pos: _Position | None = None
    prev_raw = prev_sig = None

    def reset_strategies():
        nonlocal prev_raw, prev_sig
        prev_raw = prev_sig = None
        for s in strategies.values():
            s.on_reset()

    def close(fill: float, ts: str, reason: str):
        nonlocal balance, pos
        proceeds = pos.qty * fill * (1 - fee)
        net = proceeds - pos.cost
        balance += proceeds
        buy_fee = pos.cost * fee
        sell_fee = pos.qty * fill * fee
        result.trades.append(Trade(
            entry_time=pos.entry_time, exit_time=ts, entry_price=pos.entry_price, exit_price=fill,
            qty=pos.qty, cost=pos.cost, proceeds=proceeds, fees=buy_fee + sell_fee, net_pnl=net,
            reason_in=pos.reason_in, reason_out=reason))
        result.events.append({"timestamp": ts, "price": fill, "action": "sell", "reason": reason,
                              "pnl": round(net, 2)})
        pos = None

    for i, row in enumerate(rows):
        price = row["price"]
        ts = row.get("timestamp")

        # 1. the close enters the strategies' price buffers (BotEngine._record_market_data)
        for s in strategies.values():
            if hasattr(s, "record_price"):
                s.record_price(price)

        # 2. risk exit; BotEngine returns right after it, with the strategies reset
        if pos is not None:
            hit = _risk_exit(pos, row, price, config.trailing_stop_pct, intrabar)
            if hit is not None:
                close(hit[0], ts, hit[1])
                reset_strategies()
                peak, result.max_drawdown_pct = _track_drawdown(balance, peak, result.max_drawdown_pct)
                continue

        # 3. strategies
        if bc_offsets is not None:
            ref = bc_reference[i]
            config.bc_buy_price = None if ref is None else ref * (1 - bc_offsets[0] / 100)
            config.bc_sell_price = None if ref is None else ref * (1 + bc_offsets[1] / 100)

        raw, sig = row.get("rsi_ultra_raw"), row.get("rsi_ultra_signal")
        ctx = TickContext(
            price=price, rsi=row.get("rsi"), config=config,
            has_open_position=pos is not None, buy_lock_held=False,
            rsi_ultra_raw=raw, rsi_ultra_signal=sig,
            prev_rsi_ultra_raw=prev_raw, prev_rsi_ultra_signal=prev_sig,
        )
        for mode in active_modes:
            strategy = strategies.get(mode)
            if strategy is None:
                continue
            res = strategy.on_tick(ctx)
            if res.signal == Signal.BUY and pos is None:
                amount = balance if full_balance else (
                    res.amount_override if res.amount_override is not None else config.trade_amount_usd)
                if amount and amount >= 1e-9 and balance >= amount:
                    lows = []
                    if config.sl_lookback_candles is not None:
                        lows = [r["low"] for r in rows[max(0, i - config.sl_lookback_candles + 1): i + 1]
                                if r.get("low") is not None]
                    t = risk.compute_thresholds(price, config, recent_lows=lows)
                    balance -= amount
                    pos = _Position(
                        entry_price=price, qty=amount * (1 - fee) / price, cost=amount, entry_time=ts,
                        reason_in=res.reason, stop_loss=t.stop_loss, take_profit=t.take_profit)
                    result.events.append({"timestamp": ts, "price": price, "action": "buy",
                                          "reason": res.reason, "pnl": None})
                break
            elif res.signal == Signal.SELL and pos is not None:
                close(price, ts, res.reason)
                reset_strategies()
                break

        # 4. advance rolling state
        prev_raw, prev_sig = raw, sig

        equity = balance + (pos.qty * price * (1 - fee) if pos is not None else 0.0)
        peak, result.max_drawdown_pct = _track_drawdown(equity, peak, result.max_drawdown_pct)

    if pos is not None and rows:
        last = rows[-1]
        close(last["price"], last.get("timestamp"), "end_of_data")
        peak, result.max_drawdown_pct = _track_drawdown(balance, peak, result.max_drawdown_pct)

    result.final_balance = balance
    return result


def _track_drawdown(equity: float, peak: float, worst: float) -> tuple[float, float]:
    peak = max(peak, equity)
    if peak > 0:
        worst = max(worst, (peak - equity) / peak * 100)
    return peak, worst
