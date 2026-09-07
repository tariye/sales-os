from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import unittest

from core_database import connect as core_connect
from integrations.home_sentinel_producer import HomeSentinelProducer
from tests.support import request_json, start_server, stop_server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class HomeSentinelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def db_path(self) -> Path:
        return self.root / "home_sentinel.db"

    def event_payload(self, *, event_type: str, dedupe_key: str, payload: dict) -> dict:
        return {
            "source_system_id": "sys_home_sentinel",
            "event_type": event_type,
            "occurred_at": utc_now(),
            "dedupe_key": dedupe_key,
            "priority": "P2",
            "confidence": 0.92,
            "source_ref": dedupe_key,
            "payload": payload,
        }

    def post_event(self, handle, payload):
        return request_json(
            handle.port,
            "/events",
            method="POST",
            payload=payload,
            headers={"Authorization": "Bearer test-key"},
        )

    def fetch_counts(self, db_path: Path) -> tuple[int, int, int]:
        with core_connect(db_path) as conn:
            return (
                conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0],
            )

    def test_camera_health_states_route_correctly(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            offline = self.event_payload(
                event_type="camera_health_changed",
                dedupe_key="home-offline-1",
                payload={"camera_name": "Front Door", "status": "offline"},
            )
            status, body = self.post_event(handle, offline)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "camera_offline")
            self.assertEqual(body["effects"][0]["priority"], "P0")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            degraded = self.event_payload(
                event_type="camera_health_changed",
                dedupe_key="home-degraded-1",
                payload={"camera_name": "Garage", "status": "degraded", "metrics": {"fps": 8}},
            )
            status, body = self.post_event(handle, degraded)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "camera_degraded")
            self.assertEqual(body["effects"][0]["priority"], "P1")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            recovered = self.event_payload(
                event_type="camera_health_changed",
                dedupe_key="home-recovered-1",
                payload={"camera_name": "Garage", "status": "recovered"},
            )
            status, body = self.post_event(handle, recovered)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "camera_recovered")
            self.assertEqual(body["effects"][0]["priority"], "P2")
            self.assertEqual(len(body["effects"]), 1)

            healthy = self.event_payload(
                event_type="camera_health_changed",
                dedupe_key="home-healthy-1",
                payload={"camera_name": "Porch", "status": "healthy"},
            )
            status, body = self.post_event(handle, healthy)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "camera_recovered")
            self.assertEqual(body["effects"][0]["priority"], "P2")
            self.assertEqual(len(body["effects"]), 1)

            with core_connect(db_path) as conn:
                counts = {
                    "events": conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0],
                    "signals": conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0],
                    "alerts": conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0],
                    "legacy_live_signals": conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0],
                }
            self.assertEqual(counts["events"], 4)
            self.assertEqual(counts["signals"], 4)
            self.assertEqual(counts["alerts"], 2)
            self.assertEqual(counts["legacy_live_signals"], 0)
        finally:
            stop_server(handle)

    def test_detection_states_route_correctly(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            unexpected = self.event_payload(
                event_type="detection_observed",
                dedupe_key="home-unexpected-1",
                payload={
                    "detection_type": "person",
                    "camera_name": "Driveway",
                    "detection_confidence": 0.98,
                    "zone": "driveway",
                    "expected": False,
                    "image_ref": "capture://driveway/1",
                },
            )
            status, body = self.post_event(handle, unexpected)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "unexpected_person_detected")
            self.assertEqual(body["effects"][0]["priority"], "P0")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            uncertain = self.event_payload(
                event_type="detection_observed",
                dedupe_key="home-uncertain-1",
                payload={
                    "detection_type": "person",
                    "camera_name": "Driveway",
                    "detection_confidence": 0.71,
                    "zone": "driveway",
                },
            )
            status, body = self.post_event(handle, uncertain)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "person_verification_required")
            self.assertEqual(body["effects"][0]["priority"], "P1")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            expected = self.event_payload(
                event_type="detection_observed",
                dedupe_key="home-expected-1",
                payload={
                    "detection_type": "person",
                    "camera_name": "Driveway",
                    "detection_confidence": 0.95,
                    "zone": "driveway",
                    "expected": True,
                },
            )
            status, body = self.post_event(handle, expected)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "expected_person_detected")
            self.assertEqual(body["effects"][0]["priority"], "P2")
            self.assertEqual(len(body["effects"]), 1)

            motion = self.event_payload(
                event_type="detection_observed",
                dedupe_key="home-motion-1",
                payload={
                    "detection_type": "motion",
                    "camera_name": "Porch",
                    "detection_confidence": 0.60,
                    "zone": "front porch",
                },
            )
            status, body = self.post_event(handle, motion)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "motion_observed")
            self.assertEqual(body["effects"][0]["priority"], "P2")
            self.assertEqual(len(body["effects"]), 1)

            with core_connect(db_path) as conn:
                counts = {
                    "events": conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0],
                    "signals": conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0],
                    "alerts": conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0],
                    "legacy_live_signals": conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0],
                }
            self.assertEqual(counts["events"], 4)
            self.assertEqual(counts["signals"], 4)
            self.assertEqual(counts["alerts"], 2)
            self.assertEqual(counts["legacy_live_signals"], 0)
        finally:
            stop_server(handle)

    def test_duplicate_delivery_creates_one_event_signal_and_alert(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            payload = self.event_payload(
                event_type="camera_health_changed",
                dedupe_key="home-duplicate-1",
                payload={"camera_name": "Garage", "status": "offline"},
            )
            first_status, first_body = self.post_event(handle, payload)
            second_status, second_body = self.post_event(handle, payload)
            self.assertEqual(first_status, 201)
            self.assertEqual(second_status, 200)
            self.assertTrue(second_body["duplicate"])
            self.assertEqual(first_body["event"]["event_id"], second_body["event"]["event_id"])

            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0], 1)
        finally:
            stop_server(handle)

    def test_producer_to_http_endpoint_and_network_failure(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            producer = HomeSentinelProducer(
                base_url=f"http://127.0.0.1:{handle.port}",
                api_key="test-key",
                timeout_seconds=2.0,
            )
            result = producer.publish_detection(
                local_event_id="producer-local-1",
                occurred_at=utc_now(),
                camera_name="Driveway",
                detection_type="person",
                detection_confidence=0.99,
                zone="driveway",
                expected=False,
                image_ref="capture://driveway/producer-1",
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.delivered)
            self.assertIsNotNone(result.event_id)
            self.assertIsNotNone(result.signal_id)
            self.assertIsNotNone(result.alert_id)

            with core_connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT s.signal_type, s.priority, s.metadata_json, e.source_ref
                    FROM core_signals AS s
                    JOIN core_signal_events AS se ON se.signal_id = s.signal_id
                    JOIN core_events AS e ON e.event_id = se.event_id
                    WHERE se.event_id = ?
                    """,
                    (result.event_id,),
                ).fetchone()
                self.assertEqual(row["signal_type"], "unexpected_person_detected")
                self.assertEqual(row["priority"], "P0")
                self.assertEqual(row["source_ref"], "producer-local-1")

            failing = HomeSentinelProducer(
                base_url="http://127.0.0.1:6553",
                api_key="test-key",
                timeout_seconds=0.25,
            )
            failure = failing.publish_camera_health(
                local_event_id="producer-local-2",
                occurred_at=utc_now(),
                camera_name="Garage",
                status="offline",
            )
            self.assertFalse(failure.ok)
            self.assertFalse(failure.delivered)
            self.assertIsNotNone(failure.error)
        finally:
            stop_server(handle)

    def test_unrelated_event_is_stored_without_dispatch(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            payload = {
                "source_system_id": "sys_info_analyzer",
                "event_type": "note_added",
                "occurred_at": utc_now(),
                "dedupe_key": "home-unrelated-1",
                "priority": "P2",
                "confidence": 0.5,
                "payload": {"message": "hello"},
            }
            status, body = self.post_event(handle, payload)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"], [])
            self.assertEqual(body["event"]["processing_status"], "new")
            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0], 0)
        finally:
            stop_server(handle)


if __name__ == "__main__":
    unittest.main()
