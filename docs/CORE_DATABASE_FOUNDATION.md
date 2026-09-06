# Core Database Foundation

This report records the combined database probe and the first normalized core migration layered onto the canonical v0.3 database.

## Probe Summary

- Canonical database: `data/info_analyzer.db`
- SQLite version: `3.53.2`
- Database size: `6762496` bytes
- `PRAGMA journal_mode`: `wal`
- `PRAGMA foreign_keys`: `0` on a raw probe connection
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: no rows
- Legacy schema inventory before migration: 33 tables, 0 views, 0 triggers

Application connection enforcement:

- canonical helper: `core_database.connect()`
- `PRAGMA foreign_keys`: `1`
- `PRAGMA busy_timeout`: `5000`
- `PRAGMA journal_mode`: `wal`

### Legacy classification at probe time

1. Legacy memory/intelligence
1. Ingestion infrastructure
1. Decision/action infrastructure
1. Domain module
1. Operational/audit infrastructure
1. Normalized core candidate
1. Transitional or uncertain

The detailed per-table classification, column inventory, row counts, JSON validity, timestamp formats, identifier formats, and `server.py` usage summary are preserved in `docs/COMBINED_DB_PROBE.md`.

## Final Combined Architecture

The canonical v0.3 database remains the source of truth. The normalized lifecycle was added as a namespaced core that coexists with the legacy schema:

- `core_systems`
- `core_entities`
- `core_goals`
- `core_events`
- `core_signals`
- `core_signal_events`
- `core_signal_goals`
- `core_alerts`
- `core_decisions`
- `core_actions`
- `core_outcomes`
- `core_lessons`
- `core_lesson_outcomes`
- `core_record_links`
- `core_alert_decisions`

Compatibility is intentionally bridge-based:

- legacy `entries` remains the memory/intelligence surface
- legacy `actions` remains the original memory-cockpit action table
- `core_*` records represent the normalized lifecycle
- `core_record_links` carries deterministic provenance links between old and new records without copying or rewriting the legacy content

Core views added:

- `v_core_open_alerts`
- `v_core_learning_loop`

## Migration Foundation

Migration runner:

- `schema_migrations` added as the migration ledger
- ordered additive SQL migrations under `migrations/`
- transactional application
- visible failure on migration error
- idempotent re-run behavior

First migration:

- `migrations/001_core_foundation.sql`

This migration creates the core namespace, supporting indexes, the two core views, and a seed row for the `sys_info_analyzer` core system.

## Preservation Results

Validation was run against the canonical database copied to a working file before migration.

### Table counts

- Pre-migration tables: 33
- Post-migration tables: 49
- Post-migration views: 2

### Legacy data preservation

- Legacy row counts were unchanged for all 33 legacy tables after migration.
- Existing records remained readable.
- Legacy `actions` schema and behavior remained unchanged.

### Integrity

- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: no violations

### Migration ledger

- `schema_migrations` contains exactly one applied migration:
  - `1 | core_foundation | 2026-09-06T23:00:07.669Z`

## Validation Results

Foundation test suite:

- `tests.test_core_database_foundation`
- 12 tests passed

The suite covered:

- fresh v0.3 initialization
- canonical connection helper FK enforcement
- migration of an existing v0.3 database copy
- idempotent re-initialization
- legacy table presence and readability
- legacy `actions` schema preservation
- core `core_actions` lifecycle schema
- core FK / JSON / enum-style constraint enforcement
- integrity and FK checks
- rollback on failed migration
- migration ledger idempotence
- existing API/UI startup on localhost

## Remaining Schema Risks

- The legacy bootstrap initializer still does not create every historical table that exists in the canonical database image, notably the `ledger_*` tables. Those tables are preserved in the canonical DB and unchanged by the core migration, but they remain a transitional legacy surface rather than part of the new core bootstrap.
- The normalized core is additive only. No legacy tables were rewritten or retired.
- No `/events` endpoint or domain-specific producers were added in this phase.

## Ready For Next Phase

Yes.

The core foundation is ready for the next phase: a single `/events` endpoint layered on top of the new normalized core and legacy bridge, without changing the legacy action table contract.
