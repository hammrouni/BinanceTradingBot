"""
MCP tool helper functions — file-based data access.
Used by both the MCP server (external clients) and the chat endpoint (in-process).
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Well-known crypto RSS feeds available by short name
KNOWN_FEEDS: dict[str, str] = {
    "coindesk":        "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml",
    "cointelegraph":   "https://cointelegraph.com/rss",
    "bitcoin_magazine":"https://bitcoinmagazine.com/feed",
    "decrypt":         "https://decrypt.co/feed",
    "theblock":        "https://www.theblock.co/rss.xml",
    "cryptopanic":     "https://cryptopanic.com/news/rss/",
}

CONFIG_PATH = Path("data/config.json")
TRADES_PATH = Path("data/trades.jsonl")
BOT_STATE_PATH = Path("data/bot_state.json")


def tool_get_config() -> dict:
    """Read current trading config from disk."""
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text())


_app = None


def bind_app(app) -> None:
    """Give the tools access to the running FastAPI app (set once from main.py)."""
    global _app
    _app = app


async def tool_update_config(field: str, value: Any) -> dict:
    """Update a single config field through the same service as PUT /config
    (validation, live config update, SL/TP refresh, RSI threshold history)."""
    if _app is None:
        return {"error": "Config service unavailable: app not bound"}
    from src.services.config_service import update_config_field
    return await update_config_field(field, value, _app)


def tool_get_recent_trades(limit: int = 10) -> list:
    """Recent trades (newest first) with pnl_usd computed by calculate_pnl (net of fees).

    PnL is paired over the whole log first, so limiting never breaks buy/sell pairing.
    """
    from src.core.pnl_calculator import calculate_pnl
    from src.core.trade_reader import read_trades

    all_trades = read_trades(limit=10**9)  # newest first
    return [t.model_dump() for t in calculate_pnl(all_trades)[:limit]]


def tool_get_pnl_summary(limit: int = 50) -> dict:
    """Aggregated P&L over the last `limit` trades. pnl_usd is already net of fees."""
    trades = tool_get_recent_trades(limit=limit)
    sells = [t for t in trades if t.get("direction") == "sell" and t.get("pnl_usd") is not None]
    if not sells:
        return {"message": "No completed trades with P&L data found."}
    total_pnl = sum(t["pnl_usd"] for t in sells)
    total_fees = sum(t.get("fee_usd") or 0 for t in trades)
    wins = [t for t in sells if t["pnl_usd"] > 0]
    best = max(sells, key=lambda t: t["pnl_usd"])
    worst = min(sells, key=lambda t: t["pnl_usd"])
    return {
        "trades_analyzed": len(sells),
        "total_pnl_usd": round(total_pnl, 4),
        "total_fees_usd": round(total_fees, 4),
        "net_pnl_usd": round(total_pnl, 4),  # fees already deducted by calculate_pnl
        "wins": len(wins),
        "losses": len(sells) - len(wins),
        "win_rate_pct": round(len(wins) / len(sells) * 100, 1),
        "best_trade_usd": round(best["pnl_usd"], 4),
        "worst_trade_usd": round(worst["pnl_usd"], 4),
    }


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities from a string."""
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = (text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return " ".join(text.split())  # collapse whitespace


async def tool_read_rss_feed(url_or_name: str, limit: int = 10) -> list | dict:
    """
    Fetch and parse an RSS/Atom feed. Returns a list of items with
    title, link, published, and summary.

    `url_or_name` can be:
      a short name from KNOWN_FEEDS (e.g. "coindesk", "cointelegraph").
    Arbitrary URLs are refused (SSRF / prompt-injection surface).
    """
    import httpx

    name = (url_or_name or "").lower().strip()
    url = KNOWN_FEEDS.get(name)
    if url is None:
        return {"error": f"Unknown feed '{url_or_name}'. Use one of: {', '.join(KNOWN_FEEDS)}"}
    limit = max(1, min(limit, 30))

    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            resp = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; BinanceTradingBot/1.0)"},
            )
        resp.raise_for_status()
    except Exception as e:
        return {"error": f"Failed to fetch feed: {e}", "url": url}

    # Content-type check — reject obvious HTML pages (not feeds)
    ct = resp.headers.get("content-type", "")
    if "html" in ct and "xml" not in ct and "rss" not in ct and "atom" not in ct:
        return {"error": "URL returned an HTML page, not an RSS/Atom feed.", "url": url}

    try:
        root = ET.fromstring(resp.content)  # bytes — avoids encoding issues
    except ET.ParseError as e:
        return {"error": f"Failed to parse XML: {e}", "url": url}

    # Detect namespace prefix for Atom feeds (e.g. "{http://www.w3.org/2005/Atom}")
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag[: root.tag.index("}") + 1]

    items: list[dict] = []

    # ── RSS 2.0 / RSS 1.0 ────────────────────────────────────────────────────
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item")[:limit]:
            title   = _strip_html(item.findtext("title") or "")
            link    = (item.findtext("link") or "").strip()
            pub     = (item.findtext("pubDate") or "").strip()
            summary = _strip_html(item.findtext("description") or "")
            items.append({"title": title, "link": link, "published": pub, "summary": summary[:300]})

    # ── Atom ─────────────────────────────────────────────────────────────────
    elif "feed" in root.tag:
        for entry in root.findall(f"{ns}entry")[:limit]:
            title   = _strip_html(entry.findtext(f"{ns}title") or "")
            link_el = entry.find(f"{ns}link")
            link    = (link_el.get("href", "") if link_el is not None else "").strip()
            pub     = (entry.findtext(f"{ns}published")
                       or entry.findtext(f"{ns}updated") or "").strip()
            summary = _strip_html(
                entry.findtext(f"{ns}summary") or entry.findtext(f"{ns}content") or ""
            )
            items.append({"title": title, "link": link, "published": pub, "summary": summary[:300]})

    if not items:
        return {
            "error": "No items found. Feed may be empty or use an unsupported format.",
            "url": url,
        }

    return items


def tool_get_bot_state() -> dict:
    """Read last-saved bot state from disk (snapshot, not live)."""
    if not BOT_STATE_PATH.exists():
        return {"state": "UNKNOWN"}
    try:
        return json.loads(BOT_STATE_PATH.read_text())
    except Exception:
        return {"state": "UNKNOWN"}
