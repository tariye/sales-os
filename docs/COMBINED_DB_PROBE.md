# Combined Database Probe

## Baseline Facts

- Database path: `/Users/admin/Library/Mobile Documents/com~apple~CloudDocs/Downloads/Projects/info_analyzer_os_sqlite_v0_3_clean/data/info_analyzer.db`
- SQLite version: `3.53.2`
- Database size: `6762496` bytes
- PRAGMA journal_mode: `wal`
- PRAGMA foreign_keys: `0`
- PRAGMA integrity_check: `ok`
- PRAGMA foreign_key_check rows: `0`

## Schema Inventory

- Tables (33): `actions`, `api_idempotency`, `audit_log`, `decision_reviews`, `decision_rules`, `device_log_catalog`, `entity_aliases`, `entries`, `entries_fts`, `entries_fts_config`, `entries_fts_content`, `entries_fts_data`, `entries_fts_docsize`, `entries_fts_idx`, `import_batches`, `import_rows`, `import_sheets`, `ingest_items`, `ingest_sources`, `ledger_decisions`, `ledger_projects`, `listening_extractions`, `listening_projects`, `live_signals`, `pattern_runs`, `pattern_stats`, `portfolio_trades`, `pull_rules`, `relationships`, `risk_reward_setups`, `surfaced_cards`, `watchlist_items`, `watchlists`
- Views (0): none
- Indexs (40): `idx_actions_due`, `idx_actions_status`, `idx_api_idempotency_created`, `idx_decision_reviews_entry`, `idx_decision_reviews_status`, `idx_decision_rules_domain`, `idx_device_log_catalog_batch`, `idx_entries_action_status`, `idx_entries_actionability`, `idx_entries_card_type`, `idx_entries_created`, `idx_entries_domain`, `idx_entries_entity`, `idx_entries_raw_staging`, `idx_entries_review_date`, `idx_entries_signal_role`, `idx_entries_status`, `idx_import_batches_created`, `idx_import_rows_batch`, `idx_import_rows_record_type`, `idx_import_sheets_batch`, `idx_ingest_items_fingerprint`, `idx_ingest_items_source`, `idx_ingest_sources_active`, `idx_listening_extractions_label`, `idx_listening_extractions_project`, `idx_listening_projects_status`, `idx_listening_projects_updated`, `idx_live_signals_domain`, `idx_live_signals_source`, `idx_live_signals_status`, `idx_pattern_runs_created`, `idx_portfolio_trades_symbol`, `idx_pull_rules_active`, `idx_relationships_from`, `idx_relationships_to`, `idx_risk_reward_symbol`, `idx_surfaced_status`, `idx_watchlist_items_watchlist`, `idx_watchlists_batch`
- Triggers (0): none

## Table Classification and Counts

| Table | Classification | Rows | Columns | FKs | Server refs | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `actions` | Decision/action infrastructure | 152 | 13 | 1 | 89 |  |
| `api_idempotency` | Operational/audit infrastructure | 13 | 7 | 0 | 4 | Operational support table. |
| `audit_log` | Operational/audit infrastructure | 705 | 6 | 0 | 2 | Operational support table. |
| `decision_reviews` | Decision/action infrastructure | 6 | 15 | 2 | 20 |  |
| `decision_rules` | Decision/action infrastructure | 8 | 15 | 1 | 16 |  |
| `device_log_catalog` | Ingestion infrastructure | 16 | 11 | 2 | 8 |  |
| `entity_aliases` | Legacy memory/intelligence | 16 | 10 | 0 | 0 | Related to the legacy decision/memory graph but not fully normalized. |
| `entries` | Legacy memory/intelligence | 194 | 45 | 2 | 204 |  |
| `entries_fts` | Legacy memory/intelligence | 193 | 10 | 0 | 9 | FTS shadow/support table for legacy entries search. |
| `entries_fts_config` | Legacy memory/intelligence | 1 | 2 | 0 | 0 | FTS shadow/support table for legacy entries search. |
| `entries_fts_content` | Legacy memory/intelligence | 193 | 11 | 0 | 0 | FTS shadow/support table for legacy entries search. |
| `entries_fts_data` | Legacy memory/intelligence | 153 | 2 | 0 | 0 | FTS shadow/support table for legacy entries search. |
| `entries_fts_docsize` | Legacy memory/intelligence | 193 | 2 | 0 | 0 | FTS shadow/support table for legacy entries search. |
| `entries_fts_idx` | Legacy memory/intelligence | 150 | 3 | 0 | 0 | FTS shadow/support table for legacy entries search. |
| `import_batches` | Ingestion infrastructure | 4 | 15 | 0 | 19 |  |
| `import_rows` | Ingestion infrastructure | 141 | 15 | 2 | 11 |  |
| `import_sheets` | Ingestion infrastructure | 26 | 14 | 1 | 14 |  |
| `ingest_items` | Ingestion infrastructure | 0 | 15 | 1 | 7 |  |
| `ingest_sources` | Ingestion infrastructure | 0 | 12 | 0 | 11 |  |
| `ledger_decisions` | Transitional or uncertain | 4 | 17 | 0 | 4 | Related to the legacy decision/memory graph but not fully normalized. |
| `ledger_projects` | Transitional or uncertain | 9 | 16 | 0 | 0 | Related to the legacy decision/memory graph but not fully normalized. |
| `listening_extractions` | Domain module | 0 | 14 | 1 | 13 |  |
| `listening_projects` | Domain module | 0 | 9 | 0 | 14 |  |
| `live_signals` | Transitional or uncertain | 0 | 20 | 4 | 12 | Related to the legacy decision/memory graph but not fully normalized. |
| `pattern_runs` | Legacy memory/intelligence | 7 | 6 | 0 | 5 | Derived analytics/history table with no direct foreign keys. |
| `pattern_stats` | Legacy memory/intelligence | 59 | 10 | 0 | 8 | Derived analytics/history table with no direct foreign keys. |
| `portfolio_trades` | Domain module | 13 | 19 | 3 | 10 |  |
| `pull_rules` | Legacy memory/intelligence | 2046 | 10 | 1 | 9 |  |
| `relationships` | Legacy memory/intelligence | 428 | 7 | 2 | 26 |  |
| `risk_reward_setups` | Domain module | 2 | 16 | 3 | 10 |  |
| `surfaced_cards` | Legacy memory/intelligence | 474 | 11 | 2 | 27 |  |
| `watchlist_items` | Domain module | 126 | 22 | 4 | 13 |  |
| `watchlists` | Domain module | 8 | 9 | 2 | 15 |  |

## Tables Related But Without Declared FKs

- `audit_log`: `entity_id`
- `entity_aliases`: `canonical_entity_id`
- `entries_fts`: `entry_id`
- `pattern_stats`: `last_entry_id`

## Server.py Usage

- Tables used by `server.py` are summarized by regex hits in the source file.
  - `entries`: 204
  - `actions`: 89
  - `surfaced_cards`: 27
  - `relationships`: 26
  - `decision_reviews`: 20
  - `import_batches`: 19
  - `decision_rules`: 16
  - `watchlists`: 15
  - `import_sheets`: 14
  - `listening_projects`: 14
  - `listening_extractions`: 13
  - `watchlist_items`: 13
  - `live_signals`: 12
  - `import_rows`: 11
  - `ingest_sources`: 11
  - `portfolio_trades`: 10
  - `risk_reward_setups`: 10
  - `entries_fts`: 9
  - `pull_rules`: 9
  - `device_log_catalog`: 8
  - `pattern_stats`: 8
  - `ingest_items`: 7
  - `pattern_runs`: 5
  - `api_idempotency`: 4
  - `ledger_decisions`: 4
  - `audit_log`: 2

## Per-Table Schema Detail

### `actions`

- Classification: Decision/action infrastructure
- Row count: 152
- Foreign keys: 1
- Indexes: 3
- Status values: {"status": ["open", "cancelled", "done", "waiting"]}
- Priority values: {"priority": ["Medium", "High"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"], "due_date": ["ISO-8601 naive without fractional seconds"]}
- Identifier prefixes: {"id": [["ACT", 152]], "entry_id": [["ESI", 109], ["IA", 43]]}
- JSON validity: {"metadata": {"valid": 152, "total": 152}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `entry_id` | `TEXT` | 0 | `` | 0 |
| `action_title` | `TEXT` | 0 | `` | 0 |
| `why` | `TEXT` | 1 | `` | 0 |
| `track_metric` | `TEXT` | 1 | `` | 0 |
| `due_date` | `TEXT` | 1 | `` | 0 |
| `priority` | `TEXT` | 1 | `'Medium'` | 0 |
| `status` | `TEXT` | 1 | `'open'` | 0 |
| `result` | `TEXT` | 1 | `` | 0 |
| `lesson_update` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |

### `api_idempotency`

- Classification: Operational/audit infrastructure
- Row count: 13
- Foreign keys: 0
- Indexes: 2
- Notes: Operational support table.
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- JSON validity: {"response_json": {"valid": 13, "total": 13}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `key` | `TEXT` | 0 | `` | 1 |
| `method` | `TEXT` | 0 | `` | 2 |
| `path` | `TEXT` | 0 | `` | 3 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `request_hash` | `TEXT` | 1 | `` | 0 |
| `status_code` | `INTEGER` | 0 | `` | 0 |
| `response_json` | `TEXT` | 0 | `` | 0 |

### `audit_log`

- Classification: Operational/audit infrastructure
- Row count: 705
- Foreign keys: 0
- Indexes: 1
- Notes: Operational support table.
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["AUD", 200]], "entity_id": [["ESI", 134], ["IA", 59], ["ACT", 6], ["PTRUN", 1]]}
- JSON validity: {"payload": {"valid": 705, "total": 705}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `event_type` | `TEXT` | 0 | `` | 0 |
| `entity_type` | `TEXT` | 0 | `` | 0 |
| `entity_id` | `TEXT` | 1 | `` | 0 |
| `payload` | `TEXT` | 1 | `'{}'` | 0 |

### `decision_reviews`

- Classification: Decision/action infrastructure
- Row count: 6
- Foreign keys: 2
- Indexes: 4
- Status values: {"status": ["open"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["DREV", 6]], "entry_id": [["IA", 6]], "rule_id": [["DR", 6]]}
- JSON validity: {"metadata": {"valid": 6, "total": 6}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `entry_id` | `TEXT` | 0 | `` | 0 |
| `rule_id` | `TEXT` | 1 | `` | 0 |
| `decision_question` | `TEXT` | 0 | `` | 0 |
| `current_rule` | `TEXT` | 1 | `` | 0 |
| `recommended_change` | `TEXT` | 1 | `` | 0 |
| `confidence_before` | `REAL` | 1 | `0.5` | 0 |
| `confidence_after` | `REAL` | 1 | `0.5` | 0 |
| `status` | `TEXT` | 1 | `'open'` | 0 |
| `feedback_metric` | `TEXT` | 1 | `` | 0 |
| `result` | `TEXT` | 1 | `` | 0 |
| `rule_update` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `rule_id` | `decision_rules` | `id` | `NO ACTION` | `NO ACTION` |
| `entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |

### `decision_rules`

- Classification: Decision/action infrastructure
- Row count: 8
- Foreign keys: 1
- Indexes: 2
- Status values: {"status": ["active"]}
- Confidence values: {"confidence": ["0.65", "0.45000000000000007", "0.45", "0.7", "0.837"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["DR", 8]], "last_entry_id": [["IA", 6]]}
- JSON validity: {"metadata": {"valid": 8, "total": 8}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `name` | `TEXT` | 0 | `` | 0 |
| `domain` | `TEXT` | 1 | `'Other'` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `rule_text` | `TEXT` | 0 | `` | 0 |
| `confidence` | `REAL` | 1 | `0.5` | 0 |
| `status` | `TEXT` | 1 | `'active'` | 0 |
| `evidence_count` | `INTEGER` | 1 | `0` | 0 |
| `action_count` | `INTEGER` | 1 | `0` | 0 |
| `success_count` | `INTEGER` | 1 | `0` | 0 |
| `failure_count` | `INTEGER` | 1 | `0` | 0 |
| `last_entry_id` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `last_entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |

### `device_log_catalog`

- Classification: Ingestion infrastructure
- Row count: 16
- Foreign keys: 2
- Indexes: 2
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["DLC", 16]], "batch_id": [["IBAT", 16]], "sheet_id": [["ISHT", 16]]}
- JSON validity: {"metadata": {"valid": 16, "total": 16}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `batch_id` | `TEXT` | 0 | `` | 0 |
| `sheet_id` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `workbook_title` | `TEXT` | 1 | `` | 0 |
| `sheet_name` | `TEXT` | 0 | `` | 0 |
| `sheet_index` | `INTEGER` | 1 | `0` | 0 |
| `size_bytes` | `INTEGER` | 1 | `0` | 0 |
| `parser_status` | `TEXT` | 1 | `'manifest_only'` | 0 |
| `notes` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `sheet_id` | `import_sheets` | `id` | `NO ACTION` | `NO ACTION` |
| `batch_id` | `import_batches` | `id` | `NO ACTION` | `NO ACTION` |

### `entity_aliases`

- Classification: Legacy memory/intelligence
- Row count: 16
- Foreign keys: 0
- Indexes: 1
- Notes: Related to the legacy decision/memory graph but not fully normalized.
- Timestamp formats: {"created_at": ["ISO-8601 Z without fractional seconds"], "updated_at": ["ISO-8601 Z without fractional seconds"]}
- Identifier prefixes: {"id": [["alias", 16]], "canonical_entity_id": [["entity", 16]]}
- JSON validity: {"metadata": {"valid": 16, "total": 16}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `canonical_entity_id` | `TEXT` | 0 | `` | 0 |
| `canonical_name` | `TEXT` | 0 | `` | 0 |
| `domain` | `TEXT` | 1 | `` | 0 |
| `aliases` | `TEXT` | 1 | `'[]'` | 0 |
| `source_record_count` | `INTEGER` | 1 | `0` | 0 |
| `related_entry_ids` | `TEXT` | 1 | `'[]'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `entries`

- Classification: Legacy memory/intelligence
- Row count: 194
- Foreign keys: 2
- Indexes: 11
- Status values: {"status": ["codified", "archived", "needs_enrichment", "validated", "pending_claude"]}
- Confidence values: {"confidence": ["Medium", "High"]}
- Action-state values: {"action_status": ["open", "cancelled", "done", "waiting"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds", "ISO-8601 -07:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"], "date": ["ISO-8601 naive without fractional seconds"], "review_date": ["ISO-8601 naive without fractional seconds"], "last_resurfaced": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["ESI", 134], ["IA", 60]], "parent_entry_id": [["IA", 3]]}
- JSON validity: {"tags": {"valid": 194, "total": 194}, "metadata": {"valid": 194, "total": 194}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `date` | `TEXT` | 0 | `` | 0 |
| `title` | `TEXT` | 1 | `` | 0 |
| `domain` | `TEXT` | 1 | `'Other'` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `source_type` | `TEXT` | 1 | `'manual'` | 0 |
| `raw_input` | `TEXT` | 0 | `` | 0 |
| `signal` | `TEXT` | 1 | `` | 0 |
| `interpretation` | `TEXT` | 1 | `` | 0 |
| `signal_role` | `TEXT` | 1 | `'watch'` | 0 |
| `trackable_as` | `TEXT` | 1 | `` | 0 |
| `tracking_metric` | `TEXT` | 1 | `` | 0 |
| `baseline` | `TEXT` | 1 | `` | 0 |
| `target_threshold` | `TEXT` | 1 | `` | 0 |
| `trigger_condition` | `TEXT` | 1 | `` | 0 |
| `review_date` | `TEXT` | 1 | `` | 0 |
| `pattern` | `TEXT` | 1 | `` | 0 |
| `returned_action` | `TEXT` | 1 | `` | 0 |
| `action_status` | `TEXT` | 1 | `'open'` | 0 |
| `result` | `TEXT` | 1 | `` | 0 |
| `lesson` | `TEXT` | 1 | `` | 0 |
| `next_step` | `TEXT` | 1 | `` | 0 |
| `confidence` | `TEXT` | 1 | `'Medium'` | 0 |
| `status` | `TEXT` | 1 | `'codified'` | 0 |
| `tags` | `TEXT` | 1 | `'[]'` | 0 |
| `proof_artifact` | `TEXT` | 1 | `` | 0 |
| `parent_entry_id` | `TEXT` | 1 | `` | 0 |
| `supersedes_entry_id` | `TEXT` | 1 | `` | 0 |
| `memory_version` | `INTEGER` | 1 | `1` | 0 |
| `last_resurfaced` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |
| `actionability` | `TEXT` | 1 | `'watch'` | 0 |
| `pull_trigger_type` | `TEXT` | 1 | `'tag'` | 0 |
| `pull_trigger` | `TEXT` | 1 | `` | 0 |
| `relationship_type` | `TEXT` | 1 | `'connects'` | 0 |
| `card_type` | `TEXT` | 1 | `'Watch Card'` | 0 |
| `result_to_track` | `TEXT` | 1 | `` | 0 |
| `raw_staging_status` | `TEXT` | 1 | `'processed'` | 0 |
| `first_step` | `TEXT` | 1 | `` | 0 |
| `impact_metric` | `TEXT` | 1 | `` | 0 |
| `feedback_to_capture` | `TEXT` | 1 | `` | 0 |
| `related_memory_query` | `TEXT` | 1 | `` | 0 |
| `qa_scores` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `supersedes_entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |
| `parent_entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |

### `entries_fts`

- Classification: Legacy memory/intelligence
- Row count: 193
- Foreign keys: 0
- Indexes: 0
- Notes: FTS shadow/support table for legacy entries search.
- Identifier prefixes: {"entry_id": [["ESI", 134], ["IA", 59]]}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `entry_id` | `` | 1 | `` | 0 |
| `title` | `` | 1 | `` | 0 |
| `domain` | `` | 1 | `` | 0 |
| `entity` | `` | 1 | `` | 0 |
| `raw_input` | `` | 1 | `` | 0 |
| `signal` | `` | 1 | `` | 0 |
| `interpretation` | `` | 1 | `` | 0 |
| `pattern` | `` | 1 | `` | 0 |
| `lesson` | `` | 1 | `` | 0 |
| `tags_text` | `` | 1 | `` | 0 |

### `entries_fts_config`

- Classification: Legacy memory/intelligence
- Row count: 1
- Foreign keys: 0
- Indexes: 1
- Notes: FTS shadow/support table for legacy entries search.

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `k` | `` | 0 | `` | 1 |
| `v` | `` | 1 | `` | 0 |

### `entries_fts_content`

- Classification: Legacy memory/intelligence
- Row count: 193
- Foreign keys: 0
- Indexes: 0
- Notes: FTS shadow/support table for legacy entries search.

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `INTEGER` | 1 | `` | 1 |
| `c0` | `` | 1 | `` | 0 |
| `c1` | `` | 1 | `` | 0 |
| `c2` | `` | 1 | `` | 0 |
| `c3` | `` | 1 | `` | 0 |
| `c4` | `` | 1 | `` | 0 |
| `c5` | `` | 1 | `` | 0 |
| `c6` | `` | 1 | `` | 0 |
| `c7` | `` | 1 | `` | 0 |
| `c8` | `` | 1 | `` | 0 |
| `c9` | `` | 1 | `` | 0 |

### `entries_fts_data`

- Classification: Legacy memory/intelligence
- Row count: 153
- Foreign keys: 0
- Indexes: 0
- Notes: FTS shadow/support table for legacy entries search.

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `INTEGER` | 1 | `` | 1 |
| `block` | `BLOB` | 1 | `` | 0 |

### `entries_fts_docsize`

- Classification: Legacy memory/intelligence
- Row count: 193
- Foreign keys: 0
- Indexes: 0
- Notes: FTS shadow/support table for legacy entries search.

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `INTEGER` | 1 | `` | 1 |
| `sz` | `BLOB` | 1 | `` | 0 |

### `entries_fts_idx`

- Classification: Legacy memory/intelligence
- Row count: 150
- Foreign keys: 0
- Indexes: 1
- Notes: FTS shadow/support table for legacy entries search.

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `segid` | `` | 0 | `` | 1 |
| `term` | `` | 0 | `` | 2 |
| `pgno` | `` | 1 | `` | 0 |

### `import_batches`

- Classification: Ingestion infrastructure
- Row count: 4
- Foreign keys: 0
- Indexes: 3
- Status values: {"status": ["imported", "partial"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["IBAT", 4]]}
- JSON validity: {"metadata": {"valid": 4, "total": 4}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `source_path` | `TEXT` | 0 | `` | 0 |
| `file_name` | `TEXT` | 0 | `` | 0 |
| `file_ext` | `TEXT` | 0 | `` | 0 |
| `source_signature` | `TEXT` | 0 | `` | 0 |
| `import_kind` | `TEXT` | 1 | `'workbook'` | 0 |
| `parser_name` | `TEXT` | 1 | `` | 0 |
| `status` | `TEXT` | 1 | `'imported'` | 0 |
| `sheet_count` | `INTEGER` | 1 | `0` | 0 |
| `row_count` | `INTEGER` | 1 | `0` | 0 |
| `projected_count` | `INTEGER` | 1 | `0` | 0 |
| `notes` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `import_rows`

- Classification: Ingestion infrastructure
- Row count: 141
- Foreign keys: 2
- Indexes: 3
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["IROW", 141]], "batch_id": [["IBAT", 141]], "sheet_id": [["ISHT", 141]]}
- JSON validity: {"raw_json": {"valid": 141, "total": 141}, "normalized_json": {"valid": 141, "total": 141}, "metadata": {"valid": 141, "total": 141}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `batch_id` | `TEXT` | 0 | `` | 0 |
| `sheet_id` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `sheet_name` | `TEXT` | 0 | `` | 0 |
| `row_number` | `INTEGER` | 0 | `` | 0 |
| `row_kind` | `TEXT` | 1 | `'data'` | 0 |
| `record_type` | `TEXT` | 1 | `'raw'` | 0 |
| `domain` | `TEXT` | 1 | `'Other'` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `parser_status` | `TEXT` | 1 | `'imported'` | 0 |
| `fingerprint` | `TEXT` | 1 | `` | 0 |
| `raw_json` | `TEXT` | 1 | `'{}'` | 0 |
| `normalized_json` | `TEXT` | 1 | `'{}'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `sheet_id` | `import_sheets` | `id` | `NO ACTION` | `NO ACTION` |
| `batch_id` | `import_batches` | `id` | `NO ACTION` | `NO ACTION` |

### `import_sheets`

- Classification: Ingestion infrastructure
- Row count: 26
- Foreign keys: 1
- Indexes: 2
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["ISHT", 26]], "batch_id": [["IBAT", 26]]}
- JSON validity: {"columns_json": {"valid": 26, "total": 26}, "sample_rows_json": {"valid": 26, "total": 26}, "metadata": {"valid": 26, "total": 26}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `batch_id` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `sheet_index` | `INTEGER` | 1 | `0` | 0 |
| `sheet_name` | `TEXT` | 0 | `` | 0 |
| `source_ref` | `TEXT` | 1 | `` | 0 |
| `parser_status` | `TEXT` | 1 | `'imported'` | 0 |
| `header_row` | `INTEGER` | 1 | `` | 0 |
| `nonempty_rows` | `INTEGER` | 1 | `0` | 0 |
| `projected_rows` | `INTEGER` | 1 | `0` | 0 |
| `columns_json` | `TEXT` | 1 | `'[]'` | 0 |
| `sample_rows_json` | `TEXT` | 1 | `'[]'` | 0 |
| `notes` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `batch_id` | `import_batches` | `id` | `NO ACTION` | `NO ACTION` |

### `ingest_items`

- Classification: Ingestion infrastructure
- Row count: 0
- Foreign keys: 1
- Indexes: 4
- Status values: {"status": []}
- JSON validity: {"metadata": {"valid": 0, "total": 0}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `source_id` | `TEXT` | 0 | `` | 0 |
| `source_name` | `TEXT` | 1 | `` | 0 |
| `source_type` | `TEXT` | 1 | `` | 0 |
| `url` | `TEXT` | 1 | `` | 0 |
| `title` | `TEXT` | 1 | `` | 0 |
| `raw_text` | `TEXT` | 0 | `` | 0 |
| `published_at` | `TEXT` | 1 | `` | 0 |
| `fingerprint` | `TEXT` | 1 | `` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `domain` | `TEXT` | 1 | `'Other'` | 0 |
| `status` | `TEXT` | 1 | `'new'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `source_id` | `ingest_sources` | `id` | `NO ACTION` | `NO ACTION` |

### `ingest_sources`

- Classification: Ingestion infrastructure
- Row count: 0
- Foreign keys: 0
- Indexes: 2
- JSON validity: {"metadata": {"valid": 0, "total": 0}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `name` | `TEXT` | 0 | `` | 0 |
| `source_type` | `TEXT` | 1 | `'manual'` | 0 |
| `url` | `TEXT` | 1 | `` | 0 |
| `domain` | `TEXT` | 1 | `'Other'` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `poll_interval_minutes` | `INTEGER` | 1 | `60` | 0 |
| `active` | `INTEGER` | 1 | `1` | 0 |
| `last_run_at` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `ledger_decisions`

- Classification: Transitional or uncertain
- Row count: 4
- Foreign keys: 0
- Indexes: 1
- Notes: Related to the legacy decision/memory graph but not fully normalized.
- Status values: {"status": ["open"]}
- Confidence values: {"confidence": ["Medium"]}
- Timestamp formats: {"created_at": ["ISO-8601 Z without fractional seconds"], "updated_at": ["ISO-8601 Z without fractional seconds"]}
- Identifier prefixes: {"id": [["decision", 4]]}
- JSON validity: {"options": {"valid": 4, "total": 4}, "metadata": {"valid": 4, "total": 4}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `title` | `TEXT` | 0 | `` | 0 |
| `domain` | `TEXT` | 1 | `` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `status` | `TEXT` | 1 | `'open'` | 0 |
| `lifecycle` | `TEXT` | 1 | `'investigating'` | 0 |
| `decision_question` | `TEXT` | 0 | `` | 0 |
| `options` | `TEXT` | 1 | `'[]'` | 0 |
| `current_position` | `TEXT` | 1 | `` | 0 |
| `next_review` | `TEXT` | 1 | `` | 0 |
| `confidence` | `TEXT` | 1 | `'Medium'` | 0 |
| `tracking_metric` | `TEXT` | 1 | `` | 0 |
| `aliases` | `TEXT` | 1 | `'[]'` | 0 |
| `related_query` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `ledger_projects`

- Classification: Transitional or uncertain
- Row count: 9
- Foreign keys: 0
- Indexes: 1
- Notes: Related to the legacy decision/memory graph but not fully normalized.
- Status values: {"status": ["active"]}
- Confidence values: {"confidence": ["Medium", "High"]}
- Timestamp formats: {"created_at": ["ISO-8601 Z without fractional seconds"], "updated_at": ["ISO-8601 Z without fractional seconds"]}
- Identifier prefixes: {"id": [["project", 9]]}
- JSON validity: {"metadata": {"valid": 9, "total": 9}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `title` | `TEXT` | 0 | `` | 0 |
| `domain` | `TEXT` | 1 | `` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `status` | `TEXT` | 1 | `'active'` | 0 |
| `lifecycle` | `TEXT` | 1 | `'investigating'` | 0 |
| `summary` | `TEXT` | 1 | `` | 0 |
| `current_milestone` | `TEXT` | 1 | `` | 0 |
| `current_blocker` | `TEXT` | 1 | `` | 0 |
| `next_action` | `TEXT` | 1 | `` | 0 |
| `confidence` | `TEXT` | 1 | `'Medium'` | 0 |
| `aliases` | `TEXT` | 1 | `'[]'` | 0 |
| `related_query` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `listening_extractions`

- Classification: Domain module
- Row count: 0
- Foreign keys: 1
- Indexes: 3
- JSON validity: {"section_map": {"valid": 0, "total": 0}, "glossary": {"valid": 0, "total": 0}, "tags": {"valid": 0, "total": 0}, "metadata": {"valid": 0, "total": 0}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `project_id` | `TEXT` | 0 | `` | 0 |
| `label` | `TEXT` | 1 | `` | 0 |
| `extraction_type` | `TEXT` | 1 | `'song_breakdown'` | 0 |
| `raw_evidence` | `TEXT` | 1 | `` | 0 |
| `section_map` | `TEXT` | 1 | `'[]'` | 0 |
| `glossary` | `TEXT` | 1 | `'[]'` | 0 |
| `sound_example` | `TEXT` | 1 | `` | 0 |
| `breakdown` | `TEXT` | 1 | `` | 0 |
| `reuse_context` | `TEXT` | 1 | `` | 0 |
| `tags` | `TEXT` | 1 | `'[]'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `project_id` | `listening_projects` | `id` | `NO ACTION` | `NO ACTION` |

### `listening_projects`

- Classification: Domain module
- Row count: 0
- Foreign keys: 0
- Indexes: 3
- Status values: {"status": []}
- JSON validity: {"metadata": {"valid": 0, "total": 0}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `title` | `TEXT` | 0 | `` | 0 |
| `artist` | `TEXT` | 1 | `` | 0 |
| `source_url` | `TEXT` | 1 | `` | 0 |
| `notes` | `TEXT` | 1 | `` | 0 |
| `status` | `TEXT` | 1 | `'active'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `live_signals`

- Classification: Transitional or uncertain
- Row count: 0
- Foreign keys: 4
- Indexes: 4
- Notes: Related to the legacy decision/memory graph but not fully normalized.
- Status values: {"status": []}
- Priority values: {"priority": []}
- Confidence values: {"confidence": []}
- JSON validity: {"metadata": {"valid": 0, "total": 0}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `ingest_item_id` | `TEXT` | 1 | `` | 0 |
| `entry_id` | `TEXT` | 1 | `` | 0 |
| `decision_review_id` | `TEXT` | 1 | `` | 0 |
| `source_id` | `TEXT` | 1 | `` | 0 |
| `source_name` | `TEXT` | 1 | `` | 0 |
| `domain` | `TEXT` | 1 | `'Other'` | 0 |
| `entity` | `TEXT` | 1 | `` | 0 |
| `signal` | `TEXT` | 1 | `` | 0 |
| `why_it_matters` | `TEXT` | 1 | `` | 0 |
| `decision_affected` | `TEXT` | 1 | `` | 0 |
| `recommended_action` | `TEXT` | 1 | `` | 0 |
| `tracking_metric` | `TEXT` | 1 | `` | 0 |
| `confidence` | `TEXT` | 1 | `'Medium'` | 0 |
| `priority` | `TEXT` | 1 | `'Medium'` | 0 |
| `status` | `TEXT` | 1 | `'new'` | 0 |
| `related_memory_count` | `INTEGER` | 1 | `0` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `source_id` | `ingest_sources` | `id` | `NO ACTION` | `NO ACTION` |
| `decision_review_id` | `decision_reviews` | `id` | `NO ACTION` | `NO ACTION` |
| `entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |
| `ingest_item_id` | `ingest_items` | `id` | `NO ACTION` | `NO ACTION` |

### `pattern_runs`

- Classification: Legacy memory/intelligence
- Row count: 7
- Foreign keys: 0
- Indexes: 2
- Notes: Derived analytics/history table with no direct foreign keys.
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["PTRUN", 7]]}
- JSON validity: {"cards": {"valid": 7, "total": 7}, "metadata": {"valid": 7, "total": 7}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `scan_type` | `TEXT` | 1 | `'full'` | 0 |
| `summary` | `TEXT` | 1 | `` | 0 |
| `cards` | `TEXT` | 1 | `'[]'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `pattern_stats`

- Classification: Legacy memory/intelligence
- Row count: 59
- Foreign keys: 0
- Indexes: 2
- Notes: Derived analytics/history table with no direct foreign keys.
- Confidence values: {"confidence": ["Low", "High", "Medium"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["PAT", 59]], "last_entry_id": [["IA", 50], ["ESI", 9]]}
- JSON validity: {"tags": {"valid": 59, "total": 59}, "metadata": {"valid": 59, "total": 59}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `pattern` | `TEXT` | 0 | `` | 0 |
| `domains` | `TEXT` | 1 | `'[]'` | 0 |
| `tags` | `TEXT` | 1 | `'[]'` | 0 |
| `entry_count` | `INTEGER` | 1 | `0` | 0 |
| `confidence` | `TEXT` | 1 | `'Medium'` | 0 |
| `last_entry_id` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

### `portfolio_trades`

- Classification: Domain module
- Row count: 13
- Foreign keys: 3
- Indexes: 2
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["TRD", 13]], "batch_id": [["IBAT", 13]], "sheet_id": [["ISHT", 13]], "source_row_id": [["IROW", 13]]}
- JSON validity: {"raw_fields": {"valid": 13, "total": 13}, "metadata": {"valid": 13, "total": 13}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `batch_id` | `TEXT` | 0 | `` | 0 |
| `sheet_id` | `TEXT` | 0 | `` | 0 |
| `source_row_id` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `symbol` | `TEXT` | 1 | `` | 0 |
| `avg_price` | `REAL` | 1 | `` | 0 |
| `invested_amount` | `REAL` | 1 | `` | 0 |
| `shares` | `REAL` | 1 | `` | 0 |
| `sell_price` | `REAL` | 1 | `` | 0 |
| `returns_amount` | `REAL` | 1 | `` | 0 |
| `pnl_per_share` | `REAL` | 1 | `` | 0 |
| `pct_change` | `REAL` | 1 | `` | 0 |
| `volume_text` | `TEXT` | 1 | `` | 0 |
| `trade_date_text` | `TEXT` | 1 | `` | 0 |
| `hold_period_days` | `INTEGER` | 1 | `` | 0 |
| `account` | `TEXT` | 1 | `` | 0 |
| `raw_fields` | `TEXT` | 1 | `'{}'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `source_row_id` | `import_rows` | `id` | `NO ACTION` | `NO ACTION` |
| `sheet_id` | `import_sheets` | `id` | `NO ACTION` | `NO ACTION` |
| `batch_id` | `import_batches` | `id` | `NO ACTION` | `NO ACTION` |

### `pull_rules`

- Classification: Legacy memory/intelligence
- Row count: 2046
- Foreign keys: 1
- Indexes: 3
- Priority values: {"priority": ["Medium", "High"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["PULL", 200]], "entry_id": [["ESI", 200]]}
- JSON validity: {"metadata": {"valid": 2046, "total": 2046}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `entry_id` | `TEXT` | 0 | `` | 0 |
| `trigger_type` | `TEXT` | 0 | `` | 0 |
| `trigger_value` | `TEXT` | 0 | `` | 0 |
| `priority` | `TEXT` | 1 | `'Medium'` | 0 |
| `active` | `INTEGER` | 1 | `1` | 0 |
| `last_triggered` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |

### `relationships`

- Classification: Legacy memory/intelligence
- Row count: 428
- Foreign keys: 2
- Indexes: 3
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["REL", 200]], "from_entry_id": [["ESI", 192], ["IA", 8]], "to_entry_id": [["ESI", 200]]}
- JSON validity: {"metadata": {"valid": 428, "total": 428}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `from_entry_id` | `TEXT` | 0 | `` | 0 |
| `to_entry_id` | `TEXT` | 0 | `` | 0 |
| `relationship_type` | `TEXT` | 0 | `` | 0 |
| `note` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `to_entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |
| `from_entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |

### `risk_reward_setups`

- Classification: Domain module
- Row count: 2
- Foreign keys: 3
- Indexes: 2
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["RRS", 2]], "batch_id": [["IBAT", 2]], "sheet_id": [["ISHT", 2]], "source_row_id": [["IROW", 2]]}
- JSON validity: {"raw_fields": {"valid": 2, "total": 2}, "metadata": {"valid": 2, "total": 2}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `batch_id` | `TEXT` | 0 | `` | 0 |
| `sheet_id` | `TEXT` | 0 | `` | 0 |
| `source_row_id` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `calc_type` | `TEXT` | 1 | `` | 0 |
| `symbol` | `TEXT` | 1 | `` | 0 |
| `avg_price` | `REAL` | 1 | `` | 0 |
| `shares` | `REAL` | 1 | `` | 0 |
| `invested_amount` | `REAL` | 1 | `` | 0 |
| `trigger_price` | `REAL` | 1 | `` | 0 |
| `returns_amount` | `REAL` | 1 | `` | 0 |
| `pnl_per_share` | `REAL` | 1 | `` | 0 |
| `pct_change` | `REAL` | 1 | `` | 0 |
| `raw_fields` | `TEXT` | 1 | `'{}'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `source_row_id` | `import_rows` | `id` | `NO ACTION` | `NO ACTION` |
| `sheet_id` | `import_sheets` | `id` | `NO ACTION` | `NO ACTION` |
| `batch_id` | `import_batches` | `id` | `NO ACTION` | `NO ACTION` |

### `surfaced_cards`

- Classification: Legacy memory/intelligence
- Row count: 474
- Foreign keys: 2
- Indexes: 2
- Status values: {"status": ["archived", "open"]}
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"], "updated_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["CARD", 200]], "source_entry_id": [["IA", 180], ["ESI", 20]], "triggered_by_entry_id": [["IA", 200]]}
- JSON validity: {"action_card": {"valid": 474, "total": 474}, "metadata": {"valid": 474, "total": 474}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `updated_at` | `TEXT` | 0 | `` | 0 |
| `source_entry_id` | `TEXT` | 0 | `` | 0 |
| `triggered_by_entry_id` | `TEXT` | 1 | `` | 0 |
| `triggered_by_raw` | `TEXT` | 1 | `` | 0 |
| `score` | `INTEGER` | 1 | `0` | 0 |
| `reason` | `TEXT` | 1 | `` | 0 |
| `action_card` | `TEXT` | 1 | `'{}'` | 0 |
| `status` | `TEXT` | 1 | `'open'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `triggered_by_entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |
| `source_entry_id` | `entries` | `id` | `NO ACTION` | `NO ACTION` |

### `watchlist_items`

- Classification: Domain module
- Row count: 126
- Foreign keys: 4
- Indexes: 2
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["WLI", 126]], "watchlist_id": [["WL", 126]], "batch_id": [["IBAT", 126]], "sheet_id": [["ISHT", 126]], "source_row_id": [["IROW", 126]]}
- JSON validity: {"raw_fields": {"valid": 126, "total": 126}, "metadata": {"valid": 126, "total": 126}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `watchlist_id` | `TEXT` | 0 | `` | 0 |
| `batch_id` | `TEXT` | 0 | `` | 0 |
| `sheet_id` | `TEXT` | 0 | `` | 0 |
| `source_row_id` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `row_number` | `INTEGER` | 1 | `` | 0 |
| `display_name` | `TEXT` | 1 | `` | 0 |
| `ticker` | `TEXT` | 1 | `` | 0 |
| `sector` | `TEXT` | 1 | `` | 0 |
| `industry` | `TEXT` | 1 | `` | 0 |
| `catalyst` | `TEXT` | 1 | `` | 0 |
| `note` | `TEXT` | 1 | `` | 0 |
| `price` | `REAL` | 1 | `` | 0 |
| `peak_52w` | `REAL` | 1 | `` | 0 |
| `target_price` | `REAL` | 1 | `` | 0 |
| `support_price` | `REAL` | 1 | `` | 0 |
| `resistance_1` | `REAL` | 1 | `` | 0 |
| `resistance_2` | `REAL` | 1 | `` | 0 |
| `return_potential` | `REAL` | 1 | `` | 0 |
| `raw_fields` | `TEXT` | 1 | `'{}'` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `source_row_id` | `import_rows` | `id` | `NO ACTION` | `NO ACTION` |
| `sheet_id` | `import_sheets` | `id` | `NO ACTION` | `NO ACTION` |
| `batch_id` | `import_batches` | `id` | `NO ACTION` | `NO ACTION` |
| `watchlist_id` | `watchlists` | `id` | `NO ACTION` | `NO ACTION` |

### `watchlists`

- Classification: Domain module
- Row count: 8
- Foreign keys: 2
- Indexes: 2
- Timestamp formats: {"created_at": ["ISO-8601 +00:00 without fractional seconds"]}
- Identifier prefixes: {"id": [["WL", 8]], "batch_id": [["IBAT", 8]], "sheet_id": [["ISHT", 8]]}
- JSON validity: {"metadata": {"valid": 8, "total": 8}}

| Column | Type | Null | Default | PK |
| --- | --- | --- | --- | ---: |
| `id` | `TEXT` | 1 | `` | 1 |
| `batch_id` | `TEXT` | 0 | `` | 0 |
| `sheet_id` | `TEXT` | 0 | `` | 0 |
| `created_at` | `TEXT` | 0 | `` | 0 |
| `strategy_name` | `TEXT` | 0 | `` | 0 |
| `header_row` | `INTEGER` | 1 | `` | 0 |
| `item_count` | `INTEGER` | 1 | `0` | 0 |
| `notes` | `TEXT` | 1 | `` | 0 |
| `metadata` | `TEXT` | 1 | `'{}'` | 0 |

| FK column | Ref table | Ref column | On update | On delete |
| --- | --- | --- | --- | --- |
| `sheet_id` | `import_sheets` | `id` | `NO ACTION` | `NO ACTION` |
| `batch_id` | `import_batches` | `id` | `NO ACTION` | `NO ACTION` |

## Overlap Notes

- `entries` and `live_signals` are legacy signal-memory surfaces; `core_*` does not exist yet in the baseline.
- `ledger_projects` and `ledger_decisions` are transitional precursors to the normalized core concepts.
- `import_*`, `watchlists`, `watchlist_items`, `portfolio_trades`, and `risk_reward_setups` are domain/import infrastructure.
- `api_idempotency` and `audit_log` are operational support tables.
- All declared foreign keys pass `PRAGMA foreign_key_check`; `entries`/FTS shadows are search support tables rather than new data models.
