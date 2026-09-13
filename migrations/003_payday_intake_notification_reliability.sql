PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS core_operations (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    source_system_id TEXT REFERENCES core_systems(system_id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'pending_reconciliation')),
    subject_namespace TEXT,
    subject_type TEXT,
    subject_id TEXT,
    request_hash TEXT,
    result_namespace TEXT,
    result_type TEXT,
    result_id TEXT,
    result_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(result_json)),
    error_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(error_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT,
    UNIQUE (operation_type, operation_key)
);

CREATE TABLE IF NOT EXISTS core_operation_attempts (
    attempt_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES core_operations(operation_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    status TEXT NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'succeeded', 'failed', 'abandoned', 'unknown')),
    worker_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    lease_started_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    heartbeat_at TEXT,
    reclaimed_at TEXT,
    retry_after TEXT,
    error_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(error_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (operation_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS core_source_observations (
    observation_id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL REFERENCES core_systems(system_id) ON DELETE RESTRICT,
    source_connection_id TEXT NOT NULL,
    account_external_id TEXT NOT NULL,
    source_name TEXT,
    observation_type TEXT NOT NULL,
    source_transaction_id TEXT,
    provider_transaction_id TEXT,
    provider_pending_id TEXT,
    provider_posted_id TEXT,
    economic_inflow_key TEXT NOT NULL,
    observation_status TEXT NOT NULL
        CHECK (observation_status IN ('pending', 'posted', 'removed', 'unknown')),
    amount_cents INTEGER CHECK (amount_cents IS NULL OR amount_cents >= 0),
    currency TEXT,
    account_name TEXT,
    classification TEXT,
    classification_confidence REAL
        CHECK (classification_confidence IS NULL OR
               (classification_confidence >= 0.0 AND classification_confidence <= 1.0)),
    observed_at TEXT NOT NULL,
    effective_date TEXT,
    posted_at TEXT,
    source_modified_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    supersedes_observation_id TEXT REFERENCES core_source_observations(observation_id) ON DELETE SET NULL,
    pending_observation_id TEXT REFERENCES core_source_observations(observation_id) ON DELETE SET NULL,
    posted_observation_id TEXT REFERENCES core_source_observations(observation_id) ON DELETE SET NULL,
    dedupe_state TEXT NOT NULL DEFAULT 'new'
        CHECK (dedupe_state IN ('new', 'duplicate', 'updated', 'superseded', 'conflict')),
    match_state TEXT NOT NULL DEFAULT 'unmatched'
        CHECK (match_state IN ('unmatched', 'probable_match', 'confirmed_match', 'conflict')),
    operation_id TEXT REFERENCES core_operations(operation_id) ON DELETE SET NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_ingestion_results (
    ingestion_result_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES core_operations(operation_id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES core_operation_attempts(attempt_id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL REFERENCES core_source_observations(observation_id) ON DELETE CASCADE,
    event_id TEXT REFERENCES core_events(event_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    effects_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(effects_json)),
    error_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(error_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_notification_requests (
    notification_request_id TEXT PRIMARY KEY,
    operation_id TEXT REFERENCES core_operations(operation_id) ON DELETE SET NULL,
    alert_id TEXT NOT NULL REFERENCES core_alerts(alert_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'alert_delivery',
    status TEXT NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'cancelled', 'superseded')),
    requested_at TEXT NOT NULL,
    requested_by TEXT NOT NULL DEFAULT 'system',
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_notification_delivery_results (
    delivery_result_id TEXT PRIMARY KEY,
    notification_request_id TEXT NOT NULL REFERENCES core_notification_requests(notification_request_id) ON DELETE CASCADE,
    alert_id TEXT NOT NULL REFERENCES core_alerts(alert_id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES core_operation_attempts(attempt_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    provider_status TEXT NOT NULL
        CHECK (provider_status IN ('not_attempted', 'submitted', 'provider_accepted', 'delivered', 'failed', 'unknown')),
    attempted_at TEXT NOT NULL,
    provider_accepted_at TEXT,
    delivered_at TEXT,
    failed_at TEXT,
    external_delivery_ref TEXT,
    trusted_evidence_type TEXT,
    trusted_evidence_ref TEXT,
    evidence_recorded_at TEXT,
    provider_response_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(provider_response_json)),
    error_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(error_json)),
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        provider_status != 'delivered'
        OR (
            delivered_at IS NOT NULL
            AND trusted_evidence_type IS NOT NULL
            AND trusted_evidence_ref IS NOT NULL
            AND evidence_recorded_at IS NOT NULL
        )
    )
);

CREATE TABLE IF NOT EXISTS core_alert_presentations (
    presentation_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES core_alerts(alert_id) ON DELETE CASCADE,
    delivery_result_id TEXT REFERENCES core_notification_delivery_results(delivery_result_id) ON DELETE SET NULL,
    presented_at TEXT NOT NULL,
    presented_by TEXT NOT NULL,
    presentation_surface TEXT NOT NULL,
    session_ref TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_alert_acknowledgments (
    acknowledgment_id TEXT PRIMARY KEY,
    alert_id TEXT NOT NULL REFERENCES core_alerts(alert_id) ON DELETE CASCADE,
    decision_id TEXT REFERENCES core_decisions(decision_id) ON DELETE SET NULL,
    acknowledged_at TEXT NOT NULL,
    acknowledged_by TEXT NOT NULL,
    auth_context TEXT NOT NULL,
    trust_level TEXT NOT NULL DEFAULT 'authenticated_service'
        CHECK (trust_level IN ('authenticated_service', 'untrusted_metadata')),
    response TEXT,
    same_case_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_core_operations_key
    ON core_operations(operation_type, operation_key);
CREATE INDEX IF NOT EXISTS idx_core_operations_status
    ON core_operations(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_core_operation_attempts_operation
    ON core_operation_attempts(operation_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_core_operation_attempts_lease
    ON core_operation_attempts(status, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_core_source_observations_source_txn
    ON core_source_observations(source_system_id, source_connection_id, account_external_id, source_transaction_id);
CREATE INDEX IF NOT EXISTS idx_core_source_observations_economic
    ON core_source_observations(source_system_id, source_connection_id, account_external_id, economic_inflow_key, observed_at);
CREATE INDEX IF NOT EXISTS idx_core_source_observations_status
    ON core_source_observations(source_system_id, observation_status, observed_at);
CREATE INDEX IF NOT EXISTS idx_core_ingestion_results_observation
    ON core_ingestion_results(observation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_core_notification_requests_alert
    ON core_notification_requests(alert_id, requested_at);
CREATE INDEX IF NOT EXISTS idx_core_notification_delivery_results_alert
    ON core_notification_delivery_results(alert_id, attempted_at);
CREATE INDEX IF NOT EXISTS idx_core_alert_presentations_alert
    ON core_alert_presentations(alert_id, presented_at);
CREATE INDEX IF NOT EXISTS idx_core_alert_acknowledgments_alert
    ON core_alert_acknowledgments(alert_id, acknowledged_at);

INSERT OR IGNORE INTO schema_migrations (version, name)
VALUES (3, 'payday_intake_notification_reliability');

COMMIT;
