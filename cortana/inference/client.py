"""llama.cpp OpenAI-compatible client wrapper."""
from __future__ import annotations

import logging
from typing import Any

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

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for memory storage."""
        response = await self._client.embeddings.create(
            model="nomic-embed-text",
            input=text,
        )
        return response.data[0].embedding
