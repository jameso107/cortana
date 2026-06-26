"""System control plugin — volume, brightness, DND, app control via AppleScript/subprocess."""
from __future__ import annotations
import subprocess
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "system_control"
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

        # ── Volume ────────────────────────────────────────────
        if action == "set_volume":
            level = max(0, min(100, int(float(value)))) if value else 50
            subprocess.run(["osascript", "-e", f"set volume output volume {level}"], check=True)
            return f"Volume set to {level}%."

        if action == "get_volume":
            r = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True,
            )
            return f"Volume is {r.stdout.strip()}%."

        if action == "mute":
            subprocess.run(["osascript", "-e", "set volume with output muted"], check=True)
            return "Muted."

        if action == "unmute":
            subprocess.run(["osascript", "-e", "set volume without output muted"], check=True)
            return "Unmuted."

        # ── Brightness ────────────────────────────────────────
        if action == "set_brightness":
            level = max(0, min(100, int(float(value)))) if value else 100
            # Normalize to 0.0-1.0 for osascript
            norm = level / 100.0
            script = f'tell application "System Events" to set brightness of display 1 to {norm}'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            if result.returncode != 0:
                # Fallback: use brightness CLI if installed
                subprocess.run(["brightness", str(norm)], capture_output=True)
            return f"Brightness set to {level}%."

        if action == "get_brightness":
            r = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get brightness of display 1'],
                capture_output=True, text=True,
            )
            try:
                pct = round(float(r.stdout.strip()) * 100)
                return f"Brightness is {pct}%."
            except ValueError:
                return "Could not read brightness."

        # ── Apps ──────────────────────────────────────────────
        if action == "launch_app":
            subprocess.run(["open", "-a", app], check=True)
            return f"Launched {app}."

        if action == "quit_app":
            subprocess.run(["osascript", "-e", f'quit app "{app}"'])
            return f"Quit {app}."

        # ── DND / Lock ────────────────────────────────────────
        if action == "set_dnd":
            on = value.lower() in ("on", "1", "true", "yes")
            label = "Turn On Do Not Disturb" if on else "Turn Off Do Not Disturb"
            subprocess.run(["shortcuts", "run", label])
            return f"Do Not Disturb {'on' if on else 'off'}."

        if action == "lock_screen":
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to keystroke "q" using {control down, command down}',
            ])
            return "Screen locked."

        return "Unknown system action."
