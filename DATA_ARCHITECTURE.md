# Data Architecture Guide

How data flows, is stored, and should be handled in this portfolio tracker. This document defines the engineering principles that all future development must follow. Written for a system that will scale from a single user to hundreds of traders.

---

## Foundational Principles

These five principles govern every data decision. Violating any of them creates technical debt that compounds as the system scales.

### 1. Compute Once, Read Many

Financial data changes at known, discrete intervals: market close (daily) and trade entry (user-initiated). Between those events, all derived data is static.

**Never recompute on read.** Precompute on write.

| Trigger | What to precompute | Where to store |
|---------|-------------------|----------------|
| Trade added/edited/deleted | Today's portfolio snapshot | `portfolio_snapshots/{today}` |
| Daily price refresh (5:30 PM ET) | Portfolio snapshot + price series update | `portfolio_snapshots` + `price_series` |
| New asset registered | Historical price series for that ticker | `price_series/{ticker}` |

Every GET endpoint should read precomputed data. The only computation allowed on read is a cache-miss fallback that immediately stores its result.

### 2. Idempotency

Every operation must produce the same result whether run once or ten times, without side effects or wasted resources.

**Why this matters at scale**: Distributed systems have retries, duplicate webhook deliveries, users double-clicking buttons, cron jobs that overlap, and crash-recovery replays. If any operation isn't idempotent, data corrupts silently.

| Operation | How idempotency is ensured |
|-----------|---------------------------|
| Price backfill | Checks `price_series` for existing tickers, skips them |
| Portfolio snapshot | Uses date as document ID — same date overwrites, doesn't duplicate |
| Trade import | Signature deduplication `(date, ticker, side, price, quantity)` |
| Price refresh | `merge=True` on Firestore writes — updates, never duplicates |
| Asset creation | 409 conflict if ticker already exists |
| Theme rename | Scans all docs, replaces matching values — running twice changes nothing |

**Rules**:
- Use natural keys as document IDs (ticker, date) — not auto-generated IDs for reference data
- Always use `merge=True` or `set()` with full replacement — never `create()` for data that may already exist
- Check-before-write for external API calls — don't re-fetch data you already have
- Design every POST/PUT endpoint so that calling it twice with the same payload produces the same state

### 3. Data Locality

Keep related data together. Minimize the number of documents and collections a single page load touches.

**Target**: < 100 Firestore reads per page load. Ideally < 10.

| Pattern | Bad | Good | Improvement |
|---------|-----|------|-------------|
| Price history | 261k individual docs | 570 consolidated per-ticker docs | 458x fewer docs |
| Portfolio load | Replay 2,058 trades + 571 price lookups | Read 1 snapshot doc | 2,629x fewer reads |
| History chart (1Y) | 184k batch doc reads (29s) | 54 snapshot docs (<1s) | 3,407x fewer reads |

### 4. Separation of Concerns: Source vs Derived

**Source data** (trades, asset registrations) is the ground truth. It's written by users and must never be lost.

**Derived data** (snapshots, price series, theme baskets) is computed from source data. It can always be regenerated. Losing it is inconvenient, not catastrophic.

| Layer | Collection | Can be regenerated? | Backup priority |
|-------|-----------|--------------------|-----------------|
| Source | `trades` | No — user-entered | Critical |
| Source | `asset_prices` | Partially (themes are user-entered, prices are fetched) | High |
| Derived | `portfolio_snapshots` | Yes — from trades + asset_prices | Low |
| Derived | `price_series` | Yes — from Yahoo Finance | Low |
| Legacy | `price_history` | Yes — subset of price_series | None |

**Rule**: Never modify source data as a side effect of reading derived data. Never store derived data in source collections.

### 5. Fail Gracefully, Never Silently

Every background operation (price fetch, snapshot computation, wash sale detection) must:
- Catch exceptions without crashing the parent operation
- Log the failure with context
- Return partial results rather than nothing
- Allow retry without side effects (see: Idempotency)

```python
# Good: Import succeeds even if wash sale detection fails
try:
    wash_sales.detect_wash_sales(all_trades, db)
except Exception as wash_err:
    print(f"Wash sales detection failed (trades were still imported): {wash_err}")
```

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
- All portfolio calculations derive from this collection
- Every trade change triggers snapshot recomputation
- Deduplication via signature: `(date, ticker, side, price, quantity)`

### `asset_prices` — Asset Registry (Denormalized)
```
Document ID: ticker (e.g., "AAPL")
{
  ticker: "AAPL",
  price: 248.80,
  previous_close: 253.90,
  daily_change: -5.10,
  daily_change_pct: -2.01,
  primary_theme: "AI",
  secondary_theme: "Technology",
  last_updated: Timestamp
}
```
- **Denormalized for O(1) reads** — no joins needed for dashboard
- Updated daily by price refresh scheduler
- Themes are plain strings (no separate themes collection — themes exist as long as assets reference them)
- Document ID = ticker for direct lookups

### `price_series` — Consolidated Historical Prices
```
Document ID: ticker (e.g., "AAPL")
{
  ticker: "AAPL",
  prices: {
    "2023-06-26": 182.88,
    "2023-06-27": 185.63,
    ...
  },
  last_updated: Timestamp
}
```
- **One doc per ticker** with ALL daily closes in a map
- ~17KB per ticker per year — Firestore 1MB limit supports 50+ years
- Auto-populated on asset creation (background thread)
- Appended daily by price refresh
- `merge=True` ensures idempotent writes
- Used for: theme basket comparison, individual stock charts, any analytics

### `portfolio_snapshots` — Precomputed Portfolio State
```
Document ID: "YYYY-MM-DD" (e.g., "2026-03-29")
{
  date: "2026-03-29",
  total_value: 120877.00,
  positions: [{ticker, quantity, average_price, current_price,
               market_value, unrealized_pnl, realized_pnl,
               primary_theme, secondary_theme}],
  computed_at: Timestamp
}
```
- **One doc per day** — date as natural key ensures idempotency
- Today's snapshot includes full `positions` array (used by GET /portfolio)
- Historical snapshots store only `total_value` (positions omitted to save space)
- Triggers: trade CRUD, daily price refresh, manual backfill

### `price_history` — DEPRECATED
- 261k individual docs — replaced by `price_series`
- No longer written to. Safe to delete after verifying `price_series` coverage.

---

## Data Flow Patterns

### New Asset Added
```
POST /assets {ticker: "NVDA", primary_theme: "AI", ...}
    │
    ├── 1. Write asset_prices/NVDA (sync, immediate)
    │
    └── 2. Background thread (non-blocking):
            fetch_and_store_ticker_prices(db, "NVDA")
            └── yf.download("NVDA", start="2020-01-01")
            └── Write price_series/NVDA {prices: {...}} (merge=True)
```

### Trade Created/Edited/Deleted
```
POST|PUT|DELETE /trades/...
    │
    ├── 1. Write trade to trades collection
    ├── 2. Wash sale detection (best-effort, non-fatal)
    └── 3. Recompute portfolio_snapshots/{today} (best-effort)
```

### Daily Refresh (5:30 PM ET)
```
APScheduler → _scheduled_refresh()
    │
    ├── 1. yf.download(all_tickers, period='5d')     ← 1 API call
    ├── 2. Update asset_prices (price, daily_change)  ← batch write
    ├── 3. Append to price_series/{ticker}            ← per-ticker update
    └── 4. compute_and_store_snapshot(db)             ← 1 snapshot write
```

### Dashboard Load
```
GET /portfolio
    │
    ├── Read portfolio_snapshots/{today}  ← 1 Firestore read
    │     └── If exists with positions → return (cache hit)
    │
    └── Cache miss → calculate_portfolio(db) → store → return
```

### Backfill (One-Time)
```
POST /portfolio/backfill-history
    │
    ├── 1. Find all tickers from trades
    ├── 2. Check price_series for existing data    ← idempotent check
    ├── 3. Download only NEW tickers from Yahoo    ← skip existing
    ├── 4. Write to price_series (merge=True)      ← idempotent write
    ├── 5. Load all price_series into memory
    ├── 6. Replay trades at weekly intervals
    └── 7. Write portfolio_snapshots (date as ID)  ← idempotent write
```

---

## Anti-Patterns

### 1. One Doc Per Data Point Per Day
```
BAD:  price_history/AAPL_2024-01-01, AAPL_2024-01-02, ...
GOOD: price_series/AAPL → {prices: {"2024-01-01": 182.88, ...}}
```

### 2. Recomputing Static Data
```
BAD:  Replay all trades on every GET /portfolio
GOOD: Read precomputed snapshot, recompute only on trade/price changes
```

### 3. Re-fetching Existing Data
```
BAD:  Backfill downloads all 570 tickers every run
GOOD: Check existing, download only missing tickers
```

### 4. Blocking on Background Work
```
BAD:  create_asset() waits 10s for yfinance before responding
GOOD: Spawn daemon thread, respond immediately
```

### 5. Full Collection Scans
```
BAD:  db.collection('price_history').stream() → 261k docs in memory
GOOD: Targeted queries, consolidated docs, or pagination
```

### 6. One API Call Per Entity
```
BAD:  for ticker in 570_tickers: yf.download(ticker)
GOOD: yf.download(all_570_tickers)  # batched internally
```

### 7. Non-Idempotent Writes
```
BAD:  db.collection('snapshots').add(data)  # creates duplicate on retry
GOOD: db.collection('snapshots').document(date_str).set(data)  # overwrites on retry
```

---

## Scaling Roadmap

### Current State (Single User)
```
Trades:     ~2,000 docs
Assets:     ~570 docs
Prices:     ~570 docs (consolidated)
Snapshots:  ~150 docs (weekly)
Reads/load: ~5-10
```

### Phase 1: Multi-User (Hundreds of Users)
```
Architecture changes:
├── Add user_id to trades collection (or per-user subcollection)
├── portfolio_snapshots becomes per-user: users/{uid}/snapshots/{date}
├── price_series stays SHARED (same stock = same price for everyone)
├── asset_prices stays SHARED (themes could become per-user later)
├── Authentication gate (password, OAuth, or Firebase Auth)
└── Rate limit trade creation per user

Firestore reads per user page load: still ~5-10 (snapshots are per-user)
Price refresh: still 1 call/day (shared across all users)
```

### Phase 2: Performance (Thousands of Tickers)
```
Architecture changes:
├── Chunk yf.download() into batches of 400 tickers
├── price_series: if any ticker exceeds 500KB, split by year
│   └── price_series/AAPL_2024, price_series/AAPL_2025
├── Theme basket computation: cache in theme_basket_snapshots/{theme}
├── Add Redis/Memcached for hot-path caching (portfolio, prices)
└── Consider Cloud Functions for background price refresh

Firestore reads per page load: still ~5-10 with caching
Price refresh: chunked into 2-3 yfinance calls
```

### Phase 3: Real-Time (Intraday Data)
```
Architecture changes:
├── WebSocket connection to market data feed (Polygon, Alpaca, etc.)
├── New collection: intraday_prices/{ticker}_{date}
│   └── Contains minute-level or tick-level data
├── NEVER mix intraday with daily close data
├── Separate intraday portfolio valuation pipeline
├── Server-Sent Events (SSE) for pushing live updates to frontend
└── Consider TimescaleDB or InfluxDB for time-series at this scale

Firestore: still used for trades, assets, themes, daily snapshots
Time-series DB: used for intraday prices, tick data, live P&L
```

### Phase 4: Enterprise (Compliance, Audit)
```
Architecture changes:
├── Immutable audit log: every trade change logged with before/after
├── Soft deletes only — never hard delete trades
├── Role-based access (admin, trader, viewer)
├── Regulatory reporting endpoints (Form 8949, wash sale summaries)
├── Data retention policies (7-year minimum for tax records)
└── Encrypted backups with versioning
```

---

## Checklist for New Data Features

Before building any feature that touches data:

- [ ] **Idempotent?** Running it twice produces the same state without side effects
- [ ] **Can it be precomputed?** If data changes ≤ daily, compute on write, not on read
- [ ] **Consolidated storage?** One doc per entity, not one doc per data point
- [ ] **External data check?** Verify data doesn't already exist before fetching
- [ ] **Read budget?** Target < 100 Firestore reads per page load
- [ ] **Non-blocking?** Operations > 2s run in background threads
- [ ] **Stale trigger defined?** Document exactly what events invalidate cached data
- [ ] **Graceful failure?** Errors are caught, logged, and don't crash parent operations
- [ ] **Natural keys?** Use meaningful IDs (ticker, date) not auto-generated ones for reference data
- [ ] **Source vs derived?** Never modify source data as a side effect. Derived data can always be regenerated
