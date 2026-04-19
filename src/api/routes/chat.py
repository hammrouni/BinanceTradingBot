"""
Chat endpoint — conversational interface backed by your LLM + MCP tools.

Reads LLM_BASE_URL / LLM_MODEL / LLM_API_KEY from .env — works with
Groq, Ollama, or any OpenAI-compatible endpoint.

POST /api/v1/chat/message
  Body:  {"message": "...", "history": [{"role": "user"|"assistant", "content": "..."}]}
  Reply: {"response": "...", "tools_used": [...]}

Available tools:
  get_bot_status      — live state, price, RSI, open position
  get_config          — full trading config
  update_config       — change one config field
  get_recent_trades   — trade history with P&L
  get_pnl_summary     — aggregated P&L stats
  get_balances        — wallet balances (USDT + asset)
  get_market_summary  — recent price/RSI history
  start_bot           — start the bot
  pause_bot           — pause the bot
  resume_bot          — resume the bot
  stop_bot            — stop the bot
  manual_buy          — execute a manual buy
  manual_sell         — execute a manual sell (closes open position)
"""
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/chat", tags=["chat"])

# ─── Tool schemas (OpenAI function-calling format) ────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_bot_status",
            "description": (
                "Get live bot status: running/paused state, current price, RSI value, "
                "open position details (entry price, quantity, stop-loss, take-profit)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_config",
            "description": "Get the full current trading configuration.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_trades",
            "description": (
                "Get recent trade history (newest first). "
                "Each trade includes direction, price, quantity, P&L, fees, and reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of trades to return (max 50, default 10)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pnl_summary",
            "description": (
                "Get aggregated P&L statistics: total realized P&L, win rate, "
                "number of wins/losses, total fees paid, and best/worst trade."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent trades to include (default 50)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_balances",
            "description": "Get current wallet balances: USDT and the trading asset (e.g. BTC).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_summary",
            "description": (
                "Get a summary of recent market data: last N price/RSI data points, "
                "price range (high/low), and current trend direction."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "points": {
                        "type": "integer",
                        "description": "Number of recent data points to include (default 30, max 200)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_open_position_pnl",
            "description": (
                "Get the live unrealized P&L for the current open position: "
                "entry price, current price, quantity, gross P&L in USD and %."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_levels",
            "description": (
                "Get all active price levels: entry price, stop-loss price, "
                "take-profit price, and BC buy price if in BC mode."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_uptime",
            "description": "Get bot uptime in seconds and human-readable format.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rsi_threshold_history",
            "description": (
                "Get the history of RSI threshold changes (oversold/overbought). "
                "Shows when thresholds were modified and what values were set."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Filter by 'oversold' or 'overbought'. Omit for both.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trade_breakdown_by_reason",
            "description": (
                "Get trade statistics grouped by trigger reason: "
                "buy_signal, bc_signal, stop_loss, take_profit, manual, etc. "
                "Shows count and total P&L per reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent trades to analyze (default 100)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_logs",
            "description": (
                "Get recent bot log entries. Useful for diagnosing errors or "
                "understanding recent bot activity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "description": "Filter by log level: ERROR, WARNING, INFO. Omit for all.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of log entries to return (default 20, max 100)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_rss_feed",
            "description": (
                "Fetch and parse a live RSS/Atom news feed. Returns recent articles "
                "with title, link, published date, and summary. "
                "Built-in feeds: coindesk, cointelegraph, bitcoin_magazine, decrypt, theblock, cryptopanic. "
                "Or pass any full RSS URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url_or_name": {
                        "type": "string",
                        "description": "Short feed name (e.g. 'coindesk') or full RSS URL",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of articles to return (default 10, max 30)",
                    },
                },
                "required": ["url_or_name"],
            },
        },
    },
]

# ─── System prompt ────────────────────────────────────────────────────────────

_BASE_SYSTEM_PROMPT = """\
You are a helpful assistant for BinanceTradingBot — an automated RSI-based crypto trading bot.

You have access to the following tools — USE THEM proactively when relevant:
- get_bot_status: live state, price, RSI, open position
- get_config: full trading configuration
- get_recent_trades: trade history with P&L
- get_pnl_summary: aggregated P&L stats
- get_balances: wallet balances
- get_market_summary: recent price/RSI data
- get_open_position_pnl: unrealized P&L for open position
- get_price_levels: entry, stop-loss, take-profit, BC price
- get_uptime: bot uptime
- get_rsi_threshold_history: RSI threshold change log
- get_trade_breakdown_by_reason: trades grouped by trigger
- get_recent_logs: recent bot log entries
- read_rss_feed: fetch live crypto news from RSS feeds (coindesk, cointelegraph, bitcoin_magazine, decrypt, theblock, cryptopanic)

When the user asks about news, crypto news, market news, or any feed — ALWAYS call read_rss_feed.
Do NOT say you cannot fetch news. You have the read_rss_feed tool and must use it.

Trading modes:
- RSI mode: buys when RSI < oversold threshold, sells when RSI > overbought or TP/SL hit
- BC Price mode: buys all available USDT when price drops below min_bc_price

Be concise and accurate. Round numbers to reasonable precision.
"""

_LANG_INSTRUCTIONS = {
    "EN": "",
    "FR": "\n\nLANGUAGE: Respond entirely in French.",
    "AR": "\n\nLANGUAGE: Respond entirely in Arabic.",
}


def _build_system_prompt(language: str) -> str:
    lang = language.upper() if language else "EN"
    return _BASE_SYSTEM_PROMPT + _LANG_INSTRUCTIONS.get(lang, "")


# ─── Tool execution ───────────────────────────────────────────────────────────

async def _execute_tool(name: str, inputs: dict, request: Request) -> Any:
    bot = getattr(request.app.state, "bot_engine", None)
    # Always reload config from disk — ensures dashboard changes are reflected immediately
    from src.core.config_manager import load_config
    config = load_config()
    request.app.state.config = config  # keep app state in sync

    # ── Read: bot status ─────────────────────────────────────────────────────
    if name == "get_bot_status":
        if bot is None:
            return {"error": "Bot engine not available"}
        history = list(bot.market_history)
        last = history[-1] if history else {}
        return {
            "state": getattr(bot, "state", "UNKNOWN"),
            "current_price": last.get("price"),
            "current_rsi": last.get("rsi"),
            "open_position": bot.open_position.model_dump() if bot.open_position else None,
            "stop_loss_price": getattr(bot, "_stop_loss_price", None),
            "take_profit_price": getattr(bot, "_take_profit_price", None),
        }

    # ── Read: config ─────────────────────────────────────────────────────────
    elif name == "get_config":
        return config.model_dump()

    # ── Read: recent trades ──────────────────────────────────────────────────
    elif name == "get_recent_trades":
        from src.mcp_server.tools import tool_get_recent_trades
        return tool_get_recent_trades(limit=int(inputs.get("limit", 10)))

    # ── Read: P&L summary ────────────────────────────────────────────────────
    elif name == "get_pnl_summary":
        from src.mcp_server.tools import tool_get_recent_trades
        limit = int(inputs.get("limit", 50))
        trades = tool_get_recent_trades(limit=limit)
        sells = [t for t in trades if t.get("direction") == "sell" and t.get("pnl_usd") is not None]
        if not sells:
            return {"message": "No completed trades with P&L data found."}
        total_pnl = sum(t["pnl_usd"] for t in sells)
        total_fees = sum(t.get("fee_usd", 0) for t in trades)
        wins  = [t for t in sells if t["pnl_usd"] > 0]
        losses = [t for t in sells if t["pnl_usd"] <= 0]
        best  = max(sells, key=lambda t: t["pnl_usd"])
        worst = min(sells, key=lambda t: t["pnl_usd"])
        return {
            "trades_analyzed": len(sells),
            "total_pnl_usd": round(total_pnl, 4),
            "total_fees_usd": round(total_fees, 4),
            "net_pnl_usd": round(total_pnl - total_fees, 4),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(len(wins) / len(sells) * 100, 1),
            "best_trade_usd": round(best["pnl_usd"], 4),
            "worst_trade_usd": round(worst["pnl_usd"], 4),
        }

    # ── Read: balances ───────────────────────────────────────────────────────
    elif name == "get_balances":
        if bot is None:
            return {"error": "Bot engine not available"}
        return bot.balances or {"message": "No balance data yet — try refreshing wallet."}

    # ── Read: market summary ─────────────────────────────────────────────────
    elif name == "get_market_summary":
        if bot is None:
            return {"error": "Bot engine not available"}
        points = min(int(inputs.get("points", 30)), 200)
        history = list(bot.market_history)[-points:]
        if not history:
            return {"message": "No market data available yet."}
        prices = [p["price"] for p in history if p.get("price")]
        rsis   = [p["rsi"]   for p in history if p.get("rsi")]
        latest = history[-1]
        return {
            "data_points": len(history),
            "latest_price": latest.get("price"),
            "latest_rsi": latest.get("rsi"),
            "price_high": round(max(prices), 4) if prices else None,
            "price_low":  round(min(prices), 4) if prices else None,
            "rsi_high":   round(max(rsis),   2) if rsis   else None,
            "rsi_low":    round(min(rsis),   2) if rsis   else None,
            "trend": (
                "up"   if len(prices) >= 2 and prices[-1] > prices[0] else
                "down" if len(prices) >= 2 and prices[-1] < prices[0] else
                "flat"
            ),
        }

    # ── Live unrealized P&L ──────────────────────────────────────────────────
    elif name == "get_open_position_pnl":
        if bot is None:
            return {"error": "Bot engine not available"}
        if not bot.open_position:
            return {"message": "No open position."}
        history = list(bot.market_history)
        current_price = history[-1]["price"] if history else None
        if current_price is None:
            return {"error": "No current price available."}
        pos = bot.open_position
        gross_pnl = (current_price - pos.price) * pos.quantity
        pnl_pct   = (current_price - pos.price) / pos.price * 100
        return {
            "pair": pos.pair,
            "entry_price": pos.price,
            "current_price": current_price,
            "quantity": pos.quantity,
            "gross_pnl_usd": round(gross_pnl, 4),
            "pnl_pct": round(pnl_pct, 3),
            "stop_loss_price": getattr(bot, "_stop_loss_price", None),
            "take_profit_price": getattr(bot, "_take_profit_price", None),
        }

    # ── Price levels ─────────────────────────────────────────────────────────
    elif name == "get_price_levels":
        if bot is None:
            return {"error": "Bot engine not available"}
        cfg = config.model_dump()
        history = list(bot.market_history)
        current_price = history[-1]["price"] if history else None
        return {
            "current_price": current_price,
            "entry_price": bot.open_position.price if bot.open_position else None,
            "stop_loss_price": getattr(bot, "_stop_loss_price", None),
            "take_profit_price": getattr(bot, "_take_profit_price", None),
            "bc_buy_price": cfg.get("min_bc_price") or cfg.get("bc_buy_price"),
        }

    # ── Uptime ───────────────────────────────────────────────────────────────
    elif name == "get_uptime":
        if bot is None:
            return {"error": "Bot engine not available"}
        seconds = bot.get_uptime_seconds() or 0
        h, rem = divmod(int(seconds), 3600)
        m, s   = divmod(rem, 60)
        return {
            "uptime_seconds": int(seconds),
            "uptime_human": f"{h}h {m}m {s}s" if h else f"{m}m {s}s",
            "bot_state": getattr(bot, "state", "UNKNOWN"),
        }

    # ── RSI threshold history ────────────────────────────────────────────────
    elif name == "get_rsi_threshold_history":
        from src.services.rsi_history_service import get_rsi_threshold_history
        threshold_type = inputs.get("type")  # "oversold" / "overbought" / None
        entries = get_rsi_threshold_history(threshold_type)
        return [e.model_dump() for e in entries]

    # ── Trade breakdown by reason ────────────────────────────────────────────
    elif name == "get_trade_breakdown_by_reason":
        from src.mcp_server.tools import tool_get_recent_trades
        limit  = int(inputs.get("limit", 100))
        trades = tool_get_recent_trades(limit=limit)
        breakdown: dict[str, dict] = {}
        for t in trades:
            reason = t.get("reason") or "unknown"
            if reason not in breakdown:
                breakdown[reason] = {"count": 0, "pnl_usd": 0.0, "direction_counts": {}}
            breakdown[reason]["count"] += 1
            breakdown[reason]["pnl_usd"] += t.get("pnl_usd") or 0.0
            d = t.get("direction", "unknown")
            breakdown[reason]["direction_counts"][d] = (
                breakdown[reason]["direction_counts"].get(d, 0) + 1
            )
        # Round P&L values
        for v in breakdown.values():
            v["pnl_usd"] = round(v["pnl_usd"], 4)
        return breakdown

    # ── Recent logs ──────────────────────────────────────────────────────────
    elif name == "get_recent_logs":
        import re
        from pathlib import Path
        limit       = min(int(inputs.get("limit", 20)), 100)
        level_filter = inputs.get("level", "").upper() or None
        log_paths = [Path("logs/bot.log"), Path("../logs/bot.log")]
        log_file  = next((p for p in log_paths if p.exists()), None)
        if not log_file:
            return {"error": "Log file not found"}
        pattern = re.compile(
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - "
            r"(?P<name>[\w\.]+) - (?P<level>\w+) - (?P<message>.+)$"
        )
        entries = []
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
        except Exception as e:
            return {"error": str(e)}
        for line in reversed(lines):
            m = pattern.match(line.strip())
            if not m:
                continue
            if level_filter and m.group("level") != level_filter:
                continue
            entries.append({
                "timestamp": m.group("timestamp"),
                "level": m.group("level"),
                "logger": m.group("name"),
                "message": m.group("message"),
            })
            if len(entries) >= limit:
                break
        return entries

    # ── RSS feed ─────────────────────────────────────────────────────────────
    elif name == "read_rss_feed":
        from src.mcp_server.tools import tool_read_rss_feed
        return tool_read_rss_feed(
            url_or_name=inputs.get("url_or_name", "coindesk"),
            limit=int(inputs.get("limit", 10)),
        )

    return {"error": f"Unknown tool: {name}"}


# ─── Request / Response models ────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/message")
async def chat_message(body: ChatRequest, request: Request):
    llm_settings = getattr(request.app.state, "settings", None)
    if llm_settings is None:
        raise HTTPException(status_code=503, detail="Settings not loaded — check .env")
    base_url = llm_settings.llm_base_url
    model    = llm_settings.llm_model
    api_key  = llm_settings.llm_api_key
    timeout    = llm_settings.llm_timeout
    max_tokens = llm_settings.llm_max_tokens

    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="openai package not installed. Run: pip install openai",
        )

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    # Pick language from running config
    config = getattr(request.app.state, "config", None)
    language = getattr(config, "agent_language", "EN") if config else "EN"
    system_prompt = _build_system_prompt(language)

    # Build message history
    messages = [{"role": "system", "content": system_prompt}]
    for m in body.history:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": body.message})

    tools_used = []
    tools_supported = True  # assume supported until proven otherwise

    # Agentic tool-use loop (max 5 rounds)
    for _ in range(5):
        try:
            kwargs: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7}
            if tools_supported:
                kwargs["tools"] = TOOLS
                kwargs["tool_choice"] = "auto"
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            # Some models / providers don't support tool calling — retry without tools
            error_str = str(e).lower()
            if "tool" in error_str or "function" in error_str or "not supported" in error_str:
                tools_supported = False
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.7,
                )
            else:
                raise HTTPException(status_code=502, detail=f"LLM error: {e}")

        choice = response.choices[0]
        msg = choice.message

        # No tool calls — return final text
        if not msg.tool_calls:
            return JSONResponse(
                content={"response": msg.content or "", "tools_used": tools_used}
            )

        # Execute each tool call
        messages.append(msg)
        for tc in msg.tool_calls:
            tools_used.append(tc.function.name)
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await _execute_tool(tc.function.name, args, request)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    # Loop exhausted
    return JSONResponse(
        content={
            "response": "I had trouble processing that request. Please try again.",
            "tools_used": tools_used,
        }
    )
