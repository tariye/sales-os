"""INNBANK allocation plan and manual routing workflow."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from core_database import connect
from core_events import create_event as core_create_event


PLAN_STATUSES = {"proposed", "decided", "completed", "rejected"}
ITEM_TYPES = {"allocation", "unallocated"}
ITEM_STATES = {"proposed", "decided", "routed", "failed"}
ROUTING_STATUSES = {"partial", "completed", "failed"}
PLAN_RESPONSES = {"approve", "hold", "defer", "reject"}
ALLOCATION_ACTION_PREFIX = "innbank_allocation_manual_route"
ROUTING_EVENT_TYPE = "routing_completed"


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


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


def money_to_cents(value: Any, field_name: str, *, allow_zero: bool = True) -> int:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a whole number of cents") from exc
    if not amount.is_finite():
        raise ValueError(f"{field_name} must be a whole number of cents")
    if amount != amount.to_integral_value():
        raise ValueError(f"{field_name} must be a whole number of cents")
    cents = int(amount)
    if cents < 0 or (cents == 0 and not allow_zero):
        raise ValueError(f"{field_name} must be a non-negative whole number of cents")
    return cents


def amount_to_cents(value: Any, field_name: str) -> int:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a valid money amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field_name} must be a valid money amount")
    quantized = amount.quantize(Decimal("0.01"))
    if quantized != amount:
        raise ValueError(f"{field_name} must have at most two decimal places")
    return int(quantized * 100)


def cents_to_money(cents: int, currency: str) -> str:
    value = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    currency = clean_text(currency or "USD").upper()
    if currency == "USD":
        return f"${value:,.2f}"
    return f"{value:,.2f} {currency}"


def _plan_row_to_dict(row) -> dict[str, Any]:
    plan = dict(row)
    plan["metadata"] = load_json(plan.pop("metadata_json", "{}"), {})
    plan["paycheck_amount"] = cents_to_money(plan["paycheck_amount_cents"], plan["currency"])
    return plan


def _item_row_to_dict(row) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = load_json(item.pop("metadata_json", "{}"), {})
    item["proposed_amount"] = cents_to_money(item["proposed_amount_cents"], item["currency"])
    item["state"] = clean_text(item["state"])
    item["routing_status"] = clean_text(item.get("routing_status")) or None
    item["routed_at"] = item.get("routed_at")
    if item.get("actual_amount_cents") is not None:
        item["actual_amount"] = cents_to_money(item["actual_amount_cents"], item["currency"])
    else:
        item["actual_amount"] = None
    if item.get("variance_cents") is not None:
        item["variance"] = cents_to_money(abs(item["variance_cents"]), item["currency"])
        item["variance_sign"] = "+" if item["variance_cents"] >= 0 else "-"
    else:
        item["variance"] = None
        item["variance_sign"] = None
    return item


def _routing_run_row_to_dict(row) -> dict[str, Any]:
    run = dict(row)
    run["notes"] = clean_text(run.get("notes"))
    return run


def _routing_item_row_to_dict(row) -> dict[str, Any]:
    routing = dict(row)
    routing["notes"] = clean_text(routing.get("notes"))
    routing["outcome"] = load_json(routing.pop("outcome_json", None), None)
    return routing


def _action_row_to_dict(row) -> dict[str, Any]:
    action = dict(row)
    action["metadata"] = load_json(action.pop("metadata_json", "{}"), {})
    return action


def _outcome_row_to_dict(row) -> dict[str, Any]:
    outcome = dict(row)
    outcome["measurement"] = load_json(outcome.pop("measurement_json", "{}"), {})
    return outcome


def _fetch_signal_context(conn, signal_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            s.*,
            e.event_id AS source_event_id,
            e.event_type AS source_event_type,
            e.payload_json AS source_event_payload_json,
            e.priority AS event_priority,
            e.confidence AS event_confidence
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


def _fetch_existing_plan(conn, signal_id: str):
    return conn.execute(
        "SELECT * FROM innbank_allocation_plans WHERE signal_id=?",
        (signal_id,),
    ).fetchone()


def _validate_plan_items(items_payload: Any, paycheck_amount_cents: int) -> list[dict[str, Any]]:
    if not isinstance(items_payload, list) or not items_payload:
        raise ValueError("items must be a non-empty JSON array")
    parsed: list[dict[str, Any]] = []
    total = 0
    has_unallocated = False
    has_positive_allocation = False
    for index, raw_item in enumerate(items_payload):
        if not isinstance(raw_item, dict):
            raise ValueError("each item must be a JSON object")
        item_type = clean_text(raw_item.get("item_type") or "allocation").lower()
        if item_type not in ITEM_TYPES:
            raise ValueError("item_type must be allocation or unallocated")
        label = clean_text(raw_item.get("label"))
        if not label:
            raise ValueError(f"items[{index}].label is required")
        proposed = money_to_cents(
            raw_item.get("proposed_amount_cents", raw_item.get("amount_cents", raw_item.get("amount"))),
            f"items[{index}].proposed_amount_cents",
        )
        goal_id = clean_text(raw_item.get("goal_id")) or None
        metadata = raw_item.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError(f"items[{index}].metadata must be a JSON object")
        parsed.append(
            {
                "item_type": item_type,
                "label": label,
                "proposed_amount_cents": proposed,
                "goal_id": goal_id,
                "notes": clean_text(raw_item.get("notes")) or None,
                "metadata": metadata,
            }
        )
        total += proposed
        has_unallocated = has_unallocated or item_type == "unallocated"
        has_positive_allocation = has_positive_allocation or (item_type == "allocation" and proposed > 0)
    if not has_unallocated:
        raise ValueError("allocation plans must include an unallocated item")
    if not has_positive_allocation:
        raise ValueError("allocation plans must include at least one nonzero allocation item")
    if total != paycheck_amount_cents:
        raise ValueError("allocation totals must exactly equal the paycheck amount")
    return parsed


def _serialize_plan(conn, plan_id: str) -> dict[str, Any]:
    plan_row = conn.execute(
        "SELECT * FROM innbank_allocation_plans WHERE plan_id=?",
        (plan_id,),
    ).fetchone()
    if not plan_row:
        raise KeyError("allocation plan not found")
    plan = _plan_row_to_dict(plan_row)
    items = [
        _item_row_to_dict(row)
        for row in conn.execute(
            """
            SELECT ai.*, s.title AS signal_title, s.summary AS signal_summary
                   , p.currency
                   , ri.actual_amount_cents
                   , ri.variance_cents
                   , ri.routing_status
                   , ri.completed_at AS routed_at
            FROM innbank_allocation_items AS ai
            JOIN innbank_allocation_plans AS p ON p.plan_id = ai.plan_id
            JOIN core_signals AS s ON s.signal_id = p.signal_id
            LEFT JOIN innbank_routing_items AS ri ON ri.allocation_item_id = ai.allocation_item_id
            WHERE ai.plan_id = ?
            ORDER BY ai.order_index ASC, ai.created_at ASC
            """,
            (plan_id,),
        ).fetchall()
    ]
    routing_runs = [
        _routing_run_row_to_dict(row)
        for row in conn.execute(
            "SELECT * FROM innbank_routing_runs WHERE plan_id=? ORDER BY created_at ASC",
            (plan_id,),
        ).fetchall()
    ]
    routing_items = []
    for row in conn.execute(
        """
        SELECT
            ri.*,
            o.outcome_id AS outcome_id_alias,
            o.outcome_type,
            o.result_status,
            o.expected_result,
            o.actual_result,
            o.measurement_json,
            o.observed_at AS outcome_observed_at,
            o.notes AS outcome_notes
        FROM innbank_routing_items AS ri
        LEFT JOIN core_outcomes AS o ON o.outcome_id = ri.outcome_id
        WHERE ri.plan_id = ?
        ORDER BY ri.created_at ASC
        """,
        (plan_id,),
    ).fetchall():
        routing_item = _routing_item_row_to_dict(row)
        routing_item["outcome"] = {
            "outcome_id": routing_item.pop("outcome_id_alias", None),
            "outcome_type": routing_item.pop("outcome_type", None),
            "result_status": routing_item.pop("result_status", None),
            "expected_result": routing_item.pop("expected_result", None),
            "actual_result": routing_item.pop("actual_result", None),
            "measurement": load_json(routing_item.pop("measurement_json", "{}"), {}),
            "observed_at": routing_item.pop("outcome_observed_at", None),
            "notes": routing_item.pop("outcome_notes", None),
        }
        routing_items.append(routing_item)
    actions = [
        _action_row_to_dict(row)
        for row in conn.execute(
            """
            SELECT a.*
            FROM core_actions AS a
            JOIN innbank_allocation_items AS ai ON ai.core_action_id = a.action_id
            WHERE ai.plan_id = ?
            ORDER BY ai.order_index ASC
            """,
            (plan_id,),
        ).fetchall()
    ]
    outcomes = [
        _outcome_row_to_dict(row)
        for row in conn.execute(
            """
            SELECT o.*
            FROM core_outcomes AS o
            WHERE o.action_id IN (
                SELECT core_action_id
                FROM innbank_allocation_items
                WHERE plan_id = ? AND core_action_id IS NOT NULL
            )
            ORDER BY o.created_at ASC
            """,
            (plan_id,),
        ).fetchall()
    ]
    return {
        "plan": plan,
        "items": items,
        "routing_runs": routing_runs,
        "routing_items": routing_items,
        "actions": actions,
        "outcomes": outcomes,
    }


def _insert_plan(conn, signal: dict[str, Any], items: list[dict[str, Any]], payload: dict[str, Any]) -> str:
    plan_id = make_id("IPL")
    metadata = {
        "signal_id": signal["signal_id"],
        "source_event_id": signal["source_event_id"],
        "source_system_id": signal["owner_system_id"],
        "paycheck_amount_cents": signal["paycheck_amount_cents"],
    }
    extra_metadata = payload.get("metadata")
    if isinstance(extra_metadata, dict):
        metadata.update(extra_metadata)
    conn.execute(
        """
        INSERT INTO innbank_allocation_plans (
            plan_id, source_system_id, signal_id, source_event_id,
            paycheck_amount_cents, currency, account_name, title, summary,
            rationale, recommended_action, status, latest_response,
            latest_decision_id, latest_decided_at, response_count,
            completed_at, completed_event_id, completed_routing_run_id,
            notes, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', NULL, NULL, NULL, 0,
                  NULL, NULL, NULL, ?, ?, ?, ?)
        """,
        (
            plan_id,
            signal["owner_system_id"],
            signal["signal_id"],
            signal["source_event_id"],
            signal["paycheck_amount_cents"],
            signal["currency"],
            signal["account_name"],
            payload.get("title") or signal["title"],
            payload.get("summary") or signal["summary"],
            payload.get("rationale") or signal.get("rationale"),
            payload.get("recommended_action") or signal.get("recommended_action"),
            clean_text(payload.get("notes")) or None,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            now_utc_iso(),
            now_utc_iso(),
        ),
    )
    for index, item in enumerate(items):
        conn.execute(
            """
            INSERT INTO innbank_allocation_items (
                allocation_item_id, plan_id, item_type, label,
                proposed_amount_cents, goal_id, core_action_id, state,
                order_index, decided_at, routed_at, notes, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'proposed', ?, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                make_id("ALI"),
                plan_id,
                item["item_type"],
                item["label"],
                item["proposed_amount_cents"],
                item["goal_id"],
                index,
                item["notes"],
                json.dumps(item["metadata"], ensure_ascii=False, sort_keys=True),
                now_utc_iso(),
                now_utc_iso(),
            ),
        )
    return plan_id


def create_allocation_plan(database_path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    signal_id = clean_text(payload.get("signal_id"))
    if not signal_id:
        raise ValueError("signal_id is required")
    with connect(database_path) as conn:
        existing = _fetch_existing_plan(conn, signal_id)
        if existing:
            return {"created": False, **_serialize_plan(conn, existing["plan_id"])}
        signal = _fetch_signal_context(conn, signal_id)
        if signal["signal_type"] != "paycheck_received":
            raise ValueError("allocation plans must reference a paycheck_received signal")
        if signal["owner_system_id"] != "sys_innbank":
            raise ValueError("allocation plans must reference an INNBANK signal")
        paycheck_amount_cents = amount_to_cents(signal["source_event_payload"].get("amount"), "paycheck amount")
        currency = clean_text(
            signal["source_event_payload"].get("currency")
            or signal["metadata"].get("currency")
            or "USD"
        ).upper()
        account_name = clean_text(
            signal["source_event_payload"].get("account_name")
            or signal["metadata"].get("account_name")
            or "connected account"
        )
        items_payload = payload.get("items")
        items = _validate_plan_items(items_payload, paycheck_amount_cents)
        plan_id = _insert_plan(
            conn,
            {
                **signal,
                "paycheck_amount_cents": paycheck_amount_cents,
                "currency": currency,
                "account_name": account_name,
            },
            items,
            payload,
        )
        conn.commit()
        return {"created": True, **_serialize_plan(conn, plan_id)}


def get_allocation_plan(database_path, plan_id: str) -> dict[str, Any]:
    with connect(database_path) as conn:
        return _serialize_plan(conn, clean_text(plan_id))


def _require_plan(conn, plan_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT p.*, s.title AS signal_title, s.summary AS signal_summary, s.rationale AS signal_rationale,
               s.recommended_action AS signal_recommended_action, s.actionability_score,
               e.payload_json AS source_event_payload_json
        FROM innbank_allocation_plans AS p
        JOIN core_signals AS s ON s.signal_id = p.signal_id
        JOIN core_events AS e ON e.event_id = p.source_event_id
        WHERE p.plan_id = ?
        """,
        (plan_id,),
    ).fetchone()
    if not row:
        raise KeyError("allocation plan not found")
    plan = dict(row)
    plan["metadata"] = load_json(plan.pop("metadata_json", "{}"), {})
    plan["source_event_payload"] = load_json(plan.pop("source_event_payload_json", "{}"), {})
    return plan


def _plan_items(conn, plan_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ai.*, p.currency
        FROM innbank_allocation_items AS ai
        JOIN innbank_allocation_plans AS p ON p.plan_id = ai.plan_id
        WHERE ai.plan_id = ?
        ORDER BY ai.order_index ASC, ai.created_at ASC
        """,
        (plan_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _record_plan_decision(conn, plan: dict[str, Any], response: str, payload: dict[str, Any]) -> dict[str, Any]:
    decision_id = make_id("DEC")
    rationale = clean_text(payload.get("rationale") or payload.get("note") or plan.get("rationale"))
    if not rationale:
        rationale = plan.get("rationale") or plan.get("summary")
    decision = {
        "decision_id": decision_id,
        "signal_id": plan["signal_id"],
        "goal_id": None,
        "decision_type": {
            "approve": "approve",
            "hold": "hold",
            "defer": "defer",
            "reject": "reject",
        }[response],
        "selected_option": response,
        "rationale": rationale or "",
        "decided_by": clean_text(payload.get("decided_by") or "human") or "human",
        "metadata_json": {
            "plan_id": plan["plan_id"],
            "signal_id": plan["signal_id"],
            "source_event_id": plan["source_event_id"],
            "source_system_id": plan["source_system_id"],
            "response": response,
            "paycheck_amount_cents": plan["paycheck_amount_cents"],
        },
    }
    conn.execute(
        """
        INSERT INTO core_decisions (
            decision_id, signal_id, goal_id, decision_type, selected_option,
            rationale, decided_by, supersedes_decision_id, decided_at,
            metadata_json, created_at
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            decision["decision_id"],
            decision["signal_id"],
            decision["decision_type"],
            decision["selected_option"],
            decision["rationale"],
            decision["decided_by"],
            now_utc_iso(),
            json.dumps(decision["metadata_json"], ensure_ascii=False, sort_keys=True),
            now_utc_iso(),
        ),
    )
    return decision


def _create_or_update_actions(conn, plan: dict[str, Any], decision_id: str) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    items = _plan_items(conn, plan["plan_id"])
    now = now_utc_iso()
    for item in items:
        if item["item_type"] != "allocation" or int(item["proposed_amount_cents"]) <= 0:
            conn.execute(
                "UPDATE innbank_allocation_items SET state='decided', decided_at=?, updated_at=? WHERE allocation_item_id=?",
                (now, now, item["allocation_item_id"]),
            )
            continue
        existing = conn.execute(
            """
            SELECT action_id
            FROM core_actions
            WHERE json_extract(metadata_json, '$.allocation_item_id') = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (item["allocation_item_id"],),
        ).fetchone()
        if existing:
            action = conn.execute(
                "SELECT * FROM core_actions WHERE action_id=?",
                (existing["action_id"],),
            ).fetchone()
            created.append(_action_row_to_dict(action))
            conn.execute(
                """
                UPDATE innbank_allocation_items
                SET state='decided', decided_at=?, core_action_id=COALESCE(core_action_id, ?), updated_at=?
                WHERE allocation_item_id=?
                """,
                (now, existing["action_id"], now, item["allocation_item_id"]),
            )
            continue
        action_id = make_id("ACT")
        title = f"Route {cents_to_money(item['proposed_amount_cents'], plan['currency'])} to {item['label']}"
        details = item["notes"] or plan.get("notes") or plan["summary"]
        metadata = {
            "plan_id": plan["plan_id"],
            "signal_id": plan["signal_id"],
            "source_event_id": plan["source_event_id"],
            "allocation_item_id": item["allocation_item_id"],
            "proposed_amount_cents": int(item["proposed_amount_cents"]),
            "currency": plan["currency"],
            "response_decision_id": decision_id,
        }
        conn.execute(
            """
            INSERT INTO core_actions (
                action_id, decision_id, owner_system_id, goal_id, action_type,
                title, details, status, execution_mode, assigned_to, due_at,
                started_at, completed_at, external_ref, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', 'manual', 'user',
                      NULL, NULL, NULL, NULL, ?, ?, ?)
            """,
            (
                action_id,
                decision_id,
                plan["source_system_id"],
                item["goal_id"],
                ALLOCATION_ACTION_PREFIX,
                title,
                details,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE innbank_allocation_items
            SET state='decided', decided_at=?, core_action_id=?, updated_at=?
            WHERE allocation_item_id=?
            """,
            (now, action_id, now, item["allocation_item_id"]),
        )
        created.append(_action_row_to_dict(conn.execute("SELECT * FROM core_actions WHERE action_id=?", (action_id,)).fetchone()))
    return created


def respond_to_allocation_plan(database_path, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    response = clean_text(payload.get("response") or payload.get("action") or payload.get("status")).lower()
    if response not in PLAN_RESPONSES:
        raise ValueError("response must be approve, hold, defer, or reject")
    with connect(database_path) as conn:
        plan = _require_plan(conn, clean_text(plan_id))
        if plan["status"] == "completed":
            raise ValueError("allocation plan is already completed")
        decision = _record_plan_decision(conn, plan, response, payload)
        now = now_utc_iso()
        conn.execute(
            """
            UPDATE innbank_allocation_plans
            SET latest_response=?, latest_decision_id=?, latest_decided_at=?,
                response_count=response_count + 1,
                status=?, updated_at=?
            WHERE plan_id=?
            """,
            (
                response,
                decision["decision_id"],
                now,
                "rejected" if response == "reject" else "decided",
                now,
                plan["plan_id"],
            ),
        )
        created_actions: list[dict[str, Any]] = []
        if response == "approve":
            created_actions = _create_or_update_actions(conn, plan, decision["decision_id"])
        elif response in {"hold", "defer", "reject"}:
            conn.execute(
                "UPDATE innbank_allocation_items SET state='decided', decided_at=?, updated_at=? WHERE plan_id=?",
                (now, now, plan["plan_id"]),
            )
        if response == "reject":
            conn.commit()
            serialized = _serialize_plan(conn, plan["plan_id"])
            return {
                "plan": serialized["plan"],
                "items": serialized["items"],
                "routing_runs": serialized["routing_runs"],
                "routing_items": serialized["routing_items"],
                "actions": created_actions,
                "decision": decision,
            }
        conn.commit()
        serialized = _serialize_plan(conn, plan["plan_id"])
        return {
            "plan": serialized["plan"],
            "items": serialized["items"],
            "routing_runs": serialized["routing_runs"],
            "routing_items": serialized["routing_items"],
            "actions": created_actions,
            "decision": decision,
        }


def _routing_item_status(item_type: str, proposed: int, actual: int, explicit_status: str | None = None) -> str:
    if explicit_status:
        explicit_status = clean_text(explicit_status).lower()
        if explicit_status not in ROUTING_STATUSES:
            raise ValueError("routing_status must be partial, completed, or failed")
        return explicit_status
    if actual == proposed:
        return "completed"
    return "partial"


def _record_outcome(conn, plan: dict[str, Any], item: dict[str, Any], routing_row: dict[str, Any]) -> dict[str, Any]:
    outcome_payload = {
        "plan_id": plan["plan_id"],
        "allocation_item_id": item["allocation_item_id"],
        "routing_run_id": routing_row["routing_run_id"],
        "proposed_amount_cents": int(item["proposed_amount_cents"]),
        "actual_amount_cents": int(routing_row["actual_amount_cents"]),
        "variance_cents": int(routing_row["variance_cents"]),
        "routing_status": routing_row["routing_status"],
        "currency": plan["currency"],
        "account_name": plan["account_name"],
    }
    expected = f"Route {cents_to_money(item['proposed_amount_cents'], plan['currency'])} to {item['label']}"
    if routing_row["routing_status"] == "failed":
        actual = f"Routing failed for {item['label']}"
        result_status = "failure"
    elif routing_row["routing_status"] == "partial":
        actual = (
            f"Routed {cents_to_money(routing_row['actual_amount_cents'], plan['currency'])} "
            f"to {item['label']} with a variance of {routing_row['variance_cents']} cents"
        )
        result_status = "partial"
    else:
        actual = (
            f"Routed {cents_to_money(routing_row['actual_amount_cents'], plan['currency'])} "
            f"to {item['label']}"
        )
        result_status = "success"
    if item["item_type"] == "unallocated" and routing_row["routing_status"] != "failed":
        actual = f"Retained {cents_to_money(routing_row['actual_amount_cents'], plan['currency'])} for {item['label']}"
    outcome_id = routing_row.get("outcome_id")
    if outcome_id:
        conn.execute(
            """
            UPDATE core_outcomes
            SET action_id=?, source_event_id=?, outcome_type=?, result_status=?,
                expected_result=?, actual_result=?, measurement_json=?,
                observed_at=?, evaluated_by='human', notes=?, created_at=created_at
            WHERE outcome_id=?
            """,
            (
                item.get("core_action_id"),
                plan["source_event_id"],
                "innbank_allocation_routing",
                result_status,
                expected,
                actual,
                json.dumps(outcome_payload, ensure_ascii=False, sort_keys=True),
                routing_row["completed_at"],
                routing_row.get("notes"),
                outcome_id,
            ),
        )
    else:
        outcome_id = make_id("OUT")
        conn.execute(
            """
            INSERT INTO core_outcomes (
                outcome_id, action_id, source_event_id, outcome_type, result_status,
                expected_result, actual_result, measurement_json, observed_at,
                evaluated_by, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'human', ?, ?)
            """,
            (
                outcome_id,
                item.get("core_action_id"),
                plan["source_event_id"],
                "innbank_allocation_routing",
                result_status,
                expected,
                actual,
                json.dumps(outcome_payload, ensure_ascii=False, sort_keys=True),
                routing_row["completed_at"],
                routing_row.get("notes"),
                now_utc_iso(),
            ),
        )
    conn.execute(
        "UPDATE innbank_routing_items SET outcome_id=?, updated_at=? WHERE routing_item_id=?",
        (outcome_id, now_utc_iso(), routing_row["routing_item_id"]),
    )
    return conn.execute("SELECT * FROM core_outcomes WHERE outcome_id=?", (outcome_id,)).fetchone()


def _all_items_routed(conn, plan_id: str) -> bool:
    total = conn.execute(
        "SELECT COUNT(*) FROM innbank_allocation_items WHERE plan_id=?",
        (plan_id,),
    ).fetchone()[0]
    routed = conn.execute(
        "SELECT COUNT(*) FROM innbank_routing_items WHERE plan_id=?",
        (plan_id,),
    ).fetchone()[0]
    return int(total) > 0 and int(total) == int(routed)


def record_allocation_routing(database_path, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    items_payload = payload.get("items")
    if items_payload is None:
        items_payload = [payload] if payload.get("allocation_item_id") else []
    if not isinstance(items_payload, list) or not items_payload:
        raise ValueError("items must be a non-empty JSON array")
    with connect(database_path) as conn:
        plan = _require_plan(conn, clean_text(plan_id))
        if plan["latest_response"] != "approve":
            raise ValueError("allocation plan must be approved before routing")
        run_id = make_id("RUN")
        run_notes = clean_text(payload.get("notes")) or None
        conn.execute(
            """
            INSERT INTO innbank_routing_runs (
                routing_run_id, plan_id, source_system_id, status, notes,
                completed_at, routing_completed_event_id, created_at, updated_at
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, ?, ?)
            """,
            (
                run_id,
                plan["plan_id"],
                plan["source_system_id"],
                run_notes,
                now_utc_iso(),
                now_utc_iso(),
            ),
        )
        updated_routing_items: list[dict[str, Any]] = []
        for raw_item in items_payload:
            if not isinstance(raw_item, dict):
                raise ValueError("each routing item must be a JSON object")
            allocation_item_id = clean_text(raw_item.get("allocation_item_id"))
            if not allocation_item_id:
                raise ValueError("allocation_item_id is required")
            item = conn.execute(
                """
                SELECT ai.*, p.currency, p.account_name
                FROM innbank_allocation_items AS ai
                JOIN innbank_allocation_plans AS p ON p.plan_id = ai.plan_id
                WHERE ai.allocation_item_id = ? AND ai.plan_id = ?
                """,
                (allocation_item_id, plan["plan_id"]),
            ).fetchone()
            if not item:
                raise KeyError("allocation item not found")
            item = dict(item)
            proposed = int(item["proposed_amount_cents"])
            actual = money_to_cents(
                raw_item.get("actual_amount_cents", raw_item.get("amount_cents", raw_item.get("actual_amount"))),
                "actual_amount_cents",
            )
            explicit_status = clean_text(raw_item.get("routing_status")) or None
            routing_status = _routing_item_status(item["item_type"], proposed, actual, explicit_status)
            completed_at = now_utc_iso()
            variance = actual - proposed
            notes = clean_text(raw_item.get("notes")) or None
            existing = conn.execute(
                "SELECT * FROM innbank_routing_items WHERE allocation_item_id=?",
                (allocation_item_id,),
            ).fetchone()
            outcome_id = None
            if existing:
                outcome_id = existing["outcome_id"]
            routing_item_id = existing["routing_item_id"] if existing else make_id("RIT")
            conn.execute(
                """
                INSERT INTO innbank_routing_items (
                    routing_item_id, routing_run_id, plan_id, allocation_item_id,
                    core_action_id, proposed_amount_cents, actual_amount_cents,
                    variance_cents, routing_status, completed_at, notes, outcome_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(allocation_item_id) DO UPDATE SET
                    routing_run_id=excluded.routing_run_id,
                    plan_id=excluded.plan_id,
                    core_action_id=excluded.core_action_id,
                    proposed_amount_cents=excluded.proposed_amount_cents,
                    actual_amount_cents=excluded.actual_amount_cents,
                    variance_cents=excluded.variance_cents,
                    routing_status=excluded.routing_status,
                    completed_at=excluded.completed_at,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    routing_item_id,
                    run_id,
                    plan["plan_id"],
                    allocation_item_id,
                    item["core_action_id"],
                    proposed,
                    actual,
                    variance,
                    routing_status,
                    completed_at,
                    notes,
                    outcome_id,
                    now_utc_iso(),
                    now_utc_iso(),
                ),
            )
            routing_row = conn.execute(
                "SELECT * FROM innbank_routing_items WHERE allocation_item_id=?",
                (allocation_item_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE innbank_allocation_items
                SET state=?, routed_at=?, updated_at=?
                WHERE allocation_item_id=?
                """,
                ("failed" if routing_status == "failed" else "routed", completed_at, now_utc_iso(), allocation_item_id),
            )
            outcome = _record_outcome(conn, plan, item, dict(routing_row))
            updated_routing_items.append(
                {
                    **_routing_item_row_to_dict(routing_row),
                    "outcome": _outcome_row_to_dict(outcome),
                }
            )
        completed_event = None
        if _all_items_routed(conn, plan["plan_id"]):
            completed_event = conn.execute(
                "SELECT completed_event_id, completed_at FROM innbank_allocation_plans WHERE plan_id=?",
                (plan["plan_id"],),
            ).fetchone()
            if completed_event and completed_event["completed_event_id"]:
                completed_event_row = conn.execute(
                    "SELECT * FROM core_events WHERE event_id=?",
                    (completed_event["completed_event_id"],),
                ).fetchone()
                event_dict = dict(completed_event_row) if completed_event_row else None
                conn.execute(
                    "UPDATE innbank_allocation_plans SET status='completed', completed_at=COALESCE(completed_at, ?), completed_routing_run_id=COALESCE(completed_routing_run_id, ?), updated_at=? WHERE plan_id=?",
                    (now_utc_iso(), run_id, now_utc_iso(), plan["plan_id"]),
                )
                conn.execute(
                    "UPDATE innbank_routing_runs SET status='completed', completed_at=COALESCE(completed_at, ?), routing_completed_event_id=COALESCE(routing_completed_event_id, ?), updated_at=? WHERE routing_run_id=?",
                    (now_utc_iso(), event_dict["event_id"] if event_dict else completed_event["completed_event_id"], now_utc_iso(), run_id),
                )
                conn.commit()
                serialized = _serialize_plan(conn, plan["plan_id"])
                return {
                    "completed": True,
                    "plan": serialized["plan"],
                    "items": serialized["items"],
                    "routing_runs": serialized["routing_runs"],
                    "routing_items": serialized["routing_items"],
                    "routing_run": _routing_run_row_to_dict(
                        conn.execute("SELECT * FROM innbank_routing_runs WHERE routing_run_id=?", (run_id,)).fetchone()
                    ),
                    "routing_items": updated_routing_items,
                    "routing_completed_event": event_dict,
                }
            else:
                dedupe_key = f"innbank-routing-completed:{plan['plan_id']}"
                event_payload = {
                    "plan_id": plan["plan_id"],
                    "signal_id": plan["signal_id"],
                    "source_event_id": plan["source_event_id"],
                    "paycheck_amount_cents": plan["paycheck_amount_cents"],
                    "currency": plan["currency"],
                    "account_name": plan["account_name"],
                    "routing_run_id": run_id,
                }
                event_result = core_create_event(
                    conn,
                    {
                        "source_system_id": plan["source_system_id"],
                        "event_type": ROUTING_EVENT_TYPE,
                        "occurred_at": now_utc_iso(),
                        "dedupe_key": dedupe_key,
                        "priority": "P2",
                        "confidence": 1.0,
                        "payload": event_payload,
                    },
                )
                event_dict = event_result["event"]
                conn.execute(
                    """
                    UPDATE innbank_allocation_plans
                    SET status='completed', completed_at=?, completed_event_id=?, completed_routing_run_id=?, updated_at=?
                    WHERE plan_id=?
                    """,
                    (now_utc_iso(), event_dict["event_id"], run_id, now_utc_iso(), plan["plan_id"]),
                )
                conn.execute(
                    "UPDATE innbank_routing_runs SET status='completed', completed_at=?, routing_completed_event_id=?, updated_at=? WHERE routing_run_id=?",
                    (now_utc_iso(), event_dict["event_id"], now_utc_iso(), run_id),
                )
                conn.commit()
                return {
                    "completed": True,
                    "plan": _serialize_plan(conn, plan["plan_id"]),
                    "routing_run": _routing_run_row_to_dict(
                        conn.execute("SELECT * FROM innbank_routing_runs WHERE routing_run_id=?", (run_id,)).fetchone()
                    ),
                    "routing_items": updated_routing_items,
                    "routing_completed_event": event_dict,
                }
        conn.execute(
            "UPDATE innbank_routing_runs SET updated_at=? WHERE routing_run_id=?",
            (now_utc_iso(), run_id),
        )
        conn.commit()
        serialized = _serialize_plan(conn, plan["plan_id"])
        return {
            "completed": False,
            "plan": serialized["plan"],
            "items": serialized["items"],
            "routing_runs": serialized["routing_runs"],
            "routing_items": serialized["routing_items"],
            "routing_run": _routing_run_row_to_dict(
                conn.execute("SELECT * FROM innbank_routing_runs WHERE routing_run_id=?", (run_id,)).fetchone()
            ),
            "routing_items": updated_routing_items,
            "routing_completed_event": None,
        }
