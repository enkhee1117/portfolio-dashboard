import pandas as pd
import sys

def clean_currency(val):
    if pd.isna(val) or val == '':
        return 0.0
    if isinstance(val, str):
        clean_str = val.replace('$', '').replace(',', '').replace('(', '-').replace(')', '').replace('%', '').strip()
        if not clean_str or clean_str == '-':
            return 0.0
        return float(clean_str)
    return float(val)

file_path = "Stock Trades.csv"
print(f"Reading {file_path}...")

with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
    lines = f.readlines()

header_row = 0
for i, line in enumerate(lines[:20]):
    if "Assets,Date,Ticker" in line:
        header_row = i
        break

print(f"Header row: {header_row}")
df = pd.read_csv(file_path, header=header_row)
print(f"Total rows in DF: {len(df)}")
print(f"Columns: {df.columns.tolist()}")

skipped_count = 0
valid_count = 0

for index, row in df.iterrows():
    if pd.isna(row.get('Ticker')):
        continue
    
    col_bought = ' Bought ' if ' Bought ' in df.columns else 'Bought'
    col_sold = 'Sold' # Sold seems clean
                        
    bought_raw = row.get(col_bought)
    sold_raw = row.get(col_sold)
    
    bought_qty = clean_currency(bought_raw)
    sold_qty = clean_currency(sold_raw)
    
    if bought_qty > 0 or sold_qty > 0:
        valid_count += 1
    else:
        skipped_count += 1
        if skipped_count < 10:
            print(f"Skipped Row {index}: Ticker={row.get('Ticker')}, Bought='{bought_raw}'->{bought_qty}, Sold='{sold_raw}'->{sold_qty}")

print(f"Valid trades: {valid_count}")
print(f"Skipped trades: {skipped_count}")
