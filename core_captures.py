"""Durable chat capture ingestion and deterministic daily-loop interpretation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from core_database import connect
from core_operations import claim_operation, clean_text, complete_attempt, make_id, now_utc_iso, stable_json


CAPTURE_TYPES = {
    "begin_day_checklist", "end_of_day_report", "voice_debrief",
    "user_note", "user_report", "decision_note", "project_update",
    "research_note", "assistant_report",
}
DAILY_CAPTURE_TYPES = {"begin_day_checklist", "end_of_day_report", "voice_debrief"}
AUTHOR_ROLES = {"user", "assistant"}
CAPTURE_POLICY_VERSION = "chat_capture_v2"
ALLOWED_ASSISTANT_REPORT_TYPES = {
    "daily_intelligence_briefing", "end_of_day_analysis", "architecture_report",
    "decision_packet", "research_report", "project_handoff", "operating_review",
}


def content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def normalize_timestamp(value: Any, field_name: str, *, required: bool) -> str | None:
    raw = clean_text(value)
    if not raw:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware ISO-8601")
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_date_for_capture(capture: dict[str, Any]) -> str:
    basis = capture.get("occurred_at") or capture.get("captured_at")
    if not basis:
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    return datetime.fromisoformat(str(basis).replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat()


def row_to_capture(row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = load_json(data.pop("metadata_json", "{}"), {})
    return data


def row_to_day_case(row) -> dict[str, Any]:
    data = dict(row)
    data["progress"] = load_json(data.pop("progress_json", "{}"), {})
    return data


def infer_capture_request(raw_text: str, *, author_role: str = "user") -> dict[str, Any]:
    """Return a conservative capture decision for a chat message."""
    text = str(raw_text or "").strip()
    lowered = text.lower()
    if re.match(r"^(don't|do not)\s+save\s+this\s*:", lowered):
        return {"capture": False, "reason": "explicit_opt_out"}
    if lowered.startswith(("note:", "save this:")):
        return {"capture": True, "capture_type": "assistant_report" if author_role == "assistant" else "user_note", "reason": "explicit_force_capture"}
    if author_role == "assistant":
        return {"capture": False, "reason": "ordinary_assistant_answer"}
    patterns = (
        ("begin-day checklist", "begin_day_checklist"),
        ("beginning of day", "begin_day_checklist"),
        ("morning checklist", "begin_day_checklist"),
        ("end of day report", "end_of_day_report"),
        ("daily dump", "end_of_day_report"),
        ("eod report", "end_of_day_report"),
        ("voice debrief", "voice_debrief"),
        ("post-event debrief", "voice_debrief"),
    )
    for marker, capture_type in patterns:
        if marker in lowered:
            return {"capture": True, "capture_type": capture_type, "reason": "recognized_daily_capture"}
    return {"capture": False, "reason": "ordinary_conversation"}


def validate_capture_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("capture payload must be a JSON object")
    raw_text = str(payload.get("raw_text") or "")
    if not raw_text.strip():
        raise ValueError("raw_text is required")
    source = clean_text(payload.get("source") or "chatgpt")
    if source != "chatgpt":
        raise ValueError("source must be chatgpt for this phase")
    idempotency_key = clean_text(payload.get("idempotency_key"))
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    request_id = clean_text(payload.get("request_id"))
    if not request_id:
        raise ValueError("request_id is required")
    try:
        payload_version = int(payload.get("payload_version") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload_version must be an integer") from exc
    if payload_version < 1:
        raise ValueError("payload_version must be positive")
    captured_at = normalize_timestamp(payload.get("captured_at"), "captured_at", required=True)
    occurred_at = normalize_timestamp(payload.get("occurred_at"), "occurred_at", required=False)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    author_role = clean_text(metadata.get("author_role") or payload.get("author_role") or "user")
    if author_role not in AUTHOR_ROLES:
        raise ValueError("author_role must be user or assistant")
    inferred = infer_capture_request(raw_text, author_role=author_role)
    capture_type = clean_text(payload.get("capture_type") or inferred.get("capture_type") or "user_note")
    if capture_type not in CAPTURE_TYPES:
        raise ValueError("capture_type is required or must be a supported chat capture class")
    explicit_type = bool(payload.get("capture_type"))
    report_type = clean_text(metadata.get("report_type") or payload.get("report_type"))
    durable_output = bool(metadata.get("durable_output") or payload.get("durable_output"))
    if author_role == "assistant" and (durable_output or report_type in ALLOWED_ASSISTANT_REPORT_TYPES):
        inferred = {"capture": True, "capture_type": "assistant_report", "reason": "explicit_durable_output"}
        if not explicit_type:
            capture_type = "assistant_report"
    elif explicit_type and inferred.get("reason") in {"ordinary_conversation", "ordinary_assistant_answer"}:
        inferred = {"capture": True, "capture_type": capture_type, "reason": "explicit_caller_classification"}
    metadata = {
        **metadata,
        "author_role": author_role,
        "capture_reason": inferred.get("reason"),
        "capture_policy_version": CAPTURE_POLICY_VERSION,
    }
    if author_role == "assistant":
        metadata.setdefault("generation_timestamp", captured_at)
        metadata.setdefault("report_type", report_type or "durable_assistant_report")
    return {
        "capture_type": capture_type,
        "source": source,
        "raw_text": raw_text,
        "content_hash": content_hash(raw_text),
        "occurred_at": occurred_at,
        "occurred_precision": "datetime" if occurred_at else "unknown",
        "captured_at": captured_at,
        "conversation_id": clean_text(payload.get("conversation_id")) or None,
        "message_id": clean_text(payload.get("message_id")) or None,
        "request_id": request_id,
        "correlation_id": clean_text(payload.get("correlation_id")) or None,
        "idempotency_key": idempotency_key,
        "payload_version": payload_version,
        "metadata": metadata,
        "capture_decision": inferred,
    }


def _insert_link(conn, *, capture_id: str, day_case_id: str | None, namespace: str, record_type: str, record_id: str, relationship: str, metadata: dict[str, Any] | None = None) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO core_capture_derivations (
            derivation_id, capture_id, day_case_id, derived_namespace,
            derived_record_type, derived_record_id, relationship, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            make_id("DRV"),
            capture_id,
            day_case_id,
            namespace,
            record_type,
            record_id,
            relationship,
            stable_json(metadata or {}),
        ),
    )


def _derived_record_ids(conn, capture_id: str) -> dict[str, list[str]]:
    rows = conn.execute(
        "SELECT derived_record_type, derived_record_id FROM core_capture_derivations WHERE capture_id=? ORDER BY created_at, derivation_id",
        (capture_id,),
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["derived_record_type"], []).append(row["derived_record_id"])
    return result


def _get_or_create_day_case(conn, capture: dict[str, Any], *, now: str) -> dict[str, Any]:
    local_date = local_date_for_capture(capture)
    row = conn.execute(
        "SELECT * FROM core_day_cases WHERE owner_system_id='sys_info_analyzer' AND local_date=?",
        (local_date,),
    ).fetchone()
    if not row:
        day_case_id = make_id("DAY")
        conn.execute(
            """
            INSERT INTO core_day_cases (
                day_case_id, owner_system_id, local_date, timezone, status,
                summary, progress_json, created_at, updated_at
            ) VALUES (?, 'sys_info_analyzer', ?, 'America/Los_Angeles', 'open', ?, '{}', ?, ?)
            """,
            (day_case_id, local_date, f"Daily loop for {local_date}", now, now),
        )
        row = conn.execute("SELECT * FROM core_day_cases WHERE day_case_id=?", (day_case_id,)).fetchone()
    return row_to_day_case(row)


def _extract_bullets(raw_text: str) -> list[str]:
    lines = []
    for line in raw_text.splitlines():
        cleaned = re.sub(r"^[-*#\\d.\\s]+", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines[:12]


def extract_explicit_actions(raw_text: str, capture_type: str) -> list[dict[str, str]]:
    """Extract only text with an explicit action signal and retain its evidence span."""
    actions: list[dict[str, str]] = []
    explicit = re.compile(
        r"^(?:action|next action|next step|todo|to-do|follow[- ]?up|commitment|plan|i will|we will|must|should)\s*[:\-]?\s*(.+)$",
        re.IGNORECASE,
    )
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        candidate = re.sub(r"^[-*#\d.\s]+", "", line).strip()
        match = explicit.match(candidate)
        if capture_type == "begin_day_checklist" and candidate and not re.search(r"\b(blocker|blocked|risk|note)\b", candidate, re.IGNORECASE):
            match = match or re.match(r"(.+)", candidate)
        if match:
            phrase = (match.group(1) if match.lastindex else match.group(0)).strip()
            if phrase and not re.match(r"^(no action|none|n/?a)\b", phrase, re.IGNORECASE):
                actions.append({"phrase": phrase, "source_span": line})
    return actions[:12]


def _progress_for(day_case: dict[str, Any], capture: dict[str, Any], bullets: list[str]) -> dict[str, Any]:
    current = dict(day_case.get("progress") or {})
    evidence = current.get("evidence_capture_ids") or []
    if capture["capture_id"] not in evidence:
        evidence.append(capture["capture_id"])
    current.update(
        {
            "overarching_goal": current.get("overarching_goal") or "Move important information into a decision/action loop.",
            "current_short_term_milestone": bullets[0] if bullets else current.get("current_short_term_milestone") or "Review today's captured evidence.",
            "validated_milestones": current.get("validated_milestones") or [],
            "unvalidated_milestones": bullets[1:6],
            "blocker": next((b for b in bullets if "block" in b.lower() or "stuck" in b.lower()), ""),
            "evidence_capture_ids": evidence,
            "smallest_next_validated_state_transition": "Review linked capture evidence and mark one planned/observed item as validated.",
        }
    )
    return current


def ingest_capture(database_path, payload: dict[str, Any], *, process: bool = True, worker_id: str = "capture-ingest") -> dict[str, Any]:
    normalized = validate_capture_payload(payload)
    if not normalized["capture_decision"].get("capture", True) and (
        not payload.get("capture_type") or normalized["capture_decision"].get("reason") == "explicit_opt_out"
    ):
        return {"ok": True, "captured": False, "duplicate": False, "status": "not_captured", "reason": normalized["capture_decision"]["reason"]}
    operation_payload = {k: normalized[k] for k in sorted(normalized) if k not in {"metadata", "capture_decision"}}
    operation_payload["metadata"] = normalized["metadata"]
    now = now_utc_iso()
    with connect(database_path) as conn:
        claimed = claim_operation(
            conn,
            operation_type="ingest_capture",
            operation_key=f"{normalized['source']}:{normalized['idempotency_key']}",
            request_payload=operation_payload,
            worker_id=worker_id,
            source_system_id="sys_info_analyzer",
            subject_namespace="core",
            subject_type="capture",
            subject_id=normalized["idempotency_key"],
            immutable_payload=True,
            now=now,
        )
        if claimed["idempotent"]:
            result = claimed["operation"].get("result") or {}
            row = conn.execute("SELECT * FROM core_captures WHERE capture_id=?", (result.get("capture_id"),)).fetchone()
            capture = row_to_capture(row) if row else None
            derived = _derived_record_ids(conn, result.get("capture_id")) if result.get("capture_id") else {}
            return {
                "ok": True,
                "duplicate": True,
                "capture": capture,
                "capture_id": result.get("capture_id"),
                "operation_id": claimed["operation"]["operation_id"],
                "attempt_id": None,
                "status": claimed["operation"]["status"],
                "content_hash": result.get("content_hash"),
                "processing_job_id": result.get("processing_job_id"),
                "derived_record_ids": derived,
            }
        capture_id = make_id("CAP")
        try:
            conn.execute(
                """
                INSERT INTO core_captures (
                    capture_id, capture_type, source, conversation_id, message_id,
                    request_id, correlation_id, idempotency_key, payload_version,
                    raw_text, content_hash, occurred_at, occurred_precision,
                    captured_at, ingested_at, processing_state, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    capture_id,
                    normalized["capture_type"],
                    normalized["source"],
                    normalized["conversation_id"],
                    normalized["message_id"],
                    normalized["request_id"],
                    normalized["correlation_id"],
                    normalized["idempotency_key"],
                    normalized["payload_version"],
                    normalized["raw_text"],
                    normalized["content_hash"],
                    normalized["occurred_at"],
                    normalized["occurred_precision"],
                    normalized["captured_at"],
                    now,
                    stable_json(normalized["metadata"]),
                    now,
                    now,
                ),
            )
            result = {"capture_id": capture_id, "content_hash": normalized["content_hash"], "processing_job_id": None}
            completed = complete_attempt(
                conn,
                operation_id=claimed["operation"]["operation_id"],
                attempt_id=claimed["attempt"]["attempt_id"],
                worker_id=worker_id,
                status="succeeded",
                result=result,
                result_namespace="core",
                result_type="capture",
                result_id=capture_id,
                now=now,
            )
            conn.commit()
        except Exception as exc:
            if conn.in_transaction:
                conn.rollback()
            raise exc
    processing_result = process_capture(database_path, capture_id, worker_id="capture-worker") if process else None
    with connect(database_path) as conn:
        row = conn.execute("SELECT * FROM core_captures WHERE capture_id=?", (capture_id,)).fetchone()
        capture = row_to_capture(row)
        derived = _derived_record_ids(conn, capture_id)
    return {
        "ok": True,
        "duplicate": False,
        "capture": capture,
        "capture_id": capture_id,
        "operation_id": completed["operation_id"],
        "attempt_id": claimed["attempt"]["attempt_id"],
        "status": completed["status"],
        "content_hash": normalized["content_hash"],
        "processing_job_id": (processing_result or {}).get("operation_id"),
        "day_case_id": (processing_result or {}).get("day_case_id"),
        "signal_id": (processing_result or {}).get("signal_id"),
        "processing": processing_result,
        "derived_record_ids": derived,
    }


def process_capture(database_path, capture_id: str, *, worker_id: str = "capture-worker") -> dict[str, Any]:
    now = now_utc_iso()
    with connect(database_path) as conn:
        row = conn.execute("SELECT * FROM core_captures WHERE capture_id=?", (clean_text(capture_id),)).fetchone()
        if not row:
            raise KeyError("capture not found")
        capture = row_to_capture(row)
        claimed = claim_operation(
            conn,
            operation_type="process_capture",
            operation_key=capture["capture_id"],
            request_payload={"capture_id": capture["capture_id"], "content_hash": capture["content_hash"]},
            worker_id=worker_id,
            source_system_id="sys_info_analyzer",
            subject_namespace="core",
            subject_type="capture",
            subject_id=capture["capture_id"],
            immutable_payload=True,
            now=now,
        )
        if claimed["idempotent"]:
            return {"ok": True, "idempotent": True, "operation_id": claimed["operation"]["operation_id"], **(claimed["operation"].get("result") or {})}
        try:
            conn.execute("UPDATE core_captures SET processing_state='processing', updated_at=? WHERE capture_id=?", (now, capture["capture_id"]))
            day_case = None
            if capture["capture_type"] in DAILY_CAPTURE_TYPES:
                day_case = _get_or_create_day_case(conn, capture, now=now)
            elif capture.get("metadata", {}).get("day_case_id"):
                day_case_row = conn.execute("SELECT * FROM core_day_cases WHERE day_case_id=?", (capture["metadata"]["day_case_id"],)).fetchone()
                if day_case_row:
                    day_case = row_to_day_case(day_case_row)
            bullets = _extract_bullets(capture["raw_text"])
            explicit_actions = extract_explicit_actions(capture["raw_text"], capture["capture_type"])
            signal_id = make_id("SIG")
            signal_type = f"capture_{capture['capture_type']}"
            title = {
                "begin_day_checklist": "Begin-day checklist captured",
                "end_of_day_report": "End-of-day report captured",
                "voice_debrief": "Voice debrief captured",
                "user_note": "User note captured",
                "user_report": "User report captured",
                "decision_note": "Decision note captured",
                "project_update": "Project update captured",
                "research_note": "Research note captured",
                "assistant_report": "Assistant report captured",
            }[capture["capture_type"]]
            summary = bullets[0] if bullets else f"{capture['capture_type']} received from {capture['source']}."
            metadata = {
                "capture_id": capture["capture_id"],
                "content_hash": capture["content_hash"],
                "bullet_count": len(bullets),
                "bullets": bullets,
                "interpretation_status": "deterministic_initial_pass",
                "capture_reason": capture.get("metadata", {}).get("capture_reason"),
                "capture_policy_version": capture.get("metadata", {}).get("capture_policy_version"),
                "explicit_action_count": len(explicit_actions),
            }
            conn.execute(
                """
                INSERT INTO core_signals (
                    signal_id, owner_system_id, signal_type, title, summary,
                    priority, confidence, actionability_score, status,
                    rationale, recommended_action, detected_at, metadata_json
                ) VALUES (?, 'sys_info_analyzer', ?, ?, ?, 'P2', 0.75, 0.50, 'new', ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    signal_type,
                    title,
                    summary,
                    "Raw capture was preserved and converted into a reviewable daily-loop signal.",
                    "Review the linked capture and confirm the next evidence-backed transition.",
                    capture.get("captured_at") or now,
                    stable_json(metadata),
                ),
            )
            _insert_link(conn, capture_id=capture["capture_id"], day_case_id=day_case["day_case_id"] if day_case else None, namespace="core", record_type="signal", record_id=signal_id, relationship="interpreted_as", metadata={"content_hash": capture["content_hash"]})
            if day_case:
                progress = _progress_for(day_case, capture, bullets)
                updates = ["progress_json=?", "updated_at=?"]
                args: list[Any] = [stable_json(progress), now]
                if capture["capture_type"] == "begin_day_checklist":
                    updates.append("plan_capture_id=COALESCE(plan_capture_id, ?)")
                    args.append(capture["capture_id"])
                if capture["capture_type"] == "end_of_day_report":
                    updates.append("report_capture_id=COALESCE(report_capture_id, ?)")
                    args.append(capture["capture_id"])
                args.append(day_case["day_case_id"])
                conn.execute(f"UPDATE core_day_cases SET {', '.join(updates)} WHERE day_case_id=?", tuple(args))
                _insert_link(conn, capture_id=capture["capture_id"], day_case_id=day_case["day_case_id"], namespace="core", record_type="day_case", record_id=day_case["day_case_id"], relationship="updates_day_case")
            for source_capture_id in capture.get("metadata", {}).get("source_capture_ids", []) or []:
                source_row = conn.execute("SELECT capture_id FROM core_captures WHERE capture_id=?", (clean_text(source_capture_id),)).fetchone()
                if source_row:
                    _insert_link(conn, capture_id=source_row["capture_id"], day_case_id=day_case["day_case_id"] if day_case else None, namespace="core", record_type="capture", record_id=capture["capture_id"], relationship="assistant_report", metadata={"source_capture_id": source_row["capture_id"]})
            for action in explicit_actions:
                action_id = make_id("ACT")
                conn.execute(
                    """
                    INSERT INTO core_actions (
                        action_id, owner_system_id, action_type, title, details,
                        status, execution_mode, assigned_to, metadata_json
                    ) VALUES (?, 'sys_info_analyzer', 'capture_next_step', ?, ?, 'proposed', 'manual', 'user', ?)
                    """,
                    (
                        action_id,
                        "Review captured next step",
                        action["phrase"],
                        stable_json({
                            "capture_id": capture["capture_id"],
                            "source": "capture_interpretation",
                            "source_span": action["source_span"],
                            "extraction_rule": "explicit_action_prefix_v1",
                            "extraction_version": "chat_capture_v2",
                        }),
                    ),
                )
                _insert_link(conn, capture_id=capture["capture_id"], day_case_id=day_case["day_case_id"] if day_case else None, namespace="core", record_type="action", record_id=action_id, relationship="proposes_action")
            conn.execute(
                "UPDATE core_captures SET processing_state='processed', processed_at=?, process_operation_id=?, updated_at=? WHERE capture_id=?",
                (now, claimed["operation"]["operation_id"], now, capture["capture_id"]),
            )
            result = {"capture_id": capture["capture_id"], "day_case_id": day_case["day_case_id"] if day_case else None, "signal_id": signal_id}
            completed = complete_attempt(
                conn,
                operation_id=claimed["operation"]["operation_id"],
                attempt_id=claimed["attempt"]["attempt_id"],
                worker_id=worker_id,
                status="succeeded",
                result=result,
                result_namespace="core",
                result_type="capture_interpretation",
                result_id=capture["capture_id"],
                now=now,
            )
            conn.commit()
            return {"ok": True, "idempotent": False, "operation_id": completed["operation_id"], "derived_record_ids": _derived_record_ids(conn, capture["capture_id"]), **result}
        except Exception as exc:
            conn.execute("UPDATE core_captures SET processing_state='failed', updated_at=? WHERE capture_id=?", (now, capture["capture_id"]))
            complete_attempt(
                conn,
                operation_id=claimed["operation"]["operation_id"],
                attempt_id=claimed["attempt"]["attempt_id"],
                worker_id=worker_id,
                status="failed",
                error={"error": str(exc)},
                now=now,
            )
            conn.commit()
            raise


def get_day_progress(database_path, *, local_date: str | None = None) -> dict[str, Any]:
    with connect(database_path) as conn:
        if local_date:
            row = conn.execute("SELECT * FROM core_day_cases WHERE owner_system_id='sys_info_analyzer' AND local_date=?", (local_date,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM core_day_cases WHERE owner_system_id='sys_info_analyzer' ORDER BY local_date DESC LIMIT 1").fetchone()
        if not row:
            return {"status": "empty", "day_case": None}
        day = row_to_day_case(row)
        links = [dict(r) for r in conn.execute("SELECT * FROM core_capture_derivations WHERE day_case_id=? ORDER BY created_at", (day["day_case_id"],)).fetchall()]
        return {"status": "ok", "day_case": day, "links": links}


def list_captures(database_path, *, conversation_id: str | None = None, local_date: str | None = None, capture_type: str | None = None, project: str | None = None, domain: str | None = None, author_role: str | None = None, include_raw_text: bool = True, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Read bounded capture receipts and lineage without exposing arbitrary SQL."""
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    where = ["1=1"]
    args: list[Any] = []
    if conversation_id:
        where.append("conversation_id=?")
        args.append(clean_text(conversation_id))
    if local_date:
        where.append("substr(COALESCE(occurred_at, captured_at), 1, 10)=?")
        args.append(clean_text(local_date))
    if capture_type:
        where.append("capture_type=?")
        args.append(clean_text(capture_type))
    if author_role:
        where.append("json_extract(metadata_json, '$.author_role')=?")
        args.append(clean_text(author_role))
    for key, value in (("project", project), ("domain", domain)):
        if value:
            where.append("json_extract(metadata_json, '$.' || ?) = ?")
            args.extend([key, clean_text(value)])
    with connect(database_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM core_captures WHERE {' AND '.join(where)} ORDER BY captured_at DESC, created_at DESC, capture_id DESC LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()
        results = []
        for row in rows:
            capture = row_to_capture(row)
            links = [dict(link) for link in conn.execute(
                "SELECT * FROM core_capture_derivations WHERE capture_id=? ORDER BY created_at, derivation_id",
                (capture["capture_id"],),
            ).fetchall()]
            reverse_links = [dict(link) for link in conn.execute(
                "SELECT * FROM core_capture_derivations WHERE derived_record_id=? AND derived_record_type='capture' ORDER BY created_at, derivation_id",
                (capture["capture_id"],),
            ).fetchall()]
            capture["derivations"] = links + reverse_links
            if not include_raw_text:
                capture.pop("raw_text", None)
            results.append(capture)
        total = conn.execute(f"SELECT COUNT(*) FROM core_captures WHERE {' AND '.join(where)}", tuple(args)).fetchone()[0]
    return {"status": "ok" if results else "empty", "captures": results, "count": len(results), "total": total, "limit": limit, "offset": offset, "coverage": ["core_captures", "core_capture_derivations"]}
