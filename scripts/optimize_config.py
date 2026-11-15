"""Find RSI settings that win consistently, not just once.

Every parameter set is replayed (with fees) on many separate time windows of public Binance
1m data, on several pairs. A setting is only ranked if it is profitable in most windows, so a
lucky single run cannot win. Uses the bot's own simulator (same code as live trading).

    python scripts/optimize_config.py                       # BTCUSDT ETHUSDT BNBUSDT SOLUSDT, 16 days
    python scripts/optimize_config.py --pairs BTCUSDT --days 16 --fee 0.075

Needs the project's dependencies; dummy PROD_/TEST_ Binance env vars are enough (data is public).
"""
from __future__ import annotations

import argparse
import itertools
import os
import statistics
import sys
import time
from pathlib import Path

for _k in ("PROD_BINANCE_API_KEY", "PROD_BINANCE_API_SECRET", "TEST_BINANCE_API_KEY", "TEST_BINANCE_API_SECRET"):
    os.environ.setdefault(_k, "x")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from src.core.simulator import simulate_single  # noqa: E402
from src.services.history_loader import WARMUP_CANDLES, build_market_history  # noqa: E402

TRADE_USD = 100.0
BALANCE = 1000.0


def fetch(symbol: str, days: int) -> list[dict]:
    minutes = days * 1440 + WARMUP_CANDLES
    now = int(time.time() * 1000)
    start = (now - minutes * 60000) // 60000 * 60000
    rows: list[list] = []
    with httpx.Client(timeout=30) as c:
        while True:
            b = c.get("https://api.binance.com/api/v3/klines",
                      params=dict(symbol=symbol, interval="1m", startTime=start, limit=1000)).json()
            if not isinstance(b, list) or not b:
                break
            rows += b
            start = b[-1][0] + 60000
            if len(b) < 1000:
                break
    rows = [r for r in rows if r[6] < now]
    return build_market_history(rows, window=days * 1440)


def run_chunk(chunk, params, fee):
    r = simulate_single(chunk, "rsi", BALANCE, TRADE_USD, fee_pct=fee, **params)
    return r["total_pnl"] / TRADE_USD * 100, r["trade_count"], r["max_drawdown_pct"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"])
    ap.add_argument("--days", type=int, default=16)
    ap.add_argument("--chunk-days", type=int, default=2)
    ap.add_argument("--fee", type=float, default=0.1, help="% per side (0.075 with BNB fee discount)")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()

    oversold = [15, 20, 25, 30]
    overbought = [60, 70, 80]
    stop = [1.0, 2.0, 3.0]
    take = [0.8, 1.2, 2.0, 3.0]
    filters = {
        "none": {},
        "EMA20>EMA50": dict(ema_fast_period=20, ema_slow_period=50),
        "bear-block": dict(bear_trend_candles=30, bear_trend_pct=0.5),
    }
    combos = [
        dict(rsi_oversold=o, rsi_overbought=b, stop_loss_pct=s, take_profit_pct=t, **f, _filter=name)
        for (o, b, s, t), (name, f) in itertools.product(itertools.product(oversold, overbought, stop, take), filters.items())
    ]

    chunks = []  # (pair, rows)
    size = a.chunk_days * 1440
    for sym in a.pairs:
        hist = fetch(sym, a.days)
        print(f"{sym}: {len(hist)} candles, buy&hold {100 * (hist[-1]['price'] / hist[0]['price'] - 1):+.2f}%", flush=True)
        chunks += [hist[i:i + size] for i in range(0, len(hist) - size + 1, size)]
    print(f"{len(combos)} settings x {len(chunks)} windows, fee {a.fee}%/side\n", flush=True)

    scored = []
    for n, p in enumerate(combos, 1):
        params = {k: v for k, v in p.items() if k != "_filter"}
        res = [run_chunk(c, params, a.fee) for c in chunks]
        pnls = [r[0] for r in res]
        trades = sum(r[1] for r in res)
        scored.append(dict(
            filter=p["_filter"], params={k: v for k, v in params.items() if k in
                                         ("rsi_oversold", "rsi_overbought", "stop_loss_pct", "take_profit_pct")},
            mean=statistics.mean(pnls), worst=min(pnls),
            win_windows=sum(1 for x in pnls if x > 0) / len(pnls) * 100,
            traded_windows=sum(1 for r in res if r[1] > 0), trades=trades,
            dd=max(r[2] for r in res),
        ))
        if n % 50 == 0:
            print(f"  {n}/{len(combos)}", flush=True)

    # Robust ranking: must trade enough and be profitable in most windows that traded.
    ok = [s for s in scored if s["trades"] >= len(chunks) * 1.5]
    ok.sort(key=lambda s: (s["mean"] - 0.5 * abs(min(s["worst"], 0))), reverse=True)
    print("\nTop settings (mean % of trade size per window, after fees):")
    for s in ok[:a.top]:
        print(f"  mean {s['mean']:+6.2f}%  worst {s['worst']:+6.2f}%  profitable windows {s['win_windows']:4.0f}%  "
              f"trades {s['trades']:3}  max DD {s['dd']:.2f}%  filter={s['filter']}  {s['params']}")
    best = ok[0] if ok else None
    all_mean = statistics.mean(s["mean"] for s in scored)
    print(f"\nAverage over ALL {len(scored)} settings: {all_mean:+.2f}% per window (the 'no skill' baseline).")
    if not best or best["mean"] <= 0 or best["win_windows"] < 55:
        print("VERDICT: no setting is reliably profitable after fees in this period. Do not trade live with it.")
    else:
        print("VERDICT: candidate found. Still forward-test it on testnet for days before using real money.")


if __name__ == "__main__":
    main()
