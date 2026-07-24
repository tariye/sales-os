#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT/.runtime"
PID_FILE="$RUNTIME_DIR/server.pid"
STATE_FILE="$RUNTIME_DIR/local_server.json"
PORT="${INFO_ANALYZER_PORT:-8100}"
HOST="${INFO_ANALYZER_HOST:-127.0.0.1}"
BASE_URL="http://$HOST:$PORT"

echo "Info Analyzer Local Doctor"
echo "Repository: $ROOT"
echo "Branch: $(git -C "$ROOT" branch --show-current)"
echo "Commit: $(git -C "$ROOT" rev-parse HEAD)"
echo "Git status:"
git -C "$ROOT" status --short
echo

if [[ -f "$STATE_FILE" ]]; then
  echo "Runtime state file: $STATE_FILE"
  cat "$STATE_FILE"
  echo
else
  echo "Runtime state file: missing"
fi

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  echo "PID file: $PID_FILE"
  echo "PID: $PID"
  if [[ "$PID" != "" ]] && kill -0 "$PID" 2>/dev/null; then
    echo "Process: running"
    ps -p "$PID" -o pid=,ppid=,command=
  else
    echo "Process: stale or stopped"
  fi
else
  echo "PID file: missing"
fi
echo

python3 - "$BASE_URL" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1]
checks = [
    ("GET", "/", base + "/"),
    ("GET", "/app.js?v=2.0.2", base + "/app.js?v=2.0.2"),
    ("GET", "/style.css?v=2.0.2", base + "/style.css?v=2.0.2"),
    ("GET", "/api/runtime/status", base + "/api/runtime/status"),
]

for method, label, url in checks:
    try:
        request = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(request, timeout=4) as response:
            body = response.read()
            print(f"{method} {label}: HTTP {response.status}, {len(body)} bytes")
            if label == "/api/runtime/status":
                data = json.loads(body.decode("utf-8"))
                print(json.dumps({
                    "server": data.get("server"),
                    "branch": data.get("git_branch"),
                    "commit": data.get("git_commit"),
                    "active_db_path": data.get("active_db_path"),
                    "test_db_path": data.get("test_db_path"),
                    "sqlite": data.get("sqlite"),
                }, indent=2, sort_keys=True))
    except urllib.error.HTTPError as exc:
        print(f"{method} {label}: HTTP {exc.code}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"{method} {label}: FAILED {exc}")
        raise SystemExit(1)
PY
