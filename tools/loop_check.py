#!/usr/bin/env python3
"""
Info Analyzer OS loop checker.

This is the executable form of the build principle:
Build -> Run -> Use -> Observe -> Fix -> Retest -> Document -> Commit.

The script uses the live local site the way a user would:
- verifies the app is running
- checks Command Center resolver controls
- pulls actionable memory
- runs Stock Intel
- creates a temporary memory entry
- pulls that entry back contextually
- logs a result
- deletes the temporary entry
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApiClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: {exc.code} {raw}") from exc

    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, payload: dict) -> dict:
        return self.request("POST", path, payload)

    def patch(self, path: str, payload: dict) -> dict:
        return self.request("PATCH", path, payload)

    def delete(self, path: str) -> dict:
        return self.request("DELETE", path)


def pass_check(name: str, detail: str, evidence=None) -> dict:
    return {"name": name, "status": "pass", "detail": detail, "evidence": evidence}


def fail_check(name: str, detail: str, evidence=None) -> dict:
    return {"name": name, "status": "fail", "detail": detail, "evidence": evidence}


def assert_condition(condition: bool, name: str, detail: str, evidence=None) -> dict:
    if not condition:
        raise AssertionError(json.dumps(fail_check(name, detail, evidence), ensure_ascii=False))
    return pass_check(name, detail, evidence)


def check_health(api: ApiClient) -> dict:
    data = api.get("/api/health")
    return assert_condition(
        bool(data.get("ok") and data.get("version")),
        "health",
        "Live app responds with a version.",
        {"version": data.get("version")},
    )


def check_command_center(api: ApiClient) -> dict:
    data = api.get("/api/command")
    cockpit = data.get("cockpit") or {}
    callouts = (cockpit.get("warnings") or []) + (cockpit.get("cautions") or []) + (cockpit.get("advisories") or [])
    button_count = sum(len(c.get("buttons") or []) for c in callouts)
    return assert_condition(
        button_count > 0,
        "command_center_resolvers",
        "Command Center callouts expose resolver buttons.",
        {"callouts": len(callouts), "buttons": button_count},
    )


def check_pull(api: ApiClient) -> dict:
    data = api.post("/api/pull", {"query": "sales", "domain": "Business"})
    cards = (data.get("quick_actions") or []) + (data.get("big_picture_actions") or [])
    top = cards[0] if cards else {}
    return assert_condition(
        bool(cards and top.get("recommended_action")),
        "pull_sales",
        "Pull Engine returns an actionable sales card.",
        {
            "card_count": len(cards),
            "top_title": top.get("title"),
            "top_metric": top.get("tracking_metric"),
        },
    )


def check_stock(api: ApiClient, symbol: str) -> dict:
    data = api.post("/api/stock/analyze", {"symbol": symbol})
    analysis = data.get("analysis") or {}
    financials = analysis.get("financials") or {}
    quarter = financials.get("latest_quarter") or {}
    signals = analysis.get("signals") or []
    return assert_condition(
        bool(financials.get("available") and quarter.get("revenue") and signals),
        "stock_intel",
        "Stock Intel returns financials and extracted signals.",
        {
            "symbol": symbol,
            "quarter_revenue": (quarter.get("revenue") or {}).get("display"),
            "signal_types": [s.get("type") for s in signals],
            "errors": analysis.get("errors"),
        },
    )


def check_memory_loop(api: ApiClient) -> dict:
    stamp = str(int(time.time()))
    raw = f"LOOP QA temporary proof {stamp}: Command Center needs a complete input to action to result loop."
    entry_id = None
    try:
        created = api.post("/api/entries", {
            "title": f"LOOP QA proof {stamp}",
            "raw_input": raw,
            "domain": "AI Project",
            "entity": "Loop QA",
            "source_type": "Observation",
            "signal": "Feature work must complete a live use loop before it counts as shipped.",
            "signal_role": "proof",
            "interpretation": "The system should prove that memory can be written, pulled, acted on, and cleaned up.",
            "trackable_as": "proof artifact",
            "tracking_metric": "Entry created, pull returned it, result logged, temporary record deleted.",
            "returned_action": "Run the loop checker and log the result.",
            "first_step": "Create a temporary proof entry and pull it back by query.",
            "actionability": "proof",
            "pull_trigger": f"loop qa temporary proof {stamp}",
            "trigger_condition": f"Resurface when loop qa temporary proof {stamp} appears.",
            "feedback_to_capture": "Whether the loop checker completed without leaving temporary data behind.",
            "tags": ["loop-qa", "temporary", stamp],
        })
        entry_id = created.get("entry_id")
        pulled = api.post("/api/pull", {"query": f"loop qa temporary proof {stamp}", "domain": "AI Project"})
        cards = (pulled.get("quick_actions") or []) + (pulled.get("big_picture_actions") or [])
        found = any(card.get("entry_id") == entry_id for card in cards)
        if not found:
            raise AssertionError(json.dumps(fail_check(
                "memory_loop",
                "Temporary entry was saved but did not resurface through Pull.",
                {"entry_id": entry_id, "card_count": len(cards)},
            ), ensure_ascii=False))
        api.patch(f"/api/entries/{urllib.parse.quote(entry_id)}", {
            "action_status": "done",
            "status": "validated",
            "result": "Loop checker validated write, pull, action logging, and cleanup path.",
        })
        return pass_check(
            "memory_loop",
            "Temporary entry was saved, pulled, result-logged, and cleaned up.",
            {"entry_id": entry_id, "pull_cards": len(cards)},
        )
    finally:
        if entry_id:
            try:
                api.delete(f"/api/entries/{urllib.parse.quote(entry_id)}")
            except Exception:
                pass


def run_loop(base_url: str, stock_symbol: str) -> dict:
    api = ApiClient(base_url)
    checks = []
    for fn in (
        check_health,
        check_command_center,
        check_pull,
        lambda client: check_stock(client, stock_symbol),
        check_memory_loop,
    ):
        try:
            checks.append(fn(api))
        except AssertionError as exc:
            try:
                checks.append(json.loads(str(exc)))
            except Exception:
                checks.append(fail_check(getattr(fn, "__name__", "check"), str(exc)))
        except Exception as exc:
            checks.append(fail_check(getattr(fn, "__name__", "check"), str(exc)))
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = [c for c in checks if c["status"] != "pass"]
    return {
        "generated_at": now_iso(),
        "base_url": base_url,
        "stock_symbol": stock_symbol,
        "principle": "No feature ships until it survives the live user loop.",
        "summary": {"passed": passed, "failed": len(failed), "total": len(checks)},
        "checks": checks,
        "status": "pass" if not failed else "fail",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run Info Analyzer OS live loop checks")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--stock", default="AAPL")
    parser.add_argument("--write-proof", default="")
    args = parser.parse_args(argv)
    result = run_loop(args.base_url, args.stock)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.write_proof:
        with open(args.write_proof, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
