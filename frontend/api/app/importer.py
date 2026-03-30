import pandas as pd
from . import schemas
from datetime import datetime
from google.cloud import firestore


def normalize_theme(name: str) -> str:
    """Normalize theme names to Title Case for consistent grouping."""
    return name.strip().title() if name else ""

def import_data(db: firestore.Client, file_path: str, skip_dedup: bool = False, user_id: str = "anonymous"):
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
        
        with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            first_lines = [f.readline() for _ in range(20)]
        content_sample = "".join(first_lines)
        
        if "Assets,Date,Ticker" in content_sample:
            # Load existing trades for deduplication (skip if requested to save quota)
            existing_signatures = set()
            if not skip_dedup:
                existing_docs = db.collection('trades').stream()
                for doc in existing_docs:
                    d = doc.to_dict()
                    if 'date' in d and 'ticker' in d and 'side' in d and 'price' in d and 'quantity' in d:
                        dt = d['date'].replace(tzinfo=None) if hasattr(d['date'], 'replace') else d['date']
                        existing_signatures.add((dt, d['ticker'], d['side'], d['price'], d['quantity']))
            
            header_row = 0
            for i, line in enumerate(first_lines):
                if "Assets,Date,Ticker" in line:
                    header_row = i
                    break
            
            df = pd.read_csv(file_path, header=header_row)
            batch = db.batch()
            batch_count = 0
            
            for index, row in df.iterrows():
                if pd.isna(row.get('Ticker')):
                    continue
                try:
                    col_ticker = 'Ticker'
                    col_date = 'Date'
                    col_price = ' Price ' if ' Price ' in df.columns else 'Price'
                    col_qty = 'Number of stocks' if 'Number of stocks' in df.columns else 'Quantity'
                    
                    ticker = str(row.get(col_ticker)).strip().upper()
                    date_val = pd.to_datetime(row.get(col_date), errors='coerce')
                    price_val = clean_currency(row.get(col_price))
                    raw_qty = clean_currency(row.get(col_qty))
                    
                    if raw_qty != 0:
                        side = 'Buy' if raw_qty > 0 else 'Sell'
                        quantity = abs(raw_qty)
                        date_py = date_val.to_pydatetime() if not pd.isna(date_val) else None
                        
                        if date_py:
                            sig = (date_py, ticker, side, price_val, quantity)
                            if sig in existing_signatures:
                                continue
                            
                            trade_obj = schemas.TradeCreate(
                                date=date_py,
                                ticker=ticker,
                                type='Equity',
                                side=side,
                                price=price_val,
                                quantity=quantity,
                                currency='USD'
                            )
                            
                            doc_ref = db.collection('trades').document()
                            t_dict = trade_obj.model_dump()
                            t_dict['user_id'] = user_id
                            batch.set(doc_ref, t_dict)
                            
                            # build list for wash sales
                            t_dict['id'] = doc_ref.id
                            new_trades_list.append(schemas.Trade(**t_dict))
                            existing_signatures.add(sig)
                            trades_added_count += 1
                            batch_count += 1
                            
                            if batch_count >= 400:
                                batch.commit()
                                batch = db.batch()
                                batch_count = 0
                except Exception as e:
                    print(f"Error importing row {index}: {e}")
            
            if batch_count > 0:
                batch.commit()
            
            if new_trades_list:
                try:
                    from . import wash_sales
                    affected_tickers = set([t.ticker for t in new_trades_list])
                    for t in affected_tickers:
                        from google.cloud.firestore_v1.base_query import FieldFilter
                        tdocs = db.collection('trades').where(filter=FieldFilter('ticker', '==', t)).stream()
                        all_t = []
                        for td in tdocs:
                            d = td.to_dict()
                            if 'date' in d and hasattr(d['date'], 'replace'):
                                d['date'] = d['date'].replace(tzinfo=None)
                            d['id'] = td.id
                            all_t.append(schemas.Trade(**d))
                        wash_sales.detect_wash_sales(all_t, db)
                except Exception as wash_err:
                    print(f"Wash sales detection failed (trades were still imported): {wash_err}")

        elif "Equity Portfolio" in content_sample or "Main,Stats" in content_sample or "Assets\tTicker" in content_sample or ("Assets" in content_sample and "Ticker" in content_sample and "Primary theme" in content_sample):
            sep = '\t' if "Assets\tTicker" in content_sample else ','
            header_row = 0
            for i, line in enumerate(first_lines):
                if "Assets" in line and "Ticker" in line:
                    header_row = i
                    break
            
            if header_row == 0 and ("Assets" not in content_sample or "Ticker" not in content_sample):
                with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                    lines = f.readlines()
                    for i, line in enumerate(lines):
                        if "Assets" in line and "Ticker" in line:
                            header_row = i
                            break
            
            df = pd.read_csv(file_path, header=header_row, sep=sep)
            
            batch = db.batch()
            batch_count = 0
            
            # Since asset_prices replaces older data, we just query existing once
            # or rely on batch.set() to overwrite if doc IDs are predictable
            # Let's use `ticker` as the document ID for asset_prices!
            for index, row in df.iterrows():
                if pd.isna(row.get('Ticker')):
                    continue
                try:
                    ticker = str(row.get('Ticker')).strip().upper()
                    price_val = clean_currency(row.get('Price'))
                    
                    p_theme = str(row.get('Primary theme', '')).strip() if 'Primary theme' in df.columns else None
                    s_theme = str(row.get('Secondary theme', '')).strip() if 'Secondary theme' in df.columns else None
                    if p_theme == 'nan': p_theme = None
                    if s_theme == 'nan': s_theme = None

                    if price_val > 0:
                        # Ensure shared price entry exists (for price refresh)
                        shared_ref = db.collection('asset_prices').document(ticker)
                        if not shared_ref.get().exists:
                            batch.set(shared_ref, {
                                'ticker': ticker,
                                'price': price_val,
                                'last_updated': datetime.utcnow()
                            })
                            batch_count += 1

                        # Write themes to user-scoped asset_themes
                        if user_id and user_id != "anonymous":
                            theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
                            batch.set(theme_ref, {
                                'ticker': ticker,
                                'primary': normalize_theme(p_theme) if p_theme else '',
                                'secondary': normalize_theme(s_theme) if s_theme else '',
                            }, merge=True)
                            batch_count += 1

                        if batch_count >= 400:
                            batch.commit()
                            batch = db.batch()
                            batch_count = 0

                except Exception as e:
                    print(f"Error importing row {index}: {e}")
                    
            if batch_count > 0:
                batch.commit()
                
        return {"added": trades_added_count}
        
    except Exception as e:
        raise e
