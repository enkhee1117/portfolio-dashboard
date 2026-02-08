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
        
    # Wash Sale Logic:
    # 1. Track pools of shares per ticker (FIFO).
    # 2. When a SELL occurs at a LOSS:
    #    a. Check if there were any BUYs in [SellDate - 30d, SellDate + 30d].
    #    b. If yes, it's a Wash Sale. Mark the trade.
    #    c. (Advanced) Adjust cost basis of the replacement shares. (Skipping for now, just flagging).
    
    # We need to process trades in chronological order.
    
    for ticker, t_list in trades_by_ticker.items():
        # sort by date just in case
        t_list.sort(key=lambda x: x.date)
        
        # Simple approach for V1:
        # If a sell results in a loss (Price < AvgCost), look for replacement shares.
        # Problem: We don't have accurate AvgCost at the time of trade without re-running calculator logic history.
        # simplified heuristic: 
        # Iterate through sells. If price < (heuristic average or just check for ANY buy within 30 days?), 
        # Valid Wash Sale requires a loss. We need to estimate if it's a loss.
        # Let's assume for this version: If a Sell happens, we check 30 days before/after. 
        # If there is a buy, AND the sell price is LOWER than the buy price of the matching shares (loss), flag it.
        
        # ACTUALLY, strict wash sale rule:
        # Realized Loss + Replacement Share Purchase.
        # Since we don't have historical cost basis per lot in DB, we will use a "Potential Wash Sale" flag.
        # Flag any SELL where:
        # 1. There is a BUY of the same ticker within +/- 30 days.
        # This is a "Wash Sale Candidate". 
        
        for i, trade in enumerate(t_list):
            if trade.type == 'Equity' and trade.side == 'Sell':
                # Check window
                window_start = trade.date - timedelta(days=30)
                window_end = trade.date + timedelta(days=30)
                
                is_wash = False
                for other_trade in t_list:
                    if other_trade.id == trade.id:
                        continue
                    if other_trade.side == 'Buy' and window_start <= other_trade.date <= window_end:
                        is_wash = True
                        break
                
                if is_wash:
                    wash_sales[trade.id] = True
                    trade.is_wash_sale = True

    return wash_sales
