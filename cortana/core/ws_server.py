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


async def _send(ws: WebSocketServerProtocol, msg: dict):
    """Send one message to a single client, ignoring a closed socket."""
    try:
        await ws.send(json.dumps(msg))
    except Exception:
        pass


async def _run_turn(ws: WebSocketServerProtocol, orchestrator, text: str):
    """
    Run one chat turn, streaming events to the REQUESTING client only.

    Turn events (status, stream_*, tool, reasoning) go to the socket that asked,
    so two open windows don't cross-contaminate each other's chat. Genuinely
    global events (proactive notifications, voice input) still use broadcast().
    """
    from cortana.core.orchestrator import Request

    async def emit(ev: dict):
        await _send(ws, ev)

    await _send(ws, {"type": "status", "value": "thinking"})
    # The final answer arrives incrementally via stream_* events, so we do NOT
    # also send a "message" here (that would duplicate it).
    await orchestrator.handle(Request(text=text, source="text"), emit=emit)
    await _send(ws, {"type": "status", "value": "idle"})


async def handle(ws: WebSocketServerProtocol, orchestrator):
    _clients.add(ws)
    log.info("UI client connected (%d total).", len(_clients))
    current: asyncio.Task | None = None
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

            if msg_type == "reset":
                orchestrator.reset_session("default")
                await broadcast({"type": "session_reset"})
                continue

            if msg_type == "stop":
                if current and not current.done():
                    current.cancel()
                    # Wait for the turn to unwind, then notify from THIS
                    # (uncancelled) context so the messages actually send.
                    try:
                        await current
                    except asyncio.CancelledError:
                        pass
                    await _send(ws, {"type": "stream_cancel"})
                    await _send(ws, {"type": "message", "text": "⏹ _Generation stopped._"})
                    await _send(ws, {"type": "status", "value": "idle"})
                continue

            if msg_type != "message":
                continue

            text = data.get("text", "").strip()
            if not text:
                continue

            # One turn at a time per connection — ignore new prompts while busy.
            if current and not current.done():
                await _send(ws, {"type": "message", "text": "_Still working on the previous request — hit Stop to interrupt._"})
                continue

            current = asyncio.create_task(_run_turn(ws, orchestrator, text))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if current and not current.done():
            current.cancel()
        _clients.discard(ws)
        log.info("UI client disconnected (%d remaining).", len(_clients))


async def serve(orchestrator, host: str = "localhost", port: int = 8765):
    log.info("Chat WebSocket server on ws://%s:%d", host, port)
    async with websockets.serve(lambda ws: handle(ws, orchestrator), host, port):
        await asyncio.Future()
