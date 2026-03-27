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
    
    # Calculate PnL on the real data
    trades_with_pnl = calculate_pnl(trades)
    
    return {"status": "ok", "data": [t.model_dump() for t in trades_with_pnl], "type": "prod"}


@router.get("/test")
async def get_test_trades():
    # Fetch local test history from the logs
    trades = read_trades(limit=50)
    
    # Calculate PnL on the local test data
    trades_with_pnl = calculate_pnl(trades)
    
    return {"status": "ok", "data": [t.model_dump() for t in trades_with_pnl], "type": "test"}
