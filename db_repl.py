#!/usr/bin/env python3
"""
Interactive Database REPL for Claude Code

Start this, then Claude can run SQL queries directly.

Usage:
    python3 db_repl.py

Then in Claude Code chat, use:
    ! python3 db_repl.py --query "SELECT ..."
    ! python3 db_repl.py --sql "INSERT ..."
"""

import sqlite3
import json
import sys
import argparse
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "data" / "info_analyzer.db"


def connect():
    """Open database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: list = None) -> list[dict]:
    """Execute SELECT query, return results as list of dicts."""
    conn = connect()
    try:
        cursor = conn.execute(sql, params or [])
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def execute(sql: str, params: list = None) -> dict:
    """Execute INSERT/UPDATE/DELETE, return row count."""
    conn = connect()
    try:
        cursor = conn.execute(sql, params or [])
        conn.commit()
        return {
            "success": True,
            "rows_affected": cursor.rowcount,
            "last_insert_id": cursor.lastrowid
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def get_entry(entry_id: str) -> dict:
    """Fetch a full entry by ID (convenience function)."""
    results = query(
        "SELECT * FROM entries WHERE id = ?",
        [entry_id]
    )
    return results[0] if results else {}


def get_queue() -> list[dict]:
    """Fetch all pending entries (convenience function)."""
    return query("""
        SELECT id, title, domain, entity, status, created_at
        FROM entries
        WHERE status IN ('pending_claude', 'raw', 'needs_enrichment')
        ORDER BY created_at DESC
    """)


def get_patterns() -> list[dict]:
    """Fetch pattern records (convenience function)."""
    return query("""
        SELECT * FROM pattern_stats
        ORDER BY created_at DESC LIMIT 20
    """)


def get_stats() -> dict:
    """Get database statistics."""
    conn = connect()
    try:
        stats = {
            "total_entries": conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "queued": conn.execute(
                "SELECT COUNT(*) FROM entries WHERE status IN ('pending_claude', 'raw', 'needs_enrichment')"
            ).fetchone()[0],
            "codified": conn.execute(
                "SELECT COUNT(*) FROM entries WHERE status = 'codified'"
            ).fetchone()[0],
            "archived": conn.execute(
                "SELECT COUNT(*) FROM entries WHERE status = 'archived'"
            ).fetchone()[0],
            "actions_open": conn.execute(
                "SELECT COUNT(*) FROM actions WHERE status = 'open'"
            ).fetchone()[0],
        }
        return stats
    finally:
        conn.close()


def update_entry(entry_id: str, updates: dict) -> dict:
    """Update entry fields. Returns updated entry."""
    # Build SET clause
    set_parts = [f"{k} = ?" for k in updates.keys()]
    set_clause = ", ".join(set_parts)
    values = list(updates.values())
    values.append(entry_id)

    sql = f"UPDATE entries SET {set_clause} WHERE id = ?"

    result = execute(sql, values)
    if result["success"]:
        # Return updated entry
        updated = get_entry(entry_id)
        result["entry"] = updated
    return result


def insert_entry(data: dict) -> dict:
    """Insert new entry. Returns created entry."""
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    sql = f"INSERT INTO entries ({cols}) VALUES ({placeholders})"

    result = execute(sql, list(data.values()))
    if result["success"] and result["last_insert_id"]:
        # Return created entry
        created = get_entry(result["last_insert_id"])
        result["entry"] = created
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Database REPL for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 db_repl.py --query "SELECT * FROM entries LIMIT 5"
  python3 db_repl.py --sql "UPDATE entries SET status='codified' WHERE id='...'"
  python3 db_repl.py --get-entry IA-20260629082916-A51B8A
  python3 db_repl.py --get-queue
  python3 db_repl.py --get-stats
  python3 db_repl.py --interactive

When using --query or --sql, output is JSON for easy parsing by Claude.
        """
    )

    parser.add_argument("--query", help="Execute SELECT query (read-only)")
    parser.add_argument("--sql", help="Execute INSERT/UPDATE/DELETE")
    parser.add_argument("--get-entry", metavar="ID", help="Fetch entry by ID")
    parser.add_argument("--get-queue", action="store_true", help="Fetch pending queue")
    parser.add_argument("--get-stats", action="store_true", help="Get DB stats")
    parser.add_argument("--get-patterns", action="store_true", help="Fetch patterns")
    parser.add_argument("--update-entry", nargs=2, metavar=("ID", "JSON"), help="Update entry (ID and JSON update payload)")
    parser.add_argument("--insert-entry", metavar="JSON", help="Insert new entry (JSON payload)")
    parser.add_argument("--interactive", action="store_true", help="Interactive REPL mode")

    args = parser.parse_args()

    # Ensure DB exists
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    if args.query:
        results = query(args.query)
        print(json.dumps(results, indent=2, default=str))

    elif args.sql:
        result = execute(args.sql)
        print(json.dumps(result, indent=2, default=str))

    elif args.get_entry:
        entry = get_entry(args.get_entry)
        print(json.dumps(entry, indent=2, default=str))

    elif args.get_queue:
        entries = get_queue()
        print(json.dumps(entries, indent=2, default=str))

    elif args.get_stats:
        stats = get_stats()
        print(json.dumps(stats, indent=2, default=str))

    elif args.get_patterns:
        patterns = get_patterns()
        print(json.dumps(patterns, indent=2, default=str))

    elif args.update_entry:
        entry_id, json_str = args.update_entry
        try:
            updates = json.loads(json_str)
            result = update_entry(entry_id, updates)
            print(json.dumps(result, indent=2, default=str))
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}, indent=2))

    elif args.insert_entry:
        try:
            data = json.loads(args.insert_entry)
            result = insert_entry(data)
            print(json.dumps(result, indent=2, default=str))
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}, indent=2))

    elif args.interactive:
        print("\n" + "=" * 70)
        print("Database Interactive REPL")
        print("=" * 70)
        print("\nCommands:")
        print("  :queue       - Show pending queue")
        print("  :stats       - Show database stats")
        print("  :patterns    - Show patterns")
        print("  :entry ID    - Get entry by ID")
        print("  :help        - Show this help")
        print("  :exit        - Exit")
        print("\nOr type SQL directly (SELECT, INSERT, UPDATE, DELETE)")
        print("=" * 70 + "\n")

        while True:
            try:
                cmd = input("> ").strip()

                if not cmd:
                    continue
                elif cmd == ":exit":
                    break
                elif cmd == ":help":
                    print("Commands: :queue, :stats, :patterns, :entry ID, :exit")
                elif cmd == ":queue":
                    entries = get_queue()
                    print(json.dumps(entries, indent=2, default=str))
                elif cmd == ":stats":
                    stats = get_stats()
                    print(json.dumps(stats, indent=2, default=str))
                elif cmd == ":patterns":
                    patterns = get_patterns()
                    print(json.dumps(patterns, indent=2, default=str))
                elif cmd.startswith(":entry "):
                    entry_id = cmd[7:].strip()
                    entry = get_entry(entry_id)
                    print(json.dumps(entry, indent=2, default=str))
                elif cmd.upper().startswith("SELECT "):
                    results = query(cmd)
                    print(json.dumps(results, indent=2, default=str))
                else:
                    result = execute(cmd)
                    print(json.dumps(result, indent=2, default=str))

            except KeyboardInterrupt:
                print("\nExit")
                break
            except Exception as e:
                print(f"Error: {e}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
