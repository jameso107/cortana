"""Base class all Cortana plugins must implement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PluginBase(ABC):
    name: str = ""
    description: str = ""
    # Declared permissions (PRD 8.2). Known values: "network", "filesystem",
    # "shell", "system", "code". Used for capability disclosure and logging.
    capabilities: set[str] = set()

    def manifest(self) -> dict:
        """Self-describing capability manifest for the plugin manager / logs."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": sorted(self.capabilities),
        }

    @abstractmethod
    def register(self) -> dict:
        """Return the OpenAI-compatible tool schema for this plugin."""
        ...

    @abstractmethod
    async def handle(self, intent: str, args: dict[str, Any]) -> str:
        """Execute the intent and return a string result."""
        ...

    async def background_task(self):
        """Optional: override to run a persistent background coroutine."""
        pass
