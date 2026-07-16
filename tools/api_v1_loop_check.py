#!/usr/bin/env python3
"""Verify the authenticated cross-chat Intelligence Ledger API loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request


def request(base_url: str, method: str, path: str, api_key: str, payload=None, idempotency_key: str = ""):
    url = base_url.rstrip("/") + path
    data = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Source-Client": "api-v1-loop-check",
        "X-Source-Chat": "loop-check-chat",
        "X-Request-ID": f"REQ-{uuid.uuid4()}",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as res:
        body = res.read().decode("utf-8")
        return res.status, json.loads(body or "{}")


def data_from(envelope: dict) -> dict:
    if not {"success", "data", "error", "request_id"}.issubset(envelope):
        raise AssertionError(f"response is not a stable v1 envelope: {envelope}")
    if envelope.get("success") is not True:
        raise AssertionError(f"v1 request failed: {envelope}")
    return envelope.get("data") or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--write-proof", default="")
    args = parser.parse_args()

    nonce = str(int(time.time()))
    raw = (
        f"API v1 cross-chat loop test {nonce}: Chat saves a memory, another chat retrieves it, "
        "acknowledges the returned alert, then logs feedback so the original entry becomes stronger."
    )
    status, health = request(args.base_url, "GET", "/api/v1/health", args.api_key)
    health_data = data_from(health)
    checks = [{"name": "health", "status": status, "ok": health_data.get("ok") is True, "evidence": health}]

    entry_payload = {
        "title": f"API v1 cross-chat loop test {nonce}",
        "raw_input": raw,
        "domain": "Info Analyzer OS",
        "entity": "Authenticated Ledger API",
        "source_type": "chat",
        "source_chat": "api-v1-loop-check",
        "source_input": "tools/api_v1_loop_check.py",
        "signal": "Authenticated API can write structured chat memory into the Intelligence Ledger.",
        "interpretation": "The API is the live bridge between chats and SQLite memory.",
        "signal_role": "risk",
        "actionability": "now",
        "trackable_as": "acceptance_test",
        "tracking_metric": "Entry saved, retrieved, alert acknowledged, feedback logged.",
        "returned_action": "Complete the authenticated API cross-chat loop and record the result.",
        "first_step": "Search for the saved nonce from a separate API call.",
        "impact_metric": "Cross-chat memory continuity proven.",
        "feedback_to_capture": "Whether write, retrieve, act, and learn all completed.",
        "tags": ["api-v1", "cross-chat", "acceptance-test", "memory-bridge"],
    }
    status, saved = request(args.base_url, "POST", "/api/v1/entries", args.api_key, entry_payload, f"entry-{nonce}")
    saved_data = data_from(saved)
    status, replay = request(args.base_url, "POST", "/api/v1/entries", args.api_key, entry_payload, f"entry-{nonce}")
    replay_data = data_from(replay)
    entry_id = saved_data.get("entry_id")
    action_id = (saved_data.get("action") or {}).get("id")
    checks.append({"name": "write", "status": status, "ok": bool(entry_id and action_id), "evidence": {"entry_id": entry_id, "action_id": action_id, "envelope_request_id": saved.get("request_id")}})
    checks.append({"name": "idempotency_replay", "status": status, "ok": replay_data.get("entry_id") == entry_id, "evidence": {"entry_id": entry_id, "replay_entry_id": replay_data.get("entry_id")}})

    query = urllib.parse.urlencode({"q": nonce, "domain": "Info Analyzer OS", "limit": 10})
    status, search = request(args.base_url, "GET", f"/api/v1/entries/search?{query}", args.api_key)
    search_data = data_from(search)
    found = any(row.get("id") == entry_id for row in search_data.get("entries", []))
    checks.append({"name": "retrieve", "status": status, "ok": found, "evidence": {"count": search_data.get("count"), "entry_id": entry_id}})

    status, alerts = request(args.base_url, "GET", "/api/v1/critical_alerts?limit=20", args.api_key)
    alerts_data = data_from(alerts)
    alert = next((item for item in alerts_data.get("alerts", []) if item.get("id") == action_id), None)
    checks.append({"name": "critical_alert", "status": status, "ok": bool(alert), "evidence": alert or alerts})

    status, ack = request(args.base_url, "PATCH", f"/api/v1/alerts/{action_id}/acknowledge", args.api_key, {
        "status": "waiting",
        "note": "Acknowledged by API v1 loop check; feedback result pending.",
    }, f"ack-{nonce}")
    ack_data = data_from(ack)
    checks.append({"name": "acknowledge", "status": status, "ok": bool(ack_data.get("alert_id")), "evidence": ack})

    status, feedback = request(args.base_url, "POST", "/api/v1/feedback", args.api_key, {
        "entry_id": entry_id,
        "action_id": action_id,
        "status": "done",
        "result": "Authenticated API loop completed: write, retrieve, acknowledge, and feedback all passed.",
        "lesson": "The API is the correct live connection layer for cross-chat intelligence.",
        "confidence": "High",
        "playbook_relationship": "validates",
    }, f"feedback-{nonce}")
    feedback_data = data_from(feedback)
    checks.append({"name": "learn", "status": status, "ok": bool(feedback_data.get("entry")), "evidence": {"entry_id": entry_id, "action_id": action_id, "request_id": feedback.get("request_id")}})

    passed = sum(1 for check in checks if check["ok"])
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "summary": {"passed": passed, "failed": len(checks) - passed, "total": len(checks)},
        "entry_id": entry_id,
        "action_id": action_id,
        "checks": checks,
        "status": "pass" if passed == len(checks) else "fail",
    }
    print(json.dumps(result, indent=2))
    if args.write_proof:
        path = Path(args.write_proof)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
