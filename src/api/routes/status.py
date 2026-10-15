from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness probe (unauthenticated): used by the Docker healthcheck."""
    return {"status": "ok"}


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
                "stop_loss_price": bot._stop_loss_price,
                "take_profit_price": bot._take_profit_price,
            } if pos else None,
            "balances": bot.balances,
        },
    }
@router.post("/refresh-wallet")
async def refresh_wallet(request: Request):
    bot = getattr(request.app.state, "bot_engine", None)
    if bot:
        # Fetch the latest from Binance - this updates and broadcasts to UI
        await bot.update_balances(
            request.app.state.config.trading_pair,
            request.app.state.config,
        )
        return {"status": "ok", "balances": bot.balances}
    return {"status": "error", "message": "Bot engine not found"}
