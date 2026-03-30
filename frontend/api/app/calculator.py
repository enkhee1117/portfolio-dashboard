from . import schemas
from collections import defaultdict
from datetime import datetime
import logging

logger = logging.getLogger("portfolio")

def calculate_portfolio(db, user_id: str = "anonymous"):
    from google.cloud.firestore_v1.base_query import FieldFilter
    query = db.collection('trades')
    if user_id != "anonymous":
        query = query.where(filter=FieldFilter('user_id', '==', user_id))
    trades_docs = query.stream()
    trades = []
    for doc in trades_docs:
        d = doc.to_dict()
        # Normalize timezone-aware dates to naive
        if 'date' in d and hasattr(d['date'], 'replace'):
            d['date'] = d['date'].replace(tzinfo=None)
        d['id'] = doc.id
        trades.append(schemas.Trade(**d))

    # CRITICAL: sort by date so weighted average cost basis is calculated correctly
    trades.sort(key=lambda t: t.date)

    # YTD boundary: January 1st of current year
    ytd_start = datetime(datetime.utcnow().year, 1, 1)

    positions = defaultdict(lambda: {"quantity": 0.0, "cost_basis": 0.0, "realized_pnl": 0.0, "realized_pnl_ytd": 0.0})

    for trade in trades:
        ticker = trade.ticker
        if trade.type == 'Equity':
            qty = trade.quantity
            price = trade.price

            if trade.side == 'Buy':
                current_qty = positions[ticker]["quantity"]
                current_cost = positions[ticker]["cost_basis"]
                new_qty = current_qty + qty
                if new_qty > 0:
                    positions[ticker]["cost_basis"] = ((current_qty * current_cost) + (qty * price)) / new_qty
                positions[ticker]["quantity"] = new_qty

            elif trade.side == 'Sell':
                avg_cost = positions[ticker]["cost_basis"]
                pnl = (price - avg_cost) * qty
                positions[ticker]["realized_pnl"] += pnl
                if trade.date >= ytd_start:
                    positions[ticker]["realized_pnl_ytd"] += pnl
                positions[ticker]["quantity"] -= qty

                # Reset cost basis when position is fully closed to avoid stale values
                if abs(positions[ticker]["quantity"]) < 0.0001:
                    positions[ticker]["quantity"] = 0.0
                    positions[ticker]["cost_basis"] = 0.0

    # Fetch current prices for user's tickers only (from shared price cache)
    asset_data = {}
    for ticker in positions.keys():
        price_doc = db.collection('asset_prices').document(ticker).get()
        if price_doc.exists:
            d = price_doc.to_dict()
            asset_data[ticker] = {
                'price': d.get('price', 0.0),
                'primary': d.get('primary_theme'),  # fallback themes from shared
                'secondary': d.get('secondary_theme')
            }
        else:
            asset_data[ticker] = {'price': 0.0, 'primary': None, 'secondary': None}

    # Override with user-scoped themes if authenticated
    if user_id != "anonymous":
        try:
            theme_docs = db.collection('users').document(user_id).collection('asset_themes').stream()
            for doc in theme_docs:
                ticker = doc.id
                d = doc.to_dict()
                if ticker in asset_data:
                    asset_data[ticker]['primary'] = d.get('primary') or asset_data[ticker].get('primary')
                    asset_data[ticker]['secondary'] = d.get('secondary') or asset_data[ticker].get('secondary')
                else:
                    asset_data[ticker] = {'price': 0.0, 'primary': d.get('primary'), 'secondary': d.get('secondary')}
        except Exception:
            pass

    results = []
    for ticker, data in positions.items():
        if abs(data["quantity"]) > 0.0001 or abs(data["realized_pnl"]) > 0.001:
            current_price = 0.0
            p_theme = None
            s_theme = None

            if ticker in asset_data:
                current_price = asset_data[ticker]['price']
                p_theme = asset_data[ticker]['primary']
                s_theme = asset_data[ticker]['secondary']

            market_val = data["quantity"] * current_price
            unrealized = (current_price - data["cost_basis"]) * data["quantity"] if abs(data["quantity"]) > 0.0001 else 0.0

            results.append({
                "ticker": ticker,
                "quantity": data["quantity"],
                "average_price": round(data["cost_basis"], 4),
                "current_price": current_price,
                "market_value": round(market_val, 2),
                "unrealized_pnl": round(unrealized, 2),
                "realized_pnl": round(data["realized_pnl"], 2),
                "realized_pnl_ytd": round(data["realized_pnl_ytd"], 2),
                "date": datetime.utcnow().replace(tzinfo=None),
                "primary_theme": p_theme,
                "secondary_theme": s_theme
            })
    return results


def compute_and_store_snapshot(db, date_str: str | None = None, user_id: str = "anonymous"):
    """
    Compute portfolio value and store as a daily snapshot.
    If date_str is None, uses today's date.
    Returns the snapshot dict.
    """
    if date_str is None:
        date_str = datetime.utcnow().strftime('%Y-%m-%d')

    positions = calculate_portfolio(db, user_id=user_id)
    total_value = sum(p["market_value"] for p in positions)

    # Strip datetime objects for Firestore storage — keep only serializable fields
    positions_data = []
    for p in positions:
        positions_data.append({
            "ticker": p["ticker"],
            "quantity": p["quantity"],
            "average_price": p["average_price"],
            "current_price": p["current_price"],
            "market_value": p["market_value"],
            "unrealized_pnl": p["unrealized_pnl"],
            "realized_pnl": p["realized_pnl"],
            "realized_pnl_ytd": p.get("realized_pnl_ytd", 0.0),
            "primary_theme": p.get("primary_theme"),
            "secondary_theme": p.get("secondary_theme"),
        })

    snapshot = {
        "date": date_str,
        "total_value": round(total_value, 2),
        "positions": positions_data,
        "computed_at": datetime.utcnow(),
    }

    # Store in user-scoped path if authenticated, otherwise global
    if user_id != "anonymous":
        db.collection('users').document(user_id).collection('portfolio_snapshots').document(date_str).set(snapshot)
    else:
        db.collection('portfolio_snapshots').document(date_str).set(snapshot)
    logger.info(f"Snapshot stored for {date_str} (user={user_id[:8]}...): ${total_value:,.2f} ({len(positions_data)} positions)")

    return snapshot


def _recompute_ticker_position(db, user_id: str, ticker: str) -> dict | None:
    """Replay all trades for a single ticker to get its exact position.
    Returns a position dict or None if no trades exist for this ticker.
    Cost: ~5 reads (average trades per ticker) + 2 reads (price + theme)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = db.collection('trades').where(filter=FieldFilter('ticker', '==', ticker))
    if user_id != "anonymous":
        query = query.where(filter=FieldFilter('user_id', '==', user_id))

    trades = []
    for doc in query.stream():
        d = doc.to_dict()
        if 'date' in d and hasattr(d['date'], 'replace'):
            d['date'] = d['date'].replace(tzinfo=None)
        d['id'] = doc.id
        trades.append(schemas.Trade(**d))

    if not trades:
        return None

    trades.sort(key=lambda t: t.date)
    ytd_start = datetime(datetime.utcnow().year, 1, 1)

    qty = 0.0
    cost_basis = 0.0
    realized_pnl = 0.0
    realized_pnl_ytd = 0.0

    for t in trades:
        if t.type != 'Equity':
            continue
        if t.side == 'Buy':
            new_qty = qty + t.quantity
            if new_qty > 0:
                cost_basis = ((qty * cost_basis) + (t.quantity * t.price)) / new_qty
            qty = new_qty
        elif t.side == 'Sell':
            pnl = (t.price - cost_basis) * t.quantity
            realized_pnl += pnl
            if t.date >= ytd_start:
                realized_pnl_ytd += pnl
            qty -= t.quantity
            if abs(qty) < 0.0001:
                qty = 0.0
                cost_basis = 0.0

    # Fetch current price and themes
    current_price = 0.0
    p_theme = None
    s_theme = None

    price_doc = db.collection('asset_prices').document(ticker).get()
    if price_doc.exists:
        pd = price_doc.to_dict()
        current_price = pd.get('price', 0.0)
        p_theme = pd.get('primary_theme')
        s_theme = pd.get('secondary_theme')

    if user_id != "anonymous":
        try:
            theme_doc = db.collection('users').document(user_id).collection('asset_themes').document(ticker).get()
            if theme_doc.exists:
                td = theme_doc.to_dict()
                p_theme = td.get('primary') or p_theme
                s_theme = td.get('secondary') or s_theme
        except Exception:
            pass

    market_val = qty * current_price
    unrealized = (current_price - cost_basis) * qty if abs(qty) > 0.0001 else 0.0

    return {
        "ticker": ticker,
        "quantity": qty,
        "average_price": round(cost_basis, 4),
        "current_price": current_price,
        "market_value": round(market_val, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized_pnl, 2),
        "realized_pnl_ytd": round(realized_pnl_ytd, 2),
        "primary_theme": p_theme,
        "secondary_theme": s_theme,
    }


def apply_trade_delta(db, user_id: str, ticker: str, action: str = "add") -> bool:
    """Apply a trade's effect to the cached snapshot by recomputing only the affected ticker.
    action: "add" (new/updated trade) or "remove" (deleted trade).
    Returns True if snapshot was updated, False if cache miss (caller should invalidate).
    Cost: ~5-10 Firestore reads + 1 write (vs ~2500 for full recompute)."""
    today = datetime.utcnow().strftime('%Y-%m-%d')

    # Read cached snapshot
    try:
        if user_id != "anonymous":
            snap_ref = db.collection('users').document(user_id).collection('portfolio_snapshots').document(today)
        else:
            snap_ref = db.collection('portfolio_snapshots').document(today)
        snap_doc = snap_ref.get()
        if not snap_doc.exists:
            return False
        snapshot = snap_doc.to_dict()
        positions = snapshot.get('positions', [])
        if not positions:
            return False
    except Exception:
        return False

    # Recompute just this ticker's position from its trades
    new_position = _recompute_ticker_position(db, user_id, ticker)

    # Find and replace (or add/remove) the ticker's position in the snapshot
    old_market_value = 0.0
    new_positions = []
    found = False
    for p in positions:
        if p.get('ticker') == ticker:
            old_market_value = p.get('market_value', 0.0)
            found = True
            # Replace with recomputed position (skip if no trades left)
            if new_position and (abs(new_position['quantity']) > 0.0001 or abs(new_position['realized_pnl']) > 0.001):
                new_positions.append(new_position)
        else:
            new_positions.append(p)

    # If ticker wasn't in snapshot before, add it
    if not found and new_position and (abs(new_position['quantity']) > 0.0001 or abs(new_position['realized_pnl']) > 0.001):
        new_positions.append(new_position)

    # Update total_value
    new_market_value = new_position['market_value'] if new_position else 0.0
    total_value = snapshot.get('total_value', 0.0) - old_market_value + new_market_value

    # Write updated snapshot
    try:
        snap_ref.set({
            "date": today,
            "total_value": round(total_value, 2),
            "positions": new_positions,
            "computed_at": datetime.utcnow(),
        })
        logger.info(f"Delta update for {ticker}: {len(new_positions)} positions, ${total_value:,.2f}")
        return True
    except Exception as e:
        logger.error(f"Delta update failed for {ticker}: {e}")
        return False


def get_cached_portfolio(db, user_id: str = "anonymous"):
    """
    Read today's snapshot if it exists and has positions.
    Otherwise compute fresh (and try to store).
    """
    today = datetime.utcnow().strftime('%Y-%m-%d')

    # Required fields that must exist in cached positions (add new fields here)
    REQUIRED_FIELDS = {"ticker", "quantity", "realized_pnl", "realized_pnl_ytd"}

    try:
        if user_id != "anonymous":
            doc = db.collection('users').document(user_id).collection('portfolio_snapshots').document(today).get()
        else:
            doc = db.collection('portfolio_snapshots').document(today).get()
        if doc.exists:
            d = doc.to_dict()
            positions = d.get('positions', [])
            if positions:
                # Validate cache has all required fields (recompute if schema changed)
                if REQUIRED_FIELDS.issubset(positions[0].keys()):
                    for p in positions:
                        p['date'] = datetime.utcnow().replace(tzinfo=None)
                    return positions
                else:
                    logger.info("Cached snapshot missing required fields — recomputing")
    except Exception:
        pass

    # No valid snapshot — compute fresh
    positions = calculate_portfolio(db, user_id=user_id)

    # Try to store snapshot (best-effort, don't fail if it errors)
    try:
        compute_and_store_snapshot(db, today, user_id=user_id)
    except Exception:
        pass

    return positions
