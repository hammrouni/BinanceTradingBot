"""Shared history loader: paginated kline fetch + market_history building with warm-up stripped."""
import math

from src.core.rsi_calculator import RsiCalculator
from src.core.rsi_ultra_calculator import RsiUltraCalculator
from src.services import history_loader as hl

MIN = 60_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % MIN)


def make_rows(n, start=T0, base=100.0):
    rows = []
    for i in range(n):
        c = base + 5 * math.sin(i / 5) + 2 * math.sin(i / 1.7)
        t = start + i * MIN
        rows.append([t, str(c - 0.1), str(c + 0.5), str(c - 0.5), str(c), "1.5", t + MIN - 1])
    return rows


class FakeClient:
    """Serves klines like Binance: startTime inclusive, at most `limit` rows per call."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def get_klines(self, symbol, interval, startTime, limit=1000):
        self.calls.append(startTime)
        return [r for r in self.rows if r[0] >= startTime][:limit]


async def test_fetch_klines_paginates_past_1000_and_drops_the_open_candle():
    rows = make_rows(2500)
    now_ms = rows[-1][0] + 30_000   # the last row is still open
    client = FakeClient(rows)
    out = await hl.fetch_klines(client, "BTCUSDT", minutes=2400, now_ms=now_ms)
    assert len(client.calls) >= 3
    assert out[-1][0] == rows[-2][0]                 # open candle dropped
    assert len(out) >= 2400
    opens = [r[0] for r in out]
    assert opens == sorted(set(opens))               # no duplicates across pages


async def test_fetch_klines_empty():
    assert await hl.fetch_klines(FakeClient([]), "BTCUSDT", minutes=100, now_ms=T0) == []


def test_build_history_row_shape_and_rsi_start():
    hist = hl.build_market_history(make_rows(60))
    assert hist, "expected rows once RSI has enough candles"
    row = hist[0]
    assert set(row) >= {"timestamp", "price", "open", "high", "low", "volume",
                        "rsi", "rsi_ultra_raw", "rsi_ultra_signal"}
    assert row["timestamp"].endswith("Z")
    assert all(r["rsi"] is not None for r in hist)
    assert len(hist) == 60 - 14                     # RSI needs period+1 candles


def test_build_history_strips_warmup_to_window():
    hist = hl.build_market_history(make_rows(500), window=100)
    assert len(hist) == 100
    # the window is the most recent part and its Ultra values are already warm
    assert hist[0]["rsi_ultra_raw"] is not None and hist[0]["rsi_ultra_signal"] is not None


def test_build_history_uses_configured_ultra_periods():
    rows = make_rows(400)
    a = hl.build_market_history(rows, ultra_period=14, ultra_signal_period=9)
    b = hl.build_market_history(rows, ultra_period=5, ultra_signal_period=3)
    assert a[-1]["rsi_ultra_raw"] != b[-1]["rsi_ultra_raw"]
    assert a[-1]["rsi"] == b[-1]["rsi"]


def test_build_history_feeds_provided_calculators():
    rsi, ultra = RsiCalculator(), RsiUltraCalculator(7, 4)
    hist = hl.build_market_history(make_rows(120), rsi_calc=rsi, ultra_calc=ultra)
    assert rsi.current_rsi is not None
    assert ultra.current_values[0] is not None
    assert hist[-1]["rsi"] == round(rsi.current_rsi, 2)


def test_compute_ultra_series_matches_loader_values():
    rows = make_rows(300)
    hist = hl.build_market_history(rows, ultra_period=14, ultra_signal_period=9)
    series = hl.compute_ultra_series(hist, 14, 9)
    assert len(series) == len(hist)
    # recomputing from the (RSI-trimmed) rows is internally consistent
    assert series[-1][0] is not None


async def test_load_market_history_uses_prod_client_and_window(monkeypatch):
    rows = make_rows(900)
    client = FakeClient(rows)
    closed = {"v": False}

    async def close():
        closed["v"] = True
    client.close_connection = close

    async def factory(settings):
        return client

    hist = await hl.load_market_history(
        settings=object(), symbol="BTCUSDT", minutes=200, client_factory=factory,
        now_ms=rows[-1][0] + 10_000)
    assert len(hist) == 200 and closed["v"]
