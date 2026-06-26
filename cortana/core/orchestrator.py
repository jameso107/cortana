"""Central orchestrator — routes requests, runs the agent loop, assembles responses."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

# An async callback the orchestrator uses to stream events to a UI.
# Receives dicts like {"type": "stream_delta", "text": "..."}.
EmitFn = Callable[[dict], Awaitable[None]]


# Shared accessor so HTTP endpoints can reach the live orchestrator.
_active: "Orchestrator | None" = None


def _set_orchestrator(o: "Orchestrator"):
    global _active
    _active = o


def get_orchestrator() -> "Orchestrator | None":
    return _active


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
    Call .start() to initialize; .handle(request) to process a single turn.
    """

    def __init__(self):
        from cortana.config import get_config
        from cortana.inference.client import InferenceClient
        from cortana.memory.store import MemoryStore
        from cortana.plugins.registry import PluginRegistry

        cfg = get_config()
        self.inference = InferenceClient()
        self.memory = MemoryStore()
        self.plugins = PluginRegistry()
        self._max_steps = cfg.agent.max_steps
        self._inject_facts = cfg.agent.inject_facts
        self._reasoning = cfg.agent.reasoning  # "auto" | "always" | "never"
        self._running = False

    async def start(self):
        log.info("Cortana orchestrator starting…")
        await self.memory.init()
        await self.plugins.load_all()
        self._running = True
        _set_orchestrator(self)
        log.info("Cortana ready.")

    @property
    def reasoning(self) -> str:
        return self._reasoning

    def set_reasoning(self, mode: str) -> bool:
        if mode in ("auto", "always", "never"):
            self._reasoning = mode
            log.info("Reasoning mode set to %s.", mode)
            return True
        return False

    async def stop(self):
        self._running = False
        log.info("Cortana stopped.")

    async def handle(self, request: Request, emit: EmitFn | None = None) -> Response:
        """
        Process one user turn through a multi-step ReAct-style agent loop.

        The model may call tools repeatedly (search → fetch → summarize → …),
        observing each result before deciding the next action, up to max_steps.

        If `emit` is provided, the final natural-language answer is streamed
        token-by-token via stream_* events; otherwise the full text is returned
        only in the Response (used by the voice/CLI paths).
        """
        log.debug("Handling request: %s", request.text)

        context = await self.memory.retrieve(request.text)
        facts = self.memory.facts_block() if self._inject_facts else ""
        tools = self.plugins.get_tool_schemas()
        messages = self._build_messages(request, context, facts)

        final_text = ""
        all_tool_calls: list[dict] = []

        for step in range(self._max_steps):
            full_text = ""
            tool_calls = None
            streamed_any = False
            # Streaming state for hiding Qwen3 <think>…</think> reasoning.
            buf = ""
            emitted = ""
            in_think_prev = False

            async for ev in self.inference.chat_stream(messages, tools):
                if ev["type"] == "delta":
                    if not emit:
                        continue
                    buf += ev["text"]
                    visible, in_think = self._strip_think(buf)
                    visible = self._emittable(visible)
                    if in_think != in_think_prev:
                        await emit({"type": "reasoning", "value": "start" if in_think else "end"})
                        in_think_prev = in_think
                    if len(visible) > len(emitted):
                        if not streamed_any:
                            await emit({"type": "stream_start"})
                            streamed_any = True
                        await emit({"type": "stream_delta", "text": visible[len(emitted):]})
                        emitted = visible
                else:  # done
                    full_text = ev["text"]
                    tool_calls = ev["tool_calls"]
            if emit and in_think_prev:
                await emit({"type": "reasoning", "value": "end"})

            if tool_calls:
                # This step is an action, not the final answer. Any preamble we
                # streamed isn't the user-facing reply — tell the UI to drop it.
                if streamed_any and emit:
                    await emit({"type": "stream_cancel"})

                all_tool_calls.extend(tool_calls)
                if emit:
                    for tc in tool_calls:
                        await emit({"type": "tool", "name": tc["name"]})

                tool_results = await self.plugins.dispatch(tool_calls)
                formatted_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ]
                messages += [
                    {"role": "assistant", "content": self._strip_think(full_text)[0].strip(), "tool_calls": formatted_calls},
                    *tool_results,
                ]
                continue

            # No tool calls → this is the final answer (with reasoning stripped).
            final_text = self._strip_think(full_text)[0].strip()
            if emit:
                if not streamed_any:
                    await emit({"type": "stream_start"})
                await emit({"type": "stream_end", "text": final_text})
            break
        else:
            log.warning("Agent loop hit max_steps (%d).", self._max_steps)
            final_text = final_text or (
                "I wasn't able to finish that within my step limit. "
                "Could you narrow it down?"
            )
            if emit:
                await emit({"type": "stream_start"})
                await emit({"type": "stream_end", "text": final_text})

        await self.memory.save(request.text, final_text)
        return Response(text=final_text, tool_calls=all_tool_calls)

    @staticmethod
    def _strip_think(text: str) -> tuple[str, bool]:
        """
        Remove Qwen3 <think>…</think> reasoning. Returns (visible, in_think)
        where in_think is True if an unclosed <think> is currently open.
        """
        import re
        visible = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        in_think = False
        idx = visible.rfind("<think>")
        if idx != -1:
            visible = visible[:idx]
            in_think = True
        return visible.lstrip("\n"), in_think

    @staticmethod
    def _emittable(visible: str) -> str:
        """Hold back a trailing partial '<think>' tag so it never flashes in the UI."""
        frag = "<think>"
        for n in range(len(frag) - 1, 0, -1):
            if visible.endswith(frag[:n]):
                return visible[:-n]
        return visible

    def _build_messages(self, request: Request, context: str, facts: str) -> list[dict]:
        import os
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        system = (
            "You are Cortana, a fully local, privacy-first AI personal assistant "
            "running on the user's Mac. You are capable, direct, and efficient.\n\n"

            "## Tools & autonomy\n"
            "You can call tools and chain them across multiple steps to complete a "
            "task: act, observe the result, then decide the next action until done. "
            "Use tools when they help; answer directly when they don't.\n\n"

            "## Memory\n"
            "Use the `memory` tool to remember durable facts the user shares (name, "
            "preferences, projects, tools they use) and to recall or forget them. "
            "Remember proactively when the user states a lasting preference.\n\n"

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
            "manage files, run shell commands, take notes, read/send email, set "
            "reminders, and more via your tools.\n"
            "Keep responses concise. Confirm before destructive or irreversible actions.\n\n"
        )
        if facts:
            system += f"## What you know about the user\n{facts}\n\n"
        if context:
            system += f"## Relevant memory\n{context}\n"

        prefix = self._reasoning_prefix(request.text)
        user = f"{prefix}\n{request.text}" if prefix else request.text
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    # Qwen3 soft-switches: /think enables chain-of-thought, /no_think disables it.
    _COMPLEX_HINTS = (
        "plan", "debug", "why", "analyze", "analyse", "fix", "build", "implement",
        "compare", "step", "calculate", "design", "refactor", "troubleshoot",
        "explain", "diagnose", "optimize", "strategy", "multiple", "research",
    )

    def _reasoning_prefix(self, text: str) -> str:
        """Decide whether to enable Qwen3's thinking mode for this turn."""
        if self._reasoning == "always":
            return "/think"
        if self._reasoning == "never":
            return "/no_think"
        # auto: think for complex/multi-step asks, stay fast for simple ones.
        low = text.lower()
        complex_task = (
            len(text.split()) > 24
            or any(h in low for h in self._COMPLEX_HINTS)
            or "?" in text and len(text.split()) > 12
        )
        return "/think" if complex_task else "/no_think"
