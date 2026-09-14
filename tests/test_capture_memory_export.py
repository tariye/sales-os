from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core_captures import ingest_capture
from core_database import connect as core_connect
from core_migrations import initialize_core_migrations
from tools import memory_manager


class CaptureMemoryExportTests(unittest.TestCase):
    def test_daily_capture_progress_is_sanitized_for_assistant_bundle(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        db_path = Path(tempdir.name) / "capture-memory.db"
        try:
            initialize_core_migrations(db_path)

            result = ingest_capture(
                db_path,
                {
                    "capture_type": "end_of_day_report",
                    "source": "chatgpt",
                    "raw_text": "End of day report\n- Memory export should include sanitized capture progress",
                    "occurred_at": "2026-09-13T20:30:00-07:00",
                    "captured_at": "2026-09-13T20:31:00-07:00",
                    "conversation_id": "conv-memory-export-test",
                    "message_id": "msg-memory-export-test",
                    "request_id": "req-memory-export-test",
                    "correlation_id": "corr-memory-export-test",
                    "idempotency_key": "memory-export-capture-001",
                    "payload_version": 1,
                    "metadata": {"fixture": True},
                },
            )
            self.assertTrue(result["ok"])

            with core_connect(db_path) as conn:
                progress = memory_manager.fetch_daily_progress(conn)
            self.assertEqual(progress["status"], "ok")
            self.assertEqual(progress["recent_captures"][0]["capture_id"], result["capture_id"])
            self.assertNotIn("raw_text", progress["recent_captures"][0])
            self.assertEqual(progress["day_cases"][0]["local_date"], "2026-09-13")

            bundle = memory_manager.build_assistant_bundle(
                "2026-09-13T21:00:00Z",
                entries=[],
                actions=[],
                patterns=[],
                watchlist=[],
                decisions=[],
                projects=[],
                manifest={"todays_highest_priorities": []},
                health={"export_success": True},
                entity_aliases={},
                daily_progress=progress,
            )
            self.assertIn("daily_capture_loop", bundle)
            self.assertEqual(bundle["daily_capture_loop"]["recent_captures"][0]["capture_id"], result["capture_id"])
            self.assertTrue(bundle["privacy_validation_passed"])
        finally:
            tempdir.cleanup()

    def test_publication_pointer_references_content_commit_without_self_reference(self) -> None:
        original_memory_dir = memory_manager.MEMORY_DIR
        tempdir = tempfile.TemporaryDirectory()
        try:
            memory_manager.MEMORY_DIR = Path(tempdir.name) / "memory"
            memory_manager.MEMORY_DIR.mkdir(parents=True)
            memory_manager.write_json(
                memory_manager.MEMORY_DIR / "assistant_bundle.json",
                {
                    "generated_at": "2026-09-13T21:00:00Z",
                    "privacy_validation_passed": True,
                },
            )
            memory_manager.write_json(
                memory_manager.MEMORY_DIR / "export_status.json",
                {"generated_at": "2026-09-13T21:00:00Z", "export_success": True},
            )
            memory_manager.write_json(
                memory_manager.MEMORY_DIR / "system_health.json",
                {"last_export": "2026-09-13T21:00:00Z"},
            )
            pointer = memory_manager.write_publication_pointer(content_commit="abc123", state="verified")
            self.assertEqual(pointer["publication_state"], "verified")
            self.assertEqual(pointer["content_commit"], "abc123")
            self.assertNotIn("pointer_commit", pointer)
            self.assertEqual(pointer["bundle_sha256"], memory_manager.file_sha256(memory_manager.MEMORY_DIR / "assistant_bundle.json"))
        finally:
            memory_manager.MEMORY_DIR = original_memory_dir
            tempdir.cleanup()

    def test_publication_health_anchors_verified_content_commit(self) -> None:
        health = memory_manager._build_publication_health(
            "2026-09-13T21:00:00Z",
            "run-1",
            {"status": "green", "age_minutes": 1},
            {"ok": True, "errors": []},
            True,
            current_stage="publication",
            publication_status="green",
            content_commit="content-sha",
            pointer_commit="pointer-sha",
            remote_head_sha="pointer-sha",
            remote_verified_at="2026-09-13T21:00:01Z",
        )
        self.assertEqual(health["publication"]["verified_content_commit"], "content-sha")
        self.assertEqual(health["publication"]["remote_head_at_content_verification"], "content-sha")
        self.assertEqual(health["publication"]["pointer_commit"], "pointer-sha")


if __name__ == "__main__":
    unittest.main()
