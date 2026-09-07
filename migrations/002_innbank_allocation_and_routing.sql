PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS innbank_allocation_plans (
    plan_id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL
        REFERENCES core_systems(system_id) ON DELETE RESTRICT,
    signal_id TEXT NOT NULL
        REFERENCES core_signals(signal_id) ON DELETE RESTRICT,
    source_event_id TEXT NOT NULL
        REFERENCES core_events(event_id) ON DELETE RESTRICT,
    paycheck_amount_cents INTEGER NOT NULL CHECK (paycheck_amount_cents >= 0),
    currency TEXT NOT NULL,
    account_name TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    rationale TEXT,
    recommended_action TEXT,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'decided', 'completed', 'rejected')),
    latest_response TEXT,
    latest_decision_id TEXT REFERENCES core_decisions(decision_id) ON DELETE SET NULL,
    latest_decided_at TEXT,
    response_count INTEGER NOT NULL DEFAULT 0 CHECK (response_count >= 0),
    completed_at TEXT,
    completed_event_id TEXT REFERENCES core_events(event_id) ON DELETE SET NULL,
    completed_routing_run_id TEXT REFERENCES innbank_routing_runs(routing_run_id) ON DELETE SET NULL,
    notes TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (signal_id)
);

CREATE TABLE IF NOT EXISTS innbank_allocation_items (
    allocation_item_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL
        REFERENCES innbank_allocation_plans(plan_id) ON DELETE CASCADE,
    item_type TEXT NOT NULL
        CHECK (item_type IN ('allocation', 'unallocated')),
    label TEXT NOT NULL,
    proposed_amount_cents INTEGER NOT NULL CHECK (proposed_amount_cents >= 0),
    goal_id TEXT REFERENCES core_goals(goal_id) ON DELETE SET NULL,
    core_action_id TEXT REFERENCES core_actions(action_id) ON DELETE SET NULL,
    state TEXT NOT NULL DEFAULT 'proposed'
        CHECK (state IN ('proposed', 'decided', 'routed', 'failed')),
    order_index INTEGER NOT NULL,
    decided_at TEXT,
    routed_at TEXT,
    notes TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (plan_id, order_index)
);

CREATE TABLE IF NOT EXISTS innbank_routing_runs (
    routing_run_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL
        REFERENCES innbank_allocation_plans(plan_id) ON DELETE CASCADE,
    source_system_id TEXT NOT NULL
        REFERENCES core_systems(system_id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'recorded'
        CHECK (status IN ('recorded', 'completed', 'failed')),
    notes TEXT,
    completed_at TEXT,
    routing_completed_event_id TEXT REFERENCES core_events(event_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS innbank_routing_items (
    routing_item_id TEXT PRIMARY KEY,
    routing_run_id TEXT NOT NULL
        REFERENCES innbank_routing_runs(routing_run_id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL
        REFERENCES innbank_allocation_plans(plan_id) ON DELETE CASCADE,
    allocation_item_id TEXT NOT NULL
        REFERENCES innbank_allocation_items(allocation_item_id) ON DELETE CASCADE,
    core_action_id TEXT REFERENCES core_actions(action_id) ON DELETE SET NULL,
    proposed_amount_cents INTEGER NOT NULL CHECK (proposed_amount_cents >= 0),
    actual_amount_cents INTEGER NOT NULL CHECK (actual_amount_cents >= 0),
    variance_cents INTEGER NOT NULL,
    routing_status TEXT NOT NULL
        CHECK (routing_status IN ('partial', 'completed', 'failed')),
    completed_at TEXT NOT NULL,
    notes TEXT,
    outcome_id TEXT REFERENCES core_outcomes(outcome_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (allocation_item_id)
);

CREATE INDEX IF NOT EXISTS idx_innbank_allocation_plans_signal
    ON innbank_allocation_plans(signal_id);
CREATE INDEX IF NOT EXISTS idx_innbank_allocation_items_plan
    ON innbank_allocation_items(plan_id, order_index);
CREATE INDEX IF NOT EXISTS idx_innbank_routing_runs_plan
    ON innbank_routing_runs(plan_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_innbank_routing_items_plan
    ON innbank_routing_items(plan_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_innbank_routing_items_run
    ON innbank_routing_items(routing_run_id, allocation_item_id);

INSERT OR IGNORE INTO schema_migrations (version, name)
VALUES (2, 'innbank_allocation_and_routing');

COMMIT;
