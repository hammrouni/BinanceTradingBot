from fastapi import APIRouter, Request
from src.core.pnl_calculator import calculate_pnl
from src.core.trade_reader import read_trades

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("")
async def get_trades(request: Request):
    client = getattr(request.app.state, "binance_client", None)
    config = getattr(request.app.state, "config", None)

    if not client or not config:
        return {"status": "ok", "data": []}

    # Fetch real trade history from PROD (handled by client internally)
    trades = await client.get_trade_history(symbol=config.trading_pair, limit=50)

    # Binance API doesn't return reason (stop_loss, take_profit, etc.)
    # Enrich from local trades.jsonl which records reason at execution time
    local_trades = read_trades(limit=500)
    reason_by_order_id = {t.order_id: t.reason for t in local_trades if t.reason}
    for t in trades:
        if t.reason is None and t.order_id in reason_by_order_id:
            t.reason = reason_by_order_id[t.order_id]

    # Calculate PnL on the real data
    trades_with_pnl = calculate_pnl(trades)

    return {"status": "ok", "data": [t.model_dump() for t in trades_with_pnl], "type": "prod"}


@router.get("/test")
async def get_test_trades():
    # Local testnet history from the trade log: only testnet trades, PnL paired per trading pair
    trades = [t for t in read_trades(limit=500) if t.is_test]
    trades_with_pnl = calculate_pnl(trades)[:50]   # read_trades is newest first

    return {"status": "ok", "data": [t.model_dump() for t in trades_with_pnl], "type": "test"}
