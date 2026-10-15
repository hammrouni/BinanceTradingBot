"""DataStream follows set_symbol() without a process restart."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.data_stream import DataStream
from tests.services.test_data_stream import make_kline_msg, make_settings


def msg(symbol, close, closed=True):
    m = make_kline_msg(close, closed)
    m["s"] = symbol
    m["k"]["s"] = symbol
    return m


async def test_stream_subscribes_to_the_requested_symbol_and_switches_live():
    stream = DataStream()
    settings = make_settings()
    queue: asyncio.Queue = asyncio.Queue()
    subscribed = []

    def make_ws(symbol):
        pending = {"BTCUSDT": [msg("BTCUSDT", 100.0), msg("BTCUSDT", 101.0)],
                   "ETHUSDT": [msg("ETHUSDT", 2000.0)]}[symbol]

        async def recv():
            if pending:
                m = pending.pop(0)
                if symbol == "BTCUSDT" and m["k"]["c"] == "100.0":
                    stream.set_symbol("ETHUSDT")   # the pair is changed while streaming
                return m
            stream.stop()
            return None

        ws = AsyncMock()
        ws.recv = AsyncMock(side_effect=recv)
        return ws

    def kline_socket(symbol, interval):
        subscribed.append(symbol)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=make_ws(symbol))
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    bm = MagicMock()
    bm.kline_socket = kline_socket
    with patch("src.services.data_stream.AsyncClient") as cls, \
         patch("src.services.data_stream.BinanceSocketManager", return_value=bm):
        cls.create = AsyncMock(return_value=AsyncMock())
        await asyncio.wait_for(stream.start(settings, queue, symbol="BTCUSDT"), timeout=5.0)

    assert subscribed == ["BTCUSDT", "ETHUSDT"]
    got = []
    while not queue.empty():
        got.append(await queue.get())
    # candles of the old pair that arrive after the switch request are discarded
    assert [(k.pair, k.close) for k in got] == [("ETHUSDT", 2000.0)]


def test_set_symbol_normalises_case():
    s = DataStream()
    s.set_symbol(" ethusdt ")
    assert s._symbol == "ETHUSDT"
