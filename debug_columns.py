import pandas as pd

file_path = "PortfolioSnapshot.csv"
print(f"Reading {file_path}...")

with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
    lines = f.readlines()

header_row = 0
for i, line in enumerate(lines[:20]):
    if "Assets" in line and "Ticker" in line:
        print(f"Found header candidate at line {i}: {repr(line)}")
        header_row = i
        break

try:
    # Try default (comma)
    df = pd.read_csv(file_path, header=header_row)
    print(f"Columns (Comma): {df.columns.tolist()}")
    
    # Check if we have one column (incorrect parse)
    if len(df.columns) < 2:
        print("Comma failed, trying tab...")
        df = pd.read_table(file_path, header=header_row)
        print(f"Columns (Tab): {df.columns.tolist()}")

except Exception as e:
    print(e)
