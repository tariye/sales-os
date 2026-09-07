from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import unittest

from core_database import connect as core_connect
from tests.support import request_json, start_server, stop_server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class InnbankPaydayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def db_path(self) -> Path:
        return self.root / "innbank.db"

    def event_payload(self, **overrides):
        payload = {
            "source_system_id": "sys_innbank",
            "event_type": "financial_inflow_posted",
            "occurred_at": utc_now(),
            "dedupe_key": "innbank-dedupe-1",
            "priority": "P0",
            "confidence": 0.98,
            "payload": {
                "amount": "2500.00",
                "currency": "USD",
                "account_name": "Primary Checking",
                "classification": "paycheck",
                "classification_confidence": 0.97,
                "transaction_ref": "payref-001",
            },
        }
        payload.update(overrides)
        if "payload" in overrides:
            payload["payload"] = overrides["payload"]
        return payload

    def post_event(self, handle, payload):
        return request_json(
            handle.port,
            "/events",
            method="POST",
            payload=payload,
            headers={"Authorization": "Bearer test-key"},
        )

    def signal_and_alert_counts(self, db_path: Path) -> tuple[int, int, int]:
        with core_connect(db_path) as conn:
            events = conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0]
            signals = conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0]
            alerts = conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0]
        return events, signals, alerts

    def test_confirmed_payroll_and_earned_income_create_signal_and_alert(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            for classification in ("payroll", "earned_income"):
                payload = self.event_payload(
                    dedupe_key=f"dedupe-{classification}",
                    payload={
                        "amount": "3125.50",
                        "currency": "USD",
                        "account_name": "Primary Checking",
                        "classification": classification,
                        "classification_confidence": 0.99,
                        "transaction_ref": f"tx-{classification}",
                    },
                )
                status, body = self.post_event(handle, payload)
                self.assertEqual(status, 201)
                self.assertTrue(body["success"])
                self.assertEqual(body["effects"][0]["type"], "core_signal_created")
                self.assertEqual(body["effects"][1]["type"], "critical_alert_created")
                self.assertEqual(body["event"]["processing_status"], "processed")
                with core_connect(db_path) as conn:
                    signal = conn.execute(
                        "SELECT signal_type, priority, actionability_score, title, summary, rationale, recommended_action FROM core_signals WHERE signal_id=?",
                        (body["effects"][0]["signal_id"],),
                    ).fetchone()
                    alert = conn.execute(
                        "SELECT state, priority FROM core_alerts WHERE alert_id=?",
                        (body["effects"][1]["alert_id"],),
                    ).fetchone()
                self.assertEqual(signal["signal_type"], "paycheck_received")
                self.assertEqual(signal["priority"], "P0")
                self.assertEqual(float(signal["actionability_score"]), 1.0)
                self.assertIn("Confirmed deployable income", signal["summary"])
                self.assertIn("Review the protected cash floor", signal["recommended_action"])
                self.assertEqual(alert["state"], "queued")
                self.assertEqual(alert["priority"], "P0")
        finally:
            stop_server(handle)

    def test_non_deployable_inflows_are_ignored(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            for classification in ("internal_transfer", "refund"):
                payload = self.event_payload(
                    dedupe_key=f"ignore-{classification}",
                    payload={
                        "amount": "100.00",
                        "currency": "USD",
                        "account_name": "Primary Checking",
                        "classification": classification,
                        "classification_confidence": 0.88,
                    },
                )
                status, body = self.post_event(handle, payload)
                self.assertEqual(status, 201)
                self.assertEqual(body["event"]["processing_status"], "ignored")
                self.assertEqual(body["effects"][0]["type"], "inflow_ignored")
                with core_connect(db_path) as conn:
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0],
                        0,
                    )
        finally:
            stop_server(handle)

    def test_ambiguous_inflow_requires_classification(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            payload = self.event_payload(
                dedupe_key="ambiguous-1",
                payload={
                    "amount": "875.25",
                    "currency": "USD",
                    "account_name": "Primary Checking",
                    "classification": "unknown",
                    "classification_confidence": 0.22,
                },
            )
            status, body = self.post_event(handle, payload)
            self.assertEqual(status, 201)
            self.assertEqual(body["event"]["processing_status"], "processed")
            self.assertEqual(body["effects"][0]["type"], "core_signal_created")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")
            with core_connect(db_path) as conn:
                signal = conn.execute(
                    "SELECT signal_type, priority, actionability_score, recommended_action FROM core_signals WHERE signal_id=?",
                    (body["effects"][0]["signal_id"],),
                ).fetchone()
                alert = conn.execute(
                    "SELECT state FROM core_alerts WHERE alert_id=?",
                    (body["effects"][1]["alert_id"],),
                ).fetchone()
            self.assertEqual(signal["signal_type"], "paycheck_classification_required")
            self.assertEqual(signal["priority"], "P0")
            self.assertLess(float(signal["actionability_score"]), 1.0)
            self.assertIn("Classify this inflow", signal["recommended_action"])
            self.assertEqual(alert["state"], "queued")
        finally:
            stop_server(handle)

    def test_invalid_amount_marks_event_failed(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            payload = self.event_payload(
                dedupe_key="invalid-amount",
                payload={
                    "amount": "0",
                    "currency": "USD",
                    "account_name": "Primary Checking",
                    "classification": "paycheck",
                    "classification_confidence": 0.99,
                },
            )
            status, body = self.post_event(handle, payload)
            self.assertEqual(status, 400)
            self.assertIn("amount must be a positive number", body["error"])
            with core_connect(db_path) as conn:
                event = conn.execute(
                    "SELECT processing_status FROM core_events WHERE dedupe_key=?",
                    ("invalid-amount",),
                ).fetchone()
                self.assertEqual(event["processing_status"], "failed")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0], 0)
        finally:
            stop_server(handle)

    def test_duplicate_delivery_creates_one_event_signal_and_alert(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            payload = self.event_payload(
                dedupe_key="duplicate-1",
                payload={
                    "amount": "1400.00",
                    "currency": "USD",
                    "account_name": "Primary Checking",
                    "classification": "payroll",
                    "classification_confidence": 0.96,
                },
            )
            first_status, first_body = self.post_event(handle, payload)
            second_status, second_body = self.post_event(handle, payload)
            self.assertEqual(first_status, 201)
            self.assertEqual(second_status, 200)
            self.assertTrue(second_body["duplicate"])
            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0], 1)
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
                "dedupe_key": "unrelated-1",
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

    def test_route_level_end_to_end_behavior(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            payload = self.event_payload(
                dedupe_key="route-e2e",
                payload={
                    "amount": "2200.00",
                    "currency": "USD",
                    "account_name": "Household Checking",
                    "classification": "paycheck",
                    "classification_confidence": 0.99,
                    "transaction_ref": "pay-777",
                },
            )
            status, body = self.post_event(handle, payload)
            self.assertEqual(status, 201)
            self.assertTrue(body["effects"])
            signal_id = body["effects"][0]["signal_id"]
            alert_id = body["effects"][1]["alert_id"]
            self.assertEqual(body["event"]["processing_status"], "processed")

            alerts_status, alerts_body = request_json(handle.port, "/alerts?limit=10")
            self.assertEqual(alerts_status, 200)
            alert_ids = {alert["alert_id"] for alert in alerts_body["alerts"]}
            self.assertIn(alert_id, alert_ids)

            with core_connect(db_path) as conn:
                event = conn.execute(
                    "SELECT processing_status FROM core_events WHERE dedupe_key=?",
                    ("route-e2e",),
                ).fetchone()
                signal = conn.execute(
                    "SELECT signal_type FROM core_signals WHERE signal_id=?",
                    (signal_id,),
                ).fetchone()
                alert = conn.execute(
                    "SELECT state FROM core_alerts WHERE alert_id=?",
                    (alert_id,),
                ).fetchone()
                link = conn.execute(
                    "SELECT relationship FROM core_signal_events WHERE signal_id=? AND event_id=(SELECT event_id FROM core_events WHERE dedupe_key=?)",
                    (signal_id, "route-e2e"),
                ).fetchone()
            self.assertEqual(event["processing_status"], "processed")
            self.assertEqual(signal["signal_type"], "paycheck_received")
            self.assertEqual(alert["state"], "queued")
            self.assertEqual(link["relationship"], "trigger")
        finally:
            stop_server(handle)


if __name__ == "__main__":
    unittest.main()
