from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
import unittest

from core_database import connect as core_connect
from tests.support import request_json, start_server, stop_server


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DB = ROOT / "data" / "info_analyzer.db"


WATCH_TABLES = [
    "core_events",
    "core_signals",
    "core_alerts",
    "innbank_allocation_plans",
    "innbank_allocation_items",
    "core_decisions",
    "core_actions",
    "core_outcomes",
    "actions",
    "live_signals",
    "audit_log",
]


class SharedAccessTests(unittest.TestCase):
    def copy_db(self, name: str = "shared.db") -> tuple[tempfile.TemporaryDirectory, Path]:
        tempdir = tempfile.TemporaryDirectory()
        db_path = Path(tempdir.name) / name
        shutil.copy2(CANONICAL_DB, db_path)
        return tempdir, db_path

    def counts(self, db_path: Path) -> dict[str, int]:
        with core_connect(db_path) as conn:
            return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in WATCH_TABLES}

    def shared_get(self, port: int, path: str, *, key: str = "test-key"):
        return request_json(port, path, headers={"Authorization": f"Bearer {key}", "X-Request-ID": "REQ-SHARED-TEST"})

    def test_shared_status_cases_trace_and_legacy_reads_are_read_only(self) -> None:
        tempdir, db_path = self.copy_db()
        handle = start_server(db_path, api_key="test-key")
        try:
            before = self.counts(db_path)

            status, body = self.shared_get(handle.port, "/shared/system-status")
            self.assertEqual(status, 200)
            self.assertTrue(body["foreign_keys_enforced"])
            self.assertIn("core_events", body["coverage"]["tables"])
            self.assertTrue(any(system["system_id"] == "sys_innbank" for system in body["systems"]))

            cases_status, cases = self.shared_get(handle.port, "/shared/cases?limit=1")
            self.assertEqual(cases_status, 200)
            self.assertEqual(cases["status"], "ok")
            self.assertEqual(len(cases["cases"]), 1)
            case_id = cases["cases"][0]["case_id"]
            self.assertEqual(case_id, "core:innbank_allocation_plan:IPL-703C8FAA34DE4857")
            self.assertEqual(cases["pagination"]["stable_order"], "created_at DESC, stable primary key ASC")

            case_status, case = self.shared_get(handle.port, f"/shared/cases/{case_id}")
            self.assertEqual(case_status, 200)
            self.assertEqual(case["case"]["kind"], "normalized")
            self.assertEqual(case["case"]["plan"]["plan_id"], "IPL-703C8FAA34DE4857")
            self.assertEqual(case["case"]["delivery"]["status"], "delivery_unknown")

            trace_status, trace = self.shared_get(handle.port, "/shared/event-trace/EVT-ABA4A8FDC3C64D6C")
            self.assertEqual(trace_status, 200)
            self.assertEqual(trace["event"]["event_id"], "EVT-ABA4A8FDC3C64D6C")
            self.assertEqual(trace["delivery_status"], "delivery_unknown")
            self.assertEqual(trace["signals"][0]["signal_id"], "SIG-266403086E2C4264")

            legacy_status, legacy = self.shared_get(handle.port, "/shared/cases?include_legacy=true&legacy_type=entries&limit=3")
            self.assertEqual(legacy_status, 200)
            self.assertTrue(legacy["legacy_included"])
            self.assertTrue(all(item["kind"] == "legacy_candidate" for item in legacy["cases"]))
            self.assertTrue(all(item["legacy_table"] == "entries" for item in legacy["cases"]))

            action_status, actions = self.shared_get(handle.port, "/shared/cases?include_legacy=true&legacy_type=actions&limit=2")
            self.assertEqual(action_status, 200)
            self.assertTrue(all(item["legacy_table"] == "actions" for item in actions["cases"]))

            after = self.counts(db_path)
            self.assertEqual(before, after)
        finally:
            stop_server(handle)
            tempdir.cleanup()

    def test_shared_access_auth_invalid_identifiers_and_pagination(self) -> None:
        tempdir, db_path = self.copy_db("shared-auth.db")
        handle = start_server(db_path, api_key="test-key")
        try:
            unauth_status, unauth = request_json(handle.port, "/shared/system-status")
            self.assertEqual(unauth_status, 401)
            self.assertEqual(unauth["error"]["code"], "unauthorized")

            page_one_status, page_one = self.shared_get(handle.port, "/shared/cases?include_legacy=true&legacy_type=entries&limit=2&cursor=0")
            page_two_status, page_two = self.shared_get(handle.port, "/shared/cases?include_legacy=true&legacy_type=entries&limit=2&cursor=2")
            self.assertEqual(page_one_status, 200)
            self.assertEqual(page_two_status, 200)
            self.assertEqual(len(page_one["cases"]), 2)
            self.assertEqual(len(page_two["cases"]), 2)
            self.assertNotEqual(
                [item["case_id"] for item in page_one["cases"]],
                [item["case_id"] for item in page_two["cases"]],
            )

            bad_case_status, bad_case = self.shared_get(handle.port, "/shared/cases/core:innbank_allocation_plan:missing")
            self.assertEqual(bad_case_status, 404)
            self.assertIn("case not found", bad_case["error"])

            bad_trace_status, bad_trace = self.shared_get(handle.port, "/shared/event-trace/EVT-MISSING")
            self.assertEqual(bad_trace_status, 404)
            self.assertIn("event not found", bad_trace["error"])
        finally:
            stop_server(handle)
            tempdir.cleanup()

    def test_shared_access_preserves_payday_tool_compatibility_and_fk_helper(self) -> None:
        tempdir, db_path = self.copy_db("shared-payday.db")
        handle = start_server(db_path, api_key="test-key")
        try:
            with core_connect(db_path) as conn:
                self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            status, plan = request_json(handle.port, "/innbank/allocation-plans/IPL-703C8FAA34DE4857")
            self.assertEqual(status, 200)
            self.assertEqual(plan["plan"]["plan_id"], "IPL-703C8FAA34DE4857")
            self.assertEqual(plan["plan"]["status"], "proposed")
        finally:
            stop_server(handle)
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
