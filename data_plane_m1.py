from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


JOB_STATUSES = {
    "queued",
    "claimed",
    "running",
    "succeeded",
    "partial",
    "failed",
    "retry_scheduled",
    "dead_letter",
    "skipped_duplicate",
}
INGEST_RUN_STATUSES = {"running", "succeeded", "partial", "failed", "skipped_duplicate"}
SOURCE_EVENT_TYPES = {"source_failure", "source_stale", "source_recovered"}
LEASE_NAME = "data_plane_scheduler"
DEFAULT_SOURCE_ID = "fixture-source-default"
FIXTURE_CONNECTOR_TYPE = "fixture"
FIXTURE_CONNECTOR_NAME = "fixture_connector"
FIXTURE_CONNECTOR_VERSION = "1.0.0"
DEFAULT_CAPTURED_BUCKET_SECONDS = 300
DEFAULT_RETRY_DELAYS_SECONDS = (2, 5, 10)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso(value: datetime | None = None) -> str:
    current = value or now_utc()
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def make_id(prefix: str) -> str:
    stamp = now_utc().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8].upper()}"


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(raw_payload: str) -> str:
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def schedule_every_seconds(schedule_expression: str) -> int:
    text = str(schedule_expression or "").strip().lower()
    if not text.startswith("every:"):
        raise ValueError("schedule_expression must use every:<seconds>")
    seconds = int(text.split(":", 1)[1])
    if seconds <= 0:
        raise ValueError("schedule_expression must use a positive interval")
    return seconds


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def json_load(value: str | None, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def time_bucket(value: datetime, bucket_seconds: int) -> int:
    epoch = int(value.timestamp())
    return epoch - (epoch % bucket_seconds)


MIGRATIONS: list[tuple[str, str]] = [
    (
        "20260718_m1_001_schema_migrations",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        """,
    ),
    (
        "20260718_m1_002_sources",
        """
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            connector_type TEXT NOT NULL,
            connector_version TEXT NOT NULL,
            schedule_expression TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            freshness_target_seconds INTEGER NOT NULL,
            captured_bucket_seconds INTEGER NOT NULL,
            configuration_json TEXT NOT NULL DEFAULT '{}',
            last_attempt_at TEXT,
            last_success_at TEXT,
            last_error_at TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sources_active ON sources(active);
        """,
    ),
    (
        "20260718_m1_003_jobs",
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            status TEXT NOT NULL,
            claimed_by TEXT,
            claimed_at TEXT,
            lease_expires_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            next_retry_at TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            last_error_code TEXT,
            last_error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_jobs_idempotency_key ON jobs(idempotency_key);
        CREATE INDEX IF NOT EXISTS idx_jobs_claimable ON jobs(status, scheduled_for, next_retry_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source_id, status);
        """,
    ),
    (
        "20260718_m1_004_ingest_runs",
        """
        CREATE TABLE IF NOT EXISTS ingest_runs (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            connector_name TEXT NOT NULL,
            connector_version TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            payload_hash TEXT,
            error_code TEXT,
            error_message TEXT,
            retry_number INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id),
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ingest_runs_source_started ON ingest_runs(source_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ingest_runs_job ON ingest_runs(job_id);
        """,
    ),
    (
        "20260718_m1_005_raw_snapshots",
        """
        CREATE TABLE IF NOT EXISTS raw_snapshots (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            ingest_run_id TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            captured_bucket INTEGER NOT NULL,
            payload_hash TEXT NOT NULL,
            content_type TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            evidence_url TEXT,
            connector_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            FOREIGN KEY (ingest_run_id) REFERENCES ingest_runs(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_snapshots_dedup
            ON raw_snapshots(source_id, payload_hash, captured_bucket);
        CREATE INDEX IF NOT EXISTS idx_raw_snapshots_source_captured
            ON raw_snapshots(source_id, captured_at DESC);
        """,
    ),
    (
        "20260718_m1_006_source_health_events",
        """
        CREATE TABLE IF NOT EXISTS source_health_events (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id)
        );
        CREATE INDEX IF NOT EXISTS idx_source_health_events_source
            ON source_health_events(source_id, created_at DESC);
        """,
    ),
    (
        "20260718_m1_007_scheduler_leases",
        """
        CREATE TABLE IF NOT EXISTS scheduler_leases (
            lease_name TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            renewed_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    (
        "20260718_m1_008_quarantined_snapshots",
        """
        CREATE TABLE IF NOT EXISTS quarantined_snapshots (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            ingest_run_id TEXT,
            payload_hash TEXT NOT NULL,
            captured_at TEXT,
            reason_code TEXT NOT NULL,
            reason_message TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            FOREIGN KEY (ingest_run_id) REFERENCES ingest_runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_quarantined_snapshots_source
            ON quarantined_snapshots(source_id, created_at DESC);
        """,
    ),
    (
        "20260718_m1_009_normalization_failures",
        """
        CREATE TABLE IF NOT EXISTS normalization_failures (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            ingest_run_id TEXT,
            raw_snapshot_id TEXT,
            error_code TEXT NOT NULL,
            error_message TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            FOREIGN KEY (ingest_run_id) REFERENCES ingest_runs(id),
            FOREIGN KEY (raw_snapshot_id) REFERENCES raw_snapshots(id)
        );
        CREATE INDEX IF NOT EXISTS idx_normalization_failures_source
            ON normalization_failures(source_id, created_at DESC);
        """,
    ),
]


def apply_migrations(db_path: Path) -> list[str]:
    applied: list[str] = []
    with connect_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        for migration_id, sql in MIGRATIONS:
            exists = conn.execute("SELECT 1 FROM schema_migrations WHERE id=?", (migration_id,)).fetchone()
            if exists:
                continue
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
                (migration_id, now_iso()),
            )
            applied.append(migration_id)
        conn.commit()
    ensure_default_fixture_source(db_path)
    return applied


def ensure_default_fixture_source(db_path: Path) -> dict[str, Any]:
    created_at = now_iso()
    configuration = {
        "fixture_name": "milestone_1_default",
        "supported_scenarios": [
            "success_alpha",
            "repeat_alpha",
            "change_bravo",
            "partial_gamma",
            "delayed_delta",
            "failure_epsilon",
            "stale_seed",
        ],
        "default_scenario": "success_alpha",
        "captured_bucket_seconds": DEFAULT_CAPTURED_BUCKET_SECONDS,
    }
    with connect_db(db_path) as conn:
        existing = conn.execute("SELECT * FROM sources WHERE id=?", (DEFAULT_SOURCE_ID,)).fetchone()
        if existing:
            return row_to_dict(existing) or {}
        conn.execute(
            """
            INSERT INTO sources (
                id, name, source_type, connector_type, connector_version,
                schedule_expression, active, freshness_target_seconds,
                captured_bucket_seconds, configuration_json, last_attempt_at,
                last_success_at, last_error_at, consecutive_failures,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?)
            """,
            (
                DEFAULT_SOURCE_ID,
                "Fixture Source Default",
                "merchant_fixture",
                FIXTURE_CONNECTOR_TYPE,
                FIXTURE_CONNECTOR_VERSION,
                "every:60",
                1,
                120,
                DEFAULT_CAPTURED_BUCKET_SECONDS,
                stable_json(configuration),
                created_at,
                created_at,
            ),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM sources WHERE id=?", (DEFAULT_SOURCE_ID,)).fetchone()) or {}


def create_source(
    db_path: Path,
    *,
    source_id: str,
    name: str,
    schedule_expression: str = "every:60",
    active: bool = True,
    freshness_target_seconds: int = 120,
    captured_bucket_seconds: int = DEFAULT_CAPTURED_BUCKET_SECONDS,
    source_type: str = "merchant_fixture",
    connector_type: str = FIXTURE_CONNECTOR_TYPE,
    connector_version: str = FIXTURE_CONNECTOR_VERSION,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created_at = now_iso()
    config = {
        "fixture_name": source_id,
        "supported_scenarios": sorted(FIXTURE_SCENARIOS.keys()),
        "default_scenario": "success_alpha",
        "captured_bucket_seconds": captured_bucket_seconds,
    }
    if configuration:
        config.update(configuration)
    with connect_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (
                id, name, source_type, connector_type, connector_version,
                schedule_expression, active, freshness_target_seconds,
                captured_bucket_seconds, configuration_json, last_attempt_at,
                last_success_at, last_error_at, consecutive_failures,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?, ?)
            """,
            (
                source_id,
                name,
                source_type,
                connector_type,
                connector_version,
                schedule_expression,
                1 if active else 0,
                freshness_target_seconds,
                captured_bucket_seconds,
                stable_json(config),
                created_at,
                created_at,
            ),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()) or {}


class CollectionError(Exception):
    def __init__(self, code: str, message: str, retriable: bool = True):
        super().__init__(message)
        self.code = code
        self.retriable = retriable


class ConnectorContract:
    connector_name = ""
    connector_version = ""
    source_type = ""

    def validate_configuration(self, configuration: dict[str, Any]) -> None:
        raise NotImplementedError

    def collect(self, source: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def health_check(self, source: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class FixtureConnector(ConnectorContract):
    connector_name = FIXTURE_CONNECTOR_NAME
    connector_version = FIXTURE_CONNECTOR_VERSION
    source_type = "merchant_fixture"

    def validate_configuration(self, configuration: dict[str, Any]) -> None:
        bucket = int(configuration.get("captured_bucket_seconds") or DEFAULT_CAPTURED_BUCKET_SECONDS)
        if bucket <= 0:
            raise ValueError("fixture connector requires a positive captured_bucket_seconds")

    def collect(self, source: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        configuration = json_load(source.get("configuration_json"), {})
        job_payload = json_load(job.get("payload_json"), {})
        scenario = str(job_payload.get("scenario") or configuration.get("default_scenario") or "success_alpha")
        fixture = FIXTURE_SCENARIOS.get(scenario)
        if fixture is None:
            raise CollectionError("unknown_fixture_scenario", f"Unknown fixture scenario: {scenario}", retriable=False)
        delay_seconds = float(fixture.get("delay_seconds") or 0)
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        if fixture.get("raise_error"):
            raise CollectionError(
                str(fixture["raise_error"]["code"]),
                str(fixture["raise_error"]["message"]),
                bool(fixture["raise_error"].get("retriable", True)),
            )
        raw_payload = stable_json(fixture["payload"])
        return {
            "raw_payload": raw_payload,
            "content_type": "application/json",
            "captured_at": fixture["captured_at"],
            "evidence_url": fixture["evidence_url"],
            "metadata": {
                "row_count": int(fixture.get("row_count") or 0),
                "partial": bool(fixture.get("partial")),
                "scenario": scenario,
            },
        }

    def health_check(self, source: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "connector_name": self.connector_name,
            "connector_version": self.connector_version,
            "source_id": source.get("id"),
        }


FIXTURE_SCENARIOS: dict[str, dict[str, Any]] = {
    "success_alpha": {
        "captured_at": "2026-07-18T10:00:00+00:00",
        "evidence_url": "fixture://merchant/success_alpha",
        "row_count": 2,
        "payload": {
            "snapshot_id": "fixture-success-alpha",
            "items": [
                {"name": "compute board alpha", "sold_volume": 11, "avg_sale_price": 79.0},
                {"name": "iphone 13", "sold_volume": 27, "avg_sale_price": 321.0},
            ],
            "scenario": "success_alpha",
        },
    },
    "repeat_alpha": {
        "captured_at": "2026-07-18T10:00:00+00:00",
        "evidence_url": "fixture://merchant/success_alpha",
        "row_count": 2,
        "payload": {
            "snapshot_id": "fixture-success-alpha",
            "items": [
                {"name": "compute board alpha", "sold_volume": 11, "avg_sale_price": 79.0},
                {"name": "iphone 13", "sold_volume": 27, "avg_sale_price": 321.0},
            ],
            "scenario": "success_alpha",
        },
    },
    "change_bravo": {
        "captured_at": "2026-07-18T10:05:00+00:00",
        "evidence_url": "fixture://merchant/change_bravo",
        "row_count": 2,
        "payload": {
            "snapshot_id": "fixture-change-bravo",
            "items": [
                {"name": "compute board alpha", "sold_volume": 18, "avg_sale_price": 84.0},
                {"name": "iphone 13", "sold_volume": 22, "avg_sale_price": 315.0},
            ],
            "scenario": "change_bravo",
        },
    },
    "partial_gamma": {
        "captured_at": "2026-07-18T10:10:00+00:00",
        "evidence_url": "fixture://merchant/partial_gamma",
        "row_count": 1,
        "partial": True,
        "payload": {
            "snapshot_id": "fixture-partial-gamma",
            "items": [{"name": "compute board alpha", "sold_volume": 19, "avg_sale_price": 83.0}],
            "scenario": "partial_gamma",
            "note": "fixture partial payload",
        },
    },
    "delayed_delta": {
        "captured_at": "2026-07-18T10:15:00+00:00",
        "evidence_url": "fixture://merchant/delayed_delta",
        "row_count": 2,
        "delay_seconds": 0.25,
        "payload": {
            "snapshot_id": "fixture-delayed-delta",
            "items": [
                {"name": "compute board alpha", "sold_volume": 21, "avg_sale_price": 85.0},
                {"name": "iphone 13", "sold_volume": 24, "avg_sale_price": 319.0},
            ],
            "scenario": "delayed_delta",
        },
    },
    "failure_epsilon": {
        "raise_error": {
            "code": "fixture_failure",
            "message": "Deterministic fixture failure for retry and dead-letter tests.",
            "retriable": True,
        }
    },
    "stale_seed": {
        "captured_at": "2026-07-18T10:20:00+00:00",
        "evidence_url": "fixture://merchant/stale_seed",
        "row_count": 1,
        "payload": {
            "snapshot_id": "fixture-stale-seed",
            "items": [{"name": "compute board alpha", "sold_volume": 17, "avg_sale_price": 80.0}],
            "scenario": "stale_seed",
        },
    },
}


CONNECTORS: dict[str, ConnectorContract] = {
    FIXTURE_CONNECTOR_TYPE: FixtureConnector(),
}


def connector_for(source: dict[str, Any]) -> ConnectorContract:
    connector_type = str(source.get("connector_type") or "").strip()
    connector = CONNECTORS.get(connector_type)
    if connector is None:
        raise ValueError(f"Unknown connector_type: {connector_type}")
    connector.validate_configuration(json_load(source.get("configuration_json"), {}))
    return connector


def insert_source_health_event(
    conn: sqlite3.Connection,
    source_id: str,
    event_type: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_type not in SOURCE_EVENT_TYPES:
        raise ValueError(f"Unknown source health event type: {event_type}")
    event_id = make_id("SHE")
    created_at = now_iso()
    conn.execute(
        """
        INSERT INTO source_health_events (
            id, source_id, event_type, severity, message, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, source_id, event_type, severity, message, stable_json(details or {}), created_at),
    )
    return {
        "id": event_id,
        "source_id": source_id,
        "event_type": event_type,
        "severity": severity,
        "message": message,
        "details": details or {},
        "created_at": created_at,
    }


def source_by_id(conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if row is None:
        raise KeyError(f"source not found: {source_id}")
    return row_to_dict(row) or {}


def create_job(
    db_path: Path,
    source_id: str,
    scenario: str | None = None,
    *,
    scheduled_for: datetime | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    job_type: str = "source_ingest",
) -> dict[str, Any]:
    scheduled = scheduled_for or now_utc()
    payload = {"scenario": scenario} if scenario else {}
    job_id = make_id("JOB")
    idem = idempotency_key or f"{job_type}:{source_id}:{scheduled.isoformat()}:{scenario or 'default'}"
    created_at = now_iso()
    with connect_db(db_path) as conn:
        source = source_by_id(conn, source_id)
        connector_for(source)
        conn.execute(
            """
            INSERT INTO jobs (
                id, job_type, source_id, idempotency_key, scheduled_for, status,
                claimed_by, claimed_at, lease_expires_at, started_at, finished_at,
                attempts, max_attempts, next_retry_at, payload_json, last_error_code,
                last_error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', NULL, NULL, NULL, NULL, NULL, 0, ?, NULL, ?, NULL, NULL, ?, ?)
            """,
            (
                job_id,
                job_type,
                source_id,
                idem,
                now_iso(scheduled),
                max_attempts,
                stable_json(payload),
                created_at,
                created_at,
            ),
        )
        conn.commit()
        return get_job(db_path, job_id)


def acquire_scheduler_lease(
    db_path: Path,
    owner_id: str,
    *,
    lease_seconds: int = 5,
    now_value: datetime | None = None,
) -> bool:
    current = now_value or now_utc()
    expires = current + timedelta(seconds=lease_seconds)
    with connect_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM scheduler_leases WHERE lease_name=?", (LEASE_NAME,)).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO scheduler_leases (
                    lease_name, owner_id, acquired_at, renewed_at, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (LEASE_NAME, owner_id, now_iso(current), now_iso(current), now_iso(expires), now_iso(current), now_iso(current)),
            )
            conn.commit()
            return True
        row_dict = row_to_dict(row) or {}
        existing_owner = str(row_dict.get("owner_id") or "")
        existing_expires = parse_iso(row_dict.get("expires_at"))
        if existing_owner == owner_id or (existing_expires and existing_expires <= current):
            conn.execute(
                """
                UPDATE scheduler_leases
                SET owner_id=?, renewed_at=?, expires_at=?, updated_at=?,
                    acquired_at=CASE WHEN owner_id=? THEN acquired_at ELSE ? END
                WHERE lease_name=?
                """,
                (
                    owner_id,
                    now_iso(current),
                    now_iso(expires),
                    now_iso(current),
                    owner_id,
                    now_iso(current),
                    LEASE_NAME,
                ),
            )
            conn.commit()
            return True
        conn.commit()
        return False


def scheduler_status(db_path: Path, runtime: "RuntimeService | None" = None) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        lease = row_to_dict(conn.execute("SELECT * FROM scheduler_leases WHERE lease_name=?", (LEASE_NAME,)).fetchone())
    runtime_data = runtime.status_snapshot() if runtime else {}
    return {
        "lease": lease,
        "runtime": runtime_data.get("scheduler", {}),
    }


def worker_status(runtime: "RuntimeService | None" = None) -> dict[str, Any]:
    runtime_data = runtime.status_snapshot() if runtime else {}
    return runtime_data.get("worker", {})


def schedule_due_jobs(
    db_path: Path,
    *,
    now_value: datetime | None = None,
) -> list[dict[str, Any]]:
    current = now_value or now_utc()
    created: list[dict[str, Any]] = []
    with connect_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM sources WHERE active=1 ORDER BY id").fetchall()
        for row in rows:
            source = row_to_dict(row) or {}
            interval = schedule_every_seconds(str(source.get("schedule_expression") or ""))
            bucket = int(current.timestamp()) - (int(current.timestamp()) % interval)
            scheduled = datetime.fromtimestamp(bucket, tz=timezone.utc)
            idem = f"source_ingest:{source['id']}:{bucket}"
            existing = conn.execute("SELECT id FROM jobs WHERE idempotency_key=?", (idem,)).fetchone()
            if existing:
                continue
            job_id = make_id("JOB")
            created_at = now_iso(current)
            conn.execute(
                """
                INSERT INTO jobs (
                    id, job_type, source_id, idempotency_key, scheduled_for, status,
                    claimed_by, claimed_at, lease_expires_at, started_at, finished_at,
                    attempts, max_attempts, next_retry_at, payload_json, last_error_code,
                    last_error_message, created_at, updated_at
                ) VALUES (?, 'source_ingest', ?, ?, ?, 'queued', NULL, NULL, NULL, NULL, NULL, 0, 3, NULL, '{}', NULL, NULL, ?, ?)
                """,
                (job_id, source["id"], idem, now_iso(scheduled), created_at, created_at),
            )
            created.append({"id": job_id, "source_id": source["id"], "scheduled_for": now_iso(scheduled), "idempotency_key": idem})
        conn.commit()
    return created


def recover_expired_jobs(conn: sqlite3.Connection, now_value: datetime) -> int:
    rows = conn.execute(
        """
        SELECT * FROM jobs
        WHERE status IN ('claimed', 'running')
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at <= ?
        """,
        (now_iso(now_value),),
    ).fetchall()
    count = 0
    for row in rows:
        job = row_to_dict(row) or {}
        conn.execute(
            """
            UPDATE jobs
            SET status='queued',
                claimed_by=NULL,
                claimed_at=NULL,
                lease_expires_at=NULL,
                updated_at=?,
                last_error_code='lease_expired',
                last_error_message='Recovered after abandoned lease.'
            WHERE id=?
            """,
            (now_iso(now_value), job["id"]),
        )
        count += 1
    return count


def claim_next_job(
    db_path: Path,
    worker_id: str,
    *,
    lease_seconds: int = 10,
    now_value: datetime | None = None,
) -> dict[str, Any] | None:
    current = now_value or now_utc()
    expires = current + timedelta(seconds=lease_seconds)
    with connect_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        recover_expired_jobs(conn, current)
        row = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE
                (status='queued' AND scheduled_for <= ?)
                OR (status='retry_scheduled' AND next_retry_at IS NOT NULL AND next_retry_at <= ?)
            ORDER BY
                CASE status WHEN 'retry_scheduled' THEN 0 ELSE 1 END,
                COALESCE(next_retry_at, scheduled_for),
                created_at
            LIMIT 1
            """,
            (now_iso(current), now_iso(current)),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        updated = conn.execute(
            """
            UPDATE jobs
            SET status='claimed',
                claimed_by=?,
                claimed_at=?,
                lease_expires_at=?,
                updated_at=?
            WHERE id=?
              AND ((status='queued' AND scheduled_for <= ?)
                   OR (status='retry_scheduled' AND next_retry_at IS NOT NULL AND next_retry_at <= ?))
            """,
            (
                worker_id,
                now_iso(current),
                now_iso(expires),
                now_iso(current),
                row["id"],
                now_iso(current),
                now_iso(current),
            ),
        ).rowcount
        if updated != 1:
            conn.rollback()
            return None
        claimed = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        conn.commit()
        return row_to_dict(claimed)


def create_ingest_run(
    conn: sqlite3.Connection,
    *,
    job: dict[str, Any],
    source: dict[str, Any],
    connector: ConnectorContract,
    started_at: datetime,
) -> dict[str, Any]:
    run_id = make_id("RUN")
    conn.execute(
        """
        INSERT INTO ingest_runs (
            id, job_id, source_id, connector_name, connector_version,
            started_at, finished_at, status, row_count, payload_hash,
            error_code, error_message, retry_number, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, 'running', 0, NULL, NULL, NULL, ?, ?)
        """,
        (
            run_id,
            job["id"],
            source["id"],
            connector.connector_name,
            connector.connector_version,
            now_iso(started_at),
            int(job.get("attempts") or 0),
            now_iso(started_at),
        ),
    )
    return row_to_dict(conn.execute("SELECT * FROM ingest_runs WHERE id=?", (run_id,)).fetchone()) or {}


def bounded_retry_time(attempts: int, base_time: datetime) -> datetime:
    index = max(0, min(attempts - 1, len(DEFAULT_RETRY_DELAYS_SECONDS) - 1))
    return base_time + timedelta(seconds=DEFAULT_RETRY_DELAYS_SECONDS[index])


def process_claimed_job(
    db_path: Path,
    job: dict[str, Any],
    worker_id: str,
    *,
    now_value: datetime | None = None,
) -> dict[str, Any]:
    started = now_value or now_utc()
    with connect_db(db_path) as conn:
        source = source_by_id(conn, str(job["source_id"]))
        connector = connector_for(source)
        attempts = int(job.get("attempts") or 0) + 1
        conn.execute(
            """
            UPDATE jobs
            SET status='running',
                started_at=COALESCE(started_at, ?),
                attempts=?,
                lease_expires_at=?,
                updated_at=?
            WHERE id=? AND status='claimed' AND claimed_by=?
            """,
            (
                now_iso(started),
                attempts,
                now_iso(started + timedelta(seconds=10)),
                now_iso(started),
                job["id"],
                worker_id,
            ),
        )
        job = row_to_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()) or {}
        run = create_ingest_run(conn, job=job, source=source, connector=connector, started_at=started)
        conn.commit()
    try:
        result = connector.collect(source, job)
    except CollectionError as exc:
        finished = now_utc()
        with connect_db(db_path) as conn:
            next_retry = None
            next_status = "dead_letter" if attempts >= int(job.get("max_attempts") or 3) or not exc.retriable else "retry_scheduled"
            if next_status == "retry_scheduled":
                next_retry = bounded_retry_time(attempts, finished)
            conn.execute(
                """
                UPDATE ingest_runs
                SET finished_at=?, status='failed', row_count=0, payload_hash=NULL,
                    error_code=?, error_message=?
                WHERE id=?
                """,
                (now_iso(finished), exc.code, str(exc), run["id"]),
            )
            conn.execute(
                """
                UPDATE jobs
                SET status=?,
                    finished_at=?,
                    next_retry_at=?,
                    lease_expires_at=NULL,
                    last_error_code=?,
                    last_error_message=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    next_status,
                    now_iso(finished) if next_status == "dead_letter" else None,
                    now_iso(next_retry) if next_retry else None,
                    exc.code,
                    str(exc),
                    now_iso(finished),
                    job["id"],
                ),
            )
            conn.execute(
                """
                UPDATE sources
                SET last_attempt_at=?, last_error_at=?, consecutive_failures=consecutive_failures + 1, updated_at=?
                WHERE id=?
                """,
                (now_iso(finished), now_iso(finished), now_iso(finished), source["id"]),
            )
            insert_source_health_event(
                conn,
                source["id"],
                "source_failure",
                "critical" if next_status == "dead_letter" else "warning",
                f"Collection failed for source {source['id']}: {exc}",
                {"job_id": job["id"], "ingest_run_id": run["id"], "status": next_status, "error_code": exc.code},
            )
            conn.commit()
        return {
            "job_id": job["id"],
            "ingest_run_id": run["id"],
            "status": next_status,
            "error_code": exc.code,
            "error_message": str(exc),
        }
    finished = now_utc()
    raw_payload = str(result["raw_payload"])
    captured_at = parse_iso(str(result["captured_at"]))
    if captured_at is None:
        raise ValueError("connector returned invalid captured_at")
    snapshot_hash = payload_hash(raw_payload)
    bucket_seconds = int(source.get("captured_bucket_seconds") or DEFAULT_CAPTURED_BUCKET_SECONDS)
    captured_bucket = time_bucket(captured_at, bucket_seconds)
    row_count = int(((result.get("metadata") or {}).get("row_count")) or 0)
    is_partial = bool((result.get("metadata") or {}).get("partial"))
    outcome_status = "partial" if is_partial else "succeeded"
    snapshot_id = make_id("RAW")
    duplicate = False
    with connect_db(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO raw_snapshots (
                    id, source_id, ingest_run_id, captured_at, captured_bucket,
                    payload_hash, content_type, raw_payload, evidence_url,
                    connector_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    source["id"],
                    run["id"],
                    now_iso(captured_at),
                    captured_bucket,
                    snapshot_hash,
                    str(result["content_type"]),
                    raw_payload,
                    result.get("evidence_url"),
                    connector.connector_version,
                    now_iso(finished),
                ),
            )
        except sqlite3.IntegrityError:
            duplicate = True
            outcome_status = "skipped_duplicate"
            snapshot_id = ""
        conn.execute(
            """
            UPDATE ingest_runs
            SET finished_at=?, status=?, row_count=?, payload_hash=?, error_code=NULL, error_message=NULL
            WHERE id=?
            """,
            (now_iso(finished), outcome_status, row_count, snapshot_hash, run["id"]),
        )
        conn.execute(
            """
            UPDATE jobs
            SET status=?,
                finished_at=?,
                next_retry_at=NULL,
                lease_expires_at=NULL,
                last_error_code=NULL,
                last_error_message=NULL,
                updated_at=?
            WHERE id=?
            """,
            (outcome_status, now_iso(finished), now_iso(finished), job["id"]),
        )
        conn.execute(
            """
            UPDATE sources
            SET last_attempt_at=?, last_success_at=?, last_error_at=NULL,
                consecutive_failures=0, updated_at=?
            WHERE id=?
            """,
            (now_iso(finished), now_iso(finished), now_iso(finished), source["id"]),
        )
        if duplicate:
            insert_source_health_event(
                conn,
                source["id"],
                "source_recovered",
                "info",
                f"Duplicate payload detected for source {source['id']}; raw snapshot not duplicated.",
                {"job_id": job["id"], "ingest_run_id": run["id"], "payload_hash": snapshot_hash},
            )
        conn.commit()
    return {
        "job_id": job["id"],
        "ingest_run_id": run["id"],
        "raw_snapshot_id": snapshot_id or None,
        "status": outcome_status,
        "payload_hash": snapshot_hash,
        "duplicate": duplicate,
    }


def refresh_stale_sources(
    db_path: Path,
    *,
    now_value: datetime | None = None,
) -> list[dict[str, Any]]:
    current = now_value or now_utc()
    events: list[dict[str, Any]] = []
    with connect_db(db_path) as conn:
        rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
        for row in rows:
            source = row_to_dict(row) or {}
            health = compute_source_health(conn, source, now_value=current)
            if health["status"] != "stale":
                continue
            latest_event = conn.execute(
                """
                SELECT created_at
                FROM source_health_events
                WHERE source_id=? AND event_type='source_stale'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (source["id"],),
            ).fetchone()
            last_success = parse_iso(source.get("last_success_at"))
            latest_event_at = parse_iso(latest_event["created_at"]) if latest_event else None
            if latest_event_at and last_success and latest_event_at >= last_success:
                continue
            events.append(
                insert_source_health_event(
                    conn,
                    source["id"],
                    "source_stale",
                    "warning",
                    f"Source {source['id']} is stale.",
                    {
                        "current_age_seconds": health["current_age_seconds"],
                        "freshness_target_seconds": source["freshness_target_seconds"],
                    },
                )
            )
        conn.commit()
    return events


def compute_source_health(
    conn: sqlite3.Connection,
    source: dict[str, Any],
    *,
    now_value: datetime | None = None,
) -> dict[str, Any]:
    current = now_value or now_utc()
    last_attempt = parse_iso(source.get("last_attempt_at"))
    last_success = parse_iso(source.get("last_success_at"))
    last_error = parse_iso(source.get("last_error_at"))
    age_from = last_success or last_attempt
    current_age_seconds = int((current - age_from).total_seconds()) if age_from else None
    freshness_target = int(source.get("freshness_target_seconds") or 0)
    latest_run = row_to_dict(
        conn.execute(
            "SELECT * FROM ingest_runs WHERE source_id=? ORDER BY started_at DESC LIMIT 1",
            (source["id"],),
        ).fetchone()
    )
    counts = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued_jobs,
            SUM(CASE WHEN status IN ('claimed', 'running') THEN 1 ELSE 0 END) AS running_jobs,
            SUM(CASE WHEN status='dead_letter' THEN 1 ELSE 0 END) AS dead_letter_jobs
        FROM jobs
        WHERE source_id=?
        """,
        (source["id"],),
    ).fetchone()
    latest_payload_hash = latest_run["payload_hash"] if latest_run else None
    latest_row_count = latest_run["row_count"] if latest_run else 0
    stale = bool(current_age_seconds is not None and freshness_target > 0 and current_age_seconds > freshness_target)
    if not last_attempt:
        status = "never_run"
    elif int(source.get("consecutive_failures") or 0) > 0 or (latest_run and latest_run["status"] in {"failed", "retry_scheduled", "dead_letter"}):
        status = "failed"
    elif stale:
        status = "stale"
    else:
        status = "healthy"
    return {
        "source_id": source["id"],
        "active": bool(source.get("active")),
        "status": status,
        "last_attempt_at": source.get("last_attempt_at"),
        "last_success_at": source.get("last_success_at"),
        "last_error_at": source.get("last_error_at"),
        "consecutive_failures": int(source.get("consecutive_failures") or 0),
        "freshness_target_seconds": freshness_target,
        "current_age_seconds": current_age_seconds,
        "stale": stale,
        "latest_ingest_status": latest_run["status"] if latest_run else None,
        "latest_row_count": int(latest_row_count or 0),
        "latest_payload_hash": latest_payload_hash,
        "queued_jobs": int(counts["queued_jobs"] or 0),
        "running_jobs": int(counts["running_jobs"] or 0),
        "dead_letter_jobs": int(counts["dead_letter_jobs"] or 0),
        "latest_ingest_run_id": latest_run["id"] if latest_run else None,
        "latest_ingest_started_at": latest_run["started_at"] if latest_run else None,
        "latest_ingest_finished_at": latest_run["finished_at"] if latest_run else None,
    }


def list_sources(db_path: Path) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        rows = [row_to_dict(row) or {} for row in conn.execute("SELECT * FROM sources ORDER BY created_at, id").fetchall()]
    return {"sources": rows, "count": len(rows)}


def get_source(db_path: Path, source_id: str) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        return source_by_id(conn, source_id)


def read_source_health(db_path: Path, source_id: str, runtime: "RuntimeService | None" = None) -> dict[str, Any]:
    refresh_stale_sources(db_path)
    with connect_db(db_path) as conn:
        source = source_by_id(conn, source_id)
        health = compute_source_health(conn, source)
        recent_events = [
            {**(row_to_dict(row) or {}), "details": json_load(row["details_json"], {})}
            for row in conn.execute(
                "SELECT * FROM source_health_events WHERE source_id=? ORDER BY created_at DESC LIMIT 10",
                (source_id,),
            ).fetchall()
        ]
    health["recent_events"] = recent_events
    health["scheduler"] = scheduler_status(db_path, runtime)
    health["worker"] = worker_status(runtime)
    return health


def list_source_health(db_path: Path, runtime: "RuntimeService | None" = None) -> dict[str, Any]:
    refresh_stale_sources(db_path)
    with connect_db(db_path) as conn:
        rows = [row_to_dict(row) or {} for row in conn.execute("SELECT * FROM sources ORDER BY id").fetchall()]
        health_rows = [compute_source_health(conn, row) for row in rows]
    return {
        "sources": health_rows,
        "count": len(health_rows),
        "scheduler": scheduler_status(db_path, runtime),
        "worker": worker_status(runtime),
    }


def list_jobs(db_path: Path, limit: int = 50) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        rows = [
            {**(row_to_dict(row) or {}), "payload": json_load(row["payload_json"], {})}
            for row in conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
    return {"jobs": rows, "count": len(rows)}


def get_job(db_path: Path, job_id: str) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        data = row_to_dict(row) or {}
    data["payload"] = json_load(data.get("payload_json"), {})
    return data


def list_ingest_runs(db_path: Path, limit: int = 50) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        rows = [
            row_to_dict(row) or {}
            for row in conn.execute(
                "SELECT * FROM ingest_runs ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
    return {"ingest_runs": rows, "count": len(rows)}


def get_ingest_run(db_path: Path, ingest_run_id: str) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT * FROM ingest_runs WHERE id=?", (ingest_run_id,)).fetchone()
        if row is None:
            raise KeyError(f"ingest run not found: {ingest_run_id}")
        return row_to_dict(row) or {}


def _snapshot_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": snapshot["id"],
        "source_id": snapshot["source_id"],
        "ingest_run_id": snapshot["ingest_run_id"],
        "captured_at": snapshot["captured_at"],
        "captured_bucket": snapshot["captured_bucket"],
        "payload_hash": snapshot["payload_hash"],
        "content_type": snapshot["content_type"],
        "evidence_url": snapshot["evidence_url"],
        "connector_version": snapshot["connector_version"],
        "created_at": snapshot["created_at"],
        "raw_payload_bytes": len(str(snapshot["raw_payload"]).encode("utf-8")),
    }


def list_raw_snapshot_metadata(db_path: Path, limit: int = 50) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        rows = [
            _snapshot_metadata(row_to_dict(row) or {})
            for row in conn.execute(
                "SELECT * FROM raw_snapshots ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
    return {"raw_snapshots": rows, "count": len(rows)}


def get_raw_snapshot_metadata(db_path: Path, snapshot_id: str) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT * FROM raw_snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(f"raw snapshot not found: {snapshot_id}")
        return _snapshot_metadata(row_to_dict(row) or {})


def read_raw_snapshot_payload(db_path: Path, snapshot_id: str) -> str:
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT raw_payload FROM raw_snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(f"raw snapshot not found: {snapshot_id}")
        return str(row["raw_payload"])


def attempt_raw_snapshot_update(*_args: Any, **_kwargs: Any) -> None:
    raise PermissionError("raw snapshots are immutable and cannot be updated through the application layer")


@dataclass
class RuntimeState:
    started_at: str
    scheduler_owner_id: str
    worker_id: str
    scheduler_last_heartbeat_at: str | None = None
    worker_last_heartbeat_at: str | None = None
    scheduler_is_leader: bool = False
    worker_current_job_id: str | None = None
    worker_last_result: dict[str, Any] | None = None


class RuntimeService:
    def __init__(
        self,
        db_path: Path,
        *,
        scheduler_poll_seconds: float = 1.0,
        worker_poll_seconds: float = 0.5,
        lease_seconds: int = 5,
    ) -> None:
        self.db_path = Path(db_path)
        self.scheduler_poll_seconds = scheduler_poll_seconds
        self.worker_poll_seconds = worker_poll_seconds
        self.lease_seconds = lease_seconds
        self.scheduler_owner_id = f"scheduler-{uuid.uuid4().hex[:8]}"
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self.state = RuntimeState(
            started_at=now_iso(),
            scheduler_owner_id=self.scheduler_owner_id,
            worker_id=self.worker_id,
        )
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self._stop_event.clear()
        self._threads = [
            threading.Thread(target=self._scheduler_loop, name="data-plane-scheduler", daemon=True),
            threading.Thread(target=self._worker_loop, name="data-plane-worker", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads = []

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "started_at": self.state.started_at,
                "scheduler": {
                    "owner_id": self.state.scheduler_owner_id,
                    "last_heartbeat_at": self.state.scheduler_last_heartbeat_at,
                    "is_leader": self.state.scheduler_is_leader,
                    "alive": self._is_recent(self.state.scheduler_last_heartbeat_at, threshold_seconds=10),
                },
                "worker": {
                    "worker_id": self.state.worker_id,
                    "last_heartbeat_at": self.state.worker_last_heartbeat_at,
                    "alive": self._is_recent(self.state.worker_last_heartbeat_at, threshold_seconds=10),
                    "current_job_id": self.state.worker_current_job_id,
                    "last_result": self.state.worker_last_result,
                },
            }

    def _is_recent(self, value: str | None, *, threshold_seconds: int) -> bool:
        parsed = parse_iso(value)
        if parsed is None:
            return False
        return (now_utc() - parsed).total_seconds() <= threshold_seconds

    def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            current = now_utc()
            leader = acquire_scheduler_lease(self.db_path, self.scheduler_owner_id, lease_seconds=self.lease_seconds, now_value=current)
            with self._lock:
                self.state.scheduler_last_heartbeat_at = now_iso(current)
                self.state.scheduler_is_leader = leader
            if leader:
                schedule_due_jobs(self.db_path, now_value=current)
                refresh_stale_sources(self.db_path, now_value=current)
            self._stop_event.wait(self.scheduler_poll_seconds)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            current = now_utc()
            with self._lock:
                self.state.worker_last_heartbeat_at = now_iso(current)
            job = claim_next_job(self.db_path, self.worker_id, now_value=current)
            if job is None:
                with self._lock:
                    self.state.worker_current_job_id = None
                self._stop_event.wait(self.worker_poll_seconds)
                continue
            with self._lock:
                self.state.worker_current_job_id = job["id"]
            result = process_claimed_job(self.db_path, job, self.worker_id)
            with self._lock:
                self.state.worker_last_result = result
                self.state.worker_current_job_id = None
            self._stop_event.wait(0.01)


def build_milestone_1_proof(
    db_path: Path,
    *,
    runtime: RuntimeService | None = None,
    poll_timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    apply_migrations(db_path)
    ensure_default_fixture_source(db_path)
    local_runtime = runtime or RuntimeService(db_path, scheduler_poll_seconds=0.2, worker_poll_seconds=0.1, lease_seconds=2)
    started_here = runtime is None
    if started_here:
        local_runtime.start()

    def wait_for(predicate, timeout: float = poll_timeout_seconds) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    results: list[dict[str, Any]] = []

    def check(name: str, ok: bool, evidence: dict[str, Any]) -> None:
        results.append({"name": name, "ok": ok, "evidence": evidence})

    scheduler_job_ready = wait_for(lambda: list_jobs(db_path)["count"] >= 1)
    check("scheduled_job_created", scheduler_job_ready, list_jobs(db_path))

    manual_duplicate = create_job(
        db_path,
        DEFAULT_SOURCE_ID,
        "repeat_alpha",
        scheduled_for=now_utc(),
        idempotency_key=f"proof:{DEFAULT_SOURCE_ID}:repeat:{uuid.uuid4().hex[:8]}",
    )
    manual_change = create_job(
        db_path,
        DEFAULT_SOURCE_ID,
        "change_bravo",
        scheduled_for=now_utc(),
        idempotency_key=f"proof:{DEFAULT_SOURCE_ID}:change:{uuid.uuid4().hex[:8]}",
    )
    manual_failure = create_job(
        db_path,
        DEFAULT_SOURCE_ID,
        "failure_epsilon",
        scheduled_for=now_utc(),
        idempotency_key=f"proof:{DEFAULT_SOURCE_ID}:failure:{uuid.uuid4().hex[:8]}",
        max_attempts=2,
    )

    wait_for(lambda: get_job(db_path, manual_duplicate["id"])["status"] in {"skipped_duplicate", "succeeded", "partial"})
    wait_for(lambda: get_job(db_path, manual_change["id"])["status"] in {"succeeded", "partial"})
    wait_for(lambda: get_job(db_path, manual_failure["id"])["status"] == "dead_letter")
    time.sleep(2.2)
    refresh_stale_sources(db_path)

    jobs = list_jobs(db_path)["jobs"]
    runs = list_ingest_runs(db_path)["ingest_runs"]
    snapshots = list_raw_snapshot_metadata(db_path)["raw_snapshots"]
    health = read_source_health(db_path, DEFAULT_SOURCE_ID, local_runtime)

    check("worker_claimed_and_processed_jobs", any(job["status"] in {"succeeded", "skipped_duplicate", "dead_letter"} for job in jobs), {"jobs": jobs})
    check("duplicate_replay_auditable", any(run["status"] == "skipped_duplicate" for run in runs), {"runs": runs})
    check("changed_snapshot_created", len(snapshots) >= 2, {"raw_snapshots": snapshots})
    check("failed_pull_retried_then_dead_lettered", any(job["status"] == "dead_letter" for job in jobs), {"jobs": jobs})
    check("source_health_updated", health["status"] in {"healthy", "stale", "failed"}, {"health": health})
    check(
        "source_health_events_exist",
        bool(health.get("recent_events")),
        {"recent_events": health.get("recent_events")},
    )

    passed = sum(1 for item in results if item["ok"])
    proof = {
        "generated_at": now_iso(),
        "db_path": str(db_path),
        "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results)},
        "results": results,
        "status": "pass" if passed == len(results) else "fail",
    }
    if started_here:
        local_runtime.stop()
    return proof
