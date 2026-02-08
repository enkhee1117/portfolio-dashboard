from datetime import timedelta
from typing import List, Dict
from . import models

def detect_wash_sales(trades: List[models.Trade]) -> Dict[int, bool]:
    """
    Detects wash sales in a list of trades.
    Returns a dictionary mapping Trade ID to True if it constitutes a wash sale (loss disallowed).
    
    Rule: A wash sale occurs when you sell or trade a security at a loss and within 30 days 
    before or after the sale you:
    1. Buy or acquire a substantially identical security,
    2. Acquire a contract or option to buy a substantially identical security.
    
    For this implementation, we check for Buys of the SAME ticker within the window.
    """
    wash_sales = {}
    
    # Sort trades by date
    sorted_trades = sorted(trades, key=lambda x: x.date)
    
    # Organize by ticker
    trades_by_ticker = {}
    for trade in sorted_trades:
        if trade.ticker not in trades_by_ticker:
            trades_by_ticker[trade.ticker] = []
        trades_by_ticker[trade.ticker].append(trade)
        
    # Wash Sale Logic with FIFO Cost Basis
    
    for ticker, t_list in trades_by_ticker.items():
        # Sort by date
        t_list.sort(key=lambda x: x.date)
        
        # FIFO Queue: List of specific lots [date, price, quantity, original_trade_id]
        # We really just need {price, quantity} for cost basis, but date helps for debug.
        # We don't have permanent lot tracking in DB yet, so we reconstruct it from the full trade history.
        inventory = [] 
        
        for i, trade in enumerate(t_list):
            if trade.type == 'Equity':
                if trade.side == 'Buy':
                    # Add to inventory
                    inventory.append({
                        'price': trade.price,
                        'quantity': trade.quantity,
                        'date': trade.date,
                        'id': trade.id
                    })
                
                elif trade.side == 'Sell':
                    # Process Sell against Inventory (FIFO)
                    qty_to_sell = trade.quantity
                    total_cost_basis = 0.0
                    shares_sold_count = 0.0
                    consumed_buy_ids = set() # Track IDs of buys consumed in this sale
                    
                    # Consume inventory
                    while qty_to_sell > 0 and inventory:
                        lot = inventory[0] # FIFO: take from front
                        
                        consumed_buy_ids.add(lot['id'])
                        
                        if lot['quantity'] > qty_to_sell:
                            # Partial lot consumed
                            cost_contribution = qty_to_sell * lot['price']
                            total_cost_basis += cost_contribution
                            shares_sold_count += qty_to_sell
                            
                            lot['quantity'] -= qty_to_sell
                            qty_to_sell = 0
                        else:
                            # Full lot consumed
                            cost_contribution = lot['quantity'] * lot['price']
                            total_cost_basis += cost_contribution
                            shares_sold_count += lot['quantity']
                            
                            qty_to_sell -= lot['quantity']
                            inventory.pop(0)
                    
                    # Calculate P&L
                    # If we ran out of inventory, we assume cost basis of 0 for remaining (or error).
                    # For now, just calculate based on what we matched.
                    if shares_sold_count > 0:
                        avg_sell_price = trade.price
                        # Realized P&L = (Sell Price * Qty) - Cost Basis
                        proceeds = avg_sell_price * shares_sold_count
                        realized_pnl = proceeds - total_cost_basis
                        
                        # CHECK WASH SALE RULE
                        if realized_pnl < -0.01: # Use small epsilon for float comparison
                            # It's a LOSS. Check for replacement shares.
                            # It's a LOSS. Check for replacement shares.
                            # User Logic: Only check +30 days (Forward looking only)
                            # Window: (SellDate, SellDate + 30d]
                            window_start = trade.date
                            window_end = trade.date + timedelta(days=30)
                            
                            is_wash = False
                            
                            for other_trade in t_list:
                                if other_trade.id == trade.id:
                                    continue
                                
                                # Must be a Buy
                                if other_trade.side == 'Buy':
                                    # SKIP if this buy was the one we just sold (or part of it)
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
                            # Gain. Not a wash sale.
                            trade.is_wash_sale = False

    return wash_sales

    return wash_sales
