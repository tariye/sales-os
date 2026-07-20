from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


APP_SUPPORT_ROOT = Path.home() / "Library/Application Support/InfoAnalyzer"
ACTIVE_DB_PATH = APP_SUPPORT_ROOT / "active" / "info_analyzer.db"
LEGACY_DB_PATH = APP_SUPPORT_ROOT / "legacy" / "info_analyzer_legacy.db"
BACKUPS_DIR = APP_SUPPORT_ROOT / "backups"
MANIFEST_PATH = APP_SUPPORT_ROOT / "database-manifest.json"

ACTIVE_DATA_PLANE_TABLES = [
    "ingest_sources",
    "ingest_items",
    "data_plane_jobs",
    "worker_claims",
    "ingest_runs",
    "raw_snapshots",
    "source_health_events",
    "scheduler_leases",
    "scheduler_events",
    "worker_heartbeats",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_cutover_dirs() -> None:
    for path in (ACTIVE_DB_PATH.parent, LEGACY_DB_PATH.parent, BACKUPS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _table_row_count(conn: sqlite3.Connection, table: str) -> int | str:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def inventory_sqlite(path: str | Path, role: str = "") -> dict:
    db_path = Path(path).expanduser()
    if not db_path.is_absolute():
        db_path = db_path.resolve()
    exists = db_path.exists()
    info = {
        "role": role,
        "absolute_path": str(db_path),
        "exists": exists,
        "sha256": "",
        "file_size": 0,
        "modified_at": "",
        "table_names": [],
        "row_counts": {},
        "schema_version": None,
    }
    if not exists:
        return info
    stat = db_path.stat()
    info["sha256"] = sha256_file(db_path)
    info["file_size"] = stat.st_size
    info["modified_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        info["table_names"] = _sqlite_table_names(conn)
        info["row_counts"] = {name: _table_row_count(conn, name) for name in info["table_names"]}
        info["schema_version"] = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    return info


def write_json(path: str | Path, payload: dict) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def backup_snapshot(source: str | Path, label: str, backup_dir: str | Path | None = None) -> Path:
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    target_dir = Path(backup_dir or BACKUPS_DIR).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace(":", "").replace("-", "")
    target = target_dir / f"{label}-{stamp}.db"
    shutil.copy2(source_path, target)
    return target


def copy_selected_tables(source_db: str | Path, target_db: str | Path, tables: Iterable[str]) -> dict:
    source_path = Path(source_db).expanduser()
    target_path = Path(target_db).expanduser()
    copied: dict[str, int] = {}
    with sqlite3.connect(source_path) as src, sqlite3.connect(target_path) as dst:
        src.row_factory = sqlite3.Row
        dst.row_factory = sqlite3.Row
        dst.execute("PRAGMA foreign_keys = OFF")
        for table in tables:
            src_cols = [row[1] for row in src.execute(f"PRAGMA table_info({table})").fetchall()]
            dst_cols = [row[1] for row in dst.execute(f"PRAGMA table_info({table})").fetchall()]
            if not src_cols or not dst_cols:
                continue
            cols = [col for col in src_cols if col in dst_cols]
            if not cols:
                continue
            dst.execute(f"DELETE FROM {table}")
            rows = src.execute(
                f"SELECT {', '.join(cols)} FROM {table}"
            ).fetchall()
            if not rows:
                copied[table] = 0
                continue
            placeholders = ", ".join(["?"] * len(cols))
            dst.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                [tuple(row[col] for col in cols) for row in rows],
            )
            copied[table] = len(rows)
        dst.commit()
    return copied

