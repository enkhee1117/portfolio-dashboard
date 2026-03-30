# Portfolio Tracker — Design Guide

A reference for anyone building features for this app. Follow these patterns to keep the codebase consistent.

---

## Architecture

```
Frontend (Next.js 16 / React 19 / TypeScript)
  └─ /api/* proxied to backend via next.config.ts rewrites (dev only)

Backend (FastAPI / Python)
  └─ Firestore collections: trades, asset_prices, price_history (all user-scoped)

Auth: Firebase Authentication (email/password + Google OAuth)
Deployment: Vercel (frontend + serverless backend)
Database: Google Cloud Firestore (Blaze plan)
Price Data: Yahoo Finance (yfinance), auto-refreshed daily 5:30 PM ET
```

### Key collections

| Collection | Doc ID | Purpose | User-scoped |
|---|---|---|---|
| `trades` | auto-generated | Individual buy/sell transactions | Yes (`user_id` field) |
| `asset_prices` | ticker (e.g. "AAPL") | **Shared price cache** — price, daily change, RSI. Written only by price refresh. | No (shared) |
| `users/{uid}/asset_themes` | ticker | **User's asset registry** — themes, manual additions. User CRUD operates here. | Yes |
| `price_history` | `{ticker}_{date}` | Historical OHLCV for analytics | No (shared) |
| `price_series` | ticker | Consolidated historical closing prices | No (shared) |

**Data isolation rules:**
- A user's visible asset list = tickers from their trades + tickers in their `asset_themes`
- No user action ever deletes from shared `asset_prices` — it's a price cache for all users
- Theme assignments are per-user in `asset_themes` (fields: `primary`, `secondary`)
- Backup/restore only touches the user's own trades and `asset_themes`

### Frontend pages

| Route | File | Purpose |
|---|---|---|
| `/login` | `app/login/page.tsx` | Email/password + Google OAuth sign-in/sign-up |
| `/` | `app/page.tsx` | Dashboard — net liquidity, P&L, top positions, RSI signals, chart |
| `/portfolio` | `app/portfolio/page.tsx` | 3-tab view: Positions, Trades, Assets |
| `/analytics` | `app/analytics/page.tsx` | Theme allocation, basket performance comparison |
| `/settings` | `app/settings/page.tsx` | Import, export, backup/restore, price refresh, theme management |
| `/positions` | Redirect → `/portfolio` | |
| `/trades` | Redirect → `/portfolio?tab=trades` | |
| `/assets` | Redirect → `/portfolio?tab=assets` | |

### Key components

| Component | File | Purpose |
|---|---|---|
| `Navigation` | `components/Navigation.tsx` | Nav bar + auth guard (redirects to `/login` if not authenticated) |
| `PortfolioChart` | `components/PortfolioChart.tsx` | Area chart of portfolio value over time (Recharts) |
| `PositionTable` | `components/PositionTable.tsx` | Sortable/filterable positions table with inline trade editing |
| `ManualTradeForm` | `components/ManualTradeForm.tsx` | Modal form for adding trades with inline asset registration |
| `ThemeAnalysis` | `components/ThemeAnalysis.tsx` | Theme composition analysis |
| `ImportButton` | `components/ImportButton.tsx` | CSV/Excel file upload |
| `Toast` | `components/Toast.tsx` | Toast notification system (`useToast()` hook) |
| `useKeyboard` | `components/useKeyboard.tsx` | `useEscape()` and `useCmdK()` hooks |

---

## Authentication

### Overview
Multi-user support via Firebase Authentication. Each user's data (trades, portfolio) is isolated by `user_id`.

### Frontend auth flow
```
AuthProvider (lib/AuthContext.tsx)
  └─ onAuthStateChanged listener restores session on page load
  └─ Provides: { user, loading, logout }

Navigation (components/Navigation.tsx)
  └─ Auth guard: redirects to /login if !user && !loading

apiCall (lib/api.ts)
  └─ Reads auth.currentUser, attaches Bearer token to every request
```

### Backend auth flow
```python
# main.py — every protected endpoint uses Depends(get_current_user)
def get_current_user(authorization: str = Header(None)) -> str:
    # Verifies Firebase ID token, returns uid
    # Raises 401 if missing or invalid

# All data queries filter by user_id:
db.collection("trades").where(filter=FieldFilter("user_id", "==", user_id))
```

### Critical rules
- **Initialize Firebase once at module level** — never inside request handlers (race condition)
- **`apiCall()` automatically attaches the token** — no manual header management needed
- **Gate all fetches on `useAuth()` user state** — see "Authenticated Data Fetching" pattern below

---

## Color System

Dark theme only. All colors use Tailwind classes.

### Backgrounds
- **Page**: `bg-gray-900`
- **Cards/Tables**: `bg-gray-800`
- **Inputs**: `bg-gray-700`
- **Subtle panels**: `bg-gray-900/50`

### Text
- **Primary**: `text-white`
- **Secondary**: `text-gray-300`
- **Muted**: `text-gray-400`
- **Disabled**: `text-gray-500` / `text-gray-600`

### Borders
- **Default**: `border-gray-700`
- **Hover**: `border-gray-600`
- **Focus**: `focus:border-indigo-500`

### Semantic Colors
| Purpose | Background | Text | Border |
|---|---|---|---|
| Primary action | `bg-indigo-600` | `text-white` | — |
| Success / Gain | `bg-green-900/20` | `text-green-400` | `border-green-700/50` |
| Error / Loss | `bg-red-900/20` | `text-red-400` | `border-red-700/50` |
| Warning | `bg-amber-900/20` | `text-amber-300` | `border-amber-700/50` |
| Info | `bg-gray-800` | `text-gray-300` | `border-gray-700` |

### Theme Badges
- **Primary theme**: `bg-indigo-900/40 text-indigo-300 border-indigo-700/50`
- **Secondary theme**: `bg-cyan-900/40 text-cyan-300 border-cyan-700/50`

### P&L Coloring
```tsx
className={value >= 0 ? "text-green-400" : "text-red-400"}
```
Always green for gains, red for losses. No exceptions.

---

## Button Hierarchy

| Level | Style | Use for |
|---|---|---|
| **Primary** | `bg-indigo-600 hover:bg-indigo-700 text-white` | Main actions: Save, Submit, Create |
| **Secondary** | `border border-gray-600 hover:bg-gray-800 text-gray-300` | Toggle, Cancel, non-critical actions |
| **Danger** | `text-red-400 hover:text-red-300` (text only) | Delete, Remove (always with confirm) |
| **Success submit** | `bg-green-600 hover:bg-green-700 text-white` | Final form submission (Add Trade) |
| **Warning action** | `bg-amber-600 hover:bg-amber-700 text-white` | Contextual warning actions (register unregistered ticker) |

### Button rules
- All buttons: `rounded-md text-sm transition-colors`
- Disabled: `disabled:opacity-50`
- Never use `bg-blue-600` or `bg-cyan-600` — those are retired

---

## Components & Patterns

### Toast Notifications (not alert)
```tsx
import { useToast } from '../components/Toast';

const toast = useToast();
toast.success("Trade added successfully!");
toast.error("Failed to save.");
toast.info("Copied to clipboard");
```
**Never use `alert()`.** Use `confirm()` only for destructive actions (delete, restore).

### Modals
```tsx
<div
  className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50"
  onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
>
  <div className="bg-gray-800 rounded-xl shadow-xl border border-gray-700 w-full max-w-5xl max-h-[85vh] flex flex-col">
    {/* Header with close button */}
    {/* Scrollable content */}
  </div>
</div>
```
- Always close on backdrop click
- Always close on Escape: `useEscape(isOpen ? onClose : null)`
- Use `max-w-5xl` or `max-w-6xl` for data-heavy modals
- Scrollable body with sticky header

### Sortable Tables
```tsx
const TH = ({ colKey, label, right }) => (
  <th
    className={`px-3 py-3 font-semibold cursor-pointer hover:text-white text-xs ${right ? "text-right" : ""}`}
    onClick={() => handleSort(colKey)}
  >
    {label} <SortIcon colKey={colKey} />
  </th>
);
```
- Sort icons: `⇅` (inactive), `↑` (asc), `↓` (desc)
- Default sort order: `desc` for numbers, `asc` for text
- Table padding: `px-3 py-2.5` for data cells

### Authenticated Data Fetching
All API calls to auth-protected endpoints must wait for Firebase auth to restore the session:
```tsx
import { useAuth } from "../lib/AuthContext";
import { apiCall } from "../lib/api";

const { user } = useAuth();

useEffect(() => {
  if (!user) return;  // Wait for auth — NEVER fetch without this guard
  apiCall("/api/portfolio")
    .then(async (r) => { if (r.ok) setData(await r.json()); })
    .catch(console.error);
}, [user]);  // Re-fetch when user changes (login/logout)
```
**Rules:**
- Always include `user` in the dependency array
- Always check `r.ok` before parsing — non-ok responses are error objects, not arrays
- Never use `[]` as dependency for authenticated fetches — it races with auth restoration

### Empty States
Always provide actionable guidance with links:
```tsx
No positions yet. Import trades from <a href="/settings" className="text-indigo-400 hover:underline">Settings</a>.
```

### Keyboard Shortcuts
```tsx
import { useEscape, useCmdK } from '../components/useKeyboard';

useEscape(modalOpen ? closeModal : null);  // Escape closes modals
useCmdK();  // Cmd/Ctrl+K focuses search input
```

---

## Number Formatting

### Currency
```tsx
// Summary cards — whole dollars
${value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}

// Tables — 2 decimal places
${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}

// Percentages
{value.toFixed(1)}%    // one decimal
{value.toFixed(2)}%    // two decimals (daily change)
```

**Always include `maximumFractionDigits`** to prevent 3+ decimal overflow.

### Daily Change Format
```tsx
{value >= 0 ? "+" : ""}{value.toFixed(2)}%
// Renders: +2.50% or -1.30%
```

---

## Page Layout

```tsx
<main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
  <div className="max-w-7xl mx-auto space-y-6">
    {/* Page header */}
    <div className="flex justify-between items-center">
      <div>
        <h1 className="text-2xl font-bold text-white">Page Title</h1>
        <p className="mt-1 text-sm text-gray-400">Description</p>
      </div>
      {/* Action buttons */}
    </div>

    {/* Content sections */}
  </div>
</main>
```

### Spacing scale
- Page padding: `p-8`
- Section gaps: `space-y-6`
- Card padding: `p-5` (summary) or `p-6` (content cards)
- Grid gaps: `gap-4` (tight) or `gap-6` (spacious)

---

## Backend Conventions

### Endpoint naming

All endpoints except `/` and `/assets` require authentication (`Depends(get_current_user)`).

```
# Core
GET    /                           — health check
POST   /import                     — CSV/Excel file upload (skip_dedup param)

# Portfolio (user-scoped)
GET    /portfolio                   — computed positions with P&L, themes, RSI
GET    /portfolio/history           — historical portfolio value (period: ytd,1m,3m,6m,1y,all)
POST   /portfolio/backfill-history  — backfill historical prices from Yahoo Finance

# Trades (user-scoped)
GET    /trades                      — list all trades
POST   /trades/manual               — create trade (force param to skip dedup)
PUT    /trades/{trade_id}           — update trade
DELETE /trades/{trade_id}           — delete trade
GET    /trades/export-csv           — tax-ready CSV with wash sale flags

# Assets (shared across users)
GET    /assets                      — list all assets with prices
GET    /assets/themes               — available primary/secondary themes
POST   /assets                      — register new asset
PUT    /assets/{ticker}             — update (supports rename via new_ticker)
DELETE /assets/{ticker}             — remove
POST   /assets/refresh-prices       — trigger manual price refresh
GET    /assets/refresh-status       — last refresh time and schedule

# Themes
GET    /themes/summary              — theme counts
PUT    /themes/rename               — bulk rename
POST   /themes/combine              — merge themes
DELETE /themes/{name}               — remove theme from all assets

# Analytics
GET    /analytics/theme-baskets     — theme performance comparison (period param)

# Data Management
GET    /backup/export               — JSON backup (user-scoped)
POST   /backup/restore              — restore from backup
POST   /admin/migrate-to-user       — one-time migration of unscoped data to user
```

### Firestore batch writes
Always batch in groups of 400 (Firestore limit is 500):
```python
if batch_count >= 400:
    batch.commit()
    batch = db.batch()
    batch_count = 0
```

### Error handling
- Return appropriate HTTP status codes (404, 409, 400, 502)
- Wrap risky operations in try/except (e.g., wash sales after import)
- Log errors with `logger.error()`

### Date handling
- Store as `datetime` in Firestore (naive UTC)
- Return ISO strings to frontend
- Append `"Z"` suffix when returning timestamps so browsers parse as UTC
- Frontend converts to local time via `new Date(isoString)`

---

## Testing

### Backend tests (pytest)
```python
def make_trade_doc(doc_id, ticker, side, price, quantity, date=None):
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = { ... }
    return doc

def make_db(trade_docs=None, asset_docs=None):
    db = MagicMock()
    # Wire up collection().stream() and collection().document()
    return db
```

**Categories:**
- **Calculator tests**: quantity, avg price, market value, P&L, themes, ordering
- **API tests**: CRUD endpoints with TestClient
- **Importer tests**: CSV parsing, deduplication
- **Wash sales tests**: IRS rule logic
- **Backup tests**: export/restore round-trip

```bash
cd frontend/api
python3 -m pytest tests/ --ignore=tests/test_smoke.py -v
```

### Frontend tests (Vitest + React Testing Library)

Tests live in `frontend/src/__tests__/`. Mock Firebase and auth before importing components:

```tsx
vi.mock("../lib/firebase", () => ({ auth: { currentUser: null } }));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ user: mockUser, loading: false, logout: vi.fn() }),
}));
```

**Categories:**
- **API wrapper tests** (`api.test.ts`): token attachment, response handling
- **Auth-fetch guard tests** (`auth-fetch-guard.test.tsx`): verify components don't fetch before auth resolves
- **Error resilience tests** (`error-resilience.test.ts`): defensive patterns against non-array API responses

```bash
cd frontend
npx vitest run        # single run
npx vitest            # watch mode
```

### CI pipeline (`.github/workflows/ci.yml`)
1. **Backend tests** — pytest (all pushes/PRs to main)
2. **Frontend tests** — Vitest + Next.js build (all pushes/PRs to main)
3. **Smoke tests** — live integration tests against Vercel (main pushes only)

---

## Deployment

### Local vs Production Differences

| Aspect | Local dev | Vercel production |
|--------|-----------|-------------------|
| API routing | Next.js rewrite proxy (`localhost:8000`) | Vercel serverless (`/api/index.py`) |
| Python path | Automatic (uvicorn runs from `api/`) | Must add `sys.path.insert(0, os.path.dirname(__file__))` |
| API prefix | Routes at `/portfolio`, `/trades`, etc. | Mounted under `/api` via `app.mount("/api", api_app)` |
| APScheduler | Background thread runs daily at 5:30 PM ET | Disabled (serverless can't run background threads) |
| Firebase creds | `firebase-credentials.json` file | `FIREBASE_CREDENTIALS_JSON` env var |
| File uploads | `python-multipart` installed locally | Must be in `requirements.txt` |

### Deployment Lessons Learned

1. **Every Python dependency must be in `requirements.txt`** — even ones that "just work" locally because they're installed globally. If FastAPI uses `UploadFile`, you need `python-multipart` explicitly listed.

2. **Vercel serverless doesn't support background threads** — APScheduler, `threading.Thread`, and any long-running background processes won't work. Check `VERCEL` env var and disable accordingly.

3. **Module paths differ between local and serverless** — Vercel runs from `/var/task/` where the Python path doesn't include your `api/` directory. Always add `sys.path.insert(0, os.path.dirname(__file__))` in the entry point.

4. **FastAPI route prefix must match deployment** — locally routes are at `/portfolio`, but Vercel routes requests to `/api/portfolio`. Use `app.mount("/api", api_app)` in the entry point.

5. **Test the API endpoint directly after every deploy** — `curl https://your-app.vercel.app/api/portfolio` should return JSON, not HTML.

6. **Never call `firebase_admin.initialize_app()` inside a request handler** — it causes race conditions on concurrent requests. Initialize once at module level.

7. **Frontend API calls must handle non-ok responses gracefully** — a 401/500 returns an error object, not an array. Calling `.slice()` or `.map()` on it crashes the app. Always check `r.ok` before parsing.

8. **Gate authenticated API calls on auth state** — Firebase's `onAuthStateChanged` is async and takes 100-500ms on page load. If `useEffect` fires before auth restores, `auth.currentUser` is null and requests go out without tokens. Always use `useAuth()` and guard with `if (!user) return;`.

### Pre-Push Checklist

Before pushing code that will auto-deploy:

- [ ] `npx next build` passes locally
- [ ] `cd frontend && npx vitest run` passes (frontend tests)
- [ ] `pytest tests/ --ignore=tests/test_smoke.py` passes (76+ tests)
- [ ] `requirements.txt` includes any new Python packages
- [ ] No `import` at module level that might fail on serverless
- [ ] Tested locally with both servers running
- [ ] Page refresh while logged in loads data (no stale zeros)

---

## Feature Checklist

When adding a new feature, check these:

- [ ] Toast notifications for success/error (never `alert()`)
- [ ] Empty state with actionable guidance
- [ ] Escape closes any modal
- [ ] Cmd+K focuses search if page has filter
- [ ] Numbers formatted with `maximumFractionDigits`
- [ ] Buttons follow color hierarchy
- [ ] Destructive actions use `confirm()`
- [ ] Theme badges are clickable to filter
- [ ] P&L values colored green/red
- [ ] Mobile-aware (test at 768px)
- [ ] Backend uses batch writes for bulk operations
- [ ] Tests written for new backend logic
- [ ] API calls gated on `useAuth()` user state (not raw `[]` dependency)
- [ ] API responses checked with `r.ok` before parsing JSON
- [ ] Frontend tests written for new components/pages
