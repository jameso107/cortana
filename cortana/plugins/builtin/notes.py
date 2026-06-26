"""Notes plugin — markdown files in ~/Notes."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from cortana.plugins.base import PluginBase

NOTES_DIR = Path.home() / "Notes"


class Plugin(PluginBase):
    name = "notes"
    description = "Create, search, and append to personal markdown notes."

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "append", "search", "list"]},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "query": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        NOTES_DIR.mkdir(exist_ok=True)
        action = args.get("action")

        if action == "list":
            files = sorted(NOTES_DIR.glob("*.md"))
            return "\n".join(f.stem for f in files) or "No notes found."

        if action == "create":
            title = args.get("title", f"note-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            path = NOTES_DIR / f"{title}.md"
            path.write_text(f"# {title}\n\n{args.get('content', '')}\n")
            return f"Created note: {path}"

        if action == "append":
            title = args.get("title", "")
            path = NOTES_DIR / f"{title}.md"
            if not path.exists():
                return f"Note not found: {title}"
            with path.open("a") as f:
                f.write(f"\n{args.get('content', '')}\n")
            return f"Appended to {title}."

        if action == "search":
            query = args.get("query", "").lower()
            matches = []
            for f in NOTES_DIR.glob("*.md"):
                if query in f.read_text().lower():
                    matches.append(f.stem)
            return "\n".join(matches) or "No matching notes."

        return "Unknown notes action."
