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
                {"get_payday_case", "save_payday_decision", "record_manual_routing"},
            )
            annotations = {tool.name: tool.annotations for tool in tools}
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
                return len(tools) == 3
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
