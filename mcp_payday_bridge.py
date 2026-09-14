"""Info Analyzer payday MCP bridge.

This server exposes the ChatGPT-facing tools required for the
INNBANK payday bridge milestone:

* prepare_payday_case
* record_financial_source_observation
* get_source_observation_status
* get_payday_case
* save_payday_decision
* record_manual_routing
* ingest_capture
* get_day_progress

It reads from the canonical SQLite database through the shared connection
helper, keeps API credentials server-side, and reuses the existing INNBANK
allocation and routing services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from core_database import connect, resolve_database_path
from core_captures import get_day_progress as shared_get_day_progress
from core_captures import ingest_capture as core_ingest_capture
from core_captures import list_captures as shared_list_captures
from core_events import create_event as core_create_event
from core_events import normalize_timestamp
from core_innbank_routing import (
    amount_to_cents,
    cents_to_money,
    create_allocation_plan,
    get_allocation_plan,
    record_allocation_routing,
    respond_to_allocation_plan,
)
from core_migrations import initialize_core_migrations
from core_observations import ingest_observation, record_source_observation
from core_processors import EventDispatcher, InnbankProcessingError
from core_shared_access import (
    get_case as shared_get_case,
    get_event_trace as shared_get_event_trace,
    get_system_status as shared_get_system_status,
    list_cases as shared_list_cases,
)
from server import configured_api_key

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations
except Exception:  # pragma: no cover - guarded in tests
    MCPServer = None  # type: ignore[assignment]
    ToolAnnotations = None  # type: ignore[assignment]


MCP_AVAILABLE = MCPServer is not None and ToolAnnotations is not None

WRITE_RESPONSES = {"approve", "modify", "defer", "reject", "not_income", "not-income"}
OUTPUT_STATES = {
    "approve": "approved",
    "modify": "pending_manual_routing",
    "defer": "deferred",
    "reject": "rejected",
    "not_income": "rejected",
    "not-income": "rejected",
}
NON_DEPLOYABLE_CLASSIFICATIONS = {
    "internal_transfer",
    "credit_card_payment",
    "refund",
    "reversal",
    "interest",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def _fail(message: str, **extra: Any) -> dict[str, Any]:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return payload


def _success(**extra: Any) -> dict[str, Any]:
    payload = {"ok": True}
    payload.update(extra)
    return payload


def _maybe_result_state(response: str) -> str:
    return OUTPUT_STATES.get(response, response)


def _money_box(label: str, amount_cents: Any, currency: str = "USD", *, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        cents = int(amount_cents)
    except (TypeError, ValueError):
        return None
    box = {
        "label": label,
        "amount_cents": cents,
        "amount": cents_to_money(cents, currency),
        "currency": clean_text(currency or "USD").upper(),
    }
    if extra:
        box.update(extra)
    return box


def _normalize_response(value: Any) -> str:
    response = clean_text(value).lower().replace(" ", "_")
    if response == "notincome":
        response = "not_income"
    if response == "not-income":
        response = "not_income"
    return response


def _tool_annotations(*, read_only: bool) -> Any:
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=not read_only,
        openWorldHint=False,
    )


def _signal_context(conn, signal_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            s.*,
            e.event_id AS source_event_id,
            e.event_type AS source_event_type,
            e.occurred_at AS source_event_occurred_at,
            e.observed_at AS source_event_observed_at,
            e.received_at AS source_event_received_at,
            e.priority AS source_event_priority,
            e.confidence AS source_event_confidence,
            e.processing_status AS source_event_processing_status,
            e.payload_json AS source_event_payload_json
        FROM core_signals AS s
        JOIN core_signal_events AS se
            ON se.signal_id = s.signal_id AND se.relationship = 'trigger'
        JOIN core_events AS e
            ON e.event_id = se.event_id
        WHERE s.signal_id = ?
        """,
        (signal_id,),
    ).fetchone()
    if not row:
        raise KeyError("signal not found")
    signal = dict(row)
    signal["metadata"] = load_json(signal.pop("metadata_json", "{}"), {})
    signal["source_event_payload"] = load_json(signal.pop("source_event_payload_json", "{}"), {})
    return signal


def _alert_context(conn, signal_id: str, alert_id: str | None = None) -> dict[str, Any] | None:
    query = """
        SELECT
            a.*,
            s.signal_type,
            s.title AS signal_title,
            s.summary AS signal_summary,
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
        WHERE a.signal_id = ?
    """
    params: tuple[Any, ...] = (signal_id,)
    if alert_id:
        query += " AND a.alert_id = ?"
        params = (signal_id, alert_id)
    query += " ORDER BY a.updated_at DESC, a.created_at DESC LIMIT 1"
    row = conn.execute(query, params).fetchone()
    if not row:
        return None
    alert = dict(row)
    return {
        "alert_id": alert["alert_id"],
        "signal_id": alert["signal_id"],
        "signal_type": alert["signal_type"],
        "source_system_id": alert["owner_system_id"],
        "source_system_name": alert["source_system_name"],
        "title": alert["signal_title"],
        "summary": alert["signal_summary"],
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


def _plan_from_signal(conn, signal_id: str) -> str | None:
    row = conn.execute(
        "SELECT plan_id FROM innbank_allocation_plans WHERE signal_id=? ORDER BY created_at ASC LIMIT 1",
        (signal_id,),
    ).fetchone()
    return clean_text(row["plan_id"]) if row else None


def _resolve_case(conn, *, alert_id: str | None = None, signal_id: str | None = None, plan_id: str | None = None) -> dict[str, Any]:
    if not any([alert_id, signal_id, plan_id]):
        raise ValueError("alert_id, signal_id, or plan_id is required")

    resolved_plan_id = clean_text(plan_id) or None
    resolved_signal_id = clean_text(signal_id) or None
    resolved_alert_id = clean_text(alert_id) or None

    if resolved_plan_id:
        plan_row = conn.execute(
            "SELECT plan_id, signal_id, source_event_id FROM innbank_allocation_plans WHERE plan_id=?",
            (resolved_plan_id,),
        ).fetchone()
        if not plan_row:
            raise KeyError("allocation plan not found")
        plan_signal_id = clean_text(plan_row["signal_id"])
        if resolved_signal_id and resolved_signal_id != plan_signal_id:
            raise ValueError("provided identifiers do not refer to the same payday case")
        resolved_signal_id = resolved_signal_id or plan_signal_id
    if resolved_alert_id:
        alert_row = conn.execute(
            "SELECT alert_id, signal_id FROM core_alerts WHERE alert_id=?",
            (resolved_alert_id,),
        ).fetchone()
        if not alert_row:
            raise KeyError("alert not found")
        alert_signal_id = clean_text(alert_row["signal_id"])
        if resolved_signal_id and resolved_signal_id != alert_signal_id:
            raise ValueError("provided identifiers do not refer to the same payday case")
        resolved_signal_id = alert_signal_id
    if resolved_signal_id and not resolved_plan_id:
        resolved_plan_id = _plan_from_signal(conn, resolved_signal_id)
    if not resolved_signal_id:
        raise KeyError("signal not found")

    signal = _signal_context(conn, resolved_signal_id)
    alert = _alert_context(conn, resolved_signal_id, resolved_alert_id)
    allocation_plan = None
    if resolved_plan_id:
        allocation_plan = get_allocation_plan(_database_path_from_connection(conn), resolved_plan_id)

    event = {
        "event_id": signal["source_event_id"],
        "source_system_id": signal["owner_system_id"],
        "event_type": signal["source_event_type"],
        "occurred_at": signal["source_event_occurred_at"],
        "observed_at": signal["source_event_observed_at"],
        "received_at": signal["source_event_received_at"],
        "priority": signal["source_event_priority"],
        "confidence": signal["source_event_confidence"],
        "processing_status": signal["source_event_processing_status"],
        "payload": signal["source_event_payload"],
    }
    if allocation_plan is None and resolved_plan_id:
        allocation_plan = get_allocation_plan(_database_path_from_connection(conn), resolved_plan_id)

    if allocation_plan is None:
        allocation_plan = _plan_bundle(conn, resolved_signal_id)
        if allocation_plan is not None:
            resolved_plan_id = allocation_plan["plan"]["plan_id"]

    active_goals = _active_goals(conn, resolved_signal_id, allocation_plan)
    previous_outcomes = _previous_outcomes(conn, resolved_signal_id, allocation_plan)
    lessons = _lessons(conn, previous_outcomes)
    payday_context = _payday_context(signal, allocation_plan, event)
    return {
        "case_id": {
            "alert_id": alert["alert_id"] if alert else None,
            "signal_id": signal["signal_id"],
            "plan_id": resolved_plan_id,
            "event_id": signal["source_event_id"],
        },
        "event": event,
        "signal": signal,
        "alert": alert,
        "allocation_plan": allocation_plan,
        "active_goals": active_goals,
        "previous_outcomes": previous_outcomes,
        "lessons": lessons,
        "payday_context": payday_context,
    }


def _database_path_from_connection(conn) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return clean_text(row["file"]) if row else ""


def _plan_bundle(conn, signal_id: str) -> dict[str, Any] | None:
    plan_id = _plan_from_signal(conn, signal_id)
    if not plan_id:
        return None
    return get_allocation_plan(_database_path_from_connection(conn), plan_id)


def _active_goals(conn, signal_id: str, allocation_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    goal_ids = {
        clean_text(row["goal_id"])
        for row in conn.execute(
            """
            SELECT goal_id
            FROM core_signal_goals
            WHERE signal_id=?
            """,
            (signal_id,),
        ).fetchall()
        if clean_text(row["goal_id"])
    }
    if allocation_plan:
        for item in allocation_plan.get("items") or []:
            goal_id = clean_text(item.get("goal_id"))
            if goal_id:
                goal_ids.add(goal_id)
    if not goal_ids:
        return []
    rows = conn.execute(
        f"""
        SELECT *
        FROM core_goals
        WHERE goal_id IN ({','.join('?' for _ in goal_ids)})
        ORDER BY priority ASC, created_at ASC
        """,
        tuple(goal_ids),
    ).fetchall()
    results = []
    for row in rows:
        goal = dict(row)
        goal["metadata"] = load_json(goal.pop("metadata_json", "{}"), {})
        results.append(goal)
    return results


def _previous_outcomes(conn, signal_id: str, allocation_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    source_event_id = None
    if allocation_plan:
        source_event_id = clean_text((allocation_plan.get("plan") or {}).get("source_event_id"))
    if not source_event_id:
        row = conn.execute(
            """
            SELECT e.event_id
            FROM core_signal_events AS se
            JOIN core_events AS e ON e.event_id = se.event_id
            WHERE se.signal_id = ? AND se.relationship = 'trigger'
            LIMIT 1
            """,
            (signal_id,),
        ).fetchone()
        source_event_id = clean_text(row["event_id"]) if row else None
    action_ids = {
        clean_text(row["action_id"])
        for row in conn.execute(
            """
            SELECT a.action_id
            FROM core_actions AS a
            JOIN innbank_allocation_items AS ai ON ai.core_action_id = a.action_id
            WHERE ai.plan_id = ?
            """,
            (clean_text((allocation_plan or {}).get("plan", {}).get("plan_id")) or None,),
        ).fetchall()
        if clean_text(row["action_id"])
    } if allocation_plan else set()
    if not source_event_id and not action_ids:
        return []
    clauses = []
    params: list[Any] = []
    if source_event_id:
        clauses.append("source_event_id = ?")
        params.append(source_event_id)
    if action_ids:
        clauses.append(f"action_id IN ({','.join('?' for _ in action_ids)})")
        params.extend(sorted(action_ids))
    where = " OR ".join(clauses) if clauses else "1=0"
    rows = conn.execute(
        f"""
        SELECT *
        FROM core_outcomes
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT 10
        """,
        tuple(params),
    ).fetchall()
    results = []
    for row in rows:
        outcome = dict(row)
        outcome["measurement"] = load_json(outcome.pop("measurement_json", "{}"), {})
        results.append(outcome)
    return results


def _lessons(conn, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outcome_ids = [clean_text(outcome.get("outcome_id")) for outcome in outcomes if clean_text(outcome.get("outcome_id"))]
    if not outcome_ids:
        return []
    rows = conn.execute(
        f"""
        SELECT
            l.*,
            lo.relationship AS outcome_relationship
        FROM core_lessons AS l
        JOIN core_lesson_outcomes AS lo ON lo.lesson_id = l.lesson_id
        WHERE lo.outcome_id IN ({','.join('?' for _ in outcome_ids)})
        ORDER BY l.created_at DESC
        LIMIT 10
        """,
        tuple(outcome_ids),
    ).fetchall()
    results = []
    for row in rows:
        lesson = dict(row)
        lesson["metadata"] = load_json(lesson.pop("metadata_json", "{}"), {})
        results.append(lesson)
    return results


def _payday_context(signal: dict[str, Any], allocation_plan: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") or {}
    classification = clean_text(payload.get("classification") or "unknown").lower()
    classification_confidence = payload.get("classification_confidence")
    if classification_confidence in (None, ""):
        classification_confidence = signal["metadata"].get("classification_confidence")
    classification_confidence = float(classification_confidence or 0.0)
    amount_cents = None
    if payload.get("amount") not in (None, ""):
        try:
            amount_cents = int(round(float(payload["amount"]) * 100))
        except Exception:
            amount_cents = None
    if amount_cents is None:
        amount_cents = signal["metadata"].get("amount_cents")
    support = {
        "classification": classification,
        "classification_confidence": classification_confidence,
        "supporting_evidence": [
            {"field": "account_name", "value": clean_text(payload.get("account_name") or signal["metadata"].get("account_name"))},
            {"field": "transaction_ref", "value": clean_text(payload.get("transaction_ref") or signal["metadata"].get("transaction_ref")) or None},
            {"field": "source_event_id", "value": signal["source_event_id"]},
        ],
        "probable_internal_transfer": classification in NON_DEPLOYABLE_CLASSIFICATIONS or "internal transfer" in clean_text(payload.get("account_name")).lower(),
        "confirmed_internal_transfer": classification == "internal_transfer",
        "user_override": None,
    }
    plan = (allocation_plan or {}).get("plan") or {}
    plan_metadata = plan.get("metadata") or {}
    if allocation_plan and plan:
        support["user_override"] = clean_text(plan.get("latest_response")) or None
    operating_floor = None
    protected_hold = None
    protected_holds: dict[str, Any] = {}
    proposed_route: list[dict[str, Any]] = []
    actual_spend: list[dict[str, Any]] = []
    retained_cash = None
    capital_semantics = load_json(plan_metadata.get("capital_semantics"), {}) if isinstance(plan_metadata, dict) else {}
    raw_transfer_evidence = load_json(plan_metadata.get("transfer_evidence"), {}) if isinstance(plan_metadata, dict) else {}
    transfer_evidence = dict(raw_transfer_evidence) if isinstance(raw_transfer_evidence, dict) else {}
    if allocation_plan:
        items = allocation_plan.get("items") or []
        route_items = [item for item in items if item.get("item_type") == "allocation"]
        retained_item = next((item for item in items if item.get("item_type") == "unallocated"), None)
        route_total_cents = sum(int(item.get("proposed_amount_cents") or 0) for item in route_items)
        if retained_item:
            retained_cash = _money_box(
                retained_item.get("label") or "Retained paycheck remainder",
                retained_item.get("proposed_amount_cents"),
                retained_item.get("currency") or plan.get("currency") or "USD",
                extra={"state": retained_item.get("state"), "source": "allocation_item"},
            )
        proposed_route = [
            {
                "allocation_item_id": item.get("allocation_item_id"),
                "label": item.get("label"),
                "goal_id": item.get("goal_id"),
                "item_type": item.get("item_type"),
                "proposed_amount_cents": item.get("proposed_amount_cents"),
                "proposed_amount": item.get("proposed_amount"),
                "state": item.get("state"),
            }
            for item in route_items
        ]
        actual_spend = [
            {
                "allocation_item_id": row.get("allocation_item_id"),
                "label": row.get("label"),
                "actual_amount_cents": row.get("actual_amount_cents"),
                "actual_amount": row.get("actual_amount"),
                "variance_cents": row.get("variance_cents"),
                "variance": row.get("variance"),
                "routing_status": row.get("routing_status"),
                "outcome_id": (row.get("outcome") or {}).get("outcome_id"),
                "result_status": (row.get("outcome") or {}).get("result_status"),
            }
            for row in allocation_plan.get("routing_items") or []
        ]
        operating_floor_cents = capital_semantics.get("operating_floor_cents")
        if operating_floor_cents is not None:
            operating_floor = _money_box(
                "Operating floor",
                operating_floor_cents,
                plan.get("currency") or "USD",
                extra={"state": capital_semantics.get("decision_state") or plan.get("status"), "source": "plan_metadata", "purpose": "capital_protection"},
            )
        if operating_floor is None and retained_item:
            operating_floor = _money_box(
                retained_item.get("label") or "Retained cash",
                retained_item.get("proposed_amount_cents"),
                retained_item.get("currency") or plan.get("currency") or "USD",
                extra={"state": retained_item.get("state"), "source": "allocation_item"},
            )
        if isinstance(capital_semantics, dict):
            protected_holds_data = capital_semantics.get("protected_holds")
            if isinstance(protected_holds_data, dict):
                medical_hold = _money_box(
                    "Medical protected hold",
                    protected_holds_data.get("medical_cents"),
                    plan.get("currency") or "USD",
                    extra={"source": "plan_metadata"},
                )
                insurance_hold = _money_box(
                    "Insurance/daycare protected hold",
                    protected_holds_data.get("insurance_daycare_cents"),
                    plan.get("currency") or "USD",
                    extra={"source": "plan_metadata"},
                )
                if medical_hold:
                    protected_holds["medical"] = medical_hold
                if insurance_hold:
                    protected_holds["insurance_daycare"] = insurance_hold
        if capital_semantics.get("starting_balance_cents") is None and plan.get("paycheck_amount_cents") is not None:
            capital_semantics["starting_balance_cents"] = plan.get("paycheck_amount_cents")
        if capital_semantics.get("operating_floor_cents") is None and retained_item is not None:
            capital_semantics["operating_floor_cents"] = int(retained_item.get("proposed_amount_cents") or 0)
        if capital_semantics.get("headroom_above_floor_cents") is None and capital_semantics.get("starting_balance_cents") is not None and capital_semantics.get("operating_floor_cents") is not None:
            capital_semantics["headroom_above_floor_cents"] = int(capital_semantics["starting_balance_cents"]) - int(capital_semantics["operating_floor_cents"])
        if capital_semantics.get("total_protected_holds_cents") is None:
            total_holds = 0
            for hold in protected_holds.values():
                total_holds += int(hold.get("amount_cents") or 0)
            capital_semantics["total_protected_holds_cents"] = total_holds
        if capital_semantics.get("truly_deployable_cents") is None and capital_semantics.get("headroom_above_floor_cents") is not None:
            capital_semantics["truly_deployable_cents"] = max(
                int(capital_semantics.get("headroom_above_floor_cents") or 0) - int(capital_semantics.get("total_protected_holds_cents") or 0),
                0,
            )
        if capital_semantics.get("projected_balance_after_routes_cents") is None and capital_semantics.get("starting_balance_cents") is not None:
            capital_semantics["projected_balance_after_routes_cents"] = int(capital_semantics["starting_balance_cents"]) - route_total_cents
        if capital_semantics.get("decision_state") is None:
            capital_semantics["decision_state"] = plan.get("status")
        if capital_semantics.get("retained_cash_cents") is None:
            capital_semantics["retained_cash_cents"] = int(retained_item.get("proposed_amount_cents") or 0) if retained_item else max(int(plan.get("paycheck_amount_cents") or 0) - route_total_cents, 0)
        if transfer_evidence:
            transfer_probable = transfer_evidence.get("probable_internal_transfer")
            transfer_confirmed = transfer_evidence.get("confirmed_internal_transfer")
            transfer_confidence = transfer_evidence.get("classification_confidence")
            transfer_evidence = {
                "probable_internal_transfer": support["probable_internal_transfer"] if transfer_probable is None else bool(transfer_probable),
                "confirmed_internal_transfer": support["confirmed_internal_transfer"] if transfer_confirmed is None else bool(transfer_confirmed),
                "classification_confidence": support["classification_confidence"] if transfer_confidence is None else float(transfer_confidence),
                "matching_amount_cents": transfer_evidence.get("matching_amount_cents"),
                "payroll_posted_at": transfer_evidence.get("payroll_posted_at"),
                "transfer_posted_at": transfer_evidence.get("transfer_posted_at"),
                "wells_fargo_reference": transfer_evidence.get("wells_fargo_reference"),
                "capital_one_reference": transfer_evidence.get("capital_one_reference"),
                "supporting_evidence": transfer_evidence.get("supporting_evidence"),
                "user_override": transfer_evidence.get("user_override"),
            }
    return {
        "amount_cents": amount_cents,
        "amount": cents_to_money(int(amount_cents), "USD") if amount_cents is not None else None,
        "source_system_id": signal["owner_system_id"],
        "signal_id": signal["signal_id"],
        "signal_type": signal["signal_type"],
        "classification": support["classification"],
        "classification_confidence": support["classification_confidence"],
        "probable_internal_transfer": transfer_evidence.get("probable_internal_transfer", support["probable_internal_transfer"]) if allocation_plan else support["probable_internal_transfer"],
        "confirmed_internal_transfer": transfer_evidence.get("confirmed_internal_transfer", support["confirmed_internal_transfer"]) if allocation_plan else support["confirmed_internal_transfer"],
        "supporting_evidence": support["supporting_evidence"],
        "user_override": support["user_override"],
        "operating_floor": operating_floor,
        "protected_hold": protected_hold,
        "medical_protected_hold": protected_holds.get("medical"),
        "insurance_daycare_protected_hold": protected_holds.get("insurance_daycare"),
        "protected_holds": protected_holds,
        "retained_cash": retained_cash,
        "capital_semantics": capital_semantics if allocation_plan else {},
        "transfer_evidence": transfer_evidence if allocation_plan else {},
        "transfer_classification_confidence": transfer_evidence.get("classification_confidence") if allocation_plan else None,
        "proposed_route": proposed_route,
        "actual_spend": actual_spend,
    }


def _latest_decision_row(database_path: str, plan_id: str) -> dict[str, Any] | None:
    with connect(database_path) as conn:
        row = conn.execute(
            """
            SELECT d.*
            FROM core_decisions AS d
            JOIN innbank_allocation_plans AS p ON p.latest_decision_id = d.decision_id
            WHERE p.plan_id = ?
            """,
            (plan_id,),
        ).fetchone()
        if not row:
            return None
        decision = dict(row)
        decision["metadata"] = load_json(decision.pop("metadata_json", "{}"), {})
        return decision


def _map_requested_decision(requested: str) -> str:
    if requested in {"not_income", "not-income"}:
        return "reject"
    if requested not in WRITE_RESPONSES:
        raise ValueError("decision must be approve, modify, defer, reject, or not-income")
    return "hold" if requested == "modify" else requested


def _input_money_to_cents(value: Any, field_name: str) -> int:
    if isinstance(value, dict):
        if value.get("amount_cents") not in (None, ""):
            return int(value["amount_cents"])
        value = value.get("amount")
    return amount_to_cents(value, field_name)


def _decimal_money_string(cents: int) -> str:
    return str((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))


def _parse_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = clean_text(value).lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{field_name} must be true or false")


def _normalize_named_amounts(values: Any, field_name: str) -> list[dict[str, Any]]:
    if values is None:
        values = []
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a JSON array")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{index}] must be a JSON object")
        label = clean_text(item.get("label") or item.get("name"))
        if not label:
            raise ValueError(f"{field_name}[{index}].label is required")
        amount_cents = _input_money_to_cents(item, f"{field_name}[{index}].amount")
        if amount_cents < 0:
            raise ValueError(f"{field_name}[{index}].amount must be non-negative")
        normalized.append(
            {
                "label": label,
                "amount_cents": amount_cents,
                "amount": cents_to_money(amount_cents, clean_text(item.get("currency") or "USD").upper()),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            }
        )
    return normalized


def _normalize_transfer_evidence(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError("possible_matching_transfer_evidence must be a JSON object")
    evidence: dict[str, Any] = {}
    for key in (
        "probable_internal_transfer",
        "confirmed_internal_transfer",
        "classification_confidence",
        "matching_amount_cents",
        "matching_amount",
        "payroll_posted_at",
        "transfer_posted_at",
        "wells_fargo_reference",
        "capital_one_reference",
        "supporting_evidence",
        "user_override",
    ):
        if key in value:
            evidence[key] = value[key]
    if "matching_amount_cents" not in evidence and evidence.get("matching_amount") not in (None, ""):
        evidence["matching_amount_cents"] = _input_money_to_cents(evidence["matching_amount"], "possible_matching_transfer_evidence.matching_amount")
    evidence.pop("matching_amount", None)
    if "classification_confidence" in evidence:
        try:
            confidence = float(evidence["classification_confidence"])
        except (TypeError, ValueError) as exc:
            raise ValueError("possible_matching_transfer_evidence.classification_confidence must be between 0 and 1") from exc
        if confidence < 0 or confidence > 1:
            raise ValueError("possible_matching_transfer_evidence.classification_confidence must be between 0 and 1")
        evidence["classification_confidence"] = confidence
    if "probable_internal_transfer" in evidence:
        evidence["probable_internal_transfer"] = _parse_bool(
            evidence["probable_internal_transfer"],
            "possible_matching_transfer_evidence.probable_internal_transfer",
        )
    if "confirmed_internal_transfer" in evidence:
        evidence["confirmed_internal_transfer"] = _parse_bool(
            evidence["confirmed_internal_transfer"],
            "possible_matching_transfer_evidence.confirmed_internal_transfer",
        )
    return evidence


def _build_payday_case_inputs(
    *,
    paycheck_amount: Any,
    posted_at: str,
    employer_reference: str,
    receiving_account: str,
    starting_balance: Any,
    operating_floor: Any,
    protected_holds: list[dict[str, Any]] | None,
    proposed_routes: list[dict[str, Any]] | None,
    currency: str | None = "USD",
    source_transaction_id: str | None = None,
    dedupe_key: str | None = None,
    possible_matching_transfer_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    currency_code = clean_text(currency or "USD").upper()
    if not currency_code:
        raise ValueError("currency is required")
    amount_cents = _input_money_to_cents(paycheck_amount, "paycheck_amount")
    if amount_cents <= 0:
        raise ValueError("paycheck_amount must be positive")
    starting_balance_cents = _input_money_to_cents(starting_balance, "starting_balance")
    operating_floor_cents = _input_money_to_cents(operating_floor, "operating_floor")
    if starting_balance_cents < operating_floor_cents:
        raise ValueError("starting_balance must be greater than or equal to operating_floor")
    normalized_holds = _normalize_named_amounts(protected_holds, "protected_holds")
    normalized_routes = _normalize_named_amounts(proposed_routes, "proposed_routes")
    if not normalized_routes:
        raise ValueError("proposed_routes must include at least one route")
    posted_at_utc = normalize_timestamp(posted_at, "posted_at")
    source_ref = clean_text(source_transaction_id or employer_reference)
    resolved_dedupe_key = clean_text(dedupe_key or source_transaction_id)
    if not resolved_dedupe_key:
        raise ValueError("source_transaction_id or dedupe_key is required")
    total_protected_holds_cents = sum(item["amount_cents"] for item in normalized_holds)
    route_total_cents = sum(item["amount_cents"] for item in normalized_routes)
    headroom_above_floor_cents = starting_balance_cents - operating_floor_cents
    truly_deployable_cents = headroom_above_floor_cents - total_protected_holds_cents
    if truly_deployable_cents < 0:
        raise ValueError("protected holds exceed headroom above operating floor")
    if route_total_cents > truly_deployable_cents:
        raise ValueError("sum(proposed_routes) must not exceed truly_deployable capital")
    retained_paycheck_remainder_cents = amount_cents - route_total_cents
    if retained_paycheck_remainder_cents < 0:
        raise ValueError("sum(proposed_routes) must not exceed paycheck amount")
    projected_balance_after_routes_cents = starting_balance_cents - route_total_cents
    transfer_evidence = _normalize_transfer_evidence(possible_matching_transfer_evidence)
    protected_hold_map: dict[str, int] = {}
    protected_hold_details: list[dict[str, Any]] = []
    for hold in normalized_holds:
        key = clean_text(hold["label"]).lower().replace("/", "_").replace(" ", "_").replace("-", "_")
        protected_hold_map[f"{key}_cents"] = hold["amount_cents"]
        protected_hold_details.append(
            {
                "label": hold["label"],
                "amount_cents": hold["amount_cents"],
                "amount": cents_to_money(hold["amount_cents"], currency_code),
            }
        )
    capital_semantics = {
        "starting_balance_cents": starting_balance_cents,
        "operating_floor_cents": operating_floor_cents,
        "headroom_above_floor_cents": headroom_above_floor_cents,
        "protected_holds": protected_hold_map,
        "protected_hold_details": protected_hold_details,
        "total_protected_holds_cents": total_protected_holds_cents,
        "truly_deployable_cents": truly_deployable_cents,
        "projected_balance_after_routes_cents": projected_balance_after_routes_cents,
        "retained_cash_cents": retained_paycheck_remainder_cents,
        "decision_state": "proposed_only",
    }
    event_payload = {
        "source_system_id": "sys_innbank",
        "event_type": "financial_inflow_posted",
        "occurred_at": posted_at_utc,
        "dedupe_key": resolved_dedupe_key,
        "source_ref": source_ref or None,
        "priority": "P0",
        "confidence": 0.99,
        "payload": {
            "amount": _decimal_money_string(amount_cents),
            "currency": currency_code,
            "account_name": clean_text(receiving_account),
            "classification": "payroll",
            "classification_confidence": 0.99,
            "transaction_ref": source_ref,
        },
    }
    plan_items = [
        {
            "item_type": "allocation",
            "label": route["label"],
            "proposed_amount_cents": route["amount_cents"],
            "metadata": route["metadata"],
        }
        for route in normalized_routes
    ]
    plan_items.append(
        {
            "item_type": "unallocated",
            "label": "Retained paycheck remainder",
            "proposed_amount_cents": retained_paycheck_remainder_cents,
            "metadata": {"reason": "retained_cash_not_operating_floor"},
        }
    )
    metadata = {
        "capital_semantics": capital_semantics,
        "prepared_by": "prepare_payday_case",
    }
    if transfer_evidence is not None:
        metadata["transfer_evidence"] = transfer_evidence
    preview = {
        "source_system_id": "sys_innbank",
        "event_type": "financial_inflow_posted",
        "dedupe_key": resolved_dedupe_key,
        "source_transaction_id": clean_text(source_transaction_id) or None,
        "posted_at": posted_at_utc,
        "paycheck_amount_cents": amount_cents,
        "paycheck_amount": cents_to_money(amount_cents, currency_code),
        "starting_balance": _money_box("Starting account balance", starting_balance_cents, currency_code),
        "operating_floor": _money_box("Operating floor", operating_floor_cents, currency_code),
        "protected_holds": protected_hold_details,
        "total_protected_holds_cents": total_protected_holds_cents,
        "headroom_above_floor_cents": headroom_above_floor_cents,
        "truly_deployable_cents": truly_deployable_cents,
        "proposed_routes": [
            {"label": route["label"], "amount_cents": route["amount_cents"], "amount": cents_to_money(route["amount_cents"], currency_code)}
            for route in normalized_routes
        ],
        "proposed_route_total_cents": route_total_cents,
        "retained_paycheck_remainder": _money_box("Retained paycheck remainder", retained_paycheck_remainder_cents, currency_code),
        "projected_balance_after_routes": _money_box("Projected account balance after routes", projected_balance_after_routes_cents, currency_code),
        "actual_spend": [],
        "decision_state": "proposed_only",
        "possible_matching_transfer_evidence": transfer_evidence,
        "will_write": {
            "confirmed_false": "no database writes",
            "confirmed_true": "create event, signal, alert, and proposed allocation plan through existing services",
        },
    }
    return {
        "event_payload": event_payload,
        "plan_payload": {
            "title": f"Payday allocation candidate: {cents_to_money(amount_cents, currency_code)}",
            "summary": f"{clean_text(employer_reference)} posted to {clean_text(receiving_account)}; allocation is proposed only.",
            "rationale": "Prepared from explicit paycheck and capital-context inputs. No routing has been approved or recorded.",
            "recommended_action": "Review the proposed routes and decide whether to approve, modify, defer, or reject.",
            "notes": "decision_state=proposed_only; no_allocation_approved; no_manual_routing_recorded",
            "metadata": metadata,
            "items": plan_items,
        },
        "preview": preview,
    }


def _existing_case_for_dedupe(conn, dedupe_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT e.event_id, s.signal_id, a.alert_id, p.plan_id
        FROM core_events AS e
        LEFT JOIN core_signal_events AS se ON se.event_id = e.event_id AND se.relationship = 'trigger'
        LEFT JOIN core_signals AS s ON s.signal_id = se.signal_id
        LEFT JOIN core_alerts AS a ON a.signal_id = s.signal_id
        LEFT JOIN innbank_allocation_plans AS p ON p.signal_id = s.signal_id
        WHERE e.source_system_id = 'sys_innbank'
          AND e.event_type = 'financial_inflow_posted'
          AND e.dedupe_key = ?
        ORDER BY e.created_at ASC, p.created_at ASC
        LIMIT 1
        """,
        (dedupe_key,),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    plan_id = clean_text(result.get("plan_id"))
    signal_id = clean_text(result.get("signal_id"))
    if plan_id:
        result["case"] = _resolve_case(conn, alert_id=None, signal_id=None, plan_id=plan_id)
    elif signal_id:
        result["case"] = _resolve_case(conn, alert_id=None, signal_id=signal_id, plan_id=None)
    else:
        result["case"] = None
    return result


def _row_to_source_observation(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = load_json(data.pop("metadata_json", "{}"), {})
    return data


def _existing_ingestion_for_economic_inflow(conn, observation: dict[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            o.observation_id,
            i.event_id,
            s.signal_id,
            a.alert_id
        FROM core_source_observations AS o
        JOIN core_ingestion_results AS i
            ON i.observation_id = o.observation_id AND i.status = 'succeeded'
        LEFT JOIN core_signal_events AS se
            ON se.event_id = i.event_id AND se.relationship = 'trigger'
        LEFT JOIN core_signals AS s
            ON s.signal_id = se.signal_id
        LEFT JOIN core_alerts AS a
            ON a.signal_id = s.signal_id
        WHERE o.source_system_id = ?
          AND o.source_connection_id = ?
          AND o.account_external_id = ?
          AND o.economic_inflow_key = ?
        ORDER BY i.created_at ASC
        LIMIT 1
        """,
        (
            observation["source_system_id"],
            observation["source_connection_id"],
            observation["account_external_id"],
            observation["economic_inflow_key"],
        ),
    ).fetchone()
    return dict(row) if row else None


def _normalize_source_observation_payload(
    *,
    source_system_id: str,
    source_connection_id: str,
    account_external_id: str,
    source_transaction_id: str,
    observation_status: str,
    observed_at: str,
    amount_cents: int | None = None,
    currency: str | None = "USD",
    account_name: str | None = None,
    classification: str | None = None,
    classification_confidence: float | None = None,
    effective_date: str | None = None,
    posted_at: str | None = None,
    source_name: str | None = None,
    observation_type: str | None = "financial_inflow",
    economic_inflow_key: str | None = None,
    provider_transaction_id: str | None = None,
    provider_pending_id: str | None = None,
    provider_posted_id: str | None = None,
    source_modified_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required = {
        "source_system_id": source_system_id,
        "source_connection_id": source_connection_id,
        "account_external_id": account_external_id,
        "source_transaction_id": source_transaction_id,
        "observation_status": observation_status,
        "observed_at": observed_at,
    }
    missing = [name for name, value in required.items() if not clean_text(value)]
    if missing:
        raise ValueError(f"missing required source observation fields: {', '.join(missing)}")
    status = clean_text(observation_status).lower()
    if status not in {"pending", "posted", "removed", "unknown"}:
        raise ValueError("observation_status must be pending, posted, removed, or unknown")
    normalized_observed_at = normalize_timestamp(observed_at, "observed_at")
    normalized_posted_at = normalize_timestamp(posted_at, "posted_at") if clean_text(posted_at) else None
    if status == "posted" and not normalized_posted_at:
        normalized_posted_at = normalized_observed_at
    amount_value = None
    if amount_cents is not None:
        try:
            amount_value = int(amount_cents)
        except (TypeError, ValueError) as exc:
            raise ValueError("amount_cents must be an integer") from exc
        if amount_value <= 0:
            raise ValueError("amount_cents must be positive when supplied")
    confidence_value = None
    if classification_confidence is not None:
        try:
            confidence_value = float(classification_confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("classification_confidence must be between 0 and 1") from exc
        if confidence_value < 0 or confidence_value > 1:
            raise ValueError("classification_confidence must be between 0 and 1")
    return {
        "source_system_id": clean_text(source_system_id),
        "source_connection_id": clean_text(source_connection_id),
        "account_external_id": clean_text(account_external_id),
        "source_name": clean_text(source_name) or clean_text(source_system_id),
        "observation_type": clean_text(observation_type) or "financial_inflow",
        "source_transaction_id": clean_text(source_transaction_id),
        "provider_transaction_id": clean_text(provider_transaction_id) or None,
        "provider_pending_id": clean_text(provider_pending_id) or None,
        "provider_posted_id": clean_text(provider_posted_id) or None,
        "economic_inflow_key": clean_text(economic_inflow_key) or clean_text(source_transaction_id),
        "observation_status": status,
        "amount_cents": amount_value,
        "currency": clean_text(currency or "USD").upper(),
        "account_name": clean_text(account_name) or None,
        "classification": clean_text(classification).lower() or None,
        "classification_confidence": confidence_value,
        "observed_at": normalized_observed_at,
        "effective_date": clean_text(effective_date) or None,
        "posted_at": normalized_posted_at,
        "source_modified_at": normalize_timestamp(source_modified_at, "source_modified_at") if clean_text(source_modified_at) else None,
        "metadata": {
            **(metadata if isinstance(metadata, dict) else {}),
            "recorded_by": "mcp_source_observation_tool",
            "caller_contract": "chatgpt_finances_observation_manual_or_supported_automation",
            "access_gap": "Local Python process does not have direct bank or ChatGPT Finances API access.",
        },
    }


def _record_financial_source_observation(
    db_path: Path,
    *,
    source_system_id: str,
    source_connection_id: str,
    account_external_id: str,
    source_transaction_id: str,
    observation_status: str,
    observed_at: str,
    amount_cents: int | None = None,
    currency: str | None = "USD",
    account_name: str | None = None,
    classification: str | None = None,
    classification_confidence: float | None = None,
    effective_date: str | None = None,
    posted_at: str | None = None,
    source_name: str | None = None,
    observation_type: str | None = "financial_inflow",
    economic_inflow_key: str | None = None,
    provider_transaction_id: str | None = None,
    provider_pending_id: str | None = None,
    provider_posted_id: str | None = None,
    source_modified_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    confirmed: bool | None = None,
) -> dict[str, Any]:
    if not configured_api_key():
        return _fail("INFO_ANALYZER_API_KEY is not configured for source observation write tools")
    if not confirmed:
        return _fail("confirmation required")
    try:
        payload = _normalize_source_observation_payload(
            source_system_id=source_system_id,
            source_connection_id=source_connection_id,
            account_external_id=account_external_id,
            source_transaction_id=source_transaction_id,
            observation_status=observation_status,
            observed_at=observed_at,
            amount_cents=amount_cents,
            currency=currency,
            account_name=account_name,
            classification=classification,
            classification_confidence=classification_confidence,
            effective_date=effective_date,
            posted_at=posted_at,
            source_name=source_name,
            observation_type=observation_type,
            economic_inflow_key=economic_inflow_key,
            provider_transaction_id=provider_transaction_id,
            provider_pending_id=provider_pending_id,
            provider_posted_id=provider_posted_id,
            source_modified_at=source_modified_at,
            metadata=metadata,
        )
        with connect(db_path) as conn:
            result = record_source_observation(conn, payload, worker_id="mcp-source-observer")
            observation = result["observation"]
            effects: list[dict[str, Any]] = []
            event_id = None
            signal_id = None
            alert_id = None
            ingestion_result = None
            if observation["observation_status"] == "posted":
                existing = _existing_ingestion_for_economic_inflow(conn, observation)
                if existing:
                    event_id = existing.get("event_id")
                    signal_id = existing.get("signal_id")
                    alert_id = existing.get("alert_id")
                    effects.append(
                        {
                            "type": "economic_inflow_already_ingested",
                            "event_id": event_id,
                            "signal_id": signal_id,
                            "alert_id": alert_id,
                            "source_observation_id": existing.get("observation_id"),
                        }
                    )
                else:
                    ingestion_result = ingest_observation(
                        conn,
                        observation["observation_id"],
                        worker_id="mcp-ingestion-worker",
                    )
                    event_id = ingestion_result.get("event_id")
                    effects.extend(ingestion_result.get("effects") or [])
                    signal_id = clean_text(next((effect.get("signal_id") for effect in effects if effect.get("signal_id")), ""))
                    alert_id = clean_text(next((effect.get("alert_id") for effect in effects if effect.get("alert_id")), ""))
            conn.commit()
        return _success(
            observation=observation,
            created=result.get("created", False),
            updated=result.get("updated", False),
            event_id=event_id,
            signal_id=signal_id,
            alert_id=alert_id,
            ingestion=ingestion_result,
            effects=effects,
            pending_without_event=observation["observation_status"] == "pending",
            caller_contract={
                "supported_caller": "ChatGPT or trusted automation supplying observed financial source fields through MCP",
                "local_bank_access": "not_available",
                "notes": "The local process records observations it is given; it does not fetch bank data itself.",
            },
        )
    except (KeyError, ValueError, RuntimeError, InnbankProcessingError) as exc:
        return _fail(str(exc))


def _get_source_observation_status(
    db_path: Path,
    *,
    observation_id: str | None = None,
    source_system_id: str | None = None,
    source_connection_id: str | None = None,
    account_external_id: str | None = None,
    source_transaction_id: str | None = None,
    economic_inflow_key: str | None = None,
    limit: int | None = 10,
) -> dict[str, Any]:
    limit_value = max(1, min(int(limit or 10), 50))
    where: list[str] = []
    args: list[Any] = []
    if clean_text(observation_id):
        where.append("o.observation_id = ?")
        args.append(clean_text(observation_id))
    else:
        filters = {
            "o.source_system_id": source_system_id,
            "o.source_connection_id": source_connection_id,
            "o.account_external_id": account_external_id,
            "o.source_transaction_id": source_transaction_id,
            "o.economic_inflow_key": economic_inflow_key,
        }
        for column, value in filters.items():
            if clean_text(value):
                where.append(f"{column} = ?")
                args.append(clean_text(value))
    if not where:
        return _fail("provide observation_id or at least one source identity filter")
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT o.*
            FROM core_source_observations AS o
            WHERE {' AND '.join(where)}
            ORDER BY o.created_at DESC, o.observation_id ASC
            LIMIT ?
            """,
            (*args, limit_value),
        ).fetchall()
        observations = [_row_to_source_observation(row) for row in rows]
        for observation in observations:
            ingestion_rows = conn.execute(
                """
                SELECT ingestion_result_id, operation_id, attempt_id, event_id, status, created_at
                FROM core_ingestion_results
                WHERE observation_id=?
                ORDER BY created_at ASC
                """,
                (observation["observation_id"],),
            ).fetchall()
            observation["ingestion_results"] = [dict(row) for row in ingestion_rows]
            observation["event_id"] = observation["ingestion_results"][0]["event_id"] if observation["ingestion_results"] else None
            observation["status_explanation"] = (
                "pending observation recorded without settled event"
                if observation["observation_status"] == "pending" and not observation["event_id"]
                else "posted observation linked to event" if observation["event_id"]
                else "observation recorded; ingestion not recorded"
            )
    return _success(
        status="ok" if observations else "empty",
        observations=observations,
        coverage={
            "tables": ["core_source_observations", "core_ingestion_results", "core_events"],
            "limitations": ["This read reports recorded observations only; it does not poll bank or Finances sources."],
        },
    )


def _prepare_payday_case(
    db_path: Path,
    *,
    paycheck_amount: Any,
    posted_at: str,
    employer_reference: str,
    receiving_account: str,
    starting_balance: Any,
    operating_floor: Any,
    protected_holds: list[dict[str, Any]] | None = None,
    proposed_routes: list[dict[str, Any]] | None = None,
    possible_matching_transfer_evidence: dict[str, Any] | None = None,
    currency: str | None = "USD",
    source_transaction_id: str | None = None,
    dedupe_key: str | None = None,
    confirmed: bool | None = None,
) -> dict[str, Any]:
    prepared = _build_payday_case_inputs(
        paycheck_amount=paycheck_amount,
        posted_at=posted_at,
        employer_reference=employer_reference,
        receiving_account=receiving_account,
        starting_balance=starting_balance,
        operating_floor=operating_floor,
        protected_holds=protected_holds,
        proposed_routes=proposed_routes,
        possible_matching_transfer_evidence=possible_matching_transfer_evidence,
        currency=currency,
        source_transaction_id=source_transaction_id,
        dedupe_key=dedupe_key,
    )
    if not confirmed:
        return _success(confirmed=False, preview=prepared["preview"], writes=[])
    if not configured_api_key():
        return _fail("INFO_ANALYZER_API_KEY is not configured for payday write tools")

    with connect(db_path) as conn:
        existing = _existing_case_for_dedupe(conn, prepared["event_payload"]["dedupe_key"])
    if existing and existing.get("plan_id"):
        return _success(
            confirmed=True,
            idempotent=True,
            preview=prepared["preview"],
            event_id=existing["event_id"],
            signal_id=existing["signal_id"],
            alert_id=existing["alert_id"],
            plan_id=existing["plan_id"],
            case=existing["case"],
        )

    with connect(db_path) as conn:
        try:
            event_result = core_create_event(conn, prepared["event_payload"])
            dispatch_result = EventDispatcher().dispatch(
                conn,
                event_result["event"],
                deduplicated=not event_result["created"],
            )
            event_result["event"]["processing_status"] = dispatch_result.get(
                "event_status",
                event_result["event"].get("processing_status"),
            )
            conn.commit()
        except InnbankProcessingError as exc:
            conn.commit()
            return _fail(str(exc), effects=exc.effects)
    effects = dispatch_result.get("effects", [])
    signal_id = clean_text(next((effect.get("signal_id") for effect in effects if effect.get("signal_id")), ""))
    alert_id = clean_text(next((effect.get("alert_id") for effect in effects if effect.get("alert_id")), ""))
    if not signal_id:
        with connect(db_path) as conn:
            existing = _existing_case_for_dedupe(conn, prepared["event_payload"]["dedupe_key"])
            signal_id = clean_text((existing or {}).get("signal_id"))
            alert_id = clean_text((existing or {}).get("alert_id"))
    if not signal_id:
        return _fail("payday event did not produce a signal", event=event_result["event"], effects=effects)

    plan_payload = dict(prepared["plan_payload"])
    plan_payload["signal_id"] = signal_id
    plan_result = create_allocation_plan(str(db_path), plan_payload)
    plan_id = plan_result["plan"]["plan_id"]
    with connect(db_path) as conn:
        case = _resolve_case(conn, alert_id=None, signal_id=None, plan_id=plan_id)
    return _success(
        confirmed=True,
        idempotent=not event_result["created"] or not plan_result.get("created", False),
        preview=prepared["preview"],
        event_id=event_result["event"]["event_id"],
        signal_id=signal_id,
        alert_id=alert_id or case["case_id"].get("alert_id"),
        plan_id=plan_id,
        case=case,
        effects=effects,
    )


def build_server(database_path: str | Path | None = None) -> Any:
    if not MCP_AVAILABLE:
        raise RuntimeError("mcp is not installed; install the official MCP SDK first")
    db_path = resolve_database_path(database_path)
    initialize_core_migrations(db_path)
    server = MCPServer(
        name="info-analyzer-payday-bridge",
        title="Info Analyzer Payday Bridge",
        description="Read and update INNBANK payday context through chat tools.",
    )

    @server.tool(
        name="prepare_payday_case",
        annotations=_tool_annotations(read_only=False),
        structured_output=True,
    )
    def prepare_payday_case(
        paycheck_amount: str,
        posted_at: str,
        employer_reference: str,
        receiving_account: str,
        starting_balance: str,
        operating_floor: str,
        protected_holds: list[dict[str, Any]] | None = None,
        proposed_routes: list[dict[str, Any]] | None = None,
        possible_matching_transfer_evidence: dict[str, Any] | None = None,
        currency: str | None = "USD",
        source_transaction_id: str | None = None,
        dedupe_key: str | None = None,
        confirmed: bool | None = None,
    ) -> dict[str, Any]:
        try:
            return _prepare_payday_case(
                db_path,
                paycheck_amount=paycheck_amount,
                posted_at=posted_at,
                employer_reference=employer_reference,
                receiving_account=receiving_account,
                starting_balance=starting_balance,
                operating_floor=operating_floor,
                protected_holds=protected_holds,
                proposed_routes=proposed_routes,
                possible_matching_transfer_evidence=possible_matching_transfer_evidence,
                currency=currency,
                source_transaction_id=source_transaction_id,
                dedupe_key=dedupe_key,
                confirmed=confirmed,
            )
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))

    @server.tool(
        name="get_payday_case",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def get_payday_case(
        alert_id: str | None = None,
        signal_id: str | None = None,
        plan_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            with connect(db_path) as conn:
                case = _resolve_case(conn, alert_id=alert_id, signal_id=signal_id, plan_id=plan_id)
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))
        return _success(case=case)

    @server.tool(
        name="record_financial_source_observation",
        annotations=_tool_annotations(read_only=False),
        structured_output=True,
    )
    def record_financial_source_observation(
        source_system_id: str,
        source_connection_id: str,
        account_external_id: str,
        source_transaction_id: str,
        observation_status: str,
        observed_at: str,
        amount_cents: int | None = None,
        currency: str | None = "USD",
        account_name: str | None = None,
        classification: str | None = None,
        classification_confidence: float | None = None,
        effective_date: str | None = None,
        posted_at: str | None = None,
        source_name: str | None = None,
        observation_type: str | None = "financial_inflow",
        economic_inflow_key: str | None = None,
        provider_transaction_id: str | None = None,
        provider_pending_id: str | None = None,
        provider_posted_id: str | None = None,
        source_modified_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        confirmed: bool | None = None,
    ) -> dict[str, Any]:
        return _record_financial_source_observation(
            db_path,
            source_system_id=source_system_id,
            source_connection_id=source_connection_id,
            account_external_id=account_external_id,
            source_transaction_id=source_transaction_id,
            observation_status=observation_status,
            observed_at=observed_at,
            amount_cents=amount_cents,
            currency=currency,
            account_name=account_name,
            classification=classification,
            classification_confidence=classification_confidence,
            effective_date=effective_date,
            posted_at=posted_at,
            source_name=source_name,
            observation_type=observation_type,
            economic_inflow_key=economic_inflow_key,
            provider_transaction_id=provider_transaction_id,
            provider_pending_id=provider_pending_id,
            provider_posted_id=provider_posted_id,
            source_modified_at=source_modified_at,
            metadata=metadata,
            confirmed=confirmed,
        )

    @server.tool(
        name="get_source_observation_status",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def get_source_observation_status(
        observation_id: str | None = None,
        source_system_id: str | None = None,
        source_connection_id: str | None = None,
        account_external_id: str | None = None,
        source_transaction_id: str | None = None,
        economic_inflow_key: str | None = None,
        limit: int | None = 10,
    ) -> dict[str, Any]:
        return _get_source_observation_status(
            db_path,
            observation_id=observation_id,
            source_system_id=source_system_id,
            source_connection_id=source_connection_id,
            account_external_id=account_external_id,
            source_transaction_id=source_transaction_id,
            economic_inflow_key=economic_inflow_key,
            limit=limit,
        )

    @server.tool(
        name="ingest_capture",
        annotations=_tool_annotations(read_only=False),
        structured_output=True,
    )
    def ingest_capture(
        source: str,
        raw_text: str,
        captured_at: str,
        request_id: str,
        idempotency_key: str,
        capture_type: str | None = None,
        payload_version: int | None = 1,
        occurred_at: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        author_role: str | None = None,
        confirmed: bool | None = None,
    ) -> dict[str, Any]:
        if not configured_api_key():
            return _fail("INFO_ANALYZER_API_KEY is not configured for capture write tools")
        if not confirmed:
            return _fail("confirmation required")
        try:
            return core_ingest_capture(
                db_path,
                {
                    "capture_type": capture_type,
                    "source": source,
                    "raw_text": raw_text,
                    "captured_at": captured_at,
                    "request_id": request_id,
                    "idempotency_key": idempotency_key,
                    "payload_version": payload_version or 1,
                    "occurred_at": occurred_at,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "correlation_id": correlation_id,
                    "metadata": metadata or {},
                    "author_role": author_role,
                },
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            return _fail(str(exc))

    @server.tool(
        name="get_day_progress",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def get_day_progress(local_date: str | None = None) -> dict[str, Any]:
        try:
            return shared_get_day_progress(db_path, local_date=local_date)
        except Exception as exc:
            return _fail(str(exc))

    @server.tool(
        name="list_captures",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def list_captures(
        conversation_id: str | None = None,
        local_date: str | None = None,
        capture_type: str | None = None,
        project: str | None = None,
        domain: str | None = None,
        author_role: str | None = None,
        include_raw_text: bool | None = True,
        limit: int | None = 20,
        offset: int | None = 0,
    ) -> dict[str, Any]:
        try:
            return shared_list_captures(
                db_path,
                conversation_id=conversation_id,
                local_date=local_date,
                capture_type=capture_type,
                project=project,
                domain=domain,
                author_role=author_role,
                include_raw_text=bool(include_raw_text),
                limit=limit or 20,
                offset=offset or 0,
            )
        except Exception as exc:
            return _fail(str(exc))

    @server.tool(
        name="get_system_status",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def get_system_status() -> dict[str, Any]:
        try:
            return shared_get_system_status(db_path)
        except Exception as exc:
            return _fail(str(exc))

    @server.tool(
        name="list_cases",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def list_cases(
        limit: int | None = None,
        cursor: int | None = None,
        system_id: str | None = None,
        include_legacy: bool | None = None,
        legacy_type: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "limit": [str(limit if limit is not None else "")],
            "cursor": [str(cursor if cursor is not None else "0")],
            "system_id": [clean_text(system_id)],
            "include_legacy": ["true" if include_legacy else "false"],
            "legacy_type": [clean_text(legacy_type or "entries")],
            "domain": [clean_text(domain)],
        }
        try:
            return shared_list_cases(db_path, params)
        except Exception as exc:
            return _fail(str(exc))

    @server.tool(
        name="get_case",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def get_case(case_id: str) -> dict[str, Any]:
        try:
            return shared_get_case(db_path, case_id)
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))

    @server.tool(
        name="get_event_trace",
        annotations=_tool_annotations(read_only=True),
        structured_output=True,
    )
    def get_event_trace(event_id: str) -> dict[str, Any]:
        try:
            return shared_get_event_trace(db_path, event_id)
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))

    @server.tool(
        name="save_payday_decision",
        annotations=_tool_annotations(read_only=False),
        structured_output=True,
    )
    def save_payday_decision(
        plan_id: str,
        decision: str | None = None,
        confirmed: bool | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        if not configured_api_key():
            return _fail("INFO_ANALYZER_API_KEY is not configured for payday write tools")
        if not confirmed:
            return _fail("confirmation required")
        try:
            mapped = _map_requested_decision(decision or "")
        except ValueError as exc:
            return _fail(str(exc))
        try:
            with connect(db_path) as conn:
                plan = conn.execute(
                    "SELECT plan_id, latest_response, latest_decision_id, status FROM innbank_allocation_plans WHERE plan_id=?",
                    (clean_text(plan_id),),
                ).fetchone()
                if not plan:
                    return _fail("allocation plan not found")
                plan = dict(plan)
            if plan.get("latest_response") == mapped and plan.get("latest_decision_id"):
                decision_row = _latest_decision_row(str(db_path), clean_text(plan_id))
                bundle = get_allocation_plan(str(db_path), clean_text(plan_id))
                return _success(
                    idempotent=True,
                    requested_decision=clean_text(decision or "").lower(),
                    canonical_response=mapped,
                    decision=decision_row,
                    plan=bundle["plan"],
                    items=bundle["items"],
                    routing_runs=bundle["routing_runs"],
                    routing_items=bundle["routing_items"],
                    actions=bundle["actions"],
                    outcomes=bundle["outcomes"],
                    response_state=_maybe_result_state(clean_text(decision or "").lower()),
                )
            result = respond_to_allocation_plan(
                str(db_path),
                clean_text(plan_id),
                {
                    "response": mapped,
                    "rationale": rationale or "Recorded through payday bridge.",
                    "decided_by": "human",
                },
            )
            if clean_text(decision or "").lower() == "modify" and result.get("decision", {}).get("decision_id"):
                with connect(db_path) as conn:
                    row = conn.execute(
                        "SELECT metadata_json FROM core_decisions WHERE decision_id=?",
                        (result["decision"]["decision_id"],),
                    ).fetchone()
                    metadata = load_json(row["metadata_json"] if row else "{}", {})
                    metadata.update(
                        {
                            "bridge_requested_response": "modify",
                            "bridge_response_state": "pending_manual_routing",
                        }
                    )
                    conn.execute(
                        "UPDATE core_decisions SET metadata_json=? WHERE decision_id=?",
                        (
                            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                            result["decision"]["decision_id"],
                        ),
                    )
                    conn.commit()
                    result["decision"]["metadata_json"] = metadata
            return _success(
                idempotent=False,
                requested_decision=clean_text(decision or "").lower(),
                canonical_response=mapped,
                response_state=_maybe_result_state(clean_text(decision or "").lower()),
                decision=result["decision"],
                plan=result["plan"],
                items=result["items"],
                routing_runs=result["routing_runs"],
                routing_items=result["routing_items"],
                actions=result["actions"],
            )
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))

    @server.tool(
        name="record_manual_routing",
        annotations=_tool_annotations(read_only=False),
        structured_output=True,
    )
    def record_manual_routing(
        plan_id: str,
        items: list[dict[str, Any]] | None = None,
        notes: str | None = None,
        confirmed: bool | None = None,
    ) -> dict[str, Any]:
        if not configured_api_key():
            return _fail("INFO_ANALYZER_API_KEY is not configured for payday write tools")
        if not confirmed:
            return _fail("confirmation required")
        if not isinstance(items, list) or not items:
            return _fail("items must be a non-empty JSON array")
        try:
            with connect(db_path) as conn:
                plan = conn.execute(
                    "SELECT plan_id, latest_response, completed_at, completed_event_id FROM innbank_allocation_plans WHERE plan_id=?",
                    (clean_text(plan_id),),
                ).fetchone()
                if not plan:
                    return _fail("allocation plan not found")
                plan = dict(plan)
                if plan["latest_response"] != "approve":
                    return _fail("allocation plan must be approved before routing")
                existing_rows = conn.execute(
                    """
                    SELECT allocation_item_id, actual_amount_cents, variance_cents, routing_status
                    FROM innbank_routing_items
                    WHERE plan_id=?
                    ORDER BY allocation_item_id ASC
                    """,
                    (clean_text(plan_id),),
                ).fetchall()
            canonical_items = []
            for item in items:
                if not isinstance(item, dict):
                    return _fail("each routing item must be a JSON object")
                allocation_item_id = clean_text(item.get("allocation_item_id"))
                if not allocation_item_id:
                    return _fail("allocation_item_id is required")
                canonical_items.append(
                    {
                        "allocation_item_id": allocation_item_id,
                        "actual_amount_cents": item.get("actual_amount_cents", item.get("amount_cents", item.get("actual_amount"))),
                        "routing_status": item.get("routing_status"),
                        "notes": clean_text(item.get("notes")) or None,
                    }
                )
            normalized_existing = [
                {
                    "allocation_item_id": clean_text(row["allocation_item_id"]),
                    "actual_amount_cents": row["actual_amount_cents"],
                    "variance_cents": row["variance_cents"],
                    "routing_status": row["routing_status"],
                }
                for row in existing_rows
            ]
            idempotent = False
            if len(normalized_existing) == len(canonical_items) and normalized_existing:
                expected_pairs = {
                    (
                        row["allocation_item_id"],
                        int(row["actual_amount_cents"]),
                    )
                    for row in normalized_existing
                }
                observed_pairs = {
                    (
                        clean_text(item["allocation_item_id"]),
                        int(
                            item["actual_amount_cents"]
                            if str(item["actual_amount_cents"]) not in {"None", "", "null"}
                            else 0
                        ),
                    )
                    for item in canonical_items
                }
                if expected_pairs == observed_pairs:
                    idempotent = True
            if idempotent:
                bundle = get_allocation_plan(str(db_path), clean_text(plan_id))
                return _success(
                    idempotent=True,
                    completed=bool((bundle.get("plan") or {}).get("completed_at")),
                    plan=bundle["plan"],
                    items=bundle["items"],
                    routing_runs=bundle["routing_runs"],
                    routing_items=bundle["routing_items"],
                    actions=bundle["actions"],
                    outcomes=bundle["outcomes"],
                )
            result = record_allocation_routing(
                str(db_path),
                clean_text(plan_id),
                {
                    "notes": notes,
                    "items": items,
                },
            )
            return _success(
                idempotent=False,
                completed=result["completed"],
                plan=result["plan"]["plan"],
                items=result["plan"]["items"],
                routing_runs=result["plan"]["routing_runs"],
                routing_items=result["plan"]["routing_items"],
                actions=result["plan"]["actions"],
                outcomes=result["plan"]["outcomes"],
                routing_run=result["routing_run"],
                routing_completed_event=result["routing_completed_event"],
            )
        except (KeyError, ValueError) as exc:
            return _fail(str(exc))

    return server


def run_server(host: str, port: int, database_path: str | Path | None = None) -> None:
    if not MCP_AVAILABLE:
        raise RuntimeError("mcp is not installed; install the official MCP SDK first")
    server = build_server(database_path=database_path)
    asyncio.run(
        server.run_streamable_http_async(
            host=host,
            port=port,
            streamable_http_path="/mcp",
            stateless_http=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Info Analyzer payday MCP bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database-path", default=None)
    args = parser.parse_args(argv)
    run_server(args.host, args.port, args.database_path)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
