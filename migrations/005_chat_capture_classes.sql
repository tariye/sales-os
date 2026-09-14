PRAGMA foreign_keys = OFF;

BEGIN IMMEDIATE;

CREATE TABLE core_captures_expanded (
    capture_id TEXT PRIMARY KEY,
    capture_type TEXT NOT NULL CHECK (capture_type IN (
        'begin_day_checklist', 'end_of_day_report', 'voice_debrief',
        'user_note', 'user_report', 'decision_note', 'project_update',
        'research_note', 'assistant_report'
    )),
    source TEXT NOT NULL,
    conversation_id TEXT,
    message_id TEXT,
    request_id TEXT NOT NULL,
    correlation_id TEXT,
    idempotency_key TEXT NOT NULL,
    payload_version INTEGER NOT NULL DEFAULT 1,
    raw_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    occurred_at TEXT,
    occurred_precision TEXT NOT NULL DEFAULT 'unknown'
        CHECK (occurred_precision IN ('unknown', 'date', 'datetime')),
    captured_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    processing_state TEXT NOT NULL DEFAULT 'queued'
        CHECK (processing_state IN ('queued', 'processing', 'processed', 'failed')),
    processed_at TEXT,
    process_operation_id TEXT REFERENCES core_operations(operation_id) ON DELETE SET NULL,
    supersedes_capture_id TEXT REFERENCES core_captures_expanded(capture_id) ON DELETE SET NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source, idempotency_key)
);

INSERT INTO core_captures_expanded (
    capture_id, capture_type, source, conversation_id, message_id,
    request_id, correlation_id, idempotency_key, payload_version,
    raw_text, content_hash, occurred_at, occurred_precision,
    captured_at, ingested_at, processing_state, processed_at,
    process_operation_id, supersedes_capture_id, metadata_json,
    created_at, updated_at
)
SELECT capture_id, capture_type, source, conversation_id, message_id,
       request_id, correlation_id, idempotency_key, payload_version,
       raw_text, content_hash, occurred_at, occurred_precision,
       captured_at, ingested_at, processing_state, processed_at,
       process_operation_id, supersedes_capture_id, metadata_json,
       created_at, updated_at
FROM core_captures;

CREATE TABLE core_day_cases_expanded (
    day_case_id TEXT PRIMARY KEY,
    owner_system_id TEXT NOT NULL REFERENCES core_systems(system_id) ON DELETE RESTRICT,
    local_date TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'archived')),
    summary TEXT,
    plan_capture_id TEXT REFERENCES core_captures_expanded(capture_id) ON DELETE SET NULL,
    report_capture_id TEXT REFERENCES core_captures_expanded(capture_id) ON DELETE SET NULL,
    progress_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(progress_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (owner_system_id, local_date)
);

INSERT INTO core_day_cases_expanded
SELECT * FROM core_day_cases;

CREATE TABLE core_capture_derivations_expanded (
    derivation_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL REFERENCES core_captures_expanded(capture_id) ON DELETE CASCADE,
    day_case_id TEXT REFERENCES core_day_cases_expanded(day_case_id) ON DELETE SET NULL,
    derived_namespace TEXT NOT NULL,
    derived_record_type TEXT NOT NULL,
    derived_record_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (capture_id, derived_namespace, derived_record_type, derived_record_id, relationship)
);

INSERT INTO core_capture_derivations_expanded
SELECT * FROM core_capture_derivations;

DROP TABLE core_capture_derivations;
DROP TABLE core_day_cases;
DROP TABLE core_captures;
ALTER TABLE core_captures_expanded RENAME TO core_captures;
ALTER TABLE core_day_cases_expanded RENAME TO core_day_cases;
ALTER TABLE core_capture_derivations_expanded RENAME TO core_capture_derivations;

CREATE INDEX IF NOT EXISTS idx_core_captures_type_created
    ON core_captures(capture_type, created_at);
CREATE INDEX IF NOT EXISTS idx_core_captures_processing
    ON core_captures(processing_state, updated_at);
CREATE INDEX IF NOT EXISTS idx_core_captures_idempotency
    ON core_captures(source, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_core_day_cases_date
    ON core_day_cases(owner_system_id, local_date);
CREATE INDEX IF NOT EXISTS idx_core_capture_derivations_capture
    ON core_capture_derivations(capture_id, created_at);
CREATE INDEX IF NOT EXISTS idx_core_capture_derivations_derived
    ON core_capture_derivations(derived_namespace, derived_record_type, derived_record_id);

INSERT INTO schema_migrations (version, name)
VALUES (5, 'chat_capture_classes');

COMMIT;

PRAGMA foreign_keys = ON;
