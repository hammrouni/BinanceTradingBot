import asyncio
import json

from fastapi import WebSocket

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)
        logger.info("WS client connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)
        logger.info("WS client disconnected. Total: %d", len(self.active))

    async def broadcast(self, message: dict) -> None:
        logger.info("WS broadcast: type=%s, clients=%d", message.get("type"), len(self.active))
        if not self.active:
            logger.info("WS broadcast skipped - no clients connected")
            return
        data = json.dumps(message)
        dead: set[WebSocket] = set()
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except asyncio.CancelledError:
                dead.add(ws)
            except Exception as e:
                logger.debug("WS send failed, removing client: %s", e)
                dead.add(ws)
        self.active -= dead


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
