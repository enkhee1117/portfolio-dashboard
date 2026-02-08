import pandas as pd
from sqlalchemy.orm import Session
from . import models, schemas
from datetime import datetime

def import_data(db: Session, file_path: str): # file_path is the uploaded file, but we need to handle 2 specific CSVs.
    # The user uploads ONE file? or we look for files in likely locations?
    # The prompt says "import Stock Trades csv". 
    # Let's assume the user uploads `Stock Trades.csv`.
    # AND/OR `PortfolioSnapshot.csv`.
    # Since the API takes one file, we need to inspect the file content to decide what it is.
    
    with open("import_debug.log", "w") as log:
        log.write(f"Importing file: {file_path}\n")
        
        # Helper to clean currency strings
        def clean_currency(val):
            if pd.isna(val) or val == '':
                return 0.0
            if isinstance(val, str):
                clean_str = val.replace('$', '').replace(',', '').replace('(', '-').replace(')', '').replace('%', '').strip()
                if not clean_str or clean_str == '-':
                    return 0.0
                return float(clean_str)
            return float(val)

        try:
            new_trades_list = []
            trades_added_count = 0
            # Try reading as CSV
            # We don't know which one it is, so we read a few lines
            with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                first_lines = [f.readline() for _ in range(20)]
            
            content_sample = "".join(first_lines)
            
            # Detect File Type
            if "Assets,Date,Ticker" in content_sample:
                log.write("Detected Stock Trades.csv format - Using Smart Import (Deduplication)\n")
                
                # Fetch existing trades to build signature set
                # Signature: (Date, Ticker, Side, Price, Quantity)
                existing_trades = db.query(models.Trade).all()
                existing_signatures = set()
                for t in existing_trades:
                    # Normalize date to YYYY-MM-DD for comparison if needed, but datetime objects should compare fine 
                    # provided pandas timestamp matches. 
                    # Start with tuple.
                    sig = (t.date, t.ticker, t.side, t.price, t.quantity)
                    existing_signatures.add(sig)
                
                log.write(f"Loaded {len(existing_signatures)} existing trade signatures.\n")
                
                # Re-read with pandas
                # Find header row index
                header_row = 0
                for i, line in enumerate(first_lines):
                    if "Assets,Date,Ticker" in line:
                        header_row = i
                        break
                
                df = pd.read_csv(file_path, header=header_row)
                log.write(f"Columns: {df.columns.tolist()}\n")
                log.write(f"Rows found: {len(df)}\n")
                
                for index, row in df.iterrows():
                    # log.write(f"Processing row {index}: {row.get('Ticker', 'NaN')}\n")
                    if pd.isna(row.get('Ticker')):
                        continue
                        
                    try:
                        # Map columns
                        col_ticker = 'Ticker'
                        col_date = 'Date'
                        col_price = ' Price ' if ' Price ' in df.columns else 'Price'
                        col_qty = 'Number of stocks' if 'Number of stocks' in df.columns else 'Quantity' # Fallback
                        
                        ticker = str(row.get(col_ticker)).strip()
                        date_val = pd.to_datetime(row.get(col_date), errors='coerce')
                        price_val = clean_currency(row.get(col_price))
                        raw_qty = clean_currency(row.get(col_qty))
                        
                        # log.write(f"Parsed: {ticker} {date_val} {price_val} {raw_qty}\n")

                        if raw_qty != 0:
                            side = 'Buy' if raw_qty > 0 else 'Sell'
                            quantity = abs(raw_qty)
                            
                            # Create signature
                            date_py = date_val.to_pydatetime() if not pd.isna(date_val) else None
                            
                            if date_py:
                                sig = (date_py, ticker, side, price_val, quantity)
                                
                                if sig in existing_signatures:
                                    continue
                                
                                # New trade
                                trade_obj = models.Trade(
                                    date=date_py,
                                    ticker=ticker,
                                    type='Equity',
                                    side=side,
                                    price=price_val,
                                    quantity=quantity,
                                    currency='USD'
                                )
                                db.add(trade_obj)
                                new_trades_list.append(trade_obj)
                                
                                existing_signatures.add(sig)
                                trades_added_count += 1
                                log.write(f"Added {side} {ticker} {quantity}\n")

                    except Exception as e:
                        log.write(f"Error importing row {index}: {e}\n")
                
                log.write(f"Smart Import Complete: Added {trades_added_count} new trades.\n")
            
                # Run Wash Sale Detection (Nested inside the Stock Trades block)
                if new_trades_list:
                    # Flush to get IDs
                    db.flush()
                    log.write("Running Wash Sale Detection...\n")
                    from . import wash_sales
                    wash_sales.detect_wash_sales(new_trades_list)
                    log.write("Wash Sale Detection Complete.\n")

            elif "Equity Portfolio" in content_sample or "Main,Stats" in content_sample or "Assets\tTicker" in content_sample:
                log.write("Detected PortfolioSnapshot.csv format\n")
                
                # Determine separator
                sep = ','
                if "Assets\tTicker" in content_sample:
                     sep = '\t'
                     log.write("Using tab separator\n")

                # Header is deeper. Look for "Assets" and "Ticker"
                header_row = 0
                for i, line in enumerate(first_lines):
                    if "Assets" in line and "Ticker" in line:
                        header_row = i
                        break
                
                # If not found in first 20 lines, read more?
                if header_row == 0 and ("Assets" not in content_sample or "Ticker" not in content_sample):
                    with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                             if "Assets" in line and "Ticker" in line:
                                header_row = i
                                break
                
                df = pd.read_csv(file_path, header=header_row, sep=sep)
                log.write(f"Columns: {df.columns.tolist()}\n")
                
                # Pre-fetch existing prices to avoid duplicates and N+1 queries
                price_cache = {p.ticker: p for p in db.query(models.AssetPrice).all()}
                
                for index, row in df.iterrows():
                    if pd.isna(row.get('Ticker')):
                        continue
                        
                    try:
                        ticker = str(row.get('Ticker')).strip()
                        price_val = clean_currency(row.get('Price'))
                        
                        # Extract themes (handle missing columns gracefully)
                        p_theme = str(row.get('Primary theme', '')).strip() if 'Primary theme' in df.columns else None
                        s_theme = str(row.get('Secondary theme', '')).strip() if 'Secondary theme' in df.columns else None
                        
                        # Maps empty strings to None if preferred, or keep as empty strings
                        if p_theme == 'nan': p_theme = None
                        if s_theme == 'nan': s_theme = None

                        if price_val > 0:
                            if ticker in price_cache:
                                price_cache[ticker].price = price_val
                                price_cache[ticker].primary_theme = p_theme
                                price_cache[ticker].secondary_theme = s_theme
                                price_cache[ticker].last_updated = datetime.utcnow()
                                log.write(f"Updated price/theme for {ticker}: {price_val}\n")
                            else:
                                new_price = models.AssetPrice(
                                    ticker=ticker, 
                                    price=price_val, 
                                    primary_theme=p_theme, 
                                    secondary_theme=s_theme,
                                    last_updated=datetime.utcnow()
                                )
                                db.add(new_price)
                                price_cache[ticker] = new_price
                                log.write(f"Added price/theme for {ticker}: {price_val}\n")

                    except Exception as e:
                        log.write(f"Error importing snapshot price row {index}: {e}\n")
                        
            else:
                log.write("Unknown file format\n")
                
            db.commit()
            
            return {"added": trades_added_count}
            
        except Exception as e:
            log.write(f"Fatal error: {e}\n")
            raise e
