#!/usr/bin/env python3
"""
Info Analyzer OS v0.3 — Clean Intelligence Website

A local, append-only personal intelligence database.
The database is the product. The UI is the cockpit. ChatGPT is the processor.

Run:
  python3 server.py --host 127.0.0.1 --port 8000
Open:
  http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import uuid
import zipfile
from datetime import datetime, date, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree as ET

try:
    import anthropic as _anthropic
except Exception:
    _anthropic = None  # type: ignore


def _get_anthropic_client():
    if _anthropic is None:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        return _anthropic.Anthropic(api_key=key)
    except Exception:
        return None

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "info_analyzer.db"

APP_VERSION = "v0.70-unified-intelligence"
APP_VERSIONS = [
    {
        "version": "v0.1",
        "name": "SQLite Memory Foundation",
        "features": [
            "Local writable SQLite database",
            "Append-only memory ledger",
            "Basic browser UI",
            "Export/import foundation",
        ],
    },
    {
        "version": "v0.2",
        "name": "Pull Engine Foundation",
        "features": [
            "Trackability fields on every signal",
            "Pull rules for resurfacing memory",
            "Action cards",
            "Open action queue",
            "Pattern library",
            "Context packets after save",
        ],
    },
    {
        "version": "v0.3",
        "name": "Intelligence Website",
        "features": [
            "Command Center view",
            "Dormant Info Detector",
            "Result-required action lifecycle",
            "Database contextualization endpoint",
            "Version history endpoint",
            "Clean DB-first architecture",
        ],
    },
    {
        "version": "v0.4",
        "name": "Signal Translation Engine",
        "features": [
            "Operator classifications before memory save",
            "Actionability levels",
            "Pull trigger types",
            "Output card types",
            "Relationship suggestions",
            "Raw staging status with raw evidence preserved",
            "Translation contract endpoint",
        ],
    },
    {
        "version": "v0.41",
        "name": "Cockpit Action Controls",
        "features": [
            "Dormant info recategorize/delete controls",
            "Permanent DB delete endpoint",
            "Returned action recategorize/abort controls",
            "Cockpit warning/caution/advisory callout lanes",
            "Dump buttons renamed around contextualize/save flow",
        ],
    },
    {
        "version": "v0.42",
        "name": "Action Cards + Pattern Insights",
        "features": [
            "Returned actions reframed as execution cards",
            "Action cards include source, why it matters, exact steps, track metric, and abort logic",
            "Action controls reduced to Done, Extract Pattern, Abort",
            "Pattern Library cross-analyzes the database and returns insight cards",
        ],
    },
    {
        "version": "v0.43",
        "name": "Loop Engineering",
        "features": [
            "Loop analyzer endpoint",
            "QA scoring across specificity, friction, impact, trackability, context, and feedback",
            "First executable step, impact metric, feedback capture, and related-memory query fields",
            "Up to five refinement loops before final outcome",
            "Database JSON output for direct ledger saving",
        ],
    },
    {
        "version": "v0.44",
        "name": "Pattern Engine",
        "features": [
            "Database-wide pattern scans",
            "Pattern cards with severity, evidence, action, first step, metric, and trigger",
            "Cross-domain tag, entity, risk, backlog, and proof-pattern detection",
            "Pattern scan history stored locally",
            "Pattern Library scan button and engine output",
        ],
    },
    {
        "version": "v0.45",
        "name": "Command Pull Architecture",
        "features": [
            "PAM-A Pull Actionable Memory Algorithm",
            "Pull integrated into Command Center",
            "Quick Actions and Big-Picture Actions split",
            "Action List cards with Abort, Act, Recontextualize controls",
            "Contextual DB search over translated fields instead of raw dump only",
        ],
    },
    {
        "version": "v0.46",
        "name": "Precision Cockpit Pull",
        "features": [
            "Strong-field Pull matching with no false action surfacing",
            "No-match state for dead queries",
            "Quick Action promotion when a signal has action, first step, and metric",
            "Sales/business routing ahead of generic finance/network matches",
            "Pattern Engine severity caps for quieter cockpit output",
        ],
    },
    {
        "version": "v0.47",
        "name": "Signal Hygiene",
        "features": [
            "Bulk-imported news stub entries archived on startup",
            "Weak action titles backfilled using entity and signal context",
            "Clean action titles saved at entry creation, not raw returned_action",
            "Watch entries with review_date now generate trackable due actions",
            "Wallpaper defaults removed from interpretation, pattern, and lesson fields",
            "Stable action IDs per entry enabling true upsert on update",
        ],
    },
    {
        "version": "v0.48",
        "name": "UX Clarity",
        "features": [
            "Dump tab renamed to New Entry",
            "Workflow guide shows the three-step input flow",
            "Save to Memory is now the primary button — Translate and Loop Analysis are secondary",
            "Signal Translation Contract has a field hint explaining every field is optional",
            "Tooltips on Signal Type, Actionability, Card Type, and Pull Trigger Type selects",
            "Act renamed to Done — Log Result with confirm-then-log flow",
            "Recontextualize renamed to Re-translate, Abort/Dismiss renamed to Dismiss",
            "Detect Dormant Info button moved next to the dormant list it controls",
            "Open pulls stat renamed to Memory cards",
            "Empty states guide new users to New Entry tab",
            "Patterns tab reordered: Insights first, Engine Cards second, Records last",
        ],
    },
    {
        "version": "v0.49",
        "name": "AI Translate",
        "features": [
            "Claude Opus 4.8 wired into Translate Signal button",
            "Real AI-generated signal, interpretation, pattern, lesson, returned_action, first_step, tracking_metric, and more",
            "New /api/translate/ai endpoint — regex scaffold plus AI semantic layer",
            "Graceful fallback to regex-only if ANTHROPIC_API_KEY not set or API call fails",
            "Loading state on Translate Signal button during AI call",
            "ai_used flag in response indicates whether Claude ran",
        ],
    },
    {
        "version": "v0.50",
        "name": "Changelog",
        "features": [
            "Dedicated Changelog tab showing full build history",
            "Versions displayed newest-first with feature lists",
            "Current version highlighted with accent badge and 'current' pill",
            "Meta line: total versions, total shipped features, current build label",
            "Compact version cards still available in Command Center",
        ],
    },
    {
        "version": "v0.51",
        "name": "AI Guidance + Title Fix",
        "features": [
            "AI status banner near Translate button — tells user exactly what to do if Claude is not configured",
            "/api/ai/status endpoint returns sdk_installed, key_set, ai_enabled, model, hint",
            "Short title generator replaces raw-input truncation — first sentence, max 10 words, entity-prefixed",
            "Regex signal field cleaned up: no longer repeats the full raw input",
        ],
    },
    {
        "version": "v0.52",
        "name": "Claude Processing Queue",
        "features": [
            "pending_claude status — mark any entry for Claude Code to process",
            "Queue for Claude button on every Memory DB card",
            "GET /api/entries/queue — returns all pending entries plus full DB context for cross-entry analysis",
            "POST /api/translate/batch — Claude writes back translations for all entries in one call",
            "Claude queue count visible in Command Center stats",
            "Advisory cockpit callout when queue is non-empty",
            "Claude Code is now the AI processing layer — no API credits required",
        ],
    },
    {
        "version": "v0.60",
        "name": "Claude Architecture",
        "features": [
            "Dump-first UI — New Entry is now a clean raw input screen with no Translation Contract visible by default",
            "Save goes directly to pending_claude queue when no signal or interpretation is provided",
            "Translation Contract collapsed to optional 'Fill manually' panel for power users",
            "Queue as first-class tab in nav with live count badge",
            "Dedicated Queue tab showing all pending entries grouped by domain with word count hints",
            "Enrichment state badges on every entry card: Queued / AI Enriched / Extracted / Codified",
            "Parent-child relationship visible on cards — Extracted badge for child entries",
            "Interpretation shown as primary content on enriched entries, raw signal as fallback",
            "Lesson field surfaced directly on entry cards",
            "/api/entries/:id/decompose endpoint — full entry read + DB context + Claude instructions for deep decomposition",
            "Queue badge updates on save, queue toggle, and page load",
            "Command Center Queued stat replaces In Queue label",
        ],
    },
    {
        "version": "v0.61",
        "name": "Signal Hygiene",
        "features": [
            "needs_enrichment status for partial or generic entries",
            "Codified entries now require stronger signal quality before leaving the queue",
            "Context resurfacing ignores queued and half-translated memory",
            "Surfaced cards archived more aggressively to reduce cockpit backlog",
            "Command Center shows completion metrics and backlog saturation warnings",
            "New Entry wording aligned across the UI",
        ],
    },
    {
        "version": "v0.62",
        "name": "INNBANK Command Center",
        "features": [
            "Command Center reframed as the INNBANK value creation and capital routing engine",
            "New architecture view for mission engine, control plane, data planes, and sub-control planes",
            "Live domain counts wired into the INNBANK command surface",
            "Routing language now emphasizes value creation, capital flow, bottlenecks, and next allocation decisions",
        ],
    },
    {
        "version": "v0.63",
        "name": "Memory Field Hygiene",
        "features": [
            "Memory DB hides placeholder lesson, action, first-step, and metric text",
            "Startup cleanup clears the most obvious generic first-step and feedback boilerplate",
            "New entries no longer get a forced generic first-step or impact boilerplate from migration logic",
        ],
    },
    {
        "version": "v0.64",
        "name": "Display Hygiene",
        "features": [
            "Actions page hides generic why/track boilerplate when it adds no decision value",
            "Command Center routing cards suppress placeholder action, first-step, and metric text",
            "Post-save context packet hides generic resurfaced card fields instead of rendering system filler",
            "Pattern Engine cards hide placeholder action, first-step, and metric text",
        ],
    },
    {
        "version": "v0.65",
        "name": "Data Plane Imports",
        "features": [
            "Workbook import ledger for local .xlsx and .xlsb source files",
            "Structured import tables for batches, sheets, and normalized source rows",
            "Portfolio trades, risk/reward setups, watchlists, and watchlist items stored in dedicated SQLite tables",
            "Binary Libre parser workbook ingested as sheet-level manifest with parser-status visibility",
            "New workbook import API and CLI path for loading source systems into the database",
            "Command Center now reports imported data-plane counts and recent source systems",
        ],
    },
    {
        "version": "v0.66",
        "name": "INNBANK Control Plane Alignment",
        "features": [
            "Website language fully reframed around INNBANK as the value creation and capital routing engine",
            "Command Center now presents mission engine, control plane, data planes, and sub-control planes as first-class UX objects",
            "Control-plane questions make the dashboard answer what value is being created, what resources are controlled, and where attention should route next",
            "Imported source systems are displayed as structured data planes instead of hidden database tables",
            "Cockpit lanes renamed around bottlenecks, routing review, and system watch to match the capital-routing model",
            "Pull workflow reframed from search to routing: Route Next Moves, Immediate Routing Moves, and System-Level Moves",
        ],
    },
    {
        "version": "v0.67",
        "name": "Contextual Memory Chip",
        "features": [
            "Every entry gets a persisted memory chip that captures capture, organize, improve, reuse, and compound",
            "Contextual synthesis links entries by domain, entity, state, and preference",
            "Preference plus current need can synthesize a direct action",
            "Rebuild Context Memory endpoint backfills the database",
            "Entry cards show the contextual chip instead of isolated notes",
        ],
    },
    {
        "version": "v0.70",
        "name": "Unified Sales Intelligence",
        "features": [
            "Single site, multiple functions: Intelligence Ledger + Market Trends + Watchlist Evidence + Command Center",
            "Market data (eBay sales volume/price) flows into signals database automatically",
            "Real-time sales trends visualization with volume and price charts",
            "Watchlist evidence cards link to eBay research with margin calculations",
            "Discovery products ranked by sales volume with 40-item trending list",
            "Unified database: raw sales data + analyzed signals + opportunities",
            "New endpoints: /api/sales/trends, /api/sales/watchlist, /api/sales/discovery, /api/sales/opportunities",
            "Multi-view frontend with intelligent tab navigation",
            "Command Center now shows alerts from both intelligence and market data layers",
        ],
    },
]

STATUS_VALUES = {"raw", "pending_claude", "needs_enrichment", "codified", "watching", "validated", "weakened", "upgraded", "superseded", "archived"}
ACTION_STATUSES = {"open", "in_progress", "waiting", "done", "cancelled"}
SIGNAL_ROLES = {"action", "watch", "pattern", "risk", "opportunity", "contradiction", "proof", "preference", "reference", "archive"}
ACTIONABILITY_LEVELS = {"now", "next", "watch", "review", "link_only", "proof", "no_action"}
PULL_TRIGGER_TYPES = {"tag", "entity", "domain", "review_date", "threshold", "repetition", "contradiction", "action", "preference", "reference"}
CARD_TYPES = {"Action Card", "Watch Card", "Pattern Card", "Risk Card", "Opportunity Card", "Contradiction Card", "Proof Card", "Review Card", "Preference Card", "Reference Card", "Archive Card"}
REL_TYPES = {"connects", "validates", "contradicts", "expands", "refines", "supersedes", "produces", "repeats"}
DOMAINS = ["Lab", "Investing", "Business", "Career", "Fitness", "Network+", "Music", "AI Project", "Personal Finance", "Personal Preference", "Other"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def make_id(prefix="IA") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"


def clean_text(value) -> str:
    return str(value or "").strip()


def normalize_text(value) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9+#.:%$\-/\s]", " ", str(value or "").lower())).strip()


def normalize_tags(tags) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, list):
        raw = tags
    else:
        raw = re.split(r"[,#]", str(tags))
    out = []
    for tag in raw:
        t = normalize_text(tag).strip("- ")
        if t and t not in out:
            out.append(t)
    return out[:30]


def json_loads(value, fallback):
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1]


def stable_json(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def to_float(value):
    text = clean_text(value).replace(",", "")
    if not text:
        return None
    lowered = text.lower()
    if any(token in lowered for token in ("k", "m", "b")) and not re.fullmatch(r"-?\d+(\.\d+)?", lowered):
        return None
    text = text.replace("$", "").replace("%", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        try:
            return float(text)
        except Exception:
            return None
    return None


def to_int(value):
    num = to_float(value)
    if num is None:
        return None
    return int(round(num))


def excel_serial_to_iso(value):
    num = to_float(value)
    if num is None:
        return ""
    if num < 20000 or num > 80000:
        return ""
    base = datetime(1899, 12, 30, tzinfo=timezone.utc)
    try:
        converted = base.timestamp() + (num * 86400)
        return datetime.fromtimestamp(converted, tz=timezone.utc).date().isoformat()
    except Exception:
        return ""


def is_probably_header(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if len(t) > 80:
        return False
    return bool(re.search(r"[A-Za-z]", t))


def clean_header_name(value: str, index: int, seen: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", clean_text(value).lower()).strip("_") or f"col_{index + 1}"
    name = base
    n = 2
    while name in seen:
        name = f"{base}_{n}"
        n += 1
    seen.add(name)
    return name


def row_nonempty(values) -> list[str]:
    return [clean_text(v) for v in values if clean_text(v)]


def dedupe_strings(values):
    out = []
    seen = set()
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            out.append(text)
            seen.add(text)
    return out


def first_present(mapping: dict, *keys: str) -> str:
    for key in keys:
        value = clean_text(mapping.get(key))
        if value:
            return value
    return ""


def map_field(row: dict, *keys: str):
    return first_present(row, *keys)


def sheet_header_guess(rows: list[dict], probe: int = 8) -> int:
    best_row = 0
    best_score = -1
    for idx, row in enumerate(rows[:probe]):
        values = row_nonempty(row.get("values") or [])
        if len(values) < 2:
            continue
        headerish = sum(1 for value in values if is_probably_header(value))
        score = (len(values) * 2) + headerish
        if score > best_score:
            best_score = score
            best_row = idx
    return best_row


def map_rows_from_header(rows: list[dict], header_index: int) -> tuple[list[str], list[dict]]:
    if not rows:
        return [], []
    header_values = rows[header_index].get("values") or []
    seen = set()
    headers = [clean_header_name(value, idx, seen) for idx, value in enumerate(header_values)]
    mapped = []
    for row in rows[header_index + 1:]:
        values = row.get("values") or []
        if not row_nonempty(values):
            continue
        payload = {headers[idx]: clean_text(values[idx]) if idx < len(values) else "" for idx in range(len(headers))}
        payload = {k: v for k, v in payload.items() if v}
        if payload:
            mapped.append({"row_number": row["row_number"], "values": values, "data": payload})
    return headers, mapped


def record_fingerprint(batch_id: str, sheet_name: str, row_number: int, payload: dict) -> str:
    raw = f"{batch_id}|{sheet_name}|{row_number}|{stable_json(payload)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def path_signature(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def sheet_sample_rows(rows: list[dict], limit: int = 3) -> list[dict]:
    samples = []
    for row in rows[:limit]:
        values = [clean_text(v) for v in row.get("values") or [] if clean_text(v)]
        if values:
            samples.append({"row_number": row["row_number"], "values": values[:12]})
    return samples


def xlsx_cell_value(cell, shared_strings, ns) -> str:
    ctype = cell.attrib.get("t")
    if ctype == "inlineStr":
        return "".join((t.text or "") for t in cell.findall(".//a:t", ns)).strip()
    value_node = cell.find("a:v", ns)
    if value_node is None:
        return ""
    raw = value_node.text or ""
    if ctype == "s":
        try:
            return clean_text(shared_strings[int(raw)])
        except Exception:
            return clean_text(raw)
    if ctype == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return clean_text(raw)


def xlsx_col_index(cell_ref: str) -> int:
    letters = re.match(r"([A-Z]+)", cell_ref or "")
    if not letters:
        return 0
    idx = 0
    for ch in letters.group(1):
        idx = (idx * 26) + (ord(ch) - 64)
    return max(idx - 1, 0)


def parse_xlsx_workbook(path: Path) -> dict:
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(path) as zf:
        shared_strings = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                shared_strings.append("".join((t.text or "") for t in si.iterfind(".//a:t", ns)))
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib.get("Id"): rel.attrib.get("Target") for rel in rels.findall("rel:Relationship", ns)}
        sheets = []
        for sheet_index, sheet in enumerate(workbook.find("a:sheets", ns) or [], start=1):
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rel_id, "")
            sheet_path = "xl/" + target.lstrip("/")
            sheet_root = ET.fromstring(zf.read(sheet_path))
            rows = []
            max_cols = 0
            for row in sheet_root.findall(".//a:sheetData/a:row", ns):
                cells = {}
                for cell in row.findall("a:c", ns):
                    idx = xlsx_col_index(cell.attrib.get("r", ""))
                    cells[idx] = xlsx_cell_value(cell, shared_strings, ns)
                if not cells:
                    continue
                max_cols = max(max_cols, max(cells) + 1)
                values = [""] * (max(cells) + 1)
                for idx, value in cells.items():
                    values[idx] = value
                rows.append({"row_number": int(row.attrib.get("r") or len(rows) + 1), "values": values})
            # Normalize widths after full scan so mapped headers align across rows.
            normalized_rows = []
            for row in rows:
                values = list(row["values"])
                if len(values) < max_cols:
                    values.extend([""] * (max_cols - len(values)))
                normalized_rows.append({"row_number": row["row_number"], "values": values})
            sheets.append({
                "sheet_index": sheet_index,
                "sheet_name": sheet.attrib.get("name") or f"Sheet{sheet_index}",
                "source_ref": sheet_path,
                "rows": normalized_rows,
            })
    return {"kind": "xlsx", "sheets": sheets}


def parse_xlsb_manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        app = ET.fromstring(zf.read("docProps/app.xml"))
        core = ET.fromstring(zf.read("docProps/core.xml"))
        titles_node = next((child for child in app if local_tag(child.tag) == "TitlesOfParts"), None)
        titles = []
        if titles_node is not None:
            titles = [clean_text(text) for text in titles_node.itertext() if clean_text(text) and "!Print_" not in clean_text(text)]
        sheet_files = sorted(
            (name for name in zf.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".bin")),
            key=lambda name: int(re.search(r"sheet(\d+)\.bin", name).group(1)),
        )
        sheet_titles = titles[:len(sheet_files)] if titles else []
        metadata = {}
        for child in core:
            text = clean_text(child.text)
            if text:
                metadata[local_tag(child.tag)] = text
        workbook_title = metadata.get("title") or path.stem
        sheets = []
        for idx, sheet_name in enumerate(sheet_files, start=1):
            info = zf.getinfo(sheet_name)
            label = sheet_titles[idx - 1] if idx - 1 < len(sheet_titles) else f"Sheet{idx}"
            sheets.append({
                "sheet_index": idx,
                "sheet_name": label,
                "source_ref": sheet_name,
                "size_bytes": info.file_size,
            })
    return {"kind": "xlsb", "workbook_title": workbook_title, "metadata": metadata, "sheets": sheets}


class ClosingConnection(sqlite3.Connection):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _fix_weak_action_titles(conn) -> None:
    weak = {"insights", "insight", "review", "watch", "analyze", "action", "next step"}
    rows = conn.execute(
        "SELECT a.id, a.entry_id, a.action_title FROM actions a WHERE status NOT IN ('done','cancelled')"
    ).fetchall()
    now = now_iso()
    for row in rows:
        raw = normalize_text(clean_text(row["action_title"])).strip(". ")
        is_weak = (
            raw in weak
            or raw.startswith("click track signal")
            or bool(re.search(
                r"compare against the old thesis|save retrieve related memories|"
                r"review this memory|execute/track action|execute the next concrete step",
                raw,
            ))
        )
        if is_weak:
            entry_row = conn.execute("SELECT * FROM entries WHERE id=?", (row["entry_id"],)).fetchone()
            if entry_row:
                entry = row_to_entry(entry_row)
                new_title = clean_action_title(entry)
                if new_title != row["action_title"]:
                    conn.execute(
                        "UPDATE actions SET action_title=?, updated_at=? WHERE id=?",
                        (new_title, now, row["id"]),
                    )


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            date TEXT NOT NULL,
            title TEXT,
            domain TEXT DEFAULT 'Other',
            entity TEXT,
            source_type TEXT DEFAULT 'manual',
            raw_input TEXT NOT NULL,
            signal TEXT,
            interpretation TEXT,
            signal_role TEXT DEFAULT 'watch',
            actionability TEXT DEFAULT 'watch',
            pull_trigger_type TEXT DEFAULT 'tag',
            pull_trigger TEXT,
            relationship_type TEXT DEFAULT 'connects',
            card_type TEXT DEFAULT 'Watch Card',
            result_to_track TEXT,
            first_step TEXT,
            impact_metric TEXT,
            feedback_to_capture TEXT,
            related_memory_query TEXT,
            qa_scores TEXT DEFAULT '{}',
            raw_staging_status TEXT DEFAULT 'processed',
            trackable_as TEXT,
            tracking_metric TEXT,
            baseline TEXT,
            target_threshold TEXT,
            trigger_condition TEXT,
            review_date TEXT,
            pattern TEXT,
            returned_action TEXT,
            action_status TEXT DEFAULT 'open',
            result TEXT,
            lesson TEXT,
            next_step TEXT,
            confidence TEXT DEFAULT 'Medium',
            status TEXT DEFAULT 'codified',
            tags TEXT DEFAULT '[]',
            proof_artifact TEXT,
            parent_entry_id TEXT,
            supersedes_entry_id TEXT,
            memory_version INTEGER DEFAULT 1,
            last_resurfaced TEXT,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(parent_entry_id) REFERENCES entries(id),
            FOREIGN KEY(supersedes_entry_id) REFERENCES entries(id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
            entry_id UNINDEXED,
            title,
            domain,
            entity,
            raw_input,
            signal,
            interpretation,
            pattern,
            lesson,
            tags_text
        );

        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            from_entry_id TEXT NOT NULL,
            to_entry_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            note TEXT,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(from_entry_id) REFERENCES entries(id),
            FOREIGN KEY(to_entry_id) REFERENCES entries(id)
        );

        CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            action_title TEXT NOT NULL,
            why TEXT,
            track_metric TEXT,
            due_date TEXT,
            priority TEXT DEFAULT 'Medium',
            status TEXT DEFAULT 'open',
            result TEXT,
            lesson_update TEXT,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(entry_id) REFERENCES entries(id)
        );

        CREATE TABLE IF NOT EXISTS pull_rules (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_value TEXT NOT NULL,
            priority TEXT DEFAULT 'Medium',
            active INTEGER DEFAULT 1,
            last_triggered TEXT,
            metadata TEXT DEFAULT '{}',
            UNIQUE(entry_id, trigger_type, trigger_value),
            FOREIGN KEY(entry_id) REFERENCES entries(id)
        );

        CREATE TABLE IF NOT EXISTS surfaced_cards (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_entry_id TEXT NOT NULL,
            triggered_by_entry_id TEXT,
            triggered_by_raw TEXT,
            score INTEGER DEFAULT 0,
            reason TEXT,
            action_card TEXT DEFAULT '{}',
            status TEXT DEFAULT 'open',
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(source_entry_id) REFERENCES entries(id),
            FOREIGN KEY(triggered_by_entry_id) REFERENCES entries(id)
        );

        CREATE TABLE IF NOT EXISTS pattern_stats (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            pattern TEXT NOT NULL UNIQUE,
            domains TEXT DEFAULT '[]',
            tags TEXT DEFAULT '[]',
            entry_count INTEGER DEFAULT 0,
            confidence TEXT DEFAULT 'Medium',
            last_entry_id TEXT,
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS pattern_runs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            scan_type TEXT DEFAULT 'full',
            summary TEXT,
            cards TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            payload TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS import_batches (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_ext TEXT NOT NULL,
            source_signature TEXT NOT NULL UNIQUE,
            import_kind TEXT DEFAULT 'workbook',
            parser_name TEXT,
            status TEXT DEFAULT 'imported',
            sheet_count INTEGER DEFAULT 0,
            row_count INTEGER DEFAULT 0,
            projected_count INTEGER DEFAULT 0,
            notes TEXT,
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS import_sheets (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sheet_index INTEGER DEFAULT 0,
            sheet_name TEXT NOT NULL,
            source_ref TEXT,
            parser_status TEXT DEFAULT 'imported',
            header_row INTEGER,
            nonempty_rows INTEGER DEFAULT 0,
            projected_rows INTEGER DEFAULT 0,
            columns_json TEXT DEFAULT '[]',
            sample_rows_json TEXT DEFAULT '[]',
            notes TEXT,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(batch_id) REFERENCES import_batches(id)
        );

        CREATE TABLE IF NOT EXISTS import_rows (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            row_kind TEXT DEFAULT 'data',
            record_type TEXT DEFAULT 'raw',
            domain TEXT DEFAULT 'Other',
            entity TEXT,
            parser_status TEXT DEFAULT 'imported',
            fingerprint TEXT,
            raw_json TEXT DEFAULT '{}',
            normalized_json TEXT DEFAULT '{}',
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(batch_id) REFERENCES import_batches(id),
            FOREIGN KEY(sheet_id) REFERENCES import_sheets(id)
        );

        CREATE TABLE IF NOT EXISTS portfolio_trades (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL,
            source_row_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            symbol TEXT,
            avg_price REAL,
            invested_amount REAL,
            shares REAL,
            sell_price REAL,
            returns_amount REAL,
            pnl_per_share REAL,
            pct_change REAL,
            volume_text TEXT,
            trade_date_text TEXT,
            hold_period_days INTEGER,
            account TEXT,
            raw_fields TEXT DEFAULT '{}',
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(batch_id) REFERENCES import_batches(id),
            FOREIGN KEY(sheet_id) REFERENCES import_sheets(id),
            FOREIGN KEY(source_row_id) REFERENCES import_rows(id)
        );

        CREATE TABLE IF NOT EXISTS risk_reward_setups (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL,
            source_row_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            calc_type TEXT,
            symbol TEXT,
            avg_price REAL,
            shares REAL,
            invested_amount REAL,
            trigger_price REAL,
            returns_amount REAL,
            pnl_per_share REAL,
            pct_change REAL,
            raw_fields TEXT DEFAULT '{}',
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(batch_id) REFERENCES import_batches(id),
            FOREIGN KEY(sheet_id) REFERENCES import_sheets(id),
            FOREIGN KEY(source_row_id) REFERENCES import_rows(id)
        );

        CREATE TABLE IF NOT EXISTS watchlists (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            header_row INTEGER,
            item_count INTEGER DEFAULT 0,
            notes TEXT,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(batch_id) REFERENCES import_batches(id),
            FOREIGN KEY(sheet_id) REFERENCES import_sheets(id)
        );

        CREATE TABLE IF NOT EXISTS watchlist_items (
            id TEXT PRIMARY KEY,
            watchlist_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL,
            source_row_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            row_number INTEGER,
            display_name TEXT,
            ticker TEXT,
            sector TEXT,
            industry TEXT,
            catalyst TEXT,
            note TEXT,
            price REAL,
            peak_52w REAL,
            target_price REAL,
            support_price REAL,
            resistance_1 REAL,
            resistance_2 REAL,
            return_potential REAL,
            raw_fields TEXT DEFAULT '{}',
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(watchlist_id) REFERENCES watchlists(id),
            FOREIGN KEY(batch_id) REFERENCES import_batches(id),
            FOREIGN KEY(sheet_id) REFERENCES import_sheets(id),
            FOREIGN KEY(source_row_id) REFERENCES import_rows(id)
        );

        CREATE TABLE IF NOT EXISTS device_log_catalog (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            sheet_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            workbook_title TEXT,
            sheet_name TEXT NOT NULL,
            sheet_index INTEGER DEFAULT 0,
            size_bytes INTEGER DEFAULT 0,
            parser_status TEXT DEFAULT 'manifest_only',
            notes TEXT,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY(batch_id) REFERENCES import_batches(id),
            FOREIGN KEY(sheet_id) REFERENCES import_sheets(id)
        );

        CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_entries_domain ON entries(domain);
        CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status);
        CREATE INDEX IF NOT EXISTS idx_entries_action_status ON entries(action_status);
        CREATE INDEX IF NOT EXISTS idx_entries_signal_role ON entries(signal_role);
        CREATE INDEX IF NOT EXISTS idx_entries_review_date ON entries(review_date);
        CREATE INDEX IF NOT EXISTS idx_entries_entity ON entries(entity);
        CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_entry_id);
        CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_entry_id);
        CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
        CREATE INDEX IF NOT EXISTS idx_actions_due ON actions(due_date);
        CREATE INDEX IF NOT EXISTS idx_pull_rules_active ON pull_rules(active, trigger_type, trigger_value);
        CREATE INDEX IF NOT EXISTS idx_surfaced_status ON surfaced_cards(status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_pattern_runs_created ON pattern_runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_import_batches_created ON import_batches(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_import_sheets_batch ON import_sheets(batch_id, sheet_index);
        CREATE INDEX IF NOT EXISTS idx_import_rows_batch ON import_rows(batch_id, sheet_name, row_number);
        CREATE INDEX IF NOT EXISTS idx_import_rows_record_type ON import_rows(record_type, domain);
        CREATE INDEX IF NOT EXISTS idx_portfolio_trades_symbol ON portfolio_trades(symbol, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_risk_reward_symbol ON risk_reward_setups(symbol, calc_type);
        CREATE INDEX IF NOT EXISTS idx_watchlists_batch ON watchlists(batch_id, strategy_name);
        CREATE INDEX IF NOT EXISTS idx_watchlist_items_watchlist ON watchlist_items(watchlist_id, row_number);
        CREATE INDEX IF NOT EXISTS idx_device_log_catalog_batch ON device_log_catalog(batch_id, sheet_index);
        """)
        ensure_column(conn, "entries", "actionability", "TEXT DEFAULT 'watch'")
        ensure_column(conn, "entries", "pull_trigger_type", "TEXT DEFAULT 'tag'")
        ensure_column(conn, "entries", "pull_trigger", "TEXT")
        ensure_column(conn, "entries", "relationship_type", "TEXT DEFAULT 'connects'")
        ensure_column(conn, "entries", "card_type", "TEXT DEFAULT 'Watch Card'")
        ensure_column(conn, "entries", "result_to_track", "TEXT")
        ensure_column(conn, "entries", "first_step", "TEXT")
        ensure_column(conn, "entries", "impact_metric", "TEXT")
        ensure_column(conn, "entries", "feedback_to_capture", "TEXT")
        ensure_column(conn, "entries", "related_memory_query", "TEXT")
        ensure_column(conn, "entries", "qa_scores", "TEXT DEFAULT '{}'")
        ensure_column(conn, "entries", "raw_staging_status", "TEXT DEFAULT 'processed'")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pattern_runs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                scan_type TEXT DEFAULT 'full',
                summary TEXT,
                cards TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pattern_runs_created ON pattern_runs(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_actionability ON entries(actionability)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_card_type ON entries(card_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_raw_staging ON entries(raw_staging_status)")
        conn.execute("UPDATE entries SET actionability=COALESCE(NULLIF(actionability, ''), CASE WHEN signal_role='action' THEN 'next' WHEN signal_role='proof' THEN 'proof' WHEN signal_role='archive' THEN 'no_action' ELSE 'watch' END)")
        conn.execute("UPDATE entries SET card_type=COALESCE(NULLIF(card_type, ''), CASE signal_role WHEN 'action' THEN 'Action Card' WHEN 'pattern' THEN 'Pattern Card' WHEN 'risk' THEN 'Risk Card' WHEN 'opportunity' THEN 'Opportunity Card' WHEN 'contradiction' THEN 'Contradiction Card' WHEN 'proof' THEN 'Proof Card' WHEN 'archive' THEN 'Archive Card' ELSE 'Watch Card' END)")
        conn.execute("UPDATE entries SET actionability=CASE WHEN signal_role IN ('action','risk','opportunity') THEN 'next' WHEN signal_role='contradiction' THEN 'review' WHEN signal_role='proof' THEN 'proof' WHEN signal_role IN ('reference') THEN 'link_only' WHEN signal_role='archive' THEN 'no_action' ELSE actionability END WHERE actionability='watch'")
        conn.execute("UPDATE entries SET card_type=CASE signal_role WHEN 'action' THEN 'Action Card' WHEN 'pattern' THEN 'Pattern Card' WHEN 'risk' THEN 'Risk Card' WHEN 'opportunity' THEN 'Opportunity Card' WHEN 'contradiction' THEN 'Contradiction Card' WHEN 'proof' THEN 'Proof Card' WHEN 'preference' THEN 'Preference Card' WHEN 'reference' THEN 'Reference Card' WHEN 'archive' THEN 'Archive Card' ELSE card_type END WHERE card_type='Watch Card'")
        conn.execute("UPDATE entries SET pull_trigger_type=COALESCE(NULLIF(pull_trigger_type, ''), CASE WHEN signal_role='action' THEN 'action' WHEN signal_role='pattern' THEN 'repetition' WHEN signal_role='contradiction' THEN 'contradiction' ELSE 'tag' END)")
        conn.execute("UPDATE entries SET pull_trigger_type=CASE WHEN signal_role IN ('action','risk','opportunity') THEN 'action' WHEN signal_role='pattern' THEN 'repetition' WHEN signal_role='contradiction' THEN 'contradiction' WHEN signal_role='preference' THEN 'preference' WHEN signal_role='reference' THEN 'reference' ELSE pull_trigger_type END WHERE pull_trigger_type='tag'")
        conn.execute("UPDATE entries SET pull_trigger=COALESCE(NULLIF(pull_trigger, ''), NULLIF(trigger_condition, ''), 'Resurface when a matching domain, entity, tag, action, or review context appears.')")
        conn.execute("UPDATE entries SET result_to_track=COALESCE(NULLIF(result_to_track, ''), NULLIF(tracking_metric, ''), NULLIF(trackable_as, ''), 'Define observable result before treating this signal as complete.')")
        conn.execute("UPDATE entries SET related_memory_query=COALESCE(NULLIF(related_memory_query, ''), LOWER(COALESCE(domain, '') || ' ' || COALESCE(entity, '') || ' ' || COALESCE(signal_role, '') || ' ' || COALESCE(pattern, '')))")
        conn.execute("UPDATE entries SET qa_scores=COALESCE(NULLIF(qa_scores, ''), '{}')")
        conn.execute("UPDATE entries SET raw_staging_status=COALESCE(NULLIF(raw_staging_status, ''), 'processed')")
        _now = now_iso()
        # v0.47: archive bulk-imported news stubs that carry no real signal value
        conn.execute(
            "UPDATE entries SET status='archived', action_status='cancelled', updated_at=? "
            "WHERE (raw_input LIKE 'Economic Action: Track or archive latest info:%' "
            "       OR returned_action LIKE 'Click Track Signal%') AND status != 'archived'",
            (_now,),
        )
        conn.execute(
            "UPDATE actions SET status='cancelled', updated_at=? "
            "WHERE action_title LIKE 'Click Track Signal%' AND status NOT IN ('done','cancelled')",
            (_now,),
        )
        # v0.47: fix weak/generic action titles using entity and signal context
        _fix_weak_action_titles(conn)
        # v0.47: propagate review_date to action due_date so overdue entries surface in the queue
        conn.execute(
            "UPDATE actions SET "
            "  due_date=(SELECT review_date FROM entries WHERE entries.id=actions.entry_id), "
            "  updated_at=? "
            "WHERE (SELECT COALESCE(TRIM(review_date),'') FROM entries WHERE entries.id=actions.entry_id) != '' "
            "  AND COALESCE(TRIM(due_date),'') = '' "
            "  AND status NOT IN ('done','cancelled')",
            (_now,),
        )
        conn.execute(
            "UPDATE entries SET first_step='', updated_at=? "
            "WHERE TRIM(COALESCE(first_step,'')) IN ("
            "  'Open the entry, execute the returned action, and log the result.',"
            "  'Save, retrieve related memories, execute/track action, then log result.'"
            ")",
            (_now,),
        )
        conn.execute(
            "UPDATE entries SET impact_metric='', updated_at=? "
            "WHERE TRIM(COALESCE(impact_metric,''))='Decision clarity improved, risk reduced, quality improved, time saved, proof created, or revenue increased.'",
            (_now,),
        )
        conn.execute(
            "UPDATE entries SET feedback_to_capture='', updated_at=? "
            "WHERE TRIM(COALESCE(feedback_to_capture,''))='Log what happened, proof produced, metric changed, and whether the action should repeat.'",
            (_now,),
        )
        rows = conn.execute("SELECT * FROM entries").fetchall()
        for row in rows:
            entry = apply_entry_hygiene(row_to_entry(row), row["status"])
            conn.execute(
                "UPDATE entries SET status=?, raw_staging_status=?, metadata=?, updated_at=? WHERE id=?",
                (
                    entry["status"],
                    entry["raw_staging_status"],
                    json.dumps(entry.get("metadata") or {}, ensure_ascii=False),
                    _now,
                    entry["id"],
                ),
            )
        conn.execute(
            """
            UPDATE surfaced_cards
            SET status='archived', updated_at=?
            WHERE status='open'
              AND EXISTS (
                SELECT 1 FROM entries e
                WHERE e.id=surfaced_cards.source_entry_id
                  AND (e.status IN ('archived','superseded') OR e.action_status IN ('done','cancelled'))
              )
            """,
            (_now,),
        )
        card_rows = conn.execute(
            "SELECT id, source_entry_id FROM surfaced_cards WHERE status='open' ORDER BY updated_at DESC, score DESC"
        ).fetchall()
        seen_sources = set()
        for row in card_rows:
            source_id = row["source_entry_id"]
            if source_id in seen_sources:
                conn.execute("UPDATE surfaced_cards SET status='archived', updated_at=? WHERE id=?", (_now, row["id"]))
                continue
            seen_sources.add(source_id)
        rebuild_contextual_memory(conn)
        conn.commit()


def ensure_column(conn, table: str, column: str, definition: str) -> None:
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def row_to_entry(row) -> dict:
    d = dict(row)
    d["tags"] = json_loads(d.get("tags"), [])
    d["metadata"] = json_loads(d.get("metadata"), {})
    d["qa_scores"] = json_loads(d.get("qa_scores"), {})
    return d


def row_to_action(row) -> dict:
    d = dict(row)
    d["metadata"] = json_loads(d.get("metadata"), {})
    return d


def action_execution_card(action: dict) -> dict:
    metadata = action.get("metadata") or {}
    source_title = action.get("source_title") or metadata.get("source_title") or action.get("entry_id")
    source_signal = action.get("source_signal") or metadata.get("source_signal") or action.get("why") or ""
    source_domain = action.get("source_domain") or metadata.get("source_domain") or ""
    source_card_type = action.get("source_card_type") or metadata.get("card_type") or "Action Card"
    action_name = action.get("action_title") or "Returned action"
    track = action.get("track_metric") or metadata.get("result_to_track") or "Define proof/result before closing."
    why = action.get("why") or source_signal or "This action came from a translated signal."
    exact_steps = [
        f"Open the source memory: {source_title}.",
        f"Execute the named action: {action_name}.",
        f"Track proof using: {track}.",
        "Return here and mark Done only after logging result/proof.",
    ]
    if source_card_type in {"Risk Card", "Contradiction Card"}:
        exact_steps.insert(2, "Check whether the risk weakens, validates, or supersedes the old thesis.")
    return {
        "action_name": action_name,
        "source": source_title,
        "source_domain": source_domain,
        "source_signal": source_signal,
        "card_type": source_card_type,
        "why_it_matters": why,
        "exact_actions": exact_steps,
        "track": track,
        "done_prompt": "What result or proof did this produce?",
        "pattern_prompt": "What reusable pattern does this action reveal?",
        "abort_prompt": "Why is this action no longer worth doing?",
    }


def row_to_card(row) -> dict:
    d = dict(row)
    d["action_card"] = json_loads(d.get("action_card"), {})
    d["metadata"] = json_loads(d.get("metadata"), {})
    return d


def audit(conn, event_type, entity_type, entity_id, payload=None) -> None:
    conn.execute(
        "INSERT INTO audit_log (id, created_at, event_type, entity_type, entity_id, payload) VALUES (?, ?, ?, ?, ?, ?)",
        (make_id("AUD"), now_iso(), event_type, entity_type, entity_id, json.dumps(payload or {}, ensure_ascii=False)),
    )


def row_with_json(row, *json_fields):
    data = dict(row)
    for field in json_fields:
        fallback = [] if field in {"columns_json", "sample_rows_json"} else {}
        data[field] = json_loads(data.get(field), fallback)
    return data


def workbook_import_capabilities() -> dict:
    return {
        "extensions": [".xlsx", ".xlsb"],
        "xlsx_mode": "full_rows",
        "xlsb_mode": "manifest_only",
        "note": "Binary .xlsb row-level parsing is not available in this environment without an additional reader package.",
    }


def insert_import_sheet(conn, batch_id: str, sheet_index: int, sheet_name: str, source_ref: str, parser_status: str, header_row=None, nonempty_rows=0, projected_rows=0, columns=None, sample_rows=None, notes="", metadata=None) -> str:
    sheet_id = make_id("ISHT")
    conn.execute(
        """
        INSERT INTO import_sheets (
            id, batch_id, created_at, sheet_index, sheet_name, source_ref, parser_status,
            header_row, nonempty_rows, projected_rows, columns_json, sample_rows_json, notes, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sheet_id,
            batch_id,
            now_iso(),
            sheet_index,
            sheet_name,
            source_ref,
            parser_status,
            header_row,
            nonempty_rows,
            projected_rows,
            json.dumps(columns or [], ensure_ascii=False),
            json.dumps(sample_rows or [], ensure_ascii=False),
            notes,
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    return sheet_id


def insert_import_row(conn, batch_id: str, sheet_id: str, sheet_name: str, row_number: int, row_kind: str, record_type: str, domain: str, entity: str, parser_status: str, raw_payload: dict, normalized_payload=None, metadata=None) -> str:
    row_id = make_id("IROW")
    normalized_payload = normalized_payload or {}
    conn.execute(
        """
        INSERT INTO import_rows (
            id, batch_id, sheet_id, created_at, sheet_name, row_number, row_kind, record_type,
            domain, entity, parser_status, fingerprint, raw_json, normalized_json, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row_id,
            batch_id,
            sheet_id,
            now_iso(),
            sheet_name,
            row_number,
            row_kind,
            record_type,
            domain,
            entity,
            parser_status,
            record_fingerprint(batch_id, sheet_name, row_number, raw_payload),
            json.dumps(raw_payload or {}, ensure_ascii=False),
            json.dumps(normalized_payload, ensure_ascii=False),
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )
    return row_id


def load_import_batch(conn, batch_id: str) -> dict:
    row = conn.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
    if not row:
        raise KeyError("import batch not found")
    batch = row_with_json(row, "metadata")
    batch["sheets"] = [
        row_with_json(sheet, "columns_json", "sample_rows_json", "metadata")
        for sheet in conn.execute("SELECT * FROM import_sheets WHERE batch_id=? ORDER BY sheet_index", (batch_id,)).fetchall()
    ]
    batch["recent_rows"] = [
        row_with_json(import_row, "raw_json", "normalized_json", "metadata")
        for import_row in conn.execute(
            "SELECT * FROM import_rows WHERE batch_id=? ORDER BY sheet_name, row_number LIMIT 25",
            (batch_id,),
        ).fetchall()
    ]
    batch["portfolio_trades"] = [
        row_with_json(trade, "raw_fields", "metadata")
        for trade in conn.execute("SELECT * FROM portfolio_trades WHERE batch_id=? ORDER BY symbol, created_at", (batch_id,)).fetchall()
    ]
    batch["risk_reward_setups"] = [
        row_with_json(setup, "raw_fields", "metadata")
        for setup in conn.execute("SELECT * FROM risk_reward_setups WHERE batch_id=? ORDER BY calc_type, symbol", (batch_id,)).fetchall()
    ]
    batch["watchlists"] = [
        row_with_json(watchlist, "metadata")
        for watchlist in conn.execute("SELECT * FROM watchlists WHERE batch_id=? ORDER BY strategy_name", (batch_id,)).fetchall()
    ]
    batch["watchlist_items"] = [
        row_with_json(item, "raw_fields", "metadata")
        for item in conn.execute("SELECT * FROM watchlist_items WHERE batch_id=? ORDER BY sheet_id, row_number LIMIT 100", (batch_id,)).fetchall()
    ]
    batch["device_log_catalog"] = [
        row_with_json(item, "metadata")
        for item in conn.execute("SELECT * FROM device_log_catalog WHERE batch_id=? ORDER BY sheet_index", (batch_id,)).fetchall()
    ]
    return batch


def import_plane_summary(conn) -> dict:
    one = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
    batches = one("SELECT COUNT(*) FROM import_batches")
    raw_rows = one("SELECT COUNT(*) FROM import_rows")
    trades = one("SELECT COUNT(*) FROM portfolio_trades")
    setups = one("SELECT COUNT(*) FROM risk_reward_setups")
    watchlists = one("SELECT COUNT(*) FROM watchlists")
    watchlist_items = one("SELECT COUNT(*) FROM watchlist_items")
    device_planes = one("SELECT COUNT(*) FROM device_log_catalog")
    partial_batches = one("SELECT COUNT(*) FROM import_batches WHERE status='partial'")
    recent_batches = [
        row_with_json(row, "metadata")
        for row in conn.execute(
            "SELECT * FROM import_batches ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
    ]
    source_breakdown = [
        {
            "label": "Portfolio Trades",
            "count": trades,
            "detail": "Investment accounting ledger rows normalized into dedicated trade records.",
        },
        {
            "label": "Risk/Reward Setups",
            "count": setups,
            "detail": "Stop-loss and reward calculator rows captured as structured setups.",
        },
        {
            "label": "Watchlist Items",
            "count": watchlist_items,
            "detail": f"{watchlists} strategy sheets converted into watchlist systems and items.",
        },
        {
            "label": "Device Log Planes",
            "count": device_planes,
            "detail": "Libre parser workbook imported at sheet-manifest level for later row decoding.",
        },
    ]
    return {
        "batches": batches,
        "raw_rows": raw_rows,
        "portfolio_trades": trades,
        "risk_reward_setups": setups,
        "watchlists": watchlists,
        "watchlist_items": watchlist_items,
        "device_log_planes": device_planes,
        "partial_batches": partial_batches,
        "recent_batches": recent_batches,
        "sources": source_breakdown,
    }


def import_investment_accounting(conn, batch_id: str, workbook: dict) -> dict:
    projected = 0
    raw_rows = 0
    for sheet in workbook["sheets"]:
        rows = sheet.get("rows") or []
        if not rows:
            continue
        header_index = 0
        headers, mapped_rows = map_rows_from_header(rows, header_index)
        sheet_id = insert_import_sheet(
            conn,
            batch_id,
            sheet["sheet_index"],
            sheet["sheet_name"],
            sheet["source_ref"],
            "imported",
            header_row=rows[header_index]["row_number"],
            nonempty_rows=len(rows),
            projected_rows=len(mapped_rows),
            columns=headers,
            sample_rows=sheet_sample_rows(rows),
        )
        for item in mapped_rows:
            row = item["data"]
            symbol = map_field(row, "name")
            if not symbol:
                continue
            raw_rows += 1
            normalized = {
                "symbol": symbol.upper(),
                "avg_price": to_float(map_field(row, "avg_price")),
                "invested_amount": to_float(map_field(row, "invesment", "_invesment", "investment")),
                "shares": to_float(map_field(row, "shares")),
                "sell_price": to_float(map_field(row, "sell_price")),
                "returns_amount": to_float(map_field(row, "returns")),
                "pnl_per_share": to_float(map_field(row, "p_l_per_share")),
                "pct_change": to_float(map_field(row, "chg", "_chg", "pct_chg")),
                "volume_text": map_field(row, "vol"),
                "trade_date_text": excel_serial_to_iso(map_field(row, "date")) or map_field(row, "date"),
                "hold_period_days": to_int(map_field(row, "hold_period")),
                "account": map_field(row, "account"),
            }
            row_id = insert_import_row(conn, batch_id, sheet_id, sheet["sheet_name"], item["row_number"], "data", "portfolio_trade", "Investing", symbol.upper(), "imported", row, normalized)
            conn.execute(
                """
                INSERT INTO portfolio_trades (
                    id, batch_id, sheet_id, source_row_id, created_at, symbol, avg_price, invested_amount,
                    shares, sell_price, returns_amount, pnl_per_share, pct_change, volume_text,
                    trade_date_text, hold_period_days, account, raw_fields, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    make_id("TRD"),
                    batch_id,
                    sheet_id,
                    row_id,
                    now_iso(),
                    normalized["symbol"],
                    normalized["avg_price"],
                    normalized["invested_amount"],
                    normalized["shares"],
                    normalized["sell_price"],
                    normalized["returns_amount"],
                    normalized["pnl_per_share"],
                    normalized["pct_change"],
                    normalized["volume_text"],
                    normalized["trade_date_text"],
                    normalized["hold_period_days"],
                    normalized["account"],
                    json.dumps(row, ensure_ascii=False),
                    json.dumps({"source_file": "Investment Accounting.xlsx"}, ensure_ascii=False),
                ),
            )
            projected += 1
    return {"raw_rows": raw_rows, "projected": projected}


def import_risk_reward(conn, batch_id: str, workbook: dict) -> dict:
    projected = 0
    raw_rows = 0
    for sheet in workbook["sheets"]:
        rows = sheet.get("rows") or []
        sheet_id = insert_import_sheet(
            conn,
            batch_id,
            sheet["sheet_index"],
            sheet["sheet_name"],
            sheet["source_ref"],
            "imported",
            header_row=None,
            nonempty_rows=len(rows),
            projected_rows=0,
            columns=[],
            sample_rows=sheet_sample_rows(rows),
        )
        current_mode = ""
        current_headers = []
        for idx, row in enumerate(rows):
            values = row.get("values") or []
            lead = clean_text(values[0] if values else "")
            if "stop loss calculator" in lead.lower():
                current_mode = "stop_loss"
                current_headers = []
                continue
            if "reward calculator" in lead.lower():
                current_mode = "reward"
                current_headers = []
                continue
            nonempty = row_nonempty(values)
            if not nonempty:
                continue
            header_blob = " ".join(nonempty).lower()
            if "avg price" in header_blob and "shares" in header_blob:
                seen = set()
                current_headers = [clean_header_name(value, col_idx, seen) for col_idx, value in enumerate(values)]
                conn.execute(
                    "UPDATE import_sheets SET header_row=?, columns_json=? WHERE id=?",
                    (row["row_number"], json.dumps(current_headers, ensure_ascii=False), sheet_id),
                )
                continue
            if not current_mode or not current_headers:
                continue
            row_map = {current_headers[col_idx]: clean_text(values[col_idx]) for col_idx in range(min(len(current_headers), len(values))) if clean_text(values[col_idx])}
            symbol = map_field(row_map, "name")
            if not symbol:
                continue
            raw_rows += 1
            normalized = {
                "calc_type": current_mode,
                "symbol": symbol.upper(),
                "avg_price": to_float(map_field(row_map, "avg_price")),
                "shares": to_float(map_field(row_map, "shares")),
                "invested_amount": to_float(map_field(row_map, "invesment", "_invesment", "investment")),
                "trigger_price": to_float(map_field(row_map, "stop_price", "sell_price")),
                "returns_amount": to_float(map_field(row_map, "returns")),
                "pnl_per_share": to_float(map_field(row_map, "p_l_per_share")),
                "pct_change": to_float(map_field(row_map, "chg", "_chg", "pct_chg")),
            }
            row_id = insert_import_row(conn, batch_id, sheet_id, sheet["sheet_name"], row["row_number"], "data", "risk_reward_setup", "Investing", symbol.upper(), "imported", row_map, normalized, {"calc_type": current_mode})
            conn.execute(
                """
                INSERT INTO risk_reward_setups (
                    id, batch_id, sheet_id, source_row_id, created_at, calc_type, symbol, avg_price,
                    shares, invested_amount, trigger_price, returns_amount, pnl_per_share, pct_change,
                    raw_fields, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    make_id("RRS"),
                    batch_id,
                    sheet_id,
                    row_id,
                    now_iso(),
                    normalized["calc_type"],
                    normalized["symbol"],
                    normalized["avg_price"],
                    normalized["shares"],
                    normalized["invested_amount"],
                    normalized["trigger_price"],
                    normalized["returns_amount"],
                    normalized["pnl_per_share"],
                    normalized["pct_change"],
                    json.dumps(row_map, ensure_ascii=False),
                    json.dumps({"source_file": "RiskRewardCalculator.xlsx"}, ensure_ascii=False),
                ),
            )
            projected += 1
        conn.execute("UPDATE import_sheets SET projected_rows=? WHERE id=?", (projected, sheet_id))
    return {"raw_rows": raw_rows, "projected": projected}


def import_watchlists(conn, batch_id: str, workbook: dict) -> dict:
    projected = 0
    raw_rows = 0
    for sheet in workbook["sheets"]:
        rows = sheet.get("rows") or []
        header_index = sheet_header_guess(rows)
        headers, mapped_rows = map_rows_from_header(rows, header_index)
        notes = []
        if header_index > 0:
            notes = dedupe_strings(value for row in rows[:header_index] for value in (row.get("values") or []))
        sheet_id = insert_import_sheet(
            conn,
            batch_id,
            sheet["sheet_index"],
            sheet["sheet_name"],
            sheet["source_ref"],
            "imported",
            header_row=rows[header_index]["row_number"] if rows else None,
            nonempty_rows=len(rows),
            projected_rows=0,
            columns=headers,
            sample_rows=sheet_sample_rows(rows),
            notes=" | ".join(notes[:2]),
        )
        watchlist_id = make_id("WL")
        conn.execute(
            """
            INSERT INTO watchlists (id, batch_id, sheet_id, created_at, strategy_name, header_row, item_count, notes, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                watchlist_id,
                batch_id,
                sheet_id,
                now_iso(),
                sheet["sheet_name"],
                rows[header_index]["row_number"] if rows else None,
                0,
                " | ".join(notes[:4]),
                json.dumps({"source_file": "STOCK Watchlists analyst Table.xlsx"}, ensure_ascii=False),
            ),
        )
        item_rows = []
        for item in mapped_rows:
            row = item["data"]
            if len(row) < 2:
                continue
            display_name = first_present(row, "ticker", "name", "stocks", "stock", "sector")
            if not display_name or display_name.lower() in {"sector", "name", "stocks"}:
                continue
            ticker = first_present(row, "ticker")
            if not ticker and display_name.isupper() and 1 <= len(display_name) <= 6:
                ticker = display_name
            normalized = {
                "display_name": display_name,
                "ticker": ticker.upper() if ticker else "",
                "sector": first_present(row, "sector"),
                "industry": first_present(row, "industry"),
                "catalyst": first_present(row, "catalyst"),
                "note": first_present(row, "note"),
                "price": to_float(first_present(row, "price", "current_price", "market_price_dynamic_data", "market_price")),
                "peak_52w": to_float(first_present(row, "price_at_peak_52_wks_hgh", "52_weeks_peak", "recent_high")),
                "target_price": to_float(first_present(row, "sell_price", "gross_returns")),
                "support_price": to_float(first_present(row, "current_sup_2nd_buy", "low_sup_buy", "1_sup")),
                "resistance_1": to_float(first_present(row, "1st_res", "current_res")),
                "resistance_2": to_float(first_present(row, "2nd_res", "high_res")),
                "return_potential": to_float(first_present(row, "expected_returns_per_share", "return", "price_chg", "price_chg")),
            }
            entity = normalized["ticker"] or normalized["display_name"]
            row_id = insert_import_row(conn, batch_id, sheet_id, sheet["sheet_name"], item["row_number"], "data", "watchlist_item", "Investing", entity, "imported", row, normalized)
            conn.execute(
                """
                INSERT INTO watchlist_items (
                    id, watchlist_id, batch_id, sheet_id, source_row_id, created_at, row_number, display_name,
                    ticker, sector, industry, catalyst, note, price, peak_52w, target_price, support_price,
                    resistance_1, resistance_2, return_potential, raw_fields, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    make_id("WLI"),
                    watchlist_id,
                    batch_id,
                    sheet_id,
                    row_id,
                    now_iso(),
                    item["row_number"],
                    normalized["display_name"],
                    normalized["ticker"],
                    normalized["sector"],
                    normalized["industry"],
                    normalized["catalyst"],
                    normalized["note"],
                    normalized["price"],
                    normalized["peak_52w"],
                    normalized["target_price"],
                    normalized["support_price"],
                    normalized["resistance_1"],
                    normalized["resistance_2"],
                    normalized["return_potential"],
                    json.dumps(row, ensure_ascii=False),
                    json.dumps({"strategy": sheet["sheet_name"]}, ensure_ascii=False),
                ),
            )
            item_rows.append(item)
            raw_rows += 1
            projected += 1
        conn.execute(
            "UPDATE watchlists SET item_count=? WHERE id=?",
            (
                len(item_rows),
                watchlist_id,
            ),
        )
        conn.execute("UPDATE import_sheets SET projected_rows=? WHERE id=?", (len(item_rows), sheet_id))
    return {"raw_rows": raw_rows, "projected": projected}


def import_xlsb_catalog(conn, batch_id: str, manifest: dict) -> dict:
    projected = 0
    for sheet in manifest["sheets"]:
        sheet_id = insert_import_sheet(
            conn,
            batch_id,
            sheet["sheet_index"],
            sheet["sheet_name"],
            sheet["source_ref"],
            "manifest_only",
            header_row=None,
            nonempty_rows=0,
            projected_rows=0,
            columns=[],
            sample_rows=[],
            notes="Row-level parsing requires a dedicated .xlsb reader package.",
            metadata={"size_bytes": sheet["size_bytes"]},
        )
        conn.execute(
            """
            INSERT INTO device_log_catalog (
                id, batch_id, sheet_id, created_at, workbook_title, sheet_name, sheet_index,
                size_bytes, parser_status, notes, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                make_id("DLC"),
                batch_id,
                sheet_id,
                now_iso(),
                manifest["workbook_title"],
                sheet["sheet_name"],
                sheet["sheet_index"],
                sheet["size_bytes"],
                "manifest_only",
                "Workbook structure imported. Install a .xlsb reader for row-level decoding.",
                json.dumps(manifest.get("metadata") or {}, ensure_ascii=False),
            ),
        )
        projected += 1
    return {"raw_rows": 0, "projected": projected}


def import_workbook_path(source_path: str) -> dict:
    path = Path(source_path).expanduser()
    if not path.exists():
        raise ValueError(f"file not found: {path}")
    ext = path.suffix.lower()
    if ext not in {".xlsx", ".xlsb"}:
        raise ValueError(f"unsupported workbook type: {ext}")
    signature = path_signature(path)
    with connect() as conn:
        existing = conn.execute("SELECT id FROM import_batches WHERE source_signature=?", (signature,)).fetchone()
        if existing:
            batch = load_import_batch(conn, existing["id"])
            batch["duplicate"] = True
            batch["message"] = "Workbook already imported for this exact file state."
            return batch
        batch_id = make_id("IBAT")
        parser_name = "xlsx-native" if ext == ".xlsx" else "xlsb-manifest"
        status = "imported"
        notes = ""
        row_count = 0
        projected_count = 0
        conn.execute(
            """
            INSERT INTO import_batches (
                id, created_at, updated_at, source_path, file_name, file_ext, source_signature,
                import_kind, parser_name, status, sheet_count, row_count, projected_count, notes, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                now_iso(),
                now_iso(),
                str(path),
                path.name,
                ext,
                signature,
                "workbook",
                parser_name,
                status,
                0,
                0,
                0,
                "",
                json.dumps({"capabilities": workbook_import_capabilities()}, ensure_ascii=False),
            ),
        )
        if ext == ".xlsx":
            workbook = parse_xlsx_workbook(path)
            if "investment accounting" in path.name.lower():
                result = import_investment_accounting(conn, batch_id, workbook)
            elif "riskreward" in path.name.lower():
                result = import_risk_reward(conn, batch_id, workbook)
            else:
                result = import_watchlists(conn, batch_id, workbook)
            sheet_count = len(workbook["sheets"])
            row_count = result["raw_rows"]
            projected_count = result["projected"]
        else:
            manifest = parse_xlsb_manifest(path)
            result = import_xlsb_catalog(conn, batch_id, manifest)
            sheet_count = len(manifest["sheets"])
            row_count = 0
            projected_count = result["projected"]
            status = "partial"
            notes = "Workbook imported as sheet manifest only; row-level binary parsing is not available in this environment."
        conn.execute(
            """
            UPDATE import_batches
            SET updated_at=?, status=?, sheet_count=?, row_count=?, projected_count=?, notes=?
            WHERE id=?
            """,
            (now_iso(), status, sheet_count, row_count, projected_count, notes, batch_id),
        )
        audit(conn, "workbook_import", "import_batch", batch_id, {
            "source_path": str(path),
            "file_ext": ext,
            "status": status,
            "sheet_count": sheet_count,
            "row_count": row_count,
            "projected_count": projected_count,
        })
        conn.commit()
        batch = load_import_batch(conn, batch_id)
        batch["duplicate"] = False
        batch["message"] = "Workbook imported."
        return batch


def list_import_batches(limit: int = 25) -> dict:
    with connect() as conn:
        batches = [
            row_with_json(row, "metadata")
            for row in conn.execute(
                "SELECT * FROM import_batches ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        ]
        return {
            "capabilities": workbook_import_capabilities(),
            "summary": import_plane_summary(conn),
            "batches": batches,
        }


def get_import_batch(batch_id: str) -> dict:
    with connect() as conn:
        return load_import_batch(conn, batch_id)


def refresh_entry_fts(conn, entry: dict) -> None:
    conn.execute("DELETE FROM entries_fts WHERE entry_id = ?", (entry["id"],))
    conn.execute(
        "INSERT INTO entries_fts(entry_id, title, domain, entity, raw_input, signal, interpretation, pattern, lesson, tags_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry["id"], entry.get("title") or "", entry.get("domain") or "", entry.get("entity") or "",
            entry.get("raw_input") or "", entry.get("signal") or "", entry.get("interpretation") or "",
            entry.get("pattern") or "", entry.get("lesson") or "", " ".join(entry.get("tags") or []),
        ),
    )


def detect_domain(raw: str, tags: list[str]) -> str:
    t = normalize_text(raw + " " + " ".join(tags))
    rules = [
        ("Business", r"\bsales?\b|sales pipeline|lead gen|lead generation|outreach|follow[- ]?up|crm|conversion|proposal|deal flow|customer acquisition|marketing funnel|pipeline"),
        ("Network+", r"\bdns\b|tcp|udp|subnet|osi|router|switch|ip address|dhcp|port\b|network\+"),
        ("Investing", r"10-k|10-q|earnings|revenue|margin|inventory|cash flow|valuation|stock|ticker|shareholder|capex|balance sheet"),
        ("Lab", r"lab|operator|robot|teleop|calibration|station|sop|quality|failure mode|data collection|readiness"),
        ("Fitness", r"workout|sets|reps|arm|triceps|biceps|weight|dip|curl|protein|creatine|gym"),
        ("Music", r"song|verse|hook|melody|groove|drum|bass|chord|vocal|rap|sample"),
        ("Career", r"resume|job post|interview|role|hiring|skill|bullet|promotion|career"),
        ("Business", r"customer|sales|product|market|business|pricing|inventory|margin|resale|offer"),
        ("AI Project", r"ai|database|memory|retrieval|context|codify|agent|sqlite|chatgpt|llm|dashboard"),
        ("Personal Finance", r"budget|bill|cashflow|debt|rent|payment|expense|savings"),
        ("Personal Preference", r"\bi like\b|\bi love\b|\bi prefer\b|\bi dislike\b|\bi hate\b|favorite|favourite|grocery|meal|food|apples?|preference"),
    ]
    for domain, pat in rules:
        if re.search(pat, t):
            return domain
    return "Other"


def detect_source_type(raw: str, provided: str = "") -> str:
    value = clean_text(provided)
    if value and value.lower() != "manual":
        return value[:80]
    t = normalize_text(raw)
    if re.search(r"\bi like\b|\bi love\b|\bi prefer\b|\bi dislike\b|\bi hate\b|favorite|favourite", t):
        return "Preference"
    if re.search(r"\b\d+(\.\d+)?\b|measured|measurement|score|reps|lbs|revenue|margin|cash|inventory|weight", t):
        return "Measurement"
    if re.search(r"\?$|question|why does|how do|what is|missed question", t):
        return "Question"
    if re.search(r"article|report|filing|10-k|10-q|document|job post|contract|statement", t):
        return "Document"
    if re.search(r"said|told me|feedback|conversation|meeting|call", t):
        return "Conversation"
    if re.search(r"incident|event|happened|session|workout|market event|lab", t):
        return "Event"
    if re.search(r"idea|build|app|framework|model|business model", t):
        return "Idea"
    if re.search(r"result|outcome|proof|passed|failed|improved|validated", t):
        return "Result"
    return "Observation"


def infer_entity(raw: str, domain: str) -> str:
    if domain == "Personal Preference":
        m = re.search(r"\bi (?:like|love|prefer|dislike|hate)\s+(.+?)(?:[.!?]|$)", raw, re.IGNORECASE)
        if m:
            entity = re.sub(r"^(to|the|a|an)\s+", "", m.group(1).strip(), flags=re.IGNORECASE)
            if entity:
                return entity[:80].title()
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    if lines:
        first = re.sub(r"\s+", " ", lines[0]).strip(" -:.")
        if 3 <= len(first) <= 90:
            return first
    defaults = {
        "Lab": "Lab system", "Investing": "Investment thesis", "Business": "Business signal",
        "Career": "Career signal", "Fitness": "Training signal", "Network+": "Network+ concept",
        "Music": "Music signal", "AI Project": "Info Analyzer OS", "Personal Finance": "Cashflow signal",
        "Personal Preference": "Preference context",
    }
    return defaults.get(domain, "General signal")


def extract_tags(raw: str, domain: str, provided=None) -> list[str]:
    tags = normalize_tags(provided)
    if domain and domain.lower() not in tags:
        tags.insert(0, domain.lower())
    t = normalize_text(raw)
    vocab = [
        "training", "sop", "operator", "quality", "calibration", "failure mode", "dashboard", "metric",
        "revenue", "margin", "inventory", "cash flow", "valuation", "capex", "customer", "pricing",
        "dns", "tcp", "udp", "subnet", "osi", "router", "switch", "dhcp", "security",
        "resume", "interview", "proof", "portfolio", "skill", "network+", "sqlite", "database",
        "memory", "retrieval", "context", "action", "pattern", "risk", "opportunity", "contradiction",
        "music", "groove", "hook", "melody", "drums", "fitness", "protein", "dips", "arms",
    ]
    for word in vocab:
        if word in t and word not in tags:
            tags.append(word)
    return tags[:20]


def classify_signal_role(raw: str, tags: list[str]) -> str:
    t = normalize_text(raw + " " + " ".join(tags))
    if re.search(r"\bi like\b|\bi love\b|\bi prefer\b|\bi dislike\b|\bi hate\b|favorite|favourite", t):
        return "preference"
    if re.search(r"contradict|wrong|weaken|disconfirm|doesn't match|does not match|instead|but ", t):
        return "contradiction"
    if re.search(r"risk|break|problem|bottleneck|failure|stuck|weak|issue|miss|struggle|gap", t):
        return "risk"
    if re.search(r"opportunity|hidden value|undervalued|arbitrage|resale|demand|route value", t):
        return "opportunity"
    if re.search(r"proof|artifact|resume|receipt|evidence|validated|confirmed|result", t):
        return "proof"
    if re.search(r"pattern|repeats|again|recurring|keeps happening|lesson", t):
        return "pattern"
    if re.search(r"watch|monitor|track|threshold|review|check later", t):
        return "watch"
    if re.search(r"definition|framework|reference|quote|concept|principle", t):
        return "reference"
    if len(t) < 25:
        return "archive"
    return "action"


def default_actionability(role: str) -> str:
    return {
        "action": "next",
        "watch": "watch",
        "pattern": "watch",
        "risk": "next",
        "opportunity": "next",
        "contradiction": "review",
        "proof": "proof",
        "preference": "watch",
        "reference": "link_only",
        "archive": "no_action",
    }.get(role, "watch")


def default_card_type(role: str, actionability: str) -> str:
    if actionability == "review":
        return "Review Card"
    return {
        "action": "Action Card",
        "watch": "Watch Card",
        "pattern": "Pattern Card",
        "risk": "Risk Card",
        "opportunity": "Opportunity Card",
        "contradiction": "Contradiction Card",
        "proof": "Proof Card",
        "preference": "Preference Card",
        "reference": "Reference Card",
        "archive": "Archive Card",
    }.get(role, "Watch Card")


def default_pull_trigger_type(role: str, actionability: str) -> str:
    if role == "contradiction":
        return "contradiction"
    if role == "preference":
        return "preference"
    if role == "reference":
        return "reference"
    if role == "pattern":
        return "repetition"
    if actionability == "review":
        return "review_date"
    if actionability in {"now", "next"}:
        return "action"
    return "tag"


def default_relationship_type(role: str) -> str:
    return {
        "contradiction": "contradicts",
        "proof": "validates",
        "pattern": "repeats",
        "reference": "connects",
        "archive": "connects",
    }.get(role, "expands")


def default_pull_trigger(domain: str, entity: str, tags: list[str], role: str, actionability: str) -> str:
    tag_part = ", ".join(tags[:6]) or domain
    if role == "preference":
        return f"Resurface only in relevant planning context for {entity}: food, grocery, meal planning, discount search, routine, or environment decisions."
    if role == "contradiction":
        return f"Resurface when new evidence weakens, reverses, or conflicts with the {entity} thesis."
    if role == "pattern":
        return f"Resurface when the same pattern appears again in {domain} or repeats across domains."
    if actionability in {"now", "next"}:
        return f"Resurface until the returned action is completed with a result: {entity}."
    if actionability == "review":
        return f"Resurface on review date or when {entity}, {domain}, or tags appear: {tag_part}."
    if role == "reference":
        return f"Resurface when a new input needs this reference context: {entity}, {tag_part}."
    return f"Resurface when a new entry matches {domain}, {entity}, or tags: {tag_part}."


def default_trackable_as(domain: str, role: str) -> str:
    if role == "preference":
        return "Preference context"
    if role == "reference":
        return "Context reuse / linked memory"
    if role == "contradiction":
        return "Thesis confidence change"
    if role == "pattern":
        return "Repeat count across entries/domains"
    if role == "proof":
        return "Proof artifact / outcome receipt"
    if role == "watch":
        return "Trigger condition / review date"
    return {
        "Lab": "Process / quality metric",
        "Investing": "Financial metric / thesis trigger",
        "Business": "Customer, margin, or conversion metric",
        "Career": "Proof artifact / role fit signal",
        "Fitness": "Body or performance metric",
        "Network+": "Mock question accuracy / protocol mapping",
        "Music": "Emotional replay trigger / composition ingredient",
        "AI Project": "System behavior / retrieval quality metric",
        "Personal Finance": "Cashflow timing / dollar amount",
        "Personal Preference": "Preference context",
    }.get(domain, "Observable result")


def default_tracking_metric(domain: str, role: str) -> str:
    if role == "preference":
        return "Accepted, ignored, or rejected when resurfaced in relevant context"
    if role == "reference":
        return "Number of useful future links or decisions improved by this reference"
    if role == "pattern":
        return "Number of repeats and domains where it appears"
    if role == "contradiction":
        return "Confidence before/after and evidence that changed it"
    if role == "proof":
        return "Artifact created and result produced"
    return {
        "Lab": "Error rate, usable data hours, cycle time, checklist completion, escalation count",
        "Investing": "Revenue, margin, inventory, cash conversion, guidance, valuation, catalyst timing",
        "Business": "Units sold, conversion rate, margin, customer response, time to sale",
        "Career": "Resume bullet, interview story, skill proof, application response",
        "Fitness": "Weight, arm measurement, reps, load, recovery, weekly volume",
        "Network+": "Mock score, missed concept count, protocol/port recall accuracy",
        "Music": "Replay count, emotional trigger label, ingredient extracted, created loop/demo",
        "AI Project": "Entries saved, relevant pulls, action cards executed, false pulls reduced",
        "Personal Finance": "Amount, due date, cash buffer, payment status",
        "Personal Preference": "Accepted/ignored/rejected preference suggestions by context",
    }.get(domain, "Define metric or observable")


def simple_summary(raw: str) -> str:
    one = re.sub(r"\s+", " ", raw).strip()
    return one[:180] + ("..." if len(one) > 180 else "")


def make_short_title(raw: str, domain: str = "", entity: str = "") -> str:
    """Extract a short title from raw input — first sentence, max 10 words."""
    cleaned = re.sub(r"\s+", " ", raw).strip()
    # Take first sentence (split on sentence-ending punctuation or newline)
    first = re.split(r'(?<=[.!?])\s|\n', cleaned)[0].strip().rstrip(".!?,;:")
    if not first:
        first = cleaned
    # Limit to 10 words
    words = first.split()
    if len(words) > 10:
        first = " ".join(words[:10])
    # Prefix with entity or domain if not already present
    prefix = entity or domain or ""
    if prefix and not re.search(re.escape(prefix), first, re.IGNORECASE):
        title = f"{prefix}: {first}"
    else:
        title = first
    return title[:120]


def impact_metric_for(domain: str, role: str) -> str:
    if domain == "Investing":
        return "Decision clarity improved, portfolio risk reduced, allocation discipline improved, or cash/return impact identified."
    if domain == "Lab":
        return "Usable data quality improved, operator error reduced, cycle time reduced, or SOP compliance improved."
    if domain == "Business":
        return "Revenue opportunity clarified, customer conversion improved, margin improved, or operating risk reduced."
    if domain == "Career":
        return "Proof artifact created, role fit improved, interview readiness improved, or income opportunity increased."
    if domain == "AI Project":
        return "Retrieval quality improved, action cards executed, false pulls reduced, or database usefulness increased."
    if role == "proof":
        return "Proof created and available for reuse in portfolio, resume, memo, or decision record."
    return "Time saved, quality improved, risk reduced, learning accelerated, proof created, or decision clarity improved."


def first_step_for(domain: str, role: str, returned_action: str, tracking_metric: str) -> str:
    action_blob = normalize_text(f"{returned_action} {tracking_metric}")
    if re.search(r"\bsales?\b|pipeline|lead|outreach|crm|conversion|follow[- ]?up|deal", action_blob):
        return "Create one sales pipeline row with Lead, Stage, Next Follow-Up, Reply Rate, Booked Call, Result, and Review Date."
    if re.search(r"checklist|sop|standard operating procedure|onboarding", action_blob):
        return "Create a checklist with Item, Owner, Required Evidence, Pass/Fail, Result, and Review Date."
    if re.search(r"10-k|10-q|filing|annual report|financial statement", action_blob):
        return "Create a one-page intelligence card with official story, 3 numbers, 3 signals, bull case, bear case, and monitor-next metric."
    if domain == "Investing":
        return "Create one ledger row with thesis, allocation rule, tracking metric, review date, and result field."
    if domain == "Lab":
        return "Convert the signal into one checklist item or SOP test and run it on the next relevant session."
    if domain == "AI Project":
        return "Add this as a test entry, run retrieval/contextualization, and record whether the returned action was useful."
    if role == "preference":
        return "Save as preference memory only; do not act until a matching planning context appears."
    if returned_action:
        return returned_action.split(".")[0].strip() + "."
    return f"Define the first observable step and track it with: {tracking_metric}."


def feedback_for(domain: str, role: str, metric: str) -> str:
    if domain == "Investing":
        return "Log action taken, capital allocated or rejected, thesis change, metric value, and next review date."
    if domain == "Lab":
        return "Log before/after error rate, usable output, operator behavior, SOP change, and whether the issue repeated."
    if role == "preference":
        return "Log whether the preference suggestion was accepted, ignored, rejected, or refined in context."
    return f"Log result, proof produced, metric movement, decision changed, and whether to repeat. Metric: {metric}."


def related_query_for(domain: str, entity: str, tags: list[str], role: str) -> str:
    parts = [domain, entity, role] + list(tags[:8])
    clean = [p for p in [normalize_text(x) for x in parts] if p]
    return " OR ".join(dict.fromkeys(clean))


def qa_score_output(out: dict) -> dict:
    scores = {}
    scores["Specificity"] = 9 if len(out.get("first_step", "")) > 30 and out.get("entity") else 7
    scores["Friction Reduction"] = 9 if out.get("first_step") and not out.get("first_step", "").lower().startswith("define") else 8
    scores["Impact Metric"] = 9 if any(w in out.get("impact_metric", "").lower() for w in ["risk", "quality", "time", "revenue", "proof", "decision", "cash", "return"]) else 7
    scores["Trackability"] = 9 if out.get("tracking_metric") and out.get("resurfacing_trigger") else 7
    scores["Context Linkage"] = 9 if " OR " in out.get("related_memory_query", "") or out.get("tags") else 7
    scores["Feedback Capture"] = 9 if any(w in out.get("feedback_to_capture", "").lower() for w in ["log", "result", "proof", "metric", "decision"]) else 7
    return scores


def loop_engineer(payload: dict) -> dict:
    draft = codify_payload(payload)
    out = {
        "title": draft["title"],
        "domain": draft["domain"],
        "source_type": draft["source_type"],
        "entity": draft["entity"],
        "raw_input_summary": simple_summary(draft["raw_input"]),
        "signal": draft["signal"],
        "signal_type": draft["signal_role"],
        "interpretation": draft["interpretation"],
        "pattern": draft["pattern"],
        "returned_action": draft["returned_action"],
        "first_step": clean_text(payload.get("first_step")) or first_step_for(draft["domain"], draft["signal_role"], draft["returned_action"], draft["tracking_metric"]),
        "tracking_metric": draft["tracking_metric"],
        "impact_metric": clean_text(payload.get("impact_metric")) or impact_metric_for(draft["domain"], draft["signal_role"]),
        "resurfacing_trigger": draft["pull_trigger"],
        "feedback_to_capture": clean_text(payload.get("feedback_to_capture")) or feedback_for(draft["domain"], draft["signal_role"], draft["tracking_metric"]),
        "related_memory_query": clean_text(payload.get("related_memory_query")) or related_query_for(draft["domain"], draft["entity"], draft["tags"], draft["signal_role"]),
        "lesson": draft["lesson"],
        "next_step": draft["next_step"],
        "confidence": draft["confidence"],
        "status": draft["status"],
        "tags": draft["tags"],
    }
    trace = []
    final = False
    for i in range(1, 6):
        scores = qa_score_output(out)
        weakest = min(scores, key=scores.get)
        trace.append({"loop": i, "plan": f"Improve {weakest}.", "scores": scores})
        if all(v >= 8 for v in scores.values()):
            final = True
            break
        if weakest == "Specificity":
            out["first_step"] = first_step_for(draft["domain"], draft["signal_role"], draft["returned_action"], draft["tracking_metric"])
        elif weakest == "Impact Metric":
            out["impact_metric"] = impact_metric_for(draft["domain"], draft["signal_role"])
        elif weakest == "Context Linkage":
            out["related_memory_query"] = related_query_for(draft["domain"], draft["entity"], draft["tags"], draft["signal_role"])
        elif weakest == "Feedback Capture":
            out["feedback_to_capture"] = feedback_for(draft["domain"], draft["signal_role"], draft["tracking_metric"])
        elif weakest == "Trackability":
            out["tracking_metric"] = draft["tracking_metric"] or default_tracking_metric(draft["domain"], draft["signal_role"])
            out["resurfacing_trigger"] = draft["pull_trigger"]
        else:
            out["first_step"] = first_step_for(draft["domain"], draft["signal_role"], draft["returned_action"], draft["tracking_metric"])
    scores = qa_score_output(out)
    outcome = "FINAL OUTCOME ACHIEVED" if final and all(v >= 8 for v in scores.values()) else "NEEDS HUMAN REVIEW"
    db_json = {
        **draft,
        "first_step": out["first_step"],
        "impact_metric": out["impact_metric"],
        "feedback_to_capture": out["feedback_to_capture"],
        "related_memory_query": out["related_memory_query"],
        "qa_scores": scores,
        "metadata": {**(draft.get("metadata") or {}), "loop_trace": trace, "loop_outcome": outcome},
    }
    return {**out, "outcome": outcome, "analysis": out, "qa_scores": scores, "loop_trace": trace, "database_json": db_json}


def codify_payload(payload: dict) -> dict:
    raw = clean_text(payload.get("raw_input") or payload.get("raw_text"))
    if not raw:
        raise ValueError("raw_input is required")
    provided_tags = normalize_tags(payload.get("tags"))
    domain = clean_text(payload.get("domain")) or detect_domain(raw, provided_tags)
    if domain not in DOMAINS:
        domain = "Other"
    tags = extract_tags(raw, domain, provided_tags)
    entity = clean_text(payload.get("entity")) or infer_entity(raw, domain)
    role = clean_text(payload.get("signal_role")) or classify_signal_role(raw, tags)
    if role not in SIGNAL_ROLES:
        role = "watch"
    title = clean_text(payload.get("title")) or make_short_title(raw, domain, entity)
    _payload_signal = clean_text(payload.get("signal"))
    _payload_interp = clean_text(payload.get("interpretation"))
    signal = _payload_signal or f"{role.title()} signal in {domain}: {simple_summary(raw)}"
    interpretation = _payload_interp
    pattern = clean_text(payload.get("pattern"))
    returned_action = clean_text(payload.get("returned_action"))
    if not returned_action:
        actions = {
            "action": "Execute the next concrete step and log the result.",
            "watch": "Define the trigger condition and review date; resurface when the condition appears.",
            "pattern": "Add this to the pattern library and watch for repeats across domains.",
            "risk": "Define the failure mode, mitigation step, and metric to watch.",
            "opportunity": "Run the smallest validation test and track the outcome.",
            "contradiction": "Compare against the old thesis and update confidence with evidence.",
            "proof": "Attach or create a proof artifact and connect it to the relevant entry.",
            "preference": "Do not alert now. Resurface only when the active context makes this preference useful.",
            "reference": "Link this as reference context and resurface only when a future input needs it.",
            "archive": "Archive as raw context unless a future trigger makes it actionable.",
        }
        returned_action = actions[role]
    actionability = clean_text(payload.get("actionability")).lower() or default_actionability(role)
    if actionability not in ACTIONABILITY_LEVELS:
        actionability = default_actionability(role)
    card_type = clean_text(payload.get("card_type")) or default_card_type(role, actionability)
    if card_type not in CARD_TYPES:
        card_type = default_card_type(role, actionability)
    pull_trigger_type = clean_text(payload.get("pull_trigger_type")).lower() or default_pull_trigger_type(role, actionability)
    if pull_trigger_type not in PULL_TRIGGER_TYPES:
        pull_trigger_type = default_pull_trigger_type(role, actionability)
    relationship_type = clean_text(payload.get("relationship_type")).lower() or default_relationship_type(role)
    if relationship_type not in REL_TYPES:
        relationship_type = default_relationship_type(role)
    trackable_as = clean_text(payload.get("trackable_as")) or default_trackable_as(domain, role)
    tracking_metric = clean_text(payload.get("tracking_metric")) or default_tracking_metric(domain, role)
    lesson = clean_text(payload.get("lesson"))
    _incoming_status = clean_text(payload.get("status")).lower()
    if not _incoming_status:
        if role == "archive":
            _incoming_status = "archived"
        elif _payload_signal or _payload_interp:
            _incoming_status = "needs_enrichment"
        else:
            _incoming_status = "pending_claude"
    status = _incoming_status if _incoming_status in STATUS_VALUES else "pending_claude"
    action_status = clean_text(payload.get("action_status")).lower() or ("cancelled" if role == "archive" else "open")
    if action_status not in ACTION_STATUSES:
        action_status = "open"
    return {
        "id": clean_text(payload.get("id")) or make_id("IA"),
        "date": clean_text(payload.get("date")) or today_iso(),
        "title": title[:240],
        "domain": domain,
        "entity": entity[:180],
        "source_type": detect_source_type(raw, clean_text(payload.get("source_type")) or clean_text(payload.get("source"))),
        "raw_input": raw,
        "signal": signal,
        "interpretation": interpretation,
        "signal_role": role,
        "actionability": actionability,
        "pull_trigger_type": pull_trigger_type,
        "pull_trigger": clean_text(payload.get("pull_trigger")) or default_pull_trigger(domain, entity, tags, role, actionability),
        "relationship_type": relationship_type,
        "card_type": card_type,
        "result_to_track": clean_text(payload.get("result_to_track")) or tracking_metric,
        "first_step": clean_text(payload.get("first_step")),
        "impact_metric": clean_text(payload.get("impact_metric")),
        "feedback_to_capture": clean_text(payload.get("feedback_to_capture")),
        "related_memory_query": clean_text(payload.get("related_memory_query")),
        "qa_scores": payload.get("qa_scores") if isinstance(payload.get("qa_scores"), dict) else {},
        "raw_staging_status": clean_text(payload.get("raw_staging_status")) or stage_for_status(status),
        "trackable_as": trackable_as,
        "tracking_metric": tracking_metric,
        "baseline": clean_text(payload.get("baseline")),
        "target_threshold": clean_text(payload.get("target_threshold")),
        "trigger_condition": clean_text(payload.get("trigger_condition")) or clean_text(payload.get("pull_trigger")) or default_pull_trigger(domain, entity, tags, role, actionability),
        "review_date": clean_text(payload.get("review_date")),
        "pattern": pattern,
        "returned_action": returned_action,
        "action_status": action_status,
        "result": clean_text(payload.get("result")),
        "lesson": lesson,
        "next_step": clean_text(payload.get("next_step")) or "Save, retrieve related memories, execute/track action, then log result.",
        "confidence": clean_text(payload.get("confidence")) or "Medium",
        "status": status,
        "tags": tags,
        "proof_artifact": clean_text(payload.get("proof_artifact")),
        "parent_entry_id": clean_text(payload.get("parent_entry_id")),
        "supersedes_entry_id": clean_text(payload.get("supersedes_entry_id")),
        "memory_version": int(payload.get("memory_version") or 1),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    return apply_entry_hygiene(out, status)


_AI_TRANSLATE_PROMPT = """You are an intelligence analyst for a personal knowledge database called Info Analyzer OS.

Your job: analyze the raw input below and return a JSON object with structured signal intelligence.

Core law: Non-trackable signal is useless. Every signal must be made trackable and actionable.

Return ONLY valid JSON — no markdown, no explanation. Use empty string "" for fields you cannot determine.

Schema to return:
{
  "title": "short descriptive title (max 12 words)",
  "domain": "one of: Lab | Investing | Business | Career | Fitness | Network+ | Music | AI Project | Personal Finance | Personal Preference | Other",
  "entity": "company, system, person, role, song, protocol, product — or empty",
  "signal_role": "one of: action | watch | pattern | risk | opportunity | contradiction | proof | preference | reference | archive",
  "confidence": "one of: Low | Medium | High",
  "signal": "the single most important takeaway from this input (1-2 sentences)",
  "interpretation": "what this signal means for your decisions or actions (1-2 sentences)",
  "pattern": "recurring principle this may belong to — or empty",
  "lesson": "principle learned from this input — or empty",
  "returned_action": "the single most important concrete next action (1 sentence)",
  "first_step": "the very first executable step to take right now (1 sentence)",
  "trackable_as": "metric, behavior, threshold, proof artifact, or trigger condition that makes this trackable",
  "tracking_metric": "specific observable that proves whether this signal matters",
  "trigger_condition": "when this memory should resurface (e.g. 'when reviewing Q3 results', 'before next gym session')",
  "pull_trigger": "short phrase that makes this memory resurface in search (e.g. 'cashflow drop', 'DNS failure pattern')",
  "impact_metric": "what measurable outcome would change if action is taken — or empty",
  "feedback_to_capture": "what feedback to log after acting — or empty",
  "result_to_track": "what result to record when this entry resolves — or empty",
  "next_step": "what should happen after the first step",
  "tags": ["tag1", "tag2"]
}"""


def ai_translate(payload: dict) -> dict:
    scaffold = codify_payload(payload)
    client = _get_anthropic_client()
    if client is None:
        return {**scaffold, "ai_used": False}
    raw = scaffold["raw_input"]
    hint_lines = [f"Raw input:\n{raw}"]
    if scaffold["domain"] and scaffold["domain"] != "Other":
        hint_lines.append(f"Domain hint: {scaffold['domain']}")
    if scaffold["entity"]:
        hint_lines.append(f"Entity hint: {scaffold['entity']}")
    if scaffold["tags"]:
        hint_lines.append(f"Tags hint: {', '.join(scaffold['tags'])}")
    user_msg = "\n".join(hint_lines)
    try:
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2048,
            messages=[
                {"role": "user", "content": f"{_AI_TRANSLATE_PROMPT}\n\n{user_msg}"}
            ],
        )
        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text.strip())
        ai = json.loads(raw_text)
    except Exception:
        return {**scaffold, "ai_used": False}

    def _pick(key: str, fallback):
        v = ai.get(key)
        return str(v).strip() if v and str(v).strip() else fallback

    def _pick_list(key: str, fallback):
        v = ai.get(key)
        if isinstance(v, list) and v:
            return [str(x).strip().lower() for x in v if str(x).strip()]
        return fallback

    role = _pick("signal_role", scaffold["signal_role"])
    if role not in SIGNAL_ROLES:
        role = scaffold["signal_role"]
    domain = _pick("domain", scaffold["domain"])
    if domain not in DOMAINS:
        domain = scaffold["domain"]
    confidence = _pick("confidence", scaffold["confidence"])
    if confidence not in {"Low", "Medium", "High"}:
        confidence = scaffold["confidence"]
    tags = _pick_list("tags", scaffold["tags"])

    return {
        **scaffold,
        "title": _pick("title", scaffold["title"])[:240],
        "domain": domain,
        "entity": _pick("entity", scaffold["entity"])[:180],
        "signal_role": role,
        "confidence": confidence,
        "signal": _pick("signal", scaffold["signal"]),
        "interpretation": _pick("interpretation", scaffold["interpretation"] or ""),
        "pattern": _pick("pattern", scaffold["pattern"] or ""),
        "lesson": _pick("lesson", scaffold["lesson"] or ""),
        "returned_action": _pick("returned_action", scaffold["returned_action"]),
        "first_step": _pick("first_step", scaffold["first_step"] or ""),
        "trackable_as": _pick("trackable_as", scaffold["trackable_as"]),
        "tracking_metric": _pick("tracking_metric", scaffold["tracking_metric"]),
        "trigger_condition": _pick("trigger_condition", scaffold["trigger_condition"] or ""),
        "pull_trigger": _pick("pull_trigger", scaffold["pull_trigger"] or ""),
        "impact_metric": _pick("impact_metric", scaffold["impact_metric"] or ""),
        "feedback_to_capture": _pick("feedback_to_capture", scaffold["feedback_to_capture"] or ""),
        "result_to_track": _pick("result_to_track", scaffold["result_to_track"] or ""),
        "next_step": _pick("next_step", scaffold["next_step"]),
        "tags": tags,
        "ai_used": True,
    }


def insert_entry(conn, entry: dict) -> dict:
    now = now_iso()
    entry = apply_entry_hygiene(dict(entry), entry.get("status") or "")
    entry = {**entry, "created_at": clean_text(entry.get("created_at")) or now, "updated_at": now}
    values = {
        **entry,
        "tags": json.dumps(entry.get("tags") or [], ensure_ascii=False),
        "metadata": json.dumps(entry.get("metadata") or {}, ensure_ascii=False),
        "qa_scores": json.dumps(entry.get("qa_scores") or {}, ensure_ascii=False),
        "last_resurfaced": entry.get("last_resurfaced") or "",
    }
    # Empty parent/supersedes values should be SQL NULL so FK constraints do not fail.
    if not values.get("parent_entry_id"):
        values["parent_entry_id"] = None
    if not values.get("supersedes_entry_id"):
        values["supersedes_entry_id"] = None
    columns = [
        "id", "created_at", "updated_at", "date", "title", "domain", "entity", "source_type", "raw_input",
        "signal", "interpretation", "signal_role", "actionability", "pull_trigger_type", "pull_trigger",
        "relationship_type", "card_type", "result_to_track", "raw_staging_status",
        "first_step", "impact_metric", "feedback_to_capture", "related_memory_query", "qa_scores",
        "trackable_as", "tracking_metric", "baseline", "target_threshold",
        "trigger_condition", "review_date", "pattern", "returned_action", "action_status", "result", "lesson",
        "next_step", "confidence", "status", "tags", "proof_artifact", "parent_entry_id", "supersedes_entry_id",
        "memory_version", "last_resurfaced", "metadata"
    ]
    conn.execute(
        f"INSERT INTO entries ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})",
        tuple(values.get(c, "") for c in columns),
    )
    refresh_entry_fts(conn, entry)
    audit(conn, "create", "entry", entry["id"], {"title": entry.get("title"), "domain": entry.get("domain")})
    return entry


def update_pattern_stats(conn, entry: dict) -> None:
    pattern = clean_text(entry.get("pattern"))
    if not pattern or entry.get("signal_role") == "archive":
        return
    pattern_id = "PAT-" + uuid.uuid5(uuid.NAMESPACE_URL, pattern.lower()).hex[:16].upper()
    row = conn.execute("SELECT * FROM pattern_stats WHERE pattern = ?", (pattern,)).fetchone()
    now = now_iso()
    if row:
        domains = json_loads(row["domains"], [])
        tags = json_loads(row["tags"], [])
        if entry.get("domain") and entry.get("domain") not in domains:
            domains.append(entry.get("domain"))
        for tag in entry.get("tags") or []:
            if tag not in tags:
                tags.append(tag)
        count = int(row["entry_count"] or 0) + 1
        confidence = "High" if count >= 5 else "Medium" if count >= 2 else "Low"
        conn.execute(
            "UPDATE pattern_stats SET updated_at=?, domains=?, tags=?, entry_count=?, confidence=?, last_entry_id=? WHERE id=?",
            (now, json.dumps(domains), json.dumps(tags[:40]), count, confidence, entry["id"], row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO pattern_stats (id, created_at, updated_at, pattern, domains, tags, entry_count, confidence, last_entry_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pattern_id, now, now, pattern, json.dumps([entry.get("domain")]), json.dumps(entry.get("tags") or []), 1, "Low", entry["id"]),
        )


def upsert_action_for_entry(conn, entry: dict) -> dict | None:
    if entry.get("signal_role") == "archive" or entry.get("action_status") in {"done", "cancelled"}:
        return None
    has_review_date = (
        entry.get("actionability") == "watch"
        and entry.get("review_date")
        and entry.get("returned_action")
    )
    if entry.get("actionability") not in {"now", "next", "review"} and not has_review_date:
        return None
    if not clean_text(entry.get("returned_action")):
        return None
    title = clean_action_title(entry)
    action_id = "ACT-" + uuid.uuid5(uuid.NAMESPACE_URL, entry["id"]).hex[:16].upper()
    now = now_iso()
    payload = {
        "id": action_id,
        "created_at": now,
        "updated_at": now,
        "entry_id": entry["id"],
        "action_title": title[:240],
        "why": entry.get("signal") or "Signal returned an action.",
        "track_metric": entry.get("tracking_metric") or "",
        "due_date": entry.get("review_date") or "",
        "priority": "High" if entry.get("signal_role") in {"risk", "contradiction"} else "Medium",
        "status": entry.get("action_status") or "open",
        "metadata": json.dumps({
            "signal_role": entry.get("signal_role"),
            "actionability": entry.get("actionability"),
            "card_type": entry.get("card_type"),
            "trigger_condition": entry.get("trigger_condition"),
            "result_to_track": entry.get("result_to_track"),
        }, ensure_ascii=False),
    }
    conn.execute(
        """INSERT OR REPLACE INTO actions (id, created_at, updated_at, entry_id, action_title, why, track_metric, due_date, priority, status, metadata)
             VALUES (:id, COALESCE((SELECT created_at FROM actions WHERE id=:id), :created_at), :updated_at, :entry_id, :action_title, :why, :track_metric, :due_date, :priority, :status, :metadata)""",
        payload,
    )
    return {k: (json_loads(v, {}) if k == "metadata" else v) for k, v in payload.items()}


def pull_rule_id(entry_id: str, trigger_type: str, trigger_value: str) -> str:
    return "PULL-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{entry_id}|{trigger_type}|{trigger_value}".lower()).hex[:16].upper()


def create_pull_rules(conn, entry: dict) -> list[dict]:
    now = now_iso()
    candidates = []
    if entry.get("pull_trigger_type") and entry.get("pull_trigger"):
        candidates.append((entry["pull_trigger_type"], normalize_text(entry["pull_trigger"])[:180]))
    if entry.get("actionability") in {"now", "next", "review"} and entry.get("returned_action"):
        candidates.append(("action", normalize_text(entry["returned_action"])[:180]))
    if entry.get("domain"):
        candidates.append(("domain", entry["domain"].lower()))
    if entry.get("entity"):
        candidates.append(("entity", normalize_text(entry["entity"])[:120]))
    for tag in entry.get("tags") or []:
        candidates.append(("tag", tag))
    if entry.get("signal_role"):
        candidates.append(("signal_role", entry["signal_role"]))
    if entry.get("review_date"):
        candidates.append(("review_date", entry["review_date"]))
    saved = []
    for trigger_type, trigger_value in candidates:
        if not trigger_value:
            continue
        rid = pull_rule_id(entry["id"], trigger_type, trigger_value)
        priority = "High" if trigger_type in {"entity", "review_date", "action", "contradiction", "threshold"} or entry.get("signal_role") in {"risk", "contradiction"} else "Medium"
        conn.execute(
            """INSERT OR IGNORE INTO pull_rules (id, created_at, updated_at, entry_id, trigger_type, trigger_value, priority, active, metadata)
                 VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (rid, now, now, entry["id"], trigger_type, trigger_value, priority, json.dumps({"source": "auto", "card_type": entry.get("card_type"), "actionability": entry.get("actionability")}, ensure_ascii=False)),
        )
        saved.append({"id": rid, "entry_id": entry["id"], "trigger_type": trigger_type, "trigger_value": trigger_value, "priority": priority})
    return saved


def q_terms(q: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9+#]{3,}", normalize_text(q))
    stop = {"the", "and", "for", "with", "that", "this", "from", "into", "when", "what", "will", "should", "could", "would", "there", "their", "about"}
    return [w for w in words if w not in stop][:30]


def entry_score(old: dict, ctx: dict) -> tuple[int, list[str], str]:
    score = 0
    reasons = []
    ctx_tags = set(ctx.get("tags") or [])
    old_tags = set(old.get("tags") or [])
    if ctx.get("entry_id") and old.get("id") == ctx.get("entry_id"):
        return 0, [], ""
    if ctx.get("entity") and old.get("entity") and normalize_text(ctx["entity"]) == normalize_text(old["entity"]):
        score += 4; reasons.append("same entity")
    if ctx.get("domain") and old.get("domain") == ctx.get("domain"):
        score += 2; reasons.append("same domain")
    overlap = sorted(ctx_tags & old_tags)
    if overlap:
        add = min(6, 2 * len(overlap))
        score += add; reasons.append("matching tags: " + ", ".join(overlap[:4]))
    terms = set(q_terms(ctx.get("raw_input") or ctx.get("q") or ""))
    hay = normalize_text(" ".join([old.get("title") or "", old.get("raw_input") or "", old.get("signal") or "", old.get("lesson") or ""]))
    term_hits = [w for w in terms if w in hay][:5]
    if term_hits:
        score += min(5, len(term_hits)); reasons.append("keyword overlap: " + ", ".join(term_hits[:4]))
    if old.get("action_status") in {"open", "in_progress", "waiting"} and old.get("returned_action"):
        score += 3; reasons.append("old action still open")
    if old.get("review_date") and old.get("review_date") <= today_iso():
        score += 3; reasons.append("review date due")
    if old.get("signal_role") == ctx.get("signal_role") and old.get("signal_role") not in {"", "archive"}:
        score += 2; reasons.append("same signal role")
    raw = normalize_text(ctx.get("raw_input") or "")
    old_text = normalize_text(" ".join([old.get("signal") or "", old.get("interpretation") or "", old.get("lesson") or ""]))
    contradiction_words = {"but", "however", "contradict", "wrong", "weaken", "disconfirm", "instead", "decline", "failed", "risk"}
    if any(w in raw for w in contradiction_words) and old.get("confidence") in {"High", "Medium"}:
        score += 4; reasons.append("possible contradiction/update")
    if old.get("signal_role") == "archive" and score < 8:
        score -= 3
    relationship = "connects"
    if "possible contradiction/update" in reasons:
        relationship = "contradicts"
    elif ctx.get("signal_role") == "proof":
        relationship = "validates"
    elif ctx.get("signal_role") == "pattern" or "same signal role" in reasons:
        relationship = "expands"
    return score, reasons, relationship


def build_action_card(source: dict, ctx: dict, score: int, reasons: list[str], relationship: str) -> dict:
    action = source.get("returned_action") or "Review this memory and decide whether it should update the current rep."
    track = source.get("tracking_metric") or source.get("trackable_as") or "Define a metric/trigger before treating this as useful."
    card_type = source.get("card_type") or default_card_type(source.get("signal_role") or "watch", source.get("actionability") or "watch")
    return {
        "source_entry_id": source["id"],
        "source_title": source.get("title"),
        "card_type": card_type,
        "actionability": source.get("actionability") or "watch",
        "pull_trigger_type": source.get("pull_trigger_type") or "",
        "pull_trigger": source.get("pull_trigger") or source.get("trigger_condition") or "",
        "why_resurfaced": "; ".join(reasons) or "related memory",
        "relationship_suggestion": relationship,
        "action": action,
        "track": track,
        "decision_update": "validate, weaken, expand, refine, or supersede the older memory based on the new evidence",
        "next_step": source.get("next_step") or "Link this card to the new entry if it changes action or confidence.",
        "score": score,
    }


def get_entry_by_id(conn, entry_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return row_to_entry(row) if row else None


def resurface_context(raw_input: str = "", domain: str = "", entity: str = "", tags=None, signal_role: str = "", triggered_by_entry_id: str = "", save_cards: bool = False) -> dict:
    ctx = {
        "raw_input": clean_text(raw_input),
        "domain": clean_text(domain),
        "entity": clean_text(entity),
        "tags": normalize_tags(tags),
        "signal_role": clean_text(signal_role),
        "entry_id": clean_text(triggered_by_entry_id),
    }
    with connect() as conn:
        candidates = context_candidates_for_entry(conn, ctx, min_score=5, limit=6)
        cards = [c["card"] for c in candidates if c["score"] >= 6][:6]
        if save_cards:
            now = now_iso()
            if triggered_by_entry_id:
                conn.execute(
                    "UPDATE surfaced_cards SET status='archived', updated_at=? WHERE triggered_by_entry_id=? AND status='open'",
                    (now, triggered_by_entry_id),
                )
            for card in cards:
                card_id = "CARD-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{card['source_entry_id']}|{triggered_by_entry_id or raw_input[:80]}|{card['why_resurfaced']}").hex[:16].upper()
                conn.execute(
                    """INSERT OR REPLACE INTO surfaced_cards
                       (id, created_at, updated_at, source_entry_id, triggered_by_entry_id, triggered_by_raw, score, reason, action_card, status)
                       VALUES (?, COALESCE((SELECT created_at FROM surfaced_cards WHERE id=?), ?), ?, ?, ?, ?, ?, ?, ?, 'open')""",
                    (card_id, card_id, now, now, card["source_entry_id"], triggered_by_entry_id or "", raw_input[:1000], card["score"], card["why_resurfaced"], json.dumps(card, ensure_ascii=False)),
                )
                conn.execute(
                    "UPDATE surfaced_cards SET status='archived', updated_at=? WHERE source_entry_id=? AND status='open' AND id != ?",
                    (now, card["source_entry_id"], card_id),
                )
                conn.execute("UPDATE entries SET last_resurfaced=? WHERE id=?", (now, card["source_entry_id"]))
            conn.commit()
    return {
        "cards": cards,
        "stats": {"cards": len(cards), "threshold": 5},
        "principle": "Only resurface memory that can return action, warning, pattern, proof, review, or decision update.",
    }


def context_candidates_for_entry(conn, ctx: dict, min_score: int = 5, limit: int = 6) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM entries
        WHERE status NOT IN ('archived', 'superseded', 'raw', 'pending_claude', 'needs_enrichment')
        ORDER BY updated_at DESC
        LIMIT 2000
        """
    ).fetchall()
    candidates = []
    for row in rows:
        old = row_to_entry(row)
        if ctx.get("entry_id") and old.get("id") == ctx.get("entry_id"):
            continue
        score, reasons, rel = entry_score(old, ctx)
        if score >= min_score:
            candidates.append(
                {
                    "entry": old,
                    "score": score,
                    "reasons": reasons,
                    "relationship": rel,
                    "card": build_action_card(old, ctx, score, reasons, rel),
                }
            )
    candidates.sort(key=lambda c: (-c["score"], c["entry"].get("updated_at", "")))
    deduped = []
    seen = set()
    for c in candidates:
        source_id = c["entry"].get("id")
        if source_id in seen:
            continue
        seen.add(source_id)
        deduped.append(c)
    return deduped[:limit]


def extract_preference_target(text: str) -> str:
    t = normalize_text(text)
    m = re.search(r"\b(?:like|likes|love|loves|prefer|prefers|want|wants|favorite|favourite)\s+(?:an?\s+|the\s+)?([a-z0-9][a-z0-9\s\-]{1,40})", t)
    if not m:
        return ""
    item = clean_text(m.group(1))
    item = re.sub(r"\b(?:and|or|but|because|so|for|to|when|if)\b.*$", "", item).strip()
    if not item:
        return ""
    generic = {
        "it", "its", "them", "they", "their", "theirs", "this", "that", "these", "those",
        "something", "anything", "nothing", "one", "thing", "things", "idea", "problem",
        "context", "stuff", "some", "more", "less", "better", "worse", "good", "bad",
    }
    verbs = {
        "be", "being", "been", "come", "comes", "coming", "go", "goes", "going", "get", "gets", "getting",
        "make", "makes", "making", "do", "does", "doing", "need", "needs", "needing", "want", "wants", "wanting",
        "like", "likes", "liking", "love", "loves", "loving", "prefer", "prefers", "preferring", "think", "thinks",
        "thinking", "say", "says", "saying", "seem", "seems", "seeming", "feel", "feels", "feeling",
    }
    tokens = item.lower().split()
    if not tokens:
        return ""
    if tokens[0] in generic or tokens[0] in verbs or item.lower() in generic:
        return ""
    if len(tokens) > 4 and any(tok in verbs for tok in tokens):
        return ""
    return item


def detect_need_state(text: str) -> str:
    t = normalize_text(text)
    checks = [
        ("hungry", "food"),
        ("hunger", "food"),
        ("meal", "food"),
        ("food", "food"),
        ("thirsty", "drink"),
        ("drink", "drink"),
        ("water", "drink"),
        ("tired", "rest"),
        ("sleepy", "rest"),
        ("rest", "rest"),
        ("need coffee", "coffee"),
        ("want coffee", "coffee"),
        ("need food", "food"),
        ("need drink", "drink"),
    ]
    for needle, label in checks:
        if needle in t:
            return label
    return ""


def synthesize_contextual_action(entry: dict, related_entries: list[dict]) -> str:
    blob = " ".join([
        clean_text(entry.get("raw_input")),
        clean_text(entry.get("signal")),
        clean_text(entry.get("title")),
        clean_text(entry.get("entity")),
    ])
    entry_pref = extract_preference_target(blob)
    related_pref = ""
    related_owner = ""
    for rel in related_entries:
        if clean_text(rel.get("signal_role")) == "preference":
            target = extract_preference_target(" ".join([
                clean_text(rel.get("raw_input")),
                clean_text(rel.get("signal")),
                clean_text(rel.get("title")),
            ]))
            if target:
                related_pref = target
                related_owner = clean_text(rel.get("entity")) or clean_text(rel.get("title")) or "them"
                break
    need_state = detect_need_state(blob)
    owner = clean_text(entry.get("entity")) or related_owner or "them"
    preferred_item = entry_pref or related_pref
    if need_state and preferred_item:
        item = preferred_item.rstrip("s") if preferred_item.endswith("s") and not preferred_item.endswith("ss") else preferred_item
        article = "an" if item[:1].lower() in "aeiou" else "a"
        if need_state == "food":
            return f"Buy {owner} {article} {item}"
        if need_state == "drink":
            return f"Get {owner} {article} {item}"
        return f"Route the preferred {item} to {owner}'s current need"
    if clean_text(entry.get("signal_role")) == "preference" and preferred_item:
        return f"Store {preferred_item} as a preference and resurface it when a matching need appears."
    if clean_text(entry.get("signal_role")) == "watch":
        return "Keep this memory on watch until the matching context appears."
    action = clean_text(entry.get("returned_action"))
    if action and not weak_execution_text(action):
        return action
    return clean_text(entry.get("next_step")) or action or "Use this memory when matching context appears."


CONTEXTUAL_MEMORY_VERSION = 1


def build_contextual_memory_chip(entry: dict, candidates: list[dict]) -> dict:
    related_entries = [c["entry"] for c in candidates]
    capture = simple_summary(entry.get("raw_input") or entry.get("signal") or entry.get("title") or "")
    organize = {
        "domain": entry.get("domain") or "Other",
        "entity": entry.get("entity") or "",
        "signal_role": entry.get("signal_role") or "watch",
        "stage": entry.get("raw_staging_status") or "processed",
        "tags": (entry.get("tags") or [])[:8],
    }
    improve = {
        "summary": clean_text(entry.get("interpretation")) or clean_text(entry.get("signal")) or capture,
        "decision_value": clean_text(entry.get("lesson")) or "Use context to turn this memory into a reusable decision cue.",
    }
    reuse_action = synthesize_contextual_action(entry, related_entries)
    reuse = {
        "action": reuse_action,
        "first_step": clean_text(entry.get("first_step")) or clean_text(entry.get("next_step")) or "Open the memory card and execute the next concrete move.",
        "trigger": clean_text(entry.get("pull_trigger")) or clean_text(entry.get("trigger_condition")) or "Resurface when matching context appears.",
        "state": detect_need_state(" ".join([
            clean_text(entry.get("raw_input")),
            clean_text(entry.get("signal")),
            clean_text(entry.get("title")),
        ])),
        "preference": extract_preference_target(" ".join([
            clean_text(entry.get("raw_input")),
            clean_text(entry.get("signal")),
            clean_text(entry.get("title")),
        ])),
    }
    compound = {
        "related_entry_ids": [c["entry"].get("id") for c in candidates[:4]],
        "related_titles": [c["entry"].get("title") for c in candidates[:4]],
        "relationship_types": [c["relationship"] for c in candidates[:4]],
    }
    if clean_text(entry.get("signal_role")) == "preference":
        context_role = "preference"
    elif reuse["state"]:
        context_role = "state"
    elif clean_text(entry.get("signal_role")) == "action":
        context_role = "action"
    elif clean_text(entry.get("signal_role")) == "pattern":
        context_role = "pattern"
    elif clean_text(entry.get("signal_role")) in {"risk", "contradiction"}:
        context_role = "constraint"
    elif clean_text(entry.get("signal_role")) == "proof":
        context_role = "proof"
    else:
        context_role = "context"
    return {
        "version": CONTEXTUAL_MEMORY_VERSION,
        "context_role": context_role,
        "capture": capture,
        "organize": organize,
        "improve": improve,
        "reuse": reuse,
        "compound": compound,
        "right_context": f"{organize['domain']}::{organize['entity'] or 'unassigned'}::{organize['signal_role']}",
        "synthesized_action": reuse_action,
    }


def ensure_context_relationship(conn, from_id: str, to_id: str, rel_type: str, note: str) -> bool:
    if not from_id or not to_id or from_id == to_id:
        return False
    rel_type = rel_type if rel_type in REL_TYPES else "connects"
    existing = conn.execute(
        """
        SELECT 1 FROM relationships
        WHERE from_entry_id=? AND to_entry_id=? AND relationship_type=? AND COALESCE(note,'')=?
        LIMIT 1
        """,
        (from_id, to_id, rel_type, note),
    ).fetchone()
    if existing:
        return False
    conn.execute(
        "INSERT INTO relationships (id, created_at, from_entry_id, to_entry_id, relationship_type, note, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (make_id("REL"), now_iso(), from_id, to_id, rel_type, note, json.dumps({"kind": "contextual_memory_chip"}, ensure_ascii=False)),
    )
    return True


def contextualize_entry(conn, entry: dict) -> dict:
    ctx = {
        "raw_input": entry.get("raw_input") or "",
        "domain": entry.get("domain") or "",
        "entity": entry.get("entity") or "",
        "tags": entry.get("tags") or [],
        "signal_role": entry.get("signal_role") or "",
        "entry_id": entry.get("id") or "",
    }
    candidates = context_candidates_for_entry(conn, ctx, min_score=5, limit=6)
    chip = build_contextual_memory_chip(entry, candidates)
    metadata = dict(entry.get("metadata") or {})
    changed = metadata.get("contextual_memory") != chip or metadata.get("contextual_memory_version") != CONTEXTUAL_MEMORY_VERSION
    if changed:
        metadata["contextual_memory"] = chip
        metadata["contextual_memory_version"] = CONTEXTUAL_MEMORY_VERSION
        metadata["contextualized_at"] = now_iso()
        conn.execute(
            "UPDATE entries SET metadata=?, memory_version=MAX(COALESCE(memory_version, 1), ? ) WHERE id=?",
            (json.dumps(metadata, ensure_ascii=False), CONTEXTUAL_MEMORY_VERSION + 1, entry["id"]),
        )
        entry = get_entry_by_id(conn, entry["id"]) or entry
    linked = 0
    for candidate in candidates[:4]:
        if ensure_context_relationship(conn, entry["id"], candidate["entry"]["id"], candidate["relationship"], "contextual memory chip"):
            linked += 1
    return {
        "updated": changed,
        "linked": linked,
        "chip": chip,
        "candidates": candidates,
        "entry": entry,
    }


def rebuild_contextual_memory(conn, limit: int | None = None) -> dict:
    rows = conn.execute(
        """
        SELECT * FROM entries
        WHERE status NOT IN ('archived','superseded')
        ORDER BY updated_at DESC
        """
    ).fetchall()
    processed = 0
    updated = 0
    linked = 0
    synthesized_actions = 0
    needs_rewire = 0
    samples = []
    for row in rows[:limit] if limit else rows:
        entry = row_to_entry(row)
        result = contextualize_entry(conn, entry)
        processed += 1
        if result["updated"]:
            updated += 1
        linked += result["linked"]
        if clean_text(result["chip"].get("synthesized_action")):
            synthesized_actions += 1
        if result["chip"].get("context_role") in {"preference", "state"}:
            needs_rewire += 1
        if result["updated"] and len(samples) < 5:
            samples.append({
                "id": entry["id"],
                "title": entry.get("title"),
                "context_role": result["chip"].get("context_role"),
                "synthesized_action": result["chip"].get("synthesized_action"),
            })
    conn.commit()
    return {
        "processed": processed,
        "updated": updated,
        "linked": linked,
        "synthesized_actions": synthesized_actions,
        "needs_rewire": needs_rewire,
        "samples": samples,
        "version": CONTEXTUAL_MEMORY_VERSION,
    }


PULL_STOPWORDS = {
    "match", "matches", "matching", "signal", "signals", "entry", "entries", "note", "notes",
    "memory", "context", "data", "thing", "stuff", "token", "test", "no", "none", "find", "pull",
}


def pama_score(entry: dict, query: str, terms: set[str]) -> tuple[int, list[str]]:
    strong_fields = [
        entry.get("title"), entry.get("domain"), entry.get("entity"), entry.get("source_type"),
        entry.get("signal"), entry.get("signal_role"), entry.get("actionability"), entry.get("pull_trigger"),
        entry.get("pattern"), entry.get("returned_action"), entry.get("lesson"), entry.get("next_step"),
        entry.get("first_step"), entry.get("related_memory_query"), " ".join(entry.get("tags") or []),
    ]
    weak_fields = [
        entry.get("interpretation"), entry.get("trackable_as"), entry.get("tracking_metric"),
        entry.get("impact_metric"), entry.get("feedback_to_capture"), entry.get("result_to_track"),
    ]
    strong_hay = normalize_text(" ".join([x or "" for x in strong_fields]))
    weak_hay = normalize_text(" ".join([x or "" for x in weak_fields]))
    score = 0
    reasons = []
    exact = normalize_text(query)
    strong_hits = [t for t in terms if t and t in strong_hay]
    weak_hits = [t for t in terms if t and t in weak_hay]
    if exact and exact in strong_hay:
        score += 10
        reasons.append("exact strong-field match")
    if strong_hits:
        score += min(22, len(strong_hits) * 5)
        reasons.append("strong match: " + ", ".join(strong_hits[:5]))
    if not reasons:
        return 0, []
    if weak_hits:
        score += min(8, len(weak_hits) * 2)
        reasons.append("supporting context: " + ", ".join(weak_hits[:4]))
    if entry.get("actionability") in {"now", "next"}:
        score += 7
        reasons.append("actionable")
    if entry.get("action_status") in {"open", "in_progress", "waiting"}:
        score += 6
        reasons.append("open action")
    if entry.get("signal_role") in {"risk", "contradiction"}:
        score += 5
        reasons.append("risk/contradiction")
    if entry.get("returned_action"):
        score += 5
        reasons.append("has returned action")
    if entry.get("first_step"):
        score += 3
        reasons.append("has first step")
    if entry.get("result") or entry.get("proof_artifact"):
        score += 2
        reasons.append("has feedback/proof")
    return score, reasons


def expand_pull_terms(query: str, tags=None) -> set[str]:
    terms = set(q_terms(query) + normalize_tags(tags))
    q = normalize_text(query)
    synonyms = {
        "sales": ["sale", "sales", "pipeline", "outreach", "follow-up", "followup", "crm"],
        "cashflow": ["cashflow", "cash", "flow", "cash flow", "liquidity", "payment", "income"],
        "cash flow": ["cashflow", "cash", "flow", "cash flow", "liquidity", "payment", "income"],
        "training": ["training", "sop", "operator", "coaching", "onboarding", "checklist"],
        "portfolio": ["portfolio", "allocation", "asset", "holding", "position", "rebalance"],
    }
    for key, vals in synonyms.items():
        if key in q or key in terms:
            terms.update(vals)
    return {t for t in terms if t and len(t) >= 3 and t not in PULL_STOPWORDS}


def clean_action_title(entry: dict) -> str:
    action = clean_text(entry.get("returned_action"))
    weak = {"insight", "insights", "review", "watch", "analyze", "action", "next step"}
    action_norm = normalize_text(action).strip(". ")
    generic_action = re.search(r"compare against the old thesis|save retrieve related memories|review this memory|execute/track action|execute the next concrete step", action_norm)
    if action and action_norm not in weak and len(action) > 8 and not generic_action:
        return action
    entity = clean_text(entry.get("entity")) or clean_text(entry.get("title")) or "this signal"
    signal = clean_text(entry.get("signal"))
    if entry.get("domain") == "Business" or re.search(r"\bsales?\b|pipeline|lead|outreach|crm", normalize_text(entity + " " + signal)):
        return f"Build a trackable sales follow-up loop for {entity}"
    if entry.get("domain") == "Investing":
        return f"Review {entity} economics and update the monitor metric"
    if entry.get("signal_role") == "risk":
        return f"Mitigate risk signal for {entity}"
    return f"Turn {entity} into a tracked action"


def weak_execution_text(value: str) -> bool:
    t = normalize_text(value)
    return (not t) or bool(re.search(r"save retrieve related memories|execute/track action|click track signal|review this memory|log the next action/result", t))


def entry_quality_issues(entry: dict) -> list[str]:
    issues = []
    raw = clean_text(entry.get("raw_input"))
    role = clean_text(entry.get("signal_role")) or "watch"
    domain = clean_text(entry.get("domain")) or "Other"
    signal = clean_text(entry.get("signal"))
    interpretation = clean_text(entry.get("interpretation"))
    default_signal = f"{role.title()} signal in {domain}: {simple_summary(raw)}"
    if not signal:
        issues.append("missing_signal")
    elif normalize_text(signal) == normalize_text(default_signal) or normalize_text(signal).startswith(normalize_text(f"{role.title()} signal in {domain}:")):
        issues.append("generic_signal")
    if not interpretation:
        issues.append("missing_interpretation")
    elif len(interpretation.split()) < 6:
        issues.append("thin_interpretation")
    return issues


def stage_for_status(status: str) -> str:
    if status in {"raw", "pending_claude"}:
        return "queued"
    if status == "needs_enrichment":
        return "partial"
    return "processed"


def apply_entry_hygiene(entry: dict, requested_status: str = "") -> dict:
    requested = clean_text(requested_status or entry.get("status")).lower()
    issues = entry_quality_issues(entry)
    signal = clean_text(entry.get("signal"))
    interpretation = clean_text(entry.get("interpretation"))
    role = clean_text(entry.get("signal_role"))
    metadata = dict(entry.get("metadata") or {})
    terminal = {"validated", "weakened", "upgraded", "superseded", "archived"}
    if role == "archive":
        status = "archived"
    elif requested in {"raw", "pending_claude"}:
        status = requested
    elif requested in terminal:
        status = requested
    elif not signal and not interpretation:
        status = "pending_claude"
    elif issues:
        status = "needs_enrichment"
    elif requested == "watching":
        status = "watching"
    else:
        status = "codified"
    metadata["quality_issues"] = issues
    if issues:
        metadata["needs_enrichment_reason"] = ", ".join(issues)
    else:
        metadata.pop("needs_enrichment_reason", None)
    entry["status"] = status
    entry["raw_staging_status"] = stage_for_status(status)
    entry["metadata"] = metadata
    return entry


def sales_context(entry: dict, query: str = "") -> bool:
    blob = normalize_text(" ".join([
        query,
        entry.get("title") or "",
        entry.get("entity") or "",
        entry.get("signal") or "",
        entry.get("returned_action") or "",
        " ".join(entry.get("tags") or []),
    ]))
    return bool(re.search(r"\bsales?\b|sales pipeline|outreach|follow[- ]?up|crm", blob))


def pama_card(entry: dict, query: str, score: int, reasons: list[str], tier: str) -> dict:
    title = clean_action_title(entry)
    is_sales = sales_context(entry, query)
    first_step = entry.get("first_step") or entry.get("next_step") or ""
    tracking_metric = entry.get("tracking_metric") or entry.get("result_to_track") or ""
    feedback = entry.get("feedback_to_capture") or ""
    if is_sales and weak_execution_text(first_step):
        first_step = "Create one sales pipeline row with Lead, Stage, Next Follow-Up, Reply Rate, Booked Call, Result, and Review Date."
    if is_sales and (weak_execution_text(tracking_metric) or not re.search(r"follow|reply|book|conversion|pipeline|stage|lead|crm|sales", normalize_text(tracking_metric))):
        tracking_metric = "Follow-ups completed, reply rate, booked calls, conversion stage movement, and result logged."
    if is_sales and weak_execution_text(feedback):
        feedback = "Log whether the follow-up was sent, whether the prospect replied, next stage, and what changed in the sales process."
    return {
        "id": "PAMA-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{entry.get('id')}|{query}|{tier}").hex[:12].upper(),
        "entry_id": entry.get("id"),
        "tier": tier,
        "title": title,
        "source": entry.get("title") or entry.get("entity"),
        "domain": "Business" if is_sales else entry.get("domain"),
        "signal": entry.get("signal"),
        "why_it_matters": entry.get("impact_metric") or entry.get("interpretation") or "This memory matched the query and can return a decision or action.",
        "recommended_action": title,
        "first_step": first_step or "Open the source entry and log the next action/result.",
        "tracking_metric": tracking_metric or "Result/proof logged.",
        "resurfacing_trigger": entry.get("pull_trigger") or entry.get("trigger_condition"),
        "feedback_to_capture": feedback or "Log result, proof, decision changed, and whether this should repeat.",
        "score": score,
        "reasons": reasons,
        "buttons": ["abort", "act", "recontextualize"],
    }


def pull_actionable_memory(query: str, domain: str = "", tags=None, limit: int = 30) -> dict:
    q = clean_text(query)
    if not q:
        raise ValueError("query is required")
    terms = expand_pull_terms(q, tags)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM entries
            WHERE status NOT IN ('archived', 'superseded', 'raw', 'pending_claude', 'needs_enrichment')
            ORDER BY updated_at DESC
            LIMIT 2000
            """
        ).fetchall()
        entries = [row_to_entry(r) for r in rows]
    scored = []
    for e in entries:
        if domain and e.get("domain") != domain:
            continue
        score, reasons = pama_score(e, q, terms)
        if score >= 8:
            scored.append((score, reasons, e))
    scored.sort(key=lambda x: (-x[0], x[2].get("updated_at", "")))
    quick = []
    big = []
    seen_cards = set()
    for score, reasons, e in scored[:limit]:
        dedupe_key = "|".join([
            normalize_text(e.get("domain") or ""),
            normalize_text(e.get("entity") or ""),
            normalize_text(e.get("signal") or ""),
            normalize_text(e.get("title") or "")[:100],
        ])
        if dedupe_key in seen_cards:
            continue
        seen_cards.add(dedupe_key)
        is_sales = sales_context(e, q)
        has_execution = bool(e.get("returned_action") and (e.get("first_step") or e.get("next_step")) and (e.get("tracking_metric") or e.get("result_to_track")))
        if is_sales and e.get("returned_action") and (e.get("first_step") or e.get("next_step")):
            has_execution = True
        tier = "quick" if e.get("actionability") in {"now", "next"} and has_execution else "big_picture"
        if is_sales and has_execution:
            tier = "quick"
        if e.get("signal_role") == "pattern":
            tier = "big_picture"
        if e.get("signal_role") in {"risk", "contradiction"} and not has_execution:
            tier = "big_picture"
        card = pama_card(e, q, score, reasons, tier)
        if tier == "quick":
            quick.append(card)
        else:
            big.append(card)
    no_match = None
    if not quick and not big:
        no_match = {
            "message": "No actionable contextual memory matched this query.",
            "suggested_options": [
                "Dump new source info for this topic",
                "Save this query as a watch trigger",
                "Broaden the query with a domain, entity, or action word",
            ],
            "terms_checked": sorted(terms),
        }
    return {
        "query": q,
        "quick_actions": quick[:5],
        "big_picture_actions": big[:5],
        "no_match": no_match,
        "stats": {
            "matches": len(scored),
            "quick_actions": len(quick[:5]),
            "big_picture_actions": len(big[:5]),
            "searched": len(entries),
        },
        "principle": "PAM-A queries contextualized memory only: translated fields, action state, patterns, triggers, metrics, and feedback loops.",
    }


def create_entry(payload: dict) -> dict:
    entry = codify_payload(payload)
    with connect() as conn:
        entry = insert_entry(conn, entry)
        contextual = contextualize_entry(conn, entry)
        entry = contextual.get("entry") or entry
        action = upsert_action_for_entry(conn, entry)
        update_pattern_stats(conn, entry)
        rules = create_pull_rules(conn, entry)
        conn.commit()
    pull = resurface_context(
        raw_input=entry["raw_input"], domain=entry["domain"], entity=entry["entity"], tags=entry["tags"],
        signal_role=entry["signal_role"], triggered_by_entry_id=entry["id"], save_cards=True,
    )
    return {"entry": entry, "action": action, "pull_rules": rules, "context_packet": pull}


def translation_contract(payload: dict) -> dict:
    draft = codify_payload(payload)
    return {
        "draft": draft,
        "contract": {
            "domain": draft["domain"],
            "source_type": draft["source_type"],
            "entity": draft["entity"],
            "signal": draft["signal"],
            "signal_type": draft["signal_role"],
            "trackable_as": draft["trackable_as"],
            "tracking_metric": draft["tracking_metric"],
            "actionability": draft["actionability"],
            "pull_trigger_type": draft["pull_trigger_type"],
            "pull_trigger": draft["pull_trigger"],
            "relationship_type": draft["relationship_type"],
            "card_type": draft["card_type"],
            "result_to_track": draft["result_to_track"],
            "raw_staging_status": draft["raw_staging_status"],
        },
        "principle": "Raw data stays attached as evidence; only processed entries exit staging.",
    }


def get_claude_queue() -> dict:
    """Return all entries that need Claude processing, plus full DB context."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM entries
            WHERE status NOT IN ('archived','superseded')
              AND (
                status IN ('raw','pending_claude','needs_enrichment')
                OR (
                  COALESCE(TRIM(interpretation), '') = ''
                  AND COALESCE(TRIM(signal), '') = ''
                )
              )
            ORDER BY created_at ASC
            """,
        ).fetchall()
        entries = [row_to_entry(r) for r in rows]
        domain_counts = [dict(r) for r in conn.execute(
            "SELECT domain, COUNT(*) AS count FROM entries GROUP BY domain ORDER BY count DESC"
        ).fetchall()]
        role_counts = [dict(r) for r in conn.execute(
            "SELECT signal_role, COUNT(*) AS count FROM entries GROUP BY signal_role ORDER BY count DESC"
        ).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    return {
        "count": len(entries),
        "entries": entries,
        "db_context": {
            "total_entries": total,
            "domains": domain_counts,
            "signal_roles": role_counts,
        },
        "instructions": (
            "Process each entry: generate signal, interpretation, pattern, lesson, "
            "returned_action, first_step, tracking_metric, trackable_as, trigger_condition, "
            "pull_trigger, impact_metric, feedback_to_capture, next_step. "
            "Use cross-entry context (domains, roles, total DB) to make each signal specific. "
            "Then POST all results to /api/translate/batch."
        ),
    }


def decompose_entry(entry_id: str) -> dict:
    """Return an entry with full raw_input + DB context + decompose instructions for Claude."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            raise KeyError(f"entry not found: {entry_id}")
        entry = row_to_entry(row)
        tags = entry.get("tags") or []
        domain = entry.get("domain") or ""
        related: list[dict] = []
        if tags:
            for tag in tags[:3]:
                rs = conn.execute(
                    "SELECT * FROM entries WHERE id != ? AND tags LIKE ? AND status != 'archived' LIMIT 5",
                    (entry_id, f'%"{tag}"%'),
                ).fetchall()
                related.extend(row_to_entry(r) for r in rs)
        if domain:
            ds = conn.execute(
                "SELECT * FROM entries WHERE id != ? AND domain = ? AND status NOT IN ('archived','superseded') LIMIT 5",
                (entry_id, domain),
            ).fetchall()
            related.extend(row_to_entry(r) for r in ds)
        seen: set[str] = set()
        related_unique = []
        for r in related:
            if r["id"] not in seen:
                seen.add(r["id"])
                related_unique.append(r)
        related_unique = related_unique[:10]
        children = [row_to_entry(r) for r in conn.execute(
            "SELECT * FROM entries WHERE parent_entry_id = ?", (entry_id,)
        ).fetchall()]
    word_count = len((entry.get("raw_input") or "").split())
    return {
        "entry": entry,
        "children_already_extracted": children,
        "related_context": related_unique,
        "word_count": word_count,
        "instructions": (
            "Read raw_input carefully. If it contains multiple distinct signals, "
            "decompose it: extract each sub-signal as a separate child entry. "
            "For each child entry set: title, signal, interpretation, pattern, lesson, "
            "returned_action, first_step, tracking_metric, signal_role, domain, entity, tags, "
            "parent_entry_id (set to the parent entry's id), status='codified'. "
            "POST each child to /api/entries. "
            "Then PATCH the parent entry: set status='codified', update title/signal/interpretation "
            "to summarize the overall theme, and set lesson to the unifying principle. "
            "Use related_context to connect signals to existing memory. "
            "Skip children already listed in children_already_extracted."
        ),
    }


def batch_translate(payload: dict) -> dict:
    """Apply Claude-generated translations to multiple entries at once."""
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries must be a non-empty list")
    results = []
    errors = []
    for item in entries:
        entry_id = clean_text(item.get("id"))
        if not entry_id:
            errors.append({"error": "missing id", "item": item})
            continue
        try:
            update = {k: v for k, v in item.items() if k != "id"}
            if "status" not in update or update["status"] not in STATUS_VALUES:
                update["status"] = "codified"
            updated = update_entry(entry_id, update)
            results.append({"id": entry_id, "ok": True, "title": updated.get("title", "")})
        except Exception as e:
            errors.append({"id": entry_id, "error": str(e)})
    return {
        "processed": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }


def fts_query(q: str) -> str:
    terms = q_terms(q)
    if not terms:
        return ""
    return " OR ".join([f'"{t}"' for t in terms[:12]])


def search_entries(params: dict) -> list[dict]:
    q = clean_text((params.get("q") or [""])[0]) if isinstance(params, dict) else ""
    domain = clean_text((params.get("domain") or [""])[0]) if isinstance(params, dict) else ""
    status = clean_text((params.get("status") or [""])[0]).lower() if isinstance(params, dict) else ""
    tag = clean_text((params.get("tag") or [""])[0]).lower() if isinstance(params, dict) else ""
    limit_raw = clean_text((params.get("limit") or ["100"])[0]) if isinstance(params, dict) else "100"
    try:
        limit = max(1, min(500, int(limit_raw)))
    except ValueError:
        limit = 100
    where = []
    args = []
    from_sql = "entries e"
    order_sql = "e.updated_at DESC"
    fq = fts_query(q)
    if fq:
        from_sql = "entries_fts f JOIN entries e ON e.id = f.entry_id"
        where.append("entries_fts MATCH ?")
        args.append(fq)
        order_sql = "bm25(entries_fts), e.updated_at DESC"
    elif q:
        like = f"%{q.lower()}%"
        where.append("(LOWER(e.title) LIKE ? OR LOWER(e.raw_input) LIKE ? OR LOWER(e.signal) LIKE ? OR LOWER(e.lesson) LIKE ? OR LOWER(e.tags) LIKE ?)")
        args += [like, like, like, like, like]
    if domain:
        where.append("e.domain = ?")
        args.append(domain)
    if status:
        where.append("LOWER(e.status) = ?")
        args.append(status)
    if tag:
        where.append("LOWER(e.tags) LIKE ?")
        args.append(f"%{tag}%")
    sql = f"SELECT e.* FROM {from_sql} {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY {order_sql} LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return [row_to_entry(r) for r in conn.execute(sql, args).fetchall()]


def get_entry(entry_id: str) -> dict:
    with connect() as conn:
        entry = get_entry_by_id(conn, entry_id)
        if not entry:
            raise KeyError("entry not found")
        relationships = [dict(r) for r in conn.execute(
            "SELECT * FROM relationships WHERE from_entry_id=? OR to_entry_id=? ORDER BY created_at DESC", (entry_id, entry_id)
        ).fetchall()]
        actions = [row_to_action(r) for r in conn.execute("SELECT * FROM actions WHERE entry_id=? ORDER BY updated_at DESC", (entry_id,)).fetchall()]
        cards = [row_to_card(r) for r in conn.execute("SELECT * FROM surfaced_cards WHERE source_entry_id=? OR triggered_by_entry_id=? ORDER BY updated_at DESC LIMIT 20", (entry_id, entry_id)).fetchall()]
    return {"entry": entry, "relationships": relationships, "actions": actions, "surfaced_cards": cards}


def update_entry(entry_id: str, payload: dict) -> dict:
    allowed = {
        "title", "domain", "entity", "source_type", "signal", "interpretation", "signal_role", "actionability",
        "pull_trigger_type", "pull_trigger", "relationship_type", "card_type", "result_to_track", "raw_staging_status",
        "first_step", "impact_metric", "feedback_to_capture", "related_memory_query",
        "trackable_as", "tracking_metric",
        "baseline", "target_threshold", "trigger_condition", "review_date", "pattern", "returned_action", "action_status", "result",
        "lesson", "next_step", "confidence", "status", "proof_artifact", "parent_entry_id", "supersedes_entry_id", "last_resurfaced"
    }
    updates = {k: payload[k] for k in payload if k in allowed}
    if "tags" in payload:
        updates["tags"] = json.dumps(normalize_tags(payload.get("tags")), ensure_ascii=False)
    if "metadata" in payload and isinstance(payload.get("metadata"), dict):
        updates["metadata"] = json.dumps(payload["metadata"], ensure_ascii=False)
    if "qa_scores" in payload and isinstance(payload.get("qa_scores"), dict):
        updates["qa_scores"] = json.dumps(payload["qa_scores"], ensure_ascii=False)
    if not updates:
        raise ValueError("no updatable fields provided")
    updates["updated_at"] = now_iso()
    with connect() as conn:
        if not get_entry_by_id(conn, entry_id):
            raise KeyError("entry not found")
        set_sql = ", ".join([f"{k}=?" for k in updates])
        conn.execute(f"UPDATE entries SET {set_sql} WHERE id=?", tuple(updates.values()) + (entry_id,))
        entry = get_entry_by_id(conn, entry_id)
        entry = apply_entry_hygiene(entry, payload.get("status") or entry.get("status") or "")
        conn.execute(
            "UPDATE entries SET status=?, raw_staging_status=?, metadata=?, updated_at=? WHERE id=?",
            (entry["status"], entry["raw_staging_status"], json.dumps(entry.get("metadata") or {}, ensure_ascii=False), now_iso(), entry_id),
        )
        entry = get_entry_by_id(conn, entry_id)
        contextual = contextualize_entry(conn, entry)
        entry = contextual.get("entry") or entry
        refresh_entry_fts(conn, entry)
        update_pattern_stats(conn, entry)
        upsert_action_for_entry(conn, entry)
        create_pull_rules(conn, entry)
        audit(conn, "update", "entry", entry_id, {"updated_fields": list(updates.keys())})
        conn.commit()
    return entry


def recategorize_entry(entry_id: str, payload: dict) -> dict:
    instruction = clean_text(
        payload.get("instruction")
        or payload.get("prompt")
        or payload.get("next_use")
        or payload.get("raw_input")
        or payload.get("context")
        or payload.get("use_case")
    )
    if not instruction and (payload.get("domain") or payload.get("entity") or payload.get("tags")):
        instruction = "Reclassify this memory using the supplied domain, entity, and tags."
    if not instruction:
        raise ValueError("recategorize instruction is required")
    with connect() as conn:
        old = get_entry_by_id(conn, entry_id)
        if not old:
            raise KeyError("entry not found")
    translated = codify_payload({
        "raw_input": f"{old.get('raw_input') or ''}\n\nRecategorization instruction: {instruction}",
        "domain": payload.get("domain") or "",
        "entity": payload.get("entity") or old.get("entity") or "",
        "tags": list((old.get("tags") or []) + normalize_tags(payload.get("tags")) + ["recategorized"]),
        "source_type": old.get("source_type") or "",
    })
    metadata = old.get("metadata") or {}
    metadata["last_recategorized_at"] = now_iso()
    metadata["last_recategorize_instruction"] = instruction
    updates = {
        "title": translated["title"],
        "domain": translated["domain"],
        "entity": translated["entity"],
        "source_type": translated["source_type"],
        "signal": translated["signal"],
        "interpretation": translated["interpretation"],
        "signal_role": translated["signal_role"],
        "actionability": translated["actionability"],
        "pull_trigger_type": translated["pull_trigger_type"],
        "pull_trigger": translated["pull_trigger"],
        "relationship_type": translated["relationship_type"],
        "card_type": translated["card_type"],
        "result_to_track": translated["result_to_track"],
        "raw_staging_status": "processed",
        "trackable_as": translated["trackable_as"],
        "tracking_metric": translated["tracking_metric"],
        "trigger_condition": translated["trigger_condition"],
        "pattern": translated["pattern"],
        "returned_action": translated["returned_action"],
        "action_status": translated["action_status"],
        "lesson": translated["lesson"],
        "next_step": translated["next_step"],
        "confidence": translated["confidence"],
        "status": "codified" if translated["status"] == "archived" else translated["status"],
        "tags": translated["tags"],
        "metadata": metadata,
    }
    return update_entry(entry_id, updates)


def delete_entry(entry_id: str) -> dict:
    with connect() as conn:
        entry = get_entry_by_id(conn, entry_id)
        if not entry:
            raise KeyError("entry not found")
        conn.execute("DELETE FROM surfaced_cards WHERE source_entry_id=? OR triggered_by_entry_id=?", (entry_id, entry_id))
        conn.execute("DELETE FROM actions WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM pull_rules WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM relationships WHERE from_entry_id=? OR to_entry_id=?", (entry_id, entry_id))
        conn.execute("DELETE FROM entries_fts WHERE entry_id=?", (entry_id,))
        audit(conn, "delete", "entry", entry_id, {"title": entry.get("title"), "domain": entry.get("domain")})
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        conn.commit()
    return {"deleted": True, "entry_id": entry_id}


def create_relationship(payload: dict) -> dict:
    from_id = clean_text(payload.get("from_entry_id"))
    to_id = clean_text(payload.get("to_entry_id"))
    rel_type = clean_text(payload.get("relationship_type")) or "connects"
    if rel_type not in REL_TYPES:
        rel_type = "connects"
    if not from_id or not to_id:
        raise ValueError("from_entry_id and to_entry_id are required")
    rel_id = clean_text(payload.get("id")) or make_id("REL")
    now = now_iso()
    rel = {
        "id": rel_id, "created_at": now, "from_entry_id": from_id, "to_entry_id": to_id,
        "relationship_type": rel_type, "note": clean_text(payload.get("note")),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    with connect() as conn:
        if not get_entry_by_id(conn, from_id) or not get_entry_by_id(conn, to_id):
            raise KeyError("one or both entries not found")
        conn.execute(
            "INSERT INTO relationships (id, created_at, from_entry_id, to_entry_id, relationship_type, note, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel["id"], rel["created_at"], from_id, to_id, rel_type, rel["note"], json.dumps(rel["metadata"], ensure_ascii=False)),
        )
        audit(conn, "create", "relationship", rel_id, rel)
        conn.commit()
    return rel


def list_actions(params: dict) -> list[dict]:
    status = clean_text((params.get("status") or [""])[0]).lower()
    limit = int(clean_text((params.get("limit") or ["100"])[0]) or 100)
    where = []
    args = []
    if status:
        where.append("status = ?")
        args.append(status)
    where_sql = "WHERE " + " AND ".join([f"a.{w}" if w.startswith("status") else w for w in where]) if where else ""
    sql = f"""
        SELECT a.*, e.title AS source_title, e.domain AS source_domain, e.signal AS source_signal,
               e.card_type AS source_card_type, e.returned_action AS source_returned_action,
               e.result_to_track AS source_result_to_track, e.pull_trigger AS source_pull_trigger
        FROM actions a
        LEFT JOIN entries e ON e.id = a.entry_id
        {where_sql}
        ORDER BY CASE a.priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, a.due_date ASC, a.updated_at DESC
        LIMIT ?
    """
    args.append(max(1, min(500, limit)))
    with connect() as conn:
        out = []
        for r in conn.execute(sql, args).fetchall():
            action = row_to_action(r)
            action["execution_card"] = action_execution_card(action)
            out.append(action)
        return out


def update_action(action_id: str, payload: dict) -> dict:
    allowed = {"action_title", "why", "track_metric", "due_date", "priority", "status", "result", "lesson_update"}
    updates = {k: clean_text(payload[k]) for k in payload if k in allowed}
    if "status" in updates and updates["status"] not in ACTION_STATUSES:
        updates["status"] = "open"
    if not updates:
        raise ValueError("no updatable fields provided")
    updates["updated_at"] = now_iso()
    with connect() as conn:
        row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if not row:
            raise KeyError("action not found")
        if updates.get("status") == "done" and not (updates.get("result") or row["result"]):
            raise ValueError("done actions require a result or proof")
        set_sql = ", ".join([f"{k}=?" for k in updates])
        conn.execute(f"UPDATE actions SET {set_sql} WHERE id=?", tuple(updates.values()) + (action_id,))
        if "status" in updates or "result" in updates:
            conn.execute("UPDATE entries SET action_status=?, result=COALESCE(NULLIF(?, ''), result), updated_at=? WHERE id=?", (updates.get("status", row["status"]), updates.get("result", ""), now_iso(), row["entry_id"]))
        audit(conn, "update", "action", action_id, {"updated_fields": list(updates.keys())})
        conn.commit()
        return row_to_action(conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone())


def get_sales_trends(days: int = 30) -> dict:
    """Return time-series sales data for trend visualization."""
    try:
        with connect() as conn:
            # Get entries from Investing domain with sales data
            rows = conn.execute("""
                SELECT
                    DATE(created_at) as date,
                    AVG(CAST(COALESCE(tracking_metric, '0') AS FLOAT)) as avg_metric,
                    COUNT(*) as signal_count
                FROM entries
                WHERE domain = 'Investing' AND created_at >= datetime('now', ? || ' days')
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                LIMIT ?
            """, (f"-{days}", days)).fetchall()

            trends = [dict(r) for r in rows]
            return {
                "days": days,
                "data_points": len(trends),
                "trends": sorted(trends, key=lambda x: x["date"]),
                "source": "Sales OS - Automated eBay Research"
            }
    except Exception as e:
        return {"error": str(e), "trends": []}


def get_sales_watchlist() -> dict:
    """Return current watchlist items with profit metrics."""
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT
                    id,
                    entity as item,
                    tracking_metric,
                    CAST(COALESCE(baseline, '0') AS FLOAT) as cost,
                    CAST(COALESCE(target_threshold, '0') AS FLOAT) as price,
                    signal,
                    status,
                    updated_at
                FROM entries
                WHERE domain = 'Investing' AND signal_role IN ('opportunity', 'watch', 'action')
                AND status IN ('codified', 'validated', 'upgraded')
                ORDER BY updated_at DESC
                LIMIT 50
            """).fetchall()

            items = []
            for r in rows:
                row_dict = dict(r)
                cost = float(row_dict.get("cost", 0) or 0)
                price = float(row_dict.get("price", 0) or 0)
                margin = price - cost if price > 0 else 0

                items.append({
                    "id": row_dict["id"],
                    "item": row_dict["item"],
                    "status": row_dict["status"],
                    "price": price,
                    "cost": cost,
                    "margin": round(margin, 2),
                    "signal": row_dict["signal"][:60] if row_dict["signal"] else "",
                    "lastUpdated": row_dict["updated_at"]
                })

            return {
                "count": len(items),
                "items": items
            }
    except Exception as e:
        return {"error": str(e), "items": []}


def get_sales_discovery(limit: int = 40) -> dict:
    """Return trending discovered products."""
    try:
        with connect() as conn:
            rows = conn.execute("""
                SELECT
                    entity as product,
                    domain,
                    COUNT(*) as signal_count,
                    MAX(updated_at) as last_signal,
                    GROUP_CONCAT(DISTINCT tags) as tags
                FROM entries
                WHERE status = 'codified' AND signal_role IN ('opportunity', 'pattern')
                GROUP BY entity
                ORDER BY signal_count DESC, last_signal DESC
                LIMIT ?
            """, (limit,)).fetchall()

            products = [dict(r) for r in rows]
            return {
                "trending_count": len(products),
                "products": products,
                "generated_at": now_iso()
            }
    except Exception as e:
        return {"error": str(e), "products": []}


def get_sales_opportunities() -> dict:
    """Return cross-sell and opportunity analysis."""
    try:
        with connect() as conn:
            # Find entries that are opportunities but not yet actioned
            opportunities = conn.execute("""
                SELECT
                    id,
                    title,
                    domain,
                    entity,
                    signal_role,
                    signal,
                    interpretation,
                    status
                FROM entries
                WHERE signal_role = 'opportunity' AND status IN ('codified', 'validated')
                AND returned_action IS NULL OR returned_action = ''
                ORDER BY created_at DESC
                LIMIT 20
            """).fetchall()

            opps = [dict(o) for o in opportunities]
            return {
                "actionable_opportunities": len(opps),
                "opportunities": opps,
                "recommendation": f"Review {len(opps)} opportunity signals for next actions"
            }
    except Exception as e:
        return {"error": str(e), "opportunities": []}


def dashboard() -> dict:
    with connect() as conn:
        one = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
        imports = import_plane_summary(conn)
        domains = [dict(r) for r in conn.execute("SELECT domain, COUNT(*) AS count FROM entries GROUP BY domain ORDER BY count DESC").fetchall()]
        domain_action_load = [dict(r) for r in conn.execute(
            """
            SELECT COALESCE(e.domain, 'Other') AS domain, COUNT(a.id) AS open_actions
            FROM actions a
            LEFT JOIN entries e ON e.id = a.entry_id
            WHERE a.status IN ('open','in_progress','waiting')
            GROUP BY COALESCE(e.domain, 'Other')
            ORDER BY open_actions DESC, domain ASC
            """
        ).fetchall()]
        roles = [dict(r) for r in conn.execute("SELECT signal_role, COUNT(*) AS count FROM entries GROUP BY signal_role ORDER BY count DESC").fetchall()]
        actionability = [dict(r) for r in conn.execute("SELECT actionability, COUNT(*) AS count FROM entries GROUP BY actionability ORDER BY count DESC").fetchall()]
        card_types = [dict(r) for r in conn.execute("SELECT card_type, COUNT(*) AS count FROM entries GROUP BY card_type ORDER BY count DESC").fetchall()]
        recent = [row_to_entry(r) for r in conn.execute("SELECT * FROM entries ORDER BY created_at DESC LIMIT 8").fetchall()]
        actions = [row_to_action(r) for r in conn.execute("SELECT * FROM actions WHERE status IN ('open','in_progress','waiting') ORDER BY updated_at DESC LIMIT 8").fetchall()]
        cards = [row_to_card(r) for r in conn.execute("SELECT * FROM surfaced_cards WHERE status='open' ORDER BY score DESC, updated_at DESC LIMIT 8").fetchall()]
        risk_entries = [row_to_entry(r) for r in conn.execute("SELECT * FROM entries WHERE signal_role IN ('risk','contradiction') AND action_status IN ('open','in_progress','waiting') ORDER BY updated_at DESC LIMIT 6").fetchall()]
        due_reviews = [row_to_entry(r) for r in conn.execute("SELECT * FROM entries WHERE COALESCE(TRIM(review_date), '') != '' AND review_date <= ? AND status NOT IN ('archived','superseded') ORDER BY review_date ASC LIMIT 6", (today_iso(),)).fetchall()]
        total_entries = one("SELECT COUNT(*) FROM entries")
        open_actions = one("SELECT COUNT(*) FROM actions WHERE status IN ('open','in_progress','waiting')")
        completed_actions = one("SELECT COUNT(*) FROM actions WHERE status='done'")
        closed_actions = one("SELECT COUNT(*) FROM actions WHERE status IN ('done','cancelled')")
        total_actions = one("SELECT COUNT(*) FROM actions")
        pattern_count = one("SELECT COUNT(*) FROM pattern_stats")
        surfaced_open = one("SELECT COUNT(*) FROM surfaced_cards WHERE status='open'")
        validated_or_upgraded = one("SELECT COUNT(*) FROM entries WHERE status IN ('validated','upgraded')")
        translated = one("SELECT COUNT(*) FROM entries WHERE raw_staging_status='processed'")
        contextualized = one(
            """
            SELECT COUNT(*) FROM entries
            WHERE COALESCE(metadata, '') LIKE '%"contextual_memory"%'
            """
        )
        contextual_links = one(
            """
            SELECT COUNT(*) FROM relationships
            WHERE COALESCE(metadata, '') LIKE '%"contextual_memory_chip"%'
            """
        )
        result_backlog = one(
            """
            SELECT COUNT(*) FROM actions
            WHERE status IN ('open','in_progress','waiting')
              AND COALESCE(TRIM(result), '') = ''
            """
        )
        weak_translation = one(
            """
            SELECT COUNT(*) FROM entries
            WHERE status != 'archived'
              AND (
                COALESCE(TRIM(actionability), '') = ''
                OR COALESCE(TRIM(card_type), '') = ''
                OR COALESCE(TRIM(pull_trigger_type), '') = ''
                OR COALESCE(TRIM(pull_trigger), '') = ''
                OR COALESCE(TRIM(result_to_track), '') = ''
              )
            """
        )
        stale = one(
            "SELECT COUNT(*) FROM actions WHERE status IN ('open','in_progress','waiting') AND COALESCE(TRIM(due_date), '') != '' AND due_date < ?",
            (today_iso(),),
        )
        claude_queue = one(
            """
            SELECT COUNT(*) FROM entries
            WHERE status NOT IN ('archived','superseded')
              AND (
                status IN ('raw','pending_claude','needs_enrichment')
                OR (
                  COALESCE(TRIM(interpretation), '') = ''
                  AND COALESCE(TRIM(signal), '') = ''
                )
              )
            """
        )
    warnings = []
    cautions = []
    advisories = []
    if weak_translation:
        warnings.append({"level": "warning", "callout": "Weak translation detected", "action": "Recategorize or delete dormant info.", "count": weak_translation})
    if open_actions >= 25:
        warnings.append({"level": "warning", "callout": "Action backlog saturation", "action": "Close, cancel, or extract patterns before creating more work.", "count": open_actions})
    if stale:
        warnings.append({"level": "warning", "callout": "Action overdue", "action": "Abort, recategorize, or close with result.", "count": stale})
    for item in risk_entries[:3]:
        warnings.append({"level": "warning", "callout": item.get("signal") or item.get("title"), "action": item.get("returned_action") or "Review risk signal.", "entry_id": item.get("id")})
    if surfaced_open:
        cautions.append({"level": "caution", "callout": "Memory pull cards open", "action": "Review surfaced context before adding new work.", "count": surfaced_open})
    if surfaced_open >= 40:
        cautions.append({"level": "caution", "callout": "Surfaced card backlog", "action": "Let newer context replace old cards; keep only cards that still change a decision.", "count": surfaced_open})
    if result_backlog >= 10:
        cautions.append({"level": "caution", "callout": "Result backlog", "action": "Log proof on completed work so the loop can learn.", "count": result_backlog})
    for item in due_reviews[:3]:
        cautions.append({"level": "caution", "callout": item.get("title") or item.get("signal"), "action": "Review due signal and update result/trigger.", "entry_id": item.get("id")})
    if claude_queue:
        advisories.append({"level": "advisory", "callout": "Claude processing queue", "action": "Ask Claude Code to run the translation queue to enrich these entries.", "count": claude_queue})
    if not warnings and not cautions:
        advisories.append({"level": "advisory", "callout": "Cockpit quiet", "action": "No high-priority callouts. Continue dumping or executing open actions."})
    advisories.append({"level": "advisory", "callout": "Open action queue", "action": "Execute, recategorize, or abort returned actions.", "count": open_actions})
    summary = {
        "total_entries": total_entries,
        "open_actions": open_actions,
        "completed_actions": completed_actions,
        "closed_actions": closed_actions,
        "completion_rate": round((completed_actions / max(1, completed_actions + open_actions)) * 100, 1),
        "closure_rate": round((closed_actions / max(1, total_actions)) * 100, 1),
        "result_backlog": result_backlog,
        "patterns": pattern_count,
        "surfaced_open": surfaced_open,
        "stale_actions": stale,
        "validated_or_upgraded": validated_or_upgraded,
        "translated_entries": translated,
        "contextualized_entries": contextualized,
        "contextual_links": contextual_links,
        "weak_translation": weak_translation,
        "claude_queue": claude_queue,
        "import_batches": imports["batches"],
        "import_rows": imports["raw_rows"],
        "imported_trades": imports["portfolio_trades"],
        "imported_setups": imports["risk_reward_setups"],
        "imported_watchlists": imports["watchlist_items"],
        "imported_device_planes": imports["device_log_planes"],
    }
    if imports["partial_batches"]:
        advisories.append({
            "level": "advisory",
            "callout": "Manifest-only binary workbook imports",
            "action": "Libre parser workbook structure is stored, but row-level .xlsb decoding still needs a dedicated reader.",
            "count": imports["partial_batches"],
        })
    return {
        **summary,
        "summary": summary,
        "imports": imports,
        "domains": domains,
        "domain_action_load": domain_action_load,
        "signal_roles": roles,
        "actionability": actionability,
        "card_types": card_types,
        "recent": recent,
        "action_queue": actions,
        "surfaced_cards": cards,
        "cockpit": {
            "phase": "Route",
            "warnings": warnings,
            "cautions": cautions,
            "advisories": advisories,
            "checklist": [
                "Clear the bottlenecks blocking value creation first.",
                "Review where money, time, tools, and attention are currently flowing.",
                "Route resources toward the highest-value active system.",
                "Close loops with result or proof so the engine learns.",
                "Promote repeated wins into durable rules, dashboards, or sub-systems.",
            ],
            "go_around": "If the control plane gets noisy, reduce backlog and re-route resources before adding more inputs.",
        },
        "principle": "INNBANK routes money, data, tools, time, and attention toward higher-value outcomes.",
    }


def version_history() -> dict:
    return {
        "current": APP_VERSION,
        "app": "Info Analyzer OS",
        "principle": "The database is not a warehouse. It is a resurfacing engine.",
        "versions": APP_VERSIONS,
    }


def dormant_info_report() -> dict:
    today = today_iso()
    with connect() as conn:
        weak_entries = [row_to_entry(r) for r in conn.execute(
            """
            SELECT * FROM entries
            WHERE status != 'archived'
              AND (
                COALESCE(TRIM(trackable_as), '') = ''
                OR COALESCE(TRIM(tracking_metric), '') = ''
                OR COALESCE(TRIM(returned_action), '') = ''
                OR COALESCE(TRIM(actionability), '') = ''
                OR COALESCE(TRIM(card_type), '') = ''
                OR COALESCE(TRIM(pull_trigger_type), '') = ''
                OR COALESCE(TRIM(pull_trigger), '') = ''
                OR COALESCE(TRIM(result_to_track), '') = ''
                OR (
                  COALESCE(TRIM(trigger_condition), '') = ''
                  AND COALESCE(TRIM(review_date), '') = ''
                )
              )
            ORDER BY updated_at DESC
            LIMIT 25
            """
        ).fetchall()]
        stale_actions = [row_to_action(r) for r in conn.execute(
            """
            SELECT * FROM actions
            WHERE status IN ('open','in_progress','waiting')
              AND COALESCE(TRIM(due_date), '') != ''
              AND due_date < ?
            ORDER BY due_date ASC, updated_at DESC
            LIMIT 25
            """,
            (today,),
        ).fetchall()]
        done_without_result = [row_to_action(r) for r in conn.execute(
            """
            SELECT * FROM actions
            WHERE status='done'
              AND COALESCE(TRIM(result), '') = ''
            ORDER BY updated_at DESC
            LIMIT 25
            """
        ).fetchall()]
        review_due = [row_to_entry(r) for r in conn.execute(
            """
            SELECT * FROM entries
            WHERE TRIM(COALESCE(review_date, '')) != ''
              AND review_date <= ?
              AND status NOT IN ('archived','superseded')
            ORDER BY review_date ASC
            LIMIT 25
            """,
            (today,),
        ).fetchall()]
        open_actions = conn.execute(
            "SELECT COUNT(*) FROM actions WHERE status IN ('open','in_progress','waiting')"
        ).fetchone()[0]
        surfaced_open = conn.execute(
            "SELECT COUNT(*) FROM surfaced_cards WHERE status='open'"
        ).fetchone()[0]
    overload = []
    if open_actions >= 25:
        overload.append({
            "type": "action_backlog",
            "severity": "warning",
            "count": open_actions,
            "recommended_action": "Close, cancel, or extract patterns before creating more actions.",
        })
    if surfaced_open >= 40:
        overload.append({
            "type": "surfaced_backlog",
            "severity": "caution",
            "count": surfaced_open,
            "recommended_action": "Archive or replace stale surfaced cards so the cockpit stays readable.",
        })
    total = len(weak_entries) + len(stale_actions) + len(done_without_result) + len(review_due) + len(overload)
    items = []
    for entry in weak_entries:
        items.append({"type": "weak_entry", "severity": "caution", "entry": entry, "recommended_action": "Recategorize, add metric/trigger, or delete if no future use exists."})
    for action in stale_actions:
        items.append({"type": "stale_action", "severity": "warning", "action": action, "recommended_action": "Close with result, move to waiting, recategorize, or abort."})
    for action in done_without_result:
        items.append({"type": "done_without_result", "severity": "caution", "action": action, "recommended_action": "Add result/proof so the loop can learn."})
    for entry in review_due:
        items.append({"type": "review_due", "severity": "caution", "entry": entry, "recommended_action": "Review the signal and update status, result, or next trigger."})
    items.extend(overload)
    summary = {
        "total": total,
        "weak_entries": len(weak_entries),
        "stale_actions": len(stale_actions),
        "done_without_result": len(done_without_result),
        "review_due": len(review_due),
    }
    return {
        "generated_at": now_iso(),
        "total_dormant_risks": total,
        "summary": summary,
        "items": items[:50],
        "principle": "No info lays dormant. Every signal must become trackable, actionable, or tied to a future trigger.",
        "weak_entries": weak_entries,
        "stale_actions": stale_actions,
        "done_without_result": done_without_result,
        "review_due": review_due,
        "recommended_next_actions": [
            "Convert weak entries into watch/action/pattern/proof signals.",
            "Add a tracking metric, threshold, and review date to any useful but incomplete signal.",
            "Close stale actions with a result, or move them to waiting/cancelled with a reason.",
            "Turn repeated review-due items into pull rules or playbook patterns.",
            "Reduce backlog when the cockpit has too many open actions or surfaced cards.",
        ],
    }


def patterns() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM pattern_stats ORDER BY entry_count DESC, updated_at DESC LIMIT 100").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["domains"] = json_loads(d.get("domains"), [])
        d["tags"] = json_loads(d.get("tags"), [])
        d["metadata"] = json_loads(d.get("metadata"), {})
        out.append(d)
    return out


def pattern_insights() -> list[dict]:
    with connect() as conn:
        top_patterns = [dict(r) for r in conn.execute(
            "SELECT pattern, entry_count, confidence, domains, tags FROM pattern_stats ORDER BY entry_count DESC, updated_at DESC LIMIT 12"
        ).fetchall()]
        domain_actions = [dict(r) for r in conn.execute(
            """
            SELECT e.domain, COUNT(a.id) AS open_actions
            FROM actions a
            JOIN entries e ON e.id = a.entry_id
            WHERE a.status IN ('open','in_progress','waiting')
            GROUP BY e.domain
            ORDER BY open_actions DESC
            LIMIT 8
            """
        ).fetchall()]
        signal_mix = [dict(r) for r in conn.execute(
            "SELECT signal_role, COUNT(*) AS count FROM entries GROUP BY signal_role ORDER BY count DESC"
        ).fetchall()]
        risk_clusters = [row_to_entry(r) for r in conn.execute(
            "SELECT * FROM entries WHERE signal_role IN ('risk','contradiction') ORDER BY updated_at DESC LIMIT 10"
        ).fetchall()]
    insights = []
    for p in top_patterns[:6]:
        domains = json_loads(p.get("domains"), [])
        tags = json_loads(p.get("tags"), [])
        count = int(p.get("entry_count") or 0)
        if count < 2:
            continue
        insights.append({
            "name": p.get("pattern"),
            "type": "Repeated Pattern",
            "why_it_matters": f"This pattern appeared {count} times across {len(domains) or 1} domain(s), which means it is no longer just a note.",
            "evidence": {"reps": count, "domains": domains, "tags": tags[:8], "confidence": p.get("confidence")},
            "action": "Turn this into a reusable playbook, checklist, or rule.",
            "track": "Watch whether future entries validate, weaken, or repeat this pattern.",
        })
    for row in domain_actions[:4]:
        insights.append({
            "name": f"{row.get('domain')} has action backlog",
            "type": "Execution Bottleneck",
            "why_it_matters": "A domain with many open returned actions may be generating more intelligence than execution.",
            "evidence": {"domain": row.get("domain"), "open_actions": row.get("open_actions")},
            "action": "Close, abort, or extract patterns from the oldest returned actions in this domain.",
            "track": "Open actions by domain should decline or convert into proof/results.",
        })
    mix = {r.get("signal_role"): int(r.get("count") or 0) for r in signal_mix}
    risk_total = mix.get("risk", 0) + mix.get("contradiction", 0)
    if risk_total:
        insights.append({
            "name": "Risk and contradiction pressure",
            "type": "Cockpit Warning Pattern",
            "why_it_matters": "Risk and contradiction signals are the system telling you where old assumptions may break.",
            "evidence": {"risk_signals": mix.get("risk", 0), "contradiction_signals": mix.get("contradiction", 0), "recent": [e.get("title") for e in risk_clusters[:3]]},
            "action": "Review the newest risk/contradiction entries and decide whether to weaken, supersede, or convert them into actions.",
            "track": "Count of unresolved risk/contradiction actions.",
        })
    if not insights:
        insights.append({
            "name": "Pattern library is still forming",
            "type": "Advisory",
            "why_it_matters": "The database needs more translated reps before cross-domain patterns become reliable.",
            "evidence": {},
            "action": "Keep saving translated signals with clear result loops.",
            "track": "Pattern count and repeated domains.",
        })
    return insights[:12]


def pattern_card(card_id: str, name: str, pattern_type: str, severity: str, score: int, evidence: dict, action: str, first_step: str, metric: str, trigger: str, related_entries=None) -> dict:
    return {
        "id": card_id,
        "name": name,
        "type": pattern_type,
        "severity": severity,
        "score": score,
        "evidence": evidence,
        "interpretation": evidence.get("interpretation") or "This pattern is strong enough to return as an operational insight.",
        "action": action,
        "first_step": first_step,
        "tracking_metric": metric,
        "resurfacing_trigger": trigger,
        "related_entries": related_entries or [],
    }


def pattern_engine_scan(save: bool = False, scan_type: str = "full") -> dict:
    with connect() as conn:
        entries = [row_to_entry(r) for r in conn.execute("SELECT * FROM entries WHERE status != 'archived' ORDER BY updated_at DESC LIMIT 2000").fetchall()]
        actions = [row_to_action(r) for r in conn.execute("SELECT * FROM actions WHERE status IN ('open','in_progress','waiting') ORDER BY updated_at DESC LIMIT 1000").fetchall()]
        pattern_rows = [dict(r) for r in conn.execute("SELECT * FROM pattern_stats ORDER BY entry_count DESC, updated_at DESC LIMIT 100").fetchall()]
    cards = []
    tag_map: dict[str, list[dict]] = {}
    entity_map: dict[str, list[dict]] = {}
    domain_open_actions: dict[str, int] = {}
    proof_gap = []
    risk_entries = []
    for e in entries:
        for tag in e.get("tags") or []:
            if len(tag) >= 3:
                tag_map.setdefault(tag, []).append(e)
        entity_key = normalize_text(e.get("entity") or "")
        if entity_key:
            entity_map.setdefault(entity_key, []).append(e)
        if e.get("signal_role") in {"risk", "contradiction"}:
            risk_entries.append(e)
        if e.get("actionability") in {"next", "now", "review"} and not (e.get("result") or e.get("proof_artifact")):
            proof_gap.append(e)
    for a in actions:
        domain = ""
        for e in entries:
            if e.get("id") == a.get("entry_id"):
                domain = e.get("domain") or "Other"
                break
        domain_open_actions[domain or "Other"] = domain_open_actions.get(domain or "Other", 0) + 1
    for tag, related in sorted(tag_map.items(), key=lambda kv: len(kv[1]), reverse=True)[:12]:
        domains = sorted({e.get("domain") for e in related if e.get("domain")})
        if len(related) < 3:
            continue
        score = min(100, len(related) * 8 + len(domains) * 6)
        severity = "warning" if score >= 85 else "caution" if score >= 55 else "advisory"
        cards.append(pattern_card(
            "PATTERN-TAG-" + uuid.uuid5(uuid.NAMESPACE_URL, tag).hex[:10].upper(),
            f"Recurring tag: {tag}",
            "Tag Cluster",
            severity,
            score,
            {"count": len(related), "domains": domains, "interpretation": "The same theme is appearing repeatedly across memory."},
            "Convert this recurring theme into a rule, checklist, watch trigger, or playbook.",
            f"Review the newest 3 entries tagged '{tag}' and write the reusable rule.",
            "Future repeats, open actions tied to this tag, and results/proof generated.",
            f"Resurface when new entries include tag '{tag}' or related domains: {', '.join(domains[:4])}.",
            [{"id": e.get("id"), "title": e.get("title"), "domain": e.get("domain")} for e in related[:5]],
        ))
    for entity, related in sorted(entity_map.items(), key=lambda kv: len(kv[1]), reverse=True)[:8]:
        if len(related) < 2:
            continue
        open_count = sum(1 for e in related if e.get("action_status") in {"open", "in_progress", "waiting"})
        if open_count == 0:
            continue
        score = min(100, len(related) * 10 + open_count * 12)
        cards.append(pattern_card(
            "PATTERN-ENTITY-" + uuid.uuid5(uuid.NAMESPACE_URL, entity).hex[:10].upper(),
            f"Entity concentration: {related[0].get('entity')}",
            "Entity Cluster",
            "warning" if score >= 85 else "caution",
            score,
            {"entries": len(related), "open_actions": open_count, "interpretation": "One entity is accumulating memory and unfinished actions."},
            "Decide whether this entity deserves a dedicated watchlist, playbook, or cleanup pass.",
            "Open the entity’s newest entry and either execute, abort, or extract one pattern.",
            "Open actions and completed results for this entity.",
            f"Resurface when new input mentions {related[0].get('entity')}.",
            [{"id": e.get("id"), "title": e.get("title"), "domain": e.get("domain")} for e in related[:5]],
        ))
    for domain, count in sorted(domain_open_actions.items(), key=lambda kv: kv[1], reverse=True)[:8]:
        if count < 5:
            continue
        score = min(100, count * 6)
        cards.append(pattern_card(
            "PATTERN-BACKLOG-" + uuid.uuid5(uuid.NAMESPACE_URL, domain).hex[:10].upper(),
            f"{domain} execution backlog",
            "Action Backlog",
            "warning" if count >= 20 else "caution",
            score,
            {"open_actions": count, "domain": domain, "interpretation": "This domain is producing more returned actions than closed results."},
            "Reduce action load by closing, aborting, or extracting patterns from stale actions.",
            f"Process the oldest 5 open {domain} actions: done, extract pattern, or abort.",
            "Open actions reduced and results/proof logged.",
            f"Resurface during {domain} sessions until open action count drops below 5.",
        ))
    if risk_entries:
        score = min(100, len(risk_entries) * 10)
        cards.append(pattern_card(
            "PATTERN-RISK-" + uuid.uuid5(uuid.NAMESPACE_URL, "risk-cluster").hex[:10].upper(),
            "Risk/contradiction cluster",
            "Risk Cluster",
            "warning" if len(risk_entries) >= 8 else "caution",
            score,
            {"count": len(risk_entries), "interpretation": "Risk and contradiction signals are accumulating and should change confidence or actions."},
            "Review risk entries and decide which old theses should be weakened, superseded, or turned into mitigations.",
            "Open the 3 newest risk/contradiction entries and update confidence/action status.",
            "Number of unresolved risk actions and confidence changes logged.",
            "Resurface when risk or contradiction entries remain open.",
            [{"id": e.get("id"), "title": e.get("title"), "domain": e.get("domain")} for e in risk_entries[:5]],
        ))
    if len(proof_gap) >= 5:
        cards.append(pattern_card(
            "PATTERN-PROOF-" + uuid.uuid5(uuid.NAMESPACE_URL, "proof-gap").hex[:10].upper(),
            "Action-to-proof gap",
            "Feedback Gap",
            "caution",
            min(100, len(proof_gap) * 5),
            {"count": len(proof_gap), "interpretation": "Many actionable entries have no result or proof artifact yet."},
            "Close the loop by logging results or proof artifacts for actionable entries.",
            "Pick 5 actionable entries and add result/proof or abort them.",
            "Percent of actionable entries with result or proof artifact.",
            "Resurface when actionable entries lack result/proof.",
            [{"id": e.get("id"), "title": e.get("title"), "domain": e.get("domain")} for e in proof_gap[:5]],
        ))
    for p in pattern_rows[:8]:
        count = int(p.get("entry_count") or 0)
        if count < 2:
            continue
        domains = json_loads(p.get("domains"), [])
        score = min(100, count * 10 + len(domains) * 5)
        cards.append(pattern_card(
            "PATTERN-STORED-" + uuid.uuid5(uuid.NAMESPACE_URL, p.get("pattern") or "").hex[:10].upper(),
            p.get("pattern") or "Stored pattern",
            "Stored Pattern",
            "warning" if score >= 85 else "caution",
            score,
            {"count": count, "domains": domains, "confidence": p.get("confidence"), "interpretation": "A stored pattern has enough repeats to become doctrine or a checklist."},
            "Promote this stored pattern into a rule, checklist, or command-center watch item.",
            "Write the pattern as one rule and define when it should resurface.",
            "Future validations, contradictions, and actions produced by this pattern.",
            "Resurface when a new entry matches the pattern language or domains.",
        ))
    cards.sort(key=lambda c: (-c["score"], c["name"]))
    warnings = [c for c in cards if c["severity"] == "warning"][:3]
    cautions = [c for c in cards if c["severity"] == "caution"][:5]
    advisories = [c for c in cards if c["severity"] == "advisory"][:5]
    cards = warnings + cautions + advisories
    summary = {
        "cards": len(cards),
        "warnings": sum(1 for c in cards if c["severity"] == "warning"),
        "cautions": sum(1 for c in cards if c["severity"] == "caution"),
        "advisories": sum(1 for c in cards if c["severity"] == "advisory"),
        "entries_scanned": len(entries),
        "actions_scanned": len(actions),
    }
    run = {"id": make_id("PTRUN"), "created_at": now_iso(), "scan_type": scan_type, "summary": summary, "cards": cards}
    if save:
        with connect() as conn:
            conn.execute(
                "INSERT INTO pattern_runs (id, created_at, scan_type, summary, cards, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (run["id"], run["created_at"], scan_type, json.dumps(summary, ensure_ascii=False), json.dumps(cards, ensure_ascii=False), json.dumps({"app_version": APP_VERSION}, ensure_ascii=False)),
            )
            audit(conn, "create", "pattern_run", run["id"], summary)
            conn.commit()
    return run


def export_all() -> dict:
    with connect() as conn:
        return {
            "exported_at": now_iso(),
            "app": f"Info Analyzer OS {APP_VERSION}",
            "entries": [row_to_entry(r) for r in conn.execute("SELECT * FROM entries ORDER BY created_at").fetchall()],
            "relationships": [dict(r) for r in conn.execute("SELECT * FROM relationships ORDER BY created_at").fetchall()],
            "actions": [row_to_action(r) for r in conn.execute("SELECT * FROM actions ORDER BY created_at").fetchall()],
            "patterns": patterns(),
            "pull_rules": [dict(r) for r in conn.execute("SELECT * FROM pull_rules ORDER BY created_at").fetchall()],
            "surfaced_cards": [row_to_card(r) for r in conn.execute("SELECT * FROM surfaced_cards ORDER BY created_at").fetchall()],
            "imports": {
                "summary": import_plane_summary(conn),
                "batches": [row_with_json(r, "metadata") for r in conn.execute("SELECT * FROM import_batches ORDER BY created_at").fetchall()],
                "sheets": [row_with_json(r, "columns_json", "sample_rows_json", "metadata") for r in conn.execute("SELECT * FROM import_sheets ORDER BY created_at").fetchall()],
                "rows": [row_with_json(r, "raw_json", "normalized_json", "metadata") for r in conn.execute("SELECT * FROM import_rows ORDER BY created_at").fetchall()],
                "portfolio_trades": [row_with_json(r, "raw_fields", "metadata") for r in conn.execute("SELECT * FROM portfolio_trades ORDER BY created_at").fetchall()],
                "risk_reward_setups": [row_with_json(r, "raw_fields", "metadata") for r in conn.execute("SELECT * FROM risk_reward_setups ORDER BY created_at").fetchall()],
                "watchlists": [row_with_json(r, "metadata") for r in conn.execute("SELECT * FROM watchlists ORDER BY created_at").fetchall()],
                "watchlist_items": [row_with_json(r, "raw_fields", "metadata") for r in conn.execute("SELECT * FROM watchlist_items ORDER BY created_at").fetchall()],
                "device_log_catalog": [row_with_json(r, "metadata") for r in conn.execute("SELECT * FROM device_log_catalog ORDER BY created_at").fetchall()],
            },
        }


def import_all(payload: dict) -> dict:
    saved = {"entries": 0, "relationships": 0}
    with connect() as conn:
        for item in payload.get("entries") or []:
            try:
                entry = codify_payload(item)
                entry["id"] = item.get("id") or entry["id"]
                if conn.execute("SELECT 1 FROM entries WHERE id=?", (entry["id"],)).fetchone():
                    continue
                insert_entry(conn, entry)
                contextualize_entry(conn, entry)
                upsert_action_for_entry(conn, entry)
                update_pattern_stats(conn, entry)
                create_pull_rules(conn, entry)
                saved["entries"] += 1
            except Exception:
                continue
        for rel in payload.get("relationships") or []:
            try:
                if conn.execute("SELECT 1 FROM relationships WHERE id=?", (rel.get("id"),)).fetchone():
                    continue
                if not conn.execute("SELECT 1 FROM entries WHERE id=?", (rel.get("from_entry_id"),)).fetchone():
                    continue
                if not conn.execute("SELECT 1 FROM entries WHERE id=?", (rel.get("to_entry_id"),)).fetchone():
                    continue
                conn.execute(
                    "INSERT INTO relationships (id, created_at, from_entry_id, to_entry_id, relationship_type, note, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (rel.get("id") or make_id("REL"), rel.get("created_at") or now_iso(), rel.get("from_entry_id"), rel.get("to_entry_id"), rel.get("relationship_type") or "connects", rel.get("note") or "", json.dumps(rel.get("metadata") or {})),
                )
                saved["relationships"] += 1
            except Exception:
                continue
        audit(conn, "import", "database", None, saved)
        conn.commit()
    return saved


class Handler(SimpleHTTPRequestHandler):
    server_version = "InfoAnalyzerOS/0.4"

    def log_message(self, fmt, *args):
        print(f"[{now_iso()}] {self.address_string()} {fmt % args}")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, ctype: str):
        if not path.exists():
            return self.send_json({"error": "file not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception as e:
            raise ValueError(f"invalid JSON: {e}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if path in {"/", "/index.html"}:
                return self.send_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            if path == "/app.js":
                return self.send_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
            if path == "/style.css":
                return self.send_file(WEB_DIR / "style.css", "text/css; charset=utf-8")
            if path == "/api/health":
                return self.send_json({"ok": True, "app": "Info Analyzer OS", "version": APP_VERSION, "db_path": str(DB_PATH)})
            if path == "/api/ai/status":
                key_set = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
                sdk_ok = _anthropic is not None
                return self.send_json({
                    "ai_enabled": key_set and sdk_ok,
                    "sdk_installed": sdk_ok,
                    "key_set": key_set,
                    "model": "claude-opus-4-8" if (key_set and sdk_ok) else None,
                    "hint": None if (key_set and sdk_ok) else (
                        "Run: pip install anthropic" if not sdk_ok
                        else "Set ANTHROPIC_API_KEY environment variable before starting the server"
                    ),
                })
            if path == "/api/versions":
                return self.send_json(version_history())
            if path == "/api/import/capabilities":
                return self.send_json(workbook_import_capabilities())
            if path == "/api/imports":
                limit = int(clean_text((params.get("limit") or ["25"])[0]) or 25)
                return self.send_json(list_import_batches(limit=limit))
            if path.startswith("/api/imports/"):
                return self.send_json(get_import_batch(unquote(path.split("/api/imports/", 1)[1])))
            if path == "/api/codify":
                return self.send_json({"draft": codify_payload({"raw_input": (params.get("raw_input") or params.get("q") or [""])[0], "domain": (params.get("domain") or [""])[0], "tags": (params.get("tags") or [""])[0]})})
            if path == "/api/loop/analyze":
                return self.send_json(loop_engineer({
                    "raw_input": (params.get("raw_input") or params.get("q") or [""])[0],
                    "domain": (params.get("domain") or [""])[0],
                    "tags": (params.get("tags") or [""])[0],
                    "entity": (params.get("entity") or [""])[0],
                }))
            if path == "/api/translation/contract":
                return self.send_json(translation_contract({
                    "raw_input": (params.get("raw_input") or params.get("q") or [""])[0],
                    "domain": (params.get("domain") or [""])[0],
                    "tags": (params.get("tags") or [""])[0],
                    "entity": (params.get("entity") or [""])[0],
                }))
            if path == "/api/entries/queue":
                return self.send_json(get_claude_queue())
            if path == "/api/entries":
                return self.send_json({"entries": search_entries(params)})
            if path.startswith("/api/entries/") and path.endswith("/decompose"):
                entry_id = unquote(path.split("/api/entries/", 1)[1].rsplit("/decompose", 1)[0])
                return self.send_json(decompose_entry(entry_id))
            if path.startswith("/api/entries/"):
                return self.send_json(get_entry(unquote(path.split("/api/entries/", 1)[1])))
            if path == "/api/context" or path == "/api/resurface":
                return self.send_json(resurface_context(
                    raw_input=(params.get("raw_input") or params.get("q") or [""])[0],
                    domain=(params.get("domain") or [""])[0],
                    entity=(params.get("entity") or [""])[0],
                    tags=(params.get("tags") or [""])[0],
                    signal_role=(params.get("signal_role") or [""])[0],
                    save_cards=False,
                ))
            if path == "/api/context/rewire":
                limit = payload.get("limit")
                try:
                    limit = int(limit) if limit not in (None, "", []) else None
                except Exception:
                    limit = None
                with connect() as conn:
                    return self.send_json(rebuild_contextual_memory(conn, limit=limit), 201)
            if path == "/api/pull":
                return self.send_json(pull_actionable_memory(
                    query=(params.get("q") or params.get("query") or [""])[0],
                    domain=(params.get("domain") or [""])[0],
                    tags=(params.get("tags") or [""])[0],
                ))
            if path == "/api/actions":
                return self.send_json({"actions": list_actions(params)})
            if path == "/api/patterns":
                return self.send_json({"patterns": patterns(), "insights": pattern_insights(), "engine": pattern_engine_scan(save=False, scan_type="preview")})
            if path == "/api/pattern-engine/scan":
                save = clean_text((params.get("save") or [""])[0]).lower() in {"1", "true", "yes"}
                return self.send_json(pattern_engine_scan(save=save, scan_type="manual"))
            if path == "/api/dashboard" or path == "/api/command":
                return self.send_json(dashboard())
            if path == "/api/command/dormant":
                return self.send_json(dormant_info_report())
            if path.startswith("/api/sales/"):
                if path == "/api/sales/trends":
                    days = int((params.get("days") or ["30"])[0])
                    return self.send_json(get_sales_trends(days=days))
                if path == "/api/sales/watchlist":
                    return self.send_json(get_sales_watchlist())
                if path == "/api/sales/discovery":
                    limit = int((params.get("limit") or ["40"])[0])
                    return self.send_json(get_sales_discovery(limit=limit))
                if path == "/api/sales/opportunities":
                    return self.send_json(get_sales_opportunities())
            if path == "/api/export":
                payload = export_all()
                body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=info-analyzer-os-export.json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        except KeyError as e:
            return self.send_json({"error": str(e)}, 404)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"error": str(e)}, 500)
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self.read_json()
            if path == "/api/codify":
                return self.send_json({"draft": codify_payload(payload)})
            if path == "/api/translate/ai":
                draft = ai_translate(payload)
                return self.send_json({"draft": draft, "ai_used": draft.get("ai_used", False)})
            if path == "/api/translate/batch":
                return self.send_json(batch_translate(payload))
            if path == "/api/loop/analyze":
                return self.send_json(loop_engineer(payload))
            if path == "/api/translation/contract":
                return self.send_json(translation_contract(payload))
            if path == "/api/import/workbook":
                return self.send_json(import_workbook_path(payload.get("path") or payload.get("source_path") or ""), 201)
            if path.startswith("/api/entries/") and path.endswith("/recategorize"):
                entry_id = unquote(path.split("/api/entries/", 1)[1].rsplit("/recategorize", 1)[0])
                entry = recategorize_entry(entry_id, payload)
                return self.send_json({"success": True, "entry": entry})
            if path == "/api/entries":
                result = create_entry(payload)
                return self.send_json({"success": True, **result, "entry_id": result["entry"]["id"]}, 201)
            if path == "/api/relationships":
                rel = create_relationship(payload)
                return self.send_json({"success": True, "relationship": rel, "relationship_id": rel["id"]}, 201)
            if path == "/api/context" or path == "/api/resurface":
                return self.send_json(resurface_context(
                    raw_input=payload.get("raw_input") or payload.get("q") or "",
                    domain=payload.get("domain") or "",
                    entity=payload.get("entity") or "",
                    tags=payload.get("tags"),
                    signal_role=payload.get("signal_role") or "",
                    triggered_by_entry_id=payload.get("triggered_by_entry_id") or "",
                    save_cards=bool(payload.get("save_cards")),
                ), 201)
            if path == "/api/context/rewire":
                limit = payload.get("limit")
                try:
                    limit = int(limit) if limit not in (None, "", []) else None
                except Exception:
                    limit = None
                with connect() as conn:
                    return self.send_json(rebuild_contextual_memory(conn, limit=limit), 201)
            if path == "/api/pull":
                return self.send_json(pull_actionable_memory(
                    query=payload.get("q") or payload.get("query") or "",
                    domain=payload.get("domain") or "",
                    tags=payload.get("tags"),
                ), 201)
            if path == "/api/pattern-engine/scan":
                return self.send_json(pattern_engine_scan(save=bool(payload.get("save")), scan_type=payload.get("scan_type") or "manual"), 201)
            if path == "/api/import":
                result = import_all(payload)
                return self.send_json({"success": True, **result})
        except KeyError as e:
            return self.send_json({"error": str(e)}, 404)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"error": str(e)}, 500)
        return self.send_json({"error": "not found"}, 404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self.read_json()
            if path.startswith("/api/entries/"):
                entry = update_entry(unquote(path.split("/api/entries/", 1)[1]), payload)
                return self.send_json({"success": True, "entry": entry})
            if path.startswith("/api/actions/"):
                action = update_action(unquote(path.split("/api/actions/", 1)[1]), payload)
                return self.send_json({"success": True, "action": action})
        except KeyError as e:
            return self.send_json({"error": str(e)}, 404)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"error": str(e)}, 500)
        return self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/entries/"):
                result = delete_entry(unquote(path.split("/api/entries/", 1)[1]))
                return self.send_json({"success": True, **result})
        except KeyError as e:
            return self.send_json({"error": str(e)}, 404)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            return self.send_json({"error": str(e)}, 500)
        return self.send_json({"error": "not found"}, 404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--import-workbook", action="append", default=[], help="Absolute path to a local .xlsx or .xlsb workbook")
    parser.add_argument("--no-serve", action="store_true", help="Run import tasks and exit without starting the web server")
    args = parser.parse_args(argv)
    init_db()
    for workbook_path in args.import_workbook:
        result = import_workbook_path(workbook_path)
        print(f"Imported {result['file_name']} -> batch {result['id']} ({result.get('status', 'imported')})")
        print(f"Sheets: {result.get('sheet_count', 0)} | Rows: {result.get('row_count', 0)} | Projected: {result.get('projected_count', 0)}")
        if result.get("notes"):
            print(result["notes"])
    if args.no_serve:
        return
    httpd = Server((args.host, args.port), Handler)
    print(f"Info Analyzer OS {APP_VERSION} running at http://{args.host}:{args.port}")
    print(f"SQLite DB: {DB_PATH}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
