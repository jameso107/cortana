"""Clipboard plugin — read/write macOS clipboard."""
from __future__ import annotations
import pyperclip
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "clipboard"
    description = "Read or write the macOS clipboard."

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["read", "write"]},
                        "text": {"type": "string", "description": "Text to write (for write action)"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        if action == "read":
            return pyperclip.paste() or "(clipboard is empty)"
        elif action == "write":
            text = args.get("text", "")
            pyperclip.copy(text)
            return f"Copied {len(text)} characters to clipboard."
        return "Unknown clipboard action."
