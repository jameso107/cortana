#!/usr/bin/env bash
# Cortana launch script — starts all services

MODEL="$HOME/.cortana/models/Qwen3-30B-A3B-Q6_K.gguf"
VENV="$(dirname "$0")/../.venv/bin/activate"

# Check model
if [ ! -f "$MODEL" ]; then
  echo "Model not found at $MODEL"
  echo "Still downloading? Check: ls -lh ~/.cortana/models/"
  exit 1
fi

# 1. llama-server (background)
echo "Starting llama-server..."
llama-server \
  --model "$MODEL" \
  --port 8080 \
  --ctx-size 16384 \
  --n-gpu-layers 99 \
  --threads 8 \
  --flash-attn \
  --host 127.0.0.1 \
  > ~/.cortana/logs/llama-server.log 2>&1 &
LLAMA_PID=$!
echo "  llama-server PID: $LLAMA_PID"

# Wait for it to be ready
echo "  Waiting for inference engine..."
for i in {1..30}; do
  curl -s http://localhost:8080/health | grep -q "ok" && break
  sleep 2
done

# 2. Cortana daemon (WebSocket chat + terminal server)
echo "Starting Cortana daemon..."
source "$VENV"
cortana start &
CORTANA_PID=$!
echo "  Cortana PID: $CORTANA_PID"

# 3. UI
echo "Starting UI..."
cd "$(dirname "$0")/../ui" && npm run dev &
UI_PID=$!
echo "  UI PID: $UI_PID"

echo ""
echo "All systems online."
echo "  UI      → http://localhost:5173"
echo "  Chat    → ws://localhost:8765"
echo "  Terminal→ ws://localhost:8766"
echo "  Search  → http://localhost:8888"
echo ""
echo "Ctrl-C to stop all."

trap "kill $LLAMA_PID $CORTANA_PID $UI_PID 2>/dev/null" EXIT
wait
