"""Weather plugin — Open-Meteo API, no key required."""
from __future__ import annotations
import httpx
from cortana.plugins.base import PluginBase


class Plugin(PluginBase):
    name = "get_weather"
    description = "Get current and forecast weather for a location."

    def register(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City or location name"},
                        "days": {"type": "integer", "description": "Forecast days (1-7)", "default": 1},
                    },
                    "required": ["location"],
                },
            },
        }

    async def handle(self, intent: str, args: dict) -> str:
        location = args.get("location", "")
        # Geocode
        async with httpx.AsyncClient() as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1},
                timeout=10,
            )
            geo.raise_for_status()
            results = geo.json().get("results", [])
            if not results:
                return f"Could not find location: {location}"
            lat = results[0]["latitude"]
            lon = results[0]["longitude"]
            name = results[0]["name"]

            weather = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weathercode,windspeed_10m",
                    "temperature_unit": "fahrenheit",
                },
                timeout=10,
            )
            weather.raise_for_status()
            current = weather.json().get("current", {})
            temp = current.get("temperature_2m", "?")
            wind = current.get("windspeed_10m", "?")
            return f"{name}: {temp}°F, wind {wind} km/h"
