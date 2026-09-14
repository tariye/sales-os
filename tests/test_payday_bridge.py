from __future__ import annotations

import asyncio
import os
import shutil
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


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DB = ROOT / "data" / "info_analyzer.db"
MCP_TOOL_NAMES = {
    "prepare_payday_case",
    "record_financial_source_observation",
    "get_source_observation_status",
    "ingest_capture",
    "get_day_progress",
    "get_payday_case",
    "save_payday_decision",
    "record_manual_routing",
    "get_system_status",
    "list_cases",
    "get_case",
    "get_event_trace",
}


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
            self.assertEqual(tool_names, MCP_TOOL_NAMES)
            annotations = {tool.name: tool.annotations for tool in tools}
            self.assertFalse(bool(getattr(annotations["prepare_payday_case"], "read_only_hint", True)))
            self.assertTrue(bool(getattr(annotations["prepare_payday_case"], "destructive_hint", False)))
            self.assertFalse(bool(getattr(annotations["record_financial_source_observation"], "read_only_hint", True)))
            self.assertTrue(bool(getattr(annotations["record_financial_source_observation"], "destructive_hint", False)))
            self.assertFalse(bool(getattr(annotations["ingest_capture"], "read_only_hint", True)))
            self.assertTrue(bool(getattr(annotations["ingest_capture"], "destructive_hint", False)))
            self.assertTrue(bool(getattr(annotations["get_payday_case"], "read_only_hint", False)))
            self.assertFalse(bool(getattr(annotations["get_payday_case"], "destructive_hint", True)))
            self.assertFalse(bool(getattr(annotations["get_payday_case"], "open_world_hint", True)))
            for read_tool in ("get_system_status", "list_cases", "get_case", "get_event_trace", "get_source_observation_status", "get_day_progress"):
                self.assertTrue(bool(getattr(annotations[read_tool], "read_only_hint", False)), read_tool)
                self.assertFalse(bool(getattr(annotations[read_tool], "destructive_hint", True)), read_tool)
                self.assertFalse(bool(getattr(annotations[read_tool], "open_world_hint", True)), read_tool)
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

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_capture_ingestion_idempotency_daily_progress_and_auth(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "capture-loop.db"
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            with core_connect(db_path) as conn:
                before = self.capture_counts(conn)
            morning = self.capture_payload(
                capture_type="begin_day_checklist",
                idempotency_key="capture-loop-morning-001",
                request_id="req-capture-morning-001",
                message_id="msg-capture-morning-001",
                raw_text=(
                    "Begin-Day Checklist\n"
                    "- Ship the capture loop\n"
                    "- Verify publication proof\n"
                    "- Blocker: remote publication not validated"
                ),
                occurred_at="2026-09-13T08:00:00-07:00",
                captured_at="2026-09-13T08:02:00-07:00",
            )
            created = self.call_tool(bridge_handle.port, "ingest_capture", {**morning, "confirmed": True})
            self.assertTrue(created["ok"])
            self.assertFalse(created["duplicate"])
            self.assertTrue(created["capture_id"].startswith("CAP-"))
            self.assertEqual(created["capture"]["raw_text"], morning["raw_text"])
            self.assertEqual(created["capture"]["processing_state"], "processed")
            self.assertTrue(created["content_hash"])
            self.assertTrue(created["processing"]["signal_id"].startswith("SIG-"))

            duplicate = self.call_tool(bridge_handle.port, "ingest_capture", {**morning, "confirmed": True})
            self.assertTrue(duplicate["ok"])
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(duplicate["capture_id"], created["capture_id"])
            self.assertEqual(duplicate["content_hash"], created["content_hash"])

            conflict = self.call_tool(
                bridge_handle.port,
                "ingest_capture",
                {**morning, "raw_text": morning["raw_text"] + "\n- Different immutable payload", "confirmed": True},
            )
            self.assertFalse(conflict["ok"])
            self.assertIn("conflict", conflict["error"])

            evening = self.capture_payload(
                capture_type="end_of_day_report",
                idempotency_key="capture-loop-evening-001",
                request_id="req-capture-evening-001",
                message_id="msg-capture-evening-001",
                raw_text=(
                    "End of day report\n"
                    "- Capture loop generated receipts\n"
                    "- Publication state machine still needs remote verification\n"
                    "- Smallest next step: run golden export"
                ),
                occurred_at="2026-09-13T20:30:00-07:00",
                captured_at="2026-09-13T20:32:00-07:00",
            )
            report = self.call_tool(bridge_handle.port, "ingest_capture", {**evening, "confirmed": True})
            self.assertTrue(report["ok"])
            self.assertEqual(report["capture"]["processing_state"], "processed")

            progress = self.call_tool(bridge_handle.port, "get_day_progress", {"local_date": "2026-09-13"})
            self.assertEqual(progress["status"], "ok")
            self.assertEqual(progress["day_case"]["local_date"], "2026-09-13")
            self.assertEqual(progress["day_case"]["plan_capture_id"], created["capture_id"])
            self.assertEqual(progress["day_case"]["report_capture_id"], report["capture_id"])
            evidence = progress["day_case"]["progress"]["evidence_capture_ids"]
            self.assertIn(created["capture_id"], evidence)
            self.assertIn(report["capture_id"], evidence)
            self.assertGreaterEqual(len(progress["links"]), 4)

            with core_connect(db_path) as conn:
                after = self.capture_counts(conn)
                self.assertEqual(after["core_captures"], before["core_captures"] + 2)
                self.assertEqual(after["core_day_cases"], before["core_day_cases"] + 1)
                self.assertEqual(after["core_signals"], before["core_signals"] + 2)
                self.assertEqual(after["actions"], before["actions"])
                self.assertEqual(after["live_signals"], before["live_signals"])
        finally:
            self.stop_bridge(bridge_handle)
            tempdir.cleanup()

        no_auth_dir = tempfile.TemporaryDirectory()
        no_auth_db = Path(no_auth_dir.name) / "capture-no-auth.db"
        no_auth_bridge = self.start_bridge(no_auth_db, api_key=None)
        try:
            with core_connect(no_auth_db) as conn:
                before = self.capture_counts(conn)
            denied = self.call_tool(
                no_auth_bridge.port,
                "ingest_capture",
                {**self.capture_payload(idempotency_key="capture-auth-denied-001"), "confirmed": True},
            )
            self.assertFalse(denied["ok"])
            self.assertIn("INFO_ANALYZER_API_KEY", denied["error"])
            with core_connect(no_auth_db) as conn:
                self.assertEqual(self.capture_counts(conn), before)
        finally:
            self.stop_bridge(no_auth_bridge)
            no_auth_dir.cleanup()

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_source_observation_ingestion_pending_posted_retry_correction_and_auth(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "source-observations.db"
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            with core_connect(db_path) as conn:
                before_counts = self.source_observation_counts(conn)
                initial_status = self.call_tool(bridge_handle.port, "get_system_status", {})
                innbank = next(system for system in initial_status["systems"] if system["system_id"] == "sys_innbank")
                self.assertEqual(innbank["source_observations"]["status"], "implemented_empty")
                self.assertEqual(innbank["workers"]["status"], "sender_or_poller_not_configured")

            pending_payload = self.source_observation_payload(
                source_transaction_id="pending-payroll-001",
                observation_status="pending",
                economic_inflow_key="econ-payroll-001",
            )
            pending = self.call_tool(
                bridge_handle.port,
                "record_financial_source_observation",
                {**pending_payload, "confirmed": True},
            )
            self.assertTrue(pending["ok"])
            self.assertTrue(pending["pending_without_event"])
            self.assertIsNone(pending["event_id"])
            self.assertEqual(pending["observation"]["observation_status"], "pending")

            pending_status = self.call_tool(
                bridge_handle.port,
                "get_source_observation_status",
                {"observation_id": pending["observation"]["observation_id"]},
            )
            self.assertTrue(pending_status["ok"])
            self.assertEqual(pending_status["observations"][0]["event_id"], None)
            self.assertIn("pending observation", pending_status["observations"][0]["status_explanation"])

            posted_payload = self.source_observation_payload(
                source_transaction_id="posted-payroll-001",
                observation_status="posted",
                economic_inflow_key="econ-payroll-001",
                posted_at="2026-09-17T12:00:00-07:00",
            )
            posted = self.call_tool(
                bridge_handle.port,
                "record_financial_source_observation",
                {**posted_payload, "confirmed": True},
            )
            self.assertTrue(posted["ok"])
            self.assertIsNotNone(posted["event_id"])
            self.assertTrue(str(posted["signal_id"]).startswith("SIG-"))
            self.assertTrue(str(posted["alert_id"]).startswith("ALT-"))
            self.assertEqual(posted["observation"]["pending_observation_id"], pending["observation"]["observation_id"])

            retry = self.call_tool(
                bridge_handle.port,
                "record_financial_source_observation",
                {**posted_payload, "confirmed": True},
            )
            self.assertTrue(retry["ok"])
            self.assertEqual(retry["observation"]["observation_id"], posted["observation"]["observation_id"])
            self.assertEqual(retry["event_id"], posted["event_id"])
            self.assertEqual(retry["signal_id"], posted["signal_id"])
            self.assertEqual(retry["alert_id"], posted["alert_id"])

            correction = self.call_tool(
                bridge_handle.port,
                "record_financial_source_observation",
                {**posted_payload, "amount_cents": 108514, "confirmed": True},
            )
            self.assertTrue(correction["ok"])
            self.assertNotEqual(correction["observation"]["observation_id"], posted["observation"]["observation_id"])
            self.assertEqual(correction["event_id"], posted["event_id"])
            self.assertEqual(correction["signal_id"], posted["signal_id"])
            self.assertEqual(correction["alert_id"], posted["alert_id"])

            by_economic_key = self.call_tool(
                bridge_handle.port,
                "get_source_observation_status",
                {
                    "source_system_id": "sys_innbank",
                    "source_connection_id": "conn-chatgpt-finances-test",
                    "account_external_id": "acct-test-checking",
                    "economic_inflow_key": "econ-payroll-001",
                    "limit": 10,
                },
            )
            self.assertTrue(by_economic_key["ok"])
            self.assertEqual(by_economic_key["status"], "ok")
            self.assertEqual(len(by_economic_key["observations"]), 3)

            with core_connect(db_path) as conn:
                after_counts = self.source_observation_counts(conn)
                self.assertEqual(after_counts["core_events"], before_counts["core_events"] + 1)
                self.assertEqual(after_counts["core_signals"], before_counts["core_signals"] + 1)
                self.assertEqual(after_counts["core_alerts"], before_counts["core_alerts"] + 1)
                self.assertEqual(after_counts["core_source_observations"], before_counts["core_source_observations"] + 3)
                self.assertEqual(after_counts["actions"], before_counts["actions"])
                self.assertEqual(after_counts["live_signals"], before_counts["live_signals"])

            missing = self.call_tool(
                bridge_handle.port,
                "record_financial_source_observation",
                {**pending_payload, "source_transaction_id": "", "confirmed": True},
            )
            self.assertFalse(missing["ok"])
            self.assertIn("source_transaction_id", missing["error"])
        finally:
            self.stop_bridge(bridge_handle)
            tempdir.cleanup()

        no_auth_dir = tempfile.TemporaryDirectory()
        no_auth_db = Path(no_auth_dir.name) / "source-observations-no-auth.db"
        no_auth_bridge = self.start_bridge(no_auth_db, api_key=None)
        try:
            with core_connect(no_auth_db) as conn:
                before = self.source_observation_counts(conn)
            denied = self.call_tool(
                no_auth_bridge.port,
                "record_financial_source_observation",
                {**self.source_observation_payload(source_transaction_id="auth-denied-001"), "confirmed": True},
            )
            self.assertFalse(denied["ok"])
            self.assertIn("INFO_ANALYZER_API_KEY", denied["error"])
            with core_connect(no_auth_db) as conn:
                self.assertEqual(self.source_observation_counts(conn), before)
        finally:
            self.stop_bridge(no_auth_bridge)
            no_auth_dir.cleanup()

    @unittest.skipUnless(MCP_AVAILABLE, "official MCP SDK is not installed")
    def test_shared_ledger_tools_over_mcp_are_read_only_and_legacy_opt_in(self) -> None:
        tempdir = tempfile.TemporaryDirectory()
        root = Path(tempdir.name)
        db_path = root / "shared-ledger.db"
        shutil.copy2(CANONICAL_DB, db_path)
        bridge_handle = self.start_bridge(db_path, api_key="test-key")
        try:
            with core_connect(db_path) as conn:
                before_counts = self.shared_read_counts(conn)

            status = self.call_tool(bridge_handle.port, "get_system_status", {})
            self.assertEqual(status["status"], "ok")
            self.assertTrue(status["foreign_keys_enforced"])
            self.assertIn("core_events", status["coverage"]["tables"])

            cases = self.call_tool(bridge_handle.port, "list_cases", {"limit": 1})
            self.assertEqual(cases["status"], "ok")
            self.assertFalse(cases["legacy_included"])
            self.assertEqual(cases["cases"][0]["case_id"], "core:innbank_allocation_plan:IPL-703C8FAA34DE4857")

            case = self.call_tool(
                bridge_handle.port,
                "get_case",
                {"case_id": "core:innbank_allocation_plan:IPL-703C8FAA34DE4857"},
            )
            self.assertEqual(case["status"], "ok")
            self.assertEqual(case["case"]["kind"], "normalized")
            self.assertEqual(case["case"]["delivery"]["status"], "delivery_unknown")

            trace = self.call_tool(
                bridge_handle.port,
                "get_event_trace",
                {"event_id": "EVT-ABA4A8FDC3C64D6C"},
            )
            self.assertEqual(trace["status"], "ok")
            self.assertEqual(trace["event"]["event_id"], "EVT-ABA4A8FDC3C64D6C")
            self.assertEqual(trace["delivery_status"], "delivery_unknown")

            default_cases = self.call_tool(bridge_handle.port, "list_cases", {"limit": 5})
            self.assertTrue(all(item["kind"] == "normalized" for item in default_cases["cases"]))

            legacy = self.call_tool(
                bridge_handle.port,
                "list_cases",
                {"include_legacy": True, "legacy_type": "entries", "limit": 2},
            )
            self.assertTrue(legacy["legacy_included"])
            self.assertEqual(len(legacy["cases"]), 2)
            self.assertTrue(all(item["kind"] == "legacy_candidate" for item in legacy["cases"]))
            self.assertTrue(all(item["legacy_table"] == "entries" for item in legacy["cases"]))
            self.assertIn("provenance", legacy["cases"][0])

            invalid_case = self.call_tool(bridge_handle.port, "get_case", {"case_id": "core:innbank_allocation_plan:missing"})
            self.assertFalse(invalid_case["ok"])
            self.assertIn("case not found", invalid_case["error"])

            invalid_trace = self.call_tool(bridge_handle.port, "get_event_trace", {"event_id": "EVT-MISSING"})
            self.assertFalse(invalid_trace["ok"])
            self.assertIn("event not found", invalid_trace["error"])

            with core_connect(db_path) as conn:
                self.assertEqual(self.shared_read_counts(conn), before_counts)
        finally:
            self.stop_bridge(bridge_handle)
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

    def source_observation_counts(self, conn):
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        result = {}
        for name in [
            "core_source_observations",
            "core_ingestion_results",
            "core_events",
            "core_signals",
            "core_alerts",
            "core_decisions",
            "core_actions",
            "core_outcomes",
            "actions",
            "live_signals",
        ]:
            result[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] if name in tables else 0
        return result

    def capture_counts(self, conn):
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        result = {}
        for name in [
            "core_captures",
            "core_day_cases",
            "core_capture_derivations",
            "core_operations",
            "core_operation_attempts",
            "core_signals",
            "core_actions",
            "actions",
            "live_signals",
        ]:
            result[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] if name in tables else 0
        return result

    def capture_payload(
        self,
        *,
        capture_type: str = "begin_day_checklist",
        idempotency_key: str,
        request_id: str = "req-capture-001",
        message_id: str = "msg-capture-001",
        raw_text: str = "Begin-Day Checklist\n- Review today's signal movement",
        occurred_at: str = "2026-09-13T08:00:00-07:00",
        captured_at: str = "2026-09-13T08:01:00-07:00",
    ):
        return {
            "capture_type": capture_type,
            "source": "chatgpt",
            "raw_text": raw_text,
            "occurred_at": occurred_at,
            "captured_at": captured_at,
            "conversation_id": "conv-capture-test",
            "message_id": message_id,
            "request_id": request_id,
            "correlation_id": "corr-capture-test",
            "idempotency_key": idempotency_key,
            "payload_version": 1,
            "metadata": {"fixture": True},
        }

    def shared_read_counts(self, conn):
        return {
            name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in [
                "core_events",
                "core_signals",
                "core_alerts",
                "core_decisions",
                "core_actions",
                "core_outcomes",
                "innbank_allocation_plans",
                "innbank_allocation_items",
                "actions",
                "live_signals",
                "audit_log",
            ]
        }

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

    def source_observation_payload(
        self,
        *,
        source_transaction_id: str,
        observation_status: str = "pending",
        economic_inflow_key: str | None = None,
        posted_at: str | None = None,
    ):
        return {
            "source_system_id": "sys_innbank",
            "source_connection_id": "conn-chatgpt-finances-test",
            "account_external_id": "acct-test-checking",
            "source_transaction_id": source_transaction_id,
            "observation_status": observation_status,
            "observed_at": "2026-09-17T12:05:00-07:00",
            "amount_cents": 108414,
            "currency": "USD",
            "account_name": "Fictional Test Checking",
            "classification": "payroll",
            "classification_confidence": 0.99,
            "effective_date": "2026-09-17",
            "posted_at": posted_at,
            "source_name": "ChatGPT Finances supplied observation",
            "observation_type": "financial_inflow",
            "economic_inflow_key": economic_inflow_key or source_transaction_id,
            "provider_transaction_id": source_transaction_id,
            "metadata": {
                "fixture": True,
                "source_field_mapping": "fictional_finances_observation",
            },
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
                return {tool.name for tool in tools} == MCP_TOOL_NAMES
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
