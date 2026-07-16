# Render Deployment + ChatGPT Action Bridge

This is the v0.87++++ operational path: deploy the existing API to stable HTTPS, connect the OpenAPI schema to a private GPT Action, then run the first real cross-chat memory loop.

## Why Render First

Render is a practical first host for the single-user SQLite stage because it can deploy directly from GitHub, provide a public HTTPS URL, store secrets as environment variables, attach a persistent disk, and snapshot that disk daily.

Important constraints:

- Without a persistent disk, service filesystem writes are ephemeral across restarts and redeploys.
- Only files written under the disk mount path persist.
- A persistent disk is attached to one service instance at runtime, so this setup is single-instance only.
- A disk-backed service should not be horizontally scaled.
- Use database-level backups in addition to provider disk snapshots.

## Blueprint

The repo includes:

```text
render.yaml
```

It defines:

```text
Runtime: Python
Branch: main
Build: pip install -r requirements.txt && python -m py_compile server.py
Start: python server.py --host 0.0.0.0 --port $PORT
Persistent DB: /var/data/info_analyzer.db
Disk mount: /var/data
Health check: /api/health
```

`/api/health` is used as Render's health check because Render does not send your API key. The authenticated API contract remains `/api/v1/health`.

## Render Setup

1. Create a Render Blueprint or Web Service connected to:

```text
https://github.com/tariye/sales-os
```

2. Use branch:

```text
main
```

3. If not using the blueprint, configure manually:

```text
Runtime: Python
Build command: pip install -r requirements.txt && python -m py_compile server.py
Start command: python server.py --host 0.0.0.0 --port $PORT
Health check path: /api/health
```

4. Set environment variables:

```text
INFO_ANALYZER_API_KEY=<strong-random-secret>
INFO_ANALYZER_DB_PATH=/var/data/info_analyzer.db
```

5. Attach a persistent disk:

```text
Mount path: /var/data
Initial size: 1 GB or the smallest available
```

Only files under `/var/data` persist. The SQLite database and local backups must live there.

## Deployment Acceptance

Replace the host and key:

```bash
export INFO_ANALYZER_API_KEY="your-render-secret"
export INFO_ANALYZER_URL="https://YOUR-SERVICE.onrender.com"
```

Public health check:

```bash
curl "$INFO_ANALYZER_URL/api/health"
```

Expected:

```json
{
  "ok": true,
  "version": "v0.87-external-runtime-chat-bridge"
}
```

Unauthenticated API v1 check:

```bash
curl "$INFO_ANALYZER_URL/api/v1/health"
```

Expected stable 401 envelope:

```json
{
  "success": false,
  "data": {},
  "error": {
    "code": "unauthorized"
  },
  "request_id": "..."
}
```

Authenticated API v1 check:

```bash
curl \
  -H "Authorization: Bearer $INFO_ANALYZER_API_KEY" \
  "$INFO_ANALYZER_URL/api/v1/health"
```

Expected:

```json
{
  "success": true,
  "data": {
    "ok": true,
    "sqlite": {
      "journal_mode": "wal",
      "foreign_keys": true,
      "busy_timeout_ms": 5000,
      "quick_check": "ok",
      "persistent_path_configured": true
    }
  },
  "error": null,
  "request_id": "..."
}
```

Remote API loop:

```bash
python3 tools/remote_action_check.py \
  --base-url "$INFO_ANALYZER_URL" \
  --api-key "$INFO_ANALYZER_API_KEY"
```

Cross-chat acceptance:

```bash
python3 tools/cross_chat_acceptance.py \
  --base-url "$INFO_ANALYZER_URL" \
  --api-key "$INFO_ANALYZER_API_KEY"
```

The deployment gate passes only when the hosted service, not localhost, passes both scripts.

## Connect the Private GPT

Create a private GPT that acts as the Info Analyzer cockpit.

In the GPT editor:

```text
Configure
Actions
Create new action
Import docs/openapi/info-analyzer-v1.yaml
Authentication: API key
```

Use bearer authentication:

```text
Authorization: Bearer <INFO_ANALYZER_API_KEY>
```

Set the server URL to:

```text
https://YOUR-SERVICE.onrender.com
```

The OpenAPI schema already includes `/api/v1/...` in each path, so the Action server URL should be the host root, not `/api/v1`.

## GPT Cockpit Instructions

Use this as the private GPT instruction core:

```text
You are the Info Analyzer OS cockpit.

Use the connected Info Analyzer API as the persistent source of truth.

When the user supplies meaningful raw information:
1. Analyze it.
2. Extract the situation, signal, pattern, decision, action,
   expected result, tracking metric, resurfacing trigger,
   and feedback to capture.
3. Search the existing ledger for related context.
4. Create the entry using an Idempotency-Key.
5. Surface any related critical alerts or open actions.
6. Never delete prior memory.
7. New evidence must validate, contradict, expand, refine,
   or supersede earlier memory.
8. After an action, capture feedback and update the original
   decision without overwriting its historical state.
```

A private GPT Action is available inside that GPT's conversations. It is not automatically available to unrelated ChatGPT conversations.

## First Live Cross-Chat Test

Conversation A:

```text
Save this as an Info Analyzer entry:

Repeated operator setup errors continue after verbal coaching.
The likely bottleneck is knowledge transfer rather than effort.
Test a visual setup checklist and measure independent completion
time and setup-error count.
```

Conversation B in the same private GPT:

```text
Search Info Analyzer for operator setup errors and knowledge-transfer
bottlenecks. Return the most relevant memory, related context,
open action, and critical alert.
```

Then:

```text
Acknowledge the alert and convert it into a tracked action.
```

Conversation C after testing:

```text
Log this result:

The checklist reduced setup errors from three to one and required
less coaching intervention. Update the original memory and its
confidence without deleting the prior state.
```

The product is live when one chat writes, another retrieves, the user acts, and a later chat records reality back into the same decision model.
