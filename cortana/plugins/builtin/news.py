"""News plugin — summarize RSS feeds."""
from __future__ import annotations
import feedparser
from cortana.plugins.base import PluginBase

DEFAULT_FEEDS = [
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
]


class Plugin(PluginBase):
    name = "get_news"
    capabilities = {"network"}
    description = "Fetch the latest real-time news headlines from RSS feeds. Use only when the user asks for current news."

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "num_items": {"type": "integer", "default": 5},
                        "feed_url": {"type": "string"},
                    },
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        n = args.get("num_items", 5)
        feed_url = args.get("feed_url", DEFAULT_FEEDS[0])
        feed = feedparser.parse(feed_url)
        items = feed.entries[:n]
        if not items:
            return "No news items found."
        return "\n\n".join(f"• {e.title}: {e.link}" for e in items)
