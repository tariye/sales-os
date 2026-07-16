# ChatGPT Action Deployment Setup

Info Analyzer OS v0.86 prepares the authenticated ledger API for a private Custom GPT Action.

## Architecture

```text
GitHub
  code, migrations, docs, tests, generated memory exports

Hosted API
  INFO_ANALYZER_API_KEY
  persistent SQLite volume
  HTTPS endpoint

Private Custom GPT Action
  OpenAPI schema
  API key authentication
  controlled read/write access to the ledger
```

GitHub is not the live memory bus. SQLite is the source of truth. The API is the live access layer.

## HTTPS Requirement

The Custom GPT Action should point at a stable HTTPS base URL, for example:

```text
https://api.yourdomain.com
```

Do not use `http://127.0.0.1:8000` for real chat access. Localhost only works from the same machine and will not be reachable by ChatGPT.

Recommended deployment shape:

```text
reverse proxy / platform HTTPS
        ↓
python3 server.py --host 0.0.0.0 --port 8000
        ↓
persistent data/info_analyzer.db volume
```

## Secret Handling

Set the key in the host environment:

```bash
export INFO_ANALYZER_API_KEY="replace-with-a-long-random-secret"
```

Never commit this key to GitHub. It must not be written to proof files, memory exports, logs, or docs.

Clients may authenticate with either:

```text
Authorization: Bearer <secret>
```

or:

```text
X-Info-Analyzer-Key: <secret>
```

## Persistent SQLite Volume

The live database path is:

```text
data/info_analyzer.db
```

For cloud hosting, mount `data/` on persistent storage. If the deployment uses ephemeral disk, every restart can lose live intelligence.

`data/info_analyzer.db` must remain excluded from GitHub.

## Backup Procedure

Use SQLite's online backup command while the service is stopped or lightly loaded:

```bash
sqlite3 data/info_analyzer.db ".backup 'backups/info_analyzer-$(date +%Y%m%d-%H%M%S).db'"
```

Then export compact memory state:

```bash
python3 tools/memory_manager.py
```

Commit only generated memory exports, docs, tests, and code. Do not commit the live SQLite database.

## Custom GPT Action Configuration

In the GPT editor:

1. Open `Configure`.
2. Open `Actions`.
3. Create a new action.
4. Import:

```text
docs/openapi/info-analyzer-v1.yaml
```

5. Set authentication to API key.
6. Use either bearer auth or the custom header expected by the server:

```text
Authorization: Bearer <secret>
```

or:

```text
X-Info-Analyzer-Key: <secret>
```

7. Set the server URL in the imported schema to the deployed HTTPS API URL.

## Cross-Chat Acceptance Test

Chat A:

```text
Save this as an Info Analyzer ledger entry:
Repeated operator setup errors suggest the training system is not transferring knowledge consistently.
```

Expected:

```text
Created: IA-...
```

Chat B:

```text
Search Info Analyzer for operator training and retrieve the most relevant memory, open action, and pattern.
```

Expected:

- Original entry returned
- Related context returned
- Open alert or action returned

Then:

```text
Acknowledge the alert and convert it to a tracked action.
```

Finally:

```text
Log that the checklist reduced setup errors and strengthen the original thesis.
```

The test passes only if the second chat can retrieve and update memory created by the first chat through the API.

## Automated Checks

Validate the OpenAPI contract:

```bash
python3 tools/validate_openapi.py --write-proof docs/proof/v0.86-openapi-validation.json
```

Run the API loop locally:

```bash
INFO_ANALYZER_API_KEY=local-v1-proof-key python3 server.py --host 0.0.0.0 --port 8000
python3 tools/api_v1_loop_check.py --base-url http://127.0.0.1:8000 --api-key local-v1-proof-key
```

Run the deployed Action test:

```bash
python3 tools/remote_action_check.py --base-url https://api.yourdomain.com --api-key "$INFO_ANALYZER_API_KEY"
```
