"""Web search plugin — SearXNG local instance."""
from __future__ import annotations
import asyncio
import httpx
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "web_search"
    capabilities = {"network"}
    description = (
        "Search the web for CURRENT or real-time information only — recent news, "
        "today's prices, live scores, or facts newer than your training. "
        "Do NOT use for general knowledge, definitions, explanations, comparisons, "
        "or coding — answer those directly."
    )

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "num_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        query = args.get("query", "")
        n = args.get("num_results", 5)
        # Fast-fail: short timeout + one quick retry, so a down SearXNG can't stall
        # the whole turn (previously a 10s hang). Return gracefully so the model
        # can proceed and answer from its own knowledge instead.
        last_exc = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "http://localhost:8888/search",
                        params={"q": query, "format": "json", "num_results": n},
                        timeout=4.0,
                    )
                    resp.raise_for_status()
                    results = resp.json().get("results", [])[:n]
                    if not results:
                        return "No results found."
                    lines = [f"{r['title']}: {r['url']}\n{r.get('content','')}" for r in results]
                    return "\n\n".join(lines)
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    await asyncio.sleep(0.4)
        return (
            "Web search is temporarily unavailable (local search service not "
            f"responding: {last_exc}). Answer from your own knowledge instead, and "
            "let the user know the result may not reflect the very latest information."
        )
