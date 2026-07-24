#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT/.runtime"
PID_FILE="$RUNTIME_DIR/server.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No local Info Analyzer PID file found."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [[ "$PID" == "" ]]; then
  rm -f "$PID_FILE"
  echo "Removed empty PID file."
  exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "Local Info Analyzer process is not running. Removed stale PID file."
  exit 0
fi

kill "$PID" 2>/dev/null || true
for _ in {1..80}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Stopped Info Analyzer local runtime."
    exit 0
  fi
  sleep 0.1
done

kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Stopped Info Analyzer local runtime with SIGKILL after timeout."
