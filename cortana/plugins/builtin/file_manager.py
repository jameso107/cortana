"""File manager plugin — search and manage files via ripgrep and stdlib."""
from __future__ import annotations
import subprocess
from pathlib import Path
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "file_manager"
    capabilities = {"filesystem"}
    description = "Search, read, list, and manage files on the filesystem."

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search", "read", "list", "move", "delete"]},
                        "path": {"type": "string"},
                        "query": {"type": "string"},
                        "destination": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        path = Path(args.get("path", "~")).expanduser()
        query = args.get("query", "")

        if action == "list":
            if not path.is_dir():
                return f"Not a directory: {path}"
            items = sorted(path.iterdir())
            return "\n".join(str(i.name) for i in items[:50])

        if action == "read":
            if not path.is_file():
                return f"File not found: {path}"
            return path.read_text(errors="replace")[:4000]

        if action == "search":
            result = subprocess.run(
                ["rg", "--files-with-matches", "-l", query, str(path)],
                capture_output=True, text=True,
            )
            return result.stdout.strip() or "No matches found."

        if action == "move":
            dest = Path(args.get("destination", "")).expanduser()
            path.rename(dest)
            return f"Moved {path} → {dest}"

        if action == "delete":
            # Safety: never delete without explicit confirmation flow
            return f"Deletion of {path} must be confirmed interactively."

        return "Unknown file action."
