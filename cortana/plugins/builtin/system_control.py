"""System control plugin — volume, brightness, DND, app control via AppleScript/subprocess."""
from __future__ import annotations

import asyncio

from cortana.plugins._osa import run_cmd, run_osa
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "system_control"
    capabilities = {"system"}
    description = (
        "Control macOS system settings: volume, brightness, DND, app launch/quit, mute. "
        "Use set_brightness to change screen brightness (0-100). "
        "Use set_volume to change audio volume (0-100)."
    )

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "set_volume", "get_volume", "mute", "unmute",
                                "set_brightness", "get_brightness",
                                "launch_app", "quit_app",
                                "set_dnd", "lock_screen",
                            ],
                        },
                        "value": {
                            "type": "string",
                            "description": "Numeric value 0-100 for volume/brightness, or 'on'/'off' for DND",
                        },
                        "app": {"type": "string", "description": "App name for launch/quit"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        value  = args.get("value", "")
        app    = args.get("app", "")

        try:
            # ── Volume ────────────────────────────────────────────
            if action == "set_volume":
                level = max(0, min(100, int(float(value)))) if value else 50
                await run_osa(f"set volume output volume {level}")
                return f"Volume set to {level}%."

            if action == "get_volume":
                r = await run_osa("output volume of (get volume settings)")
                return f"Volume is {r.stdout.strip()}%."

            if action == "mute":
                await run_osa("set volume with output muted")
                return "Muted."

            if action == "unmute":
                await run_osa("set volume without output muted")
                return "Unmuted."

            # ── Brightness ────────────────────────────────────────
            if action == "set_brightness":
                level = max(0, min(100, int(float(value)))) if value else 100
                # Sweep to 0 with 16 brightness-down taps, then N up taps.
                # (macOS has no scriptable absolute-brightness API without a helper.)
                steps = round(level / 6.25)  # 16 steps cover 0-100%
                down16 = "\n  ".join(['key code 145'] * 16)
                script = f'tell application "System Events"\n  {down16}\nend tell'
                if steps > 0:
                    up_n = "\n  ".join(['key code 144'] * steps)
                    script += f'\ntell application "System Events"\n  {up_n}\nend tell'
                await run_osa(script)
                return f"Brightness set to ~{level}%."

            if action == "get_brightness":
                return "Brightness level not readable directly; use set_brightness to adjust."

            # ── Apps ──────────────────────────────────────────────
            if action == "launch_app":
                await run_cmd(["open", "-a", app])
                return f"Launched {app}."

            if action == "quit_app":
                await run_osa(f'quit app "{app}"')
                return f"Quit {app}."

            # ── DND / Lock ────────────────────────────────────────
            if action == "set_dnd":
                on = value.lower() in ("on", "1", "true", "yes")
                label = "Turn On Do Not Disturb" if on else "Turn Off Do Not Disturb"
                await run_cmd(["shortcuts", "run", label])
                return f"Do Not Disturb {'on' if on else 'off'}."

            if action == "lock_screen":
                await run_osa(
                    'tell application "System Events" to keystroke "q" using {control down, command down}'
                )
                return "Screen locked."

            return "Unknown system action."
        except asyncio.TimeoutError:
            return f"Error: system command '{action}' did not respond in time."
        except Exception as exc:
            return f"System control error: {exc}"
