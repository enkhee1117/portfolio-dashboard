"""
Importer tests using a mocked Firestore client.
Creates a temporary CSV file in the same format the importer expects,
then verifies the correct number of trades were added.
"""
import pytest
import os
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app, get_db


# ── CSV helper ────────────────────────────────────────────────────────────────

def create_temp_csv(filename, rows):
    """Write a CSV in the exact format the importer recognises."""
    header = (
        "Some Metadata Line 1\n"
        "Assets,Date,Ticker, Price ,Number of stocks, Bought , Bought Amount ,"
        "Total number bought,Total Amount bought,Sold,Sold Amount,"
        "Total Sold number of stocks,Total sold amount,Average sell price,"
        " Average buy price , Realized Profit , Current Amount\n"
    )
    with open(filename, "w") as f:
        f.write(header)
        for row in rows:
            f.write(f"Equity,{row['Date']},{row['Ticker']},{row['Price']},{row['Quantity']},,,,,,,,,,,,\n")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_firebase(monkeypatch):
    monkeypatch.setattr("firebase_admin._apps", {"default": True})


def make_import_db(existing_docs=None):
    """
    Return a mock db where:
    - collection('trades').stream() returns existing_docs
    - batch().set() and batch().commit() are no-ops
    """
    db = MagicMock()
    existing_docs = existing_docs or []

    trades_col = MagicMock()
    trades_col.stream.return_value = existing_docs
    trades_col.where.return_value = trades_col
    trades_col.document.return_value = MagicMock(id="new-id")

    db.collection.return_value = trades_col
    db.batch.return_value = MagicMock()
    return db


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_import_adds_new_trades(tmp_path):
    """Importing a CSV with 1 new trade should add 1 trade."""
    db = make_import_db(existing_docs=[])
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    csv_file = tmp_path / "trades.csv"
    create_temp_csv(str(csv_file), [
        {"Date": "2024-01-01", "Ticker": "AAPL", "Price": "150.0", "Quantity": "10"},
    ])

    with open(csv_file, "rb") as f:
        resp = client.post("/import", files={"file": ("trades.csv", f, "text/csv")})

    assert resp.status_code == 200
    assert "Added 1 new trades" in resp.json()["message"]

    app.dependency_overrides.clear()


def test_import_deduplication(tmp_path):
    """A CSV with 1 duplicate and 1 new trade should add exactly 1."""
    from datetime import datetime
    from unittest.mock import MagicMock

    # Build an existing trade doc that matches the duplicate row
    existing = MagicMock()
    existing.id = "existing-trade"
    existing.to_dict.return_value = {
        "date": datetime(2024, 1, 1),
        "ticker": "AAPL",
        "side": "Buy",
        "price": 150.0,
        "quantity": 10.0,
        "type": "Equity",
        "currency": "USD",
        "fees": 0.0,
        "is_wash_sale": False,
        "expiration_date": None,
        "strike_price": None,
        "option_type": None,
    }

    db = make_import_db(existing_docs=[existing])
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    csv_file = tmp_path / "trades2.csv"
    create_temp_csv(str(csv_file), [
        {"Date": "2024-01-01", "Ticker": "AAPL", "Price": "150.0", "Quantity": "10"},  # duplicate
        {"Date": "2024-02-01", "Ticker": "MSFT", "Price": "300.0", "Quantity": "5"},   # new
    ])

    with open(csv_file, "rb") as f:
        resp = client.post("/import", files={"file": ("trades2.csv", f, "text/csv")})

    assert resp.status_code == 200
    assert "Added 1 new trades" in resp.json()["message"]

    app.dependency_overrides.clear()
