"""Core event gateway logic for the normalized lifecycle."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core_database import connect


MAX_EVENT_BODY_BYTES = 256 * 1024
ALLOWED_FIELDS = {
    "source_system_id",
    "event_type",
    "occurred_at",
    "entity_id",
    "observed_at",
    "dedupe_key",
    "source_ref",
    "correlation_id",
    "causation_event_id",
    "priority",
    "confidence",
    "payload",
}
REQUIRED_FIELDS = {"source_system_id", "event_type", "occurred_at"}
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16].upper()}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_timestamp(value: Any, field_name: str) -> str:
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


def normalize_event_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    unknown = sorted(set(payload) - ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")
    missing = sorted(field for field in REQUIRED_FIELDS if field not in payload)
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    priority = clean_text(payload.get("priority") or "P2").upper()
    if priority not in ALLOWED_PRIORITIES:
        raise ValueError("priority must be P0, P1, or P2")
    try:
        confidence = float(payload.get("confidence", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be between 0 and 1") from exc
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")
    if "payload" in payload:
        event_payload = payload.get("payload")
        if not isinstance(event_payload, dict):
            raise ValueError("payload must be a JSON object")
    else:
        event_payload = {}
    if not isinstance(event_payload, dict):
        raise ValueError("payload must be a JSON object")
    normalized = {
        "source_system_id": clean_text(payload.get("source_system_id")),
        "event_type": clean_text(payload.get("event_type")),
        "occurred_at": normalize_timestamp(payload.get("occurred_at"), "occurred_at"),
        "entity_id": clean_text(payload.get("entity_id")) or None,
        "observed_at": None,
        "dedupe_key": clean_text(payload.get("dedupe_key")) or None,
        "source_ref": clean_text(payload.get("source_ref")) or None,
        "correlation_id": clean_text(payload.get("correlation_id")) or None,
        "causation_event_id": clean_text(payload.get("causation_event_id")) or None,
        "priority": priority,
        "confidence": round(confidence, 6),
        "payload": event_payload,
    }
    if payload.get("observed_at") is not None:
        normalized["observed_at"] = normalize_timestamp(payload.get("observed_at"), "observed_at")
    return normalized


def row_to_event(row) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = json.loads(data.get("payload_json") or "{}")
    data.pop("payload_json", None)
    return data


def event_exists(conn, source_system_id: str, dedupe_key: str | None):
    if not dedupe_key:
        return None
    return conn.execute(
        """
        SELECT * FROM core_events
        WHERE source_system_id = ? AND dedupe_key = ?
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (source_system_id, dedupe_key),
    ).fetchone()


def _verify_refs(conn, normalized: dict[str, Any]) -> None:
    source = conn.execute(
        "SELECT 1 FROM core_systems WHERE system_id=?",
        (normalized["source_system_id"],),
    ).fetchone()
    if not source:
        raise KeyError("source system not found")
    if normalized["entity_id"]:
        entity = conn.execute(
            "SELECT 1 FROM core_entities WHERE entity_id=?",
            (normalized["entity_id"],),
        ).fetchone()
        if not entity:
            raise KeyError("entity not found")
    if normalized["causation_event_id"]:
        prior = conn.execute(
            "SELECT 1 FROM core_events WHERE event_id=?",
            (normalized["causation_event_id"],),
        ).fetchone()
        if not prior:
            raise KeyError("causation event not found")


def create_event(conn, payload: Any) -> dict[str, Any]:
    normalized = normalize_event_payload(payload)
    _verify_refs(conn, normalized)
    existing = event_exists(conn, normalized["source_system_id"], normalized["dedupe_key"])
    if existing:
        return {
            "created": False,
            "duplicate": True,
            "event": row_to_event(existing),
        }
    event_id = make_id("EVT")
    conn.execute(
        """
        INSERT INTO core_events (
            event_id, source_system_id, event_type, entity_id, occurred_at, observed_at,
            received_at, dedupe_key, source_ref, correlation_id, causation_event_id,
            priority, confidence, processing_status, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            normalized["source_system_id"],
            normalized["event_type"],
            normalized["entity_id"],
            normalized["occurred_at"],
            normalized["observed_at"],
            now_utc_iso(),
            normalized["dedupe_key"],
            normalized["source_ref"],
            normalized["correlation_id"],
            normalized["causation_event_id"],
            normalized["priority"],
            normalized["confidence"],
            "new",
            json.dumps(normalized["payload"], ensure_ascii=False, sort_keys=True),
            now_utc_iso(),
        ),
    )
    event = conn.execute("SELECT * FROM core_events WHERE event_id=?", (event_id,)).fetchone()
    return {
        "created": True,
        "duplicate": False,
        "event": row_to_event(event),
    }


def store_event(database_path, payload: Any) -> dict[str, Any]:
    with connect(database_path) as conn:
        return create_event(conn, payload)
