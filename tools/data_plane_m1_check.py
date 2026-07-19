#!/usr/bin/env python3
"""Exercise Data Plane Milestone 1 from a clean runtime.

This is not a UI evaluator. It is a build-preservation proof that the
scheduled data-plane backbone exists and produces durable objects that a
black-box evaluator can reconcile later.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request


def request(base_url: str, method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def wait_for(predicate, timeout: float, label: str):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {label}; last={last!r}")


def db_rows(db_path: str, sql: str, args=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def count(db_path: str, table: str, where: str = "1=1", args=()) -> int:
    rows = db_rows(db_path, f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", args)
    return int(rows[0]["c"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8031)
    parser.add_argument("--db", default="/tmp/info-analyzer-m1-proof/eval.db")
    parser.add_argument("--api-key", default="eval-local-key")
    parser.add_argument("--write-proof", default="")
    args = parser.parse_args()

    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{args.port}"
    env = os.environ.copy()
    env["INFO_ANALYZER_DB_PATH"] = str(db_path)
    env["INFO_ANALYZER_API_KEY"] = args.api_key
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    checks = []
    try:
        wait_for(lambda: request(base_url, "GET", "/api/health"), 15, "server health")
        health = request(base_url, "GET", "/api/health")
        checks.append({"name": "health", "ok": health.get("ok") is True, "evidence": health.get("version")})
        schema_version = db_rows(str(db_path), "PRAGMA user_version")[0]["user_version"]
        checks.append({"name": "schema_version", "ok": schema_version == 1, "evidence": schema_version})

        nonce = str(int(time.time()))
        source = request(base_url, "POST", "/api/ingest/sources", {
            "name": f"M1 Fixture Source {nonce}",
            "source_type": "fixture",
            "domain": "Business",
            "entity": "M1 Sales Signal",
            "manual_text": f"M1 fixture payload {nonce}: setup objections are increasing. Track objection count and conversion rate.",
            "poll_interval_minutes": 0.05,
            "stale_after_seconds": 2,
        })["source"]
        source_id = source["id"]
        checks.append({"name": "source_registered_never_run", "ok": source["last_health_status"] == "never_run", "evidence": source_id})

        def has_background_run():
            return count(str(db_path), "ingest_runs", "source_id=? AND status='succeeded'", (source_id,)) >= 1
        wait_for(has_background_run, 12, "scheduled background ingest run")
        jobs = db_rows(str(db_path), "SELECT * FROM data_plane_jobs WHERE source_id=? ORDER BY created_at", (source_id,))
        claims = db_rows(str(db_path), "SELECT * FROM worker_claims WHERE source_id=? ORDER BY created_at", (source_id,))
        runs = db_rows(str(db_path), "SELECT * FROM ingest_runs WHERE source_id=? ORDER BY created_at", (source_id,))
        snaps = db_rows(str(db_path), "SELECT id, run_id, source_id, content_hash, connector_version FROM raw_snapshots WHERE source_id=? ORDER BY created_at", (source_id,))
        health_events = db_rows(str(db_path), "SELECT * FROM source_health_events WHERE source_id=? ORDER BY created_at", (source_id,))
        checks.append({"name": "background_job", "ok": bool(jobs and jobs[0]["trigger_type"] == "scheduled"), "evidence": jobs[0] if jobs else None})
        checks.append({"name": "worker_claim", "ok": bool(claims and claims[0]["worker_id"]), "evidence": claims[0] if claims else None})
        checks.append({"name": "ingest_run", "ok": bool(runs and runs[0]["status"] == "succeeded"), "evidence": runs[0] if runs else None})
        checks.append({"name": "raw_snapshot", "ok": bool(snaps and snaps[0]["connector_version"]), "evidence": snaps[0] if snaps else None})
        checks.append({"name": "source_health", "ok": any(e["status"] == "healthy" for e in health_events), "evidence": health_events[-2:]})

        before_snapshots = count(str(db_path), "raw_snapshots", "source_id=?", (source_id,))
        repeat = request(base_url, "POST", "/api/ingest/run", {"source_id": source_id})
        after_snapshots = count(str(db_path), "raw_snapshots", "source_id=?", (source_id,))
        checks.append({"name": "dedupe_same_payload", "ok": after_snapshots == before_snapshots and repeat.get("skipped", 0) >= 1, "evidence": repeat})

        changed = request(base_url, "POST", "/api/ingest/sources", {
            "name": f"M1 Changed Fixture {nonce}",
            "source_type": "fixture",
            "domain": "Business",
            "entity": "M1 Sales Signal",
            "manual_text": f"M1 changed payload {nonce}: objections shifted from setup to delivery timing. Track delivery questions and days-to-close.",
            "poll_interval_minutes": 5,
            "stale_after_seconds": 2,
        })["source"]
        wait_for(lambda: count(str(db_path), "raw_snapshots", "source_id=?", (changed["id"],)) >= 1, 12, "changed payload snapshot")
        checks.append({"name": "changed_payload_new_snapshot", "ok": count(str(db_path), "raw_snapshots", "source_id=?", (changed["id"],)) == 1, "evidence": changed["id"]})

        failed = request(base_url, "POST", "/api/ingest/sources", {
            "name": f"M1 Broken URL {nonce}",
            "source_type": "url",
            "url": "http://127.0.0.1:9/m1-broken",
            "domain": "Business",
            "entity": "Broken Source",
            "poll_interval_minutes": 5,
            "max_attempts": 3,
        })["source"]
        wait_for(lambda: count(str(db_path), "data_plane_jobs", "source_id=? AND status='dead_letter'", (failed["id"],)) >= 1, 15, "dead letter")
        failed_events = db_rows(str(db_path), "SELECT status, failure_count, message FROM source_health_events WHERE source_id=? ORDER BY created_at", (failed["id"],))
        checks.append({"name": "retry_and_dead_letter", "ok": any(e["status"] == "failed" for e in failed_events) and any(e["status"] == "dead_letter" for e in failed_events), "evidence": failed_events})

        # Force a stale check by aging the successful source in the clean proof DB.
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE ingest_sources SET last_success_at='2000-01-01T00:00:00+00:00', last_health_status='healthy', next_run_at='2999-01-01T00:00:00+00:00' WHERE id=?", (source_id,))
        conn.commit()
        conn.close()
        request(base_url, "POST", "/api/data-plane/scheduler/tick", {})
        stale = db_rows(str(db_path), "SELECT last_health_status FROM ingest_sources WHERE id=?", (source_id,))[0]["last_health_status"]
        checks.append({"name": "stale_state", "ok": stale == "stale", "evidence": stale})

        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc = subprocess.Popen(
            [sys.executable, "server.py", "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for(lambda: request(base_url, "GET", "/api/health"), 15, "restart health")
        persisted = {
            "jobs": count(str(db_path), "data_plane_jobs"),
            "claims": count(str(db_path), "worker_claims"),
            "runs": count(str(db_path), "ingest_runs"),
            "snapshots": count(str(db_path), "raw_snapshots"),
            "health_events": count(str(db_path), "source_health_events"),
        }
        checks.append({"name": "restart_persistence", "ok": all(v > 0 for v in persisted.values()), "evidence": persisted})

        passed = sum(1 for c in checks if c["ok"])
        result = {
            "status": "pass" if passed == len(checks) else "fail",
            "summary": {"passed": passed, "failed": len(checks) - passed, "total": len(checks)},
            "base_url": base_url,
            "db_path": str(db_path),
            "source_id": source_id,
            "checks": checks,
        }
        print(json.dumps(result, indent=2))
        if args.write_proof:
            proof = Path(args.write_proof)
            proof.parent.mkdir(parents=True, exist_ok=True)
            proof.write_text(json.dumps(result, indent=2) + "\n")
        return 0 if result["status"] == "pass" else 1
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
