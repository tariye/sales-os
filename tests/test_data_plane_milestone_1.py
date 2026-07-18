from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

import data_plane_m1


BASE_DIR = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class DataPlaneMilestone1TestCase(unittest.TestCase):
    SOCKET_TESTS_ENABLED = os.environ.get("INFO_ANALYZER_ENABLE_SOCKET_TESTS") == "1"

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="data-plane-m1-"))
        self.db_path = self.temp_dir / "info_analyzer.db"
        data_plane_m1.apply_migrations(self.db_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _claim_and_process(self, scenario: str, *, max_attempts: int = 3, source_id: str = data_plane_m1.DEFAULT_SOURCE_ID):
        job = data_plane_m1.create_job(
            self.db_path,
            source_id,
            scenario,
            idempotency_key=f"test:{source_id}:{scenario}:{time.time_ns()}",
            max_attempts=max_attempts,
        )
        claimed = data_plane_m1.claim_next_job(self.db_path, "worker-a")
        self.assertIsNotNone(claimed)
        result = data_plane_m1.process_claimed_job(self.db_path, claimed, "worker-a")
        return job, claimed, result

    def test_01_scheduler_creates_due_job_while_ui_closed(self) -> None:
        runtime = data_plane_m1.RuntimeService(self.db_path, scheduler_poll_seconds=0.2, worker_poll_seconds=0.2, lease_seconds=2)
        runtime.start()
        try:
            created = wait_for(lambda: data_plane_m1.list_jobs(self.db_path)["count"] >= 1)
            self.assertTrue(created)
        finally:
            runtime.stop()

    def test_02_only_one_scheduler_leader_holds_active_lease(self) -> None:
        now_value = data_plane_m1.now_utc()
        self.assertTrue(data_plane_m1.acquire_scheduler_lease(self.db_path, "leader-a", lease_seconds=5, now_value=now_value))
        self.assertFalse(data_plane_m1.acquire_scheduler_lease(self.db_path, "leader-b", lease_seconds=5, now_value=now_value))

    def test_03_expired_scheduler_lease_can_be_recovered(self) -> None:
        now_value = data_plane_m1.now_utc()
        self.assertTrue(data_plane_m1.acquire_scheduler_lease(self.db_path, "leader-a", lease_seconds=2, now_value=now_value))
        self.assertTrue(
            data_plane_m1.acquire_scheduler_lease(
                self.db_path,
                "leader-b",
                lease_seconds=2,
                now_value=now_value + data_plane_m1.timedelta(seconds=3),
            )
        )

    def test_04_worker_atomically_claims_one_job(self) -> None:
        job = data_plane_m1.create_job(self.db_path, data_plane_m1.DEFAULT_SOURCE_ID, "success_alpha", idempotency_key="claim-one")
        claimed = data_plane_m1.claim_next_job(self.db_path, "worker-a")
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["status"], "claimed")

    def test_05_second_worker_cannot_claim_same_active_job(self) -> None:
        data_plane_m1.create_job(self.db_path, data_plane_m1.DEFAULT_SOURCE_ID, "success_alpha", idempotency_key="claim-two")
        first = data_plane_m1.claim_next_job(self.db_path, "worker-a")
        second = data_plane_m1.claim_next_job(self.db_path, "worker-b")
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_06_every_collection_attempt_creates_ingest_run(self) -> None:
        job = data_plane_m1.create_job(
            self.db_path,
            data_plane_m1.DEFAULT_SOURCE_ID,
            "failure_epsilon",
            idempotency_key="attempt-runs",
            max_attempts=2,
        )
        claimed_one = data_plane_m1.claim_next_job(self.db_path, "worker-a")
        data_plane_m1.process_claimed_job(self.db_path, claimed_one, "worker-a")
        claimed_two = data_plane_m1.claim_next_job(
            self.db_path,
            "worker-a",
            now_value=data_plane_m1.now_utc() + data_plane_m1.timedelta(seconds=3),
        )
        data_plane_m1.process_claimed_job(self.db_path, claimed_two, "worker-a")
        runs = [run for run in data_plane_m1.list_ingest_runs(self.db_path)["ingest_runs"] if run["job_id"] == job["id"]]
        self.assertEqual(len(runs), 2)

    def test_07_successful_fixture_pull_stores_one_immutable_raw_snapshot(self) -> None:
        _job, _claimed, result = self._claim_and_process("success_alpha")
        snapshots = data_plane_m1.list_raw_snapshot_metadata(self.db_path)["raw_snapshots"]
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(snapshots), 1)

    def test_08_identical_retry_does_not_create_another_raw_snapshot(self) -> None:
        self._claim_and_process("success_alpha")
        self._claim_and_process("repeat_alpha")
        snapshots = data_plane_m1.list_raw_snapshot_metadata(self.db_path)["raw_snapshots"]
        self.assertEqual(len(snapshots), 1)

    def test_09_duplicate_detection_remains_auditable_through_ingest_run(self) -> None:
        self._claim_and_process("success_alpha")
        _job, _claimed, result = self._claim_and_process("repeat_alpha")
        run = data_plane_m1.get_ingest_run(self.db_path, result["ingest_run_id"])
        self.assertEqual(result["status"], "skipped_duplicate")
        self.assertEqual(run["status"], "skipped_duplicate")

    def test_10_changed_fixture_content_creates_new_snapshot(self) -> None:
        self._claim_and_process("success_alpha")
        self._claim_and_process("change_bravo")
        snapshots = data_plane_m1.list_raw_snapshot_metadata(self.db_path)["raw_snapshots"]
        self.assertEqual(len(snapshots), 2)

    def test_11_failed_jobs_retry_according_to_policy(self) -> None:
        job = data_plane_m1.create_job(
            self.db_path,
            data_plane_m1.DEFAULT_SOURCE_ID,
            "failure_epsilon",
            idempotency_key="retry-policy",
            max_attempts=3,
        )
        claimed = data_plane_m1.claim_next_job(self.db_path, "worker-a")
        data_plane_m1.process_claimed_job(self.db_path, claimed, "worker-a")
        reloaded = data_plane_m1.get_job(self.db_path, job["id"])
        self.assertEqual(reloaded["status"], "retry_scheduled")
        self.assertIsNotNone(reloaded["next_retry_at"])

    def test_12_terminal_failure_enters_dead_letter(self) -> None:
        job = data_plane_m1.create_job(
            self.db_path,
            data_plane_m1.DEFAULT_SOURCE_ID,
            "failure_epsilon",
            idempotency_key="dead-letter",
            max_attempts=1,
        )
        claimed = data_plane_m1.claim_next_job(self.db_path, "worker-a")
        data_plane_m1.process_claimed_job(self.db_path, claimed, "worker-a")
        reloaded = data_plane_m1.get_job(self.db_path, job["id"])
        self.assertEqual(reloaded["status"], "dead_letter")

    def test_13_failed_and_stale_sources_create_source_health_events(self) -> None:
        self._claim_and_process("failure_epsilon", max_attempts=1)
        data_plane_m1.create_source(
            self.db_path,
            source_id="fixture-stale-source",
            name="Fixture Stale Source",
            freshness_target_seconds=1,
            configuration={"default_scenario": "stale_seed"},
        )
        self._claim_and_process("stale_seed", source_id="fixture-stale-source")
        data_plane_m1.refresh_stale_sources(
            self.db_path,
            now_value=data_plane_m1.now_utc() + data_plane_m1.timedelta(seconds=3),
        )
        with data_plane_m1.connect_db(self.db_path) as conn:
            rows = conn.execute("SELECT event_type FROM source_health_events ORDER BY created_at").fetchall()
        event_types = [row["event_type"] for row in rows]
        self.assertIn("source_failure", event_types)
        self.assertIn("source_stale", event_types)

    def test_14_restart_recovery_returns_abandoned_jobs_to_valid_state(self) -> None:
        data_plane_m1.create_job(self.db_path, data_plane_m1.DEFAULT_SOURCE_ID, "success_alpha", idempotency_key="recovery")
        claimed = data_plane_m1.claim_next_job(self.db_path, "worker-a", now_value=data_plane_m1.now_utc())
        with data_plane_m1.connect_db(self.db_path) as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at=?, status='running' WHERE id=?",
                (data_plane_m1.now_iso(data_plane_m1.now_utc() - data_plane_m1.timedelta(seconds=1)), claimed["id"]),
            )
            conn.commit()
        with data_plane_m1.connect_db(self.db_path) as conn:
            recovered = data_plane_m1.recover_expired_jobs(conn, data_plane_m1.now_utc())
            conn.commit()
        self.assertEqual(recovered, 1)
        self.assertEqual(data_plane_m1.get_job(self.db_path, claimed["id"])["status"], "queued")

    def test_15_raw_payload_text_remains_unchanged_after_storage(self) -> None:
        _job, _claimed, result = self._claim_and_process("success_alpha")
        expected = data_plane_m1.stable_json(data_plane_m1.FIXTURE_SCENARIOS["success_alpha"]["payload"])
        raw = data_plane_m1.read_raw_snapshot_payload(self.db_path, result["raw_snapshot_id"])
        self.assertEqual(raw, expected)

    def test_16_raw_snapshots_cannot_be_overwritten_through_application_layer(self) -> None:
        with self.assertRaises(PermissionError):
            data_plane_m1.attempt_raw_snapshot_update()

    def test_17_source_health_distinguishes_healthy_stale_failed_and_never_run(self) -> None:
        never_run = data_plane_m1.read_source_health(self.db_path, data_plane_m1.DEFAULT_SOURCE_ID)
        self.assertEqual(never_run["status"], "never_run")

        data_plane_m1.create_source(
            self.db_path,
            source_id="fixture-health-healthy",
            name="Fixture Healthy Source",
            freshness_target_seconds=30,
        )
        self._claim_and_process("success_alpha", source_id="fixture-health-healthy")
        healthy = data_plane_m1.read_source_health(self.db_path, "fixture-health-healthy")
        self.assertEqual(healthy["status"], "healthy")

        data_plane_m1.create_source(
            self.db_path,
            source_id="fixture-health-stale",
            name="Fixture Stale Health Source",
            freshness_target_seconds=1,
        )
        self._claim_and_process("success_alpha", source_id="fixture-health-stale")
        with data_plane_m1.connect_db(self.db_path) as conn:
            source = data_plane_m1.source_by_id(conn, "fixture-health-stale")
            stale = data_plane_m1.compute_source_health(
                conn,
                source,
                now_value=data_plane_m1.now_utc() + data_plane_m1.timedelta(seconds=3),
            )
        self.assertEqual(stale["status"], "stale")

        data_plane_m1.create_source(
            self.db_path,
            source_id="fixture-health-failed",
            name="Fixture Failed Source",
        )
        self._claim_and_process("failure_epsilon", max_attempts=1, source_id="fixture-health-failed")
        failed = data_plane_m1.read_source_health(self.db_path, "fixture-health-failed")
        self.assertEqual(failed["status"], "failed")

    def test_18_sqlite_pragmas_remain_active(self) -> None:
        with data_plane_m1.connect_db(self.db_path) as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(str(journal_mode).lower(), "wal")
        self.assertEqual(int(foreign_keys), 1)
        self.assertGreaterEqual(int(busy_timeout), 5000)

    def test_19_info_analyzer_db_path_persistence_remains_functional(self) -> None:
        if not self.SOCKET_TESTS_ENABLED:
            self.skipTest("socket-backed server tests disabled in sandbox")
        port = free_port()
        env = os.environ.copy()
        env["INFO_ANALYZER_DB_PATH"] = str(self.db_path)
        env["INFO_ANALYZER_API_KEY"] = "test-key"
        server = subprocess.Popen(
            [sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(port)],
            cwd=BASE_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            ready = wait_for(lambda: self._health_ok(port))
            self.assertTrue(ready)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["db_path"], str(self.db_path))
            self.assertTrue(self.db_path.exists())
        finally:
            server.terminate()
            server.wait(timeout=10)
            if server.stdout:
                server.stdout.close()
            if server.stderr:
                server.stderr.close()

    def test_20_existing_v1_api_and_full_site_regression_tests_still_pass(self) -> None:
        if not self.SOCKET_TESTS_ENABLED:
            self.skipTest("socket-backed server tests disabled in sandbox")
        port = free_port()
        env = os.environ.copy()
        env["INFO_ANALYZER_DB_PATH"] = str(self.db_path)
        env["INFO_ANALYZER_API_KEY"] = "local-v1-proof-key"
        server = subprocess.Popen(
            [sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(port)],
            cwd=BASE_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            ready = wait_for(lambda: self._health_ok(port), timeout=12.0)
            self.assertTrue(ready)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/data-plane/source-health", timeout=10) as response:
                health = json.loads(response.read().decode("utf-8"))
            self.assertIn("sources", health)
            loop = subprocess.run(
                [sys.executable, "tools/loop_check.py", "--base-url", f"http://127.0.0.1:{port}"],
                cwd=BASE_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(loop.returncode, 0, loop.stdout + "\n" + loop.stderr)
            api_loop = subprocess.run(
                [
                    sys.executable,
                    "tools/api_v1_loop_check.py",
                    "--base-url",
                    f"http://127.0.0.1:{port}",
                    "--api-key",
                    "local-v1-proof-key",
                ],
                cwd=BASE_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(api_loop.returncode, 0, api_loop.stdout + "\n" + api_loop.stderr)
        finally:
            server.terminate()
            server.wait(timeout=10)
            if server.stdout:
                server.stdout.close()
            if server.stderr:
                server.stderr.close()

    def _health_ok(self, port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("ok"))
        except Exception:
            return False


if __name__ == "__main__":
    unittest.main()
