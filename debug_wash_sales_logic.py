from backend.app import models, database, wash_sales
from datetime import datetime, timedelta

db = database.SessionLocal()
trades = db.query(models.Trade).all()
print(f"Total trades: {len(trades)}")

# Check SWN
swn = [t for t in trades if t.ticker == 'SWN']
print(f"SWN trades: {len(swn)}")
for t in swn:
    print(f"ID: {t.id}, Date: {t.date} ({type(t.date)}), Side: {t.side}")

# Run detection
print("Running detection...")
try:
    wash_sales_map = wash_sales.detect_wash_sales(trades)
    print(f"Detected wash sales: {len(wash_sales_map)}")
    print(f"Wash sales map keys: {list(wash_sales_map.keys())}")
    
    # Commit changes
    print("Committing changes...")
    db.commit()
    print("Committed.")
    
except Exception as e:
    print(f"Error: {e}")
