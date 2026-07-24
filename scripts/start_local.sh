#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT/.runtime"
PID_FILE="$RUNTIME_DIR/server.pid"
LOG_FILE="$RUNTIME_DIR/server.log"
STATE_FILE="$RUNTIME_DIR/local_server.json"

PORT="${INFO_ANALYZER_PORT:-8100}"
HOST="${INFO_ANALYZER_HOST:-127.0.0.1}"
ACTIVE_DB="${INFO_ANALYZER_DB_PATH:-$HOME/Library/Application Support/InfoAnalyzer/active/info_analyzer.db}"
TEST_DB="${INFO_ANALYZER_TEST_DB_PATH:-$HOME/Library/Application Support/InfoAnalyzer/test/info_analyzer_test.db}"
API_KEY="${INFO_ANALYZER_API_KEY:-local-dev-key}"

mkdir -p "$RUNTIME_DIR" "$(dirname "$ACTIVE_DB")" "$(dirname "$TEST_DB")"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ "$OLD_PID" != "" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Info Analyzer is already running."
    echo "PID: $OLD_PID"
    echo "URL: http://$HOST:$PORT/"
    exit 0
  fi
fi

if python3 - "$HOST" "$PORT" <<'PY'
import socket
import sys
host, port = sys.argv[1], int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.5)
    if sock.connect_ex((host, port)) == 0:
        raise SystemExit(0)
raise SystemExit(1)
PY
then
  echo "Port $PORT is already in use. Run scripts/doctor.sh to identify the active service." >&2
  exit 1
fi

BRANCH="$(git -C "$ROOT" branch --show-current)"
SHA="$(git -C "$ROOT" rev-parse HEAD)"

if [[ "${INFO_ANALYZER_FOREGROUND:-0}" == "1" ]]; then
  SERVER_PID="$$"
  echo "$SERVER_PID" > "$PID_FILE"
  cat > "$STATE_FILE" <<JSON
{
  "pid": "$SERVER_PID",
  "url": "http://$HOST:$PORT/",
  "human_review_url": "http://$HOST:$PORT/?view=human-review",
  "branch": "$BRANCH",
  "commit": "$SHA",
  "active_db_path": "$ACTIVE_DB",
  "test_db_path": "$TEST_DB",
  "log_file": "foreground",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
  echo "Info Analyzer local runtime starting in foreground."
  echo "URL: http://$HOST:$PORT/"
  echo "Human Review: http://$HOST:$PORT/?view=human-review"
  echo "PID: $SERVER_PID"
  echo "Branch: $BRANCH"
  echo "Commit: $SHA"
  echo "Active DB: $ACTIVE_DB"
  echo "Test DB: $TEST_DB"
  cd "$ROOT"
  exec env \
    INFO_ANALYZER_DB_PATH="$ACTIVE_DB" \
    INFO_ANALYZER_TEST_DB_PATH="$TEST_DB" \
    INFO_ANALYZER_API_KEY="$API_KEY" \
    INFO_ANALYZER_ENV=local \
    INFO_ANALYZER_DISABLE_DATA_PLANE_THREADS="${INFO_ANALYZER_DISABLE_DATA_PLANE_THREADS:-1}" \
    python3 server.py --host "$HOST" --port "$PORT"
fi

pushd "$ROOT" >/dev/null
nohup env \
  INFO_ANALYZER_DB_PATH="$ACTIVE_DB" \
  INFO_ANALYZER_TEST_DB_PATH="$TEST_DB" \
  INFO_ANALYZER_API_KEY="$API_KEY" \
  INFO_ANALYZER_ENV=local \
  INFO_ANALYZER_DISABLE_DATA_PLANE_THREADS="${INFO_ANALYZER_DISABLE_DATA_PLANE_THREADS:-1}" \
  python3 server.py --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
popd >/dev/null

echo "$SERVER_PID" > "$PID_FILE"

python3 - "$HOST" "$PORT" "$ACTIVE_DB" "$TEST_DB" "$SHA" <<'PY'
import json
import sys
import time
import urllib.request

host, port, active_db, test_db, sha = sys.argv[1:6]
base = f"http://{host}:{port}"
deadline = time.time() + 25
last = ""
while time.time() < deadline:
    try:
        with urllib.request.urlopen(base + "/api/runtime/status", timeout=2) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            if data.get("active_db_path") != active_db:
                raise SystemExit(f"Active DB mismatch: {data.get('active_db_path')} != {active_db}")
            if data.get("test_db_path") != test_db:
                raise SystemExit(f"Test DB mismatch: {data.get('test_db_path')} != {test_db}")
            if data.get("git_commit") != sha:
                raise SystemExit(f"Build SHA mismatch: {data.get('git_commit')} != {sha}")
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as exc:
        last = repr(exc)
    time.sleep(0.25)
raise SystemExit(f"Runtime status check failed: {last}")
PY

cat > "$STATE_FILE" <<JSON
{
  "pid": "$SERVER_PID",
  "url": "http://$HOST:$PORT/",
  "human_review_url": "http://$HOST:$PORT/?view=human-review",
  "branch": "$BRANCH",
  "commit": "$SHA",
  "active_db_path": "$ACTIVE_DB",
  "test_db_path": "$TEST_DB",
  "log_file": "$LOG_FILE",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON

echo "Info Analyzer local runtime started."
echo "URL: http://$HOST:$PORT/"
echo "Human Review: http://$HOST:$PORT/?view=human-review"
echo "PID: $SERVER_PID"
echo "Branch: $BRANCH"
echo "Commit: $SHA"
echo "Active DB: $ACTIVE_DB"
echo "Test DB: $TEST_DB"
echo "Log: $LOG_FILE"
