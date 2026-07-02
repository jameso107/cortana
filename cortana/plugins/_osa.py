"""
Async subprocess helpers for macOS plugins.

Plugin handlers run on the single asyncio event loop that also drives inference
streaming and the WebSocket servers. A blocking subprocess.run() therefore
freezes the entire daemon for the call's duration (osascript against
Mail/Calendar/Reminders can take seconds). These helpers run the child process
without blocking the loop, and let asyncio.wait_for actually enforce a timeout.
"""
from __future__ import annotations

import asyncio


class OsaResult:
    """Mirror of subprocess.CompletedProcess for the fields plugins use."""

    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


async def run_cmd(args: list[str], timeout: float = 20.0) -> OsaResult:
    """Run a command without blocking the event loop. Returns an OsaResult."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise
    return OsaResult(
        proc.returncode if proc.returncode is not None else -1,
        out.decode("utf-8", errors="replace").strip(),
        err.decode("utf-8", errors="replace").strip(),
    )


async def run_osa(script: str, timeout: float = 20.0) -> OsaResult:
    """Run an AppleScript via osascript without blocking the event loop."""
    return await run_cmd(["osascript", "-e", script], timeout=timeout)


def esc(s: str) -> str:
    """Escape a string for safe interpolation into an AppleScript double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
