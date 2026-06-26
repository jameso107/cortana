"""Calendar plugin — read/create macOS Calendar events via AppleScript."""
from __future__ import annotations
import subprocess
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "calendar"
    capabilities = {"system"}
    description = "Read and create macOS Calendar events."

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list_today", "list_week", "create"]},
                        "title": {"type": "string"},
                        "start": {"type": "string", "description": "ISO datetime"},
                        "end": {"type": "string", "description": "ISO datetime"},
                        "notes": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")

        if action == "list_today":
            script = '''
            tell application "Calendar"
                set today to current date
                set startOfDay to today - (time of today)
                set endOfDay to startOfDay + 86399
                set eventList to {}
                repeat with c in calendars
                    set evs to (events of c whose start date >= startOfDay and start date <= endOfDay)
                    repeat with e in evs
                        set end of eventList to (summary of e & " at " & (start date of e as string))
                    end repeat
                end repeat
                return eventList
            end tell
            '''
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return result.stdout.strip() or "No events today."

        if action == "create":
            title = args.get("title", "Untitled")
            start = args.get("start", "")
            end = args.get("end", "")
            script = f'''
            tell application "Calendar"
                tell calendar "Home"
                    make new event with properties {{summary:"{title}", start date:date "{start}", end date:date "{end}"}}
                end tell
            end tell
            '''
            subprocess.run(["osascript", "-e", script], check=True)
            return f"Created event: {title}"

        return "Unknown calendar action."
