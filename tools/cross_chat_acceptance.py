#!/usr/bin/env python3
"""Run the production cross-chat acceptance test for the Info Analyzer API."""
from __future__ import annotations

import argparse
import json
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def request(base_url: str, method: str, path: str, api_key: str, payload=None, source_chat="acceptance-chat", idem=""):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Source-Client": "cross-chat-acceptance",
        "X-Source-Chat": source_chat,
        "X-Request-ID": f"REQ-{uuid.uuid4()}",
    }
    if idem:
        headers["Idempotency-Key"] = idem
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status, json.loads(res.read().decode("utf-8") or "{}")


def request_expect_error(base_url: str, method: str, path: str, api_key: str):
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        return {"status": 200, "body": {}}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "body": json.loads(exc.read().decode("utf-8") or "{}")}


def data_from(envelope: dict) -> dict:
    if not {"success", "data", "error", "request_id"}.issubset(envelope):
        raise AssertionError(f"response is not a stable envelope: {envelope}")
    if envelope["success"] is not True:
        raise AssertionError(f"request failed: {envelope}")
    return envelope["data"] or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--write-proof", default="")
    parser.add_argument("--allow-local", action="store_true")
    args = parser.parse_args()

    parsed = urlparse(args.base_url)
    if not args.allow_local and (parsed.scheme != "https" or parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0"}):
        raise SystemExit("cross_chat_acceptance requires HTTPS non-local base URL unless --allow-local is set")

    nonce = str(int(time.time()))
    checks = []

    status, health_env = request(args.base_url, "GET", "/api/v1/health", args.api_key, source_chat="chat-a")
    health = data_from(health_env)
    sqlite_state = health.get("sqlite") or {}
    checks.append({
        "name": "health_runtime",
        "ok": status == 200 and health.get("ok") is True and sqlite_state.get("journal_mode") == "wal" and sqlite_state.get("foreign_keys") is True and int(sqlite_state.get("busy_timeout_ms") or 0) >= 5000,
        "evidence": health,
    })

    chat_a_payload = {
        "title": f"Cross-chat operator setup test {nonce}",
        "raw_input": "Repeated operator setup errors continue after verbal coaching.",
        "domain": "Lab",
        "entity": "Operator setup training",
        "source_type": "chat",
        "source_client": "chatgpt",
        "source_chat": "chat-a",
        "signal": "The knowledge-transfer system is inconsistent.",
        "signal_role": "risk",
        "interpretation": "Verbal coaching is not reliably transferring setup knowledge into repeatable behavior.",
        "returned_action": "Test a visual setup checklist during the next onboarding rep.",
        "first_step": "Draft the setup checklist and use it on the next onboarding repetition.",
        "trackable_as": "behavior + outcome metric",
        "tracking_metric": "Setup errors and independent completion time.",
        "impact_metric": "Reduced setup errors, reduced coaching intervention, and faster independent completion.",
        "feedback_to_capture": "Error count before/after checklist and coaching interventions required.",
        "tags": ["operator setup", "training bottleneck", "knowledge transfer", "checklist", f"acceptance-{nonce}"],
    }
    idem = f"chat-a-entry-{nonce}"
    status, created_env = request(args.base_url, "POST", "/api/v1/entries", args.api_key, chat_a_payload, source_chat="chat-a", idem=idem)
    created = data_from(created_env)
    status, replay_env = request(args.base_url, "POST", "/api/v1/entries", args.api_key, chat_a_payload, source_chat="chat-a", idem=idem)
    replay = data_from(replay_env)
    entry_id = created.get("entry_id")
    action_id = (created.get("action") or {}).get("id")
    checks.append({"name": "cross_chat_write", "ok": bool(entry_id and action_id), "evidence": {"entry_id": entry_id, "action_id": action_id}})
    checks.append({"name": "idempotency_replay", "ok": replay.get("entry_id") == entry_id, "evidence": {"entry_id": entry_id, "replay_entry_id": replay.get("entry_id")}})

    query = urllib.parse.urlencode({"q": f"operator setup knowledge transfer acceptance-{nonce}", "domain": "Lab", "limit": 20})
    status, search_env = request(args.base_url, "GET", f"/api/v1/entries/search?{query}", args.api_key, source_chat="chat-b")
    search = data_from(search_env)
    found = next((row for row in search.get("entries", []) if row.get("id") == entry_id), None)
    metadata = (found or {}).get("metadata") or {}
    checks.append({
        "name": "cross_chat_retrieval",
        "ok": bool(found and metadata.get("source_chat") == "chat-a"),
        "evidence": {"count": search.get("count"), "entry_id": entry_id, "source_chat": metadata.get("source_chat")},
    })

    status, context_env = request(args.base_url, "POST", "/api/v1/context", args.api_key, {
        "raw_input": "operator setup errors, training bottlenecks, and knowledge-transfer problems",
        "domain": "Lab",
        "entity": "Operator setup training",
        "tags": ["operator setup", "training bottleneck", "knowledge transfer"],
    }, source_chat="chat-b", idem=f"chat-b-context-{nonce}")
    context = data_from(context_env)
    checks.append({"name": "related_context", "ok": bool(context), "evidence": {"keys": sorted(context.keys())[:12]}})

    status, alerts_env = request(args.base_url, "GET", "/api/v1/critical_alerts?limit=50", args.api_key, source_chat="chat-b")
    alerts = data_from(alerts_env)
    alert = next((item for item in alerts.get("alerts", []) if item.get("id") == action_id), None)
    checks.append({"name": "alert_returned", "ok": bool(alert), "evidence": alert or {"alert_count": alerts.get("count")}})

    status, ack_env = request(args.base_url, "PATCH", f"/api/v1/alerts/{action_id}/acknowledge", args.api_key, {
        "status": "waiting",
        "note": "Chat B acknowledged the training-system alert and converted it into a tracked checklist action.",
    }, source_chat="chat-b", idem=f"chat-b-ack-{nonce}")
    ack = data_from(ack_env)
    checks.append({"name": "alert_acknowledgement", "ok": ack.get("alert_id") == action_id, "evidence": {"alert_id": ack.get("alert_id"), "type": ack.get("type")}})

    status, feedback_env = request(args.base_url, "POST", "/api/v1/feedback", args.api_key, {
        "entry_id": entry_id,
        "action_id": action_id,
        "status": "done",
        "result": "The visual checklist reduced setup errors from three to one and reduced coaching intervention.",
        "lesson": "Visual setup checklists strengthen knowledge transfer when verbal coaching is inconsistent.",
        "confidence": "High",
        "playbook_relationship": "validates",
    }, source_chat="chat-c", idem=f"chat-c-feedback-{nonce}")
    feedback = data_from(feedback_env)
    checks.append({"name": "feedback_loop", "ok": bool(feedback.get("entry")), "evidence": {"entry_id": entry_id, "action_id": action_id}})

    bad = request_expect_error(args.base_url, "GET", "/api/v1/health", "invalid-key")
    checks.append({
        "name": "security_invalid_key",
        "ok": bad["status"] == 401 and bad["body"].get("success") is False and (bad["body"].get("error") or {}).get("code") == "unauthorized",
        "evidence": bad,
    })

    passed = sum(1 for check in checks if check["ok"])
    result = {
        "generated_at": now_iso(),
        "base_url": args.base_url,
        "entry_id": entry_id,
        "action_id": action_id,
        "summary": {"passed": passed, "failed": len(checks) - passed, "total": len(checks)},
        "checks": checks,
        "status": "pass" if passed == len(checks) else "fail",
    }
    print(json.dumps(result, indent=2))
    if args.write_proof:
        proof = Path(args.write_proof)
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
