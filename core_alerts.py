"""Core alert queue and response workflow."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core_database import connect
from core_delivery import record_alert_acknowledgment


OPEN_ALERT_STATES = {"queued", "presented", "acknowledged"}
SNOOZED_STATES = {"snoozed"}
TERMINAL_ALERT_STATES = {"dismissed", "resolved", "actioned"}
ALL_OPEN_OR_PENDING = OPEN_ALERT_STATES | SNOOZED_STATES
ALERT_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}
ALLOWED_RESPONSES = {"acknowledge", "analyze", "snooze", "dismiss", "convert_to_action"}
ALLOWED_DECIDED_BY = {"human", "rule", "ai", "joint"}
DECISION_TYPE_BY_RESPONSE = {
    "acknowledge": "approve",
    "analyze": "analyze",
    "snooze": "defer",
    "dismiss": "dismiss",
    "convert_to_action": "approve",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def parse_utc_timestamp(value: Any, field_name: str) -> str:
    raw = clean_text(value)
    if not raw:
        raise ValueError(f"{field_name} is required")
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def alert_row_to_dict(row) -> dict[str, Any]:
    return dict(row)


def _table_exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _eligible_signal_row(signal_row) -> bool:
    if signal_row["priority"] == "P0":
        return True
    if signal_row["priority"] == "P1" and float(signal_row["actionability_score"] or 0) >= 0.70:
        return True
    return False


def _latest_alert_for_signal(conn, signal_id: str):
    return conn.execute(
        """
        SELECT *
        FROM core_alerts
        WHERE signal_id=?
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """,
        (signal_id,),
    ).fetchone()


def _open_alert_for_signal(conn, signal_id: str):
    return conn.execute(
        """
        SELECT *
        FROM core_alerts
        WHERE signal_id=? AND state IN ('queued','presented','acknowledged','snoozed','failed')
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """,
        (signal_id,),
    ).fetchone()


def refresh_expired_snoozes(conn, now: str | None = None) -> int:
    now = now or now_utc_iso()
    cur = conn.execute(
        """
        UPDATE core_alerts
        SET state='queued',
            snoozed_until=NULL,
            updated_at=?
        WHERE state='snoozed' AND snoozed_until IS NOT NULL AND snoozed_until <= ?
        """,
        (now, now),
    )
    return cur.rowcount or 0


def sync_alert_queue(conn, now: str | None = None) -> dict[str, int]:
    now = now or now_utc_iso()
    reactivated = refresh_expired_snoozes(conn, now=now)
    created = 0
    updated = 0
    skipped = 0
    signals = conn.execute(
        """
        SELECT *
        FROM core_signals
        WHERE priority IN ('P0', 'P1')
          AND status NOT IN ('dismissed', 'resolved', 'expired')
        ORDER BY detected_at ASC, created_at ASC
        """
    ).fetchall()
    for signal in signals:
        if not _eligible_signal_row(signal):
            continue
        latest = _latest_alert_for_signal(conn, signal["signal_id"])
        if latest:
            if latest["state"] in ALL_OPEN_OR_PENDING:
                if signal["updated_at"] > latest["updated_at"]:
                    conn.execute(
                        "UPDATE core_alerts SET updated_at=?, attempt_count=attempt_count+1 WHERE alert_id=?",
                        (now, latest["alert_id"]),
                    )
                    updated += 1
                else:
                    skipped += 1
                continue
            if signal["updated_at"] <= latest["updated_at"]:
                skipped += 1
                continue
        conn.execute(
            """
            INSERT INTO core_alerts (
                alert_id, signal_id, priority, state, requires_acknowledgment,
                delivery_channel, scheduled_at, presented_at, acknowledged_at,
                snoozed_until, resolved_at, attempt_count, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, 'queued', 1, 'command_center', NULL, NULL, NULL, NULL, NULL, 0, NULL, ?, ?)
            """,
            (
                make_id("ALT"),
                signal["signal_id"],
                signal["priority"],
                now,
                now,
            ),
        )
        created += 1
    return {"created": created, "updated": updated, "skipped": skipped, "reactivated": reactivated}


def _alert_context_rows(conn, limit: int) -> list[dict[str, Any]]:
    sync_alert_queue(conn)
    rows = conn.execute(
        """
        SELECT
            a.*,
            s.signal_type,
            s.title,
            s.summary,
            s.priority AS signal_priority,
            s.confidence AS signal_confidence,
            s.actionability_score,
            s.rationale,
            s.recommended_action,
            s.owner_system_id,
            sys.name AS source_system_name
        FROM core_alerts AS a
        JOIN core_signals AS s ON s.signal_id = a.signal_id
        JOIN core_systems AS sys ON sys.system_id = s.owner_system_id
        WHERE a.state IN ('queued', 'presented', 'acknowledged')
        ORDER BY CASE a.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
                 COALESCE(a.presented_at, a.created_at) ASC,
                 a.created_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    alerts: list[dict[str, Any]] = []
    for row in rows:
        alert = dict(row)
        alerts.append(
            {
                "alert_id": alert["alert_id"],
                "signal_id": alert["signal_id"],
                "signal_type": alert["signal_type"],
                "source_system_id": alert["owner_system_id"],
                "source_system_name": alert["source_system_name"],
                "title": alert["title"],
                "summary": alert["summary"],
                "priority": alert["priority"],
                "confidence": alert["signal_confidence"],
                "actionability_score": alert["actionability_score"],
                "rationale": alert["rationale"],
                "recommended_action": alert["recommended_action"],
                "state": alert["state"],
                "delivery_channel": alert["delivery_channel"],
                "presented_at": alert["presented_at"],
                "acknowledged_at": alert["acknowledged_at"],
                "snoozed_until": alert["snoozed_until"],
                "resolved_at": alert["resolved_at"],
                "created_at": alert["created_at"],
                "updated_at": alert["updated_at"],
            }
        )
    return alerts


def list_alerts(database_path, limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(int(limit or 50), 100))
    with connect(database_path) as conn:
        sync = sync_alert_queue(conn)
        alerts = _alert_context_rows(conn, limit)
    return {
        "checked_at": now_utc_iso(),
        "count": len(alerts),
        "alerts": alerts,
        "sync": sync,
    }


def _load_alert_with_signal(conn, alert_id: str):
    row = conn.execute(
        """
        SELECT
            a.*,
            s.signal_type,
            s.title,
            s.summary,
            s.priority AS signal_priority,
            s.confidence AS signal_confidence,
            s.actionability_score,
            s.rationale,
            s.recommended_action,
            s.owner_system_id,
            sys.name AS source_system_name
        FROM core_alerts AS a
        JOIN core_signals AS s ON s.signal_id = a.signal_id
        JOIN core_systems AS sys ON sys.system_id = s.owner_system_id
        WHERE a.alert_id=?
        """,
        (alert_id,),
    ).fetchone()
    return dict(row) if row else None


def _decision_payload(alert: dict[str, Any], response: str, payload: dict[str, Any]) -> dict[str, Any]:
    decided_by = clean_text(payload.get("decided_by") or "human") or "human"
    if decided_by not in ALLOWED_DECIDED_BY:
        raise ValueError("decided_by must be human, rule, ai, or joint")
    note = clean_text(payload.get("note") or payload.get("rationale") or payload.get("result"))
    return {
        "decision_type": DECISION_TYPE_BY_RESPONSE[response],
        "selected_option": response,
        "rationale": note or alert.get("recommended_action") or alert.get("summary") or "",
        "decided_by": decided_by,
        "metadata_json": {
            "alert_id": alert["alert_id"],
            "signal_id": alert["signal_id"],
            "signal_type": alert["signal_type"],
            "source_system_id": alert["owner_system_id"],
            "response": response,
        },
    }


def _create_decision(conn, alert: dict[str, Any], response: str, payload: dict[str, Any]) -> dict[str, Any]:
    decision_id = make_id("DEC")
    decision = _decision_payload(alert, response, payload)
    conn.execute(
        """
        INSERT INTO core_decisions (
            decision_id, signal_id, goal_id, decision_type, selected_option,
            rationale, decided_by, supersedes_decision_id, decided_at, metadata_json, created_at
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            decision_id,
            alert["signal_id"],
            decision["decision_type"],
            decision["selected_option"],
            decision["rationale"],
            decision["decided_by"],
            now_utc_iso(),
            json.dumps(decision["metadata_json"], ensure_ascii=False, sort_keys=True),
            now_utc_iso(),
        ),
    )
    return {
        "decision_id": decision_id,
        "decision_type": decision["decision_type"],
        "selected_option": decision["selected_option"],
        "rationale": decision["rationale"],
        "decided_by": decision["decided_by"],
        "metadata_json": decision["metadata_json"],
    }


def respond_to_alert(database_path, alert_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = clean_text(payload.get("response") or payload.get("action") or payload.get("status")).lower()
    if response not in ALLOWED_RESPONSES:
        raise ValueError("response must be acknowledge, analyze, snooze, dismiss, or convert_to_action")
    with connect(database_path) as conn:
        alert_row = _load_alert_with_signal(conn, alert_id)
        if not alert_row:
            raise KeyError("alert not found")
        if alert_row["state"] in TERMINAL_ALERT_STATES:
            raise ValueError("alert is already terminal")
        if response == "snooze":
            snoozed_until = parse_utc_timestamp(payload.get("snooze_until") or payload.get("snoozed_until"), "snooze_until")
            if datetime.fromisoformat(snoozed_until.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                raise ValueError("snooze_until must be in the future")
        else:
            snoozed_until = None
        if response == "acknowledge":
            new_state = "acknowledged"
            timestamps = {"acknowledged_at": now_utc_iso()}
            relationship = "response"
        elif response == "analyze":
            new_state = "presented"
            timestamps = {"presented_at": alert_row["presented_at"] or now_utc_iso()}
            relationship = "response"
        elif response == "snooze":
            new_state = "snoozed"
            timestamps = {"snoozed_until": snoozed_until}
            relationship = "response"
        elif response == "dismiss":
            new_state = "dismissed"
            timestamps = {"resolved_at": now_utc_iso()}
            relationship = "resolution"
        else:
            new_state = "actioned"
            timestamps = {"resolved_at": now_utc_iso()}
            relationship = "response"
        decision = _create_decision(conn, alert_row, response, payload)
        conn.execute(
            "INSERT INTO core_alert_decisions (alert_id, decision_id, relationship) VALUES (?, ?, ?)",
            (alert_id, decision["decision_id"], relationship),
        )
        if response == "acknowledge" and _table_exists(conn, "core_alert_acknowledgments"):
            auth_context = clean_text(payload.get("_auth_context") or payload.get("auth_context"))
            acknowledged_by = clean_text(payload.get("_acknowledged_by") or payload.get("acknowledged_by") or payload.get("decided_by") or "authenticated_service")
            if auth_context:
                record_alert_acknowledgment(
                    conn,
                    alert_id=alert_id,
                    acknowledged_by=acknowledged_by,
                    auth_context=auth_context,
                    response=response,
                    decision_id=decision["decision_id"],
                    same_case_id=clean_text(payload.get("same_case_id")) or None,
                    now=now_utc_iso(),
                )
        action = None
        if response == "convert_to_action":
            action_id = make_id("ACT")
            conn.execute(
                """
                INSERT INTO core_actions (
                    action_id, decision_id, owner_system_id, goal_id, action_type, title,
                    details, status, execution_mode, assigned_to, due_at, started_at,
                    completed_at, external_ref, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, 'proposed', 'manual', 'user', NULL, NULL,
                          NULL, NULL, ?, ?, ?)
                """,
                (
                    action_id,
                    decision["decision_id"],
                    alert_row["owner_system_id"],
                    "alert_response",
                    alert_row["recommended_action"] or alert_row["title"],
                    alert_row["summary"] or alert_row["rationale"] or "",
                    json.dumps(
                        {
                            "alert_id": alert_id,
                            "signal_id": alert_row["signal_id"],
                            "source_system_id": alert_row["owner_system_id"],
                            "response": response,
                            "decision_id": decision["decision_id"],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_utc_iso(),
                    now_utc_iso(),
                ),
            )
            conn.execute(
                "UPDATE core_decisions SET metadata_json=? WHERE decision_id=?",
                (
                    json.dumps(
                        {
                            **decision["metadata_json"],
                            "action_id": action_id,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    decision["decision_id"],
                ),
            )
            action = dict(
                conn.execute("SELECT * FROM core_actions WHERE action_id=?", (action_id,)).fetchone()
            )
        conn.execute(
            """
            UPDATE core_alerts
            SET state=?, acknowledged_at=COALESCE(acknowledged_at, ?),
                snoozed_until=COALESCE(?, snoozed_until),
                resolved_at=COALESCE(?, resolved_at),
                updated_at=?
            WHERE alert_id=?
            """,
            (
                new_state,
                timestamps.get("acknowledged_at"),
                timestamps.get("snoozed_until"),
                timestamps.get("resolved_at"),
                now_utc_iso(),
                alert_id,
            ),
        )
        if response == "snooze":
            conn.execute(
                "UPDATE core_alerts SET snoozed_until=?, acknowledged_at=NULL, resolved_at=NULL WHERE alert_id=?",
                (snoozed_until, alert_id),
            )
        if response == "dismiss":
            conn.execute(
                "UPDATE core_alerts SET acknowledged_at=NULL, snoozed_until=NULL, resolved_at=? WHERE alert_id=?",
                (timestamps["resolved_at"], alert_id),
            )
        if response == "convert_to_action":
            conn.execute(
                "UPDATE core_alerts SET acknowledged_at=NULL, snoozed_until=NULL, resolved_at=?, state='actioned' WHERE alert_id=?",
                (timestamps["resolved_at"], alert_id),
            )
        conn.commit()
        updated_alert = _load_alert_with_signal(conn, alert_id)
        return {
            "alert": updated_alert,
            "decision": decision,
            "action": action,
        }
