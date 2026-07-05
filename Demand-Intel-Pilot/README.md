# Demand Intel Pilot

Files:

- `demand_ledger_pilot.csv`: spreadsheet-ready pilot ledger with 10 starter rows and formulas

Pilot rules:

- Research window: `Last 30 Days`
- Minimum sales volume: `5`
- Minimum net profit: `$20`
- Minimum net margin: `30%`

Columns to fill manually:

- `Average Sale Price`
- `Sales Volume`
- `Buying Price`
- `Fees`
- `Shipping`
- `Supplies`

Formula columns already included:

- `Net Profit`
- `Net Margin %`
- `Decision`

Use the pilot in this order:

1. Fill the six manual input columns for each item.
2. Review `Decision`.
3. Add notes only when they change the route or risk.
4. Do not buy items marked `PASS`.

Current file state:

- Rows 2-5 now use live eBay Seller Hub Product Research sold-data metrics gathered on `2026-07-03`.
- The model/fitment assumptions in those rows are still generic because they are based on chosen search terms, not your exact serial-number or part-number inventory.
- Replace them once you have exact item-specific comps.
