from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core_captures import ingest_capture, list_captures
from core_database import connect
from core_migrations import initialize_core_migrations


def payload(raw_text: str, key: str, *, capture_type: str | None = None, author_role: str = "user", metadata: dict | None = None) -> dict:
    value = {
        "raw_text": raw_text,
        "source": "chatgpt",
        "captured_at": "2026-09-14T10:00:00-07:00",
        "occurred_at": "2026-09-14T09:59:00-07:00",
        "request_id": f"req-{key}",
        "idempotency_key": key,
        "conversation_id": "conv-chat-class-test",
        "message_id": f"msg-{key}",
        "payload_version": 1,
        "author_role": author_role,
        "metadata": metadata or {},
    }
    if capture_type:
        value["capture_type"] = capture_type
    return value


class ChatCaptureClassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "chat-captures.db"
        initialize_core_migrations(self.db_path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_force_capture_replay_conflict_and_immutable_source(self) -> None:
        first = ingest_capture(self.db_path, payload("note: Home Sentinel camera failed after power change", "note-1"))
        duplicate = ingest_capture(self.db_path, payload("note: Home Sentinel camera failed after power change", "note-1"))
        conflict = None
        try:
            ingest_capture(self.db_path, payload("note: changed source text", "note-1"))
        except ValueError as exc:
            conflict = str(exc)
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["capture_id"], duplicate["capture_id"])
        self.assertEqual(first["derived_record_ids"], duplicate["derived_record_ids"])
        self.assertIn("conflict", conflict or "")
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT raw_text, capture_type, metadata_json FROM core_captures WHERE capture_id=?", (first["capture_id"],)).fetchone()
            self.assertEqual(row["raw_text"], "note: Home Sentinel camera failed after power change")
            self.assertEqual(row["capture_type"], "user_note")
            self.assertEqual(row["metadata_json"], '{"author_role":"user"}')

    def test_opt_out_has_no_capture(self) -> None:
        result = ingest_capture(self.db_path, payload("don't save this: temporary thought", "optout-1"))
        self.assertEqual(result["status"], "not_captured")
        with connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_captures").fetchone()[0], 0)

    def test_assistant_report_links_to_user_capture_and_retrieval_filters(self) -> None:
        source = ingest_capture(self.db_path, payload("note: camera outage needs follow-up", "source-1"))
        report = ingest_capture(
            self.db_path,
            payload(
                "The camera outage is a useful operational report with evidence and a next step.",
                "report-1",
                capture_type="assistant_report",
                author_role="assistant",
                metadata={
                    "report_type": "architecture_review",
                    "source_capture_ids": [source["capture_id"]],
                    "model_identity": "test-worker",
                    "verified_memory_content_commit": "content-test",
                    "project": "Info Analyzer",
                    "domain": "operations",
                },
            ),
        )
        self.assertEqual(report["capture"]["capture_type"], "assistant_report")
        self.assertEqual(report["capture"]["metadata"]["author_role"], "assistant")
        listed = list_captures(self.db_path, author_role="assistant", project="Info Analyzer")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["captures"][0]["capture_id"], report["capture_id"])
        self.assertIn("raw_text", listed["captures"][0])
        redacted = list_captures(self.db_path, author_role="assistant", include_raw_text=False)
        self.assertNotIn("raw_text", redacted["captures"][0])
        with connect(self.db_path) as conn:
            link = conn.execute(
                "SELECT relationship, derived_record_id FROM core_capture_derivations WHERE capture_id=? AND relationship='assistant_report'",
                (source["capture_id"],),
            ).fetchone()
            self.assertEqual(link["derived_record_id"], report["capture_id"])

    def test_existing_daily_capture_path_remains_day_linked(self) -> None:
        result = ingest_capture(self.db_path, payload("End of day report\n- completed work", "eod-1", capture_type="end_of_day_report"))
        self.assertEqual(result["capture"]["capture_type"], "end_of_day_report")
        self.assertTrue(result["day_case_id"])
        with connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_day_cases").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_captures").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
