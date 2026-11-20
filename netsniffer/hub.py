"""Real-time event hub (WebSocket fan-out) and alert dispatch."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("netsniffer.hub")


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, type_: str, data: Any = None) -> None:
        if not self.clients:
            return
        msg = json.dumps({"type": type_, "data": data}, default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(msg), 2)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def emit(self, type_: str, data: Any = None) -> None:
        """Fire-and-forget broadcast from sync or async code running on the loop."""
        try:
            asyncio.get_running_loop().create_task(self.broadcast(type_, data))
        except RuntimeError:
            pass
