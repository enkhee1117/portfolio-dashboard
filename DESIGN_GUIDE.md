# Portfolio Tracker — Design Guide

A reference for anyone building features for this app. Follow these patterns to keep the codebase consistent.

---

## Architecture

```
Frontend (Next.js 16 / React 19 / TypeScript)
  └─ /api/* proxied to backend via next.config.ts rewrites (dev only)

Backend (FastAPI / Python)
  └─ Firestore collections: trades, asset_prices, price_history

Deployment: Vercel (frontend + serverless backend)
Database: Google Cloud Firestore (Blaze plan)
Price Data: Yahoo Finance (yfinance), auto-refreshed daily 5:30 PM ET
```

### Key collections

| Collection | Doc ID | Purpose |
|---|---|---|
| `trades` | auto-generated | Individual buy/sell transactions |
| `asset_prices` | ticker (e.g. "AAPL") | Current price, themes, daily change |
| `price_history` | `{ticker}_{date}` | Historical OHLCV for analytics |

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
```
GET    /assets              — list all
POST   /assets              — create
PUT    /assets/{ticker}     — update (supports rename via new_ticker)
DELETE /assets/{ticker}     — remove

GET    /themes/summary      — theme counts
PUT    /themes/rename       — bulk rename
POST   /themes/combine      — merge themes
DELETE /themes/{name}       — remove theme from all assets

GET    /backup/export       — JSON backup
POST   /backup/restore      — restore from backup
GET    /trades/export-csv   — CSV for tax
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

### Pattern
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

### Test categories
- **Calculator tests**: quantity, avg price, market value, P&L, themes, ordering
- **API tests**: CRUD endpoints with TestClient
- **Importer tests**: CSV parsing, deduplication
- **Wash sales tests**: IRS rule logic
- **Backup tests**: export/restore round-trip

### Running tests
```bash
cd frontend/api
python3 -m pytest tests/ --ignore=tests/test_smoke.py -v
```

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
