"""The open WebSockets, keyed by user.

In-memory and therefore per-process: with more than one API worker, a POST
handled by worker B cannot reach a socket held by worker A. Fine for now;
replacing this with Redis pub/sub is the change to make before scaling out.
"""

import asyncio
import uuid

from fastapi import WebSocket

from baymax.common.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Registry of live sockets.

    Each socket gets a lock: a user may have several sessions streaming at once,
    and concurrent ``send_json`` calls on one WebSocket would interleave frames.
    """

    def __init__(self) -> None:
        self._sockets: dict[uuid.UUID, WebSocket] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    def register(self, user_uid: uuid.UUID, websocket: WebSocket) -> None:
        if user_uid in self._sockets:
            logger.info("replacing existing socket for user %s", user_uid)
        self._sockets[user_uid] = websocket
        self._locks[user_uid] = asyncio.Lock()
        logger.info("websocket registered for user %s (%d open)", user_uid, len(self._sockets))

    def unregister(self, user_uid: uuid.UUID, websocket: WebSocket) -> None:
        # Identity check: a reconnect may already have replaced this entry, and
        # the old socket's cleanup must not evict the new one.
        if self._sockets.get(user_uid) is websocket:
            del self._sockets[user_uid]
            self._locks.pop(user_uid, None)
            logger.info("websocket removed for user %s (%d open)", user_uid, len(self._sockets))

    def get(self, user_uid: uuid.UUID) -> WebSocket | None:
        return self._sockets.get(user_uid)

    def is_connected(self, user_uid: uuid.UUID) -> bool:
        return user_uid in self._sockets

    async def send(self, user_uid: uuid.UUID, payload: dict[str, object]) -> bool:
        """Send one frame. Returns False if the socket is gone.

        Callers use the return value to stop streaming into a dead socket rather
        than generating tokens nobody will receive.
        """
        websocket = self._sockets.get(user_uid)
        lock = self._locks.get(user_uid)
        if websocket is None or lock is None:
            return False

        try:
            async with lock:
                await websocket.send_json(payload)
        except Exception:
            logger.info("send failed for user %s, dropping connection", user_uid)
            self.unregister(user_uid, websocket)
            return False
        return True


#: Process-wide registry, the ``connections`` dict the design calls for.
connections = ConnectionManager()
