# Authenticated Ledger API

GitHub owns the product code and compact memory exports. SQLite owns persistent intelligence. The API is the controlled bridge that lets chats read and write memory without directly editing the database file.

## Security

Set an API key before starting the server:

```bash
export INFO_ANALYZER_API_KEY="replace-with-a-secret"
python3 server.py --host 0.0.0.0 --port 8000
```

Clients authenticate with either header:

```text
Authorization: Bearer <INFO_ANALYZER_API_KEY>
```

or:

```text
X-Info-Analyzer-Key: <INFO_ANALYZER_API_KEY>
```

Only `/api/v1/*` requires this key. Existing local browser endpoints remain unchanged.

## First Cross-Chat Loop

The minimum intelligence loop is:

1. **Write**: `POST /api/v1/entries`
2. **Retrieve**: `GET /api/v1/entries/search?q=...`
3. **Act**: `GET /api/v1/critical_alerts`, then `PATCH /api/v1/alerts/{id}/acknowledge`
4. **Learn**: `POST /api/v1/feedback` or `PATCH /api/v1/actions/{id}/feedback`

## Endpoints

### Health

```http
GET /api/v1/health
```

### Save Entry

```http
POST /api/v1/entries
Content-Type: application/json
```

Body:

```json
{
  "raw_input": "Signal from chat...",
  "domain": "Info Analyzer OS",
  "entity": "Cross-chat memory",
  "signal": "What matters",
  "signal_role": "system_milestone",
  "trackable_as": "acceptance_test",
  "tracking_metric": "Search from another chat and log result",
  "returned_action": "Run the cross-chat retrieval test",
  "source_chat": "chatgpt-main"
}
```

### Search Entries

```http
GET /api/v1/entries/search?q=memory&domain=Info%20Analyzer%20OS&limit=10
```

### Related Context

```http
POST /api/v1/context
```

Body:

```json
{
  "raw_input": "What context should resurface?",
  "domain": "Info Analyzer OS",
  "entity": "Cross-chat memory",
  "save_cards": true
}
```

### Action Queue

```http
GET /api/v1/action_queue?status=open&limit=10
```

### Critical Alerts

```http
GET /api/v1/critical_alerts?limit=5
```

### Acknowledge Alert

```http
PATCH /api/v1/alerts/{alert_id}/acknowledge
```

Body:

```json
{
  "status": "waiting",
  "note": "Acknowledged by chat; waiting on result."
}
```

### Log Feedback

```http
POST /api/v1/feedback
```

Body:

```json
{
  "entry_id": "IA-...",
  "action_id": "ACT-...",
  "status": "done",
  "result": "The cross-chat loop worked.",
  "lesson": "API is the right live memory bridge.",
  "confidence": "High",
  "playbook_relationship": "validates"
}
```

### Update Decision

```http
PATCH /api/v1/decisions/{decision_id}
```

For canonical ledger decisions, body may include:

```json
{
  "current_position": "watch",
  "confidence": "Medium",
  "tracking_metric": "Updated metric",
  "related_query": "new query"
}
```

For decision review objects, body may include:

```json
{
  "result": "Decision result",
  "rule_update": "Updated rule",
  "outcome": "success"
}
```

## Storage Rules

- Raw input is preserved in SQLite.
- API writes include `source_chat` and `source_input` metadata.
- Destructive delete is not exposed in v1.
- Every change is audited in `audit_log`.
- GitHub memory exports remain generated artifacts, not the live database.
