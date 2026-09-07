# Core Event Gateway and Critical Alert Queue

## Scope

This milestone adds a single event-ingestion boundary and a shared critical alert queue on top of the normalized core tables.

Delivery is limited to the Command Center UI. There is no email, SMS, push notification, Slack, or browser automation channel in this phase.

## Boundaries

- `core_events` records observed reality.
- `core_signals` interprets events.
- `core_alerts` routes important signals to attention.
- `core_decisions` records the human, rule, AI, or joint response.
- `core_actions` stores normalized lifecycle actions created from decisions.
- Legacy `actions` remains unchanged and continues to serve the older memory-cockpit contract.

Normalized actions must not be written into the legacy `actions` table.

## Event Contract

### Endpoint

- `POST /events`

### Authentication

- External producers must send `Authorization: Bearer <token>`.
- The token must match `INFO_ANALYZER_API_KEY`.
- Comparison uses constant-time equality.
- If the API key is not configured, external event ingestion is disabled with a `503` response.

### Required fields

- `source_system_id`
- `event_type`
- `occurred_at`

### Optional fields

- `entity_id`
- `observed_at`
- `dedupe_key`
- `source_ref`
- `correlation_id`
- `causation_event_id`
- `priority`
- `confidence`
- `payload`

### Validation rules

- Request body must be a JSON object.
- Unknown fields are rejected.
- Timestamps must be timezone-aware ISO-8601 and are normalized to UTC.
- Priority must be `P0`, `P1`, or `P2`.
- Confidence must be between `0` and `1`.
- Payload must be a JSON object.
- Referenced `core_systems`, `core_entities`, and `core_events` rows must exist when referenced.
- Request bodies are size-limited.
- Payloads are stored as JSON only. No code is executed from payload content.

### Idempotency

- Deduplication key: `source_system_id + dedupe_key`
- First accepted delivery returns `201`.
- Duplicate delivery returns `200` and the original event.
- Missing `dedupe_key` means a new observation each time.
- The same dedupe key may be reused by different source systems.

## Alert Queue Policy

### Promotion rules

- Promote every new `P0` signal.
- Promote `P1` signals only when `actionability_score >= 0.70`.
- Never auto-promote `P2`.
- At most one open alert exists per signal.

### Retrieval

- `GET /alerts`
- Returns actionable open alerts ordered by priority, then oldest ready alert first.
- Excludes resolved, dismissed, future scheduled, and actively snoozed alerts.

### State model

Allowed alert states:

- `queued`
- `presented`
- `acknowledged`
- `snoozed`
- `dismissed`
- `actioned`
- `resolved`
- `failed`

Allowed responses:

- `acknowledge`
- `analyze`
- `snooze`
- `dismiss`
- `convert_to_action`

### State transitions

- `queued -> acknowledged`
- `queued -> presented`
- `queued -> snoozed`
- `queued -> dismissed`
- `queued -> actioned`
- `presented -> acknowledged`
- `presented -> snoozed`
- `presented -> dismissed`
- `presented -> actioned`
- `acknowledged -> snoozed`
- `acknowledged -> dismissed`
- `acknowledged -> actioned`
- `snoozed -> queued` when the snooze expires and the queue is re-evaluated
- terminal states reject repeat terminal transitions

Each response writes a `core_decisions` row and a `core_alert_decisions` relationship.

### Convert to Action

`convert_to_action` creates a normalized `core_actions` row linked to the decision that produced it.

Legacy `actions` is not modified by this flow.

## API Examples

### Example event

```json
{
  "source_system_id": "sys_info_analyzer",
  "event_type": "file.created",
  "occurred_at": "2026-09-07T12:00:00.000Z",
  "dedupe_key": "inbox/weekly-note.txt",
  "priority": "P1",
  "confidence": 0.95,
  "payload": {
    "path": "Inbox/weekly-note.txt"
  }
}
```

### Example alert response

```json
{
  "response": "acknowledge",
  "decided_by": "human",
  "note": "Reviewed in the Command Center."
}
```

## Delivery Limitation

This phase is intentionally limited to the Command Center. Proactive push delivery and external notification channels are future work.
