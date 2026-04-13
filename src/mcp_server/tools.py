"""
MCP tool helper functions — file-based data access.
Used by both the MCP server (external clients) and the chat endpoint (in-process).
"""
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
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


def tool_update_config(field: str, value: Any) -> dict:
    """
    Update a single trading config field and persist it.
    Returns updated config or an error dict.
    """
    from src.core.config_manager import load_config, save_config
    from src.models.config import TradingConfig

    allowed = set(TradingConfig.model_fields.keys())
    if field not in allowed:
        return {"error": f"Unknown config field '{field}'. Allowed: {sorted(allowed)}"}

    try:
        config = load_config()
        data = config.model_dump()
        data[field] = value
        new_config = TradingConfig(**data)
        save_config(new_config)
        return {"success": True, "updated": {field: value}}
    except Exception as e:
        return {"error": str(e)}


def tool_get_recent_trades(limit: int = 10) -> list:
    """Read recent trades from trades.jsonl (newest first)."""
    if not TRADES_PATH.exists():
        return []
    records = []
    try:
        lines = TRADES_PATH.read_text().splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(records) >= limit:
                break
    except Exception:
        pass
    return records


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities from a string."""
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = (text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return " ".join(text.split())  # collapse whitespace


def tool_read_rss_feed(url_or_name: str, limit: int = 10) -> list | dict:
    """
    Fetch and parse an RSS/Atom feed. Returns a list of items with
    title, link, published, and summary.

    `url_or_name` can be:
      - A short name from KNOWN_FEEDS (e.g. "coindesk", "cointelegraph")
      - Any full RSS/Atom URL
    """
    import httpx

    url = KNOWN_FEEDS.get(url_or_name.lower().strip(), url_or_name)
    limit = min(limit, 30)

    try:
        resp = httpx.get(
            url, timeout=12, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BinanceTradingBot/1.0)"},
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
