#!/usr/bin/env python3
"""Lightweight OpenAPI contract validation for Info Analyzer OS v1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


REQUIRED_PATHS = [
    "/api/v1/health",
    "/api/v1/entries",
    "/api/v1/entries/search",
    "/api/v1/context",
    "/api/v1/action_queue",
    "/api/v1/critical_alerts",
    "/api/v1/alerts/{alert_id}/acknowledge",
    "/api/v1/feedback",
    "/api/v1/actions/{action_id}/feedback",
    "/api/v1/decisions/{decision_id}",
]

REQUIRED_OPERATION_IDS = [
    "getApiHealth",
    "createLedgerEntry",
    "searchLedgerEntries",
    "retrieveContext",
    "getActionQueue",
    "getCriticalAlerts",
    "acknowledgeAlert",
    "logFeedback",
    "updateActionFeedback",
    "updateDecision",
]

REQUIRED_TERMS = [
    "openapi: 3.1.0",
    "securitySchemes:",
    "bearerAuth:",
    "apiKeyHeader:",
    "Idempotency-Key",
    "X-Request-ID",
    "X-Source-Client",
    "X-Source-Chat",
    "EnvelopeBase",
    "ErrorEnvelope",
    '"400":',
    '"401":',
    '"404":',
    '"409":',
    '"500":',
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default="docs/openapi/info-analyzer-v1.yaml")
    parser.add_argument("--write-proof", default="")
    args = parser.parse_args()

    path = Path(args.schema)
    text = path.read_text(encoding="utf-8")
    checks = []
    for item in REQUIRED_PATHS:
        checks.append({"name": f"path:{item}", "ok": item in text})
    for item in REQUIRED_OPERATION_IDS:
        checks.append({"name": f"operationId:{item}", "ok": f"operationId: {item}" in text})
    for item in REQUIRED_TERMS:
        checks.append({"name": f"term:{item}", "ok": item in text})

    passed = sum(1 for check in checks if check["ok"])
    result = {
        "generated_at": now_iso(),
        "schema": str(path),
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
