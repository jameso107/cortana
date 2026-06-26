"""
Code assistant plugin — focused code review, generation, explanation, and debugging.

Runs a dedicated completion (no tools, lower temperature) against the same local
model with a specialized system prompt, so coding work stays structured and
isolated from the main conversational turn.
"""
from __future__ import annotations

from cortana.plugins.base import PluginBase

_SYSTEM = {
    "review":   "You are a senior code reviewer. Identify bugs, edge cases, and concrete improvements. Be specific and terse.",
    "generate": "You are an expert programmer. Write correct, idiomatic, well-structured code. Include only what was asked.",
    "explain":  "You are a patient teacher. Explain the code clearly and concisely, top-down.",
    "debug":    "You are a debugging expert. Diagnose the likely cause and give a concrete fix.",
}


class Plugin(PluginBase):
    name = "code_assistant"
    description = (
        "Specialized coding help: review, generate, explain, or debug code in any language. "
        "Provide the task and any relevant code."
    )

    def __init__(self):
        from cortana.inference.client import InferenceClient
        self._inference = InferenceClient()

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "enum": ["review", "generate", "explain", "debug"]},
                        "prompt": {"type": "string", "description": "What you want done (the instruction)."},
                        "code": {"type": "string", "description": "Relevant code, if any."},
                        "language": {"type": "string", "description": "Programming language, if relevant."},
                    },
                    "required": ["task", "prompt"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        task = args.get("task", "generate")
        system = _SYSTEM.get(task, _SYSTEM["generate"])
        prompt = args.get("prompt", "")
        code = args.get("code", "")
        language = args.get("language", "")

        user = prompt
        if language:
            user += f"\n\nLanguage: {language}"
        if code:
            user += f"\n\nCode:\n```\n{code}\n```"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        text, _ = await self._inference.chat(messages=messages)
        return text or "(no output)"
