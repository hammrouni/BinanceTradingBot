"""GET /trades/test shows only testnet trades, PnL paired per pair."""
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from main import app
from tests.core.test_recovery_pairing import trade


async def test_test_trades_route_excludes_live_trades_and_pairs_per_pair():
    log = [  # newest first, as read_trades returns them
        trade("sell", price=120, is_test=True, at="2026-01-01T03:00:00Z", order_id="t-sell"),
        trade("sell", price=500, is_test=False, at="2026-01-01T02:00:00Z", order_id="live-sell"),
        trade("buy", price=100, is_test=True, at="2026-01-01T01:00:00Z", order_id="t-buy"),
        trade("buy", price=400, is_test=False, at="2026-01-01T00:00:00Z", order_id="live-buy"),
    ]
    with patch("src.api.routes.trades.read_trades", lambda limit=50: log[:limit]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.get("/api/v1/trades/test")
    data = res.json()["data"]
    assert [t["order_id"] for t in data] == ["t-sell", "t-buy"]
    assert data[0]["pnl_usd"] == 2.0                      # (120-100)*0.1, never against the live buy at 400
