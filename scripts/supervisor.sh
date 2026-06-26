#!/usr/bin/env bash
# Supervisor — keeps the Cortana daemon alive and handles restart signals.
# Usage: bash scripts/supervisor.sh [--voice]
#
# Writes its PID to ~/.cortana/supervisor.pid so the self_editor plugin
# can send SIGUSR1 to trigger a clean restart.

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$HOME/.cortana/supervisor.pid"
mkdir -p "$HOME/.cortana"

VOICE_FLAG=""
for arg in "$@"; do
  [[ "$arg" == "--voice" ]] && VOICE_FLAG="--voice"
done

echo "$$" > "$PID_FILE"
trap "rm -f '$PID_FILE'" EXIT

_restart=0
trap '_restart=1' SIGUSR1

echo "[supervisor] PID $$ — starting Cortana daemon (voice: ${VOICE_FLAG:-off})"

while true; do
  _restart=0

  "$ROOT/.venv/bin/cortana" start $VOICE_FLAG &
  DAEMON_PID=$!
  echo "[supervisor] Daemon PID $DAEMON_PID"

  # Wait for either the daemon to exit naturally or SIGUSR1
  while kill -0 "$DAEMON_PID" 2>/dev/null; do
    if [[ "$_restart" -eq 1 ]]; then
      echo "[supervisor] SIGUSR1 received — restarting daemon…"
      kill -TERM "$DAEMON_PID" 2>/dev/null
      wait "$DAEMON_PID" 2>/dev/null
      break
    fi
    sleep 1
  done

  EXIT_CODE=$?
  if [[ "$_restart" -eq 0 ]]; then
    echo "[supervisor] Daemon exited (code $EXIT_CODE) — relaunching in 2s…"
    sleep 2
  else
    echo "[supervisor] Restarting now…"
    sleep 1
  fi
done
