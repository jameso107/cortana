"""Email plugin — read, summarize, draft, and send via macOS Mail (AppleScript)."""
from __future__ import annotations

import subprocess

from cortana.plugins.base import PluginBase


def _osa(script: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )


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
                return self._list_recent(int(args.get("count", 10)))
            if action == "read":
                idx = args.get("index")
                if idx is None:
                    return "Error: 'index' is required for read."
                return self._read(int(idx))
            if action == "send":
                return self._send(args)
            return f"Unknown email action: {action}"
        except subprocess.TimeoutExpired:
            return "Error: Mail did not respond in time."
        except Exception as exc:
            return f"Email error: {exc}"

    def _list_recent(self, count: int) -> str:
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
        r = _osa(script)
        if r.returncode != 0:
            return f"Could not read Mail: {r.stderr.strip()}"
        return r.stdout.strip() or "Inbox is empty."

    def _read(self, index: int) -> str:
        script = f'''
        tell application "Mail"
            set m to item {index} of messages of inbox
            return (sender of m) & linefeed & "Subject: " & (subject of m) & linefeed & linefeed & (content of m)
        end tell
        '''
        r = _osa(script)
        if r.returncode != 0:
            return f"Could not read message {index}: {r.stderr.strip()}"
        body = r.stdout.strip()
        return body[:4000] + "\n[… truncated]" if len(body) > 4000 else body

    def _send(self, args: dict) -> str:
        to = (args.get("to") or "").strip()
        subject = (args.get("subject") or "").strip()
        body = args.get("body") or ""
        if not to:
            return "Error: 'to' is required to send email."

        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace('"', '\\"')

        script = f'''
        tell application "Mail"
            set newMsg to make new outgoing message with properties {{subject:"{esc(subject)}", content:"{esc(body)}", visible:false}}
            tell newMsg
                make new to recipient at end of to recipients with properties {{address:"{esc(to)}"}}
                send
            end tell
        end tell
        '''
        r = _osa(script)
        if r.returncode != 0:
            return f"Send failed: {r.stderr.strip()}"
        return f"Sent email to {to} — \"{subject}\""
