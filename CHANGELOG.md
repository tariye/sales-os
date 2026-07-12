# Changelog

## v0.72-command-resolver - 2026-07-11

Commit: `7ff5801`

### Changed

- Turned Command Center callouts into resolver cards with button metadata.
- Added cockpit actions for reviewing actions, detecting bottlenecks, running pattern scans, opening the queue, rewiring memory, focusing pull queries, and clearing surfaced cards.
- Added `/api/surfaced-cards/clear` to archive open surfaced cards while preserving source entries.
- Split Sales OS pull cards into market/resale signals versus CRM pipeline signals.
- Corrected trending-item sales metrics to track sell-through, acquisition cost, gross margin, days-to-sale, inventory turns, and result logging.
- Removed full contextual-memory rebuild from startup so the server binds quickly; `Rewire Memory` now owns that heavy operation.
- Updated frontend version label to `v0.72`.

### Verified

- `python3 -m py_compile server.py`
- Frontend element-reference check: no missing `id` references from `web/app.js`.
- `GET /api/health` returned `v0.72-command-resolver`.
- `GET /api/command` returned resolver buttons on warnings, cautions, and advisories.
- `POST /api/pull` with `sales` and `Business` returned the trending phone-sourcing card first with the corrected resale metric.
- Startup `init_db()` completed in roughly 0.21 seconds after removing automatic memory rewiring.

