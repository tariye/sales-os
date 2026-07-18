#!/usr/bin/env python3
"""Verify ChatGPT can fetch the assistant bundle from an immutable GitHub SHA."""
from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


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
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return parsedate_to_datetime(value).astimezone(timezone.utc)


def fetch_url(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "info-analyzer-fetch-verifier"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read(), ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), str(exc)
    except urllib.error.URLError as exc:
        # Some local Python installs lack a current certificate bundle. Retry only for
        # certificate-store failures so the verifier remains usable on clean servers.
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            return 0, b"", str(exc)
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=context) as res:  # noqa: S323
            return res.status, res.read(), "certificate verification fallback used"


def fetch_contents_api(repo: str, sha: str, path: str) -> tuple[int, bytes, str]:
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={sha}"
    status, body, error = fetch_url(url)
    if status != 200:
        return status, body, error
    payload = json.loads(body.decode("utf-8"))
    content = base64.b64decode(str(payload.get("content") or ""))
    return status, content, error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="tariye/sales-os")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--bundle-path", default="memory/assistant_bundle.json")
    parser.add_argument("--health-path", default="memory/system_health.json")
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument("--max-bytes", type=int, default=150000)
    args = parser.parse_args()

    branch_url = f"https://api.github.com/repos/{args.repo}/branches/{args.branch}"
    branch_status, branch_body, branch_error = fetch_url(branch_url)
    if branch_status != 200:
        print(json.dumps({"status": "fail", "error": f"branch fetch failed: {branch_status} {branch_error}"}, indent=2))
        return 1
    branch_payload = json.loads(branch_body.decode("utf-8"))
    sha = branch_payload["commit"]["sha"]

    raw_bundle_url = f"https://raw.githubusercontent.com/{args.repo}/{sha}/{args.bundle_path}"
    raw_health_url = f"https://raw.githubusercontent.com/{args.repo}/{sha}/{args.health_path}"
    raw_status, raw_body, raw_error = fetch_url(raw_bundle_url)
    fallback_status, fallback_body, fallback_error = fetch_contents_api(args.repo, sha, args.bundle_path)
    if raw_status == 200:
        bundle_bytes = raw_body
        retrieval_method = "raw"
    elif fallback_status == 200:
        bundle_bytes = fallback_body
        retrieval_method = "contents_api"
    else:
        print(json.dumps({
            "status": "fail",
            "sha": sha,
            "raw_status": raw_status,
            "raw_error": raw_error,
            "contents_api_status": fallback_status,
            "contents_api_error": fallback_error,
            "immutable_bundle_url": raw_bundle_url,
        }, indent=2))
        return 1

    health_status, health_body, health_error = fetch_url(raw_health_url)
    if health_status != 200:
        print(json.dumps({"status": "fail", "sha": sha, "health_status": health_status, "health_error": health_error}, indent=2))
        return 1

    bundle = json.loads(bundle_bytes.decode("utf-8"))
    health = json.loads(health_body.decode("utf-8"))
    errors: list[str] = []
    if len(bundle_bytes) > args.max_bytes:
        errors.append(f"bundle exceeds {args.max_bytes} bytes")
    for section in REQUIRED_SECTIONS:
        if section not in bundle:
            errors.append(f"missing section: {section}")
    if bundle.get("export_success") is not True:
        errors.append("bundle export_success is not true")
    if bundle.get("privacy_validation_passed") is not True:
        errors.append("privacy_validation_passed is not true")
    if health.get("export_success") is not True:
        errors.append("system_health export_success is not true")
    if not any(item.get("id") == "CHATGPT-FETCH-TEST-202607" for item in bundle.get("recent_activity", [])):
        errors.append("acceptance-test record missing")
    generated_at = parse_time(str(bundle.get("generated_at") or ""))
    age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600
    if age_hours > args.max_age_hours:
        errors.append(f"bundle age {age_hours:.2f}h exceeds {args.max_age_hours}h")

    result = {
        "status": "pass" if not errors else "fail",
        "repository": args.repo,
        "branch": args.branch,
        "sha": sha,
        "immutable_bundle_url": raw_bundle_url,
        "immutable_health_url": raw_health_url,
        "retrieval_method": retrieval_method,
        "raw_status": raw_status,
        "contents_api_status": fallback_status,
        "health_status": health_status,
        "bundle_bytes": len(bundle_bytes),
        "generated_at": bundle.get("generated_at"),
        "age_hours": round(age_hours, 3),
        "export_success": bundle.get("export_success"),
        "privacy_validation_passed": bundle.get("privacy_validation_passed"),
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
