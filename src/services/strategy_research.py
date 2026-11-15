"""strategy_research.py — AI strategy optimizer behind the simulator's "AI Optimizer" card.

Pipeline (all of it advisory; nothing is ever applied to the live config automatically):
  1. fetch N days of 1m candles for the pair;
  2. build candidates: a grid for RSI / RSI Ultra / BC, plus candidates the LLM proposes after
     reading web-search snippets (the snippets are untrusted text, only used as hints);
  3. replay EVERY candidate with fees on many separate day-windows through the bot's own replay
     harness; the LLM's ideas get no shortcut, the backtest decides;
  4. rank on the early windows, check on the later hold-out windows, and give a verdict;
  5. the LLM explains the verdict in plain words (it cannot change the numbers).
"""
from __future__ import annotations

import asyncio
import html
import itertools
import os
import re
import statistics
import time
import uuid
from typing import Any

import httpx

from src.core.replay import causal_reference, config_for_sim, replay, valid_rows
from src.services.history_loader import compute_ultra_series, load_market_history
from src.utils.logger import get_logger

logger = get_logger(__name__)

AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "http://localhost:8090")
AGENT_ID = "strategy-researcher"
BALANCE_FACTOR = 10          # replay balance = trade size x 10, so a losing streak never starves the run
HOLDOUT_SHARE = 0.3
MAX_LLM_CANDIDATES = 8

# Allowed range per parameter: LLM output is clamped to these, unknown keys are dropped.
BOUNDS: dict[str, tuple[float, float, bool]] = {   # key: (min, max, is_int)
    "rsi_oversold": (5, 45, True), "rsi_overbought": (55, 95, True),
    "stop_loss_pct": (0.3, 10, False), "take_profit_pct": (0.5, 10, False), "trailing_stop_pct": (0.3, 5, False),
    "rsi_ultra_period": (5, 50, True), "rsi_ultra_signal_period": (3, 30, True), "rsi_ultra_zone_mid": (30, 70, False),
    "bc_buy_offset_pct": (0.3, 10, False), "bc_sell_offset_pct": (0.3, 10, False),
    "ema_fast_period": (2, 100, True), "ema_slow_period": (3, 300, True),
    "bear_trend_candles": (3, 500, True), "bear_trend_pct": (0.1, 20, False),
    "ma_filter_period": (2, 500, True), "price_bounce_ticks": (1, 20, True),
}
MODE_KEYS = {
    "rsi": ("rsi_oversold", "rsi_overbought"),
    "rsi_ultra": ("rsi_ultra_period", "rsi_ultra_signal_period", "rsi_ultra_zone_mid"),
    "bc": ("bc_buy_offset_pct", "bc_sell_offset_pct"),
}
COMMON_KEYS = ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct")
FILTER_KEYS = ("ema_fast_period", "ema_slow_period", "bear_trend_candles", "bear_trend_pct",
               "ma_filter_period", "price_bounce_ticks")
RESULT_KEYS = tuple(BOUNDS)


# ── Candidates ────────────────────────────────────────────────────────────────

def grid_candidates(modes: list[str]) -> list[dict]:
    """Deterministic search grid (kept small: every candidate is replayed on every window)."""
    out: list[dict] = []
    if "rsi" in modes:
        filters = [{}, {"ema_fast_period": 20, "ema_slow_period": 50}, {"bear_trend_candles": 30, "bear_trend_pct": 0.5}]
        for (os_, ob, sl, tp), f in itertools.product(
                itertools.product((15, 20, 25, 30), (65, 75, 85), (1.0, 2.0, 3.0), (0.8, 1.2, 2.0, 3.0)), filters):
            out.append({"mode": "rsi", "source": "grid", "params": {
                "rsi_oversold": os_, "rsi_overbought": ob, "stop_loss_pct": sl, "take_profit_pct": tp, **f}})
    if "rsi_ultra" in modes:
        for p, s, mid, sl, tp in itertools.product((7, 14, 21), (5, 9, 13), (40, 50), (1.0, 2.0), (0.8, 1.5, 3.0)):
            out.append({"mode": "rsi_ultra", "source": "grid", "params": {
                "rsi_ultra_period": p, "rsi_ultra_signal_period": s, "rsi_ultra_zone_mid": mid,
                "stop_loss_pct": sl, "take_profit_pct": tp}})
    if "bc" in modes:
        for b, s, sl, tp in itertools.product((1.0, 2.0, 3.0), (1.0, 2.0, 3.0), (1.0, 2.0), (0.8, 1.5, 3.0)):
            out.append({"mode": "bc", "source": "grid", "params": {
                "bc_buy_offset_pct": b, "bc_sell_offset_pct": s, "stop_loss_pct": sl, "take_profit_pct": tp}})
    return out


def sanitize_candidate(raw: Any, modes: list[str]) -> dict | None:
    """One LLM-proposed candidate -> a clamped, whitelisted candidate, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode", "")).lower().replace(" ", "_")
    if mode not in MODE_KEYS or mode not in modes:
        return None
    params: dict[str, float] = {}
    for key in (*MODE_KEYS[mode], *COMMON_KEYS, *(FILTER_KEYS if mode != "bc" else ())):
        v = raw.get(key)
        if v is None or isinstance(v, bool):
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v != v:   # NaN
            continue
        lo, hi, is_int = BOUNDS[key]
        v = min(hi, max(lo, v))
        params[key] = int(round(v)) if is_int else round(v, 2)
    if any(k not in params for k in (*MODE_KEYS[mode], "stop_loss_pct", "take_profit_pct")):
        return None
    if mode == "rsi" and params["rsi_oversold"] >= params["rsi_overbought"]:
        return None
    # A filter needs all its parts, otherwise drop it.
    if ("ema_fast_period" in params) != ("ema_slow_period" in params) or \
            params.get("ema_fast_period", 0) >= params.get("ema_slow_period", 1e9):
        params.pop("ema_fast_period", None)
        params.pop("ema_slow_period", None)
    if ("bear_trend_candles" in params) != ("bear_trend_pct" in params):
        params.pop("bear_trend_candles", None)
        params.pop("bear_trend_pct", None)
    return {"mode": mode, "source": "web-ai", "params": params,
            "note": str(raw.get("reason", ""))[:200]}


def _dedupe(cands: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cands:
        key = (c["mode"], tuple(sorted(c["params"].items())))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


# ── Web research (fixed provider endpoints only; never fetches arbitrary URLs) ───────

_TAG = re.compile(r"<[^>]+>")
SEARCH_QUERIES = (
    "RSI crypto trading strategy best oversold overbought settings stop loss take profit backtest",
    "long only spot RSI strategy fees stop loss take profit crypto scalping backtest results",
)
STACKEXCHANGE_QUERIES = ("RSI strategy backtest overfitting", "RSI mean reversion crypto trend filter", "stop loss take profit fees backtest")


def _clean(text: str, limit: int) -> str:
    text = html.unescape(_TAG.sub("", text or ""))
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _domain(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0][:60]


async def _brave(client: httpx.AsyncClient, key: str, per_query: int) -> list[dict]:
    out = []
    for q in SEARCH_QUERIES:
        r = await client.get("https://api.search.brave.com/res/v1/web/search",
                             params={"q": q, "count": per_query},
                             headers={"X-Subscription-Token": key, "Accept": "application/json"})
        if r.status_code != 200:
            logger.warning("Brave search HTTP %s", r.status_code)
            continue
        for it in (r.json().get("web", {}).get("results") or [])[:per_query]:
            out.append({"title": _clean(it.get("title"), 140), "snippet": _clean(it.get("description"), 320),
                        "source": _domain(it.get("url", ""))})
    return out


async def _searxng(client: httpx.AsyncClient, base: str, per_query: int) -> list[dict]:
    """Self-hosted SearXNG (JSON API). The base URL comes from our own config, never from user input."""
    out = []
    for q in SEARCH_QUERIES:
        r = await client.get(f"{base.rstrip('/')}/search", params={"q": q, "format": "json", "language": "en"})
        if r.status_code != 200:
            logger.warning("SearXNG HTTP %s", r.status_code)
            continue
        for it in (r.json().get("results") or [])[:per_query]:
            out.append({"title": _clean(it.get("title"), 140), "snippet": _clean(it.get("content"), 320),
                        "source": _domain(it.get("url", ""))})
    return out


async def _stackexchange(client: httpx.AsyncClient, per_query: int) -> list[dict]:
    """Keyless fallback: quantitative-finance Q&A excerpts from the public Stack Exchange API."""
    out = []
    for q in STACKEXCHANGE_QUERIES:
        r = await client.get("https://api.stackexchange.com/2.3/search/excerpts",
                             params={"order": "desc", "sort": "relevance", "q": q, "site": "quant", "pagesize": per_query})
        if r.status_code != 200:
            continue
        for it in (r.json().get("items") or [])[:per_query]:
            out.append({"title": _clean(it.get("title"), 140), "snippet": _clean(it.get("excerpt"), 320),
                        "source": "quant.stackexchange.com"})
    return out


async def web_search(per_query: int = 4) -> list[dict]:
    """Snippets to inspire candidates. Source, first that is configured and returns something:
    SEARXNG_URL (self-hosted), BRAVE_API_KEY (Brave Search API), then Stack Exchange quant Q&A (keyless).

    Failures just return what was gathered. Text is stripped of markup and control characters.
    """
    searx = os.getenv("SEARXNG_URL", "").strip()
    key = os.getenv("BRAVE_API_KEY", "").strip()
    providers = []
    if searx:
        providers.append(lambda c: _searxng(c, searx, per_query))
    if key:
        providers.append(lambda c: _brave(c, key, per_query))
    providers.append(lambda c: _stackexchange(c, per_query))
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "BinanceTradingBot/1.0"}) as c:
        for provider in providers:
            try:
                results = await provider(c)
            except Exception as e:
                logger.warning("Web research provider failed: %s", e)
                results = []
            if results:
                break
    seen, uniq = set(), []
    for r in results:
        if r["title"] and r["title"] not in seen:
            seen.add(r["title"])
            uniq.append(r)
    return uniq


async def call_agent(payload: dict, timeout: float = 240) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            resp = await c.post(f"{AGENT_SERVICE_URL}/api/agents/{AGENT_ID}/analyze", json=payload)
        if resp.status_code != 200:
            return {"error": f"agent service HTTP {resp.status_code}"}
        data = resp.json()
        return data if isinstance(data, dict) else {"error": "bad agent reply"}
    except Exception as e:
        return {"error": f"agent service unavailable: {type(e).__name__}"}


# ── Evaluation ────────────────────────────────────────────────────────────────

def market_summary(rows: list[dict]) -> dict:
    prices = [r["price"] for r in rows]
    day = 1440
    ranges = [(max(prices[i:i + day]) - min(prices[i:i + day])) / prices[i] * 100
              for i in range(0, len(prices) - day + 1, day)] or [0.0]
    return {
        "days": round(len(rows) / day, 1),
        "price_change_pct": round((prices[-1] / prices[0] - 1) * 100, 2),
        "avg_daily_range_pct": round(statistics.mean(ranges), 2),
        "max_drawdown_from_peak_pct": round(_max_dd(prices), 2),
    }


def _max_dd(prices: list[float]) -> float:
    peak, worst = prices[0], 0.0
    for p in prices:
        peak = max(peak, p)
        worst = max(worst, (peak - p) / peak * 100)
    return worst


def _windows(rows: list[dict]) -> tuple[list[tuple[int, int]], int]:
    size = max(360, min(1440, len(rows) // 5))
    spans = [(i, i + size) for i in range(0, len(rows) - size + 1, size)]
    return spans, max(1, round(len(spans) * (1 - HOLDOUT_SHARE)))


def evaluate(rows: list[dict], candidates: list[dict], fee_pct: float, trade_usd: float, progress=None) -> list[dict]:
    """Replay each candidate on every window (CPU heavy; run in a thread). Returns scored rows."""
    spans, n_train = _windows(rows)
    ref_full = causal_reference(rows)
    ultra_cache: dict[tuple, list[dict]] = {}
    initial = trade_usd * BALANCE_FACTOR
    scored = []
    for n, cand in enumerate(candidates, 1):
        mode, p = cand["mode"], cand["params"]
        data = rows
        if mode == "rsi_ultra":
            key = (p["rsi_ultra_period"], p["rsi_ultra_signal_period"])
            if key not in ultra_cache:
                series = compute_ultra_series(rows, *key)
                ultra_cache[key] = [{**r, "rsi_ultra_raw": a, "rsi_ultra_signal": b} for r, (a, b) in zip(rows, series)]
            data = ultra_cache[key]
        cfg_params = {k: v for k, v in p.items() if k in RESULT_KEYS and k not in ("bc_buy_offset_pct", "bc_sell_offset_pct")}
        cfg = config_for_sim(mode, trade_amount_usd=trade_usd, **cfg_params)
        offsets = (p["bc_buy_offset_pct"], p["bc_sell_offset_pct"]) if mode == "bc" else None
        pnls, trades, dds = [], [], []
        for a, b in spans:
            res = replay(data[a:b], cfg, initial_balance=initial, fee_pct=fee_pct,
                         bc_offsets=offsets, bc_reference=ref_full[a:b] if offsets else None)
            pnls.append((res.final_balance - initial) / trade_usd * 100)
            trades.append(len(res.trades))
            dds.append(res.max_drawdown_pct)
        train, hold = pnls[:n_train], pnls[n_train:]
        scored.append({
            "strategy": mode.upper(), "source": cand["source"], "note": cand.get("note", ""),
            **{k: p[k] for k in RESULT_KEYS if k in p},
            "train_mean_pct": round(statistics.mean(train), 3),
            "train_worst_pct": round(min(train), 3),
            "train_profitable_pct": round(sum(1 for x in train if x > 0) / len(train) * 100),
            "train_trades": sum(trades[:n_train]),
            "holdout_mean_pct": round(statistics.mean(hold), 3) if hold else None,
            "holdout_trades": sum(trades[n_train:]),
            "max_drawdown_pct": round(max(dds), 2),
        })
        if progress and n % 20 == 0:
            progress(n, len(candidates))
    return scored


def rank(scored: list[dict], n_windows_train: int) -> list[dict]:
    """Robust order: mean return on early windows minus a penalty for a bad worst window."""
    need = max(6, n_windows_train)
    for s in scored:
        s["score"] = round(s["train_mean_pct"] - 0.5 * abs(min(s["train_worst_pct"], 0)), 3)
        s["eligible"] = s["train_trades"] >= need
    scored.sort(key=lambda s: (s["eligible"], s["score"]), reverse=True)
    for i, s in enumerate(scored, 1):
        s["rank"] = i
    return scored


def verdict(top: dict | None) -> tuple[str, str]:
    if not top or not top["eligible"]:
        return "NO_EDGE", "No setting traded enough to judge."
    ok = (top["train_mean_pct"] > 0 and top["train_profitable_pct"] >= 55
          and top["holdout_mean_pct"] is not None and top["holdout_mean_pct"] > 0
          and top["holdout_trades"] >= 2)
    if ok:
        return "CANDIDATE", "Profitable on the early windows AND on the unseen later windows. Forward-test on testnet first."
    return "NO_EDGE", "The best setting does not hold up on the unseen later windows (or loses after fees). Do not trade it live."


def attach_bc_prices(rows: list[dict], top: list[dict]) -> None:
    recent = sorted(r["price"] for r in rows[-1440:])
    ref = recent[len(recent) // 2]
    for s in top:
        if s["strategy"] == "BC":
            s["ref_price"] = round(ref, 8)
            s["bc_buy_price"] = round(ref * (1 - s["bc_buy_offset_pct"] / 100), 8)
            s["bc_sell_price"] = round(ref * (1 + s["bc_sell_offset_pct"] / 100), 8)


# ── Job runner ────────────────────────────────────────────────────────────────

JOBS: dict[str, dict] = {}
_tasks: set[asyncio.Task] = set()


def _running() -> bool:
    return any(j["state"] == "running" for j in JOBS.values())


def start_job(settings, pair: str, opts: dict) -> str | None:
    """Start a job; None if one is already running (they are CPU heavy)."""
    if _running():
        return None
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"id": job_id, "state": "running", "phase": "starting", "progress": 0, "pair": pair,
                    "started": time.time(), "warnings": [], "result": None, "error": None}
    for old in sorted(JOBS.values(), key=lambda j: j["started"])[:-5]:
        JOBS.pop(old["id"], None)
    task = asyncio.create_task(_run_job(job_id, settings, pair, opts))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job_id


async def _run_job(job_id: str, settings, pair: str, opts: dict) -> None:
    job = JOBS[job_id]
    try:
        modes, fee, trade = opts["modes"], opts["fee_pct"], opts["trade_amount_usd"]
        job["phase"] = "loading candles"
        history = await load_market_history(settings, pair, opts["days"] * 1440)
        rows = valid_rows(history)
        if len(rows) < 3 * 360:
            raise ValueError("Not enough candle history for the optimizer.")
        summary = market_summary(rows)

        candidates = grid_candidates(modes)
        n_grid = len(candidates)
        snippets: list[dict] = []
        insights, llm_note = "", None
        if opts["use_web"]:
            job["phase"] = "searching the web"
            snippets = await web_search()
            if not snippets:
                job["warnings"].append("Web search returned nothing; continuing without it.")
        if opts["use_llm"]:
            job["phase"] = "asking the AI for candidate settings"
            reply = await call_agent({"task": "propose", "pair": pair, "market": summary, "fee_pct": fee,
                                      "modes": modes, "snippets": snippets})
            if "error" in reply:
                job["warnings"].append(f"AI proposals skipped: {reply['error']}")
            else:
                insights = str(reply.get("insights", ""))[:1200]
                proposed = [c for c in (sanitize_candidate(x, modes) for x in (reply.get("candidates") or [])[:MAX_LLM_CANDIDATES]) if c]
                candidates += proposed
                llm_note = f"{len(proposed)} AI-proposed settings"
        candidates = _dedupe(candidates)

        job["phase"] = f"backtesting {len(candidates)} settings on every day-window"

        def progress(done: int, total: int) -> None:
            job["progress"] = round(done / total * 100)

        scored = await asyncio.to_thread(evaluate, rows, candidates, fee, trade, progress)
        spans, n_train = _windows(rows)
        ranked = rank(scored, n_train)
        top = ranked[:10]
        attach_bc_prices(rows, top)
        v, v_text = verdict(next((s for s in ranked if s["eligible"]), None))
        baseline = round(statistics.mean(s["train_mean_pct"] for s in ranked), 3)

        explanation = None
        if opts["use_llm"]:
            job["phase"] = "AI is writing the summary"
            explanation = await call_agent({"task": "explain", "pair": pair, "market": summary, "fee_pct": fee,
                                            "verdict": v, "verdict_text": v_text, "baseline_mean_pct": baseline,
                                            "top": top[:5], "n_candidates": len(ranked), "n_windows": len(spans)})
            if "error" in explanation:
                job["warnings"].append(f"AI summary skipped: {explanation['error']}")
                explanation = None

        job["result"] = {
            "pair": pair, "days": opts["days"], "fee_pct": fee, "market": summary,
            "windows": len(spans), "train_windows": n_train,
            "tested": len(ranked), "grid_count": n_grid, "ai_note": llm_note,
            "sources": [{"title": s["title"], "source": s["source"]} for s in snippets],
            "insights": insights, "verdict": v, "verdict_text": v_text,
            "baseline_mean_pct": baseline, "top": top, "explanation": explanation,
        }
        job["state"], job["phase"], job["progress"] = "done", "done", 100
    except Exception as e:  # noqa: BLE001 - reported to the UI
        logger.exception("AI optimizer job failed")
        job["state"], job["error"] = "error", str(e)[:300]
