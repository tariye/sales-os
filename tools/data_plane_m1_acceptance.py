#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.error


def request(base_url: str, method: str, path: str, payload: dict | None = None, timeout: float = 20) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8") or "{}")


def wait_for(predicate, timeout: float, label: str, interval: float = 0.2):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {label}; last={last!r}")


def db_rows(db_path: str, sql: str, args=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def db_one(db_path: str, sql: str, args=()):
    rows = db_rows(db_path, sql, args)
    return rows[0] if rows else None


def db_exec(db_path: str, sql: str, args=()):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args, **_kwargs):
        return

    @property
    def state(self):
        return self.server.fixture_state

    def do_GET(self):
        route = self.state["routes"].get(self.path)
        if self.path == "/__state":
            return self._json(200, self.state)
        if not route:
            return self._json(404, {"error": "unknown path"})
        count = self.state["counts"].get(self.path, 0) + 1
        self.state["counts"][self.path] = count
        step = route[min(count - 1, len(route) - 1)]
        body = step["body"].replace("{count}", str(count)).encode("utf-8")
        self.send_response(step["status"])
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if self.path == "/__set":
            self.state["routes"][payload["path"]] = payload["steps"]
            self.state["counts"][payload["path"]] = 0
            return self._json(200, {"ok": True})
        if self.path == "/__reset":
            self.server.fixture_state = {"routes": {}, "counts": {}}
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "unknown control path"})

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_fixture_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server.fixture_state = {"routes": {}, "counts": {}}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def server_env(db_path: str, api_key: str):
    env = os.environ.copy()
    env["INFO_ANALYZER_DB_PATH"] = db_path
    env["INFO_ANALYZER_API_KEY"] = api_key
    env["INFO_ANALYZER_DISABLE_DATA_PLANE_THREADS"] = "1"
    return env


def start_server(repo_dir: Path, env: dict, port: int, log_path: Path) -> subprocess.Popen:
    handle = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(port)],
        cwd=repo_dir,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    proc._log_handle = handle  # type: ignore[attr-defined]
    return proc


def stop_server(proc: subprocess.Popen | None):
    if not proc:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    handle = getattr(proc, "_log_handle", None)
    if handle:
        handle.close()


def fixture_set(port: int, path: str, steps: list[dict]):
    request(f"http://127.0.0.1:{port}", "POST", "/__set", {"path": path, "steps": steps})


def source_by_name(base_url: str, name: str) -> dict:
    rows = request(base_url, "GET", "/api/ingest/sources").get("sources", [])
    for row in rows:
        if row.get("name") == name:
            return row
    raise KeyError(name)


def scheduler_tick(base_url: str):
    return request(base_url, "POST", "/api/data-plane/scheduler/tick", {})


def worker_tick(base_url: str, worker_id: str):
    return request(base_url, "POST", "/api/data-plane/worker/tick", {"worker_id": worker_id})


def worker_tick_may_abort(base_url: str, worker_id: str):
    try:
        return worker_tick(base_url, worker_id)
    except (urllib.error.URLError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
        return {"claimed": True, "aborted": True, "worker_id": worker_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port-a", type=int, default=8041)
    parser.add_argument("--port-b", type=int, default=8042)
    parser.add_argument("--db", default="/tmp/info-analyzer-m1-acceptance/acceptance.db")
    parser.add_argument("--api-key", default="acceptance-local-key")
    parser.add_argument("--write-proof", default="")
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parents[1]
    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            side.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    fixture_server, fixture_port = start_fixture_server()
    env = server_env(str(db_path), args.api_key)
    log_a = db_path.parent / "server-a.log"
    log_b = db_path.parent / "server-b.log"
    server_a = start_server(repo_dir, env, args.port_a, log_a)
    server_b = start_server(repo_dir, env, args.port_b, log_b)
    base_a = f"http://127.0.0.1:{args.port_a}"
    base_b = f"http://127.0.0.1:{args.port_b}"

    proof = {
        "build": {},
        "scenarios": [],
    }

    try:
        health_a = wait_for(lambda: request(base_a, "GET", "/api/health"), 20, "server A health")
        health_b = wait_for(lambda: request(base_b, "GET", "/api/health"), 20, "server B health")
        proof["build"] = {
            "version": health_a.get("version"),
            "db_path": health_a.get("db_path"),
            "schema_version": health_a.get("data_plane", {}).get("schema_version"),
        }

        # 1. Two-worker contention.
        fixture_set(fixture_port, "/contention", [{"status": 200, "body": "contention payload"}])
        contention = request(base_a, "POST", "/api/ingest/sources", {
            "name": "Acceptance Contention Source",
            "source_type": "url",
            "url": f"http://127.0.0.1:{fixture_port}/contention",
            "domain": "Business",
            "entity": "Contention Entity",
            "poll_interval_minutes": 5,
            "stale_after_seconds": 60,
        })["source"]
        scheduler_tick(base_a)
        results: list[dict] = []
        threads = []
        def run_worker(base_url: str, worker_id: str):
            results.append(worker_tick(base_url, worker_id))
        for base_url, worker_id in ((base_a, "worker-A"), (base_b, "worker-B")):
            t = threading.Thread(target=run_worker, args=(base_url, worker_id))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        contention_runs = db_rows(str(db_path), "SELECT * FROM ingest_runs WHERE source_id=?", (contention["id"],))
        contention_snaps = db_rows(str(db_path), "SELECT * FROM raw_snapshots WHERE source_id=?", (contention["id"],))
        contention_health = db_rows(str(db_path), "SELECT * FROM source_health_events WHERE source_id=?", (contention["id"],))
        proof["scenarios"].append({
            "name": "two_worker_contention",
            "worker_results": results,
            "runs": contention_runs,
            "snapshots": contention_snaps,
            "health_events": contention_health,
            "ok": len(contention_runs) == 1 and len(contention_snaps) == 1 and sum(1 for r in results if r.get("claimed")) == 1,
        })

        # 2. Crash before run start and recovery.
        fixture_set(fixture_port, "/crash-before", [{"status": 200, "body": "crash before payload"}])
        before = request(base_a, "POST", "/api/ingest/sources", {
            "name": "Acceptance Crash Before Start",
            "source_type": "url",
            "url": f"http://127.0.0.1:{fixture_port}/crash-before",
            "domain": "Business",
            "entity": "Crash Before",
            "poll_interval_minutes": 5,
            "stale_after_seconds": 60,
            "metadata": {"test_crash_once": "before_run"},
        })["source"]
        scheduler_tick(base_a)
        worker_tick_may_abort(base_a, "crash-before-worker")
        wait_for(lambda: db_one(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=?", (before["id"],)), 5, "before-start job row")
        db_exec(str(db_path), "UPDATE data_plane_jobs SET claim_expires_at='2000-01-01T00:00:00+00:00' WHERE source_id=?", (before["id"],))
        recovered_before = worker_tick(base_b, "recovery-worker-before")
        before_job = db_one(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=?", (before["id"],))
        before_runs = db_rows(str(db_path), "SELECT * FROM ingest_runs WHERE source_id=?", (before["id"],))
        before_snaps = db_rows(str(db_path), "SELECT * FROM raw_snapshots WHERE source_id=?", (before["id"],))
        before_audit = db_rows(str(db_path), "SELECT * FROM audit_log WHERE entity_type='data_plane_job' AND entity_id=? ORDER BY created_at", (before_job["id"],))
        proof["scenarios"].append({
            "name": "abandoned_job_recovery_before_run",
            "worker_result": recovered_before,
            "job": before_job,
            "runs": before_runs,
            "snapshots": before_snaps,
            "audit": before_audit,
            "ok": before_job["status"] == "succeeded" and int(before_job["recovery_count"] or 0) >= 1 and len(before_runs) == 1 and len(before_snaps) == 1,
        })

        # 3. Crash during run and recovery with same run id.
        fixture_set(fixture_port, "/crash-during", [{"status": 200, "body": "crash during payload"}])
        during = request(base_a, "POST", "/api/ingest/sources", {
            "name": "Acceptance Crash During Run",
            "source_type": "url",
            "url": f"http://127.0.0.1:{fixture_port}/crash-during",
            "domain": "Business",
            "entity": "Crash During",
            "poll_interval_minutes": 5,
            "stale_after_seconds": 60,
            "metadata": {"test_crash_once": "during_run"},
        })["source"]
        scheduler_tick(base_a)
        worker_tick_may_abort(base_a, "crash-during-worker")
        during_job = wait_for(lambda: db_one(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=?", (during["id"],)), 5, "during-run job")
        first_run_id = during_job["run_id"]
        db_exec(str(db_path), "UPDATE data_plane_jobs SET claim_expires_at='2000-01-01T00:00:00+00:00' WHERE source_id=?", (during["id"],))
        recovered_during = worker_tick(base_b, "recovery-worker-during")
        during_job = db_one(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=?", (during["id"],))
        during_runs = db_rows(str(db_path), "SELECT * FROM ingest_runs WHERE source_id=?", (during["id"],))
        during_snaps = db_rows(str(db_path), "SELECT * FROM raw_snapshots WHERE source_id=?", (during["id"],))
        proof["scenarios"].append({
            "name": "abandoned_job_recovery_during_run",
            "worker_result": recovered_during,
            "job": during_job,
            "runs": during_runs,
            "snapshots": during_snaps,
            "ok": during_job["status"] == "succeeded" and during_job["run_id"] == first_run_id and len(during_runs) == 1 and len(during_snaps) == 1,
        })

        # 4. Scheduler failover and no duplicate due jobs.
        fixture_set(fixture_port, "/scheduler", [{"status": 200, "body": "scheduler payload"}])
        sched_source = request(base_a, "POST", "/api/ingest/sources", {
            "name": "Acceptance Scheduler Source",
            "source_type": "url",
            "url": f"http://127.0.0.1:{fixture_port}/scheduler",
            "domain": "Business",
            "entity": "Scheduler Entity",
            "poll_interval_minutes": 5,
            "stale_after_seconds": 60,
        })["source"]
        lease_a = scheduler_tick(base_a)
        lease_b_blocked = scheduler_tick(base_b)
        db_exec(str(db_path), "UPDATE scheduler_leases SET lease_until='2000-01-01T00:00:00+00:00' WHERE id='default'")
        lease_b_takeover = scheduler_tick(base_b)
        worker_tick(base_b, "scheduler-worker")
        scheduler_jobs = db_rows(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=?", (sched_source["id"],))
        scheduler_events = db_rows(str(db_path), "SELECT * FROM scheduler_events ORDER BY created_at DESC LIMIT 5")
        proof["scenarios"].append({
            "name": "scheduler_failover",
            "lease_a": lease_a,
            "lease_b_blocked": lease_b_blocked,
            "lease_b_takeover": lease_b_takeover,
            "jobs": scheduler_jobs,
            "scheduler_events": scheduler_events,
            "ok": lease_a["lease"]["owner_id"] != lease_b_takeover["lease"]["owner_id"] and len(scheduler_jobs) == 1,
        })

        # 5. Retry to healthy with restart persistence.
        fixture_set(fixture_port, "/retry", [
            {"status": 500, "body": "temporary failure"},
            {"status": 200, "body": "retry success payload"},
        ])
        retry_source = request(base_b, "POST", "/api/ingest/sources", {
            "name": "Acceptance Retry Source",
            "source_type": "url",
            "url": f"http://127.0.0.1:{fixture_port}/retry",
            "domain": "Business",
            "entity": "Retry Entity",
            "poll_interval_minutes": 5,
            "stale_after_seconds": 60,
            "max_attempts": 3,
        })["source"]
        scheduler_tick(base_b)
        worker_tick(base_b, "retry-worker-a")
        retry_job = db_one(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=?", (retry_source["id"],))
        retry_source_view = source_by_name(base_b, "Acceptance Retry Source")
        stop_server(server_a)
        server_a = start_server(repo_dir, env, args.port_a, log_a)
        wait_for(lambda: request(base_a, "GET", "/api/health").get("ok"), 20, "server A restart health")
        retry_source_after_restart = source_by_name(base_a, "Acceptance Retry Source")
        recovered_retry = worker_tick(base_b, "retry-worker-b")
        retry_job_final = db_one(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=?", (retry_source["id"],))
        retry_source_final = source_by_name(base_b, "Acceptance Retry Source")
        retry_snaps = db_rows(str(db_path), "SELECT * FROM raw_snapshots WHERE source_id=?", (retry_source["id"],))
        retry_health = db_rows(str(db_path), "SELECT * FROM source_health_events WHERE source_id=? ORDER BY created_at", (retry_source["id"],))
        proof["scenarios"].append({
            "name": "retry_to_healthy",
            "retry_job": retry_job,
            "source_before_restart": retry_source_view,
            "source_after_restart": retry_source_after_restart,
            "recovered_retry": recovered_retry,
            "final_job": retry_job_final,
            "final_source": retry_source_final,
            "snapshots": retry_snaps,
            "health_events": retry_health,
            "ok": (
                retry_source_view["health_status"] == "retrying"
                and (retry_source_view.get("retry_state") or {}).get("next_retry_at") == retry_job.get("next_attempt_at")
                and retry_source_view.get("health_message") == "The latest attempt failed and another attempt is scheduled."
                and retry_source_after_restart["health_status"] == "retrying"
                and (retry_source_after_restart.get("retry_state") or {}).get("next_retry_at") == retry_job.get("next_attempt_at")
                and retry_source_final["health_status"] == "healthy"
                and (retry_source_final.get("retry_state") or {}).get("next_retry_at", "") == ""
                and retry_source_final.get("health_message") == "Latest ingest completed successfully."
                and len(retry_snaps) == 1
            ),
        })

        # 6. Dead-letter clears active next retry presentation.
        fixture_set(fixture_port, "/dead-letter", [{"status": 500, "body": "permanent failure"}])
        dead_letter = request(base_b, "POST", "/api/ingest/sources", {
            "name": "Acceptance Dead Letter Source",
            "source_type": "url",
            "url": f"http://127.0.0.1:{fixture_port}/dead-letter",
            "domain": "Business",
            "entity": "Dead Letter Entity",
            "poll_interval_minutes": 5,
            "stale_after_seconds": 60,
            "max_attempts": 2,
        })["source"]
        scheduler_tick(base_b)
        worker_tick(base_b, "dead-letter-worker-a")
        db_exec(str(db_path), "UPDATE data_plane_jobs SET next_attempt_at='2000-01-01T00:00:00+00:00' WHERE source_id=?", (dead_letter["id"],))
        worker_tick(base_b, "dead-letter-worker-b")
        dead_view = source_by_name(base_b, "Acceptance Dead Letter Source")
        dead_events = db_rows(str(db_path), "SELECT status, message FROM source_health_events WHERE source_id=? ORDER BY created_at", (dead_letter["id"],))
        proof["scenarios"].append({
            "name": "dead_letter_clears_next_retry",
            "source": dead_view,
            "health_events": dead_events,
            "ok": (
                dead_view.get("health_status") == "dead_letter"
                and (dead_view.get("retry_state") or {}).get("next_retry_at", "") == ""
                and dead_view.get("health_message") == "Retries are exhausted and this source requires intervention."
                and any(e["status"] == "dead_letter" for e in dead_events)
            ),
        })

        # 7. Persistence and API consistency.
        db_counts = {
            "jobs": db_one(str(db_path), "SELECT COUNT(*) AS c FROM data_plane_jobs")["c"],
            "runs": db_one(str(db_path), "SELECT COUNT(*) AS c FROM ingest_runs")["c"],
            "snapshots": db_one(str(db_path), "SELECT COUNT(*) AS c FROM raw_snapshots")["c"],
        }
        status = request(base_b, "GET", "/api/data-plane/status")
        proof["scenarios"].append({
            "name": "ui_api_state_consistency",
            "status": status,
            "db_counts": db_counts,
            "ok": status.get("schema_version") == proof["build"]["schema_version"] and int(sum(status.get("jobs", {}).values())) == db_counts["jobs"] and int(sum(status.get("runs", {}).values())) == db_counts["runs"],
        })

        proof["ok"] = all(item["ok"] for item in proof["scenarios"])
        if args.write_proof:
            Path(args.write_proof).write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(proof, indent=2, ensure_ascii=False))
        return 0 if proof["ok"] else 1
    finally:
        fixture_server.shutdown()
        stop_server(server_a)
        stop_server(server_b)


if __name__ == "__main__":
    raise SystemExit(main())
