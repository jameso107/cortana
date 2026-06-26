"""
Cortana WebSocket chat server — ws://localhost:8765

Handles:
  - type:"message"    — text chat from UI
  - type:"voice_mode" — toggle voice listening on/off
"""
from __future__ import annotations

import asyncio
import json
import logging

import websockets
from websockets.server import WebSocketServerProtocol

log = logging.getLogger(__name__)

_clients: set[WebSocketServerProtocol] = set()
_voice_pipeline = None   # set by cli.py when voice is active


def set_voice_pipeline(pipeline):
    global _voice_pipeline
    _voice_pipeline = pipeline


async def broadcast(msg: dict):
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
            msg_type = data.get("type")

            if msg_type == "voice_mode":
                enabled = bool(data.get("enabled", False))
                if _voice_pipeline is not None:
                    _voice_pipeline.set_listening(enabled)
                status = "listening" if enabled else "idle"
                await broadcast({"type": "status", "value": status})
                await broadcast({"type": "voice_mode_ack", "enabled": enabled})
                continue

            if msg_type != "message":
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
