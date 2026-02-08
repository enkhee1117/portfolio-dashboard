import requests
import json

try:
    res = requests.get('http://localhost:8000/portfolio')
    data = res.json()
    
    print(f"Total positions: {len(data)}")
    
    with_theme = [d for d in data if d.get('primary_theme')]
    print(f"Positions with primary theme: {len(with_theme)}")
    
    for p in with_theme[:5]:
        print(f"Ticker: {p['ticker']}, Theme: {p['primary_theme']}")
        
    goog = next((d for d in data if d['ticker'] == 'GOOG'), None)
    if goog:
        print("GOOG data:", json.dumps(goog, indent=2))
    else:
        print("GOOG not found in portfolio")
        
except Exception as e:
    print(e)
