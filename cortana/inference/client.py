"""OpenAI Responses API client for Cortana's agent loop."""
from __future__ import annotations

import logging
import os
from typing import Any

from openai import AsyncOpenAI

from cortana.config import get_config

log = logging.getLogger(__name__)


class InferenceClient:
    def __init__(self):
        cfg = get_config().inference
        api_key = os.getenv(cfg.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{cfg.api_key_env} is missing. Save an OpenAI project key in .env.local."
            )
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = os.getenv("OPENAI_MODEL", cfg.model)
        self._reasoning_effort = cfg.reasoning_effort
        self._max_output_tokens = cfg.max_output_tokens
        self._store = cfg.store

    @property
    def model(self) -> str:
        return self._model

    async def respond(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None = None,
        reasoning_effort: str | None = None,
    ):
        """Create one Responses API step, including reasoning and function calls."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "instructions": instructions,
            "input": input_items,
            "tools": tools,
            "store": self._store,
            "max_output_tokens": self._max_output_tokens,
            "reasoning": {
                "effort": reasoning_effort or self._reasoning_effort,
                "context": "all_turns",
            },
        }
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id

        try:
            return await self._client.responses.create(**kwargs)
        except Exception:
            log.exception("OpenAI Responses API request failed")
            raise
