"""Shared event processors for normalized core event dispatch."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from core_alerts import sync_alert_queue
from home_sentinel import HomeSentinelProcessor, HomeSentinelProcessingError
from module_processors import ModuleProcessingError, ModuleSignalProcessor, SUPPORTED_EVENTS


CONFIRMED_INCOME = {"paycheck", "payroll", "earned_income"}
NON_DEPLOYABLE_INFLOW = {
    "internal_transfer",
    "credit_card_payment",
    "refund",
    "reversal",
    "interest",
}


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def format_money(amount: Decimal, currency: str) -> str:
    currency = currency.upper()
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def parse_amount(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("amount must be a positive number")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("amount must be a positive number") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be a positive number")
    return amount


def parse_confidence(value: Any, default: float = 1.0) -> float:
    if value is None or value == "":
        return default
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return default
    if confidence < 0 or confidence > 1:
        return default
    return confidence


@dataclass
class InnbankProcessingError(ValueError):
    message: str
    effects: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)


class InnBankPaydayProcessor:
    """Interpret INNBANK inflow events into core signals and alerts."""

    def process_event(self, conn, event: dict[str, Any]) -> dict[str, Any]:
        event_id = event["event_id"]
        existing = conn.execute(
            """
            SELECT
                s.signal_id,
                s.signal_type,
                a.alert_id,
                e.processing_status
            FROM core_signal_events AS se
            JOIN core_signals AS s ON s.signal_id = se.signal_id
            LEFT JOIN core_alerts AS a ON a.signal_id = s.signal_id
                AND a.state IN ('queued', 'presented', 'acknowledged', 'snoozed', 'actioned', 'failed')
            JOIN core_events AS e ON e.event_id = se.event_id
            WHERE se.event_id = ? AND se.relationship = 'trigger'
              AND s.owner_system_id = 'sys_innbank'
            ORDER BY s.created_at ASC
            LIMIT 1
            """,
            (event_id,),
        ).fetchone()
        if existing:
            status = clean_text(existing["processing_status"]) or "processed"
            alert_id = clean_text(existing["alert_id"]) or None
            effects = [
                {
                    "type": "innbank_event_already_processed",
                    "event_id": event_id,
                    "signal_id": existing["signal_id"],
                    "signal_type": existing["signal_type"],
                    "alert_id": alert_id,
                }
            ]
            return {"event_status": status, "effects": effects}

        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            raise InnbankProcessingError(
                "financial inflow payload must be a JSON object",
                effects=[{"type": "event_failed", "event_id": event_id, "reason": "payload_invalid"}],
            )
        try:
            amount = parse_amount(payload.get("amount"))
        except ValueError as exc:
            conn.execute(
                "UPDATE core_events SET processing_status='failed' WHERE event_id=?",
                (event_id,),
            )
            raise InnbankProcessingError(
                "amount must be a positive number",
                effects=[{"type": "event_failed", "event_id": event_id, "reason": "invalid_amount"}],
            ) from exc
        currency = clean_text(payload.get("currency") or "USD").upper()
        classification = clean_text(payload.get("classification") or "unknown").lower()
        account_name = clean_text(payload.get("account_name") or "connected account") or "connected account"
        classification_confidence = parse_confidence(
            payload.get("classification_confidence"),
            default=float(event.get("confidence") or 1.0),
        )
        transaction_ref = clean_text(payload.get("transaction_ref")) or None

        if classification in NON_DEPLOYABLE_INFLOW:
            conn.execute(
                "UPDATE core_events SET processing_status='ignored' WHERE event_id=?",
                (event_id,),
            )
            return {
                "event_status": "ignored",
                "effects": [
                    {
                        "type": "inflow_ignored",
                        "event_id": event_id,
                        "classification": classification,
                        "reason": "non_deployable_inflow",
                    }
                ],
            }

        if classification in CONFIRMED_INCOME:
            signal_type = "paycheck_received"
            title = f"Paycheck received: {format_money(amount, currency)}"
            summary = (
                f"Confirmed deployable income posted to {account_name}. It should be reviewed "
                "before any allocation decision is made."
            )
            rationale = (
                "The posted classification identifies deployable earned income that may be "
                "routed only after review."
            )
            recommended_action = (
                "Review the protected cash floor, obligations due before the next paycheck, "
                "and active goals before approving any allocation."
            )
            signal_confidence = classification_confidence
        else:
            signal_type = "paycheck_classification_required"
            title = f"Classify inflow before allocation: {format_money(amount, currency)}"
            summary = (
                f"An inflow posted to {account_name}, but the classification does not prove "
                "that it is deployable income."
            )
            rationale = (
                "Ambiguous inflows must be classified before routing or allocation to avoid "
                "treating non-income as deployable capital."
            )
            recommended_action = (
                "Classify this inflow as paycheck, payroll, earned_income, internal_transfer, "
                "refund, reversal, or interest before allocating it."
            )
            signal_confidence = min(classification_confidence, 0.95)
            signal_actionability = 0.95
        if classification in CONFIRMED_INCOME:
            signal_actionability = 1.0

        signal_id = make_id("SIG")
        metadata_json = json.dumps(
            {
                "event_id": event_id,
                "amount": str(amount),
                "currency": currency,
                "account_name": account_name,
                "classification": classification,
                "classification_confidence": classification_confidence,
                "transaction_ref": transaction_ref,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        conn.execute(
            """
            INSERT INTO core_signals (
                signal_id, owner_system_id, signal_type, title, summary,
                priority, confidence, actionability_score, status,
                rationale, recommended_action, detected_at, metadata_json
            ) VALUES (?, 'sys_innbank', ?, ?, ?, 'P0', ?, ?, 'new', ?, ?, ?, ?)
            """,
            (
                signal_id,
                signal_type,
                title,
                summary,
                signal_confidence,
                signal_actionability,
                rationale,
                recommended_action,
                event["occurred_at"],
                metadata_json,
            ),
        )
        conn.execute(
            "INSERT INTO core_signal_events (signal_id, event_id, relationship) VALUES (?, ?, 'trigger')",
            (signal_id, event_id),
        )
        conn.execute(
            "UPDATE core_events SET processing_status='processed' WHERE event_id=?",
            (event_id,),
        )

        sync_alert_queue(conn)
        alert_row = conn.execute(
            """
            SELECT alert_id
            FROM core_alerts
            WHERE signal_id=?
              AND state IN ('queued', 'presented', 'acknowledged', 'snoozed', 'actioned', 'failed')
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (signal_id,),
        ).fetchone()

        effects = [
                {
                    "type": "core_signal_created",
                    "event_id": event_id,
                    "signal_id": signal_id,
                    "signal_type": signal_type,
                    "priority": "P0",
                    "actionability_score": signal_actionability,
                }
            ]
        if alert_row:
            effects.append(
                {
                    "type": "critical_alert_created",
                    "event_id": event_id,
                    "signal_id": signal_id,
                    "alert_id": alert_row["alert_id"],
                    "state": "queued",
                }
            )
        return {
            "event_status": "processed",
            "signal_id": signal_id,
            "signal_type": signal_type,
            "alert_id": alert_row["alert_id"] if alert_row else None,
            "effects": effects,
        }


class EventDispatcher:
    """Route normalized events to supported domain processors."""

    def __init__(self) -> None:
        self.innbank = InnBankPaydayProcessor()
        self.home_sentinel = HomeSentinelProcessor()
        self.module_processors = ModuleSignalProcessor()

    def dispatch(self, conn, event: dict[str, Any], *, deduplicated: bool) -> dict[str, Any]:
        if deduplicated:
            return {"event_status": event.get("processing_status") or "new", "effects": []}
        if (
            event.get("source_system_id") == "sys_innbank"
            and event.get("event_type") == "financial_inflow_posted"
        ):
            return self.innbank.process_event(conn, event)
        if event.get("source_system_id") == "sys_home_sentinel" and event.get("event_type") in {
            "camera_health_changed",
            "detection_observed",
        }:
            return self.home_sentinel.process_event(conn, event)
        if event.get("event_type") in SUPPORTED_EVENTS.get(event.get("source_system_id"), set()):
            return self.module_processors.process_event(conn, event)
        return {"event_status": event.get("processing_status") or "new", "effects": []}
