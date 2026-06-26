"""Central orchestrator — routes requests, manages plugin dispatch, and assembles responses."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

log = logging.getLogger(__name__)


@dataclass
class Request:
    text: str
    source: str = "voice"  # "voice" | "text" | "agent"
    session_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class Response:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


class Orchestrator:
    """
    Wires together inference, memory, plugins, and voice I/O.
    Call .start() to begin listening; .handle(request) to process a single turn.
    """

    def __init__(self):
        from cortana.inference.client import InferenceClient
        from cortana.memory.store import MemoryStore
        from cortana.plugins.registry import PluginRegistry

        self.inference = InferenceClient()
        self.memory = MemoryStore()
        self.plugins = PluginRegistry()
        self._running = False

    async def start(self):
        log.info("Cortana orchestrator starting…")
        await self.memory.init()
        await self.plugins.load_all()
        self._running = True
        log.info("Cortana ready.")

    async def stop(self):
        self._running = False
        log.info("Cortana stopped.")

    async def handle(self, request: Request) -> Response:
        """Process one user turn end-to-end."""
        log.debug("Handling request: %s", request.text)

        # 1. Retrieve relevant memories
        context = await self.memory.retrieve(request.text)

        # 2. Build system prompt with context + available tools
        tools = self.plugins.get_tool_schemas()
        messages = self._build_messages(request, context)

        # 3. Call inference (streaming)
        response_text, tool_calls = await self.inference.chat(
            messages=messages,
            tools=tools,
        )

        # 4. Dispatch tool calls if any
        if tool_calls:
            tool_results = await self.plugins.dispatch(tool_calls)
            # Second pass with tool results
            messages += [
                {"role": "assistant", "content": response_text, "tool_calls": tool_calls},
                *tool_results,
            ]
            response_text, _ = await self.inference.chat(messages=messages)

        # 5. Persist to memory
        await self.memory.save(request.text, response_text)

        return Response(text=response_text, tool_calls=tool_calls or [])

    def _build_messages(self, request: Request, context: str) -> list[dict]:
        system = (
            "You are Cortana, a fully local, privacy-first AI personal assistant. "
            "You are capable, direct, and efficient. You have access to the user's "
            "system and can execute commands, manage files, search the web, and more. "
            "Always confirm before executing destructive actions.\n\n"
        )
        if context:
            system += f"Relevant memory:\n{context}\n"

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": request.text},
        ]
