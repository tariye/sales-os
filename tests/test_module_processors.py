from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import unittest

from core_database import connect as core_connect
from integrations.domain_producers import GrooveProducer, PrivateEquityProducer, SalesProducer
from tests.support import request_json, start_server, stop_server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ModuleProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def db_path(self) -> Path:
        return self.root / "modules.db"

    def post_event(self, handle, payload):
        return request_json(
            handle.port,
            "/events",
            method="POST",
            payload=payload,
            headers={"Authorization": "Bearer test-key"},
        )

    def module_event(self, system_id: str, event_type: str, dedupe_key: str, payload: dict) -> dict:
        return {
            "source_system_id": system_id,
            "event_type": event_type,
            "occurred_at": utc_now(),
            "dedupe_key": dedupe_key,
            "priority": "P2",
            "confidence": 0.91,
            "source_ref": dedupe_key,
            "payload": payload,
        }

    def test_module_systems_are_seeded(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            with core_connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT system_id FROM core_systems WHERE system_id IN ('sys_groove','sys_sales','sys_private_equity')"
                ).fetchall()
            self.assertEqual({row["system_id"] for row in rows}, {"sys_groove", "sys_sales", "sys_private_equity"})
        finally:
            stop_server(handle)

    def test_groove_event_policies(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            blocked = self.module_event(
                "sys_groove",
                "project_blocked",
                "groove-blocked-1",
                {"project_name": "EP One", "blocker": "Mix review missing", "next_action": "Schedule mix review"},
            )
            status, body = self.post_event(handle, blocked)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "groove_project_blocked")
            self.assertEqual(body["effects"][0]["priority"], "P1")
            self.assertGreaterEqual(float(body["effects"][0]["actionability_score"]), 0.70)
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            milestone = self.module_event(
                "sys_groove",
                "release_milestone_reached",
                "groove-mile-1",
                {"project_name": "EP One", "milestone": "Master exported"},
            )
            status, body = self.post_event(handle, milestone)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "groove_release_milestone_reached")
            self.assertEqual(body["effects"][0]["priority"], "P2")
            self.assertEqual(len(body["effects"]), 1)

            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0], 0)
        finally:
            stop_server(handle)

    def test_sales_event_policies(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            followup = self.module_event(
                "sys_sales",
                "followup_due",
                "sales-followup-1",
                {
                    "opportunity_name": "Studio Partner",
                    "next_action": "Send proposal",
                    "context": "A promised reply is due today.",
                },
            )
            status, body = self.post_event(handle, followup)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "sales_followup_due")
            self.assertEqual(body["effects"][0]["priority"], "P1")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            stage = self.module_event(
                "sys_sales",
                "deal_stage_changed",
                "sales-stage-1",
                {"opportunity_name": "Studio Partner", "stage": "proposal_sent"},
            )
            status, body = self.post_event(handle, stage)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "sales_stage_changed")
            self.assertEqual(body["effects"][0]["priority"], "P2")
            self.assertEqual(len(body["effects"]), 1)
        finally:
            stop_server(handle)

    def test_private_equity_event_policies(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            invalidated = self.module_event(
                "sys_private_equity",
                "thesis_changed",
                "pe-invalidated-1",
                {
                    "asset_name": "Company A",
                    "change": "invalidated",
                    "materiality": 0.95,
                    "evidence": "Core assumption failed",
                },
            )
            status, body = self.post_event(handle, invalidated)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "investment_thesis_invalidated")
            self.assertEqual(body["effects"][0]["priority"], "P0")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            weakened = self.module_event(
                "sys_private_equity",
                "thesis_changed",
                "pe-weakened-1",
                {
                    "asset_name": "Company B",
                    "change": "weakened",
                    "materiality": 0.7,
                    "evidence": "Margin pressure increased",
                },
            )
            status, body = self.post_event(handle, weakened)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "investment_thesis_weakened")
            self.assertEqual(body["effects"][0]["priority"], "P1")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")

            strengthened = self.module_event(
                "sys_private_equity",
                "thesis_changed",
                "pe-strengthened-1",
                {
                    "asset_name": "Company C",
                    "change": "strengthened",
                    "materiality": 0.4,
                    "evidence": "Thesis improved",
                },
            )
            status, body = self.post_event(handle, strengthened)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "investment_thesis_strengthened")
            self.assertEqual(body["effects"][0]["priority"], "P2")
            self.assertEqual(len(body["effects"]), 1)

            breached = self.module_event(
                "sys_private_equity",
                "risk_limit_breached",
                "pe-risk-1",
                {
                    "asset_name": "Company D",
                    "rule": "Exposure exceeds allowed cap",
                },
            )
            status, body = self.post_event(handle, breached)
            self.assertEqual(status, 201)
            self.assertEqual(body["effects"][0]["signal_type"], "investment_risk_limit_breached")
            self.assertEqual(body["effects"][0]["priority"], "P0")
            self.assertEqual(body["effects"][1]["type"], "critical_alert_created")
        finally:
            stop_server(handle)

    def test_duplicate_delivery_creates_single_signal_and_alert(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            payload = self.module_event(
                "sys_sales",
                "followup_due",
                "sales-dup-1",
                {"opportunity_name": "Studio Partner", "next_action": "Send proposal"},
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

    def test_producer_integration_and_network_failure(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            groove = GrooveProducer(base_url=f"http://127.0.0.1:{handle.port}", api_key="test-key", timeout_seconds=2.0)
            result = groove.project_blocked(
                "groove-local-1",
                "EP One",
                "Mix review missing",
                "Schedule mix review",
            )
            self.assertTrue(result.ok)
            self.assertTrue(result.delivered)
            self.assertIsNotNone(result.event_id)
            self.assertIsNotNone(result.signal_id)
            self.assertIsNotNone(result.alert_id)

            sales = SalesProducer(base_url=f"http://127.0.0.1:{handle.port}", api_key="test-key", timeout_seconds=2.0)
            sales_result = sales.deal_stage_changed("sales-local-1", "Studio Partner", "proposal_sent")
            self.assertTrue(sales_result.ok)
            self.assertEqual(sales_result.signal_id is not None, True)

            pe = PrivateEquityProducer(base_url=f"http://127.0.0.1:{handle.port}", api_key="test-key", timeout_seconds=2.0)
            pe_result = pe.risk_limit_breached("pe-local-1", "Company D", "Exposure exceeds allowed cap")
            self.assertTrue(pe_result.ok)
            self.assertEqual(pe_result.signal_id is not None, True)

            failing = GrooveProducer(base_url="http://127.0.0.1:6553", api_key="test-key", timeout_seconds=0.25)
            failure = failing.project_blocked("groove-local-2", "EP Two", "Missing stem", "Request revised stems")
            self.assertFalse(failure.ok)
            self.assertFalse(failure.delivered)
            self.assertIsNotNone(failure.error)
        finally:
            stop_server(handle)


if __name__ == "__main__":
    unittest.main()
