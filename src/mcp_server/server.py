"""
MCP Server for BinanceTradingBot.

Exposes trading config, bot state, and trade history as MCP tools.
Mount this in FastAPI at /mcp to allow external MCP clients (e.g. Claude Desktop)
to connect via SSE transport at:
  http://localhost:8000/mcp/sse

Usage in Claude Desktop (claude_desktop_config.json):
  {
    "mcpServers": {
      "trading-bot": {
        "command": "curl",
        "args": ["-N", "http://localhost:8000/mcp/sse"]
      }
    }
  }
"""
from mcp.server.fastmcp import FastMCP

from src.mcp_server.tools import (
    KNOWN_FEEDS,
    tool_get_bot_state,
    tool_get_config,
    tool_get_recent_trades,
    tool_read_rss_feed,
    tool_update_config,
)

mcp = FastMCP("BinanceTradingBot")


@mcp.tool()
def get_bot_status() -> dict:
    """
    Get current bot status: running state, open position, stop-loss and
    take-profit prices. Note: this reads the last-saved snapshot from disk,
    not the live in-memory state.
    """
    return tool_get_bot_state()


@mcp.tool()
def get_trading_config() -> dict:
    """Get the current trading configuration (all fields)."""
    return tool_get_config()


@mcp.tool()
def update_trading_config(field: str, value: str | int | float | bool | None) -> dict:
    """
    Update a single trading config field.

    Common fields:
      trading_pair, trade_amount_usd, rsi_oversold, rsi_overbought,
      stop_loss_pct, take_profit_pct, min_bc_price, active_modes

    Returns {"success": true, "updated": {field: value}} or {"error": "..."}.
    """
    return tool_update_config(field, value)


@mcp.tool()
def get_recent_trades(limit: int = 10) -> list:
    """
    Get the most recent trades (newest first).
    Each trade includes: direction, amount_usd, entry_price, quantity,
    executed_at, reason, pnl_usd, fee_usd, is_test.
    """
    return tool_get_recent_trades(limit=min(limit, 50))


@mcp.tool()
def read_rss_feed(url_or_name: str = "coindesk", limit: int = 10) -> list | dict:
    f"""
    Fetch and parse an RSS/Atom feed. Returns title, link, published date,
    and a short summary for each item.

    Built-in feeds (use the short name):
      {", ".join(KNOWN_FEEDS.keys())}

    Or pass any full RSS URL directly.
    """
    return tool_read_rss_feed(url_or_name=url_or_name, limit=limit)
