#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Cortana OpenAI web-agent setup ==="

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -e ".[dev]"

npm install

if command -v docker >/dev/null 2>&1; then
  docker compose up -d searxng
fi

echo
echo "Setup complete."
echo "  1. node scripts/configure-secrets.mjs"
echo "  2. bash scripts/setup-local-bridge.sh"
echo "  3. bash scripts/run.sh"
