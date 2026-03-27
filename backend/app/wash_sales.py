from datetime import timedelta
from typing import List, Dict
from . import schemas
from google.cloud import firestore

def detect_wash_sales(trades: List[schemas.Trade], db: firestore.Client) -> Dict[str, bool]:
    wash_sales = {}
    
    # Sort trades by date
    sorted_trades = sorted(trades, key=lambda x: x.date)
    
    # Organize by ticker
    trades_by_ticker = {}
    for trade in sorted_trades:
        if trade.ticker not in trades_by_ticker:
            trades_by_ticker[trade.ticker] = []
        trades_by_ticker[trade.ticker].append(trade)
        
    for ticker, t_list in trades_by_ticker.items():
        t_list.sort(key=lambda x: x.date)
        
        inventory = [] 
        
        for i, trade in enumerate(t_list):
            if trade.type == 'Equity':
                if trade.side == 'Buy':
                    inventory.append({
                        'price': trade.price,
                        'quantity': trade.quantity,
                        'date': trade.date,
                        'id': trade.id
                    })
                
                elif trade.side == 'Sell':
                    qty_to_sell = trade.quantity
                    total_cost_basis = 0.0
                    shares_sold_count = 0.0
                    consumed_buy_ids = set()
                    
                    while qty_to_sell > 0 and inventory:
                        lot = inventory[0] # FIFO
                        
                        consumed_buy_ids.add(lot['id'])
                        
                        if lot['quantity'] > qty_to_sell:
                            cost_contribution = qty_to_sell * lot['price']
                            total_cost_basis += cost_contribution
                            shares_sold_count += qty_to_sell
                            
                            lot['quantity'] -= qty_to_sell
                            qty_to_sell = 0
                        else:
                            cost_contribution = lot['quantity'] * lot['price']
                            total_cost_basis += cost_contribution
                            shares_sold_count += lot['quantity']
                            
                            qty_to_sell -= lot['quantity']
                            inventory.pop(0)
                    
                    if shares_sold_count > 0:
                        avg_sell_price = trade.price
                        proceeds = avg_sell_price * shares_sold_count
                        realized_pnl = proceeds - total_cost_basis
                        
                        if realized_pnl < -0.01:
                            window_start = trade.date
                            window_end = trade.date + timedelta(days=30)
                            
                            is_wash = False
                            
                            for other_trade in t_list:
                                if other_trade.id == trade.id:
                                    continue
                                
                                if other_trade.side == 'Buy':
                                    if other_trade.id in consumed_buy_ids:
                                        continue
                                        
                                    if window_start < other_trade.date <= window_end:
                                        is_wash = True
                                        break
                            
                            if is_wash:
                                wash_sales[trade.id] = True
                                trade.is_wash_sale = True
                            else:
                                trade.is_wash_sale = False
                        else:
                            trade.is_wash_sale = False

    # Persist the wash sale statuses back to Firestore
    # To reduce writes we could do a batch update, but we'll do it sequentially for now
    batch = db.batch()
    update_count = 0
    for trade in trades:
        # Assuming you want to update all trades that were checked.
        trade_ref = db.collection('trades').document(trade.id)
        batch.update(trade_ref, {"is_wash_sale": trade.is_wash_sale})
        update_count += 1
        if update_count >= 400: # Firestore batch limit is 500
            batch.commit()
            batch = db.batch()
            update_count = 0
    
    if update_count > 0:
        batch.commit()

    return wash_sales
