PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_systems (
    system_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('planned', 'active', 'paused', 'retired')),
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    name TEXT NOT NULL,
    source_system_id TEXT REFERENCES core_systems(system_id) ON DELETE SET NULL,
    external_key TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive', 'archived')),
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_system_id, entity_type, external_key)
);

CREATE TABLE IF NOT EXISTS core_goals (
    goal_id TEXT PRIMARY KEY,
    owner_system_id TEXT REFERENCES core_systems(system_id) ON DELETE SET NULL,
    parent_goal_id TEXT REFERENCES core_goals(goal_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('draft', 'active', 'paused', 'achieved', 'abandoned')),
    priority TEXT NOT NULL DEFAULT 'P1'
        CHECK (priority IN ('P0', 'P1', 'P2')),
    target_metric TEXT,
    target_value REAL,
    current_value REAL,
    unit TEXT,
    target_date TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_events (
    event_id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL
        REFERENCES core_systems(system_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    entity_id TEXT REFERENCES core_entities(entity_id) ON DELETE SET NULL,
    occurred_at TEXT NOT NULL,
    observed_at TEXT,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    dedupe_key TEXT,
    source_ref TEXT,
    correlation_id TEXT,
    causation_event_id TEXT REFERENCES core_events(event_id) ON DELETE SET NULL,
    priority TEXT NOT NULL DEFAULT 'P2'
        CHECK (priority IN ('P0', 'P1', 'P2')),
    confidence REAL NOT NULL DEFAULT 1.0
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    processing_status TEXT NOT NULL DEFAULT 'new'
        CHECK (processing_status IN ('new', 'processing', 'processed', 'ignored', 'failed')),
    payload_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(payload_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_system_id, dedupe_key)
);

CREATE TABLE IF NOT EXISTS core_signals (
    signal_id TEXT PRIMARY KEY,
    owner_system_id TEXT NOT NULL
        REFERENCES core_systems(system_id) ON DELETE RESTRICT,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    priority TEXT NOT NULL
        CHECK (priority IN ('P0', 'P1', 'P2')),
    confidence REAL NOT NULL DEFAULT 1.0
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    actionability_score REAL
        CHECK (actionability_score IS NULL OR
               (actionability_score >= 0.0 AND actionability_score <= 1.0)),
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN (
            'new', 'acknowledged', 'snoozed', 'dismissed',
            'converted', 'resolved', 'expired'
        )),
    rationale TEXT,
    recommended_action TEXT,
    detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_signal_events (
    signal_id TEXT NOT NULL REFERENCES core_signals(signal_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES core_events(event_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL DEFAULT 'evidence'
        CHECK (relationship IN ('trigger', 'evidence', 'context', 'contradiction')),
    PRIMARY KEY (signal_id, event_id, relationship)
);

CREATE TABLE IF NOT EXISTS core_signal_goals (
    signal_id TEXT NOT NULL REFERENCES core_signals(signal_id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL REFERENCES core_goals(goal_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL DEFAULT 'affects'
        CHECK (relationship IN ('affects', 'supports', 'threatens', 'blocks', 'completes')),
    PRIMARY KEY (signal_id, goal_id, relationship)
);

CREATE TABLE IF NOT EXISTS core_alerts (
    alert_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL REFERENCES core_signals(signal_id) ON DELETE CASCADE,
    priority TEXT NOT NULL
        CHECK (priority IN ('P0', 'P1', 'P2')),
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK (state IN (
            'queued', 'presented', 'acknowledged', 'snoozed',
            'dismissed', 'actioned', 'resolved', 'failed'
        )),
    requires_acknowledgment INTEGER NOT NULL DEFAULT 1
        CHECK (requires_acknowledgment IN (0, 1)),
    delivery_channel TEXT NOT NULL DEFAULT 'command_center'
        CHECK (delivery_channel IN (
            'command_center', 'push', 'email', 'sms', 'webhook', 'none'
        )),
    scheduled_at TEXT,
    presented_at TEXT,
    acknowledged_at TEXT,
    snoozed_until TEXT,
    resolved_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_decisions (
    decision_id TEXT PRIMARY KEY,
    signal_id TEXT REFERENCES core_signals(signal_id) ON DELETE SET NULL,
    goal_id TEXT REFERENCES core_goals(goal_id) ON DELETE SET NULL,
    decision_type TEXT NOT NULL
        CHECK (decision_type IN (
            'approve', 'hold', 'analyze', 'compare', 'modify',
            'defer', 'dismiss', 'reject', 'classify', 'other'
        )),
    selected_option TEXT,
    rationale TEXT,
    decided_by TEXT NOT NULL DEFAULT 'human'
        CHECK (decided_by IN ('human', 'rule', 'ai', 'joint')),
    supersedes_decision_id TEXT REFERENCES core_decisions(decision_id) ON DELETE SET NULL,
    decided_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_actions (
    action_id TEXT PRIMARY KEY,
    decision_id TEXT REFERENCES core_decisions(decision_id) ON DELETE SET NULL,
    owner_system_id TEXT NOT NULL
        REFERENCES core_systems(system_id) ON DELETE RESTRICT,
    goal_id TEXT REFERENCES core_goals(goal_id) ON DELETE SET NULL,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN (
            'proposed', 'approved', 'in_progress', 'completed',
            'failed', 'cancelled', 'deferred'
        )),
    execution_mode TEXT NOT NULL DEFAULT 'manual'
        CHECK (execution_mode IN ('manual', 'assisted', 'automated')),
    assigned_to TEXT NOT NULL DEFAULT 'user',
    due_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    external_ref TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_outcomes (
    outcome_id TEXT PRIMARY KEY,
    action_id TEXT REFERENCES core_actions(action_id) ON DELETE SET NULL,
    source_event_id TEXT REFERENCES core_events(event_id) ON DELETE SET NULL,
    outcome_type TEXT NOT NULL,
    result_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (result_status IN ('success', 'partial', 'failure', 'unknown')),
    expected_result TEXT,
    actual_result TEXT NOT NULL,
    measurement_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(measurement_json)),
    observed_at TEXT NOT NULL,
    evaluated_by TEXT NOT NULL DEFAULT 'human'
        CHECK (evaluated_by IN ('human', 'rule', 'ai', 'joint')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_lessons (
    lesson_id TEXT PRIMARY KEY,
    owner_system_id TEXT REFERENCES core_systems(system_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    rule_text TEXT NOT NULL,
    context TEXT,
    evidence_summary TEXT,
    polarity TEXT NOT NULL DEFAULT 'neutral'
        CHECK (polarity IN ('success', 'failure', 'mixed', 'neutral')),
    confidence REAL NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    durability TEXT NOT NULL DEFAULT 'candidate'
        CHECK (durability IN ('candidate', 'situational', 'durable')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'retired', 'contradicted')),
    first_observed_at TEXT,
    last_validated_at TEXT,
    application_count INTEGER NOT NULL DEFAULT 0 CHECK (application_count >= 0),
    success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS core_lesson_outcomes (
    lesson_id TEXT NOT NULL REFERENCES core_lessons(lesson_id) ON DELETE CASCADE,
    outcome_id TEXT NOT NULL REFERENCES core_outcomes(outcome_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL DEFAULT 'supports'
        CHECK (relationship IN ('supports', 'contradicts', 'refines')),
    PRIMARY KEY (lesson_id, outcome_id, relationship)
);

CREATE TABLE IF NOT EXISTS core_record_links (
    link_id TEXT PRIMARY KEY,
    source_namespace TEXT NOT NULL,
    source_record_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    target_namespace TEXT NOT NULL,
    target_record_type TEXT NOT NULL,
    target_record_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (
        source_namespace, source_record_type, source_record_id,
        target_namespace, target_record_type, target_record_id, relationship
    )
);

CREATE TABLE IF NOT EXISTS core_alert_decisions (
    alert_id TEXT NOT NULL REFERENCES core_alerts(alert_id) ON DELETE CASCADE,
    decision_id TEXT NOT NULL REFERENCES core_decisions(decision_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL DEFAULT 'response'
        CHECK (relationship IN ('response', 'resolution', 'superseded')),
    PRIMARY KEY (alert_id, decision_id, relationship)
);

CREATE INDEX IF NOT EXISTS idx_core_entities_type_status
    ON core_entities(entity_type, status);
CREATE INDEX IF NOT EXISTS idx_core_goals_status_priority
    ON core_goals(status, priority);
CREATE INDEX IF NOT EXISTS idx_core_events_source_occurred
    ON core_events(source_system_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_events_type_occurred
    ON core_events(event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_events_processing
    ON core_events(processing_status, priority, received_at);
CREATE INDEX IF NOT EXISTS idx_core_signals_status_priority
    ON core_signals(status, priority, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_alerts_queue
    ON core_alerts(state, priority, scheduled_at, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_core_alerts_one_open_per_signal
    ON core_alerts(signal_id)
    WHERE state IN (
        'queued', 'presented', 'acknowledged', 'snoozed', 'actioned', 'failed'
    );
CREATE INDEX IF NOT EXISTS idx_core_decisions_signal
    ON core_decisions(signal_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_actions_status_due
    ON core_actions(status, due_at);
CREATE INDEX IF NOT EXISTS idx_core_outcomes_action
    ON core_outcomes(action_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_lessons_status_confidence
    ON core_lessons(status, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_core_record_links_source
    ON core_record_links(source_namespace, source_record_type, source_record_id);
CREATE INDEX IF NOT EXISTS idx_core_record_links_target
    ON core_record_links(target_namespace, target_record_type, target_record_id);
CREATE INDEX IF NOT EXISTS idx_core_alert_decisions_decision
    ON core_alert_decisions(decision_id);

CREATE VIEW IF NOT EXISTS v_core_open_alerts AS
SELECT
    a.alert_id,
    a.state AS alert_state,
    a.priority,
    a.requires_acknowledgment,
    a.delivery_channel,
    a.scheduled_at,
    a.snoozed_until,
    a.created_at AS alert_created_at,
    s.signal_id,
    s.signal_type,
    s.title,
    s.summary,
    s.confidence,
    s.recommended_action,
    sys.system_id,
    sys.name AS system_name
FROM core_alerts AS a
JOIN core_signals AS s ON s.signal_id = a.signal_id
JOIN core_systems AS sys ON sys.system_id = s.owner_system_id
WHERE a.state IN ('queued', 'presented', 'acknowledged', 'snoozed', 'failed');

CREATE VIEW IF NOT EXISTS v_core_learning_loop AS
SELECT
    e.event_id,
    e.event_type,
    e.occurred_at,
    s.signal_id,
    s.signal_type,
    s.priority AS signal_priority,
    d.decision_id,
    d.decision_type,
    a.action_id,
    a.status AS action_status,
    o.outcome_id,
    o.result_status,
    l.lesson_id,
    l.rule_text,
    l.confidence AS lesson_confidence
FROM core_events AS e
LEFT JOIN core_signal_events AS se ON se.event_id = e.event_id
LEFT JOIN core_signals AS s ON s.signal_id = se.signal_id
LEFT JOIN core_decisions AS d ON d.signal_id = s.signal_id
LEFT JOIN core_actions AS a ON a.decision_id = d.decision_id
LEFT JOIN core_outcomes AS o ON o.action_id = a.action_id
LEFT JOIN core_lesson_outcomes AS lo ON lo.outcome_id = o.outcome_id
LEFT JOIN core_lessons AS l ON l.lesson_id = lo.lesson_id;

INSERT OR IGNORE INTO core_systems
    (system_id, name, slug, description, status)
VALUES
    ('sys_info_analyzer', 'Info Analyzer', 'info-analyzer',
     'Shared signal, memory, decision, feedback, and lesson infrastructure.', 'active'),
    ('sys_innbank', 'INNBANK', 'innbank',
     'Financial control center and capital-routing engine.', 'active'),
    ('sys_groove', 'Groove OS', 'groove-os',
     'Music analysis, training, arrangement, and creation engine.', 'active'),
    ('sys_sales', 'Sales OS', 'sales-os',
     'Lead, offer, relationship, distribution, and conversion engine.', 'planned'),
    ('sys_private_equity', 'Private Equity OS', 'private-equity-os',
     'Asset evaluation, acquisition, ownership, improvement, and allocation engine.', 'planned'),
    ('sys_home_sentinel', 'Home Sentinel OS', 'home-sentinel-os',
     'Home sensing, security, device-health, and physical-event engine.', 'active');

INSERT OR IGNORE INTO schema_migrations (version, name)
VALUES (1, 'core_foundation');

COMMIT;
