from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import unittest

from core_database import connect as core_connect
from tests.support import request_json, start_server, stop_server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CriticalAlertQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def db_path(self) -> Path:
        return self.root / "alerts.db"

    def seed_signal(
        self,
        db_path: Path,
        *,
        signal_id: str,
        title: str,
        priority: str,
        actionability_score: float = 0.8,
        detected_at: str | None = None,
        updated_at: str | None = None,
        summary: str | None = None,
        recommended_action: str | None = None,
    ) -> None:
        stamp = detected_at or utc_now()
        with core_connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO core_signals (
                    signal_id, owner_system_id, signal_type, title, summary,
                    priority, confidence, actionability_score, status,
                    recommended_action, detected_at, metadata_json, created_at, updated_at
                ) VALUES (?, 'sys_info_analyzer', 'inbox_signal', ?, ?, ?, 0.95, ?, 'new', ?, ?, '{}', ?, ?)
                """,
                (
                    signal_id,
                    title,
                    summary or f"{title} summary",
                    priority,
                    actionability_score,
                    recommended_action or f"Review {title}",
                    stamp,
                    stamp,
                    updated_at or stamp,
                ),
            )

    def queue_alerts(self, port: int):
        status, body = request_json(port, "/alerts?limit=50")
        self.assertEqual(status, 200)
        return body

    def test_queue_policy_ordering_and_idempotency(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            self.seed_signal(
                db_path,
                signal_id="signal-p0",
                title="Critical P0",
                priority="P0",
                actionability_score=0.95,
                detected_at="2026-09-07T10:00:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-p1-old",
                title="Old actionable P1",
                priority="P1",
                actionability_score=0.88,
                detected_at="2026-09-07T10:01:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-p1-new",
                title="New actionable P1",
                priority="P1",
                actionability_score=0.82,
                detected_at="2026-09-07T10:03:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-p1-low",
                title="Low actionable P1",
                priority="P1",
                actionability_score=0.60,
                detected_at="2026-09-07T10:02:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-p2",
                title="Quiet P2",
                priority="P2",
                actionability_score=0.99,
                detected_at="2026-09-07T10:04:00.000Z",
            )

            first = self.queue_alerts(handle.port)
            self.assertEqual(first["sync"]["created"], 3)
            self.assertEqual(first["count"], 3)
            titles = [alert["title"] for alert in first["alerts"]]
            self.assertEqual(titles, ["Critical P0", "Old actionable P1", "New actionable P1"])
            self.assertEqual([alert["priority"] for alert in first["alerts"]], ["P0", "P1", "P1"])
            self.assertEqual(first["alerts"][0]["source_system_name"], "Info Analyzer")
            self.assertIn("recommended_action", first["alerts"][0])

            second = self.queue_alerts(handle.port)
            self.assertEqual(second["sync"]["created"], 0)
            self.assertEqual(second["count"], 3)

            with core_connect(db_path) as conn:
                duplicate_open = conn.execute(
                    """
                    SELECT signal_id, COUNT(*) AS count
                    FROM core_alerts
                    WHERE state IN ('queued', 'presented', 'acknowledged', 'snoozed', 'actioned', 'failed')
                    GROUP BY signal_id
                    HAVING COUNT(*) > 1
                    """
                ).fetchall()
                self.assertEqual(duplicate_open, [])
        finally:
            stop_server(handle)

    def test_state_transitions_and_legacy_action_preservation(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            self.seed_signal(
                db_path,
                signal_id="signal-ack",
                title="Acknowledge me",
                priority="P0",
                actionability_score=0.95,
                detected_at="2026-09-07T11:00:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-analyze",
                title="Analyze me",
                priority="P1",
                actionability_score=0.90,
                detected_at="2026-09-07T11:01:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-snooze",
                title="Snooze me",
                priority="P1",
                actionability_score=0.91,
                detected_at="2026-09-07T11:02:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-dismiss",
                title="Dismiss me",
                priority="P1",
                actionability_score=0.92,
                detected_at="2026-09-07T11:03:00.000Z",
            )
            self.seed_signal(
                db_path,
                signal_id="signal-convert",
                title="Convert me",
                priority="P1",
                actionability_score=0.93,
                detected_at="2026-09-07T11:04:00.000Z",
            )

            alerts = self.queue_alerts(handle.port)["alerts"]
            alert_ids = {alert["title"]: alert["alert_id"] for alert in alerts}

            with core_connect(db_path) as conn:
                legacy_before = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
                decisions_before = conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0]

            status, body = request_json(
                handle.port,
                f"/alerts/{alert_ids['Acknowledge me']}/respond",
                method="POST",
                payload={"response": "acknowledge", "decided_by": "human"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["alert"]["state"], "acknowledged")
            self.assertIsNotNone(body["decision"]["decision_id"])

            status, body = request_json(
                handle.port,
                f"/alerts/{alert_ids['Analyze me']}/respond",
                method="POST",
                payload={"response": "analyze", "decided_by": "human"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["alert"]["state"], "presented")

            future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            status, body = request_json(
                handle.port,
                f"/alerts/{alert_ids['Snooze me']}/respond",
                method="POST",
                payload={"response": "snooze", "snooze_until": future, "decided_by": "human"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["alert"]["state"], "snoozed")
            snoozed_id = alert_ids["Snooze me"]
            visible_after_snooze = self.queue_alerts(handle.port)["alerts"]
            self.assertNotIn(snoozed_id, {alert["alert_id"] for alert in visible_after_snooze})

            with core_connect(db_path) as conn:
                past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                conn.execute(
                    "UPDATE core_alerts SET snoozed_until=?, updated_at=? WHERE alert_id=?",
                    (
                        past,
                        past,
                        snoozed_id,
                    ),
                )
                conn.commit()
            resumed = self.queue_alerts(handle.port)["alerts"]
            resumed_map = {alert["alert_id"]: alert for alert in resumed}
            self.assertIn(snoozed_id, resumed_map)
            self.assertEqual(resumed_map[snoozed_id]["state"], "queued")

            status, body = request_json(
                handle.port,
                f"/alerts/{alert_ids['Dismiss me']}/respond",
                method="POST",
                payload={"response": "dismiss", "decided_by": "human"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["alert"]["state"], "dismissed")
            dismissed_id = alert_ids["Dismiss me"]
            after_dismiss = self.queue_alerts(handle.port)["alerts"]
            self.assertNotIn(dismissed_id, {alert["alert_id"] for alert in after_dismiss})

            with core_connect(db_path) as conn:
                decisions_before_invalid = conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0]
                legacy_mid = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]

            status, body = request_json(
                handle.port,
                f"/alerts/{alert_ids['Dismiss me']}/respond",
                method="POST",
                payload={"response": "acknowledge", "decided_by": "human"},
            )
            self.assertEqual(status, 400)
            self.assertIn("terminal", body["error"])

            with core_connect(db_path) as conn:
                decisions_after_invalid = conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0]
                legacy_after_invalid = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
            self.assertEqual(decisions_before_invalid, decisions_after_invalid)
            self.assertEqual(legacy_before, legacy_mid)
            self.assertEqual(legacy_mid, legacy_after_invalid)

            status, body = request_json(
                handle.port,
                f"/alerts/{alert_ids['Convert me']}/respond",
                method="POST",
                payload={"response": "convert_to_action", "decided_by": "human"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["alert"]["state"], "actioned")
            self.assertIsNotNone(body["action"]["action_id"])

            with core_connect(db_path) as conn:
                legacy_after = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
                core_actions = conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0]
                alert_decisions = conn.execute("SELECT COUNT(*) FROM core_alert_decisions").fetchone()[0]
                self.assertEqual(legacy_after, legacy_before)
                self.assertGreaterEqual(core_actions, 1)
                self.assertGreaterEqual(alert_decisions, 4)

            repeat_status, repeat_body = request_json(
                handle.port,
                f"/alerts/{alert_ids['Convert me']}/respond",
                method="POST",
                payload={"response": "convert_to_action", "decided_by": "human"},
            )
            self.assertEqual(repeat_status, 400)
            self.assertIn("terminal", repeat_body["error"])
        finally:
            stop_server(handle)


if __name__ == "__main__":
    unittest.main()
