"""Read-only shared access layer for normalized and legacy records."""

from __future__ import annotations

import json
from typing import Any

from core_database import connect


DEFAULT_LIMIT = 25
MAX_LIMIT = 100
CORE_COVERAGE = [
    "core_systems",
    "core_events",
    "core_signals",
    "core_signal_events",
    "core_alerts",
    "core_decisions",
    "core_actions",
    "core_outcomes",
    "core_lessons",
    "innbank_allocation_plans",
    "innbank_allocation_items",
    "innbank_routing_runs",
    "innbank_routing_items",
]
LEGACY_COVERAGE = ["entries", "actions"]
GATE3_COVERAGE = [
    "core_source_observations",
    "core_ingestion_results",
    "core_operations",
    "core_operation_attempts",
    "core_notification_requests",
    "core_notification_delivery_results",
    "core_alert_presentations",
    "core_alert_acknowledgments",
]


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def parse_limit(value: Any) -> int:
    try:
        limit = int(value or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def parse_cursor(value: Any) -> int:
    try:
        cursor = int(value or 0)
    except (TypeError, ValueError):
        cursor = 0
    return max(0, cursor)


def coverage(tables: list[str], *, systems: list[str] | None = None, limitations: list[str] | None = None) -> dict[str, Any]:
    return {
        "tables": tables,
        "systems": systems or [],
        "limitations": limitations or [],
    }


def table_counts(conn, tables: list[str]) -> dict[str, int | str]:
    existing = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    counts: dict[str, int | str] = {}
    for table in tables:
        if table not in existing:
            counts[table] = "not_implemented"
        else:
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return counts


def table_exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def get_system_status(database_path) -> dict[str, Any]:
    with connect(database_path) as conn:
        fk_enforced = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        existing_tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        systems = [dict(row) for row in conn.execute("SELECT * FROM core_systems ORDER BY system_id").fetchall()]
        for system in systems:
            system["metadata"] = load_json(system.pop("metadata_json", "{}"), {})
            system_id = system["system_id"]
            event_counts = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT processing_status, COUNT(*) AS count, MAX(created_at) AS latest_created_at
                    FROM core_events
                    WHERE source_system_id=?
                    GROUP BY processing_status
                    ORDER BY processing_status
                    """,
                    (system_id,),
                ).fetchall()
            ]
            signal_counts = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT status, priority, COUNT(*) AS count, MAX(created_at) AS latest_created_at
                    FROM core_signals
                    WHERE owner_system_id=?
                    GROUP BY status, priority
                    ORDER BY priority, status
                    """,
                    (system_id,),
                ).fetchall()
            ]
            observation_counts = []
            latest_observation = None
            if "core_source_observations" in existing_tables:
                observation_counts = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT observation_status, COUNT(*) AS count, MAX(last_seen_at) AS latest_seen_at
                        FROM core_source_observations
                        WHERE source_system_id=?
                        GROUP BY observation_status
                        ORDER BY observation_status
                        """,
                        (system_id,),
                    ).fetchall()
                ]
                latest_observation = max((row.get("latest_seen_at") or "" for row in observation_counts), default=None)
            notification_counts = []
            if "core_notification_requests" in existing_tables:
                notification_counts = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT nr.status, COUNT(*) AS count, MAX(nr.requested_at) AS latest_requested_at
                        FROM core_notification_requests AS nr
                        JOIN core_alerts AS a ON a.alert_id = nr.alert_id
                        JOIN core_signals AS s ON s.signal_id = a.signal_id
                        WHERE s.owner_system_id=?
                        GROUP BY nr.status
                        ORDER BY nr.status
                        """,
                        (system_id,),
                    ).fetchall()
                ]
            system["events"] = event_counts or [{"state": "empty", "count": 0}]
            system["signals"] = signal_counts or [{"state": "empty", "count": 0}]
            system["source_observations"] = {
                "status": (
                    "not_implemented"
                    if "core_source_observations" not in existing_tables
                    else "records_present"
                    if observation_counts
                    else "implemented_empty"
                ),
                "counts": observation_counts,
                "latest_seen_at": latest_observation,
            }
            system["source_freshness"] = {
                "status": "unknown" if not observation_counts and not event_counts else "recorded",
                "as_of": latest_observation or max((row.get("latest_created_at") or "" for row in event_counts), default=None),
                "reason": (
                    "Source observation ledger is implemented but empty for this system."
                    if "core_source_observations" in existing_tables and not observation_counts
                    else "Source observation ledger is not implemented."
                    if "core_source_observations" not in existing_tables
                    else "Based on latest recorded source observation."
                ),
            }
            system["workers"] = {
                "status": "sender_or_poller_not_configured",
                "reason": "Durable operation tables do not prove that a sender, poller, or worker is currently running.",
            }
            system["delivery"] = {
                "status": (
                    "records_present"
                    if notification_counts
                    else "implemented_empty"
                    if "core_notification_requests" in existing_tables
                    else "not_implemented"
                ),
                "delivery_status": "delivery_unknown",
                "counts": notification_counts,
                "reason": "Delivery requires explicit notification request/result evidence; queued alerts alone are not delivered.",
            }
        return {
            "status": "ok",
            "foreign_keys_enforced": bool(fk_enforced),
            "systems": systems,
            "counts": table_counts(conn, CORE_COVERAGE + GATE3_COVERAGE + LEGACY_COVERAGE + ["audit_log", "schema_migrations"]),
            "coverage": coverage(
                CORE_COVERAGE + GATE3_COVERAGE + LEGACY_COVERAGE + ["audit_log", "schema_migrations"],
                systems=[row["system_id"] for row in systems],
                limitations=[
                    "Source freshness uses source observations when present, otherwise recorded events where available.",
                    "Sender/poller configuration is reported separately and is not inferred from table existence.",
                    "Notification delivery remains unknown until request/result evidence exists.",
                    "Legacy records are counted but not promoted by this read layer.",
                ],
            ),
        }


def _normalized_cases(conn, *, system_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if system_id:
        where = "WHERE p.source_system_id = ?"
        params.append(system_id)
    rows = conn.execute(
        f"""
        SELECT
            p.plan_id, p.source_system_id, p.signal_id, p.source_event_id,
            p.status, p.latest_response, p.created_at, p.updated_at,
            s.signal_type, s.priority, s.status AS signal_status,
            a.alert_id, a.state AS alert_state
        FROM innbank_allocation_plans AS p
        JOIN core_signals AS s ON s.signal_id = p.signal_id
        LEFT JOIN core_alerts AS a ON a.signal_id = s.signal_id
        {where}
        ORDER BY p.created_at DESC, p.plan_id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    cases = []
    for row in rows:
        item = dict(row)
        cases.append(
            {
                "case_id": f"core:innbank_allocation_plan:{item['plan_id']}",
                "kind": "normalized",
                "system_id": item["source_system_id"],
                "case_type": "innbank_payday_allocation",
                "state": item["status"],
                "primary_id": item["plan_id"],
                "event_id": item["source_event_id"],
                "signal_id": item["signal_id"],
                "alert_id": item["alert_id"],
                "summary": {
                    "signal_type": item["signal_type"],
                    "signal_priority": item["priority"],
                    "signal_status": item["signal_status"],
                    "alert_state": item["alert_state"] or "not_recorded",
                    "latest_response": item["latest_response"],
                },
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
        )
    return cases


def _legacy_entry_candidates(conn, *, limit: int, offset: int, domain: str) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if domain:
        where = "WHERE domain = ?"
        params.append(domain)
    rows = conn.execute(
        f"""
        SELECT id, domain, status, signal_role, action_status, source_type, created_at, updated_at
        FROM entries
        {where}
        ORDER BY created_at DESC, id ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    return [
        {
            "case_id": f"legacy:entries:{row['id']}",
            "kind": "legacy_candidate",
            "legacy_table": "entries",
            "legacy_pk": row["id"],
            "domain": row["domain"],
            "state": row["status"],
            "role": row["signal_role"] or "unknown",
            "action_status": row["action_status"],
            "source_type": row["source_type"],
            "provenance": {"table": "entries", "primary_key": row["id"]},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _legacy_action_candidates(conn, *, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, entry_id, status, priority, created_at, updated_at
        FROM actions
        ORDER BY created_at DESC, id ASC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [
        {
            "case_id": f"legacy:actions:{row['id']}",
            "kind": "legacy_candidate",
            "legacy_table": "actions",
            "legacy_pk": row["id"],
            "entry_id": row["entry_id"],
            "state": row["status"],
            "priority": row["priority"],
            "provenance": {"table": "actions", "primary_key": row["id"], "entry_id": row["entry_id"]},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def list_cases(database_path, params: dict[str, list[str]]) -> dict[str, Any]:
    limit = parse_limit((params.get("limit") or [""])[0])
    cursor = parse_cursor((params.get("cursor") or ["0"])[0])
    system_id = clean_text((params.get("system_id") or [""])[0])
    include_legacy = clean_text((params.get("include_legacy") or ["false"])[0]).lower() in {"1", "true", "yes"}
    legacy_type = clean_text((params.get("legacy_type") or ["entries"])[0]) or "entries"
    domain = clean_text((params.get("domain") or [""])[0])
    with connect(database_path) as conn:
        if include_legacy:
            if legacy_type == "actions":
                cases = _legacy_action_candidates(conn, limit=limit, offset=cursor)
                inspected = ["actions"]
            else:
                cases = _legacy_entry_candidates(conn, limit=limit, offset=cursor, domain=domain)
                inspected = ["entries"]
        else:
            cases = _normalized_cases(conn, system_id=system_id, limit=limit, offset=cursor)
            inspected = ["innbank_allocation_plans", "core_signals", "core_alerts"]
    return {
        "status": "ok" if cases else "empty",
        "cases": cases,
        "pagination": {
            "limit": limit,
            "cursor": cursor,
            "next_cursor": cursor + len(cases) if len(cases) == limit else None,
            "stable_order": "created_at DESC, stable primary key ASC",
        },
        "legacy_included": include_legacy,
        "coverage": coverage(
            inspected,
            systems=[system_id] if system_id else [],
            limitations=["Legacy candidates are read-only and not promoted by this endpoint."] if include_legacy else [],
        ),
    }


def _case_parts(case_id: str) -> tuple[str, str, str]:
    parts = clean_text(case_id).split(":", 2)
    if len(parts) != 3:
        raise ValueError("case_id must be namespace:record_type:record_id")
    return parts[0], parts[1], parts[2]


def get_case(database_path, case_id: str) -> dict[str, Any]:
    namespace, record_type, record_id = _case_parts(case_id)
    with connect(database_path) as conn:
        if namespace == "core" and record_type == "innbank_allocation_plan":
            row = conn.execute(
                """
                SELECT p.*, s.signal_type, s.title AS signal_title, s.summary AS signal_summary,
                       s.priority AS signal_priority, s.status AS signal_status,
                       e.event_type, e.processing_status AS event_processing_status,
                       a.alert_id, a.state AS alert_state, a.delivery_channel, a.presented_at, a.acknowledged_at
                FROM innbank_allocation_plans AS p
                JOIN core_signals AS s ON s.signal_id = p.signal_id
                JOIN core_events AS e ON e.event_id = p.source_event_id
                LEFT JOIN core_alerts AS a ON a.signal_id = s.signal_id
                WHERE p.plan_id=?
                """,
                (record_id,),
            ).fetchone()
            if not row:
                raise KeyError("case not found")
            items = [dict(r) for r in conn.execute("SELECT allocation_item_id, item_type, label, proposed_amount_cents, goal_id, state, order_index FROM innbank_allocation_items WHERE plan_id=? ORDER BY order_index", (record_id,)).fetchall()]
            routing = [dict(r) for r in conn.execute("SELECT routing_run_id, status, completed_at, routing_completed_event_id FROM innbank_routing_runs WHERE plan_id=? ORDER BY created_at", (record_id,)).fetchall()]
            plan = dict(row)
            plan["metadata"] = load_json(plan.pop("metadata_json", "{}"), {})
            return {
                "status": "ok",
                "case": {
                    "case_id": case_id,
                    "kind": "normalized",
                    "plan": plan,
                    "items": items,
                    "routing_runs": routing,
                    "delivery": {
                        "state": plan.get("alert_state") or "not_recorded",
                        "channel": plan.get("delivery_channel") or "not_recorded",
                        "status": "delivery_unknown" if plan.get("alert_id") else "not_recorded",
                        "presented_at": plan.get("presented_at"),
                        "acknowledged_at": plan.get("acknowledged_at"),
                    },
                },
                "coverage": coverage(["innbank_allocation_plans", "innbank_allocation_items", "core_events", "core_signals", "core_alerts", "innbank_routing_runs"], systems=[plan["source_system_id"]]),
            }
        if namespace == "legacy" and record_type == "entries":
            row = conn.execute("SELECT id, domain, status, signal_role, action_status, source_type, created_at, updated_at, metadata FROM entries WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise KeyError("case not found")
            data = dict(row)
            data["metadata"] = load_json(data.get("metadata"), {})
            return {
                "status": "ok",
                "case": {
                    "case_id": case_id,
                    "kind": "legacy_candidate",
                    "legacy_table": "entries",
                    "legacy_pk": record_id,
                    "record": data,
                    "provenance": {"table": "entries", "primary_key": record_id},
                },
                "coverage": coverage(["entries"], limitations=["Legacy entry content is not promoted or reclassified by this read."]),
            }
        if namespace == "legacy" and record_type == "actions":
            row = conn.execute("SELECT id, entry_id, status, priority, created_at, updated_at, metadata FROM actions WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise KeyError("case not found")
            data = dict(row)
            data["metadata"] = load_json(data.get("metadata"), {})
            return {
                "status": "ok",
                "case": {
                    "case_id": case_id,
                    "kind": "legacy_candidate",
                    "legacy_table": "actions",
                    "legacy_pk": record_id,
                    "record": data,
                    "provenance": {"table": "actions", "primary_key": record_id, "entry_id": data["entry_id"]},
                },
                "coverage": coverage(["actions"], limitations=["Legacy action is not converted to core_actions by this read."]),
            }
    raise ValueError("unsupported case namespace or record type")


def get_event_trace(database_path, event_id: str) -> dict[str, Any]:
    event_id = clean_text(event_id)
    with connect(database_path) as conn:
        event = conn.execute("SELECT * FROM core_events WHERE event_id=?", (event_id,)).fetchone()
        if not event:
            raise KeyError("event not found")
        event_data = dict(event)
        event_data["payload"] = load_json(event_data.pop("payload_json", "{}"), {})
        gate3 = {table: table_exists(conn, table) for table in GATE3_COVERAGE}
        signals = [dict(r) for r in conn.execute(
            """
            SELECT s.signal_id, s.signal_type, s.priority, s.status, se.relationship
            FROM core_signal_events AS se
            JOIN core_signals AS s ON s.signal_id = se.signal_id
            WHERE se.event_id=?
            ORDER BY s.created_at ASC
            """,
            (event_id,),
        ).fetchall()]
        signal_ids = [s["signal_id"] for s in signals]
        alerts: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        notification_requests: list[dict[str, Any]] = []
        delivery_results: list[dict[str, Any]] = []
        presentations: list[dict[str, Any]] = []
        acknowledgments: list[dict[str, Any]] = []
        ingestion_results: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        if signal_ids:
            placeholders = ",".join("?" for _ in signal_ids)
            alerts = [dict(r) for r in conn.execute(f"SELECT alert_id, signal_id, priority, state, delivery_channel, presented_at, acknowledged_at, resolved_at FROM core_alerts WHERE signal_id IN ({placeholders}) ORDER BY created_at ASC", tuple(signal_ids)).fetchall()]
            decisions = [dict(r) for r in conn.execute(f"SELECT decision_id, signal_id, decision_type, selected_option, decided_by, decided_at FROM core_decisions WHERE signal_id IN ({placeholders}) ORDER BY created_at ASC", tuple(signal_ids)).fetchall()]
        alert_ids = [a["alert_id"] for a in alerts]
        if alert_ids:
            placeholders = ",".join("?" for _ in alert_ids)
            if gate3.get("core_notification_requests"):
                notification_requests = [dict(r) for r in conn.execute(f"SELECT notification_request_id, alert_id, channel, purpose, status, requested_at, requested_by FROM core_notification_requests WHERE alert_id IN ({placeholders}) ORDER BY requested_at ASC", tuple(alert_ids)).fetchall()]
            if gate3.get("core_notification_delivery_results"):
                delivery_results = [dict(r) for r in conn.execute(f"SELECT delivery_result_id, notification_request_id, alert_id, channel, provider_status, attempted_at, provider_accepted_at, delivered_at, failed_at, external_delivery_ref, trusted_evidence_type, trusted_evidence_ref, evidence_recorded_at FROM core_notification_delivery_results WHERE alert_id IN ({placeholders}) ORDER BY attempted_at ASC", tuple(alert_ids)).fetchall()]
            if gate3.get("core_alert_presentations"):
                presentations = [dict(r) for r in conn.execute(f"SELECT presentation_id, alert_id, delivery_result_id, presented_at, presented_by, presentation_surface, session_ref FROM core_alert_presentations WHERE alert_id IN ({placeholders}) ORDER BY presented_at ASC", tuple(alert_ids)).fetchall()]
            if gate3.get("core_alert_acknowledgments"):
                acknowledgments = [dict(r) for r in conn.execute(f"SELECT acknowledgment_id, alert_id, decision_id, acknowledged_at, acknowledged_by, auth_context, trust_level, response, same_case_id FROM core_alert_acknowledgments WHERE alert_id IN ({placeholders}) ORDER BY acknowledged_at ASC", tuple(alert_ids)).fetchall()]
        decision_ids = [d["decision_id"] for d in decisions]
        if decision_ids:
            placeholders = ",".join("?" for _ in decision_ids)
            actions = [dict(r) for r in conn.execute(f"SELECT action_id, decision_id, action_type, status, execution_mode, created_at FROM core_actions WHERE decision_id IN ({placeholders}) ORDER BY created_at ASC", tuple(decision_ids)).fetchall()]
        action_ids = [a["action_id"] for a in actions]
        if action_ids:
            placeholders = ",".join("?" for _ in action_ids)
            outcomes = [dict(r) for r in conn.execute(f"SELECT outcome_id, action_id, outcome_type, result_status, observed_at, created_at FROM core_outcomes WHERE action_id IN ({placeholders}) ORDER BY created_at ASC", tuple(action_ids)).fetchall()]
        if gate3.get("core_ingestion_results"):
            ingestion_results = [dict(r) for r in conn.execute("SELECT ingestion_result_id, operation_id, attempt_id, observation_id, event_id, status, effects_json, error_json, created_at FROM core_ingestion_results WHERE event_id=? ORDER BY created_at ASC", (event_id,)).fetchall()]
            for result in ingestion_results:
                result["effects"] = load_json(result.pop("effects_json", "[]"), [])
                result["error"] = load_json(result.pop("error_json", "{}"), {})
        observation_ids = [r["observation_id"] for r in ingestion_results if r.get("observation_id")]
        payload_observation_id = clean_text((event_data.get("payload") or {}).get("source_observation_id"))
        if payload_observation_id:
            observation_ids.append(payload_observation_id)
        if gate3.get("core_source_observations") and observation_ids:
            unique_ids = sorted(set(observation_ids))
            placeholders = ",".join("?" for _ in unique_ids)
            observations = [dict(r) for r in conn.execute(f"SELECT observation_id, source_system_id, source_connection_id, account_external_id, source_transaction_id, economic_inflow_key, observation_status, amount_cents, currency, classification, classification_confidence, observed_at, effective_date, posted_at, dedupe_state, match_state, pending_observation_id, posted_observation_id, supersedes_observation_id FROM core_source_observations WHERE observation_id IN ({placeholders}) ORDER BY created_at ASC", tuple(unique_ids)).fetchall()]
        audit_rows = []
        if table_exists(conn, "audit_log"):
            audit_rows = [dict(r) for r in conn.execute("SELECT id, event_type, entity_type, entity_id, created_at FROM audit_log WHERE entity_id=? ORDER BY created_at ASC", (event_id,)).fetchall()]
        delivery = "not_recorded"
        if delivery_results:
            if any(row["provider_status"] == "delivered" for row in delivery_results):
                delivery = "delivered"
            elif any(row["provider_status"] in {"submitted", "provider_accepted", "failed", "unknown"} for row in delivery_results):
                delivery = "delivery_attempted"
        elif notification_requests:
            delivery = "requested"
        elif alerts:
            delivery = "delivery_unknown"
        boundaries = {
            "observed": "recorded" if observations else "not_recorded",
            "ingested": "recorded" if ingestion_results else "event_recorded_without_observation",
            "processed": event_data.get("processing_status") or "unknown",
            "queued": "recorded" if alerts else "not_recorded",
            "notification_requested": "recorded" if notification_requests else "not_recorded",
            "delivery_attempted": "recorded" if delivery_results else "not_recorded",
            "delivered": "recorded" if any(row.get("provider_status") == "delivered" for row in delivery_results) else ("unknown" if delivery_results else "not_recorded"),
            "presented": "recorded" if presentations else "not_recorded",
            "acknowledged": "recorded" if acknowledgments else "not_recorded",
            "decided": "recorded" if decisions else "not_recorded",
            "routed": "recorded" if actions else "not_recorded",
            "outcome_recorded": "recorded" if outcomes else "not_recorded",
        }
        return {
            "status": "ok",
            "event": event_data,
            "source_observations": observations,
            "ingestion_results": ingestion_results,
            "signals": signals,
            "alerts": alerts,
            "notification_requests": notification_requests,
            "delivery_results": delivery_results,
            "presentations": presentations,
            "acknowledgments": acknowledgments,
            "decisions": decisions,
            "actions": actions,
            "outcomes": outcomes,
            "operations": audit_rows,
            "delivery_status": delivery,
            "boundaries": boundaries,
            "legacy_unverified": {
                "core_alerts_presented_at": [
                    {"alert_id": alert["alert_id"], "presented_at": alert.get("presented_at")}
                    for alert in alerts
                    if alert.get("presented_at")
                ],
            },
            "coverage": coverage(
                ["core_events", "core_signal_events", "core_signals", "core_alerts", "core_decisions", "core_actions", "core_outcomes", "audit_log"] + [table for table, exists in gate3.items() if exists],
                systems=[event_data["source_system_id"]],
                limitations=[] if all(gate3.values()) else ["Gate 3A reliability tables are not fully initialized; trace preserves schema-v2 compatibility."],
            ),
        }
