"""Info Analyzer payday MCP bridge.

This server exposes only the three ChatGPT-facing tools required for the
INNBANK payday bridge milestone:

* get_payday_case
* save_payday_decision
* record_manual_routing

It reads from the canonical SQLite database through the shared connection
helper, keeps API credentials server-side, and reuses the existing INNBANK
allocation and routing services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core_database import connect, resolve_database_path
from core_innbank_routing import (
    cents_to_money,
    get_allocation_plan,
    record_allocation_routing,
    respond_to_allocation_plan,
)
from core_migrations import initialize_core_migrations
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
    transfer_evidence = load_json(plan_metadata.get("transfer_evidence"), {}) if isinstance(plan_metadata, dict) else {}
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
        transfer_probable = transfer_evidence.get("probable_internal_transfer") if isinstance(transfer_evidence, dict) else None
        transfer_confirmed = transfer_evidence.get("confirmed_internal_transfer") if isinstance(transfer_evidence, dict) else None
        transfer_confidence = transfer_evidence.get("classification_confidence") if isinstance(transfer_evidence, dict) else None
        transfer_evidence = {
            "probable_internal_transfer": support["probable_internal_transfer"] if transfer_probable is None else bool(transfer_probable),
            "confirmed_internal_transfer": support["confirmed_internal_transfer"] if transfer_confirmed is None else bool(transfer_confirmed),
            "classification_confidence": support["classification_confidence"] if transfer_confidence is None else float(transfer_confidence),
            "matching_amount_cents": transfer_evidence.get("matching_amount_cents"),
            "payroll_posted_at": transfer_evidence.get("payroll_posted_at"),
            "transfer_posted_at": transfer_evidence.get("transfer_posted_at"),
            "wells_fargo_reference": transfer_evidence.get("wells_fargo_reference"),
            "capital_one_reference": transfer_evidence.get("capital_one_reference"),
            "supporting_evidence": transfer_evidence.get("supporting_evidence") if isinstance(transfer_evidence, dict) else None,
            "user_override": transfer_evidence.get("user_override") if isinstance(transfer_evidence, dict) else None,
        }
    return {
        "amount_cents": amount_cents,
        "amount": cents_to_money(int(amount_cents), "USD") if amount_cents is not None else None,
        "source_system_id": signal["owner_system_id"],
        "signal_id": signal["signal_id"],
        "signal_type": signal["signal_type"],
        "classification": support["classification"],
        "classification_confidence": support["classification_confidence"],
        "probable_internal_transfer": transfer_evidence["probable_internal_transfer"] if allocation_plan else support["probable_internal_transfer"],
        "confirmed_internal_transfer": transfer_evidence["confirmed_internal_transfer"] if allocation_plan else support["confirmed_internal_transfer"],
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


def build_server(database_path: str | Path | None = None) -> Any:
    if not MCP_AVAILABLE:
        raise RuntimeError("mcp is not installed; install the official MCP SDK first")
    db_path = resolve_database_path(database_path)
    initialize_core_migrations(db_path)
    server = MCPServer(
        name="info-analyzer-payday-bridge",
        title="Info Analyzer Payday Bridge",
        description="Read and update INNBANK payday context through three chat tools.",
    )

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
