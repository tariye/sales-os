# Changelog

## Engineering Doctrine - Loop Principle - 2026-07-11

### Added

- Added `docs/engineering/loop-principle.md`.
- Added `tools/loop_check.py` as the executable user-loop checker.
- Added `docs/proof/loop-check-template.json`.
- README now points to the loop check command.

### Rule

No feature ships until it survives:

```text
Build -> Run -> Use -> Observe -> Fix -> Retest -> Document -> Commit
```

## v0.73-stock-intel-pilot - 2026-07-11

### Added

- Added standalone `stock_pattern_engine.py`.
- Added live stock analysis from ticker input using:
  - Yahoo chart data for price and one-year move.
  - Yahoo Finance RSS headlines for current news context.
  - SEC companyfacts for US company financial statements.
  - Local SQLite memory context for prior thesis/action resurfacing.
- Added `/api/stock/analyze`.
- Added `Stock Intel` tab with ticker input, optional company hint, `Analyze Stock`, and `Save To Memory`.
- Added conversion from stock analysis output into a normal Investing memory entry.

### Verified

- `python3 -m py_compile server.py stock_pattern_engine.py`
- Frontend element-reference check: no missing `id` references from `web/app.js`.
- `GET /api/health` returned `v0.73-stock-intel-pilot`.
- `POST /api/stock/analyze` for `AAPL` returned:
  - latest reported quarter revenue: `$111.18B`, period ending `2026-03-28`
  - latest annual revenue: `$416.16B`, fiscal year `2025`
  - extracted signal types: demand, profit, earnings, cash, market, news, memory
  - 8 local memory records
  - no source errors
- Save-to-memory path was tested by saving a temporary Apple stock entry and deleting it.

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
