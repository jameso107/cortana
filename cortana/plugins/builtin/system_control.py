"""System control plugin — volume, brightness, DND, app control via AppleScript/subprocess."""
from __future__ import annotations
import subprocess
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "system_control"
    description = "Control macOS system settings: volume, brightness, DND, app launch/quit."

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
                            "enum": ["set_volume", "get_volume", "launch_app", "quit_app", "set_dnd"],
                        },
                        "value": {"type": "string", "description": "Value for the action (e.g. '50' for volume)"},
                        "app": {"type": "string", "description": "App name for launch/quit"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        value = args.get("value", "")
        app = args.get("app", "")

        if action == "set_volume":
            level = int(value) if value.isdigit() else 50
            subprocess.run(["osascript", "-e", f"set volume output volume {level}"], check=True)
            return f"Volume set to {level}."

        if action == "get_volume":
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True,
            )
            return f"Volume is {result.stdout.strip()}."

        if action == "launch_app":
            subprocess.run(["open", "-a", app], check=True)
            return f"Launched {app}."

        if action == "quit_app":
            subprocess.run(["osascript", "-e", f'quit app "{app}"'])
            return f"Quit {app}."

        if action == "set_dnd":
            state = "true" if value.lower() in ("on", "1", "true") else "false"
            subprocess.run([
                "shortcuts", "run",
                "Turn On Do Not Disturb" if state == "true" else "Turn Off Do Not Disturb",
            ])
            return f"DND set to {state}."

        return "Unknown system action."
