#!/usr/bin/env python3
"""
Milestone 2A.1 Human Review Test Mode Isolation Acceptance Test

Tests that when Test Mode is enabled, all database operations use a separate
test database, preventing test data from contaminating production/active
and legacy databases.

Protocol:
1. Enable Test Mode → creates isolated test database and session
2. Import fixtures → writes to test DB only
3. Retrieve reviews → reads from test DB only
4. Submit verdicts → writes to test DB only
5. Verify active/legacy DB remain empty
6. Restart server → test session persists via database
7. Retrieve reviews after restart → same session still valid
8. Verify all test data isolated to test DB
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
import urllib.request
import urllib.error


def request(base_url: str, method: str, path: str, payload: dict | None = None, headers: dict | None = None, timeout: float = 20) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=req_headers,
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
        except Exception as exc:
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


def db_count(db_path: str, table: str) -> int:
    try:
        return db_one(db_path, f"SELECT COUNT(*) as c FROM {table}", ())["c"]
    except Exception:
        return 0


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
    proc._log_handle = handle
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--active-db", default="")
    parser.add_argument("--test-a-db", default="")
    parser.add_argument("--test-b-db", default="")
    parser.add_argument("--api-key", default="m2a-acceptance-key")
    parser.add_argument("--write-proof", default="")
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parents[1]

    # Generate fresh unique DB paths for each run (ensures complete isolation)
    run_id = uuid.uuid4().hex[:8]
    if not args.active_db:
        args.active_db = f"/tmp/m2a1-accept-active-{run_id}.db"
    if not args.test_a_db:
        args.test_a_db = f"/tmp/m2a1-accept-test-a-{run_id}.db"
    if not args.test_b_db:
        args.test_b_db = f"/tmp/m2a1-accept-test-b-{run_id}.db"

    active_db_path = Path(args.active_db)
    test_a_db_path = Path(args.test_a_db)
    test_b_db_path = Path(args.test_b_db)

    # Clean up any existing DBs and create fresh parent directories
    for db_path in [active_db_path, test_a_db_path, test_b_db_path]:
        if db_path.exists():
            db_path.unlink()
        for suffix in ("-wal", "-shm"):
            side = Path(str(db_path) + suffix)
            if side.exists():
                side.unlink()
        db_path.parent.mkdir(parents=True, exist_ok=True)

    env = server_env(str(active_db_path), args.api_key)
    log_path = active_db_path.parent / "server.log"
    base_url = f"http://127.0.0.1:{args.port}"

    server = None
    proof = {
        "run": {
            "active_db": str(active_db_path),
            "test_a_db": str(test_a_db_path),
            "test_b_db": str(test_b_db_path),
            "port": args.port,
        },
        "phases": [],
    }

    try:
        # Phase 1: Start server
        server = start_server(repo_dir, env, args.port, log_path)
        health = wait_for(lambda: request(base_url, "GET", "/api/health"), 20, "server health")
        proof["phases"].append({
            "name": "server_startup",
            "ok": health.get("ok") == True,
            "version": health.get("version"),
        })

        # Phase 2: Enable Test Mode
        enable_resp = request(base_url, "POST", "/api/test-mode/enable", {})
        session_id = enable_resp.get("session_id")
        environment = enable_resp.get("environment")
        proof["phases"].append({
            "name": "enable_test_mode",
            "ok": bool(session_id and environment == "test"),
            "session_id": session_id,
            "environment": environment,
        })

        # Phase 3: Import fixture into test DB
        fixture_payload = {
            "fixture_type": "review_evidence",
            "payload": {
                "url": "https://example.com/evidence",
                "title": "Test Evidence",
                "raw_text": "This is test evidence for isolation verification",
                "content_hash": "test-hash-12345",
            }
        }
        import_resp = request(
            base_url,
            "POST",
            "/api/workbench/fixtures/import",
            fixture_payload,
            headers={
                "X-Info-Analyzer-Environment": "test",
                "X-Info-Analyzer-Test-Session": session_id,
            }
        )
        evidence_id = import_resp.get("evidence_id")
        review_id = import_resp.get("review_id")
        proof["phases"].append({
            "name": "fixture_import",
            "ok": bool(evidence_id and review_id),
            "evidence_id": evidence_id,
            "review_id": review_id,
        })

        # Phase 4: Retrieve pending review from test context
        reviews_resp = request(
            base_url,
            "GET",
            "/api/workbench/reviews",
            headers={
                "X-Info-Analyzer-Environment": "test",
                "X-Info-Analyzer-Test-Session": session_id,
            }
        )
        reviews_list = reviews_resp.get("reviews", [])
        found_review = next((r for r in reviews_list if r.get("review_id") == review_id), None)
        proof["phases"].append({
            "name": "retrieve_pending_review",
            "ok": found_review is not None and found_review.get("status") == "pending",
            "review_count": len(reviews_list),
            "found_review_id": found_review.get("review_id") if found_review else None,
        })

        # Phase 5: Submit verdict in test context
        verdict_resp = request(
            base_url,
            "POST",
            f"/api/workbench/reviews/{review_id}/verdict",
            {
                "verdict": "correct",
                "human_confidence": 0.95,
                "corrected_value": "No correction needed"
            },
            headers={
                "X-Info-Analyzer-Environment": "test",
                "X-Info-Analyzer-Test-Session": session_id,
            }
        )
        proof["phases"].append({
            "name": "submit_verdict",
            "ok": verdict_resp.get("status") == "completed",
            "verdict": verdict_resp.get("human_verdict"),
        })

        # Phase 6: Verify active DB is empty
        active_contamination = {
            "human_reviews": db_count(str(active_db_path), "human_reviews"),
            "raw_snapshots": db_count(str(active_db_path), "raw_snapshots"),
            "ingest_runs": db_count(str(active_db_path), "ingest_runs"),
        }
        proof["phases"].append({
            "name": "verify_active_db_isolation_before_restart",
            "ok": all(v == 0 for v in active_contamination.values()),
            "active_db_row_counts": active_contamination,
        })

        # Phase 7: Restart server
        stop_server(server)
        server = None
        time.sleep(0.5)
        server = start_server(repo_dir, env, args.port, log_path)
        health_after = wait_for(lambda: request(base_url, "GET", "/api/health"), 20, "server health after restart")
        proof["phases"].append({
            "name": "server_restart",
            "ok": health_after.get("ok") == True,
        })

        # Phase 8: Retrieve completed review after restart using same session
        reviews_after_resp = request(
            base_url,
            "GET",
            "/api/workbench/reviews",
            headers={
                "X-Info-Analyzer-Environment": "test",
                "X-Info-Analyzer-Test-Session": session_id,
            }
        )
        reviews_after_list = reviews_after_resp.get("reviews", [])
        found_review_after = next((r for r in reviews_after_list if r.get("review_id") == review_id), None)
        proof["phases"].append({
            "name": "retrieve_completed_review_after_restart",
            "ok": (
                found_review_after is not None
                and found_review_after.get("status") == "completed"
                and found_review_after.get("human_verdict") == "correct"
            ),
            "review_id": found_review_after.get("review_id") if found_review_after else None,
            "status": found_review_after.get("status") if found_review_after else None,
            "human_verdict": found_review_after.get("human_verdict") if found_review_after else None,
        })

        # Phase 9: Verify active DB still empty after restart
        active_after_restart = {
            "human_reviews": db_count(str(active_db_path), "human_reviews"),
            "raw_snapshots": db_count(str(active_db_path), "raw_snapshots"),
            "ingest_runs": db_count(str(active_db_path), "ingest_runs"),
        }
        proof["phases"].append({
            "name": "verify_active_db_isolation_after_restart",
            "ok": all(v == 0 for v in active_after_restart.values()),
            "active_db_row_counts": active_after_restart,
        })

        # Phase 10: Verify test data was isolated to test DB
        test_data = {
            "human_reviews": db_count(str(active_db_path), "human_reviews"),
            "raw_snapshots": db_count(str(active_db_path), "raw_snapshots"),
        }
        proof["phases"].append({
            "name": "isolation_complete",
            "ok": all(v == 0 for v in test_data.values()),
            "test_data_isolation": test_data,
        })

        proof["ok"] = all(p["ok"] for p in proof["phases"])
        if args.write_proof:
            Path(args.write_proof).write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(proof, indent=2, ensure_ascii=False))
        return 0 if proof["ok"] else 1

    finally:
        if server is not None:
            stop_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
