# Info Analyzer OS

Local SQLite intelligence ledger for trackable signals, contextual memory, pull rules, action cards, and pattern scans.

## Core doctrine

Non-trackable signal is useless. Make every signal trackable and actionable.

Info Analyzer OS is not a note warehouse. It is a resurfacing engine:

`raw rep -> codified memory -> trackable signal -> pull rules -> resurfaced action cards -> result / lesson update`

## What this version does

- stores entries in SQLite
- keeps raw input attached as evidence
- adds trackability fields and pull rules
- resurfaces actionable memory in the Command Center
- turns cockpit callouts into resolver cards with buttons
- exposes returned actions, dormant info, and pattern insights
- supports contextual memory chips and database rewiring
- runs on a local web UI

## Current build

Current version: `v0.72-command-resolver`

Proof artifacts:

- [CHANGELOG.md](CHANGELOG.md)
- [ADR 0001: Command Center Resolver](docs/adr/0001-command-center-resolver.md)
- [v0.72 proof entry](docs/proof/v0.72-command-resolver.json)

## Run locally

```bash
cd "/Users/admin/Library/Mobile Documents/com~apple~CloudDocs/Downloads/info_analyzer_os_sqlite_v0_3_clean"
python3 server.py --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

For phone access on the same Wi-Fi:

```bash
python3 server.py --host 0.0.0.0 --port 8000
```

## Database

The SQLite database lives at:

```text
data/info_analyzer.db
```

The live database is intentionally excluded from git. This repository should track code, docs, and UI assets, not runtime state.

## GitHub Migration Boundary

For GitHub, treat this project as:

- code, docs, prompts, and UI assets in git
- the live SQLite database out of git

The default `.gitignore` excludes the database, journal files, caches, logs, and large workbook artifacts so the repo stays portable and you do not accidentally sync live runtime state as source code.

## Key endpoints

- `GET /api/health`
- `GET /api/command`
- `POST /api/entries`
- `POST /api/pull`
- `POST /api/context/rewire`
- `POST /api/surfaced-cards/clear`
- `GET /api/patterns`
- `GET /api/export`

## Notes

The Command Center is the operator surface.
The Translation Layer is where raw input becomes trackable memory.
The Memory Chip is the contextual layer that helps old memory resurface when new context makes it useful again.
