#!/usr/bin/env python3
"""Build the ChatGPT-facing Intelligence Ledger memory layer.

SQLite remains the source of truth. The memory/ directory is a compact,
validated transport layer for ChatGPT and other agents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import base64
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DB_PATH_RAW = os.environ.get("INFO_ANALYZER_DB_PATH", "").strip()
DB_PATH = Path(DB_PATH_RAW).expanduser() if DB_PATH_RAW else ROOT / "data" / "info_analyzer.db"
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH
MEMORY_DIR = ROOT / "memory"
SNAPSHOT_DIR = MEMORY_DIR / "snapshots"
ARCHIVE_DIR = MEMORY_DIR / "archive"

REQUIRED_FILES = [
    "memory/index.json",
    "memory/assistant_bundle.json",
    "memory/assistant_fetch.json",
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
    "memory/entity_aliases.json",
]

CANONICAL_PROJECTS = [
    {
        "id": "project-nashville-transition",
        "title": "Nashville Transition",
        "domain": "Personal Operations",
        "entity": "Nashville Transition",
        "summary": "Coordinate relocation readiness, cash runway, job search, housing, and family logistics as one operating project.",
        "current_milestone": "Define readiness checklist and weekly decision gates.",
        "current_blocker": "Needs consolidated plan, cash runway view, and trigger dates.",
        "next_action": "Create transition readiness checklist with go/no-go criteria.",
        "aliases": ["Nashville", "move to Nashville", "transition readiness"],
        "related_query": "Nashville transition job search cash runway housing family",
    },
    {
        "id": "project-job-search",
        "title": "Job Search / Career Intelligence Ledger",
        "domain": "Career",
        "entity": "Job Search / Career Intelligence Ledger",
        "summary": "Track applications, interviews, proof artifacts, role targeting, and follow-up cadence.",
        "current_milestone": "Turn applications into a measurable pipeline.",
        "current_blocker": "Needs response-rate tracking and sharper proof artifacts.",
        "next_action": "Log applications with role, date, follow-up date, response, and proof used.",
        "aliases": ["career search", "applications", "interviews", "resume"],
        "related_query": "job search resume interview applications proof outcomes",
    },
    {
        "id": "project-sales-os-liquidation",
        "title": "Sales OS Liquidation",
        "domain": "Business",
        "entity": "Sales OS Liquidation",
        "summary": "Build a sourcing, pricing, listing, objection, and sell-through loop for liquidation/resale operations.",
        "current_milestone": "Convert sales signals into inventory and listing actions.",
        "current_blocker": "Needs consistent unit economics by item type.",
        "next_action": "Track acquisition cost, listing price, objection, sale price, margin, and days-to-sale.",
        "aliases": ["Sales OS", "liquidation", "resale", "trending items"],
        "related_query": "sales liquidation resale pricing objections sell-through margin",
    },
    {
        "id": "project-info-analyzer-intelligence-ledger",
        "title": "Intelligence Ledger / Info Analyzer",
        "domain": "Info Analyzer OS",
        "entity": "Intelligence Ledger / Info Analyzer",
        "summary": "Maintain the decision intelligence system that converts raw inputs into tracked memory, actions, and briefings.",
        "current_milestone": "Prove bidirectional ChatGPT-GitHub-SQLite synchronization.",
        "current_blocker": "Needs verified write-import-export-read loop.",
        "next_action": "Run bridge acceptance test and verify raw GitHub visibility.",
        "aliases": ["Info Analyzer", "Intelligence Ledger", "memory bridge", "Sales OS memory"],
        "related_query": "info analyzer intelligence ledger github memory bridge bidirectional sync",
    },
    {
        "id": "project-agent-harness-loop-engineering",
        "title": "Agent Harness / Loop Engineering",
        "domain": "AI Project",
        "entity": "Agent Harness / Loop Engineering",
        "summary": "Build and test agent loops that repeatedly plan, execute, verify, and repair until the system works in practice.",
        "current_milestone": "Make loop testing a default release gate for API, memory, and cockpit changes.",
        "current_blocker": "Needs durable proof artifacts from each loop instead of informal session summaries.",
        "next_action": "Attach loop proof outputs to the relevant release and memory export.",
        "aliases": ["Loop Engineering", "Agent Harness", "loop engineer", "agent loop"],
        "related_query": "agent harness loop engineering acceptance test proof repair",
    },
    {
        "id": "project-groove-os",
        "title": "Groove OS",
        "domain": "Music",
        "entity": "Groove OS",
        "summary": "Develop a music intelligence system for extracting emotional, structural, sync, and reuse value from audio assets.",
        "current_milestone": "Clarify asset extraction and labeling workflow.",
        "current_blocker": "Needs repeatable library schema and examples.",
        "next_action": "Break one audio asset into section map, glossary, sound example, and reuse notes.",
        "aliases": ["Groove", "music intelligence", "asset lab music"],
        "related_query": "groove os music asset lab extraction emotional commercial reuse",
    },
    {
        "id": "project-home-sentinel",
        "title": "Home Sentinel",
        "domain": "AI Project",
        "entity": "Home Sentinel",
        "summary": "Build a home/system monitoring concept around signals, thresholds, alerts, and action loops.",
        "current_milestone": "Define minimum viable monitoring scope.",
        "current_blocker": "Needs clear sensor/event list and decision rules.",
        "next_action": "List monitored events, thresholds, alert levels, and response actions.",
        "aliases": ["home monitoring", "sentinel", "home signals"],
        "related_query": "home sentinel monitoring threshold alert action loop",
    },
    {
        "id": "project-operator-training-concept-library",
        "title": "Operator Training Concept Library",
        "domain": "Lab",
        "entity": "Operator Training Concept Library",
        "summary": "Capture operator training, SOP, calibration, quality, and feedback-loop concepts as reusable decision assets.",
        "current_milestone": "Turn lab patterns into concept cards and checklists.",
        "current_blocker": "Needs extraction labels and reusable examples.",
        "next_action": "Create concept cards for calibration drift, setup errors, SOP gaps, and usable data hours.",
        "aliases": ["operator training", "concept library", "SOP library", "lab training"],
        "related_query": "operator training SOP calibration quality feedback loop usable data",
    },
    {
        "id": "project-ai-infrastructure-investment-thesis",
        "title": "AI Infrastructure Investment Thesis",
        "domain": "Investing",
        "entity": "AI Infrastructure Investment Thesis",
        "summary": "Track AI infrastructure signals across compute, memory, networking, robotics data, edge systems, and deployment economics.",
        "current_milestone": "Convert AI infrastructure ideas into watchable company and market signals.",
        "current_blocker": "Needs current source data, trigger thresholds, and decision rules before capital allocation.",
        "next_action": "Create a watchlist for AI memory, compute, networking, and physical AI infrastructure names.",
        "aliases": ["AI infrastructure", "physical AI infrastructure", "AI investment thesis", "compute thesis"],
        "related_query": "AI infrastructure investing HBM compute networking robotics edge systems",
    },
]

CANONICAL_ENTITY_ALIASES = [
    {
        "id": "alias-info-analyzer-intelligence-ledger",
        "canonical_entity_id": "entity-info-analyzer-intelligence-ledger",
        "canonical_name": "Intelligence Ledger / Info Analyzer",
        "domain": "Info Analyzer OS",
        "aliases": ["Info Analyzer", "Intelligence Ledger", "Info Analyzer OS", "Info Analyzer / Intelligence Ledger", "Sales OS memory"],
    },
    {
        "id": "alias-sales-os",
        "canonical_entity_id": "entity-sales-os",
        "canonical_name": "Sales OS Liquidation",
        "domain": "Business",
        "aliases": ["Sales OS", "Sales Operating System", "Sales OS Liquidation", "resale", "liquidation"],
    },
    {
        "id": "alias-home-sentinel",
        "canonical_entity_id": "entity-home-sentinel",
        "canonical_name": "Home Sentinel",
        "domain": "AI Project",
        "aliases": ["Home Sentinel", "Sentinel", "home monitoring", "home signals"],
    },
    {
        "id": "alias-sk-hynix",
        "canonical_entity_id": "entity-sk-hynix",
        "canonical_name": "SK Hynix",
        "domain": "Investing",
        "aliases": ["SK Hynix", "SKHY", "Hynix", "000660.KS", "AI memory"],
    },
    {
        "id": "alias-groove-os",
        "canonical_entity_id": "entity-groove-os",
        "canonical_name": "Groove OS",
        "domain": "Music",
        "aliases": ["Groove OS", "Groove", "music intelligence"],
    },
    {
        "id": "alias-nashville-transition",
        "canonical_entity_id": "entity-nashville-transition",
        "canonical_name": "Nashville Transition",
        "domain": "Personal Operations",
        "aliases": ["Nashville Move", "Nashville Transition", "Nashville readiness", "transition readiness"],
    },
]

CANONICAL_DECISIONS = [
    {
        "id": "decision-sk-hynix-investigate-buy-watch-avoid",
        "title": "SK Hynix: investigate, buy, watch, or avoid",
        "domain": "Investing",
        "entity": "SK Hynix",
        "decision_question": "Should SK Hynix be investigated, bought, watched, or avoided based on AI memory demand, valuation, and cycle risk?",
        "options": ["investigate", "buy", "watch", "avoid"],
        "current_position": "investigate",
        "next_review": "",
        "tracking_metric": "HBM demand, AI memory pricing, capex discipline, gross margin trend, and customer concentration.",
        "aliases": ["SK Hynix", "Hynix", "000660.KS", "AI memory"],
        "related_query": "SK Hynix HBM AI memory valuation earnings capex",
    },
    {
        "id": "decision-nashville-transition-readiness",
        "title": "Nashville transition readiness",
        "domain": "Personal Operations",
        "entity": "Nashville Transition",
        "decision_question": "Is the Nashville transition ready to execute, or should it remain in preparation?",
        "options": ["go", "prepare", "defer", "stop"],
        "current_position": "prepare",
        "next_review": "",
        "tracking_metric": "Cash runway, job pipeline, housing plan, family constraints, and move date confidence.",
        "aliases": ["Nashville readiness", "transition readiness"],
        "related_query": "Nashville transition readiness cash runway job housing family",
    },
    {
        "id": "decision-dedicated-compute-purchase",
        "title": "Dedicated compute purchase: needed now or defer",
        "domain": "AI Project",
        "entity": "Dedicated Compute",
        "decision_question": "Is dedicated compute needed now for projects, or should the purchase be deferred until utilization is proven?",
        "options": ["buy now", "defer", "rent", "reuse existing hardware"],
        "current_position": "defer",
        "next_review": "",
        "tracking_metric": "Utilization hours, blocked workloads, rental cost, project revenue/proof value, and hardware payback period.",
        "aliases": ["compute purchase", "GPU purchase", "dedicated compute"],
        "related_query": "dedicated compute GPU purchase defer utilization payback",
    },
    {
        "id": "decision-bassinet-pricing-condition-strategy",
        "title": "Bassinet pricing and condition strategy",
        "domain": "Business",
        "entity": "Bassinet Resale",
        "decision_question": "What pricing and condition strategy should be used for the bassinet listing?",
        "options": ["premium price", "fast-sale discount", "bundle delivery/setup", "hold"],
        "current_position": "investigate",
        "next_review": "",
        "tracking_metric": "Comparable prices, condition score, delivery/setup questions, listing views, saves, offers, and days-to-sale.",
        "aliases": ["bassinet", "baby item resale", "condition pricing"],
        "related_query": "bassinet pricing condition resale delivery setup comparable",
    },
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
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
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


def export_run_id(generated_at: str) -> str:
    return "export-" + generated_at.replace(":", "").replace("-", "").replace("Z", "").replace("T", "-")


def source_of_truth_ref() -> str:
    return "data/info_analyzer.db"


def priority_number(value: Any) -> int:
    text = str(value or "").lower()
    if text in {"high", "critical", "urgent"}:
        return 1
    if text in {"medium", "normal"}:
        return 2
    return 3


def confidence_number(value: Any) -> float:
    text = str(value or "").lower()
    if text == "high":
        return 0.8
    if text == "low":
        return 0.35
    if text in {"", "none", "null"}:
        return 0.5
    return 0.6


SENSITIVE_TERMS = [
    "github_pat_",
    "api_key",
    "apikey",
    "authorization: bearer",
    "x-info-analyzer-key",
    "password",
    "account number",
    "routing number",
    "ssn",
    "social security",
    "private medical",
    "diagnosis:",
    "patient",
    "confidential robotics",
    "proprietary robotics",
]


def summarize_for_bundle(value: Any, limit: int = 180) -> str:
    text = one_line(value, limit)
    # Keep the assistant bundle contextual, not evidentiary. Raw source fields stay in SQLite.
    text = text.replace("Authorization: Bearer", "Authorization header")
    text = text.replace("X-Info-Analyzer-Key", "API key header")
    return text


def privacy_issues(bundle: dict[str, Any]) -> list[str]:
    text = json.dumps(bundle, ensure_ascii=False).lower()
    issues: list[str] = []
    for term in SENSITIVE_TERMS:
        if term in text:
            issues.append(f"sensitive term present: {term}")
    if '"raw_input"' in text:
        issues.append("raw_input field present")
    if "github_pat_" in text:
        issues.append("GitHub token pattern present")
    import re

    if re.search(r"\bsk-(?:proj-[a-z0-9_-]{20,}|[a-z0-9]{32,})\b", text):
        issues.append("OpenAI-style secret key pattern present")
    if re.search(r"(account number|routing number|ssn|social security)[^\n]{0,40}\d{4,}", text):
        issues.append("private financial or identity number context present")
    return sorted(set(issues))


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


def ensure_operating_tables(conn: sqlite3.Connection, generated_at: str) -> None:
    conn.executescript(
        """
        create table if not exists ledger_projects (
          id text primary key,
          created_at text not null,
          updated_at text not null,
          title text not null,
          domain text,
          entity text,
          status text default 'active',
          lifecycle text default 'investigating',
          summary text,
          current_milestone text,
          current_blocker text,
          next_action text,
          confidence text default 'Medium',
          aliases text default '[]',
          related_query text,
          metadata text default '{}'
        );
        create table if not exists ledger_decisions (
          id text primary key,
          created_at text not null,
          updated_at text not null,
          title text not null,
          domain text,
          entity text,
          status text default 'open',
          lifecycle text default 'investigating',
          decision_question text not null,
          options text default '[]',
          current_position text,
          next_review text,
          confidence text default 'Medium',
          tracking_metric text,
          aliases text default '[]',
          related_query text,
          metadata text default '{}'
        );
        create table if not exists entity_aliases (
          id text primary key,
          created_at text not null,
          updated_at text not null,
          canonical_entity_id text not null,
          canonical_name text not null,
          domain text,
          aliases text default '[]',
          source_record_count integer default 0,
          related_entry_ids text default '[]',
          metadata text default '{}'
        );
        """
    )
    for project in CANONICAL_PROJECTS:
        conn.execute(
            """
            insert into ledger_projects (
              id, created_at, updated_at, title, domain, entity, status, lifecycle,
              summary, current_milestone, current_blocker, next_action, confidence,
              aliases, related_query, metadata
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(id) do update set
              updated_at=excluded.updated_at,
              title=excluded.title,
              domain=excluded.domain,
              entity=excluded.entity,
              summary=excluded.summary,
              current_milestone=excluded.current_milestone,
              current_blocker=excluded.current_blocker,
              next_action=excluded.next_action,
              aliases=excluded.aliases,
              related_query=excluded.related_query
            """,
            (
                project["id"],
                generated_at,
                generated_at,
                project["title"],
                project["domain"],
                project["entity"],
                "active",
                "building" if "Info Analyzer" in project["title"] else "investigating",
                project["summary"],
                project["current_milestone"],
                project["current_blocker"],
                project["next_action"],
                "High" if "Info Analyzer" in project["title"] else "Medium",
                json.dumps(project["aliases"]),
                project["related_query"],
                json.dumps({"source": "canonical_project_seed", "provenance": "memory_manager_v0.84"}),
            ),
        )
    for decision in CANONICAL_DECISIONS:
        conn.execute(
            """
            insert into ledger_decisions (
              id, created_at, updated_at, title, domain, entity, status, lifecycle,
              decision_question, options, current_position, next_review, confidence,
              tracking_metric, aliases, related_query, metadata
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(id) do update set
              updated_at=excluded.updated_at,
              title=excluded.title,
              domain=excluded.domain,
              entity=excluded.entity,
              decision_question=excluded.decision_question,
              options=excluded.options,
              current_position=excluded.current_position,
              next_review=excluded.next_review,
              tracking_metric=excluded.tracking_metric,
              aliases=excluded.aliases,
              related_query=excluded.related_query
            """,
            (
                decision["id"],
                generated_at,
                generated_at,
                decision["title"],
                decision["domain"],
                decision["entity"],
                "open",
                "investigating",
                decision["decision_question"],
                json.dumps(decision["options"]),
                decision["current_position"],
                decision["next_review"],
                "Medium",
                decision["tracking_metric"],
                json.dumps(decision["aliases"]),
                decision["related_query"],
                json.dumps({"source": "canonical_decision_seed", "provenance": "memory_manager_v0.84"}),
            ),
        )
    conn.commit()


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
    ledger_rows = conn.execute(
        """
        select id, created_at, updated_at, title, domain, entity, status, lifecycle,
               decision_question, options, current_position, next_review, confidence,
               tracking_metric, aliases, related_query, metadata
        from ledger_decisions
        where status != 'archived'
        order by updated_at desc
        """
    ).fetchall()
    decisions = [
        {
            **{key: row[key] for key in row.keys() if key not in {"options", "aliases", "metadata"}},
            "options": load_json(row["options"], []),
            "aliases": load_json(row["aliases"], []),
            "metadata": load_json(row["metadata"], {}),
            "kind": "canonical_decision",
        }
        for row in ledger_rows
    ]
    review_rows = conn.execute(
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
    decisions.extend({**{key: row[key] for key in row.keys()}, "kind": "decision_review"} for row in review_rows)
    return decisions[:limit]


def fetch_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ledger_rows = conn.execute(
        """
        select id, created_at, updated_at, title, domain, entity, status, lifecycle,
               summary, current_milestone, current_blocker, next_action, confidence,
               aliases, related_query, metadata
        from ledger_projects
        where status != 'archived'
        order by updated_at desc
        """
    ).fetchall()
    projects = [
        {
            **{key: row[key] for key in row.keys() if key not in {"aliases", "metadata"}},
            "aliases": load_json(row["aliases"], []),
            "metadata": load_json(row["metadata"], {}),
            "kind": "canonical_project",
        }
        for row in ledger_rows
    ]
    asset_rows = conn.execute(
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
    projects.extend(
        {
            **{key: row[key] for key in row.keys() if key != "metadata"},
            "metadata": load_json(row["metadata"], {}),
            "kind": "asset_lab_project",
        }
        for row in asset_rows
    )
    return projects


def reconcile_entity_aliases(conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        select lower(coalesce(domain,'')) as domain_key,
               lower(coalesce(entity,'')) as entity_key,
               coalesce(domain,'') as domain,
               coalesce(entity,'') as entity,
               count(*) as c,
               group_concat(id) as entry_ids
        from entries
        where coalesce(entity,'') != ''
        group by domain_key, entity_key
        having c > 1
        order by c desc, domain, entity
        """
    ).fetchall()
    alias_records = []
    for row in rows:
        domain = row["domain"] or "Other"
        entity = row["entity"] or "Unknown"
        canonical_entity_id = "entity-" + hashlib.sha1(f"{domain.lower()}::{entity.lower()}".encode("utf-8")).hexdigest()[:12]
        entry_ids = [item for item in str(row["entry_ids"] or "").split(",") if item]
        aliases = sorted({entity, entity.strip(), entity.lower(), entity.title()})
        alias_id = "alias-" + hashlib.sha1(f"{domain.lower()}::{entity.lower()}".encode("utf-8")).hexdigest()[:12]
        metadata = {
            "source": "duplicate_entity_reconciliation",
            "method": "same normalized domain/entity grouped under a canonical entity id",
            "provenance": "memory_manager",
        }
        conn.execute(
            """
            insert into entity_aliases (
              id, created_at, updated_at, canonical_entity_id, canonical_name,
              domain, aliases, source_record_count, related_entry_ids, metadata
            ) values (?,?,?,?,?,?,?,?,?,?)
            on conflict(id) do update set
              updated_at=excluded.updated_at,
              canonical_entity_id=excluded.canonical_entity_id,
              canonical_name=excluded.canonical_name,
              domain=excluded.domain,
              aliases=excluded.aliases,
              source_record_count=excluded.source_record_count,
              related_entry_ids=excluded.related_entry_ids,
              metadata=excluded.metadata
            """,
            (
                alias_id,
                generated_at,
                generated_at,
                canonical_entity_id,
                entity,
                domain,
                json.dumps(aliases),
                row["c"],
                json.dumps(entry_ids),
                json.dumps(metadata),
            ),
        )
        alias_records.append(
            {
                "id": alias_id,
                "canonical_entity_id": canonical_entity_id,
                "canonical_name": entity,
                "domain": domain,
                "aliases": aliases,
                "source_record_count": row["c"],
                "related_entry_ids": entry_ids,
                "metadata": metadata,
            }
        )
    for item in CANONICAL_ENTITY_ALIASES:
        aliases = sorted({str(alias).strip() for alias in item["aliases"] if str(alias).strip()})
        placeholders = ",".join("?" for _ in aliases)
        related_entry_ids: list[str] = []
        if aliases:
            related_entry_ids = [
                row["id"]
                for row in conn.execute(
                    f"""
                    select id from entries
                    where lower(coalesce(entity,'')) in ({placeholders})
                       or lower(coalesce(title,'')) in ({placeholders})
                    order by updated_at desc
                    limit 40
                    """,
                    tuple(alias.lower() for alias in aliases) * 2,
                ).fetchall()
            ]
        metadata = {
            "source": "manual_canonical_alias_map",
            "method": "known project/entity naming variants grouped under one assistant-facing entity",
            "provenance": "memory_manager_assistant_bundle",
        }
        conn.execute(
            """
            insert into entity_aliases (
              id, created_at, updated_at, canonical_entity_id, canonical_name,
              domain, aliases, source_record_count, related_entry_ids, metadata
            ) values (?,?,?,?,?,?,?,?,?,?)
            on conflict(id) do update set
              updated_at=excluded.updated_at,
              canonical_entity_id=excluded.canonical_entity_id,
              canonical_name=excluded.canonical_name,
              domain=excluded.domain,
              aliases=excluded.aliases,
              source_record_count=excluded.source_record_count,
              related_entry_ids=excluded.related_entry_ids,
              metadata=excluded.metadata
            """,
            (
                item["id"],
                generated_at,
                generated_at,
                item["canonical_entity_id"],
                item["canonical_name"],
                item["domain"],
                json.dumps(aliases),
                len(related_entry_ids),
                json.dumps(related_entry_ids),
                json.dumps(metadata),
            ),
        )
        alias_records.append(
            {
                "id": item["id"],
                "canonical_entity_id": item["canonical_entity_id"],
                "canonical_name": item["canonical_name"],
                "domain": item["domain"],
                "aliases": aliases,
                "source_record_count": len(related_entry_ids),
                "related_entry_ids": related_entry_ids,
                "metadata": metadata,
            }
        )
    conn.commit()
    return {
        "duplicate_groups_detected": len(rows),
        "duplicate_groups_reconciled": len(alias_records),
        "unresolved_duplicate_entities": 0,
        "aliases": alias_records,
    }


def build_snapshot(
    generated_at: str,
    entries: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    entity_aliases: dict[str, Any],
    import_result: dict[str, Any],
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
            "entity_aliases": {
                "duplicate_groups_detected": entity_aliases.get("duplicate_groups_detected", 0),
                "duplicate_groups_reconciled": entity_aliases.get("duplicate_groups_reconciled", 0),
                "unresolved_duplicate_entities": entity_aliases.get("unresolved_duplicate_entities", 0),
            },
        },
        "recent_changes": [
            {
                "type": "chat_memory_imported",
                "id": entry.get("id"),
                "domain": entry.get("domain"),
                "entity": entry.get("entity"),
                "signal": entry.get("signal"),
            }
            for entry in import_result.get("imported_entries", [])
        ],
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


def build_assistant_bundle(
    generated_at: str,
    entries: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    manifest: dict[str, Any],
    health: dict[str, Any],
    entity_aliases: dict[str, Any],
) -> dict[str, Any]:
    run_id = export_run_id(generated_at)
    active_projects = [
        p for p in projects
        if p.get("kind") == "canonical_project" and str(p.get("status") or "").lower() not in {"archived", "complete", "deleted"}
    ][:10]
    open_actions = [a for a in actions if a.get("status") in {"open", "waiting", "in_progress", None}]
    sorted_actions = sorted(open_actions, key=lambda a: (priority_number(a.get("priority")), str(a.get("due_date") or "9999-99-99"), str(a.get("updated_at") or "")))
    active_decisions = [d for d in decisions if str(d.get("status") or "").lower() not in {"archived", "closed", "deleted"}][:10]
    active_patterns = patterns[:15]
    watch_items = watchlist[:20]
    recent_lessons = [e for e in entries if e.get("lesson")][:10]
    activity = read_jsonl(MEMORY_DIR / "activity.jsonl") if (MEMORY_DIR / "activity.jsonl").exists() else []
    recent_activity = activity[-20:]
    accountability = [
        a for a in actions
        if a.get("status") not in {"open", "waiting", "in_progress", None} and (a.get("result") or a.get("lesson_update"))
    ][:10]
    critical_actions = [a for a in sorted_actions if priority_number(a.get("priority")) == 1][:10]

    project_rows = [
        {
            "id": p.get("id") or "",
            "name": p.get("title") or p.get("entity") or "",
            "status": p.get("status") or "active",
            "priority": 1 if "Info Analyzer" in str(p.get("title") or "") or "Intelligence Ledger" in str(p.get("title") or "") else 2,
            "why_now": summarize_for_bundle(p.get("summary"), 220),
            "current_milestone": summarize_for_bundle(p.get("current_milestone"), 180),
            "blocker": summarize_for_bundle(p.get("current_blocker"), 180),
            "next_action": summarize_for_bundle(p.get("next_action"), 180),
            "deadline": "",
            "evidence_required": summarize_for_bundle(p.get("related_query"), 180),
            "review_cadence": "daily",
        }
        for p in active_projects
    ]
    project_ids = {p["id"] for p in project_rows}

    action_rows = []
    for a in sorted_actions[:20]:
        project_id = ""
        domain = str(a.get("domain") or "")
        entity = str(a.get("entity") or "")
        if "Info Analyzer" in entity or "Ledger" in entity:
            project_id = "project-info-analyzer-intelligence-ledger"
        elif "Sales" in entity or domain == "Business":
            project_id = "project-sales-os-liquidation"
        elif domain == "Career":
            project_id = "project-job-search"
        elif domain == "Lab":
            project_id = "project-operator-training-concept-library"
        if project_id and project_id not in project_ids:
            project_id = ""
        action_rows.append(
            {
                "id": a.get("id") or "",
                "project_id": project_id,
                "action": summarize_for_bundle(a.get("action_title"), 220),
                "status": a.get("status") or "open",
                "priority": priority_number(a.get("priority")),
                "deadline": a.get("due_date") or "",
                "success_metric": summarize_for_bundle(a.get("track_metric"), 180),
                "last_accountability_response": summarize_for_bundle(a.get("result"), 180),
            }
        )

    decision_rows = [
        {
            "id": d.get("id") or "",
            "entity": d.get("entity") or d.get("domain") or "",
            "question": summarize_for_bundle(d.get("decision_question") or d.get("title"), 220),
            "current_state": summarize_for_bundle(d.get("current_position") or d.get("status") or d.get("current_rule"), 160),
            "confidence": confidence_number(d.get("confidence") or d.get("confidence_after") or d.get("confidence_before")),
            "supporting_evidence": [summarize_for_bundle(d.get("tracking_metric") or d.get("recommended_change"), 160)] if (d.get("tracking_metric") or d.get("recommended_change")) else [],
            "contradicting_evidence": [],
            "next_evidence_needed": [summarize_for_bundle(d.get("related_query") or d.get("feedback_metric"), 160)] if (d.get("related_query") or d.get("feedback_metric")) else [],
            "decision_trigger": summarize_for_bundle(d.get("next_review") or d.get("tracking_metric"), 160),
            "review_cadence": "daily",
        }
        for d in active_decisions
    ]

    pattern_rows = [
        {
            "id": p.get("id") or "",
            "pattern": summarize_for_bundle(p.get("pattern"), 220),
            "confidence": p.get("confidence") or "Medium",
            "entry_count": p.get("entry_count") or 0,
            "domains": p.get("domains") or [],
            "monitor": "Promote to action if this pattern repeats or changes a current decision.",
        }
        for p in active_patterns
    ]

    watch_rows = [
        {
            "id": w.get("id") or "",
            "name": summarize_for_bundle(w.get("display_name") or w.get("ticker") or w.get("sector"), 120),
            "ticker": w.get("ticker") or "",
            "signal": summarize_for_bundle(w.get("catalyst") or w.get("note"), 180),
            "trigger": summarize_for_bundle(w.get("target_price") or w.get("support_price") or w.get("return_potential"), 120),
        }
        for w in watch_items
    ]

    acceptance_test = {
        "id": "CHATGPT-FETCH-TEST-202607",
        "type": "system_acceptance_test",
        "status": "ready",
        "signal": "ChatGPT can retrieve the current Intelligence Ledger operating state through an immutable GitHub commit URL.",
        "next_action": "Confirm the Daily Intelligence Briefing references this record.",
    }

    bundle = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "export_run_id": run_id,
        "source_of_truth": source_of_truth_ref(),
        "export_success": bool(health.get("export_success")),
        "privacy_validation_passed": False,
        "current_context": {
            "primary_constraint": "Use the compact assistant bundle for briefings; SQLite remains the source of truth and must not be committed.",
            "current_transition": "External ChatGPT memory bridge and daily briefing retrieval are the active transition.",
            "career_state": "Career and job-search context is tracked through the Career Intelligence Ledger project.",
            "important_deadlines": [a.get("deadline") for a in action_rows if a.get("deadline")][:8],
        },
        "weekend_clarity": [
            "Stabilize the ChatGPT read path through one immutable assistant bundle.",
            "Prioritize transition-critical actions, open decisions, and proof artifacts over background themes.",
        ],
        "active_projects": project_rows,
        "top_actions": action_rows,
        "active_decisions": decision_rows,
        "active_patterns": pattern_rows,
        "watchlist": watch_rows,
        "recent_lessons": [
            {"id": e.get("id") or "", "lesson": summarize_for_bundle(e.get("lesson"), 180), "domain": e.get("domain") or "", "entity": e.get("entity") or ""}
            for e in recent_lessons
        ],
        "recent_activity": [
            {
                "id": item.get("id") or "",
                "time": item.get("time") or "",
                "type": item.get("type") or "",
                "entity": summarize_for_bundle(item.get("entity"), 100),
                "summary": summarize_for_bundle(item.get("summary"), 180),
            }
            for item in recent_activity
        ] + [acceptance_test],
        "accountability_state": [
            {
                "id": a.get("id") or "",
                "action": summarize_for_bundle(a.get("action_title"), 160),
                "status": a.get("status") or "",
                "result": summarize_for_bundle(a.get("result") or a.get("lesson_update"), 180),
            }
            for a in accountability
        ],
        "critical_alerts": [
            {
                "id": a.get("id") or "",
                "type": "action",
                "severity": "high" if priority_number(a.get("priority")) == 1 else "medium",
                "signal": summarize_for_bundle(a.get("why"), 180),
                "next_action": summarize_for_bundle(a.get("action_title"), 180),
            }
            for a in critical_actions
        ],
        "briefing_priorities": [
            summarize_for_bundle(item.get("action") or item.get("summary") or item, 180)
            for item in manifest.get("todays_highest_priorities", [])[:8]
        ],
        "weekly_only_topics": [
            "Background watchlist review unless a trigger changed.",
            "Closed actions unless the result changed a decision rule.",
        ],
        "exclude_unless_material": [
            "Raw source text",
            "Full SQLite exports",
            "Credentials or host secrets",
            "Non-actionable archive notes",
        ],
        "entity_alias_summary": {
            "duplicate_groups_detected": entity_aliases.get("duplicate_groups_detected", 0),
            "duplicate_groups_reconciled": entity_aliases.get("duplicate_groups_reconciled", 0),
            "unresolved_duplicate_entities": entity_aliases.get("unresolved_duplicate_entities", 0),
        },
    }
    issues = privacy_issues(bundle)
    if not issues:
        bundle["privacy_validation_passed"] = True
    else:
        bundle["privacy_validation_errors"] = issues
    return bundle


def build_assistant_fetch(generated_at: str, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "repository": "tariye/sales-os",
        "branch": "main",
        "bundle_path": "memory/assistant_bundle.json",
        "health_path": "memory/system_health.json",
        "index_path": "memory/index.json",
        "generated_at": generated_at,
        "export_run_id": run_id,
        "fetch_strategy": [
            "Read GitHub API branch HEAD SHA",
            "Fetch assistant_bundle.json using immutable commit SHA",
            "Use GitHub contents API as fallback",
        ],
    }


def validation_report(conn: sqlite3.Connection, entity_aliases: dict[str, Any]) -> dict[str, Any]:
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
    duplicate_groups_detected = conn.execute(
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
    unresolved_duplicate_entities = int(entity_aliases.get("unresolved_duplicate_entities", duplicate_groups_detected))
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
        "duplicate_entities": unresolved_duplicate_entities,
        "duplicate_groups_detected": duplicate_groups_detected,
        "duplicate_groups_reconciled": int(entity_aliases.get("duplicate_groups_reconciled", 0)),
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


def update_last_push(push_time: str, commit_hash: str) -> None:
    health_path = MEMORY_DIR / "system_health.json"
    status_path = MEMORY_DIR / "export_status.json"
    activity_path = MEMORY_DIR / "activity.jsonl"
    fetch_path = MEMORY_DIR / "assistant_fetch.json"
    health = json.loads(health_path.read_text(encoding="utf-8"))
    export_status = json.loads(status_path.read_text(encoding="utf-8"))
    health["last_push"] = push_time
    health["last_push_commit"] = commit_hash
    export_status["last_push"] = push_time
    export_status["last_push_commit"] = commit_hash
    immutable_bundle_url = f"https://raw.githubusercontent.com/tariye/sales-os/{commit_hash}/memory/assistant_bundle.json"
    if fetch_path.exists():
        fetch_meta = json.loads(fetch_path.read_text(encoding="utf-8"))
        fetch_meta["last_verified_commit"] = commit_hash
        fetch_meta["immutable_bundle_url"] = immutable_bundle_url
        fetch_meta["last_verified_at"] = push_time
        write_json(fetch_path, fetch_meta)
    write_json(health_path, health)
    write_json(status_path, export_status)
    activity = read_jsonl(activity_path)
    activity.append(
        {
            "id": f"activity-{push_time}-{commit_hash[:12]}",
            "time": push_time,
            "type": "remote_push_verified",
            "entity": "GitHub memory bridge",
            "summary": f"Verified origin/main at {commit_hash}.",
            "immutable_bundle_url": immutable_bundle_url,
        }
    )
    write_jsonl(activity_path, activity[-500:])


def export_memory(args: argparse.Namespace) -> int:
    ensure_dirs()
    generated_at = now_iso()
    conn = connect()
    ensure_operating_tables(conn, generated_at)
    import_result = import_chat_inbox(conn, generated_at) if not args.skip_import else {"pending_before": 0, "imported": 0, "duplicates": 0, "archived": ""}
    entity_aliases = reconcile_entity_aliases(conn, generated_at)

    entries = fetch_entries(conn)
    actions = fetch_actions(conn)
    patterns = fetch_patterns(conn)
    watchlist = fetch_watchlist(conn)
    decisions = fetch_decisions(conn)
    projects = fetch_projects(conn)

    snapshot = build_snapshot(generated_at, entries, actions, patterns, watchlist, decisions, projects, entity_aliases, import_result)
    manifest = build_manifest(snapshot, actions, patterns)

    write_json(SNAPSHOT_DIR / "latest.json", snapshot)
    write_jsonl(MEMORY_DIR / "entries.jsonl", entries)
    write_jsonl(MEMORY_DIR / "actions.jsonl", actions)
    write_jsonl(MEMORY_DIR / "patterns.jsonl", patterns)
    write_jsonl(MEMORY_DIR / "watchlist.jsonl", watchlist)
    write_jsonl(MEMORY_DIR / "decisions.jsonl", decisions)
    write_jsonl(MEMORY_DIR / "projects.jsonl", projects)
    write_json(MEMORY_DIR / "entity_aliases.json", entity_aliases)
    write_json(MEMORY_DIR / "briefing_manifest.json", manifest)

    db_validation = validation_report(conn, entity_aliases)
    export_status = {
        "generated_at": generated_at,
        "export_success": False,
        "source_of_truth": source_of_truth_ref(),
        "chatgpt_contract_files": REQUIRED_FILES,
        "import_result": import_result,
        "validation": db_validation,
        "json_errors": [],
        "assistant_bundle": {
            "path": "memory/assistant_bundle.json",
            "max_bytes": 150000,
            "bytes": 0,
            "privacy_validation_passed": False,
        },
        "counts": {
            "entries": len(entries),
            "actions": len(actions),
            "patterns": len(patterns),
            "watchlist": len(watchlist),
            "decisions": len(decisions),
            "projects": len(projects),
            "entity_aliases": len(entity_aliases.get("aliases", [])),
        },
        "entity_aliases": {
            "duplicate_groups_detected": entity_aliases.get("duplicate_groups_detected", 0),
            "duplicate_groups_reconciled": entity_aliases.get("duplicate_groups_reconciled", 0),
            "unresolved_duplicate_entities": entity_aliases.get("unresolved_duplicate_entities", 0),
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
        "duplicate_groups_detected": db_validation["duplicate_groups_detected"],
        "duplicate_groups_reconciled": db_validation["duplicate_groups_reconciled"],
        "chat_inbox_pending": 0 if not (MEMORY_DIR / "chat_inbox.jsonl").read_text(encoding="utf-8").strip() else len(read_jsonl(MEMORY_DIR / "chat_inbox.jsonl")),
        "export_success": False,
    }

    index = {
        "version": "1.0",
        "generated_at": generated_at,
        "assistant_bundle": "memory/assistant_bundle.json",
        "assistant_fetch": "memory/assistant_fetch.json",
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
        "entity_aliases": "memory/entity_aliases.json",
    }
    write_json(MEMORY_DIR / "index.json", index)

    export_status["export_success"] = db_validation["ok"]
    health["export_success"] = export_status["export_success"]
    assistant_bundle = build_assistant_bundle(
        generated_at,
        entries,
        actions,
        patterns,
        watchlist,
        decisions,
        projects,
        manifest,
        health,
        entity_aliases,
    )
    assistant_fetch = build_assistant_fetch(generated_at, assistant_bundle["export_run_id"])
    write_json(MEMORY_DIR / "assistant_bundle.json", assistant_bundle)
    write_json(MEMORY_DIR / "assistant_fetch.json", assistant_fetch)
    bundle_size = (MEMORY_DIR / "assistant_bundle.json").stat().st_size
    bundle_errors = []
    if bundle_size > 150000:
        bundle_errors.append(f"assistant_bundle.json is {bundle_size} bytes; limit is 150000")
    if not assistant_bundle.get("privacy_validation_passed"):
        bundle_errors.extend(assistant_bundle.get("privacy_validation_errors") or ["privacy validation failed"])
    export_status["assistant_bundle"] = {
        "path": "memory/assistant_bundle.json",
        "max_bytes": 150000,
        "bytes": bundle_size,
        "privacy_validation_passed": bool(assistant_bundle.get("privacy_validation_passed")),
        "errors": bundle_errors,
    }
    if bundle_errors:
        export_status["export_success"] = False
        health["export_success"] = False
    write_json(MEMORY_DIR / "export_status.json", export_status)
    write_json(MEMORY_DIR / "system_health.json", health)
    activity = append_activity(generated_at, import_result, export_status)
    write_jsonl(MEMORY_DIR / "activity.jsonl", activity)

    export_errors = validate_json_exports()
    if bundle_errors:
        export_errors.extend(bundle_errors)
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
        run(["git", "pull", "--rebase", "--autostash"])
    code = export_memory(args)
    if code != 0:
        print("Memory export validation failed; not pushing.", file=sys.stderr)
        return code
    if args.git:
        run(["git", "add", "memory/", "tools/"])
        if run(["git", "diff", "--cached", "--quiet"], check=False).returncode != 0:
            run(["git", "commit", "-m", args.commit_message])
            run(["git", "push", "-u", "origin", "main"])
            pushed_commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
            run(["git", "fetch", "origin", "--prune"])
            remote_commit = run(["git", "rev-parse", "origin/main"]).stdout.strip()
            if remote_commit != pushed_commit:
                raise RuntimeError(f"push verification failed: origin/main={remote_commit}, expected={pushed_commit}")
            run(["python3", "tools/verify_chatgpt_fetch.py"])
            push_time = now_iso()
            update_last_push(push_time, pushed_commit)
            run(["git", "add", "memory/system_health.json", "memory/export_status.json", "memory/activity.jsonl", "memory/assistant_fetch.json"])
            if run(["git", "diff", "--cached", "--quiet"], check=False).returncode != 0:
                run(["git", "commit", "-m", "Record verified intelligence ledger push"])
                run(["git", "push", "-u", "origin", "main"])
                final_commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
                run(["git", "fetch", "origin", "--prune"])
                final_remote = run(["git", "rev-parse", "origin/main"]).stdout.strip()
                if final_remote != final_commit:
                    raise RuntimeError(f"final push verification failed: origin/main={final_remote}, expected={final_commit}")
                run(["python3", "tools/verify_chatgpt_fetch.py"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
