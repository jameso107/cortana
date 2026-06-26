#!/usr/bin/env bash
set -e

echo "=== Cortana setup ==="

# 1. Python env
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -e ".[dev]" -q

# 2. UI deps
cd ui && npm install -q && cd ..

# 3. SearXNG (requires Docker)
if command -v docker &>/dev/null; then
  echo "Starting SearXNG…"
  docker compose up -d searxng
  echo "SearXNG → http://localhost:8888"
else
  echo "Docker not found — install Docker Desktop to enable web search."
fi

# 4. llama.cpp check
if ! command -v llama-server &>/dev/null; then
  echo ""
  echo "llama-server not found. Install llama.cpp:"
  echo "  brew install llama.cpp"
  echo "Then download Qwen3-27B-Instruct-Q6_K_M.gguf to ~/.cortana/models/"
fi

echo ""
echo "Setup complete."
echo "  Run backend:  cortana start"
echo "  Run UI:       cd ui && npm run dev"
