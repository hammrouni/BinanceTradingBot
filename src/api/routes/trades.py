from fastapi import APIRouter

from src.core.pnl_calculator import calculate_pnl
from src.core.trade_reader import read_trades

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("")
async def get_trades():
    trades = read_trades(limit=50)
    trades_with_pnl = calculate_pnl(trades)
    return {"status": "ok", "data": [t.model_dump() for t in trades_with_pnl]}
