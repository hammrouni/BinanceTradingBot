"""sim_metrics.py — Performance metrics of a simulated run, all net of fees.

A trade's `net_pnl` already includes the buy and the sell fee (proceeds minus cost), so the win rate,
profit factor, expectancy and Sharpe below are fee-aware.
"""

from __future__ import annotations

import math
from typing import Sequence


def compute_metrics(trades: Sequence, initial_balance: float, final_balance: float, max_drawdown_pct: float) -> dict:
    """Metrics dict for `trades` (objects with net_pnl and cost).

    - win_rate: share of trades with net_pnl > 0.
    - profit_factor: gross profit / gross loss; None when there is no losing trade.
    - expectancy: mean net PnL per trade in USD.
    - sharpe: per-trade Sharpe ratio, mean / stdev (n-1) of the net trade returns (pnl / cost);
      NOT annualised. None with fewer than two trades or zero variance.
    """
    total_pnl = final_balance - initial_balance
    total_pnl_pct = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0.0
    n = len(trades)
    pnls = [t.net_pnl for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)

    sharpe = None
    if n >= 2:
        rets = [t.net_pnl / t.cost for t in trades if t.cost > 0]
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            if var > 0:
                sharpe = round(mean / math.sqrt(var), 2)

    return {
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "win_rate": round(wins / n * 100, 2) if n else 0,
        "trade_count": n,
        "winning_trades": wins,
        "losing_trades": n - wins,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "final_balance": round(final_balance, 2),
        "sharpe": sharpe,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy": round(sum(pnls) / n, 2) if n else 0,
    }
