# Sales OS

Local MVP for the demand-intel workflow.

## What it does

- tracks researched items
- calculates net profit and net margin
- applies the pilot `BUY` / `PASS` rule
- ranks items with a simple signal score
- links sale price and buy price to evidence URLs
- adds a separate manual Google Trends lane with its own evidence URL
- adds a separate manual local-market comps lane with its own evidence URL
- includes a separate trend page for sales-volume momentum across snapshots
- includes a discovery feed for high-volume products beyond the fixed watchlist
- includes a changelog page for build history
- exports the current ledger as CSV
- stores edits in local browser storage
- supports a scheduler-backed ingest from your logged-in eBay Seller Hub Chrome session

## Seed data included

The app starts with live eBay Product Research metrics gathered on `2026-07-03` for:

- iMac 21.5 2011
- 2012 MacBook Pro 13
- Nissan Altima driver door handle
- Nissan Altima instrument cluster
- Raspberry Pi 4 Model B 4GB
- Raspberry Pi 5 8GB
- NVIDIA Jetson Nano Developer Kit
- BeagleBone Black

## Source lanes

- `Sold demand`: eBay Product Research / sold comps
- `Source cost`: buy-price evidence URLs and notes
- `Attention`: manual Google Trends capture with keyword, window, direction, score, and evidence URL
- `Local market comps`: manual Facebook Marketplace, OfferUp, Craigslist, or Mercari count, ask price, and evidence URL

The Google Trends lane is displayed in the ledger but does not change the pilot `BUY` / `PASS`
rule or the sold-demand signal score.

The local-market comps lane is also displayed separately and does not change the pilot `BUY` / `PASS`
rule or the sold-demand signal score.

## Pilot rule

- net profit `>= $20`
- net margin `>= 30%`
- sales volume `>= 5`

## Files

- `index.html`: app shell
- `trends.html`: trend monitor page
- `changelog.html`: build/version history
- `styles.css`: visual layout
- `app.js`: ledger logic, scoring, persistence, export
- `trends.js`: snapshot logic, momentum ranking, realtime browser refresh
- `evidence.html`: source-cost rationale for seeded pilot buy-price assumptions
- `data/watchlist.json`: tracked eBay research queries and sourcing assumptions
- `data/discovery-seeds.json`: broad-market seeds used to discover products like iPhone 13
- `data/live-data.json`: generated research output and snapshot history
- `data/live-data.js`: browser-consumable version of the generated research output
- `scripts/update_research.rb`: Chrome/eBay Seller Hub ingest script
- `server.rb`: local server for localhost access and button-triggered fresh pulls
- `launchd/com.salesos.research-ingest.plist`: 30-minute launch agent template

## Automated ingest

The updater script reads `data/watchlist.json`, uses your logged-in Chrome session on
`Seller Hub > Product Research`, and rewrites:

- `data/live-data.json`
- `data/live-data.js`

It also appends a new snapshot on each run.

Discovery mode:

- broad seeds such as `iPhone`, `Samsung Galaxy`, `MacBook`, `iPad`, and `PS5`
- result-title normalization into product names like `iPhone 13`
- high-volume feed exposed by the `Find Market Trends` button on the trend page

Installed scheduler:

- label: `com.salesos.research-ingest`
- interval: every `1800` seconds
- target script: `scripts/update_research.rb`

## Use it

For static viewing, open `index.html` directly in a browser.

For button-triggered fresh pulls, run:

```bash
ruby server.rb
```

Then open:

- `http://127.0.0.1:4173/index.html`
- `http://127.0.0.1:4173/trends.html`

`Run Fresh Pull` calls the local `/api/run-refresh` endpoint, runs `scripts/update_research.rb`,
rewrites `data/live-data.json` and `data/live-data.js`, and reloads the newest generated data into
the page.
