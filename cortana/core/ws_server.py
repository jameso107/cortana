"""
Cortana WebSocket chat server — ws://localhost:8765
Bridges the browser UI to the orchestrator.
"""
from __future__ import annotations

import asyncio
import json
import logging

import websockets
from websockets.server import WebSocketServerProtocol

log = logging.getLogger(__name__)


async def handle(ws: WebSocketServerProtocol, orchestrator):
    log.info("UI client connected.")
    try:
        async for raw in ws:
            data = json.loads(raw)
            if data.get("type") != "message":
                continue

            text = data.get("text", "").strip()
            if not text:
                continue

            await ws.send(json.dumps({"type": "status", "value": "thinking"}))

            from cortana.core.orchestrator import Request
            response = await orchestrator.handle(Request(text=text, source="text"))

            await ws.send(json.dumps({"type": "message", "text": response.text}))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        log.info("UI client disconnected.")


async def serve(orchestrator, host: str = "localhost", port: int = 8765):
    log.info("Chat WebSocket server on ws://%s:%d", host, port)
    async with websockets.serve(lambda ws: handle(ws, orchestrator), host, port):
        await asyncio.Future()
