# Data Architecture Guide

How data flows, is stored, and should be handled in this portfolio tracker. Follow these principles for all future development.

---

## Core Principle: Compute Once, Read Many

The #1 lesson from building this app: **never recompute what can be precomputed and stored.** Financial data changes at known intervals (market close, trade entry), not on every page load.

| Pattern | Bad | Good |
|---------|-----|------|
| Portfolio value | Replay 2,058 trades on every request | Read precomputed snapshot (1 doc) |
| Historical chart | 184k price lookups per render | Read from portfolio_snapshots (~54 docs) |
| Price data | 261k individual docs | Consolidated per-ticker docs (~570 docs) |
| Theme baskets | Compute from scratch each time | Read from price_series (20 docs per theme) |

**Rule**: If data changes ≤ once per day, precompute and cache it.

---

## Firestore Collections

### `trades` — Source of Truth
```
Document ID: auto-generated
{
  date: Timestamp,
  ticker: "AAPL",
  type: "Equity",
  side: "Buy" | "Sell",
  price: 150.25,
  quantity: 10.0,
  fees: 0.0,
  currency: "USD",
  is_wash_sale: false
}
```
- **Append-only** in practice (edits/deletes are rare corrections)
- All calculations derive from this collection
- ~2,000-10,000 docs for an active trader

### `asset_prices` — Asset Registry
```
Document ID: ticker (e.g., "AAPL")
{
  ticker: "AAPL",
  price: 248.80,                    // latest close
  previous_close: 253.90,           // for daily change
  daily_change: -5.10,
  daily_change_pct: -2.01,
  primary_theme: "AI",
  secondary_theme: "Technology",
  last_updated: Timestamp
}
```
- **Denormalized** for fast UI reads (no joins needed)
- Updated daily by price refresh scheduler
- Themes are plain strings (no separate themes collection)
- ~500-600 docs

### `price_series` — Consolidated Historical Prices
```
Document ID: ticker (e.g., "AAPL")
{
  ticker: "AAPL",
  prices: {
    "2023-06-26": 182.88,
    "2023-06-27": 185.63,
    ...                              // ~700 entries per year
  },
  last_updated: Timestamp
}
```
- **One doc per ticker** with ALL daily closes in a map
- ~17KB per ticker per year → well within 1MB Firestore limit
- Updated daily by price refresh (appends one entry)
- Auto-populated when new asset is created
- Used for: theme basket comparison, any future charting/analytics
- ~570 docs (one per traded/tracked ticker)

### `portfolio_snapshots` — Precomputed Portfolio State
```
Document ID: "YYYY-MM-DD" (e.g., "2026-03-29")
{
  date: "2026-03-29",
  total_value: 120877.00,
  positions: [                       // full detail for today only
    {ticker, quantity, average_price, current_price,
     market_value, unrealized_pnl, realized_pnl,
     primary_theme, secondary_theme}
  ],
  computed_at: Timestamp
}
```
- **One doc per day** — ~365 docs per year
- Today's snapshot has full `positions` array (used by GET /portfolio)
- Historical snapshots have `positions: []` (only `total_value` needed for charts)
- Recomputed on: trade add/edit/delete, daily price refresh
- Used by: Dashboard (current portfolio), Portfolio Value chart (history)

### `price_history` — Legacy (Deprecated)
```
Document ID: "{ticker}_{date}" (e.g., "AAPL_2024-01-15")
```
- **261k individual docs** — replaced by `price_series`
- Still exists but no longer written to by new code
- Can be deleted once `price_series` is fully populated

---

## Data Flow Patterns

### When a New Asset is Added
```
User adds AAPL via UI
    │
    ├── 1. Create asset_prices/AAPL doc (themes, price)
    │
    └── 2. Background thread: fetch_and_store_ticker_prices("AAPL")
            └── yf.download("AAPL", start="2020-01-01")
            └── Write to price_series/AAPL (one doc, ~1500 price points)
```
**Key**: Historical prices are fetched immediately on asset creation. No need to wait for backfill.

### When a Trade is Added/Edited/Deleted
```
Trade CRUD operation
    │
    ├── 1. Write/update/delete trade in trades collection
    ├── 2. Run wash sale detection for affected ticker
    └── 3. Recompute today's portfolio_snapshots/{today}
            └── calculator.compute_and_store_snapshot(db)
```
**Key**: Snapshot is always fresh after any trade change.

### Daily at 5:30 PM ET (After Market Close)
```
APScheduler triggers _scheduled_refresh()
    │
    ├── 1. _run_price_refresh()
    │       ├── yf.download(all_tickers, period='5d')
    │       ├── Update asset_prices (price, daily_change, previous_close)
    │       └── Append today's close to price_series/{ticker}
    │
    └── 2. calculator.compute_and_store_snapshot(db)
            └── Store today's portfolio value + positions
```
**Key**: One Yahoo Finance call per day for ALL tickers. One snapshot computation. All subsequent reads are O(1).

### When Dashboard Loads
```
GET /portfolio
    │
    ├── 1. Check portfolio_snapshots/{today}
    │       └── If exists and has positions → return directly (1 read)
    │
    └── 2. If no snapshot → calculate_portfolio(db) + store snapshot
            └── Reads trades + asset_prices (first load of the day only)
```
**Key**: First visitor of the day pays the computation cost. Everyone after gets cached data.

### When Portfolio Chart Loads
```
GET /portfolio/history?period=1y
    │
    └── Read all portfolio_snapshots docs where date >= start
        └── Return [{date, value}, ...] (~54 docs for 1Y)
```
**Key**: No trade replay. No price lookups. Just reading precomputed snapshots.

---

## Anti-Patterns to Avoid

### 1. Never Store One Doc Per Data Point Per Day
```
BAD:  price_history/AAPL_2024-01-01, AAPL_2024-01-02, ... (261k docs)
GOOD: price_series/AAPL → {prices: {"2024-01-01": 182.88, ...}} (1 doc)
```
Firestore charges per read. 261k reads vs 1 read is a 261,000x cost difference.

### 2. Never Recompute What Doesn't Change
```
BAD:  Replay all trades on every GET /portfolio request
GOOD: Precompute snapshot once, read on every request
```
Portfolio value only changes when: (a) trade is added/modified, (b) prices update. Between those events, it's static.

### 3. Never Fetch External Data That You Already Have
```
BAD:  Backfill re-downloads prices for all 570 tickers every time
GOOD: Check which tickers already have data, only download new ones
```
Use `get_tickers_with_price_data(db)` to check existing data before calling Yahoo Finance.

### 4. Never Block the Response on Background Work
```
BAD:  create_asset() waits for yfinance download before responding
GOOD: create_asset() spawns background thread, responds immediately
```
Historical price fetch takes 5-10 seconds. The user shouldn't wait. Use `threading.Thread(daemon=True)`.

### 5. Never Load Entire Collections Into Memory
```
BAD:  db.collection('price_history').stream() → 261k docs in memory
GOOD: Query only what you need with filters, or use consolidated docs
```
If you must scan, use `.limit()`, `.where()`, or paginate.

### 6. Never Make One API Call Per Ticker
```
BAD:  for ticker in tickers: yf.download(ticker, ...)  (570 calls)
GOOD: yf.download(all_tickers, ...)  (1 call)
```
Yahoo Finance's `download()` handles batching internally. One call for all tickers.

---

## Scaling Considerations

### For Hundreds of Users
- **Price refresh**: Server-side scheduler runs once per day, shared by all users
- **Snapshots**: Each user would have their own `portfolio_snapshots` subcollection
- **Price data**: Shared across all users (same stock = same price)
- **Trades**: Per-user collection or user_id field

### For Thousands of Tickers
- `price_series` scales linearly: 1000 tickers = 1000 docs, each ~50KB
- Yahoo Finance batch download handles up to ~500 tickers per call; chunk larger sets
- Theme basket comparison: limit to top 10-15 themes with most holdings

### For Real-Time Data
- Current architecture is daily (post-market close)
- For intraday: add WebSocket connection to price feed
- Store intraday ticks in a separate `intraday_prices` collection
- Never mix intraday with daily close data

---

## Checklist for New Data Features

Before building any feature that touches data:

- [ ] **Can this be precomputed?** If data changes ≤ daily, compute and store it
- [ ] **Does the feature need a new collection?** Use consolidated docs (one per entity, not one per data point)
- [ ] **Will it fetch external data?** Check if data already exists first. Fetch only what's missing
- [ ] **How many Firestore reads?** Target < 100 reads per page load. Never scan entire collections
- [ ] **Does it block the user?** Long operations (> 2s) should run in background threads
- [ ] **Is it idempotent?** Running the same operation twice should produce the same result without wasting resources
- [ ] **What triggers recomputation?** Define exactly when cached data becomes stale and needs refresh
