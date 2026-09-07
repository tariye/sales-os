"""Thin processors for Groove, Sales, and Private Equity OS events."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from core_alerts import sync_alert_queue


SUPPORTED_EVENTS = {
    "sys_groove": {"project_blocked", "release_milestone_reached"},
    "sys_sales": {"followup_due", "deal_stage_changed"},
    "sys_private_equity": {"thesis_changed", "risk_limit_breached"},
}


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


@dataclass
class ModuleProcessingError(ValueError):
    message: str
    effects: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)


class ModuleSignalProcessor:
    """Create one shared signal from a supported Groove, Sales, or PE event."""

    def process_event(self, conn, event: dict[str, Any]) -> dict[str, Any]:
        event_id = event["event_id"]
        supported = SUPPORTED_EVENTS.get(event["source_system_id"], set())
        if event["event_type"] not in supported:
            raise ModuleProcessingError("unsupported module event")

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
              AND s.owner_system_id = ?
            ORDER BY s.created_at ASC
            LIMIT 1
            """,
            (event_id, event["source_system_id"]),
        ).fetchone()
        if existing:
            return {
                "event_status": clean_text(existing["processing_status"]) or "processed",
                "effects": [
                    {
                        "type": "module_event_already_processed",
                        "event_id": event_id,
                        "signal_id": existing["signal_id"],
                        "signal_type": existing["signal_type"],
                        "alert_id": clean_text(existing["alert_id"]) or None,
                    }
                ],
            }

        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            raise ModuleProcessingError(
                "module payload must be a JSON object",
                effects=[{"type": "event_failed", "event_id": event_id, "reason": "payload_invalid"}],
            )
        try:
            classifier = self._classifier(event["source_system_id"])
            signal = classifier(event, payload)
        except (KeyError, TypeError, ValueError) as exc:
            conn.execute(
                "UPDATE core_events SET processing_status='failed' WHERE event_id=?",
                (event_id,),
            )
            raise ModuleProcessingError(
                str(exc),
                effects=[{"type": "event_failed", "event_id": event_id, "reason": "validation_failed"}],
            ) from exc

        signal_id = make_id("SIG")
        metadata_json = json.dumps(
            {
                "event_id": event_id,
                "source_ref": clean_text(event.get("source_ref")) or None,
                "payload": payload,
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)
            """,
            (
                signal_id,
                event["source_system_id"],
                signal["signal_type"],
                signal["title"],
                signal["summary"],
                signal["priority"],
                float(event.get("confidence") or 1.0),
                signal["actionability_score"],
                signal["rationale"],
                signal["recommended_action"],
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
        if signal["priority"] in {"P0", "P1"}:
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
                "signal_type": signal["signal_type"],
                "priority": signal["priority"],
                "actionability_score": signal["actionability_score"],
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
            "signal_type": signal["signal_type"],
            "priority": signal["priority"],
            "alert_id": alert_row["alert_id"] if alert_row else None,
            "effects": effects,
        }

    @staticmethod
    def _classifier(system_id: str) -> Callable[[Any, dict[str, Any]], dict[str, Any]]:
        return {
            "sys_groove": ModuleSignalProcessor._classify_groove,
            "sys_sales": ModuleSignalProcessor._classify_sales,
            "sys_private_equity": ModuleSignalProcessor._classify_private_equity,
        }[system_id]

    @staticmethod
    def _classify_groove(event: Any, payload: dict[str, Any]) -> dict[str, Any]:
        project = required_text(payload, "project_name")
        if event["event_type"] == "project_blocked":
            blocker = required_text(payload, "blocker")
            next_action = required_text(payload, "next_action")
            return {
                "signal_type": "groove_project_blocked",
                "title": f"Groove project blocked: {project}",
                "summary": blocker,
                "priority": "P1",
                "actionability_score": 0.9,
                "rationale": "A named blocker with a next action can be resolved or deliberately deferred.",
                "recommended_action": next_action,
            }
        milestone = required_text(payload, "milestone")
        return {
            "signal_type": "groove_release_milestone_reached",
            "title": f"Groove milestone reached: {project}",
            "summary": milestone,
            "priority": "P2",
            "actionability_score": 0.3,
            "rationale": "The milestone belongs in project memory without interrupting active work.",
            "recommended_action": "Record the next milestone when planning resumes.",
        }

    @staticmethod
    def _classify_sales(event: Any, payload: dict[str, Any]) -> dict[str, Any]:
        opportunity = required_text(payload, "opportunity_name")
        if event["event_type"] == "followup_due":
            next_action = required_text(payload, "next_action")
            return {
                "signal_type": "sales_followup_due",
                "title": f"Sales follow-up due: {opportunity}",
                "summary": clean_text(payload.get("context")) or "A committed follow-up is now due.",
                "priority": "P1",
                "actionability_score": 0.95,
                "rationale": "A time-bound relationship commitment loses value when it is forgotten.",
                "recommended_action": next_action,
            }
        stage = required_text(payload, "stage")
        return {
            "signal_type": "sales_stage_changed",
            "title": f"Sales stage changed: {opportunity}",
            "summary": f"The opportunity moved to {stage}.",
            "priority": "P2",
            "actionability_score": 0.3,
            "rationale": "Stage history improves later funnel analysis.",
            "recommended_action": "No immediate action unless a follow-up becomes due.",
        }

    @staticmethod
    def _classify_private_equity(event: Any, payload: dict[str, Any]) -> dict[str, Any]:
        asset = required_text(payload, "asset_name")
        if event["event_type"] == "risk_limit_breached":
            rule = required_text(payload, "rule")
            return {
                "signal_type": "investment_risk_limit_breached",
                "title": f"Investment risk limit breached: {asset}",
                "summary": rule,
                "priority": "P0",
                "actionability_score": 1.0,
                "rationale": "A breached precommitted risk rule requires review before further capital action.",
                "recommended_action": "Review the exposure, evidence, and governing rule before acting.",
            }
        change = required_text(payload, "change").lower()
        materiality = payload.get("materiality", 0.5)
        if isinstance(materiality, bool) or not isinstance(materiality, (int, float)):
            raise ValueError("materiality must be a number from 0 to 1")
        materiality = float(materiality)
        if not 0.0 <= materiality <= 1.0:
            raise ValueError("materiality must be a number from 0 to 1")
        if change == "invalidated":
            priority, actionability = "P0", 1.0
            action = "Reopen the thesis and review any capital decision tied to it."
        elif change == "weakened" and materiality >= 0.7:
            priority, actionability = "P1", 0.9
            action = "Compare the new evidence with the thesis and decide whether to hold, modify, or reject it."
        elif change in {"strengthened", "weakened", "unchanged"}:
            priority, actionability = "P2", 0.4
            action = "Store the evidence for the next scheduled thesis review."
        else:
            raise ValueError("change must be strengthened, weakened, unchanged, or invalidated")
        return {
            "signal_type": f"investment_thesis_{change}",
            "title": f"Investment thesis {change}: {asset}",
            "summary": clean_text(payload.get("evidence")) or "New thesis evidence was recorded.",
            "priority": priority,
            "actionability_score": actionability,
            "rationale": "Capital decisions should respond to material changes in the underlying thesis.",
            "recommended_action": action,
        }
