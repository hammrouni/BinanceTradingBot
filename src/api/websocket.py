import asyncio
import json

from fastapi import WebSocket

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        self.send_timeout: float = 2.0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)
        logger.info("WS client connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)
        logger.info("WS client disconnected. Total: %d", len(self.active))

    async def _send(self, ws: WebSocket, data: str) -> bool:
        try:
            await asyncio.wait_for(ws.send_text(data), timeout=self.send_timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("WS client too slow (>%.1fs), dropping", self.send_timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("WS send failed, removing client: %s", e)
        return False

    async def broadcast(self, message: dict) -> None:
        logger.debug("WS broadcast: type=%s, clients=%d", message.get("type"), len(self.active))
        if not self.active:
            return
        data = json.dumps(message)
        clients = list(self.active)
        results = await asyncio.gather(*(self._send(ws, data) for ws in clients))
        self.active -= {ws for ws, ok in zip(clients, results) if not ok}


manager = ConnectionManager()


async def ws_broadcaster(queue: asyncio.Queue) -> None:
    while True:
        try:
            message = await queue.get()
            await manager.broadcast(message)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("ws_broadcaster error: %s", e)
