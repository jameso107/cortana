"""
Memory plugin — lets Cortana persist durable facts about the user.

The model calls this whenever the user shares something worth remembering
(name, preferences, ongoing projects, frequently used tools), or when the
user explicitly asks to remember / forget something. Stored facts are injected
into the system prompt on every turn (see Orchestrator._build_messages).
"""
from __future__ import annotations

from cortana.plugins.base import PluginBase
from cortana.memory.store import get_store


class Plugin(PluginBase):
    name = "memory"
    description = (
        "Remember durable facts about the user, recall what you know, or forget a fact. "
        "Use action 'remember' when the user shares a lasting preference, name, project, "
        "or detail worth keeping across conversations. Facts are stored as key/value pairs."
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
                            "enum": ["remember", "recall", "forget", "list"],
                        },
                        "key": {
                            "type": "string",
                            "description": "Short identifier for the fact, e.g. 'name', 'preferred_editor', 'timezone'.",
                        },
                        "value": {
                            "type": "string",
                            "description": "The fact to store (required for 'remember').",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        store = get_store()
        if store is None:
            return "Memory store is not available."

        action = args.get("action")
        key = (args.get("key") or "").strip()

        if action == "remember":
            value = args.get("value")
            if not key or value is None:
                return "Error: both 'key' and 'value' are required to remember a fact."
            store.set_fact(key, value)
            return f"Remembered — {key}: {value}"

        if action == "recall":
            if not key:
                return "Error: 'key' is required to recall a fact."
            value = store.get_fact(key)
            return f"{key}: {value}" if value is not None else f"I don't have a fact stored for '{key}'."

        if action == "forget":
            if not key:
                return "Error: 'key' is required to forget a fact."
            return f"Forgot '{key}'." if store.forget_fact(key) else f"No fact stored for '{key}'."

        if action == "list":
            facts = store.all_facts()
            if not facts:
                return "I don't have any stored facts about you yet."
            return "\n".join(f"- {k}: {v}" for k, v in facts.items())

        return f"Unknown memory action: {action}"
