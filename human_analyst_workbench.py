#!/usr/bin/env python3
"""
Human Analyst Workbench — Evidence Review, Correction, Hypothesis Testing, Action Approval

No autonomous decisions. All significant actions require explicit human approval.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def human_analyst_schema_init(db: sqlite3.Connection) -> None:
    """Initialize human analyst workbench schema extensions."""
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    # PHASE 1: Test Mode Sessions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_mode_sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            enabled_at TEXT NOT NULL,
            disabled_at TEXT,
            test_db_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            description TEXT,
            created_by TEXT
        )
    """)

    # PHASE 2: Import Management (extends existing import tables)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS import_fixtures (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            fixture_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            row_count INTEGER,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            quarantine_count INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS import_row_status (
            id TEXT PRIMARY KEY,
            import_id TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            original_payload TEXT NOT NULL,
            normalized_payload TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            requires_review TEXT DEFAULT 'false',
            FOREIGN KEY (import_id) REFERENCES import_fixtures(id)
        )
    """)

    # PHASE 3: Human Review Queue
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS human_reviews (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            review_type TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            evidence_id TEXT,
            system_interpretation TEXT,
            system_confidence REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            human_verdict TEXT,
            human_correction TEXT,
            human_reason TEXT,
            human_confidence REAL,
            verdict_at TEXT,
            reviewed_by TEXT,
            FOREIGN KEY (evidence_id) REFERENCES raw_snapshots(id)
        )
    """)

    # PHASE 4: Entity Matching Decisions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entity_match_decisions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            entity_a_id TEXT NOT NULL,
            entity_b_id TEXT NOT NULL,
            system_confidence REAL,
            human_decision TEXT NOT NULL,
            human_reason TEXT,
            decided_at TEXT,
            decided_by TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(entity_a_id, entity_b_id)
        )
    """)

    # PHASE 5: Comparison Records (for before/after analysis)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comparison_records (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            prior_capture_id TEXT,
            current_capture_id TEXT,
            field_name TEXT,
            prior_value TEXT,
            current_value TEXT,
            absolute_change TEXT,
            percentage_change REAL,
            system_confidence REAL,
            review_status TEXT DEFAULT 'pending',
            human_classification TEXT,
            FOREIGN KEY (prior_capture_id) REFERENCES raw_snapshots(id),
            FOREIGN KEY (current_capture_id) REFERENCES raw_snapshots(id)
        )
    """)

    # PHASE 6: Hypothesis Drafts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hypothesis_drafts (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            statement TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            supporting_evidence TEXT,
            contradicting_evidence TEXT,
            confidence REAL,
            test_method TEXT,
            expected_result TEXT,
            deadline TEXT,
            success_condition TEXT,
            failure_condition TEXT,
            created_by TEXT,
            approved_at TEXT,
            approved_by TEXT,
            test_start_at TEXT,
            test_end_at TEXT,
            conclusion TEXT
        )
    """)

    # PHASE 7: Approved Actions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approved_actions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            proposed_action TEXT NOT NULL,
            rationale TEXT,
            evidence_summary TEXT,
            expected_result TEXT,
            deadline TEXT,
            risk_limit REAL,
            success_condition TEXT,
            approval_state TEXT NOT NULL DEFAULT 'draft',
            drafted_by TEXT,
            approved_at TEXT,
            approved_by TEXT,
            approval_reason TEXT,
            rejected_at TEXT,
            rejection_reason TEXT,
            deferred_at TEXT,
            deferral_reason TEXT,
            hypothesis_id TEXT,
            FOREIGN KEY (hypothesis_id) REFERENCES hypothesis_drafts(id)
        )
    """)

    # PHASE 8: Outcome Records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS action_outcomes (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            action_id TEXT NOT NULL,
            action_performed TEXT,
            actual_result TEXT,
            result_date TEXT,
            success_status TEXT,
            unexpected_factors TEXT,
            lesson TEXT,
            rule_adjustment_recommendation TEXT,
            recorded_by TEXT,
            recorded_at TEXT,
            FOREIGN KEY (action_id) REFERENCES approved_actions(id)
        )
    """)

    # PHASE 9: Disagreement Ledger
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disagreement_ledger (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            system_proposal TEXT,
            system_confidence REAL,
            human_decision TEXT,
            human_reason TEXT,
            actual_outcome TEXT,
            which_was_better TEXT,
            calibration_suggestion TEXT,
            recorded_by TEXT,
            recorded_at TEXT
        )
    """)

    db.commit()


def init_test_database(test_db_path: Path) -> sqlite3.Connection:
    """Initialize a separate test database with full schema."""
    test_db_path.parent.mkdir(parents=True, exist_ok=True)

    # Create test database
    test_db = sqlite3.connect(str(test_db_path))
    test_db.row_factory = sqlite3.Row

    # Initialize basic schema (would normally clone from active)
    cursor = test_db.cursor()

    # Create all tables that exist in active database
    tables = [
        "entries", "raw_snapshots", "ingest_sources", "ingest_runs",
        "ingest_items", "actions", "live_signals", "watchlists",
        "watchlist_items", "worker_heartbeats", "scheduler_events",
        "scheduler_leases", "worker_claims", "data_plane_jobs",
        "pattern_runs", "decision_reviews", "decision_rules",
        "relationships", "surfaced_cards", "audit_log", "source_health_events"
    ]

    for table in tables:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
        """)

    # Initialize workbench schema
    human_analyst_schema_init(test_db)

    # Create marker that this is a test database
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_mode_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR REPLACE INTO test_mode_metadata VALUES (?, ?)",
                   ("test_db", "true"))
    cursor.execute("INSERT OR REPLACE INTO test_mode_metadata VALUES (?, ?)",
                   ("created_at", get_utc_now()))

    test_db.commit()
    return test_db


def enable_test_mode(active_db: sqlite3.Connection, test_db_path: Path) -> str:
    """Enable test mode for the current session."""
    session_id = f"TEST-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"

    cursor = active_db.cursor()
    cursor.execute("""
        INSERT INTO test_mode_sessions (id, created_at, enabled_at, test_db_path, status)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, get_utc_now(), get_utc_now(), str(test_db_path), "active"))

    active_db.commit()
    return session_id


def get_test_mode_status(active_db: sqlite3.Connection) -> dict[str, Any]:
    """Get current test mode status."""
    cursor = active_db.cursor()
    cursor.execute("""
        SELECT id, enabled_at, status, test_db_path
        FROM test_mode_sessions
        WHERE status = 'active'
        ORDER BY enabled_at DESC
        LIMIT 1
    """)
    row = cursor.fetchone()

    if not row:
        return {
            "active": False,
            "session_id": None,
            "test_db_path": None,
            "mode": "production"
        }

    return {
        "active": True,
        "session_id": row["id"],
        "test_db_path": row["test_db_path"],
        "enabled_at": row["enabled_at"],
        "mode": "test"
    }


def create_human_review(
    db: sqlite3.Connection,
    review_type: str,
    subject_type: str,
    subject_id: str,
    system_interpretation: str,
    system_confidence: float,
    evidence_id: str | None = None
) -> str:
    """Create a human review record."""
    review_id = f"REVIEW-{uuid.uuid4().hex[:12].upper()}"

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO human_reviews (
            id, created_at, review_type, subject_type, subject_id,
            evidence_id, system_interpretation, system_confidence, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        review_id, get_utc_now(), review_type, subject_type, subject_id,
        evidence_id, system_interpretation, system_confidence, "pending"
    ))

    db.commit()
    return review_id


def record_human_verdict(
    db: sqlite3.Connection,
    review_id: str,
    verdict: str,
    correction: str | None = None,
    reason: str | None = None,
    confidence: float = 0.9,
    reviewed_by: str = "human"
) -> bool:
    """Record a human verdict on a review."""
    cursor = db.cursor()
    cursor.execute("""
        UPDATE human_reviews
        SET status = ?, human_verdict = ?, human_correction = ?,
            human_reason = ?, human_confidence = ?, verdict_at = ?,
            reviewed_by = ?
        WHERE id = ?
    """, (
        "completed", verdict, correction, reason, confidence,
        get_utc_now(), reviewed_by, review_id
    ))

    db.commit()
    return cursor.rowcount > 0


def create_hypothesis(
    db: sqlite3.Connection,
    statement: str,
    test_method: str,
    expected_result: str,
    deadline: str,
    supporting_evidence: str | None = None,
    created_by: str = "analyst"
) -> str:
    """Create a hypothesis draft."""
    hypothesis_id = f"HYP-{uuid.uuid4().hex[:12].upper()}"

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO hypothesis_drafts (
            id, created_at, statement, status, test_method,
            expected_result, deadline, supporting_evidence, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        hypothesis_id, get_utc_now(), statement, "draft", test_method,
        expected_result, deadline, supporting_evidence, created_by
    ))

    db.commit()
    return hypothesis_id


def propose_action(
    db: sqlite3.Connection,
    action: str,
    rationale: str,
    expected_result: str,
    success_condition: str,
    hypothesis_id: str | None = None,
    drafted_by: str = "analyst"
) -> str:
    """Propose an action (requires human approval before execution)."""
    action_id = f"ACT-{uuid.uuid4().hex[:12].upper()}"

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO approved_actions (
            id, created_at, proposed_action, rationale,
            expected_result, success_condition, approval_state,
            drafted_by, hypothesis_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        action_id, get_utc_now(), action, rationale,
        expected_result, success_condition, "draft",
        drafted_by, hypothesis_id
    ))

    db.commit()
    return action_id


def approve_action(
    db: sqlite3.Connection,
    action_id: str,
    approved_by: str = "analyst",
    reason: str | None = None
) -> bool:
    """Approve an action for execution (human decision)."""
    cursor = db.cursor()
    cursor.execute("""
        UPDATE approved_actions
        SET approval_state = ?, approved_at = ?, approved_by = ?, approval_reason = ?
        WHERE id = ? AND approval_state = ?
    """, (
        "approved", get_utc_now(), approved_by, reason,
        action_id, "draft"
    ))

    db.commit()
    return cursor.rowcount > 0


def record_outcome(
    db: sqlite3.Connection,
    action_id: str,
    actual_result: str,
    success_status: str,
    lesson: str | None = None,
    recorded_by: str = "analyst"
) -> str:
    """Record the actual outcome of an executed action."""
    outcome_id = f"OUT-{uuid.uuid4().hex[:12].upper()}"

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO action_outcomes (
            id, created_at, action_id, actual_result,
            success_status, lesson, recorded_by, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        outcome_id, get_utc_now(), action_id, actual_result,
        success_status, lesson, recorded_by, get_utc_now()
    ))

    # Update action to completed
    cursor.execute("""
        UPDATE approved_actions
        SET approval_state = ? WHERE id = ?
    """, ("completed", action_id))

    db.commit()
    return outcome_id


def get_pending_reviews(db: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    """Get pending human reviews."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, created_at, review_type, subject_type, subject_id,
               system_interpretation, system_confidence
        FROM human_reviews
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT ?
    """, (limit,))

    return [dict(row) for row in cursor.fetchall()]


def get_testing_hypotheses(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Get hypotheses currently being tested."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, statement, status, test_method,
               expected_result, test_start_at, deadline
        FROM hypothesis_drafts
        WHERE status IN ('testing', 'supported', 'rejected')
        ORDER BY test_start_at DESC
    """)

    return [dict(row) for row in cursor.fetchall()]


def get_pending_approvals(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Get actions awaiting human approval."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, proposed_action, rationale, expected_result,
               success_condition, created_at
        FROM approved_actions
        WHERE approval_state = 'draft'
        ORDER BY created_at ASC
    """)

    return [dict(row) for row in cursor.fetchall()]


def get_outcome_pending_actions(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Get approved actions awaiting outcome recording."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, proposed_action, approved_at, deadline
        FROM approved_actions
        WHERE approval_state = 'approved'
        ORDER BY approved_at DESC
    """)

    return [dict(row) for row in cursor.fetchall()]
