#!/usr/bin/env python3
"""Build the ChatGPT-facing Intelligence Ledger memory layer.

SQLite remains the source of truth. The memory/ directory is a compact,
validated transport layer for ChatGPT and other agents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "info_analyzer.db"
MEMORY_DIR = ROOT / "memory"
SNAPSHOT_DIR = MEMORY_DIR / "snapshots"
ARCHIVE_DIR = MEMORY_DIR / "archive"

REQUIRED_FILES = [
    "memory/index.json",
    "memory/snapshots/latest.json",
    "memory/actions.jsonl",
    "memory/patterns.jsonl",
    "memory/watchlist.jsonl",
    "memory/entries.jsonl",
    "memory/chat_inbox.jsonl",
    "memory/export_status.json",
    "memory/briefing_manifest.json",
    "memory/system_health.json",
    "memory/activity.jsonl",
    "memory/decisions.jsonl",
    "memory/projects.jsonl",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True, capture_output=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_json(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def one_line(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text[: limit - 1] + "…" if len(text) > limit else text


def ensure_dirs() -> None:
    MEMORY_DIR.mkdir(exist_ok=True)
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    ARCHIVE_DIR.mkdir(exist_ok=True)
    inbox = MEMORY_DIR / "chat_inbox.jsonl"
    if not inbox.exists():
        inbox.write_text("", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} invalid JSONL: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no} must be a JSON object")
        rows.append(row)
    return rows


def raw_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def existing_raw_hashes(conn: sqlite3.Connection) -> set[str]:
    hashes: set[str] = set()
    for row in conn.execute("select metadata from entries"):
        metadata = load_json(row["metadata"], {})
        if metadata.get("chat_raw_hash"):
            hashes.add(str(metadata["chat_raw_hash"]))
    return hashes


def derive_signal(raw: str) -> str:
    for marker in ["Signal:", "Hidden signal:", "Decision:", "Action:"]:
        if marker.lower() in raw.lower():
            idx = raw.lower().find(marker.lower())
            return one_line(raw[idx + len(marker):], 180)
    return one_line(raw, 180)


def derive_action(raw: str) -> str:
    lowered = raw.lower()
    for marker in ["next action:", "returned action:", "action:", "decision:"]:
        if marker in lowered:
            idx = lowered.find(marker)
            return one_line(raw[idx + len(marker):], 180)
    return "Review this memory, decide whether it changes a current action, then log the result."


def derive_tags(record: dict[str, Any], raw: str) -> list[str]:
    tags = record.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    words = raw.lower()
    inferred = []
    for tag in ["sales", "stock", "investing", "lab", "career", "project", "pricing", "delivery", "watchlist"]:
        if tag in words:
            inferred.append(tag)
    return sorted({str(t).strip().lower() for t in [*tags, *inferred] if str(t).strip()})


def import_chat_inbox(conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    inbox = MEMORY_DIR / "chat_inbox.jsonl"
    rows = read_jsonl(inbox)
    if not rows:
        return {"pending_before": 0, "imported": 0, "duplicates": 0, "archived": ""}

    known = existing_raw_hashes(conn)
    imported: list[dict[str, Any]] = []
    duplicates = 0
    for record in rows:
        raw = str(record.get("raw_input") or record.get("content") or record.get("text") or "").strip()
        if not raw:
            raise ValueError("chat_inbox record missing raw_input/content/text")
        digest = raw_hash(raw)
        if digest in known:
            duplicates += 1
            continue

        created_at = str(record.get("created_at") or record.get("time") or generated_at)
        domain = str(record.get("domain") or "Other")
        entity = str(record.get("entity") or "").strip()
        signal = str(record.get("signal") or derive_signal(raw))
        action = str(record.get("returned_action") or derive_action(raw))
        tags = derive_tags(record, raw)
        entry_id = "IA-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + digest[:6].upper()
        metadata = {
            "chat_inbox_id": record.get("id") or digest[:12],
            "chat_raw_hash": digest,
            "imported_from": "memory/chat_inbox.jsonl",
            "raw_record": record,
        }
        conn.execute(
            """
            insert into entries (
              id, created_at, updated_at, date, title, domain, entity, source_type,
              raw_input, signal, interpretation, signal_role, trackable_as,
              tracking_metric, trigger_condition, returned_action, action_status,
              lesson, next_step, confidence, status, tags, metadata, actionability,
              pull_trigger_type, pull_trigger, relationship_type, card_type,
              result_to_track, first_step, impact_metric, feedback_to_capture,
              related_memory_query
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry_id,
                created_at,
                generated_at,
                created_at[:10] if len(created_at) >= 10 else today(),
                one_line(record.get("title") or signal, 120),
                domain,
                entity,
                str(record.get("source_type") or "chat"),
                raw,
                signal,
                str(record.get("interpretation") or "Imported chat memory that must be contextualized, tracked, and resurfaced when relevant."),
                str(record.get("signal_role") or record.get("signal_type") or "watch"),
                str(record.get("trackable_as") or "action/result loop"),
                str(record.get("tracking_metric") or record.get("metric") or "Result logged, decision updated, or action closed."),
                str(record.get("trigger_condition") or "Resurface when matching entity, domain, tag, or action appears."),
                action,
                str(record.get("action_status") or "open"),
                str(record.get("lesson") or ""),
                str(record.get("next_step") or action),
                str(record.get("confidence") or "Medium"),
                str(record.get("status") or "codified"),
                json.dumps(tags),
                json.dumps(metadata),
                str(record.get("actionability") or "review"),
                str(record.get("pull_trigger_type") or "tag"),
                str(record.get("pull_trigger") or "Resurface when related work appears in chat, actions, or projects."),
                str(record.get("relationship_type") or "connects"),
                str(record.get("card_type") or "Review Card"),
                str(record.get("result_to_track") or record.get("tracking_metric") or "Action result and decision quality."),
                str(record.get("first_step") or action),
                str(record.get("impact_metric") or "Decision quality improved through tracked follow-through."),
                str(record.get("feedback_to_capture") or "What changed after acting on this memory."),
                str(record.get("related_memory_query") or " ".join([domain, entity, " ".join(tags)]).strip()),
            ),
        )
        imported.append({"id": entry_id, "signal": signal, "domain": domain, "entity": entity})
        known.add(digest)

    conn.commit()
    archive_name = f"chat_inbox_{generated_at.replace(':', '').replace('-', '')}.jsonl"
    archive_path = ARCHIVE_DIR / archive_name
    archive_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    inbox.write_text("", encoding="utf-8")
    return {
        "pending_before": len(rows),
        "imported": len(imported),
        "duplicates": duplicates,
        "archived": str(archive_path.relative_to(ROOT)),
        "imported_entries": imported,
    }


def fetch_entries(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, created_at, updated_at, title, domain, entity, source_type, signal,
               interpretation, signal_role, tracking_metric, pattern, returned_action,
               action_status, result, lesson, next_step, confidence, status, tags,
               actionability, pull_trigger, card_type, first_step, impact_metric,
               feedback_to_capture, related_memory_query, last_resurfaced
        from entries
        order by updated_at desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            **{key: row[key] for key in row.keys() if key != "tags"},
            "tags": load_json(row["tags"], []),
            "summary": one_line(row["interpretation"] or row["signal"] or row["title"], 220),
        }
        for row in rows
    ]


def fetch_actions(conn: sqlite3.Connection, limit: int = 120) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select a.id, a.created_at, a.updated_at, a.entry_id, a.action_title, a.why,
               a.track_metric, a.due_date, a.priority, a.status, a.result,
               a.lesson_update, e.domain, e.entity, e.signal, e.title as source_title
        from actions a
        left join entries e on e.id = a.entry_id
        order by case a.status when 'open' then 0 when 'waiting' then 1 else 2 end,
                 case a.priority when 'High' then 0 when 'Medium' then 1 else 2 end,
                 a.updated_at desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def fetch_patterns(conn: sqlite3.Connection, limit: int = 120) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, created_at, updated_at, pattern, domains, tags, entry_count,
               confidence, last_entry_id, metadata
        from pattern_stats
        order by entry_count desc, updated_at desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    patterns = []
    for row in rows:
        patterns.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "pattern": row["pattern"],
                "domains": load_json(row["domains"], []),
                "tags": load_json(row["tags"], []),
                "entry_count": row["entry_count"],
                "confidence": row["confidence"],
                "last_entry_id": row["last_entry_id"],
                "metadata": load_json(row["metadata"], {}),
            }
        )
    return patterns


def fetch_watchlist(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, created_at, display_name, ticker, sector, industry, catalyst, note,
               price, target_price, support_price, return_potential
        from watchlist_items
        order by created_at desc, row_number asc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def fetch_decisions(conn: sqlite3.Connection, limit: int = 80) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select d.id, d.created_at, d.updated_at, d.entry_id, d.decision_question,
               d.current_rule, d.recommended_change, d.confidence_before,
               d.confidence_after, d.status, d.feedback_metric, d.result,
               d.rule_update, e.domain, e.entity, e.signal
        from decision_reviews d
        left join entries e on e.id = d.entry_id
        order by d.updated_at desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def fetch_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select p.id, p.created_at, p.updated_at, p.title, p.artist, p.source_url,
               p.notes, p.status, p.metadata, count(x.id) as extraction_count,
               max(x.updated_at) as last_extraction_at
        from listening_projects p
        left join listening_extractions x on x.project_id = p.id
        group by p.id
        order by p.updated_at desc
        """
    ).fetchall()
    return [
        {
            **{key: row[key] for key in row.keys() if key != "metadata"},
            "metadata": load_json(row["metadata"], {}),
            "kind": "asset_lab_project",
        }
        for row in rows
    ]


def build_snapshot(
    generated_at: str,
    entries: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> dict[str, Any]:
    open_actions = [a for a in actions if a.get("status") in {"open", "waiting", "in_progress", None}]
    high_actions = [a for a in open_actions if a.get("priority") == "High"][:8]
    recent_lessons = [e for e in entries if e.get("lesson")][:8]
    recent_alerts = [
        e for e in entries
        if str(e.get("signal_role") or "").lower() in {"risk", "contradiction"}
        or str(e.get("card_type") or "").lower().startswith(("risk", "contradiction"))
    ][:8]
    domains: dict[str, int] = {}
    for entry in entries:
        domains[str(entry.get("domain") or "Other")] = domains.get(str(entry.get("domain") or "Other"), 0) + 1
    return {
        "generated_at": generated_at,
        "current_context": {
            "system": "Info Analyzer OS / Sales OS",
            "source_of_truth": "data/info_analyzer.db",
            "transport_layer": "memory/",
            "active_domains": sorted(domains.items(), key=lambda item: item[1], reverse=True)[:8],
        },
        "current_priorities": [
            {
                "id": action["id"],
                "action": action["action_title"],
                "why": one_line(action.get("why"), 180),
                "priority": action.get("priority"),
                "domain": action.get("domain"),
                "entity": action.get("entity"),
                "track": action.get("track_metric"),
            }
            for action in high_actions
        ],
        "current_constraints": [
            "SQLite is authoritative; GitHub memory files are compact exports for ChatGPT.",
            "Do not export the full database into chat context.",
            "Every useful signal must become trackable, actionable, linked, or scheduled for resurfacing.",
        ],
        "weekend_goals": [
            one_line(action["action_title"], 140)
            for action in open_actions[:5]
        ],
        "open_loops": [
            {
                "id": action["id"],
                "action": action["action_title"],
                "status": action.get("status"),
                "due_date": action.get("due_date"),
                "source_entry": action.get("entry_id"),
            }
            for action in open_actions[:20]
        ],
        "projects": projects[:20],
        "watchlist": watchlist[:40],
        "decisions": decisions[:20],
        "critical_alerts": [
            {"id": e["id"], "signal": e.get("signal"), "action": e.get("returned_action"), "domain": e.get("domain")}
            for e in recent_alerts
        ],
        "upcoming_deadlines": [
            {
                "id": action["id"],
                "action": action["action_title"],
                "due_date": action.get("due_date"),
                "priority": action.get("priority"),
            }
            for action in open_actions
            if action.get("due_date")
        ][:12],
        "recent_lessons": [
            {"id": e["id"], "lesson": e.get("lesson"), "domain": e.get("domain"), "entity": e.get("entity")}
            for e in recent_lessons
        ],
        "recent_accountability": [
            {
                "id": action["id"],
                "action": action["action_title"],
                "status": action.get("status"),
                "result": action.get("result"),
            }
            for action in actions
            if action.get("status") not in {"open", "waiting", "in_progress", None}
        ][:12],
        "top_patterns": patterns[:12],
    }


def build_manifest(snapshot: dict[str, Any], actions: list[dict[str, Any]], patterns: list[dict[str, Any]]) -> dict[str, Any]:
    open_actions = [a for a in actions if a.get("status") in {"open", "waiting", "in_progress", None}]
    return {
        "generated_at": snapshot["generated_at"],
        "todays_highest_priorities": snapshot["current_priorities"][:5],
        "daily_watch_items": snapshot["critical_alerts"][:5],
        "weekly_watch_items": snapshot["watchlist"][:10],
        "projects_requiring_attention": [
            p for p in snapshot["projects"]
            if p.get("status") not in {"archived", "complete", "deleted"}
        ][:10],
        "things_to_ignore_today": [
            "Closed actions unless the result created a new decision rule.",
            "Raw historical entries without an open action, watch trigger, or contradiction.",
        ],
        "questions_still_unanswered": [
            "Which open action creates the highest leverage if completed today?",
            "Which watchlist item crossed a trigger since the last briefing?",
            "Which repeated pattern should become a reusable playbook rule?",
        ],
        "suggested_accountability_prompts": [
            "What action did you complete, and what result should be logged?",
            "Which signal changed a decision today?",
            "Which open loop should be closed, delegated, or archived?",
        ],
        "quick_action_count": len(open_actions),
        "pattern_count": len(patterns),
    }


def validation_report(conn: sqlite3.Connection) -> dict[str, Any]:
    broken_relationships = conn.execute(
        """
        select count(*) from relationships r
        left join entries f on f.id = r.from_entry_id
        left join entries t on t.id = r.to_entry_id
        where f.id is null or t.id is null
        """
    ).fetchone()[0]
    orphan_actions = conn.execute(
        "select count(*) from actions a left join entries e on e.id = a.entry_id where e.id is null"
    ).fetchone()[0]
    orphan_decisions = conn.execute(
        "select count(*) from decision_reviews d left join entries e on e.id = d.entry_id where e.id is null"
    ).fetchone()[0]
    duplicate_entities = conn.execute(
        """
        select count(*) from (
          select lower(coalesce(domain,'')) as domain_key, lower(coalesce(entity,'')) as entity_key, count(*) c
          from entries
          where coalesce(entity,'') != ''
          group by domain_key, entity_key
          having c > 1
        )
        """
    ).fetchone()[0]
    errors = []
    if broken_relationships:
        errors.append(f"{broken_relationships} broken relationships")
    if orphan_actions:
        errors.append(f"{orphan_actions} orphan actions")
    if orphan_decisions:
        errors.append(f"{orphan_decisions} orphan decision reviews")
    return {
        "broken_links": broken_relationships,
        "orphan_actions": orphan_actions,
        "orphan_decisions": orphan_decisions,
        "duplicate_entities": duplicate_entities,
        "missing_required_files": [],
        "errors": errors,
        "ok": not errors,
    }


def validate_json_exports() -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"missing {rel}")
            continue
        try:
            if path.suffix == ".jsonl":
                rows = read_jsonl(path)
                ids = [str(row.get("id")) for row in rows if row.get("id")]
                if len(ids) != len(set(ids)):
                    errors.append(f"duplicate ids in {rel}")
            elif path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception as exc:
            errors.append(f"{rel}: {exc}")
    return errors


def append_activity(generated_at: str, import_result: dict[str, Any], export_status: dict[str, Any]) -> list[dict[str, Any]]:
    path = MEMORY_DIR / "activity.jsonl"
    existing = read_jsonl(path) if path.exists() else []
    additions: list[dict[str, Any]] = []
    if import_result.get("imported"):
        for entry in import_result.get("imported_entries", []):
            additions.append(
                {
                    "id": f"activity-{generated_at}-{entry['id']}",
                    "time": generated_at,
                    "type": "chat_memory_imported",
                    "entity": entry.get("entity") or entry.get("domain"),
                    "summary": f"Imported chat memory: {entry.get('signal')}",
                }
            )
    additions.append(
        {
            "id": f"activity-{generated_at}-export",
            "time": generated_at,
            "type": "operating_state_exported",
            "entity": "Info Analyzer OS",
            "summary": "Regenerated ChatGPT memory exports and validation reports.",
            "export_success": export_status.get("export_success"),
        }
    )
    merged = [*existing, *additions]
    seen = set()
    deduped = []
    for item in reversed(merged):
        key = item.get("id") or json.dumps(item, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return list(reversed(deduped))[-500:]


def export_memory(args: argparse.Namespace) -> int:
    ensure_dirs()
    generated_at = now_iso()
    conn = connect()
    import_result = import_chat_inbox(conn, generated_at) if not args.skip_import else {"pending_before": 0, "imported": 0, "duplicates": 0, "archived": ""}

    entries = fetch_entries(conn)
    actions = fetch_actions(conn)
    patterns = fetch_patterns(conn)
    watchlist = fetch_watchlist(conn)
    decisions = fetch_decisions(conn)
    projects = fetch_projects(conn)

    snapshot = build_snapshot(generated_at, entries, actions, patterns, watchlist, decisions, projects)
    manifest = build_manifest(snapshot, actions, patterns)

    write_json(SNAPSHOT_DIR / "latest.json", snapshot)
    write_jsonl(MEMORY_DIR / "entries.jsonl", entries)
    write_jsonl(MEMORY_DIR / "actions.jsonl", actions)
    write_jsonl(MEMORY_DIR / "patterns.jsonl", patterns)
    write_jsonl(MEMORY_DIR / "watchlist.jsonl", watchlist)
    write_jsonl(MEMORY_DIR / "decisions.jsonl", decisions)
    write_jsonl(MEMORY_DIR / "projects.jsonl", projects)
    write_json(MEMORY_DIR / "briefing_manifest.json", manifest)

    db_validation = validation_report(conn)
    export_status = {
        "generated_at": generated_at,
        "export_success": False,
        "source_of_truth": str(DB_PATH.relative_to(ROOT)),
        "chatgpt_contract_files": REQUIRED_FILES,
        "import_result": import_result,
        "validation": db_validation,
        "json_errors": [],
        "counts": {
            "entries": len(entries),
            "actions": len(actions),
            "patterns": len(patterns),
            "watchlist": len(watchlist),
            "decisions": len(decisions),
            "projects": len(projects),
        },
    }

    health = {
        "database": "healthy" if db_validation["ok"] else "needs_attention",
        "last_export": generated_at,
        "last_push": "",
        "snapshot_age_minutes": 0,
        "broken_links": db_validation["broken_links"],
        "orphan_actions": db_validation["orphan_actions"],
        "duplicate_entities": db_validation["duplicate_entities"],
        "chat_inbox_pending": 0 if not (MEMORY_DIR / "chat_inbox.jsonl").read_text(encoding="utf-8").strip() else len(read_jsonl(MEMORY_DIR / "chat_inbox.jsonl")),
        "export_success": False,
    }

    index = {
        "version": "1.0",
        "generated_at": generated_at,
        "snapshot": "memory/snapshots/latest.json",
        "actions": "memory/actions.jsonl",
        "patterns": "memory/patterns.jsonl",
        "watchlist": "memory/watchlist.jsonl",
        "entries": "memory/entries.jsonl",
        "projects": "memory/projects.jsonl",
        "decisions": "memory/decisions.jsonl",
        "manifest": "memory/briefing_manifest.json",
        "health": "memory/system_health.json",
        "activity": "memory/activity.jsonl",
        "export_status": "memory/export_status.json",
        "chat_inbox": "memory/chat_inbox.jsonl",
    }
    write_json(MEMORY_DIR / "index.json", index)

    export_status["export_success"] = db_validation["ok"]
    write_json(MEMORY_DIR / "export_status.json", export_status)
    health["export_success"] = export_status["export_success"]
    write_json(MEMORY_DIR / "system_health.json", health)
    activity = append_activity(generated_at, import_result, export_status)
    write_jsonl(MEMORY_DIR / "activity.jsonl", activity)

    export_errors = validate_json_exports()
    if export_errors:
        export_status["export_success"] = False
        export_status["json_errors"] = export_errors
        write_json(MEMORY_DIR / "export_status.json", export_status)
        health["export_success"] = False
        write_json(MEMORY_DIR / "system_health.json", health)
        return 1
    if not export_status["export_success"]:
        return 1
    print(json.dumps({"ok": True, "generated_at": generated_at, "counts": export_status["counts"], "import": import_result}, indent=2))
    return 0


def git_sync(commit_message: str) -> None:
    run(["git", "pull", "--rebase"])
    status = run(["git", "status", "--porcelain"]).stdout.strip().splitlines()
    unsafe = [line for line in status if not line.endswith("README 2.md")]
    if unsafe:
        raise RuntimeError("repository has uncommitted changes before export: " + "; ".join(unsafe))
    run(["git", "add", "memory/"])
    if not run(["git", "diff", "--cached", "--quiet"], check=False).returncode == 0:
        run(["git", "commit", "-m", commit_message])
        run(["git", "push", "-u", "origin", "main"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Export SQLite memory into ChatGPT-compatible memory files.")
    parser.add_argument("--skip-import", action="store_true", help="Do not import memory/chat_inbox.jsonl before export.")
    parser.add_argument("--git", action="store_true", help="Run git pull, commit memory/, and push after validation.")
    parser.add_argument("--commit-message", default="Update intelligence operating state")
    args = parser.parse_args()

    if args.git:
        run(["git", "pull", "--rebase"])
    code = export_memory(args)
    if code != 0:
        print("Memory export validation failed; not pushing.", file=sys.stderr)
        return code
    if args.git:
        run(["git", "add", "memory/"])
        if run(["git", "diff", "--cached", "--quiet"], check=False).returncode != 0:
            run(["git", "commit", "-m", args.commit_message])
            run(["git", "push", "-u", "origin", "main"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
