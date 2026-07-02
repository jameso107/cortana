"""Central orchestrator — routes requests, runs the agent loop, assembles responses."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

TRACE_LOG = Path.home() / ".cortana" / "logs" / "traces.jsonl"


def _est_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) — good enough for budgeting."""
    return (len(text) + 3) // 4

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
        self._context_window = cfg.inference.context_window
        self._reply_reserve = cfg.inference.reply_reserve_tokens
        self._memory_token_budget = cfg.memory.context_tokens
        # Per-session conversation history so Cortana remembers the running
        # conversation across turns (and across UI reconnects). Keyed by
        # session_id; a single shared "default" session unifies text + voice.
        self._sessions: dict[str, list[dict]] = {}
        self._history_max = 60  # hard backstop; token budgeting is the real control
        # Serialize every turn (text, voice, scheduler) across the single
        # shared session and the single-slot llama-server. Without this, two
        # sources mutate the same history list and double-hit the backend.
        self._turn_lock = asyncio.Lock()
        self._running = False

    def reset_session(self, session_id: str = "default"):
        self._sessions.pop(session_id, None)
        log.info("Session %s cleared.", session_id)

    async def start(self):
        log.info("Cortana orchestrator starting…")
        await self.memory.init()
        await self.plugins.load_all()
        self._running = True
        _set_orchestrator(self)
        # Spawn any plugin background loops (scheduler, monitors → proactivity).
        self._bg_tasks = self.plugins.spawn_background_tasks()
        log.info("Cortana ready.")
        # Prime the model + KV cache so the FIRST real turn isn't a ~3s cold start.
        await self._warmup()

    async def _warmup(self):
        """
        Prime the slow-to-initialize paths so the FIRST real turn is hot:
          1. the memory embedder (Chroma's local model loads lazily on first query — ~3s)
          2. the llama.cpp KV cache with the real system-prompt+tools prefix
        Output is discarded.
        """
        try:
            await self.memory.retrieve("warmup")          # loads the embedding model
        except Exception as exc:
            log.debug("Memory warmup skipped (%s).", exc)
        try:
            msgs = self._build_messages(Request(text="hi", source="warmup"), "", "")
            tools = self.plugins.get_tool_schemas()
            async for _ in self.inference.chat_stream(msgs, tools):
                pass
            log.info("Warmed (memory embedder + model) — first turn will be hot.")
        except Exception as exc:
            log.debug("Inference warmup skipped (%s).", exc)

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
        for t in getattr(self, "_bg_tasks", []):
            t.cancel()
        log.info("Cortana stopped.")

    async def handle(self, request: Request, emit: EmitFn | None = None) -> Response:
        """
        Process one user turn through a multi-step ReAct-style agent loop.

        The whole turn is serialized behind a lock so overlapping sources (text,
        voice, scheduler) can't corrupt the shared session or double-hit the
        single-slot backend. See _handle_locked for the loop itself.
        """
        async with self._turn_lock:
            return await self._handle_locked(request, emit)

    async def _handle_locked(self, request: Request, emit: EmitFn | None = None) -> Response:
        log.debug("Handling request: %s", request.text)
        t0 = time.perf_counter()

        session_id = request.session_id or "default"
        history = self._sessions.setdefault(session_id, [])

        # Kick off the (async) memory retrieval and do the sync setup concurrently,
        # so the embedding lookup never sits alone on the critical path.
        retrieve_task = asyncio.create_task(self.memory.retrieve(request.text))
        facts = self.memory.facts_block() if self._inject_facts else ""
        tools = self.plugins.get_tool_schemas()
        prefix = self._reasoning_prefix(request.text)
        think_mode = prefix == "/think"
        context = await retrieve_task
        messages = self._build_messages(request, context, facts, history, prefix, tools)

        final_text = ""
        all_tool_calls: list[dict] = []
        reasoning_open = False
        failed = False
        ttft_ms: float | None = None
        trace_steps: list[dict] = []
        # Messages produced by THIS turn (assistant + tool results), persisted to
        # history so cross-turn follow-ups ("open the second result") have grounding.
        turn_messages: list[dict] = [{"role": "user", "content": request.text}]

        async def close_reasoning():
            nonlocal reasoning_open
            if reasoning_open and emit:
                await emit({"type": "reasoning", "value": "end"})
            reasoning_open = False

        if emit and think_mode:
            await emit({"type": "reasoning", "value": "start"})
            reasoning_open = True

        for step in range(self._max_steps):
            step_t0 = time.perf_counter()
            full_text = ""
            tool_calls = None
            streamed_any = False
            buf = ""       # accumulates raw content; <think> tags stripped for display
            emitted = ""

            async for ev in self.inference.chat_stream(messages, tools):
                if ev["type"] == "delta":
                    if ttft_ms is None:
                        ttft_ms = round((time.perf_counter() - t0) * 1000, 1)
                    if not emit:
                        continue
                    buf += ev["text"]
                    visible = self._emittable(self._strip_think(buf)[0])
                    if len(visible) > len(emitted):
                        if not streamed_any:
                            await close_reasoning()
                            await emit({"type": "stream_start"})
                            streamed_any = True
                        await emit({"type": "stream_delta", "text": visible[len(emitted):]})
                        emitted = visible
                else:  # done
                    full_text = ev["text"]
                    tool_calls = ev["tool_calls"]
                    failed = bool(ev.get("error"))

            # Backend failure: surface a transient error, DON'T persist the turn.
            if failed:
                if streamed_any and emit:
                    await emit({"type": "stream_cancel"})
                await close_reasoning()
                if emit:
                    await emit({"type": "error", "text": full_text})
                log.warning("Turn failed: inference backend unreachable.")
                return Response(text=full_text, tool_calls=all_tool_calls)

            if tool_calls:
                # This step is an action, not the final answer. Any preamble we
                # streamed isn't the user-facing reply — tell the UI to drop it.
                if streamed_any and emit:
                    await emit({"type": "stream_cancel"})
                    streamed_any = False
                    emitted = ""

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
                step_msgs = [
                    {"role": "assistant", "content": self._strip_think(full_text)[0].strip(), "tool_calls": formatted_calls},
                    *tool_results,
                ]
                messages += step_msgs
                turn_messages += step_msgs
                trace_steps.append({
                    "step": step,
                    "tools": [tc["name"] for tc in tool_calls],
                    "ms": round((time.perf_counter() - step_t0) * 1000, 1),
                })
                continue

            # No tool calls → this is the final answer (with reasoning stripped).
            final_text = self._strip_think(full_text)[0].strip()
            trace_steps.append({
                "step": step, "tools": [],
                "ms": round((time.perf_counter() - step_t0) * 1000, 1),
            })
            if emit:
                await close_reasoning()
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
                await close_reasoning()
                await emit({"type": "stream_start"})
                await emit({"type": "stream_end", "text": final_text})

        # Persist the full turn (user + any tool actions + final answer) to the
        # running conversation, then trim to budget. Episodic memory gets the
        # user/assistant pair.
        turn_messages.append({"role": "assistant", "content": final_text})
        history.extend(turn_messages)
        self._trim_history(history, tools)
        await self.memory.save(request.text, final_text)

        self._write_trace({
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": request.source,
            "session": session_id,
            "think": think_mode,
            "steps": trace_steps,
            "tool_calls": [tc["name"] for tc in all_tool_calls],
            "ttft_ms": ttft_ms,
            "total_ms": round((time.perf_counter() - t0) * 1000, 1),
            "reply_chars": len(final_text),
        })
        return Response(text=final_text, tool_calls=all_tool_calls)

    def _trim_history(self, history: list[dict], tools: list[dict]) -> None:
        """
        Trim session history to fit the model's context window (token-budgeted),
        dropping whole oldest turns so a 'tool' message is never orphaned from
        its assistant tool_calls. A message-count backstop bounds memory too.
        """
        # Backstop first: drop oldest whole turns past the message cap.
        while len(history) > self._history_max:
            self._drop_oldest_turn(history)

        overhead = _est_tokens(json.dumps(tools)) + _est_tokens(self._system_base())
        budget = self._context_window - self._reply_reserve - overhead
        if budget <= 0:
            return
        while history and self._est_history_tokens(history) > budget:
            if not self._drop_oldest_turn(history):
                break

    @staticmethod
    def _drop_oldest_turn(history: list[dict]) -> bool:
        """Delete the oldest complete turn (up to the next 'user' message). Returns True if anything was dropped."""
        if not history:
            return False
        # Find the start of the second turn (next 'user' after index 0).
        for i in range(1, len(history)):
            if history[i].get("role") == "user":
                del history[:i]
                return True
        # Only one turn present — drop it entirely rather than exceed budget.
        history.clear()
        return True

    @staticmethod
    def _est_history_tokens(history: list[dict]) -> int:
        return sum(_est_tokens(json.dumps(m)) for m in history)

    def _write_trace(self, record: dict) -> None:
        """Append one structured per-turn trace line (best-effort)."""
        try:
            TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with TRACE_LOG.open("a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as exc:
            log.debug("trace write failed: %s", exc)

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

    def _system_base(self) -> str:
        """The static system prompt (no per-turn facts/memory). Cached; also used for token overhead estimation."""
        cached = getattr(self, "_system_base_cache", None)
        if cached is not None:
            return cached
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        system = (
            "You are Cortana, a fully local, privacy-first AI personal assistant "
            "running on the user's Mac. You are capable, direct, and efficient.\n\n"

            "## Tools & autonomy\n"
            "You can call tools and chain them across multiple steps: act, observe "
            "the result, then decide the next action until the task is done.\n"
            "Choosing when to use a tool — follow these rules:\n"
            "- ANSWER DIRECTLY from your own knowledge for general facts, definitions, "
            "explanations, comparisons, reasoning, coding, and anything not tied to a "
            "specific live/recent/personal data source. Do NOT search the web for "
            "these — e.g. 'REST vs GraphQL', 'how does TLS work', 'write a function'.\n"
            "- Use NETWORK tools (`web_search`, `web_fetch`, `get_weather`, `get_news`) "
            "ONLY for information that is current, real-time, or post-training: today's "
            "news, live prices, weather, or a specific URL's contents.\n"
            "- Use SYSTEM tools (`calendar`, `email`, `reminders`, `system_control`, "
            "`file_manager`, `notes`, `clipboard`) when the user asks you to read or act "
            "on their machine or personal data.\n"
            "- Use `memory` for durable personal facts, `code_assistant` for focused "
            "coding work, and `self_editor` only to change your own source.\n"
            "When unsure whether a fact needs fresh data, prefer answering directly and "
            "offer to search if they want the latest.\n\n"

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

            "## Voice\n"
            "You have a real local voice. When the user enables voice mode (the mic "
            "button), you hear them via local speech-to-text and speak your replies "
            "aloud via local text-to-speech (Kokoro). You are NOT a text-only chatbot — "
            "never claim you have no voice or no way to speak.\n\n"

            "## Style\n"
            "Keep responses concise and direct. Confirm before destructive or "
            "irreversible actions.\n\n"
        )
        self._system_base_cache = system
        return system

    def _cap_tokens(self, text: str, budget: int) -> str:
        """Truncate text to an approximate token budget, noting the cut."""
        if budget <= 0 or _est_tokens(text) <= budget:
            return text
        keep = max(budget * 4 - 40, 0)
        return text[:keep].rstrip() + "\n[… memory truncated to fit context budget]\n"

    def _build_messages(self, request: Request, context: str, facts: str,
                        history: list[dict] | None = None, prefix: str = "",
                        tools: list[dict] | None = None) -> list[dict]:
        system = self._system_base()
        if request.source == "voice":
            system += (
                "## Voice reply mode\n"
                "This turn arrived by VOICE and your reply will be spoken aloud. "
                "Answer in 1-3 short sentences of plain spoken language. No markdown, "
                "no code blocks, no bullet lists, no URLs — just what you'd say out loud.\n\n"
            )
        # Facts + semantic recall share one token budget so they can't crowd out
        # the conversation or blow the context window.
        mem_block = ""
        if facts:
            mem_block += f"## What you know about the user\n{facts}\n\n"
        if context:
            mem_block += f"## Relevant memory (semantic recall of older conversations)\n{context}\n"
        system += self._cap_tokens(mem_block, self._memory_token_budget)

        if not prefix:
            prefix = self._reasoning_prefix(request.text)
        user = f"{prefix}\n{request.text}" if prefix else request.text
        return [
            {"role": "system", "content": system},
            *(history or []),
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
