"""
Daily briefing plugin (PRD 5.5) — a proactive morning summary.

Aggregates today's calendar, weather, open reminders, and top news into one
concise briefing. Composes the other built-in plugins rather than duplicating
their logic. Location for weather comes from the request, else the stored
'location' fact, else is skipped.
"""
from __future__ import annotations

import asyncio

from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "daily_briefing"
    description = (
        "Give a proactive daily briefing: today's calendar, weather, open reminders, "
        "and top news headlines. Use for 'good morning', 'what's my day look like', "
        "or 'daily briefing'."
    )
    capabilities = {"network", "system"}

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City for weather; defaults to your stored 'location' fact.",
                        },
                        "news_items": {"type": "integer", "default": 3},
                    },
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        from cortana.plugins.builtin.calendar import Plugin as Calendar
        from cortana.plugins.builtin.weather import Plugin as Weather
        from cortana.plugins.builtin.reminders import Plugin as Reminders
        from cortana.plugins.builtin.news import Plugin as News
        from cortana.memory.store import get_store

        location = (args.get("location") or "").strip()
        if not location:
            store = get_store()
            if store is not None:
                location = store.get_fact("location") or ""

        async def safe(coro, label: str) -> str:
            try:
                return await coro
            except Exception as exc:
                return f"({label} unavailable: {exc})"

        tasks = {
            "calendar": safe(Calendar().handle("calendar", {"action": "list_today"}), "calendar"),
            "reminders": safe(Reminders().handle("reminders", {"action": "list"}), "reminders"),
            "news": safe(News().handle("get_news", {"num_items": int(args.get("news_items", 3))}), "news"),
        }
        if location:
            tasks["weather"] = safe(Weather().handle("get_weather", {"location": location}), "weather")

        keys = list(tasks)
        results = await asyncio.gather(*(tasks[k] for k in keys))
        out = dict(zip(keys, results))

        parts = ["☀️ Daily Briefing", ""]
        if "weather" in out:
            parts += [f"Weather — {out['weather']}", ""]
        parts += [f"Today's calendar:\n{out['calendar']}", ""]
        parts += [f"Open reminders:\n{out['reminders']}", ""]
        parts += [f"Top headlines:\n{out['news']}"]
        return "\n".join(parts)
