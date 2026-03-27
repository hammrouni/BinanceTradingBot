"""Tests for Story 1.1: Project Scaffold & Running Web Server."""
import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_status_endpoint_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/status")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "data": {}}


@pytest.mark.asyncio
async def test_root_returns_index_html():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"BinanceTradingBot" in response.content
