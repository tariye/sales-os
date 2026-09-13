"""Durable operation and attempt ledger for retryable core work."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def row_to_operation(row) -> dict[str, Any]:
    data = dict(row)
    data["result"] = load_json(data.pop("result_json", "{}"), {})
    data["error"] = load_json(data.pop("error_json", "{}"), {})
    return data


def row_to_attempt(row) -> dict[str, Any]:
    data = dict(row)
    data["error"] = load_json(data.pop("error_json", "{}"), {})
    data["metadata"] = load_json(data.pop("metadata_json", "{}"), {})
    return data


def _table_exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def ensure_gate3_schema(conn) -> None:
    if not _table_exists(conn, "core_operations"):
        raise RuntimeError("Gate 3A schema is not initialized")


def claim_operation(
    conn,
    *,
    operation_type: str,
    operation_key: str,
    request_payload: Any,
    worker_id: str,
    source_system_id: str | None = None,
    subject_namespace: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    immutable_payload: bool = False,
    lease_seconds: int = 300,
    now: str | None = None,
) -> dict[str, Any]:
    """Create or claim an operation and persist a started attempt.

    Exact retries of succeeded operations return the existing operation. A running
    operation with an unexpired lease is protected from non-owner completion.
    """

    ensure_gate3_schema(conn)
    now = now or now_utc_iso()
    digest = request_hash(request_payload)
    op_type = clean_text(operation_type)
    op_key = clean_text(operation_key)
    worker = clean_text(worker_id) or "worker"
    existing = conn.execute(
        "SELECT * FROM core_operations WHERE operation_type=? AND operation_key=?",
        (op_type, op_key),
    ).fetchone()
    if existing:
        operation = dict(existing)
        if immutable_payload and operation["request_hash"] and operation["request_hash"] != digest:
            raise ValueError("operation request hash conflict")
        if operation["status"] == "succeeded":
            return {"operation": row_to_operation(existing), "attempt": None, "idempotent": True}
        active = conn.execute(
            """
            SELECT *
            FROM core_operation_attempts
            WHERE operation_id=? AND status='started'
            ORDER BY attempt_number DESC
            LIMIT 1
            """,
            (operation["operation_id"],),
        ).fetchone()
        if active and parse_utc(active["lease_expires_at"]) > parse_utc(now):
            if active["worker_id"] != worker:
                raise RuntimeError("operation is owned by another live worker")
        if active and parse_utc(active["lease_expires_at"]) <= parse_utc(now):
            conn.execute(
                """
                UPDATE core_operation_attempts
                SET status='abandoned', reclaimed_at=?, finished_at=?, error_json=?
                WHERE attempt_id=?
                """,
                (
                    now,
                    now,
                    stable_json({"reason": "lease_expired", "reclaimed_by": worker}),
                    active["attempt_id"],
                ),
            )
        operation_id = operation["operation_id"]
    else:
        operation_id = make_id("OPR")
        conn.execute(
            """
            INSERT INTO core_operations (
                operation_id, operation_type, operation_key, source_system_id, status,
                subject_namespace, subject_type, subject_id, request_hash,
                result_json, error_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, '{}', '{}', ?, ?)
            """,
            (
                operation_id,
                op_type,
                op_key,
                source_system_id,
                subject_namespace,
                subject_type,
                subject_id,
                digest,
                now,
                now,
            ),
        )
    next_attempt = (conn.execute(
        "SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM core_operation_attempts WHERE operation_id=?",
        (operation_id,),
    ).fetchone()[0])
    attempt_id = make_id("OPA")
    lease_expires = (parse_utc(now) + timedelta(seconds=max(1, lease_seconds))).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    conn.execute(
        """
        INSERT INTO core_operation_attempts (
            attempt_id, operation_id, attempt_number, status, worker_id,
            started_at, lease_started_at, lease_expires_at, heartbeat_at,
            error_json, metadata_json, created_at
        ) VALUES (?, ?, ?, 'started', ?, ?, ?, ?, ?, '{}', '{}', ?)
        """,
        (attempt_id, operation_id, next_attempt, worker, now, now, lease_expires, now, now),
    )
    conn.execute(
        """
        UPDATE core_operations
        SET status='running', updated_at=?, request_hash=COALESCE(request_hash, ?)
        WHERE operation_id=?
        """,
        (now, digest, operation_id),
    )
    operation_row = conn.execute("SELECT * FROM core_operations WHERE operation_id=?", (operation_id,)).fetchone()
    attempt_row = conn.execute("SELECT * FROM core_operation_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
    return {"operation": row_to_operation(operation_row), "attempt": row_to_attempt(attempt_row), "idempotent": False}


def complete_attempt(
    conn,
    *,
    operation_id: str,
    attempt_id: str,
    worker_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    result_namespace: str | None = None,
    result_type: str | None = None,
    result_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or now_utc_iso()
    attempt = conn.execute(
        "SELECT * FROM core_operation_attempts WHERE attempt_id=? AND operation_id=?",
        (attempt_id, operation_id),
    ).fetchone()
    if not attempt:
        raise KeyError("operation attempt not found")
    if attempt["worker_id"] != clean_text(worker_id):
        raise RuntimeError("operation attempt owned by another worker")
    if attempt["status"] != "started":
        raise RuntimeError("operation attempt is not active")
    if parse_utc(attempt["lease_expires_at"]) <= parse_utc(now):
        raise RuntimeError("operation attempt lease expired")
    if status not in {"succeeded", "failed", "unknown"}:
        raise ValueError("attempt status must be succeeded, failed, or unknown")
    conn.execute(
        """
        UPDATE core_operation_attempts
        SET status=?, finished_at=?, error_json=?, metadata_json=metadata_json
        WHERE attempt_id=?
        """,
        (status, now, stable_json(error or {}), attempt_id),
    )
    op_status = "succeeded" if status == "succeeded" else ("pending_reconciliation" if status == "unknown" else "failed")
    conn.execute(
        """
        UPDATE core_operations
        SET status=?, result_namespace=COALESCE(?, result_namespace),
            result_type=COALESCE(?, result_type),
            result_id=COALESCE(?, result_id),
            result_json=?, error_json=?, updated_at=?, completed_at=?
        WHERE operation_id=?
        """,
        (
            op_status,
            result_namespace,
            result_type,
            result_id,
            stable_json(result or {}),
            stable_json(error or {}),
            now,
            now if op_status in {"succeeded", "failed"} else None,
            operation_id,
        ),
    )
    op = conn.execute("SELECT * FROM core_operations WHERE operation_id=?", (operation_id,)).fetchone()
    return row_to_operation(op)
