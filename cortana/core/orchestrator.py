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
            # llama.cpp requires tool_calls entries to have type/function structure
            formatted_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ]
            messages += [
                {"role": "assistant", "content": response_text or "", "tool_calls": formatted_calls},
                *tool_results,
            ]
            response_text, _ = await self.inference.chat(messages=messages)

        # 5. Persist to memory
        await self.memory.save(request.text, response_text)

        return Response(text=response_text, tool_calls=tool_calls or [])

    def _build_messages(self, request: Request, context: str) -> list[dict]:
        import os
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        system = (
            "You are Cortana, a fully local, privacy-first AI personal assistant "
            "running on the user's Mac. You are capable, direct, and efficient.\n\n"

            "## Self-improvement\n"
            f"Your own source code lives at: {repo_root}\n"
            "You have full read/write access to your codebase via the `self_editor` tool. "
            "You are encouraged to improve yourself — fix bugs, add features, refactor — "
            "whenever you see an opportunity or the user asks.\n\n"
            "RULES you must always follow when editing your own code:\n"
            "1. Call `self_editor` with action `git_commit` BEFORE any `write_file` call. "
            "   A clean commit lets the user recover from any bad edit with `git checkout`.\n"
            "2. After writing files, call `shell_run` to rebuild if needed "
            "   (e.g. `cd ui && npm run build` for UI changes).\n"
            "3. Call `restart_daemon` after Python changes so they take effect.\n"
            "4. Keep commit messages descriptive — they are the audit trail.\n\n"

            "## Other capabilities\n"
            "You can control the system (volume, brightness, apps), search the web, "
            "manage files, run shell commands, take notes, and more via your tools.\n"
            "Keep responses concise. Confirm before destructive or irreversible actions.\n\n"
        )
        if context:
            system += f"## Relevant memory\n{context}\n"

        return [
            {"role": "system", "content": system},
            # /no_think disables Qwen3's chain-of-thought reasoning mode for fast responses.
            # The model will still use tools and reason correctly, just without hidden thinking tokens.
            {"role": "user", "content": f"/no_think\n{request.text}"},
        ]
