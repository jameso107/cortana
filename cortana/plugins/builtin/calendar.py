"""Calendar plugin — read/create macOS Calendar events via AppleScript."""
from __future__ import annotations

import asyncio

from cortana.plugins._osa import esc as _esc
from cortana.plugins._osa import run_osa
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
                        "start": {"type": "string", "description": "ISO datetime, e.g. 2026-07-02T15:00"},
                        "end": {"type": "string", "description": "ISO datetime, e.g. 2026-07-02T16:00"},
                        "calendar": {"type": "string", "description": "Calendar name to create in (default: your default calendar)."},
                        "notes": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        try:
            if action == "list_today":
                return await self._list_range(0)
            if action == "list_week":
                return await self._list_range(7)
            if action == "create":
                return await self._create(args)
            return f"Unknown calendar action: {action}"
        except asyncio.TimeoutError:
            return "Error: Calendar did not respond in time."
        except Exception as exc:
            return f"Calendar error: {exc}"

    async def _list_range(self, days_ahead: int) -> str:
        """List events from now through `days_ahead` days (0 = end of today)."""
        span = f"startOfDay + ({days_ahead} * 86400) + 86399" if days_ahead else "startOfDay + 86399"
        script = f'''
        tell application "Calendar"
            set today to current date
            set startOfDay to today - (time of today)
            set endWindow to {span}
            set eventList to {{}}
            repeat with c in calendars
                set evs to (events of c whose start date >= startOfDay and start date <= endWindow)
                repeat with e in evs
                    set end of eventList to (summary of e & " at " & (start date of e as string))
                end repeat
            end repeat
            return eventList
        end tell
        '''
        r = await run_osa(script, timeout=30.0)
        if r.returncode != 0:
            return f"Could not read Calendar: {r.stderr.strip()}"
        label = "this week" if days_ahead else "today"
        return r.stdout.strip() or f"No events {label}."

    async def _create(self, args: dict) -> str:
        title = _esc(args.get("title", "Untitled"))
        start = _esc(args.get("start", ""))
        end = _esc(args.get("end", ""))
        notes = _esc(args.get("notes", ""))
        cal = args.get("calendar", "")
        if not start or not end:
            return "Error: 'start' and 'end' ISO datetimes are required to create an event."
        # Target a named calendar if given, else the app's default calendar.
        cal_target = f'calendar "{_esc(cal)}"' if cal else "default calendar"
        props = f'{{summary:"{title}", start date:(my parseISO("{start}")), end date:(my parseISO("{end}"))'
        if notes:
            props += f', description:"{notes}"'
        props += "}"
        # Build the target date from ISO parts so we don't depend on the locale's
        # date-string parser (the old `date "<iso>"` form broke on most machines).
        script = f'''
        on parseISO(s)
            set y to (text 1 thru 4 of s) as integer
            set mo to (text 6 thru 7 of s) as integer
            set d to (text 9 thru 10 of s) as integer
            set hh to 0
            set mm to 0
            try
                set hh to (text 12 thru 13 of s) as integer
                set mm to (text 15 thru 16 of s) as integer
            end try
            set theDate to current date
            set year of theDate to y
            set month of theDate to mo
            set day of theDate to d
            set hours of theDate to hh
            set minutes of theDate to mm
            set seconds of theDate to 0
            return theDate
        end parseISO

        tell application "Calendar"
            tell {cal_target}
                make new event with properties {props}
            end tell
        end tell
        '''
        r = await run_osa(script, timeout=30.0)
        if r.returncode != 0:
            return f"Could not create event: {r.stderr.strip()}"
        return f"Created event: {args.get('title', 'Untitled')}"
