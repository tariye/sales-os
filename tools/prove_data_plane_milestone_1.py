#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iter_cases(suite: unittest.TestSuite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from iter_cases(test)
        else:
            yield test


def run_case(case: unittest.TestCase) -> dict:
    result = unittest.TestResult()
    case.run(result)
    if result.failures:
        status = "fail"
        detail = result.failures[0][1]
    elif result.errors:
        status = "error"
        detail = result.errors[0][1]
    elif result.skipped:
        status = "skip"
        detail = result.skipped[0][1]
    else:
        status = "pass"
        detail = ""
    return {
        "name": case.id().split(".")[-1],
        "test_id": case.id(),
        "status": status,
        "ok": status == "pass",
        "detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-proof", default=str(BASE_DIR / "docs/proof/data-plane-milestone-1.json"))
    parser.add_argument("--enable-socket-tests", action="store_true")
    args = parser.parse_args()

    if args.enable_socket_tests:
        os.environ["INFO_ANALYZER_ENABLE_SOCKET_TESTS"] = "1"

    suite = unittest.defaultTestLoader.discover(str(BASE_DIR / "tests"), pattern="test_*.py")
    checks = [run_case(case) for case in iter_cases(suite)]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] in {"fail", "error"})
    skipped = sum(1 for check in checks if check["status"] == "skip")
    proof = {
        "generated_at": now_iso(),
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": len(checks),
        },
        "checks": checks,
        "status": "pass" if failed == 0 else "fail",
        "socket_tests_enabled": bool(args.enable_socket_tests),
    }
    path = Path(args.write_proof)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, indent=2))
    return 0 if proof["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
