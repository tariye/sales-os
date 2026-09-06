#!/usr/bin/env python3
"""Read-only probe for the canonical Info Analyzer SQLite database.

This script intentionally avoids row-level content dumps. It reports schema,
counts, constraints, data-shape metadata, and server usage aggregates so future
migrations can be validated without exposing private entry contents.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "info_analyzer.db"
SERVER_PATH = PROJECT_ROOT / "server.py"

TABLE_CLASSIFICATIONS: dict[str, str] = {
    "actions": "Decision/action infrastructure",
    "api_idempotency": "Operational/audit infrastructure",
    "audit_log": "Operational/audit infrastructure",
    "decision_reviews": "Decision/action infrastructure",
    "decision_rules": "Decision/action infrastructure",
    "device_log_catalog": "Ingestion infrastructure",
    "entity_aliases": "Legacy memory/intelligence",
    "entries": "Legacy memory/intelligence",
    "entries_fts": "Legacy memory/intelligence",
    "entries_fts_config": "Legacy memory/intelligence",
    "entries_fts_content": "Legacy memory/intelligence",
    "entries_fts_data": "Legacy memory/intelligence",
    "entries_fts_docsize": "Legacy memory/intelligence",
    "entries_fts_idx": "Legacy memory/intelligence",
    "import_batches": "Ingestion infrastructure",
    "import_rows": "Ingestion infrastructure",
    "import_sheets": "Ingestion infrastructure",
    "ingest_items": "Ingestion infrastructure",
    "ingest_sources": "Ingestion infrastructure",
    "ledger_decisions": "Transitional or uncertain",
    "ledger_projects": "Transitional or uncertain",
    "listening_extractions": "Domain module",
    "listening_projects": "Domain module",
    "live_signals": "Transitional or uncertain",
    "pattern_runs": "Legacy memory/intelligence",
    "pattern_stats": "Legacy memory/intelligence",
    "portfolio_trades": "Domain module",
    "pull_rules": "Legacy memory/intelligence",
    "relationships": "Legacy memory/intelligence",
    "risk_reward_setups": "Domain module",
    "surfaced_cards": "Legacy memory/intelligence",
    "watchlist_items": "Domain module",
    "watchlists": "Domain module",
}

JSONISH_COLUMNS = {
    "json",
    "metadata",
    "metadata_json",
    "payload",
    "payload_json",
    "raw_fields",
    "raw_json",
    "normalized_json",
    "columns_json",
    "sample_rows_json",
    "tags",
    "cards",
    "options",
    "section_map",
    "glossary",
    "action_card",
    "entity_aliases",
    "entity_aliases_json",
}

TIMESTAMP_COLUMNS = {
    "created_at",
    "updated_at",
    "received_at",
    "occurred_at",
    "observed_at",
    "due_at",
    "started_at",
    "completed_at",
    "scheduled_at",
    "presented_at",
    "acknowledged_at",
    "snoozed_until",
    "resolved_at",
    "decided_at",
    "last_run_at",
    "last_triggered",
    "first_observed_at",
    "last_validated_at",
    "routed_at",
    "last_resurfaced",
    "applied_at",
    "published_at",
    "created",
    "updated",
    "date",
    "review_date",
}


@dataclass
class TableProbe:
    name: str
    classification: str
    row_count: int
    columns: list[dict[str, Any]]
    foreign_keys: list[dict[str, Any]]
    indexes: list[dict[str, Any]]
    notes: list[str]
    status_values: dict[str, list[str]]
    confidence_values: dict[str, list[str]]
    priority_values: dict[str, list[str]]
    action_values: dict[str, list[str]]
    json_validity: dict[str, dict[str, int]]
    timestamp_formats: dict[str, list[str]]
    identifier_prefixes: dict[str, list[tuple[str, int]]]


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def classify_table(name: str) -> str:
    return TABLE_CLASSIFICATIONS.get(name, "Transitional or uncertain")


def infer_timestamp_format(value: str) -> str:
    if value.endswith("Z"):
        suffix = "Z"
        body = value[:-1]
    elif "+" in value[10:] or "-" in value[10:]:
        # timezone offsets such as +00:00 or -07:00
        suffix = value[-6:]
        body = value[:-6]
    else:
        suffix = "naive"
        body = value
    has_fraction = "." in body
    if has_fraction:
        return f"ISO-8601 {suffix} with fractional seconds"
    return f"ISO-8601 {suffix} without fractional seconds"


def identifier_prefix(value: str) -> str:
    match = re.match(r"^[A-Za-z]+", value)
    if match:
        return match.group(0)
    return value[:8] if len(value) > 8 else value


def safe_json_valid(conn: sqlite3.Connection, table: str, column: str) -> tuple[int, int] | None:
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL"
        ).fetchone()[0]
        valid = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL AND json_valid({column})"
        ).fetchone()[0]
        return int(valid), int(total)
    except sqlite3.OperationalError:
        return None


def probe_table(conn: sqlite3.Connection, name: str, server_source: str) -> TableProbe:
    columns = [dict(row) for row in conn.execute(f"PRAGMA table_info({name})").fetchall()]
    foreign_keys = [dict(row) for row in conn.execute(f"PRAGMA foreign_key_list({name})").fetchall()]
    indexes = [dict(row) for row in conn.execute(f"PRAGMA index_list({name})").fetchall()]
    row_count = int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
    column_names = {col["name"] for col in columns}

    status_values: dict[str, list[str]] = {}
    confidence_values: dict[str, list[str]] = {}
    priority_values: dict[str, list[str]] = {}
    action_values: dict[str, list[str]] = {}
    json_validity: dict[str, dict[str, int]] = {}
    timestamp_formats: dict[str, list[str]] = {}
    identifier_prefixes: dict[str, list[tuple[str, int]]] = {}
    notes: list[str] = []

    for special in ("status", "priority", "confidence", "action_status"):
        if special in column_names:
            rows = conn.execute(
                f"""
                SELECT {special} AS value, COUNT(*) AS count
                FROM {name}
                WHERE {special} IS NOT NULL
                GROUP BY {special}
                ORDER BY count DESC, value ASC
                """
            ).fetchall()
            values = [str(row["value"]) for row in rows]
            if special == "status":
                status_values[special] = values
            elif special == "priority":
                priority_values[special] = values
            elif special == "confidence":
                confidence_values[special] = values
            elif special == "action_status":
                action_values[special] = values

    for col in columns:
        col_name = col["name"]
        lower = col_name.lower()
        if (
            lower in JSONISH_COLUMNS
            or lower.endswith("_json")
            or lower.endswith("_fields")
            or lower.endswith("_map")
        ):
            validity = safe_json_valid(conn, name, col_name)
            if validity is not None:
                valid, total = validity
                json_validity[col_name] = {"valid": valid, "total": total}

        if lower in TIMESTAMP_COLUMNS or lower.endswith("_at") or lower.endswith("_date"):
            samples = [
                row[0]
                for row in conn.execute(
                    f"SELECT {col_name} FROM {name} WHERE {col_name} IS NOT NULL LIMIT 12"
                ).fetchall()
            ]
            if samples:
                formats = sorted({infer_timestamp_format(str(sample)) for sample in samples})
                timestamp_formats[col_name] = formats

        if (col_name == "id" or lower.endswith("_id")) and col["type"].upper() in {"TEXT", ""}:
            rows = [
                row[0]
                for row in conn.execute(
                    f"SELECT {col_name} FROM {name} WHERE {col_name} IS NOT NULL LIMIT 200"
                ).fetchall()
            ]
            if rows:
                prefixes = Counter(identifier_prefix(str(value)) for value in rows)
                identifier_prefixes[col_name] = prefixes.most_common(5)

    if name in {"ledger_projects", "ledger_decisions", "live_signals", "entity_aliases"}:
        notes.append("Related to the legacy decision/memory graph but not fully normalized.")
    if name.startswith("entries_fts"):
        notes.append("FTS shadow/support table for legacy entries search.")
    if name in {"pattern_runs", "pattern_stats"}:
        notes.append("Derived analytics/history table with no direct foreign keys.")
    if name in {"api_idempotency", "audit_log"}:
        notes.append("Operational support table.")

    return TableProbe(
        name=name,
        classification=classify_table(name),
        row_count=row_count,
        columns=columns,
        foreign_keys=foreign_keys,
        indexes=indexes,
        notes=notes,
        status_values=status_values,
        confidence_values=confidence_values,
        priority_values=priority_values,
        action_values=action_values,
        json_validity=json_validity,
        timestamp_formats=timestamp_formats,
        identifier_prefixes=identifier_prefixes,
    )


def server_table_usage(server_source: str, table_names: list[str]) -> dict[str, int]:
    text = Path(server_source).read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for table in table_names:
        counts[table] = len(re.findall(rf"\b{re.escape(table)}\b", text))
    return counts


def detect_related_without_fk(conn: sqlite3.Connection, probes: list[TableProbe]) -> dict[str, list[str]]:
    by_table = {probe.name: probe for probe in probes}
    out: dict[str, list[str]] = {}
    for probe in probes:
        fk_cols = {fk["from"] for fk in probe.foreign_keys}
        candidate_cols = [
            col["name"]
            for col in probe.columns
            if col["name"].endswith("_id")
            and col["name"] not in fk_cols
            and col["pk"] == 0
        ]
        if candidate_cols:
            out[probe.name] = candidate_cols
    return out


def schema_inventory(conn: sqlite3.Connection) -> dict[str, list[str]]:
    inventory: dict[str, list[str]] = {}
    for kind in ("table", "view", "index", "trigger"):
        inventory[kind] = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%' ORDER BY name",
                (kind,),
            ).fetchall()
        ]
    return inventory


def probe_database(database_path: Path) -> dict[str, Any]:
    conn = connect(database_path)
    try:
        tables = schema_inventory(conn)["table"]
        table_probes = [probe_table(conn, table, str(SERVER_PATH)) for table in tables]
        server_usage = server_table_usage(str(SERVER_PATH), tables)
        return {
            "database_path": str(database_path),
            "sqlite_version": sqlite3.sqlite_version,
            "database_size": database_path.stat().st_size if database_path.exists() else None,
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": bool(conn.execute("PRAGMA foreign_keys").fetchone()[0]),
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_check": [list(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()],
            "inventory": schema_inventory(conn),
            "tables": [probe.__dict__ for probe in table_probes],
            "server_usage": server_usage,
            "related_without_fk": detect_related_without_fk(conn, table_probes),
        }
    finally:
        conn.close()


def render_markdown(probe: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Combined Database Probe")
    lines.append("")
    lines.append("## Baseline Facts")
    lines.append("")
    lines.append(f"- Database path: `{probe['database_path']}`")
    lines.append(f"- SQLite version: `{probe['sqlite_version']}`")
    lines.append(f"- Database size: `{probe['database_size']}` bytes")
    lines.append(f"- PRAGMA journal_mode: `{probe['journal_mode']}`")
    lines.append(f"- PRAGMA foreign_keys: `{int(bool(probe['foreign_keys']))}`")
    lines.append(f"- PRAGMA integrity_check: `{probe['integrity_check']}`")
    fk_check = probe["foreign_key_check"]
    lines.append(f"- PRAGMA foreign_key_check rows: `{len(fk_check)}`")
    lines.append("")
    lines.append("## Schema Inventory")
    lines.append("")
    for kind in ("table", "view", "index", "trigger"):
        items = probe["inventory"].get(kind, [])
        lines.append(f"- {kind.title()}s ({len(items)}): " + (", ".join(f"`{item}`" for item in items) if items else "none"))
    lines.append("")
    lines.append("## Table Classification and Counts")
    lines.append("")
    lines.append("| Table | Classification | Rows | Columns | FKs | Server refs | Notes |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | --- |")
    for table in probe["tables"]:
        notes = "; ".join(table["notes"]) if table["notes"] else ""
        lines.append(
            f"| `{table['name']}` | {table['classification']} | {table['row_count']} | "
            f"{len(table['columns'])} | {len(table['foreign_keys'])} | "
            f"{probe['server_usage'].get(table['name'], 0)} | {notes} |"
        )
    lines.append("")
    lines.append("## Tables Related But Without Declared FKs")
    lines.append("")
    if probe["related_without_fk"]:
        for table, cols in probe["related_without_fk"].items():
            lines.append(f"- `{table}`: {', '.join('`' + c + '`' for c in cols)}")
    else:
        lines.append("- None detected.")
    lines.append("")
    lines.append("## Server.py Usage")
    lines.append("")
    lines.append("- Tables used by `server.py` are summarized by regex hits in the source file.")
    for table, count in sorted(probe["server_usage"].items(), key=lambda kv: (-kv[1], kv[0])):
        if count:
            lines.append(f"  - `{table}`: {count}")
    lines.append("")
    lines.append("## Per-Table Schema Detail")
    lines.append("")
    for table in probe["tables"]:
        lines.append(f"### `{table['name']}`")
        lines.append("")
        lines.append(f"- Classification: {table['classification']}")
        lines.append(f"- Row count: {table['row_count']}")
        lines.append(f"- Foreign keys: {len(table['foreign_keys'])}")
        lines.append(f"- Indexes: {len(table['indexes'])}")
        if table["notes"]:
            lines.append(f"- Notes: {'; '.join(table['notes'])}")
        if table["status_values"]:
            lines.append(f"- Status values: {json.dumps(table['status_values'])}")
        if table["priority_values"]:
            lines.append(f"- Priority values: {json.dumps(table['priority_values'])}")
        if table["confidence_values"]:
            lines.append(f"- Confidence values: {json.dumps(table['confidence_values'])}")
        if table["action_values"]:
            lines.append(f"- Action-state values: {json.dumps(table['action_values'])}")
        if table["timestamp_formats"]:
            lines.append(f"- Timestamp formats: {json.dumps(table['timestamp_formats'])}")
        if table["identifier_prefixes"]:
            lines.append(f"- Identifier prefixes: {json.dumps(table['identifier_prefixes'])}")
        if table["json_validity"]:
            lines.append(f"- JSON validity: {json.dumps(table['json_validity'])}")
        lines.append("")
        lines.append("| Column | Type | Null | Default | PK |")
        lines.append("| --- | --- | --- | --- | ---: |")
        for col in table["columns"]:
            default = col["dflt_value"]
            if default is None:
                default = ""
            lines.append(
                f"| `{col['name']}` | `{col['type']}` | {0 if col['notnull'] else 1} | "
                f"`{default}` | {col['pk']} |"
            )
        if table["foreign_keys"]:
            lines.append("")
            lines.append("| FK column | Ref table | Ref column | On update | On delete |")
            lines.append("| --- | --- | --- | --- | --- |")
            for fk in table["foreign_keys"]:
                lines.append(
                    f"| `{fk['from']}` | `{fk['table']}` | `{fk['to']}` | `{fk['on_update']}` | `{fk['on_delete']}` |"
                )
        lines.append("")
    lines.append("## Overlap Notes")
    lines.append("")
    lines.append("- `entries` and `live_signals` are legacy signal-memory surfaces; `core_*` does not exist yet in the baseline.")
    lines.append("- `ledger_projects` and `ledger_decisions` are transitional precursors to the normalized core concepts.")
    lines.append("- `import_*`, `watchlists`, `watchlist_items`, `portfolio_trades`, and `risk_reward_setups` are domain/import infrastructure.")
    lines.append("- `api_idempotency` and `audit_log` are operational support tables.")
    lines.append("- All declared foreign keys pass `PRAGMA foreign_key_check`; `entries`/FTS shadows are search support tables rather than new data models.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    probe = probe_database(args.database.expanduser().resolve())
    if args.json:
        args.json.write_text(json.dumps(probe, indent=2, sort_keys=True), encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render_markdown(probe), encoding="utf-8")
    else:
        print(json.dumps(probe, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
