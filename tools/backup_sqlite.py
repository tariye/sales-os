#!/usr/bin/env python3
"""Create a restart-safe SQLite backup for Info Analyzer OS."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH_RAW = os.environ.get("INFO_ANALYZER_DB_PATH", "").strip()
DB_PATH = Path(DB_PATH_RAW).expanduser() if DB_PATH_RAW else ROOT / "data" / "info_analyzer.db"
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--backup-dir", default=str(ROOT / "backups"))
    parser.add_argument("--label", default="info_analyzer")
    parser.add_argument("--manifest", default="")
    args = parser.parse_args()

    source = Path(args.db).expanduser()
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        raise SystemExit(f"database not found: {source}")

    backup_dir = Path(args.backup_dir).expanduser()
    if not backup_dir.is_absolute():
        backup_dir = ROOT / backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{args.label}-{now_stamp()}.db"

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.execute("PRAGMA foreign_keys = ON")
        src.execute("PRAGMA journal_mode = WAL")
        src.execute("PRAGMA busy_timeout = 5000")
        src.backup(dst)
        check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        journal_mode = src.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = src.execute("PRAGMA foreign_keys").fetchone()[0]

    result = {
        "generated_at": now_iso(),
        "source": str(source),
        "backup": str(target),
        "bytes": target.stat().st_size,
        "integrity_check": check,
        "journal_mode": journal_mode,
        "foreign_keys": bool(foreign_keys),
        "status": "pass" if check == "ok" else "fail",
    }
    print(json.dumps(result, indent=2))
    if args.manifest:
        manifest = Path(args.manifest)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
