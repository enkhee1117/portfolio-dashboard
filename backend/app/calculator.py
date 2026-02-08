from sqlalchemy.orm import Session
from . import models, schemas
from collections import defaultdict

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

    # Fetch current prices
    asset_prices = {p.ticker: p.price for p in db.query(models.AssetPrice).all()}

    # Save snapshots or return data
    results = []
    for ticker, data in positions.items():
        if data["quantity"] != 0 or data["realized_pnl"] != 0:
            current_price = asset_prices.get(ticker, 0.0)
            market_value = data["quantity"] * current_price
            unrealized_pnl = (current_price - data["cost_basis"]) * data["quantity"] if current_price > 0 else 0.0
            
            results.append({
                "ticker": ticker,
                "quantity": data["quantity"],
                "average_price": data["cost_basis"],
                "realized_pnl": data["realized_pnl"],
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl
            })
    return results
