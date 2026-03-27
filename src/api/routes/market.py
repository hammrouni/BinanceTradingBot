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
