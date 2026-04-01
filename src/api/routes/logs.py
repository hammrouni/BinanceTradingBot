from pathlib import Path
from fastapi import APIRouter, Query, Request
from typing import Optional, List
import re

router = APIRouter()

LOG_LINE_REGEX = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (?P<name>[\w\.]+) - (?P<level>\w+) - (?P<message>.+)$"
)

TAIL_LINES = 5000


def get_log_file():
    """Find the log file - check multiple possible locations."""
    possible_paths = [
        Path("logs/bot.log"),
        Path("../logs/bot.log"),
        Path(__file__).parent.parent.parent / "logs" / "bot.log",
    ]
    
    for p in possible_paths:
        if p.exists():
            return p
    
    return None


@router.get("/logs")
async def get_logs(
    request: Request,
    level: Optional[str] = Query(None, description="Filter by level"),
    search: Optional[str] = Query(None, description="Search in messages"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    log_file = get_log_file()
    
    if not log_file:
        return {"status": "error", "logs": [], "total": 0, "has_more": False, "error": "Log file not found"}
    
    level_filter = level.upper() if level else None
    search_lower = search.lower() if search else None
    
    logs: List[dict] = []
    
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-TAIL_LINES:]
    except Exception as e:
        return {"status": "error", "logs": [], "total": 0, "has_more": False, "error": str(e)}
    
    for line in lines:
        match = LOG_LINE_REGEX.match(line.strip())
        if not match:
            continue
        
        entry = match.groupdict()
        
        if level_filter and entry["level"] != level_filter:
            continue
        
        if search_lower and search_lower not in entry["message"].lower():
            continue
        
        logs.append({
            "timestamp": entry["timestamp"].replace(",", "."),
            "logger": entry["name"],
            "level": entry["level"],
            "message": entry["message"],
        })

    logs.reverse()
    total = len(logs)
    paginated = logs[offset:offset + limit]
    
    return {
        "status": "ok",
        "logs": paginated,
        "total": total,
        "has_more": offset + limit < total,
        "offset": offset,
        "limit": limit,
    }