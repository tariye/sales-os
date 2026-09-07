from __future__ import annotations

import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import unittest

from core_database import connect as core_connect
from core_migrations import initialize_core_migrations

from tests.support import request_json, start_server, stop_server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def db_path(self) -> Path:
        return self.root / "events.db"

    def valid_payload(self, **overrides):
        payload = {
            "source_system_id": "sys_info_analyzer",
            "event_type": "file.created",
            "occurred_at": utc_now(),
            "dedupe_key": "dedupe-key-1",
            "priority": "P1",
            "confidence": 0.91,
            "payload": {"path": "Inbox/test.txt"},
        }
        payload.update(overrides)
        return payload

    def test_event_authentication_and_missing_key_configuration(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key=None)
        try:
            status, body = request_json(handle.port, "/events", method="POST", payload=self.valid_payload())
            self.assertEqual(status, 503)
            self.assertIn("INFO_ANALYZER_API_KEY", body["error"])
        finally:
            stop_server(handle)

        handle = start_server(db_path, api_key="super-secret-token")
        try:
            status, body = request_json(handle.port, "/events", method="POST", payload=self.valid_payload())
            self.assertEqual(status, 401)
            self.assertIn("Bearer authentication", body["error"])

            status, body = request_json(
                handle.port,
                "/events",
                method="POST",
                payload=self.valid_payload(),
                headers={"Authorization": "Bearer wrong-token"},
            )
            self.assertEqual(status, 401)
            self.assertIn("Invalid bearer token", body["error"])

            with core_connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT event_type, payload FROM audit_log WHERE entity_type='core_event' ORDER BY created_at ASC"
                ).fetchall()
                event_types = {row["event_type"] for row in rows}
                payload_text = "\n".join(row["payload"] for row in rows)
                self.assertIn("auth_failed", event_types)
                self.assertNotIn("super-secret-token", payload_text)
        finally:
            stop_server(handle)

    def test_event_validation_and_deduplication(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="super-secret-token")
        try:
            auth = {"Authorization": "Bearer super-secret-token"}

            invalid_cases = [
                ({}, 400, "missing required fields"),
                (self.valid_payload(extra_field=True), 400, "unknown fields"),
                (self.valid_payload(occurred_at="not-a-timestamp"), 400, "timezone-aware"),
                (self.valid_payload(priority="urgent"), 400, "P0, P1, or P2"),
                (self.valid_payload(confidence=1.2), 400, "between 0 and 1"),
                (self.valid_payload(payload="not-an-object"), 400, "payload must be a JSON object"),
                (self.valid_payload(source_system_id="missing-system"), 404, "source system"),
            ]
            for payload, expected_status, message in invalid_cases:
                with self.subTest(payload=payload):
                    status, body = request_json(
                        handle.port,
                        "/events",
                        method="POST",
                        payload=payload,
                        headers=auth,
                    )
                    self.assertEqual(status, expected_status)
                    self.assertIn(message, body["error"])

            too_large = self.valid_payload(payload={"blob": "x" * (256 * 1024)})
            status, body = request_json(
                handle.port,
                "/events",
                method="POST",
                payload=too_large,
                headers=auth,
            )
            self.assertEqual(status, 413)
            self.assertIn("too large", body["error"])

            valid_payload = self.valid_payload(
                dedupe_key="event-dedupe-1",
                entity_id=None,
                source_ref="Inbox/test.txt",
            )
            status, body = request_json(
                handle.port,
                "/events",
                method="POST",
                payload=valid_payload,
                headers=auth,
            )
            self.assertEqual(status, 201)
            self.assertTrue(body["success"])
            self.assertTrue(body["created"])
            self.assertFalse(body["duplicate"])
            first_event = body["event"]
            self.assertEqual(first_event["source_system_id"], "sys_info_analyzer")
            self.assertTrue(first_event["occurred_at"].endswith("Z"))

            duplicate_status, duplicate_body = request_json(
                handle.port,
                "/events",
                method="POST",
                payload=valid_payload,
                headers=auth,
            )
            self.assertEqual(duplicate_status, 200)
            self.assertFalse(duplicate_body["created"])
            self.assertTrue(duplicate_body["duplicate"])
            self.assertEqual(duplicate_body["event"]["event_id"], first_event["event_id"])

            other_system = self.valid_payload(
                source_system_id="sys_groove",
                dedupe_key="event-dedupe-1",
                source_ref="Inbox/test.txt",
            )
            other_status, other_body = request_json(
                handle.port,
                "/events",
                method="POST",
                payload=other_system,
                headers=auth,
            )
            self.assertEqual(other_status, 201)
            self.assertTrue(other_body["created"])
            self.assertNotEqual(other_body["event"]["event_id"], first_event["event_id"])

            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO core_events (
                            event_id, source_system_id, event_type, occurred_at,
                            received_at, priority, confidence, processing_status,
                            payload_json, created_at
                        ) VALUES (
                            'EVT-FOREIGN-KEY-FAIL', 'missing-system', 'file.created',
                            ?, ?, 'P1', 0.9, 'new', '{}', ?
                        )
                        """,
                        (utc_now(), utc_now(), utc_now()),
                    )

                audit_rows = conn.execute(
                    "SELECT event_type, payload FROM audit_log WHERE entity_type='core_event' ORDER BY created_at ASC"
                ).fetchall()
                payload_text = "\n".join(row["payload"] for row in audit_rows)
                event_types = {row["event_type"] for row in audit_rows}
                self.assertNotIn("super-secret-token", payload_text)
                self.assertIn("event_accepted", event_types)
                self.assertIn("duplicate_event_received", event_types)
                self.assertIn("validation_failed", event_types)
        finally:
            stop_server(handle)

    def test_event_body_size_limit_and_audit_without_secret_leakage(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="super-secret-token")
        try:
            auth = {"Authorization": "Bearer super-secret-token"}
            big_payload = self.valid_payload(payload={"blob": "y" * (300 * 1024)})
            status, body = request_json(
                handle.port,
                "/events",
                method="POST",
                payload=big_payload,
                headers=auth,
            )
            self.assertEqual(status, 413)
            self.assertIn("too large", body["error"])
        finally:
            stop_server(handle)


if __name__ == "__main__":
    unittest.main()
