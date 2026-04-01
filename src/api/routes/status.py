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
@router.post("/refresh-wallet")
async def refresh_wallet(request: Request):
    bot = getattr(request.app.state, "bot_engine", None)
    if bot:
        # Fetch the latest from Binance - this updates and broadcasts to UI
        await bot.update_balances(
            request.app.state.binance_client,
            request.app.state.config.trading_pair,
            request.app.state.config,
        )
        return {"status": "ok", "balances": bot.balances}
    return {"status": "error", "message": "Bot engine not found"}
