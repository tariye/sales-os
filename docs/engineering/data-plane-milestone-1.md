# Data Plane Milestone 1

Milestone 1 is the durable ingestion backbone only:

`Source -> Scheduled Job -> Claimed Job -> Ingest Run -> Immutable Raw Snapshot -> Source Health`

This release does not include entity resolution, normalized observations, merchant projections, signals, decisions, AI interpretation, or action/outcome loops.

## Runtime model

- One SQLite database, resolved from `INFO_ANALYZER_DB_PATH`
- `PRAGMA journal_mode=WAL`
- `PRAGMA foreign_keys=ON`
- `PRAGMA busy_timeout=5000`
- One web process
- One background scheduler thread
- One background worker thread
- One database-backed scheduler lease

The browser UI is not part of collection. The scheduler and worker continue without the UI open.

## Milestone 1 tables

- `sources`
- `jobs`
- `ingest_runs`
- `raw_snapshots`
- `source_health_events`
- `scheduler_leases`
- `quarantined_snapshots`
- `normalization_failures`
- `schema_migrations`

## Connector contract

Milestone 1 implements one deterministic fixture connector:

- `connector_name`
- `connector_version`
- `source_type`
- `validate_configuration()`
- `collect()`
- `health_check()`

`collect()` returns raw payload, content type, captured time, evidence URL, and collection metadata. Normalization is intentionally deferred to Milestone 2.

## Deduplication and immutability

- Jobs: unique `idempotency_key`
- Raw snapshots: unique `(source_id, payload_hash, captured_bucket)`
- Raw snapshots are append-only
- Duplicate pulls still create ingest runs
- Duplicate pulls do not create duplicate raw snapshots

`captured_bucket` is an integer epoch-second bucket computed from `captured_at` using each source's explicit `captured_bucket_seconds`. The fixture source uses `300` seconds.

## Fixture coverage

The fixture connector supports deterministic scenarios for:

- successful payload
- repeated identical payload
- changed payload
- collection failure
- partial result
- delayed result
- stale-source test seeding

## Thin UI

Milestone 1 adds one read-only `System Health` tab. It displays stored runtime and source state immediately and does not trigger collection when opened.
