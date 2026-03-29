"""
Backend API tests using mocked Firebase Firestore.
No real Firebase credentials required — everything runs offline.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app, get_db
from app import schemas

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_trade(doc_id="trade-1", ticker="TEST", side="Buy", price=100.0,
               quantity=10.0, date=None, is_wash_sale=False):
    """Return a dict that Firestore would deliver via doc.to_dict()."""
    return {
        "date": date or datetime(2025, 1, 1),
        "ticker": ticker,
        "type": "Equity",
        "side": side,
        "price": price,
        "quantity": quantity,
        "fees": 0.0,
        "currency": "USD",
        "is_wash_sale": is_wash_sale,
        "expiration_date": None,
        "strike_price": None,
        "option_type": None,
    }

def make_doc(doc_id, data):
    """Fake Firestore document snapshot."""
    doc = MagicMock()
    doc.id = doc_id
    doc.exists = True
    doc.to_dict.return_value = data
    return doc

def make_mock_db(trades=None, asset_prices=None):
    """Build a Firestore mock that satisfies the app's query patterns."""
    db = MagicMock()
    trades = trades or []
    asset_prices = asset_prices or []

    # collection('trades').stream() → list of docs
    trades_col = MagicMock()
    trades_col.stream.return_value = trades
    trades_col.where.return_value = trades_col   # supports chained .where().stream()

    prices_col = MagicMock()
    prices_col.stream.return_value = asset_prices

    # portfolio_snapshots — return non-existing docs by default
    snapshots_col = MagicMock()
    no_doc = MagicMock()
    no_doc.exists = False
    no_doc.to_dict.return_value = {}
    snapshots_col.document.return_value.get.return_value = no_doc
    snapshots_col.stream.return_value = []

    def _collection(name):
        if name == "trades":
            return trades_col
        if name == "asset_prices":
            return prices_col
        if name == "portfolio_snapshots":
            return snapshots_col
        return MagicMock()

    db.collection.side_effect = _collection

    # .document(id).get() for read; .document().set() / .delete() for write
    def _doc_ref(doc_id=None):
        ref = MagicMock()
        ref.id = doc_id or "new-doc-id"
        # Return a valid doc by default
        ref.get.return_value = make_doc(doc_id or "new-doc-id", make_trade(doc_id or "new-doc-id"))
        return ref

    trades_col.document.side_effect = _doc_ref
    db.batch.return_value = MagicMock()

    return db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_firebase(monkeypatch):
    """Patch firebase_admin so no real credentials are needed."""
    monkeypatch.setattr("firebase_admin._apps", {"default": True})


@pytest.fixture
def empty_client():
    """TestClient with an empty Firestore (no trades, no prices)."""
    db = make_mock_db()
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_trade():
    """TestClient pre-seeded with one BUY trade."""
    trade_data = make_trade("trade-1", ticker="AAPL", side="Buy", price=150.0, quantity=10)
    docs = [make_doc("trade-1", trade_data)]
    db = make_mock_db(trades=docs)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app), db
    app.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_read_root(empty_client):
    resp = empty_client.get("/")
    assert resp.status_code == 200
    assert "Portfolio Tracker API" in resp.json()["message"]


def test_get_trades_empty(empty_client):
    resp = empty_client.get("/trades")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_trades_with_data(client_with_trade):
    client, _ = client_with_trade
    resp = client.get("/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "AAPL"
    assert data[0]["id"] == "trade-1"


def test_get_portfolio_empty(empty_client):
    resp = empty_client.get("/portfolio")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_portfolio_calculates_positions(client_with_trade):
    client, _ = client_with_trade
    resp = client.get("/portfolio")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "AAPL"
    assert data[0]["quantity"] == 10.0
    assert data[0]["average_price"] == 150.0


def test_create_manual_trade(empty_client: TestClient):
    new_trade = {
        "date": "2025-01-01T00:00:00",
        "ticker": "TSLA",
        "type": "Equity",
        "side": "Buy",
        "price": 200.0,
        "quantity": 5.0,
        "currency": "USD",
        "fees": 0.0,
        "is_wash_sale": False,
    }
    resp = empty_client.post("/trades/manual", json=new_trade)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "TSLA"
    assert data["id"] is not None


def test_duplicate_trade_rejected():
    """Second identical trade should return 409 unless force=true."""
    trade_data = make_trade("dup-1", ticker="DUP", price=50.0, quantity=100.0)
    dup_doc = make_doc("dup-1", trade_data)

    db = MagicMock()
    db.batch.return_value = MagicMock()
    trades_col = MagicMock()
    # chained .where(...).where(...).stream() — always return dup_doc
    trades_col.where.return_value = trades_col
    trades_col.stream.return_value = [dup_doc]
    trades_col.document.return_value = MagicMock(id="new-id")
    db.collection.return_value = trades_col

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    payload = {
        "date": "2025-01-01T00:00:00",
        "ticker": "DUP",
        "type": "Equity",
        "side": "Buy",
        "price": 50.0,
        "quantity": 100.0,
        "currency": "USD",
        "fees": 0.0,
        "is_wash_sale": False,
    }
    resp = client.post("/trades/manual", json=payload)
    # 409 because DUP trade already exists with same side/price/qty
    assert resp.status_code == 409

    # Forcing should succeed even with dupe
    resp_forced = client.post("/trades/manual?force=true", json=payload)
    assert resp_forced.status_code == 200

    app.dependency_overrides.clear()


def test_delete_trade():
    """DELETE /trades/{id} should return 200 and call .delete() on the document."""
    trade_data = make_trade("trade-del", ticker="AAPL")
    doc_snapshot = make_doc("trade-del", trade_data)

    doc_ref = MagicMock()
    doc_ref.id = "trade-del"
    doc_ref.get.return_value = doc_snapshot

    db = MagicMock()
    db.batch.return_value = MagicMock()
    trades_col = MagicMock()
    trades_col.document.return_value = doc_ref
    trades_col.where.return_value = trades_col
    trades_col.stream.return_value = []    # no remaining trades after delete
    db.collection.return_value = trades_col

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    resp = client.delete("/trades/trade-del")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Trade deleted successfully"
    doc_ref.delete.assert_called_once()

    app.dependency_overrides.clear()


def test_delete_nonexistent_trade(empty_client: TestClient):
    """
    Deleting trade that doesn't exist should return 404.
    """
    db = MagicMock()
    missing = MagicMock()
    missing.exists = False
    db.collection.return_value.document.return_value.get.return_value = missing

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    resp = client.delete("/trades/ghost-id")
    assert resp.status_code == 404

    app.dependency_overrides.clear()
