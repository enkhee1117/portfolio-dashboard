from . import schemas
from collections import defaultdict
from datetime import datetime

def calculate_portfolio(db):
    trades_docs = db.collection('trades').stream()
    trades = [schemas.Trade(id=doc.id, **doc.to_dict()) for doc in trades_docs]
    
    positions = defaultdict(lambda: {"quantity": 0, "cost_basis": 0.0, "realized_pnl": 0.0})

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
                positions[ticker]["quantity"] -= qty

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
                "date": datetime.utcnow().replace(tzinfo=None), # Keep naive datetime for pydantic
                "primary_theme": p_theme,
                "secondary_theme": s_theme
            })
    return results
