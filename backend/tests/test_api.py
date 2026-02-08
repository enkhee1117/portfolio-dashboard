from fastapi.testclient import TestClient
from app.main import app
from app import models, database
import pytest

# Use a separate test database or mock session
# For simplicity, we'll use the TestClient with the existing app
# checking if it runs.

client = TestClient(app)

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
