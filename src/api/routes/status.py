from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/status")
async def get_status(request: Request):
    bot = getattr(request.app.state, "bot_engine", None)
    if bot is None:
        return {"status": "ok", "data": {}}

    pos = bot.open_position
    return {
        "status": "ok",
        "data": {
            "bot_state": bot.state.value,
            "uptime_seconds": bot.get_uptime_seconds(),
            "open_position": {
                "pair": pos.pair,
                "quantity": pos.quantity,
                "entry_price": pos.price,
                "order_id": pos.order_id,
            } if pos else None,
        },
    }
