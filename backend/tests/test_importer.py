from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.main import app, get_db
import pytest
import os
import pandas as pd
from datetime import datetime

# Setup test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_importer.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(scope="module")
def test_db():
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal()
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test_importer.db"):
        os.remove("./test_importer.db")

def create_temp_csv(filename, data):
    df = pd.DataFrame(data)
    # create a mock csv with the specific header structure expected by importer
    # "Assets,Date,Ticker, Price ,Number of stocks..."
    # We need to match the signature detection in importer.py
    # "Assets,Date,Ticker" in content_sample
    
    # Let's construct a file manually to match the weird header format
    with open(filename, "w") as f:
        f.write("Some Metadata Line 1\n")
        f.write("Assets,Date,Ticker, Price ,Number of stocks, Bought , Bought Amount ,Total number bought,Total Amount bought,Sold,Sold Amount,Total Sold number of stocks,Total sold amount,Average sell price, Average buy price , Realized Profit , Current Amount\n")
        for row in data:
            f.write(f"Equity,{row['Date']},{row['Ticker']},{row['Price']},{row['Quantity']},,,,,,,,,,,,\n")

def test_smart_import_deduplication(test_db):
    # 1. First Import: Trade A
    csv1 = "test_trades_1.csv"
    data1 = [
        {"Date": "2024-01-01", "Ticker": "AAPL", "Price": "150.0", "Quantity": "10"}
    ]
    create_temp_csv(csv1, data1)
    
    with open(csv1, "rb") as f:
        response = client.post("/import", files={"file": ("test_trades_1.csv", f, "text/csv")})
    assert response.status_code == 200
    assert response.json()["message"] == "Import successful. Added 1 new trades."
    
    # Verify Trade A exists
    trades = client.get("/trades").json()
    assert len(trades) == 1
    trade_a_id = trades[0]["id"]
    assert trades[0]["ticker"] == "AAPL"
    
    # 2. Second Import: Trade A (Duplicate) + Trade B (New)
    csv2 = "test_trades_2.csv"
    data2 = [
        {"Date": "2024-01-01", "Ticker": "AAPL", "Price": "150.0", "Quantity": "10"}, # Duplicate
        {"Date": "2024-02-01", "Ticker": "MSFT", "Price": "300.0", "Quantity": "5"}   # New
    ]
    create_temp_csv(csv2, data2)
    
    with open(csv2, "rb") as f:
        response = client.post("/import", files={"file": ("test_trades_2.csv", f, "text/csv")})
    assert response.status_code == 200
    assert response.json()["message"] == "Import successful. Added 1 new trades." # Only 1 new (MSFT), 1 duplicate (AAPL)
    
    # Verify Total Trades = 2 (not 1 if wiped, not 3 if duplicated)
    # Wait, if wipe: ID changes.
    # If dedupe: ID of A stays same.
    
    trades_updated = client.get("/trades").json()
    assert len(trades_updated) == 2
    
    # Check IDs
    ids = [t["id"] for t in trades_updated]
    assert trade_a_id in ids, "Original Trade ID should persist (Deduplication check)"
    
    # Cleanup
    os.remove(csv1)
    os.remove(csv2)
