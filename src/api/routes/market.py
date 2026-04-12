from fastapi import APIRouter, Request

router = APIRouter(prefix="/market", tags=["market"])

@router.get("/history")
async def get_market_history(request: Request):
    bot = getattr(request.app.state, "bot_engine", None)
    if bot is None:
        return {"status": "ok", "data": []}
    
    # Convert deque to list for JSON serialization
    return {
        "status": "ok",
        "data": list(bot.market_history)
    }

@router.get("/orderbook")
async def get_order_book(request: Request, symbol: str, limit: int = 20):
    client = request.app.state.binance_client
    try:
        book = await client.client.get_order_book(symbol=symbol, limit=limit)
        return {"status": "ok", "data": book}
    except Exception as e:
        return {"status": "error", "message": str(e)}
