"""Formal additive migrations for the normalized core database foundation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core_database import connect


PROJECT_ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def migration_version(path: Path) -> int:
    prefix = path.stem.split("_", 1)[0]
    if not prefix.isdigit():
        raise ValueError(f"migration filename must start with digits: {path.name}")
    return int(prefix)


def schema_migrations_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    return row is not None


def applied_versions(connection: sqlite3.Connection) -> set[int]:
    if not schema_migrations_table_exists(connection):
        return set()
    rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def initialize_core_migrations(database_path: Path) -> list[int]:
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    migration_paths = sorted(MIGRATIONS_DIR.glob("*.sql"), key=migration_version)
    if not migration_paths:
        raise RuntimeError(f"no core migrations found in {MIGRATIONS_DIR}")

    connection = connect(database_path)
    applied: list[int] = []
    try:
        # Clear any legacy transaction state before starting the migration batch.
        if connection.in_transaction:
            connection.commit()
        seen_versions = applied_versions(connection)
        for path in migration_paths:
            version = migration_version(path)
            if version in seen_versions:
                continue
            try:
                connection.executescript(path.read_text(encoding="utf-8"))
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            applied.append(version)
            seen_versions = applied_versions(connection)
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("foreign-key violations detected after core migration")
        return applied
    finally:
        connection.close()
