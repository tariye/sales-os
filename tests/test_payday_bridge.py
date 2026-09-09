from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import unittest

from core_database import connect as core_connect
from tests.support import request_json, start_server, stop_server

from mcp_payday_bridge import MCP_AVAILABLE

if MCP_AVAILABLE:
    from mcp import Client
else:  # pragma: no cover - skipped when SDK is missing
    Client = None  # type: ignore[assignment]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def structured_content(result: Any) -> dict[str, Any]:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return result.structured_content
    if hasattr(result, "structuredContent") and result.structuredContent is not None:
        return result.structuredContent
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            import json

            return json.loads(text)
    raise AssertionError(f"unable to extract structured content from {result!r}")


@dataclass
class BridgeHandle:
    proc: subprocess.Popen[str]
    port: int
    log_path: Path


class PaydayBridgeTests(unittest.TestCase):
    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_tools_annotations_and_auth_guardrails(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "payday.db"
        app_handle = start_server(db_path, api_key="test-key")
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            signal_id, alert_id, plan_id = self.create_payday_case(app_handle)
            tools = self.list_tools(bridge_handle.port)
            tool_names = {tool.name for tool in tools}
            self.assertEqual(
                tool_names,
                {"prepare_payday_case", "get_payday_case", "save_payday_decision", "record_manual_routing"},
            )
            annotations = {tool.name: tool.annotations for tool in tools}
            self.assertFalse(bool(getattr(annotations["prepare_payday_case"], "read_only_hint", True)))
            self.assertTrue(bool(getattr(annotations["prepare_payday_case"], "destructive_hint", False)))
            self.assertTrue(bool(getattr(annotations["get_payday_case"], "read_only_hint", False)))
            self.assertFalse(bool(getattr(annotations["get_payday_case"], "destructive_hint", True)))
            self.assertFalse(bool(getattr(annotations["get_payday_case"], "open_world_hint", True)))
            self.assertFalse(bool(getattr(annotations["save_payday_decision"], "read_only_hint", True)))
            self.assertTrue(bool(getattr(annotations["save_payday_decision"], "destructive_hint", False)))

            case = self.call_tool(bridge_handle.port, "get_payday_case", {"plan_id": plan_id})
            self.assertTrue(case["ok"])
            self.assertEqual(case["case"]["case_id"]["signal_id"], signal_id)
            self.assertEqual(case["case"]["case_id"]["alert_id"], alert_id)
            self.assertEqual(case["case"]["case_id"]["plan_id"], plan_id)
            self.assertIn("operating_floor", case["case"]["payday_context"])
            self.assertIn("proposed_route", case["case"]["payday_context"])

            by_signal = self.call_tool(bridge_handle.port, "get_payday_case", {"signal_id": signal_id})
            self.assertTrue(by_signal["ok"])
            self.assertEqual(by_signal["case"]["case_id"]["plan_id"], plan_id)

            by_alert = self.call_tool(bridge_handle.port, "get_payday_case", {"alert_id": alert_id})
            self.assertTrue(by_alert["ok"])
            self.assertEqual(by_alert["case"]["case_id"]["signal_id"], signal_id)
        finally:
            self.stop_bridge(bridge_handle)
            stop_server(app_handle)
            tempdir.cleanup()

        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "payday-auth.db"
        app_handle = start_server(db_path, api_key="test-key")
        bridge_handle = self.start_bridge(db_path, api_key=None)
        try:
            _, _, plan_id = self.create_payday_case(app_handle)
            response = self.call_tool(
                bridge_handle.port,
                "save_payday_decision",
                {"plan_id": plan_id, "decision": "approve", "confirmed": True},
            )
            self.assertFalse(response["ok"])
            self.assertIn("INFO_ANALYZER_API_KEY", response["error"])

            invalid = self.call_tool(
                bridge_handle.port,
                "get_payday_case",
                {"plan_id": "missing-plan"},
            )
            self.assertFalse(invalid["ok"])
            self.assertIn("not found", invalid["error"])
        finally:
            self.stop_bridge(bridge_handle)
            stop_server(app_handle)
            tempdir.cleanup()

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_prepare_payday_case_preview_confirm_idempotency_and_routing_compatibility(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "payday-prepare.db"
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            payload = self.prepare_payday_payload(dedupe_key="stage-8-2-payroll-001")
            with core_connect(db_path) as conn:
                before_counts = self.core_counts(conn)

            preview = self.call_tool(
                bridge_handle.port,
                "prepare_payday_case",
                {**payload, "confirmed": False},
            )
            self.assertTrue(preview["ok"])
            self.assertFalse(preview["confirmed"])
            preview_case = preview["preview"]
            self.assertEqual(preview_case["paycheck_amount_cents"], 108414)
            self.assertEqual(preview_case["starting_balance"]["amount_cents"], 255720)
            self.assertEqual(preview_case["operating_floor"]["amount_cents"], 200000)
            self.assertEqual(preview_case["headroom_above_floor_cents"], 55720)
            self.assertEqual(preview_case["total_protected_holds_cents"], 33400)
            self.assertEqual(preview_case["truly_deployable_cents"], 22320)
            self.assertEqual(preview_case["proposed_route_total_cents"], 22320)
            self.assertEqual(preview_case["retained_paycheck_remainder"]["amount_cents"], 86094)
            self.assertEqual(preview_case["projected_balance_after_routes"]["amount_cents"], 233400)
            self.assertEqual(preview_case["actual_spend"], [])
            self.assertTrue(preview_case["possible_matching_transfer_evidence"]["probable_internal_transfer"])
            with core_connect(db_path) as conn:
                self.assertEqual(self.core_counts(conn), before_counts)

            confirmed = self.call_tool(
                bridge_handle.port,
                "prepare_payday_case",
                {**payload, "confirmed": True},
            )
            self.assertTrue(confirmed["ok"])
            self.assertTrue(confirmed["confirmed"])
            self.assertFalse(confirmed["idempotent"])
            event_id = confirmed["event_id"]
            signal_id = confirmed["signal_id"]
            alert_id = confirmed["alert_id"]
            plan_id = confirmed["plan_id"]
            self.assertTrue(event_id.startswith("EVT-"))
            self.assertTrue(signal_id.startswith("SIG-"))
            self.assertTrue(alert_id.startswith("ALT-"))
            self.assertTrue(plan_id.startswith("IPL-"))

            case = self.call_tool(bridge_handle.port, "get_payday_case", {"plan_id": plan_id})
            self.assertTrue(case["ok"])
            payday = case["case"]["payday_context"]
            self.assertEqual(payday["capital_semantics"]["starting_balance_cents"], 255720)
            self.assertEqual(payday["capital_semantics"]["operating_floor_cents"], 200000)
            self.assertEqual(payday["capital_semantics"]["truly_deployable_cents"], 22320)
            self.assertEqual(payday["capital_semantics"]["retained_cash_cents"], 86094)
            self.assertEqual(payday["retained_cash"]["amount_cents"], 86094)
            self.assertEqual(payday["actual_spend"], [])
            self.assertTrue(payday["transfer_evidence"]["probable_internal_transfer"])
            self.assertFalse(payday["transfer_evidence"]["confirmed_internal_transfer"])
            self.assertEqual(payday["transfer_evidence"]["classification_confidence"], 0.90)
            self.assertEqual(payday["transfer_evidence"]["matching_amount_cents"], 108414)

            duplicate = self.call_tool(
                bridge_handle.port,
                "prepare_payday_case",
                {**payload, "confirmed": True},
            )
            self.assertTrue(duplicate["ok"])
            self.assertTrue(duplicate["idempotent"])
            self.assertEqual(duplicate["event_id"], event_id)
            self.assertEqual(duplicate["signal_id"], signal_id)
            self.assertEqual(duplicate["alert_id"], alert_id)
            self.assertEqual(duplicate["plan_id"], plan_id)

            with core_connect(db_path) as conn:
                after_counts = self.core_counts(conn)
            self.assertEqual(after_counts["core_events"] - before_counts["core_events"], 1)
            self.assertEqual(after_counts["core_signals"] - before_counts["core_signals"], 1)
            self.assertEqual(after_counts["core_alerts"] - before_counts["core_alerts"], 1)
            self.assertEqual(after_counts["innbank_allocation_plans"] - before_counts["innbank_allocation_plans"], 1)
            self.assertEqual(after_counts["innbank_allocation_items"] - before_counts["innbank_allocation_items"], 4)
            self.assertEqual(after_counts["actions"], before_counts["actions"])
            self.assertEqual(after_counts["live_signals"], before_counts["live_signals"])

            decision = self.call_tool(
                bridge_handle.port,
                "save_payday_decision",
                {"plan_id": plan_id, "decision": "defer", "confirmed": True},
            )
            self.assertTrue(decision["ok"])
            self.assertEqual(decision["canonical_response"], "defer")

            missing_routing_confirmation = self.call_tool(
                bridge_handle.port,
                "record_manual_routing",
                {"plan_id": plan_id, "items": [{"allocation_item_id": "ALI-MISSING", "actual_amount_cents": 0}]},
            )
            self.assertFalse(missing_routing_confirmation["ok"])
            self.assertIn("confirmation required", missing_routing_confirmation["error"])
        finally:
            self.stop_bridge(bridge_handle)
            tempdir.cleanup()

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_prepare_payday_case_rejects_routes_over_deployable_and_writes_nothing(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "payday-prepare-invalid.db"
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            payload = self.prepare_payday_payload(
                dedupe_key="stage-8-2-overdeployable-001",
                proposed_routes=[
                    {"label": "Emergency", "amount": "300.00"},
                ],
            )
            with core_connect(db_path) as conn:
                before_counts = self.core_counts(conn)
            response = self.call_tool(
                bridge_handle.port,
                "prepare_payday_case",
                {**payload, "confirmed": True},
            )
            self.assertFalse(response["ok"])
            self.assertIn("proposed_routes", response["error"])
            with core_connect(db_path) as conn:
                self.assertEqual(self.core_counts(conn), before_counts)
        finally:
            self.stop_bridge(bridge_handle)
            tempdir.cleanup()

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_prepare_payday_case_preserves_absence_of_transfer_evidence(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "payday-prepare-no-transfer.db"
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            payload = self.prepare_payday_payload(dedupe_key="stage-8-2-no-transfer-001")
            payload.pop("possible_matching_transfer_evidence")
            preview = self.call_tool(bridge_handle.port, "prepare_payday_case", {**payload, "confirmed": False})
            self.assertTrue(preview["ok"])
            self.assertIsNone(preview["preview"]["possible_matching_transfer_evidence"])
            confirmed = self.call_tool(bridge_handle.port, "prepare_payday_case", {**payload, "confirmed": True})
            self.assertTrue(confirmed["ok"])
            case = self.call_tool(bridge_handle.port, "get_payday_case", {"plan_id": confirmed["plan_id"]})
            self.assertTrue(case["ok"])
            self.assertEqual(case["case"]["payday_context"]["transfer_evidence"], {})
        finally:
            self.stop_bridge(bridge_handle)
            tempdir.cleanup()

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_semantic_case_arithmetic_and_transfer_classification(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "payday-semantic.db"
        app_handle = start_server(db_path, api_key="test-key")
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            with core_connect(db_path) as conn:
                before_counts = {
                    "events": conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0],
                    "signals": conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0],
                    "alerts": conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0],
                    "live_signals": conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0],
                    "core_actions": conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0],
                    "core_decisions": conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0],
                    "core_outcomes": conn.execute("SELECT COUNT(*) FROM core_outcomes").fetchone()[0],
                }
            case_ids = self.create_semantic_payday_case(app_handle)
            case = self.call_tool(bridge_handle.port, "get_payday_case", {"plan_id": case_ids["plan_id"]})
            self.assertTrue(case["ok"])
            payday = case["case"]["payday_context"]

            self.assertEqual(case["case"]["case_id"]["plan_id"], case_ids["plan_id"])
            self.assertEqual(case["case"]["case_id"]["signal_id"], case_ids["signal_id"])
            self.assertEqual(case["case"]["case_id"]["alert_id"], case_ids["alert_id"])
            self.assertEqual(payday["capital_semantics"]["starting_balance_cents"], 255720)
            self.assertEqual(payday["capital_semantics"]["operating_floor_cents"], 200000)
            self.assertEqual(payday["capital_semantics"]["headroom_above_floor_cents"], 55720)
            self.assertEqual(payday["capital_semantics"]["total_protected_holds_cents"], 33400)
            self.assertEqual(payday["capital_semantics"]["truly_deployable_cents"], 22320)
            self.assertEqual(payday["capital_semantics"]["projected_balance_after_routes_cents"], 233400)
            self.assertEqual(payday["capital_semantics"]["decision_state"], "proposed_only")
            self.assertTrue(payday["probable_internal_transfer"])
            self.assertFalse(payday["confirmed_internal_transfer"])
            self.assertEqual(payday["transfer_classification_confidence"], 0.90)
            self.assertEqual(payday["transfer_evidence"]["matching_amount_cents"], 108414)
            self.assertEqual(payday["transfer_evidence"]["payroll_posted_at"], "2026-09-04")
            self.assertEqual(payday["transfer_evidence"]["transfer_posted_at"], "2026-09-05")
            self.assertEqual(payday["transfer_evidence"]["wells_fargo_reference"], "Apex Systems payroll 2026-09-04")
            self.assertEqual(payday["transfer_evidence"]["capital_one_reference"], "Capital One transfer in 2026-09-05")
            self.assertEqual(payday["operating_floor"]["amount_cents"], 200000)
            self.assertEqual(payday["medical_protected_hold"]["amount_cents"], 18400)
            self.assertEqual(payday["insurance_daycare_protected_hold"]["amount_cents"], 15000)
            self.assertEqual(payday["retained_cash"]["amount_cents"], 86094)
            self.assertEqual(payday["actual_spend"], [])
            self.assertEqual(sum(item["proposed_amount_cents"] for item in payday["proposed_route"]), 22320)
            self.assertNotEqual(payday["retained_cash"]["amount_cents"], payday["operating_floor"]["amount_cents"])

            with core_connect(db_path) as conn:
                after_counts = {
                    "events": conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0],
                    "signals": conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0],
                    "alerts": conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0],
                    "live_signals": conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0],
                    "core_actions": conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0],
                    "core_decisions": conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0],
                    "core_outcomes": conn.execute("SELECT COUNT(*) FROM core_outcomes").fetchone()[0],
                }
                ignored = conn.execute(
                    "SELECT processing_status FROM core_events WHERE dedupe_key=?",
                    ("semantic-transfer-001",),
                ).fetchone()
                self.assertEqual(ignored["processing_status"], "ignored")
            self.assertEqual(after_counts["events"] - before_counts["events"], 2)
            self.assertEqual(after_counts["signals"] - before_counts["signals"], 1)
            self.assertEqual(after_counts["alerts"] - before_counts["alerts"], 1)
            self.assertEqual(after_counts["live_signals"] - before_counts["live_signals"], 0)
            self.assertEqual(after_counts["core_actions"] - before_counts["core_actions"], 0)
            self.assertEqual(after_counts["core_decisions"] - before_counts["core_decisions"], 0)
            self.assertEqual(after_counts["core_outcomes"] - before_counts["core_outcomes"], 0)
        finally:
            self.stop_bridge(bridge_handle)
            stop_server(app_handle)
            tempdir.cleanup()

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_save_decision_and_manual_routing_idempotency(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "payday-flow.db"
        app_handle = start_server(db_path, api_key="test-key")
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            _, _, plan_id = self.create_payday_case(app_handle, dedupe_key="bridge-flow-1")
            with core_connect(db_path) as conn:
                legacy_actions_before = conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
                live_signals_before = conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0]
                decisions_before = conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0]

            missing_confirm = self.call_tool(
                bridge_handle.port,
                "save_payday_decision",
                {"plan_id": plan_id, "decision": "approve"},
            )
            self.assertFalse(missing_confirm["ok"])
            self.assertIn("confirmation required", missing_confirm["error"])

            modify = self.call_tool(
                bridge_handle.port,
                "save_payday_decision",
                {"plan_id": plan_id, "decision": "modify", "confirmed": True, "rationale": "Need to hold cash"},
            )
            self.assertTrue(modify["ok"])
            self.assertEqual(modify["canonical_response"], "hold")
            self.assertEqual(modify["response_state"], "pending_manual_routing")
            first_decision_id = modify["decision"]["decision_id"]
            with core_connect(db_path) as conn:
                decisions_after_modify = conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0]
                self.assertEqual(decisions_after_modify, decisions_before + 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0], legacy_actions_before)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0], live_signals_before)

            modify_repeat = self.call_tool(
                bridge_handle.port,
                "save_payday_decision",
                {"plan_id": plan_id, "decision": "modify", "confirmed": True},
            )
            self.assertTrue(modify_repeat["ok"])
            self.assertTrue(modify_repeat["idempotent"])
            self.assertEqual(modify_repeat["decision"]["decision_id"], first_decision_id)
            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_decisions").fetchone()[0], decisions_before + 1)

            second_case = self.create_payday_case(app_handle, dedupe_key="bridge-flow-2")
            _, _, approve_plan_id = second_case
            approve = self.call_tool(
                bridge_handle.port,
                "save_payday_decision",
                {"plan_id": approve_plan_id, "decision": "approve", "confirmed": True},
            )
            self.assertTrue(approve["ok"])
            self.assertEqual(approve["canonical_response"], "approve")
            self.assertGreaterEqual(len(approve["actions"]), 1)
            with core_connect(db_path) as conn:
                actions_after_approve = conn.execute("SELECT COUNT(*) FROM core_actions").fetchone()[0]
                self.assertGreater(actions_after_approve, 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0], legacy_actions_before)

            plan_case = self.call_tool(
                bridge_handle.port,
                "get_payday_case",
                {"plan_id": approve_plan_id},
            )
            items = plan_case["case"]["allocation_plan"]["items"]
            routing_items = []
            for item in items:
                routing_items.append(
                    {
                        "allocation_item_id": item["allocation_item_id"],
                        "actual_amount_cents": item["proposed_amount_cents"],
                        "notes": f"Routed for {item['label']}",
                    }
                )
            routing = self.call_tool(
                bridge_handle.port,
                "record_manual_routing",
                {
                    "plan_id": approve_plan_id,
                    "items": routing_items,
                    "notes": "Recorded by ChatGPT bridge",
                    "confirmed": True,
                },
            )
            self.assertTrue(routing["ok"])
            self.assertTrue(routing["completed"])
            self.assertIsNotNone(routing["routing_completed_event"])
            with core_connect(db_path) as conn:
                self.assertGreater(conn.execute("SELECT COUNT(*) FROM core_outcomes").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0], legacy_actions_before)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0], live_signals_before)

            routing_repeat = self.call_tool(
                bridge_handle.port,
                "record_manual_routing",
                {
                    "plan_id": approve_plan_id,
                    "items": routing_items,
                    "notes": "Recorded by ChatGPT bridge",
                    "confirmed": True,
                },
            )
            self.assertTrue(routing_repeat["ok"])
            self.assertTrue(routing_repeat["idempotent"])
        finally:
            self.stop_bridge(bridge_handle)
            stop_server(app_handle)
            tempdir.cleanup()

    def create_payday_case(self, handle, *, dedupe_key: str = "bridge-payday-1", amount: str = "2400.00"):
        payload = {
            "source_system_id": "sys_innbank",
            "event_type": "financial_inflow_posted",
            "occurred_at": utc_now(),
            "dedupe_key": dedupe_key,
            "priority": "P0",
            "confidence": 0.99,
            "payload": {
                "amount": amount,
                "currency": "USD",
                "account_name": "Bridge Test Checking",
                "classification": "payroll",
                "classification_confidence": 0.99,
                "transaction_ref": f"txn-{dedupe_key}",
            },
        }
        status, body = request_json(
            handle.port,
            "/events",
            method="POST",
            payload=payload,
            headers={"Authorization": "Bearer test-key"},
        )
        self.assertEqual(status, 201)
        signal_id = body["effects"][0]["signal_id"]
        alert_id = body["effects"][1]["alert_id"]
        plan_status, plan_body = request_json(
            handle.port,
            "/innbank/allocation-plans",
            method="POST",
            payload={
                "signal_id": signal_id,
                "title": "Bridge payday allocation",
                "summary": "Bridge-generated plan",
                "items": [
                    {"item_type": "allocation", "label": "Rent", "proposed_amount_cents": 120000},
                    {"item_type": "allocation", "label": "Savings", "proposed_amount_cents": 60000},
                    {"item_type": "unallocated", "label": "Hold cash", "proposed_amount_cents": 60000},
                ],
            },
        )
        self.assertEqual(plan_status, 201)
        return signal_id, alert_id, plan_body["plan"]["plan_id"]

    def core_counts(self, conn):
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        result = {}
        for name in [
            "core_events",
            "core_signals",
            "core_alerts",
            "innbank_allocation_plans",
            "innbank_allocation_items",
            "core_actions",
            "core_decisions",
            "core_outcomes",
            "actions",
            "live_signals",
        ]:
            result[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] if name in tables else 0
        return result

    def prepare_payday_payload(self, *, dedupe_key: str, proposed_routes: list[dict[str, Any]] | None = None):
        return {
            "paycheck_amount": "1084.14",
            "posted_at": "2026-09-09T12:00:00-07:00",
            "employer_reference": "Apex Systems payroll",
            "receiving_account": "Wells Fargo checking",
            "starting_balance": "2557.20",
            "operating_floor": "2000.00",
            "protected_holds": [
                {"label": "medical", "amount": "184.00"},
                {"label": "insurance_daycare", "amount": "150.00"},
            ],
            "proposed_routes": proposed_routes
            or [
                {"label": "Emergency", "amount": "100.00"},
                {"label": "Transition", "amount": "75.00"},
                {"label": "Rue", "amount": "48.20"},
            ],
            "possible_matching_transfer_evidence": {
                "probable_internal_transfer": True,
                "confirmed_internal_transfer": False,
                "classification_confidence": 0.90,
                "matching_amount": "1084.14",
                "payroll_posted_at": "2026-09-09",
                "transfer_posted_at": "2026-09-10",
                "wells_fargo_reference": "Apex Systems payroll",
                "capital_one_reference": "Capital One transfer-in candidate",
                "supporting_evidence": [
                    {"field": "matching_amount", "value": "1084.14"},
                    {"field": "posting_gap_days", "value": 1},
                ],
            },
            "currency": "USD",
            "source_transaction_id": dedupe_key,
            "dedupe_key": dedupe_key,
        }

    def create_semantic_payday_case(self, handle):
        status, body = request_json(
            handle.port,
            "/events",
            method="POST",
            payload={
                "source_system_id": "sys_innbank",
                "event_type": "financial_inflow_posted",
                "occurred_at": "2026-09-04T12:00:00-07:00",
                "dedupe_key": "semantic-payroll-001",
                "priority": "P0",
                "confidence": 0.99,
                "payload": {
                    "amount": "1084.14",
                    "currency": "USD",
                    "account_name": "Wells Fargo checking",
                    "classification": "payroll",
                    "classification_confidence": 0.99,
                    "transaction_ref": "Apex Systems payroll 2026-09-04",
                },
            },
            headers={"Authorization": "Bearer test-key"},
        )
        self.assertEqual(status, 201)
        signal_id = body["effects"][0]["signal_id"]
        alert_id = body["effects"][1]["alert_id"]

        transfer_status, transfer_body = request_json(
            handle.port,
            "/events",
            method="POST",
            payload={
                "source_system_id": "sys_innbank",
                "event_type": "financial_inflow_posted",
                "occurred_at": "2026-09-05T09:30:00-07:00",
                "dedupe_key": "semantic-transfer-001",
                "priority": "P2",
                "confidence": 0.90,
                "payload": {
                    "amount": "1084.14",
                    "currency": "USD",
                    "account_name": "Capital One checking",
                    "classification": "internal_transfer",
                    "classification_confidence": 0.90,
                    "transaction_ref": "Capital One transfer in 2026-09-05",
                },
            },
            headers={"Authorization": "Bearer test-key"},
        )
        self.assertEqual(transfer_status, 201)
        self.assertEqual(transfer_body["event"]["processing_status"], "ignored")

        metadata = {
            "capital_semantics": {
                "starting_balance_cents": 255720,
                "operating_floor_cents": 200000,
                "headroom_above_floor_cents": 55720,
                "protected_holds": {
                    "medical_cents": 18400,
                    "insurance_daycare_cents": 15000,
                },
                "total_protected_holds_cents": 33400,
                "truly_deployable_cents": 22320,
                "projected_balance_after_routes_cents": 233400,
                "decision_state": "proposed_only",
            },
            "transfer_evidence": {
                "probable_internal_transfer": True,
                "confirmed_internal_transfer": False,
                "classification_confidence": 0.90,
                "matching_amount_cents": 108414,
                "payroll_posted_at": "2026-09-04",
                "transfer_posted_at": "2026-09-05",
                "wells_fargo_reference": "Apex Systems payroll 2026-09-04",
                "capital_one_reference": "Capital One transfer in 2026-09-05",
                "supporting_evidence": [
                    {"field": "matching_amount_cents", "value": 108414},
                    {"field": "payroll_posted_at", "value": "2026-09-04"},
                    {"field": "transfer_posted_at", "value": "2026-09-05"},
                    {"field": "wells_fargo_reference", "value": "Apex Systems payroll 2026-09-04"},
                    {"field": "capital_one_reference", "value": "Capital One transfer in 2026-09-05"},
                ],
            },
        }
        plan_status, plan_body = request_json(
            handle.port,
            "/innbank/allocation-plans",
            method="POST",
            payload={
                "signal_id": signal_id,
                "title": "Stage 8.1 semantic payday case",
                "summary": "Apex Systems payroll, proposed-only allocation, no approval yet",
                "rationale": "Preserve the paycheck, operating floor, and protected holds before allocation.",
                "recommended_action": "Review the proposed routes and decide whether to approve, modify, defer, or reject.",
                "notes": "decision_state=proposed_only; no_allocation_approved; no_manual_routing_recorded",
                "metadata": metadata,
                "items": [
                    {"item_type": "allocation", "label": "Emergency", "proposed_amount_cents": 10000},
                    {"item_type": "allocation", "label": "Transition", "proposed_amount_cents": 7500},
                    {"item_type": "allocation", "label": "Rue", "proposed_amount_cents": 4820},
                    {"item_type": "unallocated", "label": "Retained paycheck remainder", "proposed_amount_cents": 86094},
                ],
            },
        )
        self.assertEqual(plan_status, 201)
        return {
            "signal_id": signal_id,
            "alert_id": alert_id,
            "plan_id": plan_body["plan"]["plan_id"],
            "transfer_event_id": transfer_body["event"]["event_id"],
        }

    def start_bridge(self, db_path: Path, api_key: str | None = "test-key") -> BridgeHandle:
        log_dir = Path(tempfile.mkdtemp(prefix="info-analyzer-payday-bridge-"))
        log_path = log_dir / "bridge.log"
        env = os.environ.copy()
        env["INFO_ANALYZER_DB_PATH"] = str(db_path)
        env["PYTHONUNBUFFERED"] = "1"
        if api_key is None:
            env.pop("INFO_ANALYZER_API_KEY", None)
        else:
            env["INFO_ANALYZER_API_KEY"] = api_key
        for port in range(8210, 8240):
            log_file = log_path.open("w", encoding="utf-8")
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "mcp_payday_bridge.py",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--database-path",
                    str(db_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if self.wait_for_bridge(port, proc):
                log_file.close()
                return BridgeHandle(proc=proc, port=port, log_path=log_path)
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            log_file.close()
        raise AssertionError(log_path.read_text(encoding="utf-8", errors="replace"))

    def stop_bridge(self, handle: BridgeHandle) -> None:
        if handle.proc.poll() is None:
            handle.proc.terminate()
            try:
                handle.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                handle.proc.kill()

    def wait_for_bridge(self, port: int, proc: subprocess.Popen[str]) -> bool:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            try:
                tools = self.list_tools(port)
                return len(tools) == 4
            except Exception:
                time.sleep(0.25)
        return False

    def list_tools(self, port: int):
        async def _list():
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                result = await client.list_tools()
                return list(getattr(result, "tools", result))

        return asyncio.run(_list())

    def call_tool(self, port: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
        async def _call():
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                result = await client.call_tool(name, args)
                return structured_content(result)

        return asyncio.run(_call())


if __name__ == "__main__":
    unittest.main()
