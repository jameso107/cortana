"""
WebSocket terminal server — streams a real PTY to the browser via xterm.js.
Runs on ws://localhost:8766. Requires: pip install websockets ptyprocess
"""
from __future__ import annotations

import asyncio
import logging
import os
import pty
import fcntl
import struct
import termios

import websockets
from websockets.server import WebSocketServerProtocol

log = logging.getLogger(__name__)

SHELL = os.environ.get("SHELL", "/bin/zsh")


async def handle(ws: WebSocketServerProtocol):
    log.info("Terminal client connected.")
    # Spawn shell in a PTY
    master_fd, slave_fd = pty.openpty()
    pid = os.fork()
    if pid == 0:
        # Child: become the shell
        os.setsid()
        os.close(master_fd)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvp(SHELL, [SHELL])
        os._exit(1)

    os.close(slave_fd)

    loop = asyncio.get_event_loop()

    async def read_pty():
        """Forward PTY output → browser."""
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
                await ws.send(data.decode("utf-8", errors="replace"))
            except (OSError, websockets.exceptions.ConnectionClosed):
                break

    async def write_pty():
        """Forward browser input → PTY."""
        async for msg in ws:
            if isinstance(msg, str):
                if msg.startswith("\x1b[8;"):
                    # Resize: ESC[8;<rows>;<cols>t
                    try:
                        _, rows_s, cols_s = msg[4:-1].split(";")
                        rows, cols = int(rows_s), int(cols_s)
                        fcntl.ioctl(master_fd, termios.TIOCSWINSZ,
                                    struct.pack("HHHH", rows, cols, 0, 0))
                    except Exception:
                        pass
                else:
                    os.write(master_fd, msg.encode())
            else:
                os.write(master_fd, msg)

    try:
        await asyncio.gather(read_pty(), write_pty())
    finally:
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
            os.close(master_fd)
        except OSError:
            pass
        log.info("Terminal client disconnected.")


async def serve(host: str = "localhost", port: int = 8766):
    log.info("Terminal server starting on ws://%s:%d", host, port)
    async with websockets.serve(handle, host, port):
        await asyncio.Future()  # run forever
