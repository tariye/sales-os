#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cutover_support import (
    ACTIVE_DB_PATH,
    BACKUPS_DIR,
    LEGACY_DB_PATH,
    MANIFEST_PATH,
    ensure_cutover_dirs,
    inventory_sqlite,
    backup_snapshot,
    write_json,
)


def _existing_sources(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.exists():
            out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", action="append", default=[], help="Original database path to inventory and snapshot")
    parser.add_argument("--active-db", default=str(ACTIVE_DB_PATH), help="Active App Support database path")
    parser.add_argument("--legacy-db", default=str(LEGACY_DB_PATH), help="Legacy archive database path")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH), help="Manifest output path")
    parser.add_argument("--reset-active", action="store_true", help="Remove any existing active database before initialization")
    parser.add_argument("--reset-legacy", action="store_true", help="Remove any existing legacy archive before copying source data")
    args = parser.parse_args()

    active_db = Path(args.active_db).expanduser()
    legacy_db = Path(args.legacy_db).expanduser()
    manifest_path = Path(args.manifest).expanduser()

    ensure_cutover_dirs()

    source_paths = _existing_sources(args.source_db)
    source_inventory = [inventory_sqlite(path, role="source") for path in source_paths]
    source_backups: list[str] = []
    for path in source_paths:
        snapshot = backup_snapshot(path, path.stem, BACKUPS_DIR)
        source_backups.append(str(snapshot))

    if args.reset_active and active_db.exists():
        backup = backup_snapshot(active_db, "active-before-reset", BACKUPS_DIR)
        active_db.unlink()
        source_backups.append(str(backup))
    if args.reset_legacy and legacy_db.exists():
        backup = backup_snapshot(legacy_db, "legacy-before-reset", BACKUPS_DIR)
        legacy_db.unlink()
        source_backups.append(str(backup))

    copied_legacy_from = ""
    if source_paths and not legacy_db.exists():
        legacy_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_paths[0], legacy_db)
        copied_legacy_from = str(source_paths[0])

    os.environ["INFO_ANALYZER_DB_PATH"] = str(active_db)
    import server  # noqa: WPS433

    server.init_db()
    active_inventory = inventory_sqlite(active_db, role="active")
    legacy_inventory = inventory_sqlite(legacy_db, role="legacy") if legacy_db.exists() else inventory_sqlite(legacy_db, role="legacy")

    manifest = {
        "generated_at": server.now_iso(),
        "active_db": active_inventory,
        "legacy_db": legacy_inventory,
        "original_sources": source_inventory,
        "source_backups": source_backups,
        "copied_legacy_from": copied_legacy_from,
        "manifest_path": str(manifest_path),
        "active_initialized": True,
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
