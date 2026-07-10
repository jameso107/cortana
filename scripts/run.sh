#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/.venv/bin/activate"

cortana start &
AGENT_PID=$!

cd "$ROOT"
npm run dev &
WEB_PID=$!

trap 'kill "$AGENT_PID" "$WEB_PID" 2>/dev/null || true' EXIT

echo "Cortana development environment is running."
echo "  Web app  → http://localhost:3000"
echo "  Agent    → wss://localhost:8765"
wait
