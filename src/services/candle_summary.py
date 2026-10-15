"""Compact market features for LLM prompts (instead of shipping ~1440 raw candles)."""
from typing import Sequence

LAST_CANDLES = 60
SWING_WINDOW = 3          # a swing needs this many lower/higher candles on each side
MAX_SWINGS = 5
ATR_PERIOD = 14


def _hl(c: dict) -> tuple[float, float, float]:
    close = c["price"]
    return c.get("high", close), c.get("low", close), close


def window_volatility_pct(history: Sequence[dict]) -> float:
    """(max high - min low) / min low * 100 over the whole window."""
    if not history:
        return 0.0
    highs, lows = zip(*[_hl(c)[:2] for c in history])
    low = min(lows)
    return round((max(highs) - low) / low * 100, 2) if low else 0.0


def _swings(history: Sequence[dict]) -> tuple[list[float], list[float]]:
    highs, lows = [], []
    n = SWING_WINDOW
    for i in range(n, len(history) - n):
        h, l, _ = _hl(history[i])
        around = [_hl(history[j]) for j in range(i - n, i + n + 1) if j != i]
        if all(h > a[0] for a in around):
            highs.append(h)
        if all(l < a[1] for a in around):
            lows.append(l)
    return highs[-MAX_SWINGS:], lows[-MAX_SWINGS:]


def summarize_candles(history: Sequence[dict], last_n: int = LAST_CANDLES) -> dict:
    """Return {"summary": {...}, "candles": last_n slimmed candles}."""
    history = list(history)
    if not history:
        return {"summary": {"count": 0}, "candles": []}

    trs = []
    prev_close = None
    for c in history:
        h, l, close = _hl(c)
        trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)) if prev_close is not None else h - l)
        prev_close = close
    recent_tr = trs[-ATR_PERIOD:]
    atr = sum(recent_tr) / len(recent_tr)
    last_close = history[-1]["price"]
    swing_highs, swing_lows = _swings(history)
    highs, lows = zip(*[_hl(c)[:2] for c in history])

    summary = {
        "count": len(history),
        "window_minutes": len(history),
        "range_high": max(highs),
        "range_low": min(lows),
        "range_pct": window_volatility_pct(history),
        "atr_14": round(atr, 6),
        "atr_14_pct": round(atr / last_close * 100, 4) if last_close else None,
        "avg_candle_range": round(sum(h - l for h, l in zip(highs, lows)) / len(history), 6),
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
    }
    candles = [
        {"timestamp": c.get("timestamp"), "open": c.get("open", c["price"]), "high": _hl(c)[0],
         "low": _hl(c)[1], "close": c["price"], "rsi": c.get("rsi")}
        for c in history[-last_n:]
    ]
    return {"summary": summary, "candles": candles}
