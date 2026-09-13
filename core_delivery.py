"""Notification delivery, presentation, and acknowledgment records."""

from __future__ import annotations

from typing import Any

from core_operations import claim_operation, clean_text, complete_attempt, make_id, now_utc_iso, stable_json


def _alert(conn, alert_id: str):
    return conn.execute(
        """
        SELECT a.*, s.signal_id, s.owner_system_id
        FROM core_alerts AS a
        JOIN core_signals AS s ON s.signal_id = a.signal_id
        WHERE a.alert_id=?
        """,
        (clean_text(alert_id),),
    ).fetchone()


def request_notification(
    conn,
    *,
    alert_id: str,
    channel: str = "command_center",
    purpose: str = "alert_delivery",
    requested_by: str = "system",
    worker_id: str = "notification-requester",
    now: str | None = None,
) -> dict[str, Any]:
    now = now or now_utc_iso()
    alert = _alert(conn, alert_id)
    if not alert:
        raise KeyError("alert not found")
    op_key = f"{clean_text(alert_id)}:{clean_text(channel)}:{clean_text(purpose)}"
    claimed = claim_operation(
        conn,
        operation_type="request_notification",
        operation_key=op_key,
        request_payload={"alert_id": alert_id, "channel": channel, "purpose": purpose},
        worker_id=worker_id,
        source_system_id=alert["owner_system_id"],
        subject_namespace="core",
        subject_type="alert",
        subject_id=alert_id,
        immutable_payload=True,
        now=now,
    )
    if claimed["idempotent"]:
        result = claimed["operation"].get("result") or {}
        request_id = clean_text(result.get("notification_request_id"))
        row = conn.execute("SELECT * FROM core_notification_requests WHERE notification_request_id=?", (request_id,)).fetchone()
        return {"created": False, "request": dict(row) if row else None, "operation": claimed["operation"], "attempt": None}
    request_id = make_id("NFR")
    conn.execute(
        """
        INSERT INTO core_notification_requests (
            notification_request_id, operation_id, alert_id, channel, purpose,
            status, requested_at, requested_by, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, 'requested', ?, ?, '{}', ?)
        """,
        (request_id, claimed["operation"]["operation_id"], alert_id, channel, purpose, now, requested_by, now),
    )
    completed_operation = complete_attempt(
        conn,
        operation_id=claimed["operation"]["operation_id"],
        attempt_id=claimed["attempt"]["attempt_id"],
        worker_id=worker_id,
        status="succeeded",
        result={"notification_request_id": request_id},
        result_namespace="core",
        result_type="notification_request",
        result_id=request_id,
        now=now,
    )
    row = conn.execute("SELECT * FROM core_notification_requests WHERE notification_request_id=?", (request_id,)).fetchone()
    return {"created": True, "request": dict(row), "operation": completed_operation, "attempt": claimed["attempt"]}


def record_delivery_result(
    conn,
    *,
    notification_request_id: str,
    provider_status: str,
    worker_id: str = "notification-sender",
    external_delivery_ref: str | None = None,
    trusted_evidence_type: str | None = None,
    trusted_evidence_ref: str | None = None,
    provider_response: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or now_utc_iso()
    request = conn.execute("SELECT * FROM core_notification_requests WHERE notification_request_id=?", (notification_request_id,)).fetchone()
    if not request:
        raise KeyError("notification request not found")
    status = clean_text(provider_status)
    if status not in {"not_attempted", "submitted", "provider_accepted", "delivered", "failed", "unknown"}:
        raise ValueError("invalid provider_status")
    if status == "delivered" and not (trusted_evidence_type and trusted_evidence_ref):
        raise ValueError("trusted delivery evidence is required for delivered status")
    op_key = f"{notification_request_id}:{request['channel']}"
    claimed = claim_operation(
        conn,
        operation_type="send_notification",
        operation_key=op_key,
        request_payload={"notification_request_id": notification_request_id, "channel": request["channel"]},
        worker_id=worker_id,
        subject_namespace="core",
        subject_type="notification_request",
        subject_id=notification_request_id,
        immutable_payload=True,
        now=now,
    )
    if claimed["idempotent"]:
        result_id = clean_text((claimed["operation"].get("result") or {}).get("delivery_result_id"))
        row = conn.execute("SELECT * FROM core_notification_delivery_results WHERE delivery_result_id=?", (result_id,)).fetchone()
        return {"created": False, "delivery": dict(row) if row else None, "operation": claimed["operation"], "attempt": None}
    result_id = make_id("NDA")
    provider_accepted_at = now if status in {"provider_accepted", "delivered"} else None
    delivered_at = now if status == "delivered" else None
    failed_at = now if status == "failed" else None
    evidence_recorded_at = now if status == "delivered" else None
    conn.execute(
        """
        INSERT INTO core_notification_delivery_results (
            delivery_result_id, notification_request_id, alert_id, attempt_id,
            channel, provider_status, attempted_at, provider_accepted_at,
            delivered_at, failed_at, external_delivery_ref, trusted_evidence_type,
            trusted_evidence_ref, evidence_recorded_at, provider_response_json,
            error_json, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
        """,
        (
            result_id,
            notification_request_id,
            request["alert_id"],
            claimed["attempt"]["attempt_id"],
            request["channel"],
            status,
            now,
            provider_accepted_at,
            delivered_at,
            failed_at,
            clean_text(external_delivery_ref) or None,
            clean_text(trusted_evidence_type) or None,
            clean_text(trusted_evidence_ref) or None,
            evidence_recorded_at,
            stable_json(provider_response or {}),
            stable_json(error or {}),
            now,
            now,
        ),
    )
    attempt_status = "unknown" if status == "unknown" else ("failed" if status == "failed" else "succeeded")
    completed_operation = complete_attempt(
        conn,
        operation_id=claimed["operation"]["operation_id"],
        attempt_id=claimed["attempt"]["attempt_id"],
        worker_id=worker_id,
        status=attempt_status,
        result={"delivery_result_id": result_id, "provider_status": status},
        error=error or {},
        result_namespace="core",
        result_type="notification_delivery_result",
        result_id=result_id,
        now=now,
    )
    row = conn.execute("SELECT * FROM core_notification_delivery_results WHERE delivery_result_id=?", (result_id,)).fetchone()
    return {"created": True, "delivery": dict(row), "operation": completed_operation, "attempt": claimed["attempt"]}


def record_alert_presentation(conn, *, alert_id: str, presented_by: str, presentation_surface: str, session_ref: str | None = None, delivery_result_id: str | None = None, now: str | None = None) -> dict[str, Any]:
    now = now or now_utc_iso()
    if not _alert(conn, alert_id):
        raise KeyError("alert not found")
    presentation_id = make_id("PRS")
    conn.execute(
        """
        INSERT INTO core_alert_presentations (
            presentation_id, alert_id, delivery_result_id, presented_at,
            presented_by, presentation_surface, session_ref, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?)
        """,
        (presentation_id, alert_id, delivery_result_id, now, clean_text(presented_by), clean_text(presentation_surface), clean_text(session_ref) or None, now),
    )
    row = conn.execute("SELECT * FROM core_alert_presentations WHERE presentation_id=?", (presentation_id,)).fetchone()
    return dict(row)


def _decision_for_alert(conn, alert_id: str, decision_id: str):
    return conn.execute(
        """
        SELECT d.decision_id, d.signal_id
        FROM core_decisions AS d
        JOIN core_alerts AS a ON a.signal_id = d.signal_id
        WHERE a.alert_id=? AND d.decision_id=?
        """,
        (alert_id, decision_id),
    ).fetchone()


def record_alert_acknowledgment(
    conn,
    *,
    alert_id: str,
    acknowledged_by: str,
    auth_context: str,
    response: str | None = None,
    decision_id: str | None = None,
    same_case_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or now_utc_iso()
    if not _alert(conn, alert_id):
        raise KeyError("alert not found")
    if not clean_text(auth_context):
        raise ValueError("trusted auth_context is required")
    if decision_id and not _decision_for_alert(conn, alert_id, decision_id):
        raise ValueError("decision does not belong to alert case")
    acknowledgment_id = make_id("ACK")
    conn.execute(
        """
        INSERT INTO core_alert_acknowledgments (
            acknowledgment_id, alert_id, decision_id, acknowledged_at,
            acknowledged_by, auth_context, trust_level, response, same_case_id,
            metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'authenticated_service', ?, ?, '{}', ?)
        """,
        (
            acknowledgment_id,
            alert_id,
            clean_text(decision_id) or None,
            now,
            clean_text(acknowledged_by),
            clean_text(auth_context),
            clean_text(response) or None,
            clean_text(same_case_id) or None,
            now,
        ),
    )
    row = conn.execute("SELECT * FROM core_alert_acknowledgments WHERE acknowledgment_id=?", (acknowledgment_id,)).fetchone()
    return dict(row)
