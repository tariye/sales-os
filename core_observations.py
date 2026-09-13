"""Source observation versioning and ingestion into core events."""

from __future__ import annotations

import json
import uuid
from typing import Any

from core_events import create_event
from core_operations import (
    claim_operation,
    clean_text,
    complete_attempt,
    load_json,
    make_id,
    now_utc_iso,
    request_hash,
    stable_json,
)
from core_processors import EventDispatcher, HomeSentinelProcessingError, InnbankProcessingError, ModuleProcessingError


class ObservationConflict(ValueError):
    pass


def _row_to_observation(row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = load_json(data.pop("metadata_json", "{}"), {})
    return data


def _operation_key(payload: dict[str, Any]) -> str:
    return ":".join(
        [
            clean_text(payload.get("source_system_id")),
            clean_text(payload.get("source_connection_id")),
            clean_text(payload.get("account_external_id")),
            clean_text(payload.get("source_transaction_id")),
        ]
    )


def _observation_version_key(payload: dict[str, Any]) -> str:
    material = {
        "identity": _operation_key(payload),
        "economic_inflow_key": _economic_key(payload),
        "observation_status": clean_text(payload.get("observation_status")),
        "amount_cents": payload.get("amount_cents"),
        "currency": clean_text(payload.get("currency")),
        "classification": clean_text(payload.get("classification")),
        "classification_confidence": payload.get("classification_confidence"),
        "effective_date": clean_text(payload.get("effective_date")),
        "posted_at": clean_text(payload.get("posted_at")),
        "provider_transaction_id": clean_text(payload.get("provider_transaction_id")),
        "provider_pending_id": clean_text(payload.get("provider_pending_id")),
        "provider_posted_id": clean_text(payload.get("provider_posted_id")),
    }
    return f"{_operation_key(payload)}:{request_hash(material)}"


def _economic_key(payload: dict[str, Any]) -> str:
    provided = clean_text(payload.get("economic_inflow_key"))
    if provided:
        return provided
    return _operation_key(payload)


def _latest_for_transaction(conn, payload: dict[str, Any]):
    return conn.execute(
        """
        SELECT *
        FROM core_source_observations
        WHERE source_system_id=?
          AND source_connection_id=?
          AND account_external_id=?
          AND source_transaction_id=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            clean_text(payload.get("source_system_id")),
            clean_text(payload.get("source_connection_id")),
            clean_text(payload.get("account_external_id")),
            clean_text(payload.get("source_transaction_id")),
        ),
    ).fetchone()


def _latest_economic(conn, payload: dict[str, Any]):
    return conn.execute(
        """
        SELECT *
        FROM core_source_observations
        WHERE source_system_id=?
          AND source_connection_id=?
          AND account_external_id=?
          AND economic_inflow_key=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            clean_text(payload.get("source_system_id")),
            clean_text(payload.get("source_connection_id")),
            clean_text(payload.get("account_external_id")),
            _economic_key(payload),
        ),
    ).fetchone()


def _same_material_observation(existing, payload: dict[str, Any]) -> bool:
    comparable = {
        "observation_status": clean_text(payload.get("observation_status")),
        "amount_cents": payload.get("amount_cents"),
        "currency": clean_text(payload.get("currency")),
        "classification": clean_text(payload.get("classification")),
        "classification_confidence": payload.get("classification_confidence"),
        "effective_date": clean_text(payload.get("effective_date")),
        "posted_at": clean_text(payload.get("posted_at")),
    }
    return all(existing[key] == value for key, value in comparable.items())


def record_source_observation(conn, payload: dict[str, Any], *, worker_id: str = "source-observer", now: str | None = None) -> dict[str, Any]:
    now = now or now_utc_iso()
    required = ["source_system_id", "source_connection_id", "account_external_id", "observation_type", "source_transaction_id", "observation_status", "observed_at"]
    missing = [field for field in required if not clean_text(payload.get(field))]
    if missing:
        raise ValueError(f"missing required observation fields: {', '.join(missing)}")
    if clean_text(payload.get("observation_status")) not in {"pending", "posted", "removed", "unknown"}:
        raise ValueError("observation_status must be pending, posted, removed, or unknown")

    source_system_id = clean_text(payload["source_system_id"])
    source = conn.execute("SELECT 1 FROM core_systems WHERE system_id=?", (source_system_id,)).fetchone()
    if not source:
        raise KeyError("source system not found")

    op_key = _observation_version_key(payload)
    claimed = claim_operation(
        conn,
        operation_type="observe_source_transaction",
        operation_key=op_key,
        request_payload={"identity": op_key},
        worker_id=worker_id,
        source_system_id=source_system_id,
        subject_namespace="core",
        subject_type="source_transaction",
        subject_id=clean_text(payload.get("source_transaction_id")),
        immutable_payload=False,
        now=now,
    )
    if claimed["idempotent"]:
        result = claimed["operation"].get("result") or {}
        observation_id = clean_text(result.get("observation_id"))
        row = conn.execute("SELECT * FROM core_source_observations WHERE observation_id=?", (observation_id,)).fetchone()
        if row:
            return {"created": False, "updated": False, "observation": _row_to_observation(row), "operation": claimed["operation"], "attempt": None}

    existing_txn = _latest_for_transaction(conn, payload)
    if existing_txn and _same_material_observation(existing_txn, payload):
        conn.execute(
            "UPDATE core_source_observations SET last_seen_at=?, updated_at=?, dedupe_state='duplicate' WHERE observation_id=?",
            (now, now, existing_txn["observation_id"]),
        )
        complete_attempt(
            conn,
            operation_id=claimed["operation"]["operation_id"],
            attempt_id=claimed["attempt"]["attempt_id"],
            worker_id=worker_id,
            status="succeeded",
            result={"observation_id": existing_txn["observation_id"], "dedupe_state": "duplicate"},
            result_namespace="core",
            result_type="source_observation",
            result_id=existing_txn["observation_id"],
            now=now,
        )
        row = conn.execute("SELECT * FROM core_source_observations WHERE observation_id=?", (existing_txn["observation_id"],)).fetchone()
        return {"created": False, "updated": False, "observation": _row_to_observation(row), "operation": claimed["operation"], "attempt": claimed["attempt"]}

    existing_economic = _latest_economic(conn, payload)
    status = clean_text(payload.get("observation_status"))
    pending_id = clean_text(payload.get("pending_observation_id")) or None
    posted_id = clean_text(payload.get("posted_observation_id")) or None
    supersedes = clean_text(payload.get("supersedes_observation_id")) or None
    match_state = clean_text(payload.get("match_state")) or "unmatched"
    dedupe_state = "new"
    if existing_txn:
        supersedes = existing_txn["observation_id"]
        dedupe_state = "updated"
        if existing_txn["observation_status"] == "pending" and status == "posted":
            pending_id = existing_txn["observation_id"]
            match_state = "confirmed_match"
    elif existing_economic:
        if existing_economic["observation_status"] == "pending" and status == "posted":
            pending_id = existing_economic["observation_id"]
            match_state = "probable_match"
        elif existing_economic["observation_status"] == "posted" and status == "pending":
            posted_id = existing_economic["observation_id"]
            match_state = "probable_match"
        else:
            match_state = "probable_match"

    observation_id = make_id("OBS")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata.update({
        "request_hash": request_hash(payload),
        "source_identity_scope": {
            "source_system_id": source_system_id,
            "source_connection_id": clean_text(payload.get("source_connection_id")),
            "account_external_id": clean_text(payload.get("account_external_id")),
            "source_transaction_id": clean_text(payload.get("source_transaction_id")),
        },
    })
    conn.execute(
        """
        INSERT INTO core_source_observations (
            observation_id, source_system_id, source_connection_id, account_external_id,
            source_name, observation_type, source_transaction_id, provider_transaction_id,
            provider_pending_id, provider_posted_id, economic_inflow_key, observation_status,
            amount_cents, currency, account_name, classification, classification_confidence,
            observed_at, effective_date, posted_at, source_modified_at, first_seen_at,
            last_seen_at, supersedes_observation_id, pending_observation_id,
            posted_observation_id, dedupe_state, match_state, operation_id,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation_id,
            source_system_id,
            clean_text(payload.get("source_connection_id")),
            clean_text(payload.get("account_external_id")),
            clean_text(payload.get("source_name")) or None,
            clean_text(payload.get("observation_type")),
            clean_text(payload.get("source_transaction_id")),
            clean_text(payload.get("provider_transaction_id")) or None,
            clean_text(payload.get("provider_pending_id")) or None,
            clean_text(payload.get("provider_posted_id")) or None,
            _economic_key(payload),
            status,
            payload.get("amount_cents"),
            clean_text(payload.get("currency")) or None,
            clean_text(payload.get("account_name")) or None,
            clean_text(payload.get("classification")) or None,
            payload.get("classification_confidence"),
            clean_text(payload.get("observed_at")),
            clean_text(payload.get("effective_date")) or None,
            clean_text(payload.get("posted_at")) or None,
            clean_text(payload.get("source_modified_at")) or None,
            now if not existing_txn else existing_txn["first_seen_at"],
            now,
            supersedes,
            pending_id,
            posted_id,
            dedupe_state,
            match_state,
            claimed["operation"]["operation_id"],
            stable_json(metadata),
            now,
            now,
        ),
    )
    if supersedes:
        conn.execute(
            "UPDATE core_source_observations SET dedupe_state='superseded', updated_at=? WHERE observation_id=?",
            (now, supersedes),
        )
    if pending_id and status == "posted":
        conn.execute(
            "UPDATE core_source_observations SET posted_observation_id=?, updated_at=? WHERE observation_id=?",
            (observation_id, now, pending_id),
        )
    complete_attempt(
        conn,
        operation_id=claimed["operation"]["operation_id"],
        attempt_id=claimed["attempt"]["attempt_id"],
        worker_id=worker_id,
        status="succeeded",
        result={"observation_id": observation_id, "dedupe_state": dedupe_state, "match_state": match_state},
        result_namespace="core",
        result_type="source_observation",
        result_id=observation_id,
        now=now,
    )
    row = conn.execute("SELECT * FROM core_source_observations WHERE observation_id=?", (observation_id,)).fetchone()
    return {"created": True, "updated": dedupe_state == "updated", "observation": _row_to_observation(row), "operation": claimed["operation"], "attempt": claimed["attempt"]}


def event_payload_from_observation(observation: dict[str, Any]) -> dict[str, Any]:
    if observation["observation_status"] != "posted":
        raise ValueError("pending observations must not become posted income")
    payload = {
        "source_system_id": observation["source_system_id"],
        "event_type": "financial_inflow_posted",
        "occurred_at": observation.get("posted_at") or observation.get("observed_at"),
        "observed_at": observation.get("observed_at"),
        "dedupe_key": f"observation:{observation['observation_id']}",
        "source_ref": observation.get("source_transaction_id"),
        "priority": "P0",
        "confidence": observation.get("classification_confidence") or 1.0,
        "payload": {
            "amount": f"{int(observation['amount_cents'] or 0) / 100:.2f}",
            "currency": observation.get("currency") or "USD",
            "account_name": observation.get("account_name") or "connected account",
            "classification": observation.get("classification") or "unknown",
            "classification_confidence": observation.get("classification_confidence") or 1.0,
            "transaction_ref": observation.get("source_transaction_id"),
            "source_observation_id": observation["observation_id"],
            "economic_inflow_key": observation.get("economic_inflow_key"),
        },
    }
    return payload


def ingest_observation(conn, observation_id: str, *, worker_id: str = "ingestion-worker", dispatch: bool = True, now: str | None = None) -> dict[str, Any]:
    now = now or now_utc_iso()
    row = conn.execute("SELECT * FROM core_source_observations WHERE observation_id=?", (clean_text(observation_id),)).fetchone()
    if not row:
        raise KeyError("observation not found")
    observation = _row_to_observation(row)
    operation_key = f"{observation_id}:financial_inflow_posted"
    event_payload = event_payload_from_observation(observation)
    claimed = claim_operation(
        conn,
        operation_type="ingest_observation",
        operation_key=operation_key,
        request_payload=event_payload,
        worker_id=worker_id,
        source_system_id=observation["source_system_id"],
        subject_namespace="core",
        subject_type="source_observation",
        subject_id=observation_id,
        immutable_payload=True,
        now=now,
    )
    if claimed["idempotent"]:
        result = claimed["operation"].get("result") or {}
        return {"created": False, "idempotent": True, **result}
    try:
        event_result = create_event(conn, event_payload)
        effects: list[dict[str, Any]] = []
        if dispatch and event_result["created"]:
            dispatch_result = EventDispatcher().dispatch(conn, event_result["event"], deduplicated=False)
            effects = dispatch_result.get("effects", [])
            event_result["event"]["processing_status"] = dispatch_result.get("event_status", event_result["event"].get("processing_status"))
        elif dispatch and not event_result["created"]:
            dispatch_result = EventDispatcher().dispatch(conn, event_result["event"], deduplicated=True)
            effects = dispatch_result.get("effects", [])
        result = {
            "event_id": event_result["event"]["event_id"],
            "created": event_result["created"],
            "duplicate": event_result["duplicate"],
            "effects": effects,
        }
        conn.execute(
            """
            INSERT INTO core_ingestion_results (
                ingestion_result_id, operation_id, attempt_id, observation_id,
                event_id, status, effects_json, error_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'succeeded', ?, '{}', ?)
            """,
            (
                make_id("ING"),
                claimed["operation"]["operation_id"],
                claimed["attempt"]["attempt_id"],
                observation_id,
                event_result["event"]["event_id"],
                stable_json(effects),
                now,
            ),
        )
        complete_attempt(
            conn,
            operation_id=claimed["operation"]["operation_id"],
            attempt_id=claimed["attempt"]["attempt_id"],
            worker_id=worker_id,
            status="succeeded",
            result=result,
            result_namespace="core",
            result_type="event",
            result_id=event_result["event"]["event_id"],
            now=now,
        )
        return {"idempotent": False, **result}
    except (ValueError, KeyError, InnbankProcessingError, HomeSentinelProcessingError, ModuleProcessingError) as exc:
        conn.execute(
            """
            INSERT INTO core_ingestion_results (
                ingestion_result_id, operation_id, attempt_id, observation_id,
                event_id, status, effects_json, error_json, created_at
            ) VALUES (?, ?, ?, ?, NULL, 'failed', '[]', ?, ?)
            """,
            (
                make_id("ING"),
                claimed["operation"]["operation_id"],
                claimed["attempt"]["attempt_id"],
                observation_id,
                stable_json({"error": str(exc)}),
                now,
            ),
        )
        complete_attempt(
            conn,
            operation_id=claimed["operation"]["operation_id"],
            attempt_id=claimed["attempt"]["attempt_id"],
            worker_id=worker_id,
            status="failed",
            error={"error": str(exc)},
            now=now,
        )
        raise
