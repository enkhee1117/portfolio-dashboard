from sqlalchemy.orm import Session
from . import models, schemas
from collections import defaultdict
from datetime import datetime

def calculate_portfolio(db: Session):
    trades = db.query(models.Trade).all()
    positions = defaultdict(lambda: {"quantity": 0, "cost_basis": 0.0, "realized_pnl": 0.0})

    for trade in trades:
        ticker = trade.ticker
        if trade.type == 'Equity':
            qty = trade.quantity
            price = trade.price
            
            if trade.side == 'Buy':
                # Update weighted average cost
                current_qty = positions[ticker]["quantity"]
                current_cost = positions[ticker]["cost_basis"]
                
                new_qty = current_qty + qty
                if new_qty > 0:
                    positions[ticker]["cost_basis"] = ((current_qty * current_cost) + (qty * price)) / new_qty
                positions[ticker]["quantity"] = new_qty
                
            elif trade.side == 'Sell':
                # Calculating Realized P&L
                avg_cost = positions[ticker]["cost_basis"]
                pnl = (price - avg_cost) * qty
                positions[ticker]["realized_pnl"] += pnl
                positions[ticker]["quantity"] -= qty

        # TODO: Add Option logic

    # Fetch current prices and themes
    asset_data = {p.ticker: {'price': p.price, 'primary': p.primary_theme, 'secondary': p.secondary_theme} for p in db.query(models.AssetPrice).all()}
    with open("debug_calc.log", "w") as f:
        f.write(f"DEBUG: GOOG data from DB: {asset_data.get('GOOG')}\\n")

    # Save snapshots or return data
    results = []
    for ticker, data in positions.items():
        if data["quantity"] != 0 or data["realized_pnl"] != 0:
            current_price = 0.0
            p_theme = None
            s_theme = None
            
            if ticker in asset_data:
                current_price = asset_data[ticker]['price']
                p_theme = asset_data[ticker]['primary']
                s_theme = asset_data[ticker]['secondary']
                
            market_val = data["quantity"] * current_price
            unrealized = (current_price - data["cost_basis"]) * data["quantity"] if data["quantity"] != 0 else 0.0

            results.append({
                "ticker": ticker,
                "quantity": data["quantity"],
                "average_price": data["cost_basis"],
                "current_price": current_price,
                "market_value": market_val,
                "unrealized_pnl": unrealized,
                "realized_pnl": data["realized_pnl"],
                "date": datetime.utcnow(),
                "primary_theme": p_theme,
                "secondary_theme": s_theme
            })
    return results
