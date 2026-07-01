"""Web fetch plugin — fetch and extract text from a URL."""
from __future__ import annotations
import httpx
from bs4 import BeautifulSoup
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "web_fetch"
    capabilities = {"network"}
    description = (
        "Fetch and read the contents of a SPECIFIC URL the user provided or that a "
        "search returned. Use to extract or summarize a known page — not to answer "
        "general questions."
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
                        "url": {"type": "string", "description": "The full http(s) URL to fetch and read."},
                        "max_chars": {"type": "integer", "default": 4000, "description": "Max characters of page text to return."},
                    },
                    "required": ["url"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        url = args.get("url", "")
        max_chars = args.get("max_chars", 4000)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=15, headers={"User-Agent": "Cortana/0.1"})
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:max_chars]
