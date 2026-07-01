"""
Perception plugin — lets Cortana see what the user is doing right now:
the frontmost application and its focused window title.

Uses AppleScript via `osascript` (no extra dependency). Window-title access
needs macOS Accessibility permission for the host app; if it's not granted,
the app name still works and the title degrades gracefully.
"""
from __future__ import annotations

import asyncio

from cortana.plugins.base import PluginBase

_SCRIPT = '''
tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
    set winTitle to ""
    try
        set winTitle to name of front window of (first application process whose frontmost is true)
    end try
end tell
return frontApp & "|" & winTitle
'''


async def active_context() -> dict:
    """Return {app, window} for the frontmost app. Fast; safe to call per turn."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", _SCRIPT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=1.5)
        app, _, window = out.decode().strip().partition("|")
        return {"app": app, "window": window}
    except Exception:
        return {"app": "", "window": ""}


class Plugin(PluginBase):
    name = "perception"
    capabilities = {"system"}
    description = (
        "See what the user is currently doing — the frontmost app and window title. "
        "Use when the user refers to 'this', 'what I'm looking at', or the current app."
    )

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        ctx = await active_context()
        if not ctx["app"]:
            return "Couldn't read the active app (Accessibility permission may be needed)."
        if ctx["window"]:
            return f"The user is in {ctx['app']} — window: {ctx['window']}."
        return f"The user is in {ctx['app']}."
