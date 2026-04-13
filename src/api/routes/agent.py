from typing import Any
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
import os
from src.core.trade_reader import read_trades

router = APIRouter(prefix="/agent", tags=["agent"])

AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://localhost:8090")

async def _call_agent_service(agent_id: str, payload: dict, language: str = "EN", theme: str = "technical") -> JSONResponse:
    try:
        payload["language"] = language
        payload["theme"] = theme
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{AGENT_SERVICE_URL}/api/agents/{agent_id}/analyze",
                json=payload,
            )

        if resp.status_code != 200:
            return JSONResponse(
                content={"error": f"Agent service error ({resp.status_code}): {resp.text[:200]}"},
                status_code=resp.status_code
            )

        return JSONResponse(content=resp.json())

    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Agent service unavailable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Agent service timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trading/analyze")
async def proxy_trading_analyze(request: Request):
    """Legacy endpoint for the main trading advisor."""
    body = await request.json()
    config = request.app.state.config
    language = getattr(config, 'agent_language', 'EN')
    theme = getattr(config, 'agent_theme', 'technical')
    body["language"] = language
    body["theme"] = theme
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{AGENT_SERVICE_URL}/api/agents/trading/analyze",
                json=body,
            )
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/trade-health/analyze")
async def trade_health_analyze(request: Request):
    bot = request.app.state.bot_engine
    config = request.app.state.config
    language = getattr(config, 'agent_language', 'EN')
    theme = getattr(config, 'agent_theme', 'technical')

    if not bot.open_position:
        return JSONResponse(content={
            "verdict": "NONE",
            "confidence": 0,
            "drawdown_vs_atr": "N/A",
            "reasoning": "No open position to analyze."
        })

    history = list(bot.market_history)
    current_price = history[-1]["price"] if history else bot.open_position.price
    pnl_usd = (current_price - bot.open_position.price) * bot.open_position.quantity
    pnl_pct = (pnl_usd / (bot.open_position.price * bot.open_position.quantity)) * 100 if bot.open_position.price else 0

    recent_trades = read_trades(limit=10)

    payload = {
        "current_pnl_usd": round(pnl_usd, 2),
        "current_pnl_pct": round(pnl_pct, 2),
        "entry_price": bot.open_position.price,
        "current_price": current_price,
        "candles_24h": history[-1440:], # Last 24h
        "recent_trades": [t.model_dump() for t in recent_trades]
    }
    return await _call_agent_service("trade-health", payload, language, theme)

@router.post("/config-auditor/analyze")
async def config_auditor_analyze(request: Request):
    try:
        bot = request.app.state.bot_engine
        config = request.app.state.config
        language = getattr(config, 'agent_language', 'EN')
        theme = getattr(config, 'agent_theme', 'technical')

        history = list(bot.market_history)
        current_price = history[-1]["price"] if history else 0
        current_rsi = history[-1].get("rsi") if history else None

        vol_pct = 0
        if len(history) > 10:
            prices = [c["price"] for c in history[-60:]]
            vol_pct = ((max(prices) - min(prices)) / min(prices)) * 100

        payload = {
            "active_strategy": getattr(config, 'active_modes', ['RSI'])[0],
            "rsi_oversold": config.rsi_oversold,
            "rsi_overbought": config.rsi_overbought,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "current_rsi": current_rsi,
            "volatility_24h_pct": round(vol_pct, 2),
            "candle_pattern": "sideways" if vol_pct < 0.5 else "volatile",
            "rsi_threshold_history": []
        }
        return await _call_agent_service("config-auditor", payload, language, theme)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@router.post("/fee-watchdog/analyze")
async def fee_watchdog_analyze(request: Request):
    try:
        config = request.app.state.config
        language = getattr(config, 'agent_language', 'EN')
        theme = getattr(config, 'agent_theme', 'technical')
        trades = read_trades(limit=50)

        total_fees = sum(getattr(t, 'fee', None) or 0 for t in trades)
        total_pnl = sum(t.pnl_usd or 0 for t in trades)
        manual_count = len([t for t in trades if getattr(t, 'reason', None) == "manual"])

        payload = {
            "trades": [t.model_dump() for t in trades],
            "total_fees_usd": round(total_fees, 2),
            "total_pnl_usd": round(total_pnl, 2),
            "trade_size_usd": config.trade_amount_usd,
            "manual_trade_count": manual_count,
            "avg_fee_per_trade": round(total_fees / len(trades), 4) if trades else 0
        }
        return await _call_agent_service("fee-watchdog", payload, language, theme)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@router.post("/sltp-optimizer/analyze")
async def sltp_optimizer_analyze(request: Request):
    try:
        bot = request.app.state.bot_engine
        config = request.app.state.config
        language = getattr(config, 'agent_language', 'EN')
        theme = getattr(config, 'agent_theme', 'technical')

        history = list(bot.market_history)
        current_price = history[-1]["price"] if history else 0

        payload = {
            "take_profit_price": bot._take_profit_price,
            "stop_loss_price": bot._stop_loss_price,
            "current_price": current_price,
            "candles_24h": history[-1440:],
            "entry_price": bot.open_position.price if bot.open_position else None,
            "active_strategy": getattr(config, 'active_modes', ['RSI'])[0]
        }
        return await _call_agent_service("sltp-optimizer", payload, language, theme)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@router.post("/liquidity-scout/analyze")
async def liquidity_scout_analyze(request: Request):
    try:
        bot = request.app.state.bot_engine
        config = request.app.state.config
        language = getattr(config, 'agent_language', 'EN')
        theme = getattr(config, 'agent_theme', 'technical')
        client = request.app.state.binance_client

        history = list(bot.market_history)
        current_price = history[-1]["price"] if history else 0
        symbol = config.trading_pair

        try:
            book = await client.client.get_order_book(symbol=symbol, limit=20)
            ticker = await client.client.get_ticker(symbol=symbol)
        except Exception as e:
            return JSONResponse(content={"error": f"Binance API error: {str(e)}"}, status_code=502)

        payload = {
            "symbol": symbol,
            "trade_size_usd": config.trade_amount_usd,
            "order_book_depth": book,
            "current_price": current_price,
            "24h_volume_usd": float(ticker.get("quoteVolume", 0))
        }
        return await _call_agent_service("liquidity-scout", payload, language, theme)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
