"""Optional shared-token auth for the dashboard API.

When ``DASHBOARD_TOKEN`` is set, requests to ``/api/v1/*``, ``/ws/dashboard``
and ``/mcp`` must carry the token in the ``X-Dashboard-Token`` header or the
``dashboard_token`` cookie. Static files and ``/api/v1/health`` stay open.
Implemented as pure ASGI so it covers HTTP, WebSocket and mounted sub-apps.
"""
import hmac
from http.cookies import SimpleCookie

from config.settings import get_settings

COOKIE_NAME = "dashboard_token"
HEADER_NAME = b"x-dashboard-token"
PROTECTED_PREFIXES = ("/api/v1", "/ws/dashboard", "/mcp")
PUBLIC_PATHS = {"/api/v1/health"}


def _is_protected(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return False
    return any(path == p or path.startswith(p + "/") for p in PROTECTED_PREFIXES)


def _extract_token(scope) -> str:
    token = ""
    cookie_header = ""
    for name, value in scope.get("headers", []):
        if name == HEADER_NAME:
            token = value.decode("latin-1")
        elif name == b"cookie":
            cookie_header = value.decode("latin-1")
    if token:
        return token
    if cookie_header:
        try:
            jar = SimpleCookie(cookie_header)
            if COOKIE_NAME in jar:
                return jar[COOKIE_NAME].value
        except Exception:
            return ""
    return ""


class DashboardTokenMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        expected = get_settings().dashboard_token
        if not expected:
            return await self.app(scope, receive, send)
        if not _is_protected(scope["path"]):
            return await self.app(scope, receive, send)

        supplied = _extract_token(scope)
        if hmac.compare_digest(supplied.encode(), expected.encode()):
            return await self.app(scope, receive, send)

        if scope["type"] == "websocket":
            await receive()  # consume websocket.connect
            await send({"type": "websocket.close", "code": 1008})
            return
        body = b'{"status":"error","message":"Unauthorized"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
