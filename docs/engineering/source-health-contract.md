# Source Health Contract

Source health is first-class in Milestone 1. Historical data is never enough by itself to show a source as healthy.

## Health states

- `never_run`
- `healthy`
- `stale`
- `failed`

## Inputs

For each source the health view exposes:

- `active`
- `last_attempt_at`
- `last_success_at`
- `last_error_at`
- `consecutive_failures`
- `freshness_target_seconds`
- `current_age_seconds`
- `stale`
- `latest_ingest_status`
- `latest_row_count`
- `latest_payload_hash`
- `queued_jobs`
- `running_jobs`
- `dead_letter_jobs`
- scheduler leadership status
- worker heartbeat status

## Rules

1. `never_run`: no recorded attempt
2. `failed`: one or more consecutive failures, or latest ingest attempt failed/retry/dead-lettered
3. `stale`: no current failure, but freshness age exceeds `freshness_target_seconds`
4. `healthy`: latest successful state is fresh and no current failure exists

## Event generation

Milestone 1 creates source-health events for:

- `source_failure`
- `source_stale`
- `source_recovered`

The minimum acceptance requirement is that failed and stale states emit events. Recovery and duplicate audit events are additive.

## Freshness semantics

Freshness is based on the age of the latest successful or attempted collection relative to `freshness_target_seconds`. The UI must never present stale data as current.
