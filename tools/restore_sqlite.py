#!/usr/bin/env python3
"""Restore an Info Analyzer OS SQLite backup with explicit confirmation."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH_RAW = os.environ.get("INFO_ANALYZER_DB_PATH", "").strip()
DB_PATH = Path(DB_PATH_RAW).expanduser() if DB_PATH_RAW else ROOT / "data" / "info_analyzer.db"
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_sqlite(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--target", default=str(DB_PATH))
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if args.confirm != "RESTORE_INFO_ANALYZER_DB":
        raise SystemExit("refusing restore without --confirm RESTORE_INFO_ANALYZER_DB")

    backup = Path(args.backup).expanduser()
    if not backup.is_absolute():
        backup = ROOT / backup
    if not backup.exists():
        raise SystemExit(f"backup not found: {backup}")
    if validate_sqlite(backup) != "ok":
        raise SystemExit(f"backup failed integrity check: {backup}")

    target = Path(args.target).expanduser()
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    safety_copy = None
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safety_copy = target.with_suffix(target.suffix + f".pre-restore-{stamp}")
        shutil.copy2(target, safety_copy)
    shutil.copy2(backup, target)
    restored_check = validate_sqlite(target)

    result = {
        "generated_at": now_iso(),
        "backup": str(backup),
        "target": str(target),
        "safety_copy": str(safety_copy) if safety_copy else "",
        "integrity_check": restored_check,
        "status": "pass" if restored_check == "ok" else "fail",
    }
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
