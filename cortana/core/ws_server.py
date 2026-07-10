"""Authenticated local WebSocket bridge for the Vercel-hosted web application."""
from __future__ import annotations

import asyncio
import fnmatch
import hmac
import json
import logging
import os
import ssl
import uuid
from pathlib import Path

import websockets
from websockets.server import WebSocketServerProtocol

log = logging.getLogger(__name__)

_clients: set[WebSocketServerProtocol] = set()
_voice_pipeline = None


def set_voice_pipeline(pipeline):
    global _voice_pipeline
    _voice_pipeline = pipeline


async def broadcast(msg: dict):
    if not _clients:
        return
    raw = json.dumps(msg)
    await asyncio.gather(*(ws.send(raw) for ws in list(_clients)), return_exceptions=True)


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    configured = os.getenv("CORTANA_ALLOWED_ORIGINS", "http://localhost:3000")
    patterns = [value.strip() for value in configured.split(",") if value.strip()]
    return any(origin == pattern or fnmatch.fnmatch(origin, pattern) for pattern in patterns)


async def _authenticate(ws: WebSocketServerProtocol) -> bool:
    request = getattr(ws, "request", None)
    headers = request.headers if request is not None else getattr(ws, "request_headers", {})
    origin = headers.get("Origin")
    if not _origin_allowed(origin):
        await ws.send(json.dumps({"type": "auth_error"}))
        await ws.close(code=4403, reason="Origin not allowed")
        return False

    expected = os.getenv("CORTANA_BRIDGE_TOKEN", "")
    if len(expected) < 32:
        log.error("CORTANA_BRIDGE_TOKEN is missing or too short")
        await ws.close(code=1011, reason="Bridge not configured")
        return False

    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
        await ws.close(code=4401, reason="Authentication required")
        return False

    supplied = str(data.get("token", "")) if data.get("type") == "authenticate" else ""
    if not hmac.compare_digest(supplied, expected):
        await ws.send(json.dumps({"type": "auth_error"}))
        await ws.close(code=4401, reason="Invalid bridge credential")
        return False

    await ws.send(json.dumps({"type": "auth_ok"}))
    return True


async def _run_turn(orchestrator, ws: WebSocketServerProtocol, text: str, session_id: str):
    from cortana.core.orchestrator import Request

    async def emit(event: dict):
        await ws.send(json.dumps(event))

    await emit({"type": "status", "value": "thinking"})
    await orchestrator.handle(
        Request(text=text, source="text", session_id=session_id),
        emit=emit,
    )
    await emit({"type": "status", "value": "idle"})


async def handle(ws: WebSocketServerProtocol, orchestrator):
    if not await _authenticate(ws):
        return

    _clients.add(ws)
    session_id = str(uuid.uuid4())
    current: asyncio.Task | None = None
    log.info("Authenticated web client connected")
    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send(json.dumps({"type": "error", "message": "Invalid message"}))
                continue

            msg_type = data.get("type")
            if msg_type == "reset":
                orchestrator.reset_session(session_id)
                await ws.send(json.dumps({"type": "session_reset"}))
                continue

            if msg_type == "stop":
                if current and not current.done():
                    current.cancel()
                    try:
                        await current
                    except asyncio.CancelledError:
                        pass
                    await ws.send(json.dumps({"type": "stream_cancel"}))
                    await ws.send(json.dumps({"type": "status", "value": "idle"}))
                continue

            if msg_type != "message":
                continue
            text = str(data.get("text", "")).strip()
            if not text:
                continue
            if current and not current.done():
                await ws.send(json.dumps({
                    "type": "error",
                    "message": "Cortana is still working. Stop the current task before starting another.",
                }))
                continue
            current = asyncio.create_task(_run_turn(orchestrator, ws, text, session_id))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if current and not current.done():
            current.cancel()
        _clients.discard(ws)
        log.info("Web client disconnected")


def _tls_context() -> ssl.SSLContext | None:
    cert = Path(os.path.expanduser(os.getenv("CORTANA_TLS_CERT", "~/.cortana/certs/localhost.pem")))
    key = Path(os.path.expanduser(os.getenv("CORTANA_TLS_KEY", "~/.cortana/certs/localhost-key.pem")))
    if not cert.is_file() or not key.is_file():
        log.warning("TLS certificate not found; bridge will use ws:// for local development only")
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    return context


async def serve(orchestrator, host: str = "127.0.0.1", port: int = 8765):
    tls = _tls_context()
    scheme = "wss" if tls else "ws"
    log.info("Secure web bridge on %s://%s:%d", scheme, host, port)
    async with websockets.serve(
        lambda ws: handle(ws, orchestrator),
        host,
        port,
        ssl=tls,
        max_size=2 * 1024 * 1024,
    ):
        await asyncio.Future()
