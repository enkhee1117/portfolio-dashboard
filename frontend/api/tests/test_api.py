from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app, get_db
from app import models, database
import pytest
import os

# Setup test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_api.db"
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

@pytest.fixture(scope="module", autouse=True)
def test_db():
    models.Base.metadata.create_all(bind=engine)
    yield
    models.Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test_api.db"):
        os.remove("./test_api.db")

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Portfolio Tracker API"}

def test_get_trades():
    response = client.get("/trades")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_portfolio():
    response = client.get("/portfolio")
    assert response.status_code == 200
    # Check structure of first item if exists
    data = response.json()
    if data:
        item = data[0]
        assert "ticker" in item
        assert "current_price" in item
        assert "primary_theme" in item

def test_create_manual_trade():
    # Test creating a trade via API
    # Use a ticker that won't mess up main data too much, or clean up after.
    # We can use a mock session to avoid writing to prod DB, but 
    # for this "bootstrap" phase, we might just test the endpoint existence/validation.
    
    new_trade = {
        "date": "2025-01-01T00:00:00",
        "ticker": "TEST_TICKER",
        "type": "Equity",
        "side": "Buy",
        "price": 100.0,
        "quantity": 10.0,
        "currency": "USD"
    }
    
    response = client.post("/trades/manual", json=new_trade)
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "TEST_TICKER"
    assert data["id"] is not None
    
    # Verify it appears in trades list
    trades_resp = client.get("/trades")
    trades = trades_resp.json()
    assert any(t["ticker"] == "TEST_TICKER" for t in trades)

    # Clean up (optional, relying on user to reset DB or ignored)
    # Ideally should delete, but we don't have delete endpoint yet.

def test_prevent_duplicate_manual_trade():
    """
    Test 1: Add Trade -> Success
    Test 2: Add Same Trade -> 409 Conflict
    Test 3: Add Same Trade + force=true -> Success
    """
    trade_data = {
        "date": "2025-06-01T12:00:00",
        "ticker": "DUP_TEST",
        "type": "Equity",
        "side": "Buy",
        "price": 50.0,
        "quantity": 100.0,
        "currency": "USD"
    }
    
    # 1. First Add
    resp1 = client.post("/trades/manual", json=trade_data)
    assert resp1.status_code == 200
    
    # 2. Second Add (Duplicate)
    resp2 = client.post("/trades/manual", json=trade_data)
    assert resp2.status_code == 409
    assert "Duplicate trade detected" in resp2.json()["detail"]
    
    # 3. Third Add (Force)
    resp3 = client.post("/trades/manual?force=true", json=trade_data)
    assert resp3.status_code == 200
    
    # Verify we have 2 trades for DUP_TEST (from step 1 and 3)
    trades = client.get("/trades").json()
    dup_trades = [t for t in trades if t["ticker"] == "DUP_TEST"]
    assert len(dup_trades) == 2

def test_delete_trade_recalculates_wash_sale():
    """
    Scenario:
    1. Buy A (Jan 1)
    2. Sell A (Feb 1) @ Loss
    3. Buy A (Feb 15) -> Triggers Wash Sale on Sell
    4. DELETE Buy A (Feb 15) -> Wash Sale on Sell should be CLEARED
    """
    ticker = "WASH_DEL_TEST"
    
    # 1. Buy
    t1 = client.post("/trades/manual", json={
        "date": "2024-01-01T00:00:00", "ticker": ticker, "side": "Buy", "price": 100.0, "quantity": 10, "type": "Equity"
    })
    
    # 2. Sell @ Loss
    t2 = client.post("/trades/manual", json={
        "date": "2024-02-01T00:00:00", "ticker": ticker, "side": "Sell", "price": 90.0, "quantity": 10, "type": "Equity"
    }) 
    
    # 3. Buy Replacement
    t3 = client.post("/trades/manual", json={
        "date": "2024-02-15T00:00:00", "ticker": ticker, "side": "Buy", "price": 95.0, "quantity": 10, "type": "Equity"
    })
    
    # Verify Wash Sale is present on t2
    trades = client.get("/trades").json()
    t2_check = next(t for t in trades if t["id"] == t2.json()["id"])
    assert t2_check["is_wash_sale"] == True
    
    # 4. DELETE t3
    t3_id = t3.json()["id"]
    del_resp = client.delete(f"/trades/{t3_id}")
    assert del_resp.status_code == 200
    
    # Verify Wash Sale is GONE from t2
    trades_after = client.get("/trades").json()
    t2_check_after = next(t for t in trades_after if t["id"] == t2_check["id"])
    assert t2_check_after["is_wash_sale"] == False

def test_update_trade():
    """
    Test updating price/quantity
    """
    # Create trade
    resp = client.post("/trades/manual", json={
        "date": "2024-06-01T00:00:00", "ticker": "UPD_TEST", "side": "Buy", "price": 100.0, "quantity": 10, "type": "Equity"
    })
    trade_id = resp.json()["id"]
    
    # Update
    update_data = resp.json()
    update_data["price"] = 200.0
    update_data["quantity"] = 20.0
    
    put_resp = client.put(f"/trades/{trade_id}", json=update_data)
    assert put_resp.status_code == 200
    assert put_resp.json()["price"] == 200.0
    assert put_resp.json()["quantity"] == 20.0
    
    # Verify in DB
    get_resp = client.get("/trades")
    trade = next(t for t in get_resp.json() if t["id"] == trade_id)
    assert trade["price"] == 200.0

def test_update_trade_triggers_wash_sale():
    """
    Scenario:
    1. Buy A (Jan 1)
    2. Sell A (Feb 1) @ Loss
    3. Buy A (Mar 5) -> Outside 30 day window. No Wash Sale.
    4. EDIT Buy A date to (Feb 15) -> Inside window. Should Trigger Wash Sale.
    """
    ticker = "WASH_UPD_TEST"
    
    # 1. Buy
    t1 = client.post("/trades/manual", json={
        "date": "2024-01-01T00:00:00", "ticker": ticker, "side": "Buy", "price": 100.0, "quantity": 10, "type": "Equity"
    })
    
    # 2. Sell @ Loss
    t2 = client.post("/trades/manual", json={
        "date": "2024-02-01T00:00:00", "ticker": ticker, "side": "Sell", "price": 90.0, "quantity": 10, "type": "Equity"
    }) 
    
    # 3. Buy Replacement (Outside Window: +33 days)
    t3 = client.post("/trades/manual", json={
        "date": "2024-03-05T00:00:00", "ticker": ticker, "side": "Buy", "price": 95.0, "quantity": 10, "type": "Equity"
    })
    
    # Verify NO Wash Sale
    trades = client.get("/trades").json()
    t2_check = next(t for t in trades if t["id"] == t2.json()["id"])
    assert t2_check["is_wash_sale"] == False
    
    # 4. EDIT t3 date to Inside Window (+14 days)
    t3_id = t3.json()["id"]
    t3_data = t3.json()
    t3_data["date"] = "2024-02-15T00:00:00"
    
    put_resp = client.put(f"/trades/{t3_id}", json=t3_data)
    assert put_resp.status_code == 200
    
    # Verify Wash Sale is NOW PRESENT on t2
    trades_after = client.get("/trades").json()
    t2_check_after = next(t for t in trades_after if t["id"] == t2_check["id"])
    assert t2_check_after["is_wash_sale"] == True
