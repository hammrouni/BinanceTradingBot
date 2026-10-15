"""Tests for the DASHBOARD_TOKEN middleware and /api/v1/health."""
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from config.settings import get_settings
from main import app

TOKEN = "s3cret-token"


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    get_settings.cache_clear()


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health_ok_without_token_configured():
    async with _client() as c:
        res = await c.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_no_token_configured_leaves_api_open():
    async with _client() as c:
        res = await c.get("/api/v1/status")
    assert res.status_code == 200


async def test_401_without_token(with_token):
    async with _client() as c:
        for method, path in [("GET", "/api/v1/status"), ("POST", "/api/v1/bot/stop"),
                             ("GET", "/mcp/sse")]:
            res = await c.request(method, path)
            assert res.status_code == 401, path


async def test_401_with_wrong_token(with_token):
    async with _client() as c:
        res = await c.get("/api/v1/status", headers={"X-Dashboard-Token": "nope"})
    assert res.status_code == 401


async def test_200_with_header_token(with_token):
    async with _client() as c:
        res = await c.get("/api/v1/status", headers={"X-Dashboard-Token": TOKEN})
    assert res.status_code == 200


async def test_200_with_cookie_token(with_token):
    async with _client() as c:
        res = await c.get("/api/v1/status", cookies={"dashboard_token": TOKEN})
    assert res.status_code == 200


async def test_health_and_static_open_with_token(with_token):
    async with _client() as c:
        assert (await c.get("/api/v1/health")).status_code == 200
        assert (await c.get("/")).status_code == 200


def test_websocket_rejected_without_token(with_token):
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/dashboard"):
            pass
