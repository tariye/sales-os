#!/usr/bin/env python3
"""Verify the authenticated cross-chat Intelligence Ledger API loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


def request(base_url: str, method: str, path: str, api_key: str, payload=None):
    url = base_url.rstrip("/") + path
    data = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as res:
        body = res.read().decode("utf-8")
        return res.status, json.loads(body or "{}")


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
    checks = [{"name": "health", "status": status, "ok": health.get("ok") is True, "evidence": health}]

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
    status, saved = request(args.base_url, "POST", "/api/v1/entries", args.api_key, entry_payload)
    entry_id = saved.get("entry_id")
    action_id = (saved.get("action") or {}).get("id")
    checks.append({"name": "write", "status": status, "ok": bool(entry_id and action_id), "evidence": {"entry_id": entry_id, "action_id": action_id}})

    query = urllib.parse.urlencode({"q": nonce, "domain": "Info Analyzer OS", "limit": 10})
    status, search = request(args.base_url, "GET", f"/api/v1/entries/search?{query}", args.api_key)
    found = any(row.get("id") == entry_id for row in search.get("entries", []))
    checks.append({"name": "retrieve", "status": status, "ok": found, "evidence": {"count": search.get("count"), "entry_id": entry_id}})

    status, alerts = request(args.base_url, "GET", "/api/v1/critical_alerts?limit=20", args.api_key)
    alert = next((item for item in alerts.get("alerts", []) if item.get("id") == action_id), None)
    checks.append({"name": "critical_alert", "status": status, "ok": bool(alert), "evidence": alert or alerts})

    status, ack = request(args.base_url, "PATCH", f"/api/v1/alerts/{action_id}/acknowledge", args.api_key, {
        "status": "waiting",
        "note": "Acknowledged by API v1 loop check; feedback result pending.",
    })
    checks.append({"name": "acknowledge", "status": status, "ok": ack.get("success") is True, "evidence": ack})

    status, feedback = request(args.base_url, "POST", "/api/v1/feedback", args.api_key, {
        "entry_id": entry_id,
        "action_id": action_id,
        "status": "done",
        "result": "Authenticated API loop completed: write, retrieve, acknowledge, and feedback all passed.",
        "lesson": "The API is the correct live connection layer for cross-chat intelligence.",
        "confidence": "High",
        "playbook_relationship": "validates",
    })
    checks.append({"name": "learn", "status": status, "ok": feedback.get("success") is True, "evidence": {"entry_id": entry_id, "action_id": action_id}})

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
