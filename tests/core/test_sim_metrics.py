"""Net-of-fee metrics: win rate, Sharpe, profit factor, expectancy."""
import math

from src.core.replay import Trade
from src.core.sim_metrics import compute_metrics


def t(net, cost=100.0):
    return Trade(entry_time="a", exit_time="b", entry_price=1.0, exit_price=1.0, qty=1.0, cost=cost,
                 proceeds=cost + net, fees=0.0, net_pnl=net, reason_in="x", reason_out="y")


def test_empty():
    m = compute_metrics([], 1000.0, 1000.0, 0.0)
    assert m["trade_count"] == 0 and m["win_rate"] == 0
    assert m["sharpe"] is None and m["profit_factor"] is None and m["expectancy"] == 0


def test_win_rate_counts_net_pnl_only():
    m = compute_metrics([t(5), t(-1), t(0.0)], 1000.0, 1004.0, 1.0)
    assert m["winning_trades"] == 1 and m["losing_trades"] == 2
    assert m["win_rate"] == round(100 / 3, 2)


def test_profit_factor_expectancy_sharpe():
    trades = [t(10), t(-5), t(5), t(-5)]
    m = compute_metrics(trades, 1000.0, 1005.0, 2.0)
    assert m["profit_factor"] == 1.5                 # 15 / 10
    assert m["expectancy"] == 1.25                   # mean net pnl per trade, USD
    rets = [0.10, -0.05, 0.05, -0.05]
    mean = sum(rets) / 4
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / 3)
    assert m["sharpe"] == round(mean / sd, 2)


def test_profit_factor_none_without_losses_and_sharpe_none_for_one_trade():
    m = compute_metrics([t(3)], 1000.0, 1003.0, 0.0)
    assert m["profit_factor"] is None and m["sharpe"] is None
    assert m["expectancy"] == 3.0


def test_balance_fields():
    m = compute_metrics([t(10)], 1000.0, 1010.0, 0.5)
    assert m["total_pnl"] == 10.0 and m["total_pnl_pct"] == 1.0
    assert m["final_balance"] == 1010.0 and m["max_drawdown_pct"] == 0.5
