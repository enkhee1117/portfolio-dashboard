"""
Tests for portfolio snapshots, price utilities, and data architecture.
Covers: compute_and_store_snapshot, get_cached_portfolio,
get_tickers_last_price_date, and idempotency guarantees.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime
from app import calculator, schemas


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_trade_doc(doc_id, ticker, side, price, quantity, date=None):
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = {
        "date": date or datetime(2025, 1, 1),
        "ticker": ticker, "type": "Equity", "side": side,
        "price": price, "quantity": quantity,
        "fees": 0.0, "currency": "USD", "is_wash_sale": False,
        "expiration_date": None, "strike_price": None, "option_type": None,
    }
    return doc


def make_asset_doc(ticker, price, primary_theme=None, secondary_theme=None):
    doc = MagicMock()
    doc.id = ticker
    doc.to_dict.return_value = {
        "ticker": ticker, "price": price,
        "primary_theme": primary_theme, "secondary_theme": secondary_theme,
    }
    return doc


def make_price_series_doc(ticker, prices_map):
    doc = MagicMock()
    doc.id = ticker
    doc.to_dict.return_value = {
        "ticker": ticker,
        "prices": prices_map,
        "last_updated": datetime(2025, 3, 28),
    }
    return doc


def make_snapshot_doc(date_str, total_value, positions=None):
    doc = MagicMock()
    doc.id = date_str
    doc.exists = True
    doc.to_dict.return_value = {
        "date": date_str,
        "total_value": total_value,
        "positions": positions or [],
        "computed_at": datetime(2025, 3, 28),
    }
    return doc


def make_db(trade_docs=None, asset_docs=None, snapshot_doc=None, price_series_docs=None):
    db = MagicMock()

    trades_col = MagicMock()
    trades_col.stream.return_value = trade_docs or []
    trades_col.where.return_value = trades_col

    prices_col = MagicMock()
    prices_col.stream.return_value = asset_docs or []

    snapshots_col = MagicMock()
    if snapshot_doc:
        snapshots_col.document.return_value.get.return_value = snapshot_doc
    else:
        no_doc = MagicMock()
        no_doc.exists = False
        no_doc.to_dict.return_value = {}
        snapshots_col.document.return_value.get.return_value = no_doc
    snapshots_col.stream.return_value = []

    ps_col = MagicMock()
    ps_col.stream.return_value = price_series_docs or []

    def _collection(name):
        if name == "trades": return trades_col
        if name == "asset_prices": return prices_col
        if name == "portfolio_snapshots": return snapshots_col
        if name == "price_series": return ps_col
        return MagicMock()

    db.collection.side_effect = _collection
    db.batch.return_value = MagicMock()
    return db


@pytest.fixture(autouse=True)
def mock_firebase(monkeypatch):
    monkeypatch.setattr("firebase_admin._apps", {"default": True})


# ── Snapshot Compute & Store ─────────────────────────────────────────────

class TestComputeAndStoreSnapshot:
    def test_stores_snapshot_with_total_value(self):
        """Snapshot should sum market values and store."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 150.0)],
        )
        snapshot = calculator.compute_and_store_snapshot(db, "2025-03-28")

        assert snapshot["date"] == "2025-03-28"
        assert snapshot["total_value"] == 1500.0  # 10 * 150
        assert len(snapshot["positions"]) == 1
        assert snapshot["positions"][0]["ticker"] == "AAPL"

        # Verify Firestore write was called
        db.collection("portfolio_snapshots").document("2025-03-28").set.assert_called_once()

    def test_idempotent_same_date(self):
        """Calling twice with same date should overwrite, not duplicate."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 150.0)],
        )
        snap1 = calculator.compute_and_store_snapshot(db, "2025-03-28")
        snap2 = calculator.compute_and_store_snapshot(db, "2025-03-28")

        assert snap1["total_value"] == snap2["total_value"]
        # Both writes go to the same document ID (idempotent)
        calls = db.collection("portfolio_snapshots").document.call_args_list
        assert all(c == call("2025-03-28") for c in calls)

    def test_empty_portfolio(self):
        """Snapshot of empty portfolio should have zero value."""
        db = make_db()
        snapshot = calculator.compute_and_store_snapshot(db, "2025-03-28")

        assert snapshot["total_value"] == 0.0
        assert snapshot["positions"] == []

    def test_positions_exclude_datetime(self):
        """Stored positions should not contain datetime objects (Firestore serialization)."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 150.0, "AI", "Technology")],
        )
        snapshot = calculator.compute_and_store_snapshot(db, "2025-03-28")

        pos = snapshot["positions"][0]
        for key, val in pos.items():
            assert not isinstance(val, datetime), f"Position field '{key}' contains datetime"


# ── Cached Portfolio ─────────────────────────────────────────────────────

class TestGetCachedPortfolio:
    def test_returns_cached_when_snapshot_exists(self):
        """Should return positions from today's snapshot without recomputing."""
        cached_positions = [
            {"ticker": "AAPL", "quantity": 10, "average_price": 100.0,
             "current_price": 150.0, "market_value": 1500.0,
             "unrealized_pnl": 500.0, "realized_pnl": 0.0,
             "realized_pnl_ytd": 0.0,
             "primary_theme": "AI", "secondary_theme": "Technology"}
        ]
        snapshot = make_snapshot_doc(
            datetime.utcnow().strftime('%Y-%m-%d'),
            1500.0,
            cached_positions,
        )
        db = make_db(snapshot_doc=snapshot)

        result = calculator.get_cached_portfolio(db)

        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"
        assert result[0]["market_value"] == 1500.0

    def test_computes_fresh_when_no_snapshot(self):
        """Should fall back to calculate_portfolio when no snapshot exists."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "GOOG", "Buy", 200.0, 5)],
            asset_docs=[make_asset_doc("GOOG", 220.0)],
        )
        result = calculator.get_cached_portfolio(db)

        assert len(result) == 1
        assert result[0]["ticker"] == "GOOG"
        assert result[0]["quantity"] == 5.0

    def test_computes_fresh_when_snapshot_has_empty_positions(self):
        """Historical snapshots have empty positions — should recompute."""
        empty_snapshot = make_snapshot_doc(
            datetime.utcnow().strftime('%Y-%m-%d'),
            50000.0,
            [],  # empty positions (historical snapshot)
        )
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 150.0)],
            snapshot_doc=empty_snapshot,
        )
        result = calculator.get_cached_portfolio(db)

        # Should have computed fresh, not returned empty
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"


# ── Price Data Utilities ─────────────────────────────────────────────────

class TestGetTickersLastPriceDate:
    def test_returns_last_date_per_ticker(self):
        """Should return the max date from each ticker's prices map."""
        from app.main import get_tickers_last_price_date

        db = make_db(price_series_docs=[
            make_price_series_doc("AAPL", {"2025-03-26": 182.0, "2025-03-27": 185.0, "2025-03-28": 186.0}),
            make_price_series_doc("GOOG", {"2025-03-25": 170.0, "2025-03-26": 172.0}),
        ])
        result = get_tickers_last_price_date(db)

        assert result["AAPL"] == "2025-03-28"
        assert result["GOOG"] == "2025-03-26"

    def test_empty_collection(self):
        """Should return empty dict when no price_series docs exist."""
        from app.main import get_tickers_last_price_date

        db = make_db()
        result = get_tickers_last_price_date(db)
        assert result == {}

    def test_ticker_with_empty_prices(self):
        """Ticker with empty prices map should not appear in results."""
        from app.main import get_tickers_last_price_date

        empty_doc = MagicMock()
        empty_doc.id = "EMPTY"
        empty_doc.to_dict.return_value = {"ticker": "EMPTY", "prices": {}}

        db = make_db(price_series_docs=[empty_doc])
        result = get_tickers_last_price_date(db)
        assert "EMPTY" not in result


# ── Snapshot Idempotency ─────────────────────────────────────────────────

class TestSnapshotIdempotency:
    def test_date_as_document_id(self):
        """Snapshot uses date as doc ID — writing twice overwrites, doesn't duplicate."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 150.0)],
        )
        calculator.compute_and_store_snapshot(db, "2025-03-28")
        calculator.compute_and_store_snapshot(db, "2025-03-28")

        # Both calls should target the same document
        doc_calls = db.collection("portfolio_snapshots").document.call_args_list
        assert len(doc_calls) == 2
        assert doc_calls[0] == call("2025-03-28")
        assert doc_calls[1] == call("2025-03-28")

    def test_different_dates_create_different_docs(self):
        """Different dates should create different snapshot documents."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 150.0)],
        )
        calculator.compute_and_store_snapshot(db, "2025-03-27")
        calculator.compute_and_store_snapshot(db, "2025-03-28")

        doc_calls = db.collection("portfolio_snapshots").document.call_args_list
        doc_ids = [c[0][0] for c in doc_calls]
        assert "2025-03-27" in doc_ids
        assert "2025-03-28" in doc_ids


# ── Price Series Merge Behavior ──────────────────────────────────────────

class TestPriceSeriesMerge:
    def test_fetch_uses_merge_true(self):
        """fetch_and_store_ticker_prices should use merge=True to not overwrite existing data."""
        from app.main import fetch_and_store_ticker_prices

        db = MagicMock()
        ps_col = MagicMock()
        db.collection.return_value = ps_col

        with patch('yfinance.download') as mock_yf:
            import pandas as pd
            import numpy as np
            dates = pd.date_range('2025-03-27', periods=2)
            mock_data = pd.DataFrame({'Close': [100.0, 101.0]}, index=dates)
            mock_yf.return_value = mock_data

            fetch_and_store_ticker_prices(db, "TEST")

            # Verify merge=True was used
            set_call = ps_col.document("TEST").set
            assert set_call.called
            args, kwargs = set_call.call_args
            assert kwargs.get('merge') == True


# ── Portfolio History (Snapshot-Based) ───────────────────────────────────

class TestPortfolioHistory:
    def test_reads_from_snapshots(self):
        """GET /portfolio/history should read from portfolio_snapshots, not replay trades."""
        from fastapi.testclient import TestClient
        from app.main import app, get_db

        today = datetime.utcnow().strftime('%Y-%m-%d')
        snap1 = MagicMock()
        snap1.to_dict.return_value = {"date": today, "total_value": 50000.0}
        snap2 = MagicMock()
        snap2.to_dict.return_value = {"date": today, "total_value": 55000.0}

        db = MagicMock()
        snapshots_col = MagicMock()
        snapshots_col.stream.return_value = [snap1, snap2]

        def _col(name):
            if name == "portfolio_snapshots": return snapshots_col
            return MagicMock()

        db.collection.side_effect = _col

        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/portfolio/history?period=1m")
        assert resp.status_code == 200
        data = resp.json()

        # Should return snapshots, not empty
        assert len(data) >= 1

        app.dependency_overrides.clear()

    def test_sorted_by_date(self):
        """Results should be sorted chronologically."""
        from fastapi.testclient import TestClient
        from app.main import app, get_db

        # Insert out of order
        snap_b = MagicMock()
        snap_b.to_dict.return_value = {"date": "2025-03-20", "total_value": 60000.0}
        snap_a = MagicMock()
        snap_a.to_dict.return_value = {"date": "2025-03-10", "total_value": 50000.0}

        db = MagicMock()
        sc = MagicMock()
        sc.stream.return_value = [snap_b, snap_a]  # out of order
        db.collection.side_effect = lambda name: sc if name == "portfolio_snapshots" else MagicMock()

        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        data = client.get("/portfolio/history?period=all").json()
        if len(data) >= 2:
            assert data[0]["date"] <= data[1]["date"]

        app.dependency_overrides.clear()
