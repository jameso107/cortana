"""Reminders plugin — set, list, and complete macOS Reminders via AppleScript."""
from __future__ import annotations

import subprocess

from cortana.plugins.base import PluginBase


def _osa(script: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


class Plugin(PluginBase):
    name = "reminders"
    capabilities = {"system"}
    description = "Create, list, and complete reminders in the macOS Reminders app."

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "list", "complete"]},
                        "text": {"type": "string", "description": "Reminder title (for add / complete)."},
                        "list_name": {"type": "string", "description": "Reminders list name (default 'Reminders')."},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        list_name = (args.get("list_name") or "Reminders").strip()
        try:
            if action == "add":
                text = (args.get("text") or "").strip()
                if not text:
                    return "Error: 'text' is required to add a reminder."
                return self._add(text, list_name)
            if action == "list":
                return self._list(list_name)
            if action == "complete":
                text = (args.get("text") or "").strip()
                if not text:
                    return "Error: 'text' is required to complete a reminder."
                return self._complete(text, list_name)
            return f"Unknown reminders action: {action}"
        except subprocess.TimeoutExpired:
            return "Error: Reminders did not respond in time."
        except Exception as exc:
            return f"Reminders error: {exc}"

    def _add(self, text: str, list_name: str) -> str:
        script = f'''
        tell application "Reminders"
            tell list "{_esc(list_name)}"
                make new reminder with properties {{name:"{_esc(text)}"}}
            end tell
        end tell
        '''
        r = _osa(script)
        if r.returncode != 0:
            return f"Could not add reminder: {r.stderr.strip()}"
        return f"Added reminder: {text}"

    def _list(self, list_name: str) -> str:
        script = f'''
        tell application "Reminders"
            set out to ""
            repeat with r in (reminders of list "{_esc(list_name)}" whose completed is false)
                set out to out & "• " & (name of r) & linefeed
            end repeat
            return out
        end tell
        '''
        r = _osa(script)
        if r.returncode != 0:
            return f"Could not list reminders: {r.stderr.strip()}"
        return r.stdout.strip() or "No open reminders."

    def _complete(self, text: str, list_name: str) -> str:
        script = f'''
        tell application "Reminders"
            set matches to (reminders of list "{_esc(list_name)}" whose name is "{_esc(text)}" and completed is false)
            if (count of matches) is 0 then return "not found"
            set completed of (item 1 of matches) to true
            return "done"
        end tell
        '''
        r = _osa(script)
        if r.returncode != 0:
            return f"Could not complete reminder: {r.stderr.strip()}"
        return f"Completed: {text}" if r.stdout.strip() == "done" else f"No open reminder named '{text}'."
