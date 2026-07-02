"""Email plugin — read, summarize, draft, and send via macOS Mail (AppleScript)."""
from __future__ import annotations

import asyncio

from cortana.plugins._osa import esc as _esc
from cortana.plugins._osa import run_osa
from cortana.plugins.base import PluginBase


async def _osa(script: str, timeout: float = 30.0):
    return await run_osa(script, timeout=timeout)


class Plugin(PluginBase):
    name = "email"
    capabilities = {"network", "system"}
    description = (
        "Read recent emails, draft replies, and send mail through the macOS Mail app. "
        "Sending always requires explicit user confirmation first."
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
                            "enum": ["list_recent", "read", "send"],
                            "description": "list_recent=show recent inbox subjects (use `count`); read=full body of message at `index` (call list_recent first to get the index); send=compose to `to`/`subject`/`body` (confirm with the user before sending).",
                        },
                        "count": {
                            "type": "integer",
                            "description": "How many recent messages to list (default 10).",
                        },
                        "index": {
                            "type": "integer",
                            "description": "1-based index into the inbox for 'read'.",
                        },
                        "to": {"type": "string", "description": "Recipient address for 'send'."},
                        "subject": {"type": "string", "description": "Subject line for 'send'."},
                        "body": {"type": "string", "description": "Message body for 'send'."},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        try:
            if action == "list_recent":
                return await self._list_recent(int(args.get("count", 10)))
            if action == "read":
                idx = args.get("index")
                if idx is None:
                    return "Error: 'index' is required for read."
                return await self._read(int(idx))
            if action == "send":
                return await self._send(args)
            return f"Unknown email action: {action}"
        except asyncio.TimeoutError:
            return "Error: Mail did not respond in time."
        except Exception as exc:
            return f"Email error: {exc}"

    async def _list_recent(self, count: int) -> str:
        script = f'''
        tell application "Mail"
            set out to ""
            set msgs to messages of inbox
            set n to count of msgs
            if n > {count} then set n to {count}
            repeat with i from 1 to n
                set m to item i of msgs
                set out to out & i & ". " & (sender of m) & " — " & (subject of m) & linefeed
            end repeat
            return out
        end tell
        '''
        r = await _osa(script)
        if r.returncode != 0:
            return f"Could not read Mail: {r.stderr.strip()}"
        return r.stdout.strip() or "Inbox is empty."

    async def _read(self, index: int) -> str:
        script = f'''
        tell application "Mail"
            set m to item {index} of messages of inbox
            return (sender of m) & linefeed & "Subject: " & (subject of m) & linefeed & linefeed & (content of m)
        end tell
        '''
        r = await _osa(script)
        if r.returncode != 0:
            return f"Could not read message {index}: {r.stderr.strip()}"
        body = r.stdout.strip()
        return body[:4000] + "\n[… truncated]" if len(body) > 4000 else body

    async def _send(self, args: dict) -> str:
        to = (args.get("to") or "").strip()
        subject = (args.get("subject") or "").strip()
        body = args.get("body") or ""
        if not to:
            return "Error: 'to' is required to send email."

        script = f'''
        tell application "Mail"
            set newMsg to make new outgoing message with properties {{subject:"{_esc(subject)}", content:"{_esc(body)}", visible:false}}
            tell newMsg
                make new to recipient at end of to recipients with properties {{address:"{_esc(to)}"}}
                send
            end tell
        end tell
        '''
        r = await _osa(script)
        if r.returncode != 0:
            return f"Send failed: {r.stderr.strip()}"
        return f"Sent email to {to} — \"{subject}\""
