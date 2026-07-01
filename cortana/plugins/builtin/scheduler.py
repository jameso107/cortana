"""
Scheduler plugin — Cortana's proactivity engine.

Persists timed tasks in SQLite and runs a background loop that fires them when
due: it runs the task's prompt through the orchestrator and pushes the result
to the UI as a notification + chat message (and speaks it if voice is on).

This is what turns Cortana from reactive to ambient — e.g. a morning briefing
at 08:00, or "remind me to stretch in 20 minutes".
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from cortana.plugins.base import PluginBase

log = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "scheduler"
    capabilities = {"system"}
    description = (
        "Schedule things for the future so you can act proactively: a daily task "
        "at a set time (e.g. a morning briefing at 08:00), or a one-off after a "
        "delay (e.g. 'remind me in 20 minutes'). When a task fires you run its "
        "instruction and notify the user."
    )

    def __init__(self):
        from cortana.config import get_config
        self._db = Path(get_config().memory.structured_path).expanduser()
        self._ensure_table()

    def _ensure_table(self):
        self._db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                kind TEXT,              -- 'daily' | 'once'
                fire_at TEXT,           -- daily: 'HH:MM'; once: ISO datetime
                prompt TEXT,            -- instruction run through the orchestrator
                last_fired TEXT,        -- 'YYYY-MM-DD' (daily) or 'done' (once)
                created_at TEXT
            )
        """)
        conn.commit(); conn.close()

    # ── Tool interface ──────────────────────────────────────────────────────────
    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add_daily", "add_once", "list", "remove"],
                            "description": "add_daily=every day at `time` HH:MM; add_once=once after `minutes` from now; list=show tasks; remove=delete by `id`."},
                        "title": {"type": "string", "description": "Short human label for the task."},
                        "prompt": {"type": "string", "description": "Instruction to run when it fires, e.g. 'Give me my daily briefing.'"},
                        "time": {"type": "string", "description": "For add_daily: 24h 'HH:MM'."},
                        "minutes": {"type": "integer", "description": "For add_once: fire this many minutes from now."},
                        "id": {"type": "integer", "description": "Task id for remove."},
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        action = args.get("action")
        now = datetime.now()
        conn = sqlite3.connect(self._db)
        try:
            if action == "add_daily":
                t = (args.get("time") or "").strip()
                if not _valid_hhmm(t):
                    return "Provide a valid 24h time as HH:MM (e.g. 08:00)."
                conn.execute("INSERT INTO scheduled_tasks (title,kind,fire_at,prompt,last_fired,created_at) VALUES (?,?,?,?,?,?)",
                             (args.get("title", "Daily task"), "daily", t, args.get("prompt", ""), "", now.isoformat()))
                conn.commit()
                return f"Scheduled daily at {t}: {args.get('title','task')}."
            if action == "add_once":
                mins = int(args.get("minutes", 0))
                if mins <= 0:
                    return "Provide a positive number of minutes."
                fire = (now + timedelta(minutes=mins)).isoformat()
                conn.execute("INSERT INTO scheduled_tasks (title,kind,fire_at,prompt,last_fired,created_at) VALUES (?,?,?,?,?,?)",
                             (args.get("title", "Reminder"), "once", fire, args.get("prompt", ""), "", now.isoformat()))
                conn.commit()
                return f"Okay — I'll do that in {mins} minute(s)."
            if action == "list":
                rows = conn.execute("SELECT id,title,kind,fire_at,last_fired FROM scheduled_tasks ORDER BY id").fetchall()
                if not rows:
                    return "No scheduled tasks."
                return "\n".join(f"#{r[0]} [{r[2]}] {r[3]} — {r[1]}" + (" (done)" if r[4] == "done" else "") for r in rows)
            if action == "remove":
                conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (int(args.get("id", -1)),))
                conn.commit()
                return "Removed."
            return f"Unknown scheduler action: {action}"
        finally:
            conn.close()

    # ── Background firing loop ────────────────────────────────────────────────────
    async def background_task(self):
        log.info("Scheduler loop started.")
        while True:
            try:
                await asyncio.sleep(30)
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.debug("Scheduler tick error: %s", exc)

    async def _tick(self):
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        hhmm = now.strftime("%H:%M")
        due = []
        conn = sqlite3.connect(self._db)
        try:
            for r in conn.execute("SELECT id,title,kind,fire_at,prompt,last_fired FROM scheduled_tasks").fetchall():
                tid, title, kind, fire_at, prompt, last_fired = r
                if kind == "daily" and hhmm >= fire_at and last_fired != today:
                    due.append((tid, title, prompt))
                    conn.execute("UPDATE scheduled_tasks SET last_fired=? WHERE id=?", (today, tid))
                elif kind == "once" and last_fired != "done":
                    try:
                        if now >= datetime.fromisoformat(fire_at):
                            due.append((tid, title, prompt))
                            conn.execute("UPDATE scheduled_tasks SET last_fired='done' WHERE id=?", (tid,))
                    except ValueError:
                        pass
            conn.commit()
        finally:
            conn.close()
        for tid, title, prompt in due:
            await self._fire(title, prompt)

    async def _fire(self, title: str, prompt: str):
        from cortana.core.orchestrator import get_orchestrator, Request
        from cortana.core.ws_server import broadcast
        log.info("Scheduler firing: %s", title)
        orch = get_orchestrator()
        body = prompt
        if orch is not None and prompt:
            try:
                resp = await orch.handle(Request(text=prompt, source="proactive"))
                body = resp.text
            except Exception as exc:
                body = f"(couldn't complete '{prompt}': {exc})"
        await broadcast({"type": "notification", "title": title, "body": body})
        await broadcast({"type": "message", "text": f"🔔 **{title}**\n\n{body}"})


def _valid_hhmm(t: str) -> bool:
    try:
        h, m = t.split(":")
        return 0 <= int(h) < 24 and 0 <= int(m) < 60
    except Exception:
        return False
