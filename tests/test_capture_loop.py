from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core_database import connect as core_connect
from tests.support import request_json, start_server, stop_server


def capture_payload(**overrides):
    payload = {
        "capture_type": "end_of_day_report",
        "source": "chatgpt",
        "raw_text": "End of day report\n- Capture API route proved durable receipt\n- Next: publish verified memory bundle",
        "occurred_at": "2026-09-13T20:30:00-07:00",
        "captured_at": "2026-09-13T20:31:00-07:00",
        "conversation_id": "conv-http-capture-test",
        "message_id": "msg-http-capture-test",
        "request_id": "req-http-capture-test",
        "correlation_id": "corr-http-capture-test",
        "idempotency_key": "http-capture-loop-001",
        "payload_version": 1,
        "metadata": {"fixture": True},
    }
    payload.update(overrides)
    return payload


class CaptureLoopApiTests(unittest.TestCase):
    def test_capture_endpoint_requires_auth_and_preserves_idempotency(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        db_path = Path(tempdir.name) / "capture-api.db"
        handle = start_server(db_path, api_key="test-key")
        try:
            with core_connect(db_path) as conn:
                before = self.counts(conn)

            missing_status, missing_body = request_json(handle.port, "/captures", method="POST", payload=capture_payload())
            self.assertEqual(missing_status, 401)
            self.assertIn("Invalid or missing API key", missing_body["error"]["message"])
            with core_connect(db_path) as conn:
                self.assertEqual(self.counts(conn), before)

            status, body = request_json(
                handle.port,
                "/captures",
                method="POST",
                payload=capture_payload(),
                headers={"Authorization": "Bearer test-key"},
            )
            self.assertEqual(status, 201)
            self.assertTrue(body["success"])
            self.assertFalse(body["duplicate"])
            capture_id = body["capture_id"]
            self.assertTrue(capture_id.startswith("CAP-"))
            self.assertEqual(body["capture"]["processing_state"], "processed")
            self.assertEqual(body["capture"]["raw_text"], capture_payload()["raw_text"])

            retry_status, retry_body = request_json(
                handle.port,
                "/captures",
                method="POST",
                payload=capture_payload(),
                headers={"Authorization": "Bearer test-key"},
            )
            self.assertEqual(retry_status, 200)
            self.assertTrue(retry_body["duplicate"])
            self.assertEqual(retry_body["capture_id"], capture_id)

            conflict_status, conflict_body = request_json(
                handle.port,
                "/captures",
                method="POST",
                payload=capture_payload(raw_text="End of day report\n- Different immutable payload"),
                headers={"Authorization": "Bearer test-key"},
            )
            self.assertEqual(conflict_status, 400)
            self.assertIn("conflict", conflict_body["error"])

            with core_connect(db_path) as conn:
                after = self.counts(conn)
                self.assertEqual(after["core_captures"], before["core_captures"] + 1)
                self.assertEqual(after["actions"], before["actions"])
                self.assertEqual(after["live_signals"], before["live_signals"])
        finally:
            stop_server(handle)
            tempdir.cleanup()

    def counts(self, conn):
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        result = {}
        for name in ["core_captures", "core_signals", "core_actions", "actions", "live_signals"]:
            result[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] if name in tables else 0
        return result


if __name__ == "__main__":
    unittest.main()
