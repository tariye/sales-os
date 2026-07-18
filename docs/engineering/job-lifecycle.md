# Job Lifecycle

## Statuses

- `queued`
- `claimed`
- `running`
- `succeeded`
- `partial`
- `failed`
- `retry_scheduled`
- `dead_letter`
- `skipped_duplicate`

## Flow

1. Scheduler creates a due `queued` job with a deterministic `idempotency_key`.
2. Worker atomically claims one due job and moves it to `claimed`.
3. Worker moves the job to `running`, increments attempts, and creates an `ingest_run`.
4. Connector collection completes in one of four ways:
   - `succeeded`
   - `partial`
   - `skipped_duplicate`
   - failure path
5. Failure path:
   - `failed` ingest run is recorded
   - source failure counters update
   - retry is scheduled deterministically when attempts remain
   - terminal jobs move to `dead_letter`

## Recovery rules

- Claimed or running jobs carry a lease expiration timestamp.
- Expired claimed/running jobs are returned to `queued`.
- Recovery adds `lease_expired` error metadata for auditability.
- Retries do not create duplicate raw snapshots because raw insertion is protected by a uniqueness constraint.

## Retry policy

Milestone 1 uses bounded retry delays:

- attempt 1 retry: `+2s`
- attempt 2 retry: `+5s`
- attempt 3+ retry: `+10s`

The retry timestamp is stored in `next_retry_at`. A worker may only claim a retry once the timestamp is due.

## Ingest-run audit guarantees

Every collection attempt produces an `ingest_run`, including:

- successful pulls
- duplicate pulls
- partial pulls
- failed pulls
- retried pulls
