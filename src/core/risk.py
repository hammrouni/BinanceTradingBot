"""risk.py — Stop-loss / take-profit / trailing arithmetic shared by the live BotEngine and the simulator.

Pure functions: no I/O, no state. The engine keeps the state (current SL/TP, frozen support level) and
the replay harness keeps its own; both compute and compare through these helpers so a number can never
mean something different live and in simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Thresholds:
    stop_loss: float | None
    take_profit: float | None
    support_level: float | None = None


def compute_thresholds(
    entry_price: float,
    config,
    recent_lows: Sequence[float] = (),
    support_level: float | None = None,
    fresh_entry: bool = True,
) -> Thresholds:
    """SL / TP for a position entered at `entry_price`.

    `recent_lows` are the lows of the last `config.sl_lookback_candles` candles (caller slices).
    With a support-level SL the lowest low is frozen at entry; later calls pass it back as
    `support_level` with `fresh_entry=False` so it is not recomputed.
    """
    if config.sl_lookback_candles is not None and (recent_lows or support_level is not None):
        if fresh_entry or support_level is None:
            support_level = min(recent_lows) if recent_lows else None
        stop_loss = (support_level * (1 - config.sl_buffer_pct / 100)) if support_level is not None else None
    else:
        support_level = None
        if config.stop_loss_pct is not None:
            stop_loss = entry_price * (1 - config.stop_loss_pct / 100)
        elif config.trailing_stop_pct is not None:
            stop_loss = entry_price * (1 - config.trailing_stop_pct / 100)
        else:
            stop_loss = None

    take_profit = None
    if config.take_profit_pct is not None and config.take_profit_pct > 0:
        use_bc_anchor = config.tp_anchor == "bc_buy" and config.bc_buy_price is not None
        base = config.bc_buy_price if use_bc_anchor else entry_price
        take_profit = base * (1 + config.take_profit_pct / 100)

    return Thresholds(stop_loss, take_profit, support_level)


def ratchet_trailing(stop_loss: float | None, price: float, trailing_stop_pct: float | None) -> float | None:
    """The stop after seeing `price`: it only ever moves up, and only with a trailing % and an SL."""
    if trailing_stop_pct is None or stop_loss is None:
        return stop_loss
    candidate = price * (1 - trailing_stop_pct / 100)
    return candidate if candidate > stop_loss else stop_loss


def stop_hit(stop_loss: float | None, price: float) -> bool:
    return stop_loss is not None and price < stop_loss


def target_hit(take_profit: float | None, price: float) -> bool:
    return take_profit is not None and price >= take_profit
