"""history_loader.py — The one place that fetches 1m klines and turns them into `market_history`.

Used by the startup / pair-change seeding (MarketRuntime) and by every simulator route, so the
live feed and the simulator see candles built the same way: RSI(14), RSI Ultra with the configured
periods, warm-up candles stripped.

A market_history row is a dict: timestamp (candle open, UTC ISO), price (close), open, high, low,
volume, rsi, rsi_ultra_raw, rsi_ultra_signal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable, Sequence

from src.core.rsi_calculator import RSI_PERIOD, RsiCalculator
from src.core.rsi_ultra_calculator import BUFFER_SIZE as ULTRA_BUFFER_SIZE, RsiUltraCalculator
from src.models.market import KlineData
from src.utils.logger import get_logger

logger = get_logger(__name__)

INTERVAL_MS = 60_000
BATCH_LIMIT = 1000
MAX_BATCHES = 25
# Extra candles fetched before the requested window so both 150-slot Ultra buffers (hlc3 + rsi)
# are full of real values before the first returned candle (the rsi buffer only fills once the
# hlc3 buffer is full, hence 2x), plus the RSI period.
WARMUP_CANDLES = ULTRA_BUFFER_SIZE * 2 + RSI_PERIOD

ClientFactory = Callable[[object], Awaitable[object]]


async def open_prod_client(settings):
    """Binance production client, used for public market data only."""
    from binance import AsyncClient

    return await AsyncClient.create(
        api_key=settings.prod_binance_api_key,
        api_secret=settings.prod_binance_api_secret,
        testnet=False,
    )


async def fetch_klines(client, symbol: str, minutes: int, *, now_ms: int | None = None) -> list[list]:
    """The last `minutes` closed 1m klines of `symbol`, oldest first, paginated 1000 at a time.

    The still-open candle (close_time in the future) is dropped.
    """
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = (now_ms - minutes * INTERVAL_MS) // INTERVAL_MS * INTERVAL_MS

    rows: list[list] = []
    last_open = -1
    for _ in range(MAX_BATCHES):
        batch = await client.get_klines(symbol=symbol, interval="1m", startTime=start, limit=BATCH_LIMIT)
        if not batch:
            break
        fresh = [r for r in batch if r[0] > last_open]
        if not fresh:
            break
        rows.extend(fresh)
        last_open = fresh[-1][0]
        start = last_open + INTERVAL_MS
        if len(batch) < BATCH_LIMIT or last_open >= now_ms - INTERVAL_MS:
            break

    return [r for r in rows if r[6] < now_ms]


def kline_from_row(k: Sequence) -> KlineData:
    return KlineData(
        open_time=k[0], open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
        volume=float(k[5]), close_time=k[6], is_closed=True,
    )


def build_market_history(
    klines: Iterable[Sequence],
    *,
    rsi_calc: RsiCalculator | None = None,
    ultra_calc: RsiUltraCalculator | None = None,
    ultra_period: int = 14,
    ultra_signal_period: int = 9,
    window: int | None = None,
) -> list[dict]:
    """market_history rows for closed `klines` (oldest first).

    Candles before RSI is available are skipped. Calculators may be passed in (the live seeding
    does, so they end up warm); otherwise fresh ones with the given Ultra periods are used.
    With `window`, only the most recent `window` rows are returned: the leading warm-up is stripped.
    """
    rsi_calc = rsi_calc or RsiCalculator()
    ultra_calc = ultra_calc or RsiUltraCalculator(ultra_period, ultra_signal_period)

    history: list[dict] = []
    for k in klines:
        kd = kline_from_row(k)
        rsi_val = rsi_calc.add_candle(kd)
        raw, sig = ultra_calc.add_candle(kd)
        if rsi_val is None:
            continue
        history.append({
            "timestamp": datetime.fromtimestamp(kd.open_time / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rsi": round(rsi_val, 2),
            "rsi_ultra_raw": round(raw, 2) if raw is not None else None,
            "rsi_ultra_signal": round(sig, 2) if sig is not None else None,
            "price": kd.close, "open": kd.open, "high": kd.high, "low": kd.low, "volume": kd.volume,
        })

    if window is not None and len(history) > window:
        history = history[-window:]
    return history


def compute_ultra_series(market_history: Sequence[dict], period: int, signal_period: int) -> list[tuple]:
    """RSI Ultra (raw, signal) for every row of `market_history` with the given periods.

    Rows need 'price' (close); missing high/low fall back to the price.
    """
    calc = RsiUltraCalculator(rsi_period=int(period), signal_period=int(signal_period))
    out = []
    for p in market_history:
        price = p["price"]
        out.append(calc.add_candle(KlineData(
            open_time=0, open=p.get("open") or price, high=p.get("high") or price,
            low=p.get("low") or price, close=price, volume=0.0, close_time=0, is_closed=True,
        )))
    return out


async def load_market_history(
    settings,
    symbol: str,
    minutes: int,
    *,
    ultra_period: int = 14,
    ultra_signal_period: int = 9,
    client_factory: ClientFactory = open_prod_client,
    now_ms: int | None = None,
) -> list[dict]:
    """The last `minutes` candles of `symbol` as market_history, indicators warmed up beforehand."""
    client = await client_factory(settings)
    try:
        klines = await fetch_klines(client, symbol, minutes + WARMUP_CANDLES, now_ms=now_ms)
    finally:
        await client.close_connection()
    return build_market_history(
        klines, ultra_period=ultra_period, ultra_signal_period=ultra_signal_period, window=minutes)
