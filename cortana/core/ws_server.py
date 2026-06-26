"""
Cortana WebSocket chat server — ws://localhost:8765

Maintains a set of all connected clients so voice interactions
(triggered from the mic) are broadcast to the UI in real time.
"""
from __future__ import annotations

import asyncio
import json
import logging

import websockets
from websockets.server import WebSocketServerProtocol

log = logging.getLogger(__name__)

# All currently connected browser clients
_clients: set[WebSocketServerProtocol] = set()


async def broadcast(msg: dict):
    """Send a message to every connected UI client."""
    if not _clients:
        return
    raw = json.dumps(msg)
    await asyncio.gather(
        *[ws.send(raw) for ws in list(_clients)],
        return_exceptions=True,
    )


async def handle(ws: WebSocketServerProtocol, orchestrator):
    _clients.add(ws)
    log.info("UI client connected (%d total).", len(_clients))
    try:
        async for raw in ws:
            data = json.loads(raw)
            if data.get("type") != "message":
                continue
            text = data.get("text", "").strip()
            if not text:
                continue

            await broadcast({"type": "status", "value": "thinking"})

            from cortana.core.orchestrator import Request
            response = await orchestrator.handle(Request(text=text, source="text"))

            await broadcast({"type": "status", "value": "idle"})
            await broadcast({"type": "message", "text": response.text})
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _clients.discard(ws)
        log.info("UI client disconnected (%d remaining).", len(_clients))


async def serve(orchestrator, host: str = "localhost", port: int = 8765):
    log.info("Chat WebSocket server on ws://%s:%d", host, port)
    async with websockets.serve(lambda ws: handle(ws, orchestrator), host, port):
        await asyncio.Future()
