"""Home Sentinel event processor for camera-health and detection signals."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from core_alerts import sync_alert_queue


HOME_SENTINEL_SYSTEM_ID = "sys_home_sentinel"
SUPPORTED_EVENT_TYPES = {"camera_health_changed", "detection_observed"}


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass
class HomeSentinelProcessingError(ValueError):
    message: str
    effects: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__(self.message)


class HomeSentinelProcessor:
    """Translate Home Sentinel observations into prioritized core signals."""

    def process_event(self, conn, event: dict[str, Any]) -> dict[str, Any]:
        event_id = event["event_id"]
        existing = conn.execute(
            """
            SELECT s.signal_id, s.signal_type, a.alert_id, e.processing_status
            FROM core_signal_events AS se
            JOIN core_signals AS s ON s.signal_id = se.signal_id
            LEFT JOIN core_alerts AS a
                ON a.signal_id = s.signal_id
               AND a.state IN ('queued', 'presented', 'acknowledged', 'snoozed', 'actioned', 'failed')
            JOIN core_events AS e ON e.event_id = se.event_id
            WHERE se.event_id = ? AND se.relationship = 'trigger'
              AND s.owner_system_id = ?
            ORDER BY s.created_at ASC
            LIMIT 1
            """,
            (event_id, HOME_SENTINEL_SYSTEM_ID),
        ).fetchone()
        if existing:
            return {
                "event_status": clean_text(existing["processing_status"]) or "processed",
                "effects": [
                    {
                        "type": "home_sentinel_event_already_processed",
                        "event_id": event_id,
                        "signal_id": existing["signal_id"],
                        "signal_type": existing["signal_type"],
                        "alert_id": clean_text(existing["alert_id"]) or None,
                    }
                ],
            }

        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            raise HomeSentinelProcessingError(
                "Home Sentinel payload must be a JSON object",
                effects=[{"type": "event_failed", "event_id": event_id, "reason": "payload_invalid"}],
            )
        try:
            signal = self._classify(event, payload)
        except (KeyError, TypeError, ValueError) as exc:
            conn.execute(
                "UPDATE core_events SET processing_status='failed' WHERE event_id=?",
                (event_id,),
            )
            raise HomeSentinelProcessingError(
                str(exc),
                effects=[{"type": "event_failed", "event_id": event_id, "reason": "validation_failed"}],
            ) from exc

        signal_id = make_id("SIG")
        metadata_json = json.dumps(
            {
                "event_id": event_id,
                "source_ref": clean_text(event.get("source_ref")) or None,
                "camera_name": signal["camera_name"],
                "metrics": signal.get("metrics") or {},
                "detection_type": signal.get("detection_type"),
                "expected": signal.get("expected"),
                "zone": signal.get("zone"),
                "image_ref": signal.get("image_ref"),
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
                HOME_SENTINEL_SYSTEM_ID,
                signal["signal_type"],
                signal["title"],
                signal["summary"],
                signal["priority"],
                signal["confidence"],
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
    def _classify(event: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        event_type = clean_text(event.get("event_type")).lower()
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValueError("unsupported Home Sentinel event type")

        camera_name = clean_text(payload.get("camera_name")) or "camera"
        confidence_value = payload.get("detection_confidence", event.get("confidence", 1.0))
        if isinstance(confidence_value, bool) or not isinstance(confidence_value, (int, float)):
            raise ValueError("detection_confidence must be a number from 0 to 1")
        confidence = float(confidence_value)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("detection_confidence must be a number from 0 to 1")

        if event_type == "camera_health_changed":
            status = clean_text(payload.get("status")).lower()
            metrics = payload.get("metrics")
            if metrics is not None and not isinstance(metrics, dict):
                raise ValueError("metrics must be a JSON object")
            if status == "offline":
                return {
                    "signal_type": "camera_offline",
                    "title": f"Home Sentinel camera offline: {camera_name}",
                    "summary": "Monitoring coverage is unavailable and needs verification.",
                    "priority": "P0",
                    "confidence": confidence,
                    "actionability_score": 1.0,
                    "rationale": "Loss of camera coverage creates an immediate blind spot.",
                    "recommended_action": "Check power, network reachability, and the camera service.",
                    "camera_name": camera_name,
                    "metrics": metrics or {},
                    "detection_type": event_type,
                    "image_ref": None,
                }
            if status == "degraded":
                return {
                    "signal_type": "camera_degraded",
                    "title": f"Home Sentinel camera degraded: {camera_name}",
                    "summary": "The camera is reachable but its operating quality is reduced.",
                    "priority": "P1",
                    "confidence": confidence,
                    "actionability_score": 0.8,
                    "rationale": "Degraded capture can reduce the reliability of later evidence.",
                    "recommended_action": "Inspect camera metrics and correct the failing condition.",
                    "camera_name": camera_name,
                    "metrics": metrics or {},
                    "detection_type": event_type,
                    "image_ref": None,
                }
            if status == "online":
                signal_type = "camera_online"
                title = f"Home Sentinel camera online: {camera_name}"
            elif status in {"healthy", "recovered"}:
                signal_type = "camera_recovered"
                title = f"Home Sentinel camera recovered: {camera_name}"
            else:
                raise ValueError("status must be offline, degraded, online, healthy, or recovered")
            return {
                "signal_type": signal_type,
                "title": title,
                "summary": "Monitoring coverage is operating normally.",
                "priority": "P2",
                "confidence": confidence,
                "actionability_score": 0.1,
                "rationale": "Normal status is useful history but does not require interruption.",
                "recommended_action": "No action required.",
                "camera_name": camera_name,
                "metrics": metrics or {},
                "detection_type": event_type,
                "image_ref": None,
            }

        detection_type = clean_text(payload.get("detection_type")).lower()
        zone = clean_text(payload.get("zone")) or "monitored area"
        expected = payload.get("expected")
        if expected is not None and not isinstance(expected, bool):
            raise ValueError("expected must be true, false, or omitted")
        image_ref = clean_text(payload.get("image_ref")) or None

        if detection_type == "person" and expected is False:
            return {
                "signal_type": "unexpected_person_detected",
                "title": f"Unexpected person detected: {zone}",
                "summary": f"{camera_name} observed a person marked unexpected.",
                "priority": "P0",
                "confidence": confidence,
                "actionability_score": 1.0,
                "rationale": "An unexpected person can require immediate verification.",
                "recommended_action": "Review the referenced capture and verify household safety.",
                "camera_name": camera_name,
                "metrics": {},
                "detection_type": detection_type,
                "expected": expected,
                "zone": zone,
                "image_ref": image_ref,
            }
        if detection_type == "person" and expected is None:
            return {
                "signal_type": "person_verification_required",
                "title": f"Person requires verification: {zone}",
                "summary": f"{camera_name} observed a person whose expected status is unknown.",
                "priority": "P1",
                "confidence": confidence,
                "actionability_score": 0.85,
                "rationale": "The system needs human context before classifying the detection.",
                "recommended_action": "Review the capture and classify the person as expected or unexpected.",
                "camera_name": camera_name,
                "metrics": {},
                "detection_type": detection_type,
                "expected": expected,
                "zone": zone,
                "image_ref": image_ref,
            }
        if detection_type == "person":
            signal_type = "expected_person_detected"
            title = f"Expected person observed: {zone}"
        elif detection_type == "motion":
            signal_type = "motion_observed"
            title = f"Motion observed: {zone}"
        else:
            signal_type = f"{detection_type or 'object'}_observed"
            title = f"Object observed: {zone}"
        return {
            "signal_type": signal_type,
            "title": title,
            "summary": f"{camera_name} recorded a non-critical observation.",
            "priority": "P2",
            "confidence": confidence,
            "actionability_score": 0.2,
            "rationale": "The observation belongs in history but does not justify interruption.",
            "recommended_action": "No immediate action required.",
            "camera_name": camera_name,
            "metrics": {},
            "detection_type": detection_type,
            "expected": expected,
            "zone": zone,
            "image_ref": image_ref,
        }
