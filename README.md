# Cortana

> Local, privacy-first AI personal assistant for macOS.  
> Fully on-device — no cloud, no subscriptions, no data leaves your machine.

## Stack

| Layer | Technology |
|-------|-----------|
| Inference | llama.cpp · Qwen 3.6-27B Q6 · Metal GPU |
| STT | whisper.cpp (CoreML) · OpenWakeWord |
| TTS | Kokoro (local) · macOS fallback |
| Memory | ChromaDB (episodic) · SQLite (structured) |
| Plugins | Python modules · ZeroMQ bus |
| UI | React + Vite · Canvas brain orb |

## Quick start

```bash
# 1. Python env
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. UI
cd ui && npm install && npm run dev

# 3. Start llama.cpp server (once model is downloaded)
llama-server -m ~/.cortana/models/Qwen3-27B-Instruct-Q6_K_M.gguf \
  --port 8080 --ctx-size 16384 --n-gpu-layers 99

# 4. Run Cortana (text mode)
cortana start

# 5. Voice mode
cortana start --voice
```

## Project structure

```
cortana/
  core/          orchestrator — request routing & assembly
  inference/     llama.cpp client
  memory/        ChromaDB + SQLite store
  voice/         STT / TTS pipeline
  agent/         ReAct agentic loop (TODO)
  plugins/
    base.py      plugin interface
    registry.py  loader & dispatcher
    builtin/     weather, web_search, calendar, notes, …
ui/              React holographic UI
config/          cortana.yaml
scripts/         setup helpers
```

## Plugin development

Drop a Python module in `~/.cortana/plugins/` that exports a `Plugin` class inheriting `PluginBase`:

```python
from cortana.plugins.base import PluginBase

class Plugin(PluginBase):
    name = "my_plugin"
    description = "Does something useful."

    def register(self) -> dict:
        return { "type": "function", "function": { "name": self.name, ... } }

    async def handle(self, intent: str, args: dict) -> str:
        return "result"
```

Cortana hot-reloads plugins without restart.
