# ADR 0002: Stock Intel Pilot

Date: 2026-07-11

Status: Accepted

## Context

Info Analyzer OS is becoming an intelligence ledger rather than a note app. The user wants to post weekly plans such as "explore SK Hynix" and have the system return current news, financial context, and prior stored memory that refreshes the thesis.

The requested stock workflow is:

1. Enter a company or ticker.
2. Return quick company intelligence.
3. Include last reported quarter and latest annual numbers.
4. Add deeper analysis over time.
5. Start separate from the main system.
6. Integrate only after the standalone engine proves useful.

## Decision

Create a standalone `stock_pattern_engine.py` before integrating the feature into the website.

The engine returns one structured intelligence card with:

- company identity
- live quote context
- latest headlines
- SEC companyfacts financials for US tickers
- local memory matches from the SQLite ledger
- extracted demand/profit/earnings/cash/market/news/memory signals
- a decision frame with action, next step, tracking metric, and resurfacing trigger

After validating Apple (`AAPL`), expose the engine through:

- `POST /api/stock/analyze`
- `GET /api/stock/analyze`
- `Stock Intel` frontend tab
- `Save To Memory`, which converts the analysis into a standard Investing entry

## Consequences

The stock engine now teaches a repeatable workflow before being absorbed into the main Command Center:

- external market data enters as source evidence
- financial statement facts are normalized into decision metrics
- old memory resurfaces next to new data
- stock analysis can become a trackable ledger entry

Tradeoff: the first version relies on public Yahoo endpoints and SEC companyfacts. That is acceptable for a pilot but should later be upgraded with provider health checks, cache snapshots, and source confidence flags.

## Follow-Up

- Add caching so repeated ticker analysis does not hit public sources every time.
- Add SK Hynix-specific foreign issuer support beyond quote/news.
- Add valuation metrics and segment analysis.
- Add "weekly plan" ingestion so a plan like "explore SK Hynix this week" creates a watch trigger.
- Add a Command Center lane for stock watch plans and active company research.

