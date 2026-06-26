"""llama.cpp OpenAI-compatible client wrapper."""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from cortana.config import get_config

log = logging.getLogger(__name__)


class InferenceClient:
    def __init__(self):
        cfg = get_config().inference
        self._client = AsyncOpenAI(
            base_url=f"http://{cfg.host}:{cfg.port}/v1",
            api_key="not-needed",  # llama.cpp doesn't need a real key
        )
        self._model = cfg.model
        self._temperature = cfg.temperature
        self._tool_temperature = cfg.tool_temperature

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> tuple[str, list[dict] | None]:
        """
        Send messages to llama.cpp server. Returns (text, tool_calls).
        tool_calls is None if no tools were invoked.
        """
        temperature = self._tool_temperature if tools else self._temperature
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            log.error("Inference error: %s", exc)
            return "I'm having trouble reaching my inference engine. Is llama.cpp running?", None

        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",       # required by llama.cpp on the second pass
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                    # also expose flat keys for dispatcher convenience
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in choice.message.tool_calls
            ]
        return text, tool_calls

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        """
        Streaming variant. Yields events:
          {"type": "delta", "text": str}                        — a content token
          {"type": "done",  "text": str, "tool_calls": list|None}  — final, once

        Content deltas are emitted live. Tool calls are assembled across the
        stream and returned (fully) in the terminal "done" event, so callers
        get the same tool_calls shape as chat().
        """
        temperature = self._tool_temperature if tools else self._temperature
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        content_parts: list[str] = []
        tc_acc: dict[int, dict] = {}  # index -> {id, name, arguments}

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "delta", "text": delta.content}
                for tcd in (delta.tool_calls or []):
                    acc = tc_acc.setdefault(tcd.index, {"id": None, "name": None, "arguments": ""})
                    if tcd.id:
                        acc["id"] = tcd.id
                    if tcd.function:
                        if tcd.function.name:
                            acc["name"] = tcd.function.name
                        if tcd.function.arguments:
                            acc["arguments"] += tcd.function.arguments
        except Exception as exc:
            log.error("Inference stream error: %s", exc)
            yield {
                "type": "done",
                "text": "I'm having trouble reaching my inference engine. Is llama.cpp running?",
                "tool_calls": None,
            }
            return

        tool_calls = None
        if tc_acc:
            tool_calls = []
            for idx in sorted(tc_acc):
                acc = tc_acc[idx]
                tool_calls.append({
                    "id": acc["id"] or f"call_{idx}",
                    "type": "function",
                    "function": {"name": acc["name"], "arguments": acc["arguments"] or "{}"},
                    "name": acc["name"],
                    "arguments": acc["arguments"] or "{}",
                })
        yield {"type": "done", "text": "".join(content_parts), "tool_calls": tool_calls}

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for memory storage."""
        response = await self._client.embeddings.create(
            model="nomic-embed-text",
            input=text,
        )
        return response.data[0].embedding
