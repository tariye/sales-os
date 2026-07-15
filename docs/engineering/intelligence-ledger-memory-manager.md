# Intelligence Ledger Memory Manager

Info Analyzer OS uses SQLite as the source of truth. GitHub is the transport layer that lets ChatGPT and other agents consume a compact operating state without reading the whole database.

## Contract

Agents should start with:

1. Read `memory/index.json`.
2. Confirm `memory/system_health.json` has `export_success: true`.
3. Load `memory/snapshots/latest.json`.
4. Read only the files referenced by the index.
5. Write new memory candidates to `memory/chat_inbox.jsonl`.

The required memory files are:

- `memory/index.json`
- `memory/snapshots/latest.json`
- `memory/actions.jsonl`
- `memory/patterns.jsonl`
- `memory/watchlist.jsonl`
- `memory/entries.jsonl`
- `memory/chat_inbox.jsonl`
- `memory/export_status.json`
- `memory/briefing_manifest.json`
- `memory/system_health.json`
- `memory/activity.jsonl`
- `memory/decisions.jsonl`
- `memory/projects.jsonl`

## Operating Principle

The memory layer should answer:

> What matters right now?

It should not answer:

> What have we ever talked about?

SQLite stores full evidence. The memory directory stores summarized, validated, current operating state.

## Daily Export

Run:

```bash
python3 tools/memory_manager.py
```

To import `memory/chat_inbox.jsonl`, regenerate exports, validate, commit, and push:

```bash
python3 tools/memory_manager.py --git
```

The exporter will refuse to push if validation fails.

## Chat Inbox Schema

Each line in `memory/chat_inbox.jsonl` should be a JSON object. Minimum useful shape:

```json
{"raw_input":"The user said X. Hidden signal Y. Returned action Z.","domain":"Business","entity":"Sales OS","tags":["sales","pricing"]}
```

Useful optional fields:

- `title`
- `source_type`
- `signal`
- `interpretation`
- `returned_action`
- `tracking_metric`
- `trigger_condition`
- `lesson`
- `confidence`
- `actionability`
- `first_step`
- `impact_metric`
- `feedback_to_capture`

Raw input is never discarded. Imported inbox records are archived under `memory/archive/`.

## Lifecycle Rule

Every object should move through a lifecycle:

`idea -> investigating -> building -> testing -> validated -> operational -> archived`

Actions, projects, watchlist items, decisions, lessons, and patterns should be updated in place when possible instead of duplicated.
