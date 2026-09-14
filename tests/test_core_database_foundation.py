from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import socket
from pathlib import Path

import unittest

from core_database import connect as core_connect
from core_migrations import MIGRATIONS_DIR, initialize_core_migrations


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DB = PROJECT_ROOT / "data" / "info_analyzer.db"


LEGACY_TABLES = [
    "actions",
    "api_idempotency",
    "audit_log",
    "decision_reviews",
    "decision_rules",
    "device_log_catalog",
    "entity_aliases",
    "entries",
    "entries_fts",
    "entries_fts_config",
    "entries_fts_content",
    "entries_fts_data",
    "entries_fts_docsize",
    "entries_fts_idx",
    "import_batches",
    "import_rows",
    "import_sheets",
    "ingest_items",
    "ingest_sources",
    "ledger_decisions",
    "ledger_projects",
    "listening_extractions",
    "listening_projects",
    "live_signals",
    "pattern_runs",
    "pattern_stats",
    "portfolio_trades",
    "pull_rules",
    "relationships",
    "risk_reward_setups",
    "surfaced_cards",
    "watchlist_items",
    "watchlists",
]

BOOTSTRAP_TABLES = [
    table for table in LEGACY_TABLES if table not in {"ledger_decisions", "ledger_projects"}
]


def read_counts(database_path: Path, tables: list[str]) -> dict[str, int]:
    conn = sqlite3.connect(database_path)
    try:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    finally:
        conn.close()


def table_names(database_path: Path) -> set[str]:
    conn = sqlite3.connect(database_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def view_names(database_path: Path) -> set[str]:
    conn = sqlite3.connect(database_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def open_connection(database_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def bootstrap_legacy_and_reload(db_path: Path):
    os.environ["INFO_ANALYZER_DB_PATH"] = str(db_path)
    if "server" in sys.modules:
        server = importlib.reload(sys.modules["server"])
    else:
        import server  # type: ignore

        server = server  # type: ignore
    return server


def start_legacy_server(db_path: Path) -> tuple[subprocess.Popen[str], int]:
    env = os.environ.copy()
    env["INFO_ANALYZER_DB_PATH"] = str(db_path)
    env["PYTHONUNBUFFERED"] = "1"
    for port in tuple(range(8150, 8180)):
        proc = subprocess.Popen(
            [sys.executable, "-u", "server.py", "--host", "127.0.0.1", "--port", str(port)],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        health_deadline = time.time() + 30
        while time.time() < health_deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                    if response.status == 200:
                        return proc, port
            except Exception:
                time.sleep(0.2)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    raise AssertionError("server did not report a listening port")


class CoreDatabaseFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def fresh_db_path(self, name: str = "fresh.db") -> Path:
        return self.root / name

    def canonical_copy(self, name: str = "copy.db") -> Path:
        target = self.root / name
        target.write_bytes(CANONICAL_DB.read_bytes())
        return target

    def test_fresh_v03_database_can_initialize(self) -> None:
        db_path = self.fresh_db_path()
        server = bootstrap_legacy_and_reload(db_path)
        server.init_db()
        names = table_names(db_path)
        self.assertIn("schema_migrations", names)
        self.assertIn("core_systems", names)
        self.assertIn("core_actions", names)
        self.assertEqual(
            open_connection(db_path).execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
            5,
        )

    def test_existing_v03_database_can_receive_core_migration(self) -> None:
        db_path = self.canonical_copy()
        before = read_counts(db_path, LEGACY_TABLES)
        existing_versions = [
            row["version"]
            for row in open_connection(db_path).execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        applied = initialize_core_migrations(db_path)
        after = read_counts(db_path, LEGACY_TABLES)
        self.assertEqual(applied, [version for version in [1, 2, 3, 4, 5] if version not in existing_versions])
        self.assertEqual(before, after)
        names = view_names(db_path)
        self.assertIn("core_record_links", table_names(db_path))
        self.assertIn("innbank_allocation_plans", table_names(db_path))
        self.assertIn("core_source_observations", table_names(db_path))
        self.assertIn("core_notification_delivery_results", table_names(db_path))
        self.assertIn("core_captures", table_names(db_path))
        self.assertIn("core_day_cases", table_names(db_path))
        self.assertIn("v_core_open_alerts", names)
        self.assertIn("v_core_learning_loop", names)

    def test_initialization_is_idempotent(self) -> None:
        db_path = self.fresh_db_path("idempotent.db")
        server = bootstrap_legacy_and_reload(db_path)
        server.init_db()
        first_counts = read_counts(db_path, BOOTSTRAP_TABLES)
        server.init_db()
        second_counts = read_counts(db_path, BOOTSTRAP_TABLES)
        conn = open_connection(db_path)
        try:
            migration_count = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
            ).fetchone()[0]
            version_two_count = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 2"
            ).fetchone()[0]
            version_three_count = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 3"
            ).fetchone()[0]
            version_four_count = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 4"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(first_counts, second_counts)
        self.assertEqual(migration_count, 1)
        self.assertEqual(version_two_count, 1)
        self.assertEqual(version_three_count, 1)
        self.assertEqual(version_four_count, 1)

    def test_legacy_tables_remain_present_and_readable(self) -> None:
        db_path = self.canonical_copy("legacy-readable.db")
        initialize_core_migrations(db_path)
        names = table_names(db_path)
        for table in LEGACY_TABLES:
            self.assertIn(table, names)
        conn = open_connection(db_path)
        try:
            self.assertIsNotNone(conn.execute("SELECT id FROM entries LIMIT 1").fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM ledger_decisions LIMIT 1").fetchone())
        finally:
            conn.close()

    def test_legacy_actions_schema_and_behavior_remain_unchanged(self) -> None:
        db_path = self.canonical_copy("legacy-actions.db")
        initialize_core_migrations(db_path)
        conn = core_connect(db_path)
        try:
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(actions)").fetchall()]
            self.assertEqual(
                columns,
                [
                    "id",
                    "created_at",
                    "updated_at",
                    "entry_id",
                    "action_title",
                    "why",
                    "track_metric",
                    "due_date",
                    "priority",
                    "status",
                    "result",
                    "lesson_update",
                    "metadata",
                ],
            )
            entry_id = conn.execute("SELECT id FROM entries LIMIT 1").fetchone()[0]
            conn.execute(
                """
                INSERT INTO actions
                (id, created_at, updated_at, entry_id, action_title, status, metadata)
                VALUES ('LEGACY-ACTION-TEST', '2026-09-06T00:00:00Z', '2026-09-06T00:00:00Z',
                        ?, 'Legacy action still works', 'open', '{}')
                """,
                (entry_id,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT action_title, status FROM actions WHERE id = 'LEGACY-ACTION-TEST'"
            ).fetchone()
            self.assertEqual(tuple(row), ("Legacy action still works", "open"))
        finally:
            conn.close()

    def test_canonical_connection_enforces_foreign_keys_and_legacy_behavior(self) -> None:
        db_path = self.canonical_copy("helper.db")
        initialize_core_migrations(db_path)
        with core_connect(db_path) as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
        with core_connect(db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO core_actions (
                        action_id, decision_id, owner_system_id, action_type, title,
                        status, execution_mode, metadata_json
                    ) VALUES ('bad-helper-action', 'missing-decision', 'sys_info_analyzer',
                              'test_action', 'Bad helper action', 'proposed', 'manual', '{}')
                    """
                )
        with core_connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO core_signals (
                    signal_id, owner_system_id, signal_type, title, summary,
                    priority, confidence, actionability_score, status,
                    recommended_action, metadata_json
                ) VALUES (
                    'helper-signal', 'sys_info_analyzer', 'test_signal',
                    'Helper signal', 'Helper signal summary', 'P1', 0.9, 0.8, 'new',
                    'Review the signal', '{}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO core_decisions (
                    decision_id, signal_id, decision_type, selected_option,
                    rationale, decided_by, metadata_json
                ) VALUES (
                    'helper-decision', 'helper-signal', 'approve', 'approve',
                    'Approved for helper test', 'human', '{}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO core_actions (
                    action_id, decision_id, owner_system_id, action_type,
                    title, status, execution_mode, metadata_json
                ) VALUES (
                    'helper-action', 'helper-decision', 'sys_info_analyzer',
                    'test_action', 'Helper action', 'proposed', 'manual', '{}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO actions
                (id, created_at, updated_at, entry_id, action_title, status, metadata)
                VALUES ('LEGACY-HELPER-ACTION', '2026-09-06T00:00:00Z',
                        '2026-09-06T00:00:00Z',
                        (SELECT id FROM entries LIMIT 1),
                        'Legacy helper action still works', 'open', '{}')
                """
            )
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM core_actions WHERE action_id='helper-action'").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM actions WHERE id='LEGACY-HELPER-ACTION'").fetchone()[0],
                1,
            )

    def test_core_actions_have_normalized_lifecycle_schema(self) -> None:
        db_path = self.canonical_copy("core-actions.db")
        initialize_core_migrations(db_path)
        conn = open_connection(db_path)
        try:
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(core_actions)").fetchall()]
            self.assertIn("decision_id", columns)
            self.assertIn("owner_system_id", columns)
            self.assertIn("action_type", columns)
            self.assertIn("execution_mode", columns)
            self.assertIn("metadata_json", columns)
            conn.execute(
                """
                INSERT INTO core_signals (
                    signal_id, owner_system_id, signal_type, title, summary,
                    priority, confidence, actionability_score, status,
                    recommended_action, metadata_json
                ) VALUES (
                    'core-signal-test', 'sys_info_analyzer', 'test_signal',
                    'Core signal', 'Core signal summary', 'P1', 0.9, 0.8, 'new',
                    'Review the signal', '{}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO core_decisions (
                    decision_id, signal_id, decision_type, selected_option,
                    rationale, decided_by, metadata_json
                ) VALUES (
                    'core-decision-test', 'core-signal-test', 'approve', 'approve',
                    'Approved for test', 'human', '{}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO core_actions (
                    action_id, decision_id, owner_system_id, action_type,
                    title, status, execution_mode, metadata_json
                ) VALUES (
                    'core-action-test', 'core-decision-test', 'sys_info_analyzer',
                    'test_action', 'Core action', 'proposed', 'manual', '{}'
                )
                """
            )
            conn.commit()
            row = conn.execute(
                "SELECT status, execution_mode FROM core_actions WHERE action_id='core-action-test'"
            ).fetchone()
            self.assertEqual(tuple(row), ("proposed", "manual"))
        finally:
            conn.close()

    def test_core_foreign_keys_json_and_state_constraints_work(self) -> None:
        db_path = self.canonical_copy("constraints.db")
        initialize_core_migrations(db_path)
        conn = open_connection(db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO core_actions (
                        action_id, decision_id, owner_system_id, action_type, title,
                        status, execution_mode, metadata_json
                    ) VALUES ('bad-action', 'missing-decision', 'sys_info_analyzer',
                              'test_action', 'Bad action', 'proposed', 'manual', '{}')
                    """
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO core_signals (
                        signal_id, owner_system_id, signal_type, title, summary,
                        priority, confidence, actionability_score, status,
                        recommended_action, metadata_json
                    ) VALUES ('bad-json-signal', 'sys_info_analyzer', 'test_signal',
                              'Bad JSON', 'Bad JSON', 'P1', 0.8, 0.7, 'new',
                              'Review', '{')
                    """
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO core_signals (
                        signal_id, owner_system_id, signal_type, title, summary,
                        priority, confidence, actionability_score, status,
                        recommended_action, metadata_json
                    ) VALUES ('bad-priority', 'sys_info_analyzer', 'test_signal',
                              'Bad Priority', 'Bad Priority', 'urgent', 0.8, 0.7, 'new',
                              'Review', '{}')
                    """
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO core_actions (
                        action_id, owner_system_id, action_type, title, status,
                        execution_mode, metadata_json
                    ) VALUES ('bad-status', 'sys_info_analyzer', 'test_action',
                              'Bad Status', 'weird', 'manual', '{}')
                    """
                )
        finally:
            conn.close()

    def test_integrity_and_fk_checks_pass_after_core_migration(self) -> None:
        db_path = self.canonical_copy("integrity.db")
        initialize_core_migrations(db_path)
        conn = open_connection(db_path)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_failed_migration_rolls_back_completely(self) -> None:
        broken_dir = self.root / "broken_migrations"
        broken_dir.mkdir()
        (broken_dir / "001_broken.sql").write_text(
            """
            PRAGMA foreign_keys = ON;
            BEGIN IMMEDIATE;
            CREATE TABLE broken_core_table (
                id TEXT PRIMARY KEY,
                metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
            );
            INSERT INTO broken_core_table (id, metadata_json) VALUES ('x', '{');
            INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (1, 'broken');
            COMMIT;
            """,
            encoding="utf-8",
        )
        import core_migrations as migrations_module

        original_dir = migrations_module.MIGRATIONS_DIR
        migrations_module.MIGRATIONS_DIR = broken_dir
        db_path = self.fresh_db_path("broken.db")
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                migrations_module.initialize_core_migrations(db_path)
        finally:
            migrations_module.MIGRATIONS_DIR = original_dir
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertNotIn("broken_core_table", tables)
        self.assertNotIn("schema_migrations", tables)

    def test_migration_application_is_recorded_exactly_once(self) -> None:
        db_path = self.canonical_copy("recorded-once.db")
        existing_versions = [
            row["version"]
            for row in open_connection(db_path).execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        first = initialize_core_migrations(db_path)
        second = initialize_core_migrations(db_path)
        conn = open_connection(db_path)
        try:
            rows = conn.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        finally:
            conn.close()
        self.assertEqual(first, [version for version in [1, 2, 3, 4, 5] if version not in existing_versions])
        self.assertEqual(second, [])
        self.assertEqual(
            [(row["version"], row["name"]) for row in rows],
            [
                (1, "core_foundation"),
                (2, "innbank_allocation_and_routing"),
                (3, "payday_intake_notification_reliability"),
                (4, "capture_loop_foundation"),
                (5, "chat_capture_classes"),
            ],
        )

    def test_existing_v03_apis_and_ui_still_start(self) -> None:
        db_path = self.fresh_db_path("startup.db")
        proc, port = start_legacy_server(db_path)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as response:
                self.assertEqual(response.status, 200)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/command", timeout=10) as response:
                self.assertEqual(response.status, 200)
                body = response.read().decode("utf-8")
                self.assertIn('"cockpit"', body)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
                self.assertEqual(response.status, 200)
                body = response.read().decode("utf-8")
                self.assertIn("Info Analyzer", body)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
