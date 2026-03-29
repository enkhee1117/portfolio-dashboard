from . import schemas
from collections import defaultdict
from datetime import datetime
import logging

logger = logging.getLogger("portfolio")

def calculate_portfolio(db):
    trades_docs = db.collection('trades').stream()
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

    # Fetch current prices and themes
    price_docs = db.collection('asset_prices').stream()
    asset_data = {}
    for doc in price_docs:
        d = doc.to_dict()
        asset_data[d.get('ticker')] = {
            'price': d.get('price', 0.0),
            'primary': d.get('primary_theme'),
            'secondary': d.get('secondary_theme')
        }

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


def compute_and_store_snapshot(db, date_str: str | None = None):
    """
    Compute portfolio value and store as a daily snapshot.
    If date_str is None, uses today's date.
    Returns the snapshot dict.
    """
    if date_str is None:
        date_str = datetime.utcnow().strftime('%Y-%m-%d')

    positions = calculate_portfolio(db)
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

    db.collection('portfolio_snapshots').document(date_str).set(snapshot)
    logger.info(f"Snapshot stored for {date_str}: ${total_value:,.2f} ({len(positions_data)} positions)")

    return snapshot


def get_cached_portfolio(db):
    """
    Read today's snapshot if it exists and has positions.
    Otherwise compute fresh (and try to store).
    """
    today = datetime.utcnow().strftime('%Y-%m-%d')

    # Required fields that must exist in cached positions (add new fields here)
    REQUIRED_FIELDS = {"ticker", "quantity", "realized_pnl", "realized_pnl_ytd"}

    try:
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
    positions = calculate_portfolio(db)

    # Try to store snapshot (best-effort, don't fail if it errors)
    try:
        compute_and_store_snapshot(db, today)
    except Exception:
        pass

    return positions
