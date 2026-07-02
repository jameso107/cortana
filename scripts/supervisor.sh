#!/usr/bin/env bash
# Supervisor — keeps the Cortana daemon alive and handles restart signals.
# Usage: bash scripts/supervisor.sh [--voice]
#
# Writes its PID to ~/.cortana/supervisor.pid so the self_editor plugin
# can send SIGUSR1 to trigger a clean restart.

# NOTE: no `set -e` — a supervisor loop must survive a failing child, and the
# SIGUSR1 trap interrupts `sleep`, which would trip errexit.
set -uo pipefail
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

backoff=1                 # seconds; doubles on repeated fast crashes, capped
restarts=0                # crashes counted within the current window
window_start=$(date +%s)

while true; do
  _restart=0

  "$ROOT/.venv/bin/cortana" start $VOICE_FLAG &
  DAEMON_PID=$!
  echo "[supervisor] Daemon PID $DAEMON_PID"

  # Wait for either the daemon to exit naturally or a SIGUSR1 restart request.
  while kill -0 "$DAEMON_PID" 2>/dev/null; do
    if [[ "$_restart" -eq 1 ]]; then
      echo "[supervisor] SIGUSR1 received — restarting daemon…"
      kill -TERM "$DAEMON_PID" 2>/dev/null
      break
    fi
    sleep 1
  done

  # Reap the daemon and capture its TRUE exit status (not the loop's).
  wait "$DAEMON_PID" 2>/dev/null
  EXIT_CODE=$?

  if [[ "$_restart" -eq 1 ]]; then
    echo "[supervisor] Restarting now…"
    backoff=1
    sleep 1
    continue
  fi

  echo "[supervisor] Daemon exited (code $EXIT_CODE)."

  # Crash-loop guard: reset the window every 60s; back off exponentially when a
  # daemon keeps dying quickly so we don't spin-restart and hammer llama.cpp.
  now=$(date +%s)
  if (( now - window_start > 60 )); then
    window_start=$now
    restarts=0
    backoff=1
  fi
  restarts=$((restarts + 1))
  if (( restarts > 3 )); then
    echo "[supervisor] $restarts crashes in <60s — backing off before relaunch."
  fi
  echo "[supervisor] Relaunching in ${backoff}s…"
  sleep "$backoff"
  backoff=$(( backoff < 30 ? backoff * 2 : 30 ))
done
