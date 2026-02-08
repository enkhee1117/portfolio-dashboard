import requests
import pandas as pd

try:
    response = requests.get('http://localhost:8000/portfolio')
    data = response.json()
    
    df = pd.DataFrame(data)
    
    active_positions = df[df['quantity'] > 0]
    total_active = len(active_positions)
    
    missing_price = active_positions[active_positions['current_price'] == 0]
    missing_theme = active_positions[active_positions['primary_theme'].isnull()]
    
    print(f"Total Active Positions: {total_active}")
    print(f"Missing Price: {len(missing_price)}")
    print(f"Missing Theme: {len(missing_theme)}")
    
    if len(missing_price) > 0:
        print("\nTop 5 Active Tickers with Missing Price:")
        print(missing_price[['ticker', 'quantity']].head(5))
        
    if len(missing_theme) > 0:
        print("\nTop 5 Active Tickers with Missing Theme:")
        print(missing_theme[['ticker', 'quantity', 'current_price']].head(5))

except Exception as e:
    print(f"Error: {e}")
