"""Web search plugin — SearXNG local instance."""
from __future__ import annotations
import httpx
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "web_search"
    capabilities = {"network"}
    description = "Search the web privately using a local SearXNG instance."

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
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "http://localhost:8888/search",
                    params={"q": query, "format": "json", "num_results": n},
                    timeout=10,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])[:n]
                if not results:
                    return "No results found."
                lines = [f"{r['title']}: {r['url']}\n{r.get('content','')}" for r in results]
                return "\n\n".join(lines)
        except Exception as exc:
            return f"Search unavailable (is SearXNG running?): {exc}"
