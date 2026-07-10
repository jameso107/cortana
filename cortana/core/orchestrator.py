"""Action-first OpenAI agent orchestrator."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger(__name__)
EmitFn = Callable[[dict], Awaitable[None]]

_active: "Orchestrator | None" = None


def _set_orchestrator(orchestrator: "Orchestrator"):
    global _active
    _active = orchestrator


def get_orchestrator() -> "Orchestrator | None":
    return _active


@dataclass
class Request:
    text: str
    source: str = "text"
    session_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class Response:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


class Orchestrator:
    """Runs multi-step OpenAI Responses API turns against privileged local tools."""

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
        self._reasoning = cfg.agent.reasoning
        self._sessions: dict[str, str] = {}
        self._session_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._running = False

    @property
    def reasoning(self) -> str:
        return self._reasoning

    def set_reasoning(self, mode: str) -> bool:
        if mode in ("auto", "always", "never"):
            self._reasoning = mode
            return True
        return False

    def reset_session(self, session_id: str = "default"):
        self._sessions.pop(session_id, None)
        log.info("Session %s cleared", session_id)

    async def start(self):
        log.info("Cortana starting with OpenAI model %s", self.inference.model)
        await self.memory.init()
        await self.plugins.load_all()
        self._running = True
        _set_orchestrator(self)
        self._bg_tasks = self.plugins.spawn_background_tasks()
        log.info("Cortana agent ready")

    async def stop(self):
        self._running = False
        for task in getattr(self, "_bg_tasks", []):
            task.cancel()

    async def handle(self, request: Request, emit: EmitFn | None = None) -> Response:
        session_id = request.session_id or "default"
        async with self._session_locks[session_id]:
            return await self._handle_locked(request, session_id, emit)

    async def _handle_locked(
        self,
        request: Request,
        session_id: str,
        emit: EmitFn | None,
    ) -> Response:
        retrieve_task = asyncio.create_task(self.memory.retrieve(request.text))
        facts = self.memory.facts_block() if self._inject_facts else ""
        context = await retrieve_task
        instructions = self._instructions(request, facts, context)
        tools = self.plugins.get_responses_tool_schemas()
        previous_response_id = self._sessions.get(session_id)
        input_items: list[dict] = [{"role": "user", "content": request.text}]
        all_tool_calls: list[dict] = []
        final_text = ""

        try:
            for _step in range(self._max_steps):
                response = await self.inference.respond(
                    instructions=instructions,
                    input_items=input_items,
                    tools=tools,
                    previous_response_id=previous_response_id,
                    reasoning_effort=self._reasoning_effort(request.text),
                )

                calls = []
                for item in response.output:
                    if getattr(item, "type", None) != "function_call":
                        continue
                    calls.append({
                        "id": item.call_id,
                        "name": item.name,
                        "arguments": item.arguments or "{}",
                    })

                if calls:
                    all_tool_calls.extend(calls)
                    if emit:
                        await emit({"type": "status", "value": "working"})
                        for call in calls:
                            await emit({"type": "tool", "name": call["name"]})

                    results = await self.plugins.dispatch(calls)
                    input_items = []
                    for call, result in zip(calls, results):
                        content = str(result.get("content", ""))
                        if emit and content.lower().startswith(("error", "blocked")):
                            await emit({"type": "tool_error", "name": call["name"]})
                        input_items.append({
                            "type": "function_call_output",
                            "call_id": call["id"],
                            "output": content,
                        })
                    previous_response_id = response.id
                    continue

                final_text = (response.output_text or "").strip()
                previous_response_id = response.id
                self._sessions[session_id] = response.id
                break
            else:
                final_text = (
                    "I reached the maximum number of tool steps before completing the task. "
                    "Review the tool activity and ask me to continue."
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Agent turn failed")
            final_text = f"The OpenAI agent request failed: {type(exc).__name__}. Check the daemon logs."

        if emit:
            await emit({"type": "stream_start"})
            if final_text:
                await emit({"type": "stream_delta", "text": final_text})
            await emit({"type": "stream_end", "text": final_text})

        if final_text:
            await self.memory.save(request.text, final_text)
        return Response(text=final_text, tool_calls=all_tool_calls)

    def _reasoning_effort(self, text: str) -> str:
        if self._reasoning == "always":
            return "high"
        if self._reasoning == "never":
            return "none"
        low = text.lower()
        complex_hints = (
            "build", "implement", "debug", "research", "plan", "analyze", "refactor",
            "organize", "compare", "investigate", "fix", "deploy", "multiple", "strategy",
        )
        return "medium" if len(text.split()) > 22 or any(hint in low for hint in complex_hints) else "low"

    def _instructions(self, request: Request, facts: str, context: str) -> str:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        prompt = f"""You are Cortana, an action-first personal assistant with privileged tools on the user's Mac.

For requests to change, build, fix, organize, research, send, schedule, or operate something, use the relevant tools and continue until the requested outcome is actually complete. Observe every tool result before choosing the next action. Never claim success unless the tool result confirms it.

For questions that only ask for an answer, explanation, review, diagnosis, or plan, inspect relevant context and answer directly. Use live-data tools when freshness matters.

Read-only inspection, in-scope file edits, app control, and non-destructive validation are authorized when they are normal parts of the requested task. Ask for confirmation immediately before destructive or irreversible actions, purchases, sending external messages, or materially expanding scope. If blocked, name the exact blocker and the smallest next action.

Your source repository is {repo_root}. Keep responses direct, include material caveats, and favor completed work over instructions the user must carry out themselves."""

        if request.source == "voice":
            prompt += "\nThis request came from voice. Reply in concise, natural spoken language without Markdown."
        if facts:
            prompt += f"\n\nKnown durable user facts:\n{facts}"
        if context:
            prompt += f"\n\nRelevant prior memory:\n{context}"
        return prompt
