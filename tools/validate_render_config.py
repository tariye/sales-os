#!/usr/bin/env python3
"""Validate the Render deployment contract without external dependencies."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_TERMS = [
    "type: web",
    "runtime: python",
    "branch: main",
    "startCommand: \"python server.py --host 0.0.0.0 --port $PORT\"",
    "healthCheckPath: /api/health",
    "INFO_ANALYZER_API_KEY",
    "sync: false",
    "INFO_ANALYZER_DB_PATH",
    "value: /var/data/info_analyzer.db",
    "disk:",
    "mountPath: /var/data",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-yaml", default="render.yaml")
    parser.add_argument("--write-proof", default="")
    args = parser.parse_args()

    path = Path(args.render_yaml)
    text = path.read_text(encoding="utf-8")
    checks = [{"name": item, "ok": item in text} for item in REQUIRED_TERMS]
    checks.append({
        "name": "does_not_use_authenticated_v1_health_for_render_health_check",
        "ok": "healthCheckPath: /api/v1/health" not in text,
    })
    passed = sum(1 for check in checks if check["ok"])
    result = {
        "generated_at": now_iso(),
        "render_yaml": str(path),
        "summary": {"passed": passed, "failed": len(checks) - passed, "total": len(checks)},
        "checks": checks,
        "status": "pass" if passed == len(checks) else "fail",
    }
    print(json.dumps(result, indent=2))
    if args.write_proof:
        proof = Path(args.write_proof)
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
