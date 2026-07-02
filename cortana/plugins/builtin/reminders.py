"""Reminders plugin — set, list, and complete macOS Reminders via AppleScript."""
from __future__ import annotations

import asyncio

from cortana.plugins._osa import esc as _esc
from cortana.plugins._osa import run_osa
from cortana.plugins.base import PluginBase


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
                return await self._add(text, list_name)
            if action == "list":
                return await self._list(list_name)
            if action == "complete":
                text = (args.get("text") or "").strip()
                if not text:
                    return "Error: 'text' is required to complete a reminder."
                return await self._complete(text, list_name)
            return f"Unknown reminders action: {action}"
        except asyncio.TimeoutError:
            return "Error: Reminders did not respond in time."
        except Exception as exc:
            return f"Reminders error: {exc}"

    async def _add(self, text: str, list_name: str) -> str:
        script = f'''
        tell application "Reminders"
            tell list "{_esc(list_name)}"
                make new reminder with properties {{name:"{_esc(text)}"}}
            end tell
        end tell
        '''
        r = await run_osa(script)
        if r.returncode != 0:
            return f"Could not add reminder: {r.stderr.strip()}"
        return f"Added reminder: {text}"

    async def _list(self, list_name: str) -> str:
        script = f'''
        tell application "Reminders"
            set out to ""
            repeat with r in (reminders of list "{_esc(list_name)}" whose completed is false)
                set out to out & "• " & (name of r) & linefeed
            end repeat
            return out
        end tell
        '''
        r = await run_osa(script)
        if r.returncode != 0:
            return f"Could not list reminders: {r.stderr.strip()}"
        return r.stdout.strip() or "No open reminders."

    async def _complete(self, text: str, list_name: str) -> str:
        script = f'''
        tell application "Reminders"
            set matches to (reminders of list "{_esc(list_name)}" whose name is "{_esc(text)}" and completed is false)
            if (count of matches) is 0 then return "not found"
            set completed of (item 1 of matches) to true
            return "done"
        end tell
        '''
        r = await run_osa(script)
        if r.returncode != 0:
            return f"Could not complete reminder: {r.stderr.strip()}"
        return f"Completed: {text}" if r.stdout.strip() == "done" else f"No open reminder named '{text}'."
