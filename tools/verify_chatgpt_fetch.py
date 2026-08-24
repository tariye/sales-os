#!/usr/bin/env python3
"""Verify ChatGPT can fetch the assistant bundle from an immutable git commit."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


REQUIRED_SECTIONS = [
    "schema_version",
    "generated_at",
    "export_run_id",
    "source_of_truth",
    "export_success",
    "privacy_validation_passed",
    "current_context",
    "weekend_clarity",
    "active_projects",
    "top_actions",
    "active_decisions",
    "active_patterns",
    "watchlist",
    "recent_lessons",
    "recent_activity",
    "accountability_state",
    "critical_alerts",
    "briefing_priorities",
    "weekly_only_topics",
    "exclude_unless_material",
]


def parse_time(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def git_stdout(*args: str) -> str:
    proc = subprocess.run(["git", *args], check=True, text=True, capture_output=True)
    return proc.stdout.strip()


def git_show_json(revision: str, path: str) -> dict:
    payload = git_stdout("show", f"{revision}:{path}")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError(f"{revision}:{path} did not contain a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--bundle-path", default="memory/assistant_bundle.json")
    parser.add_argument("--health-path", default="memory/system_health.json")
    parser.add_argument("--fetch-path", default="memory/assistant_fetch.json")
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--max-bytes", type=int, default=150000)
    args = parser.parse_args()

    try:
        remote_head = git_stdout("ls-remote", args.remote, f"refs/heads/{args.branch}").split()[0]
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": f"git ls-remote failed: {exc}"}, indent=2))
        return 1
    try:
        git_stdout("fetch", args.remote, args.branch, "--prune")
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": f"git fetch failed: {exc}", "remote_head": remote_head}, indent=2))
        return 1

    try:
        fetch_meta = git_show_json(f"{args.remote}/{args.branch}", args.fetch_path)
        immutable_commit = str(fetch_meta.get("immutable_commit") or "")
        bundle = git_show_json(immutable_commit, args.bundle_path)
        health = git_show_json(f"{args.remote}/{args.branch}", args.health_path)
    except Exception as exc:
        print(json.dumps({"status": "fail", "remote_head": remote_head, "error": str(exc)}, indent=2))
        return 1

    errors: list[str] = []
    bundle_bytes = json.dumps(bundle, sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(bundle_bytes) > args.max_bytes:
        errors.append(f"bundle exceeds {args.max_bytes} bytes")
    for section in REQUIRED_SECTIONS:
        if section not in bundle:
            errors.append(f"missing section: {section}")
    if bundle.get("export_success") is not True:
        errors.append("bundle export_success is not true")
    if bundle.get("privacy_validation_passed") is not True:
        errors.append("privacy_validation_passed is not true")
    if fetch_meta.get("publication_status") != "green":
        errors.append("assistant_fetch publication_status is not green")
    if fetch_meta.get("immutable_commit") != immutable_commit:
        errors.append("assistant_fetch immutable_commit missing or mismatched")
    if health.get("overall_status") not in {"green", "yellow"}:
        errors.append("system_health overall_status is not green or yellow")
    if health.get("publication", {}).get("immutable_commit") != immutable_commit:
        errors.append("system_health publication immutable_commit does not match assistant_fetch immutable_commit")
    if health.get("publication", {}).get("status") != "green":
        errors.append("system_health publication status is not green")
    if not any(item.get("id") == "CHATGPT-FETCH-TEST-202607" for item in bundle.get("recent_activity", [])):
        errors.append("acceptance-test record missing")
    generated_at = parse_time(str(bundle.get("generated_at") or ""))
    age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600
    if age_hours > args.max_age_hours:
        errors.append(f"bundle age {age_hours:.2f}h exceeds {args.max_age_hours}h")
    remote_bundle = git_show_json(immutable_commit, args.bundle_path)
    if remote_bundle != bundle:
        errors.append("bundle content read from immutable_commit does not match parsed bundle")

    result = {
        "status": "pass" if not errors else "fail",
        "remote": args.remote,
        "branch": args.branch,
        "remote_head": remote_head,
        "immutable_commit": immutable_commit,
        "bundle_bytes": len(bundle_bytes),
        "generated_at": bundle.get("generated_at"),
        "age_hours": round(age_hours, 3),
        "export_success": bundle.get("export_success"),
        "privacy_validation_passed": bundle.get("privacy_validation_passed"),
        "assistant_fetch": fetch_meta,
        "project_count": len(bundle.get("active_projects", [])),
        "action_count": len(bundle.get("top_actions", [])),
        "decision_count": len(bundle.get("active_decisions", [])),
        "pattern_count": len(bundle.get("active_patterns", [])),
        "watch_count": len(bundle.get("watchlist", [])),
        "health": health,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
