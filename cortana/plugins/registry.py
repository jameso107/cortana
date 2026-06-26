"""Plugin registry — loads, hot-reloads, and dispatches to plugins."""
from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any

from cortana.plugins.base import PluginBase

log = logging.getLogger(__name__)

BUILTIN_PLUGINS = [
    "cortana.plugins.builtin.web_search",
    "cortana.plugins.builtin.calendar",
    "cortana.plugins.builtin.file_manager",
    "cortana.plugins.builtin.system_control",
    "cortana.plugins.builtin.weather",
    "cortana.plugins.builtin.notes",
    "cortana.plugins.builtin.clipboard",
    "cortana.plugins.builtin.web_fetch",
    "cortana.plugins.builtin.news",
    "cortana.plugins.builtin.self_editor",
    "cortana.plugins.builtin.memory",
    "cortana.plugins.builtin.email",
    "cortana.plugins.builtin.reminders",
    "cortana.plugins.builtin.code_assistant",
]


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, PluginBase] = {}

    async def load_all(self):
        for module_path in BUILTIN_PLUGINS:
            self._load_plugin(module_path)
        log.info("Loaded %d plugins.", len(self._plugins))

    def _load_plugin(self, module_path: str):
        try:
            mod = importlib.import_module(module_path)
            plugin: PluginBase = mod.Plugin()
            self._plugins[plugin.name] = plugin
            log.debug("Loaded plugin: %s", plugin.name)
        except Exception as exc:
            log.warning("Failed to load plugin %s: %s", module_path, exc)

    def get_tool_schemas(self) -> list[dict]:
        return [p.register() for p in self._plugins.values()]

    async def dispatch(self, tool_calls: list[dict]) -> list[dict]:
        """Execute tool calls and return tool result messages."""
        results = []
        for call in tool_calls:
            name = call["name"]
            try:
                args = json.loads(call.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            plugin = self._plugins.get(name)
            if plugin is None:
                content = f"Unknown tool: {name}"
            else:
                try:
                    content = await plugin.handle(name, args)
                except Exception as exc:
                    log.error("Plugin %s error: %s", name, exc)
                    content = f"Error in {name}: {exc}"

            results.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": content,
            })
        return results
