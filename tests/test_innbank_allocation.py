from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import unittest

from core_database import connect as core_connect
from tests.support import request_json, start_server, stop_server


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class InnbankAllocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def db_path(self) -> Path:
        return self.root / "allocation.db"

    def paycheck_event_payload(self, dedupe_key: str = "paycheck-1", amount: str = "2400.00"):
        return {
            "source_system_id": "sys_innbank",
            "event_type": "financial_inflow_posted",
            "occurred_at": utc_now(),
            "dedupe_key": dedupe_key,
            "priority": "P0",
            "confidence": 0.99,
            "payload": {
                "amount": amount,
                "currency": "USD",
                "account_name": "Fictional Test Checking",
                "classification": "payroll",
                "classification_confidence": 0.99,
                "transaction_ref": f"txn-{dedupe_key}",
            },
        }

    def create_paycheck_signal(self, handle, *, dedupe_key: str = "paycheck-1", amount: str = "2400.00"):
        status, body = request_json(
            handle.port,
            "/events",
            method="POST",
            payload=self.paycheck_event_payload(dedupe_key=dedupe_key, amount=amount),
            headers={"Authorization": "Bearer test-key"},
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["effects"])
        signal_id = body["effects"][0]["signal_id"]
        alert_id = body["effects"][1]["alert_id"]
        return signal_id, alert_id

    def create_plan(self, handle, signal_id: str, items: list[dict]) -> dict:
        status, body = request_json(
            handle.port,
            "/innbank/allocation-plans",
            method="POST",
            payload={
                "signal_id": signal_id,
                "notes": "Unit test allocation plan",
                "items": items,
            },
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["success"])
        self.assertTrue(body["created"])
        return body

    def test_complete_plan_creation(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            signal_id, _ = self.create_paycheck_signal(handle, dedupe_key="plan-create")
            body = self.create_plan(
                handle,
                signal_id,
                [
                    {"item_type": "allocation", "label": "Rent", "proposed_amount_cents": 120000},
                    {"item_type": "allocation", "label": "Savings", "proposed_amount_cents": 60000},
                    {"item_type": "unallocated", "label": "Retain cash", "proposed_amount_cents": 60000},
                ],
            )
            plan = body["plan"]
            self.assertEqual(plan["status"], "proposed")
            self.assertEqual(plan["paycheck_amount_cents"], 240000)
            self.assertEqual(plan["paycheck_amount"], "$2,400.00")
            self.assertEqual(len(body["items"]), 3)
            self.assertEqual(sum(item["proposed_amount_cents"] for item in body["items"]), 240000)
            self.assertTrue(any(item["item_type"] == "unallocated" for item in body["items"]))

            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0], 0)
                legacy_before = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
            self.assertGreaterEqual(legacy_before, 0)
        finally:
            stop_server(handle)

    def test_incorrect_allocation_total_rejected(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            signal_id, _ = self.create_paycheck_signal(handle, dedupe_key="bad-total")
            status, body = request_json(
                handle.port,
                "/innbank/allocation-plans",
                method="POST",
                payload={
                    "signal_id": signal_id,
                    "items": [
                        {"item_type": "allocation", "label": "Rent", "proposed_amount_cents": 120000},
                        {"item_type": "allocation", "label": "Savings", "proposed_amount_cents": 50000},
                        {"item_type": "unallocated", "label": "Retain cash", "proposed_amount_cents": 50000},
                    ],
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("exactly equal", body["error"])
        finally:
            stop_server(handle)

    def test_approval_hold_defer_and_reject(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            responses = ("approve", "hold", "defer", "reject")
            for index, response in enumerate(responses):
                signal_id, _ = self.create_paycheck_signal(handle, dedupe_key=f"resp-{response}-{index}")
                plan_body = self.create_plan(
                    handle,
                    signal_id,
                    [
                        {"item_type": "allocation", "label": "Rent", "proposed_amount_cents": 120000},
                        {"item_type": "unallocated", "label": "Retain cash", "proposed_amount_cents": 120000},
                    ],
                )
                plan_id = plan_body["plan"]["plan_id"]
                with core_connect(db_path) as conn:
                    legacy_before = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
                    core_actions_before = conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0]
                status, body = request_json(
                    handle.port,
                    f"/innbank/allocation-plans/{plan_id}/respond",
                    method="POST",
                    payload={"response": response, "rationale": f"Test {response} response"},
                )
                self.assertEqual(status, 200)
                self.assertTrue(body["success"])
                self.assertEqual(body["decision"]["selected_option"], response)
                with core_connect(db_path) as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0], index + 1)
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0], legacy_before)
                    if response == "approve":
                        self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0], core_actions_before + 1)
                        self.assertEqual(body["plan"]["latest_response"], "approve")
                        self.assertEqual(body["plan"]["status"], "decided")
                    else:
                        self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0], core_actions_before)
                        expected_status = "rejected" if response == "reject" else "decided"
                        self.assertEqual(body["plan"]["status"], expected_status)
                        self.assertEqual(body["plan"]["latest_response"], response)
        finally:
            stop_server(handle)

    def test_partial_manual_routing_then_completion_and_idempotent_completed_event(self) -> None:
        db_path = self.db_path()
        handle = start_server(db_path, api_key="test-key")
        try:
            signal_id, _ = self.create_paycheck_signal(handle, dedupe_key="routing-e2e")
            plan_body = self.create_plan(
                handle,
                signal_id,
                [
                    {"item_type": "allocation", "label": "Rent", "proposed_amount_cents": 120000},
                    {"item_type": "allocation", "label": "Savings", "proposed_amount_cents": 60000},
                    {"item_type": "unallocated", "label": "Retain cash", "proposed_amount_cents": 60000},
                ],
            )
            plan_id = plan_body["plan"]["plan_id"]
            status, body = request_json(
                handle.port,
                f"/innbank/allocation-plans/{plan_id}/respond",
                method="POST",
                payload={"response": "approve", "rationale": "Approved for test"},
            )
            self.assertEqual(status, 200)
            plan = body["plan"]
            self.assertEqual(plan["latest_response"], "approve")

            item_map = {item["label"]: item for item in body["items"]}
            rent_item = item_map["Rent"]
            savings_item = item_map["Savings"]
            retain_item = item_map["Retain cash"]

            status, routing_one = request_json(
                handle.port,
                f"/innbank/allocation-plans/{plan_id}/routing",
                method="POST",
                payload={
                    "notes": "First manual routing pass",
                    "items": [
                        {
                            "allocation_item_id": rent_item["allocation_item_id"],
                            "actual_amount_cents": 80000,
                            "notes": "Partial rent transfer",
                        }
                    ],
                },
            )
            self.assertEqual(status, 200)
            self.assertFalse(routing_one["completed"])
            self.assertEqual(routing_one["routing_items"][0]["routing_status"], "partial")
            self.assertEqual(routing_one["routing_items"][0]["variance_cents"], -40000)
            self.assertEqual(routing_one["routing_items"][0]["outcome"]["result_status"], "partial")

            status, routing_two = request_json(
                handle.port,
                f"/innbank/allocation-plans/{plan_id}/routing",
                method="POST",
                payload={
                    "notes": "Complete remaining routing",
                    "items": [
                        {
                            "allocation_item_id": savings_item["allocation_item_id"],
                            "actual_amount_cents": 60000,
                            "notes": "Savings routed",
                        },
                        {
                            "allocation_item_id": retain_item["allocation_item_id"],
                            "actual_amount_cents": 60000,
                            "notes": "Cash retained",
                        },
                    ],
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(routing_two["completed"])
            self.assertIsNotNone(routing_two["routing_completed_event"])

            with core_connect(db_path) as conn:
                plan_row = conn.execute(
                    "SELECT status, completed_at, completed_event_id FROM innbank_allocation_plans WHERE plan_id=?",
                    (plan_id,),
                ).fetchone()
                self.assertEqual(plan_row["status"], "completed")
                self.assertIsNotNone(plan_row["completed_at"])
                self.assertIsNotNone(plan_row["completed_event_id"])
                routing_event_count = conn.execute(
                    "SELECT COUNT(*) FROM core_events WHERE event_type='routing_completed' AND dedupe_key=?",
                    (f"innbank-routing-completed:{plan_id}",),
                ).fetchone()[0]
                self.assertEqual(routing_event_count, 1)
                outcome_rows = conn.execute(
                    "SELECT outcome_id, result_status, actual_result FROM core_outcomes WHERE action_id IS NOT NULL ORDER BY created_at ASC"
                ).fetchall()
                self.assertGreaterEqual(len(outcome_rows), 2)
                legacy_actions = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
                self.assertGreaterEqual(legacy_actions, 0)

            repeat_status, repeat_body = request_json(
                handle.port,
                f"/innbank/allocation-plans/{plan_id}/routing",
                method="POST",
                payload={
                    "notes": "Repeat completion pass",
                    "items": [
                        {
                            "allocation_item_id": rent_item["allocation_item_id"],
                            "actual_amount_cents": 80000,
                        },
                        {
                            "allocation_item_id": savings_item["allocation_item_id"],
                            "actual_amount_cents": 60000,
                        },
                        {
                            "allocation_item_id": retain_item["allocation_item_id"],
                            "actual_amount_cents": 60000,
                        },
                    ],
                },
            )
            self.assertEqual(repeat_status, 200)
            self.assertTrue(repeat_body["completed"])
            with core_connect(db_path) as conn:
                routing_event_count = conn.execute(
                    "SELECT COUNT(*) FROM core_events WHERE event_type='routing_completed' AND dedupe_key=?",
                    (f"innbank-routing-completed:{plan_id}",),
                ).fetchone()[0]
                self.assertEqual(routing_event_count, 1)

            get_status, get_body = request_json(handle.port, f"/innbank/allocation-plans/{plan_id}")
            self.assertEqual(get_status, 200)
            self.assertEqual(get_body["plan"]["status"], "completed")
            self.assertEqual(len(get_body["routing_items"]), 3)
        finally:
            stop_server(handle)


if __name__ == "__main__":
    unittest.main()
