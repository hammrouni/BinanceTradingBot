from fastapi import APIRouter, HTTPException, Request

from src.core.bot_engine import InvalidStateTransitionError

router = APIRouter(prefix="/bot", tags=["bot"])


@router.post("/start")
async def start_bot(request: Request):
    bot = request.app.state.bot_engine
    try:
        await bot.start()
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok", "data": {"bot_state": bot.state.value}}


@router.post("/pause")
async def pause_bot(request: Request):
    bot = request.app.state.bot_engine
    try:
        await bot.pause()
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok", "data": {"bot_state": bot.state.value}}


@router.post("/resume")
async def resume_bot(request: Request):
    bot = request.app.state.bot_engine
    try:
        await bot.resume()
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok", "data": {"bot_state": bot.state.value}}


@router.post("/stop")
async def stop_bot(request: Request):
    bot = request.app.state.bot_engine
    try:
        await bot.stop()
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok", "data": {"bot_state": bot.state.value}}


@router.post("/manual-buy")
async def manual_buy(request: Request):
    bot = request.app.state.bot_engine
    client = request.app.state.binance_client
    config = request.app.state.config
    try:
        await bot.manual_buy(config)
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok", "message": "Manual buy executed"}


@router.post("/manual-sell")
async def manual_sell(request: Request):
    bot = request.app.state.bot_engine
    client = request.app.state.binance_client
    try:
        await bot.manual_sell(config)
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok", "message": "Manual sell executed"}
