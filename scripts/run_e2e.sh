#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv-e2e/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "Missing .venv-e2e. Run: python3 -m venv .venv-e2e && .venv-e2e/bin/pip install -r requirements-e2e.txt" >&2
  exit 2
fi

RUN_ID="${INFO_ANALYZER_E2E_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
EVIDENCE_DIR="${INFO_ANALYZER_E2E_EVIDENCE_DIR:-/tmp/info-analyzer-e2e/$RUN_ID}"
PORT="${INFO_ANALYZER_E2E_PORT:-$("$PY" - <<'PY'
import socket
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
)}"
ACTIVE_DB="${INFO_ANALYZER_E2E_ACTIVE_DB:-/tmp/info-analyzer-e2e/$RUN_ID/active.db}"
TEST_DB="${INFO_ANALYZER_E2E_TEST_DB:-/tmp/info-analyzer-e2e/$RUN_ID/test.db}"
API_KEY="${INFO_ANALYZER_E2E_API_KEY:-e2e-local-key}"

mkdir -p "$EVIDENCE_DIR" "$(dirname "$ACTIVE_DB")" "$(dirname "$TEST_DB")"

ACTUAL_SHA="$(git -C "$ROOT" rev-parse HEAD)"
EXPECTED_SHA="${INFO_ANALYZER_E2E_EXPECTED_SHA:-$ACTUAL_SHA}"
SERVER_LOG="$EVIDENCE_DIR/server.log"
BASE_URL="http://127.0.0.1:$PORT"

cat > "$EVIDENCE_DIR/launch.json" <<JSON
{
  "repository_root": "$ROOT",
  "actual_git_sha": "$ACTUAL_SHA",
  "expected_git_sha": "$EXPECTED_SHA",
  "base_url": "$BASE_URL",
  "active_db": "$ACTIVE_DB",
  "test_db": "$TEST_DB",
  "server_log": "$SERVER_LOG",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON

cleanup() {
  if [[ "${SERVER_PID:-}" != "" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

pushd "$ROOT" >/dev/null
INFO_ANALYZER_DB_PATH="$ACTIVE_DB" \
INFO_ANALYZER_TEST_DB_PATH="$TEST_DB" \
INFO_ANALYZER_API_KEY="$API_KEY" \
INFO_ANALYZER_DISABLE_DATA_PLANE_THREADS=1 \
  "$PY" server.py --host 127.0.0.1 --port "$PORT" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
popd >/dev/null

"$PY" - "$BASE_URL" "$EXPECTED_SHA" "$ACTIVE_DB" "$TEST_DB" <<'PY'
import json
import sys
import time
import urllib.request

base_url, expected_sha, active_db, test_db = sys.argv[1:5]
deadline = time.time() + 25
last = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(base_url + "/api/health", timeout=2) as response:
            body = response.read().decode()
            last = (response.status, body)
            if response.status == 200:
                data = json.loads(body)
                if data.get("db_path") != active_db:
                    raise SystemExit(f"health DB path mismatch: {data.get('db_path')} != {active_db}")
                break
    except Exception as exc:
        last = repr(exc)
    time.sleep(0.25)
else:
    raise SystemExit(f"server health check failed: {last}")
PY

export INFO_ANALYZER_E2E_BASE_URL="$BASE_URL"
export INFO_ANALYZER_E2E_EVIDENCE_DIR="$EVIDENCE_DIR"
export INFO_ANALYZER_E2E_EXPECTED_SHA="$EXPECTED_SHA"
export INFO_ANALYZER_E2E_ACTIVE_DB="$ACTIVE_DB"
export INFO_ANALYZER_E2E_TEST_DB="$TEST_DB"
export INFO_ANALYZER_E2E_SERVER_PID="$SERVER_PID"
export INFO_ANALYZER_E2E_SERVER_LOG="$SERVER_LOG"
export INFO_ANALYZER_E2E_REPO_ROOT="$ROOT"
export INFO_ANALYZER_E2E_PORT="$PORT"

"$PY" "$ROOT/tests/e2e/test_human_review_ui.py"
