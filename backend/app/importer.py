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
            # Try reading as CSV
            # We don't know which one it is, so we read a few lines
            with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                first_lines = [f.readline() for _ in range(20)]
            
            content_sample = "".join(first_lines)
            
            # Detect File Type
            if "Assets,Date,Ticker" in content_sample:
                log.write("Detected Stock Trades.csv format - Clearing existing trades\n")
                db.query(models.Trade).delete()
                # db.commit() # Commit later
                
                # Header is likely line 2 (index 1), but let's be dynamic
                # The line "Assets,Date,Ticker" is the header.
                
                # Re-read with pandas
                # Find header row index
                header_row = 0
                for i, line in enumerate(first_lines):
                    if "Assets,Date,Ticker" in line:
                        header_row = i
                        break
                
                df = pd.read_csv(file_path, header=header_row)
                log.write(f"Columns: {df.columns.tolist()}\n")
                
                for index, row in df.iterrows():
                    if pd.isna(row.get('Ticker')):
                        continue
                        
                    try:
                        # Map columns
                        # "Assets,Date,Ticker, Price ,Number of stocks, Bought , Bought Amount ,Total number bought,Total Amount bought,Sold,Sold Amount,Total Sold number of stocks,Total sold amount,Average sell price, Average buy price , Realized Profit , Current Amount"
                        # Note spaces in column names
                        
                        col_ticker = 'Ticker'
                        col_date = 'Date'
                        col_price = ' Price ' if ' Price ' in df.columns else 'Price'
                        col_bought = ' Bought ' if ' Bought ' in df.columns else 'Bought'
                        col_sold = 'Sold' # Sold seems clean
                        
                        # Logic:
                        # If Bought > 0, it's a Buy
                        # If Sold > 0, it's a Sell
                        # This CSV might range per date?
                        # Let's look at the example row:
                        # EOG, 8-Apr-24, Bought 1.00, Sold 0.00.
                        # This looks like transactions.
                        
                        ticker = str(row.get(col_ticker)).strip()
                        date_val = pd.to_datetime(row.get(col_date), errors='coerce')
                        price_val = clean_currency(row.get(col_price))
                        
                        bought_qty = clean_currency(row.get(col_bought))
                        sold_qty = clean_currency(row.get(col_sold))
                        
                        if bought_qty > 0:
                            db.add(models.Trade(
                                date=date_val,
                                ticker=ticker,
                                type='Equity',
                                side='Buy',
                                price=price_val,
                                quantity=bought_qty,
                                currency='USD'
                            ))
                            log.write(f"Added Buy {ticker} {bought_qty}\n")
                            
                        if sold_qty != 0:
                            # Sold column might be negative (e.g. -150)
                            qty = abs(sold_qty)
                            
                            db.add(models.Trade(
                                date=date_val,
                                ticker=ticker,
                                type='Equity',
                                side='Sell',
                                price=price_val,
                                quantity=qty,
                                currency='USD'
                            ))
                            log.write(f"Added Sell {ticker} {qty}\n")

                    except Exception as e:
                        log.write(f"Error importing row {index}: {e}\n")

            elif "Equity Portfolio" in content_sample or "Main,Stats" in content_sample:
                log.write("Detected PortfolioSnapshot.csv format\n")
                # Header is deeper. Look for "Assets,Ticker"
                header_row = 0
                for i, line in enumerate(first_lines):
                    if "Assets,Ticker" in line:
                        header_row = i
                        break
                
                # If not found in first 20 lines, read more?
                if header_row == 0 and "Assets,Ticker" not in content_sample:
                    with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                        lines = f.readlines()
                        for i, line in enumerate(lines):
                             if "Assets,Ticker" in line:
                                header_row = i
                                break
                
                df = pd.read_csv(file_path, header=header_row)
                log.write(f"Columns: {df.columns.tolist()}\n")
                
                # Pre-fetch existing prices to avoid duplicates and N+1 queries
                price_cache = {p.ticker: p for p in db.query(models.AssetPrice).all()}
                
                for index, row in df.iterrows():
                    if pd.isna(row.get('Ticker')):
                        continue
                        
                    try:
                        ticker = str(row.get('Ticker')).strip()
                        price_val = clean_currency(row.get('Price'))
                        
                        if price_val > 0:
                            if ticker in price_cache:
                                price_cache[ticker].price = price_val
                                price_cache[ticker].last_updated = datetime.utcnow()
                                log.write(f"Updated price for {ticker}: {price_val}\n")
                            else:
                                new_price = models.AssetPrice(ticker=ticker, price=price_val, last_updated=datetime.utcnow())
                                db.add(new_price)
                                price_cache[ticker] = new_price
                                log.write(f"Added price for {ticker}: {price_val}\n")

                    except Exception as e:
                        log.write(f"Error importing snapshot price row {index}: {e}\n")
                        
            else:
                log.write("Unknown file format\n")
                
            db.commit()
            
        except Exception as e:
            log.write(f"Fatal error: {e}\n")
            raise e
