import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/agent", tags=["agent"])

# Agent service URL — env var overrides for Docker (use container name)
AGENT_SERVICE_URL = os.getenv(
    "AGENT_SERVICE_URL",
    "http://localhost:8090",
)


@router.post("/trading/analyze")
async def proxy_trading_analyze(request: Request):
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{AGENT_SERVICE_URL}/api/agents/trading/analyze",
                json=body,
            )
        text = resp.text
        if not text.strip():
            raise HTTPException(status_code=502, detail="Agent service returned an empty response.")
        try:
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
        except Exception:
            raise HTTPException(status_code=502, detail=f"Agent service returned non-JSON: {text[:300]}")
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Agent service unavailable — make sure it is running on port 8090.",
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Agent service timed out.")
