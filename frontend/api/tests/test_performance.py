"""
Performance budget tests — ensure endpoints stay within Firestore operation limits.
These tests mock Firestore and count how many read/write operations each code path makes.
If an endpoint exceeds its budget, the test fails BEFORE it reaches production.

Add new budget tests here when adding endpoints or modifying data access patterns.
"""
import pytest
from unittest.mock import MagicMock, call, patch
from datetime import datetime
from app import calculator, schemas


# ── Firestore Operation Counter ──────────────────────────────────────────

class FirestoreCounter:
    """Wraps a mock Firestore client and counts read/write operations."""

    def __init__(self):
        self.reads = 0
        self.writes = 0
        self.streams = 0
        self._db = MagicMock()

    def document_get(self, *args, **kwargs):
        self.reads += 1
        doc = MagicMock()
        doc.exists = False
        doc.to_dict.return_value = None
        return doc

    def collection_stream(self, *args, **kwargs):
        self.streams += 1
        return iter([])

    def batch_set(self, *args, **kwargs):
        self.writes += 1

    def batch_update(self, *args, **kwargs):
        self.writes += 1

    def report(self) -> dict:
        return {
            "reads": self.reads,
            "writes": self.writes,
            "streams": self.streams,
            "total": self.reads + self.writes + self.streams,
        }


# ── Helpers ──────────────────────────────────────────────────────────────

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


def make_counted_db(trade_docs=None, asset_docs=None, snapshot_positions=None):
    """Build a mock Firestore that counts operations."""
    db = MagicMock()
    trade_docs = trade_docs or []
    asset_docs = asset_docs or {}  # ticker -> {price, primary_theme, secondary_theme}

    counter = {"reads": 0, "writes": 0, "streams": 0}

    # Trades collection
    trades_col = MagicMock()
    def trades_stream():
        counter["streams"] += 1
        return iter(trade_docs)
    trades_col.stream.side_effect = trades_stream
    trades_col.where.return_value = trades_col

    # Asset prices — per-document reads
    prices_col = MagicMock()
    def price_doc(ticker):
        doc = MagicMock()
        counter["reads"] += 1
        if ticker in asset_docs:
            doc.exists = True
            doc.to_dict.return_value = asset_docs[ticker]
        else:
            doc.exists = False
            doc.to_dict.return_value = None
        doc.get.return_value = doc
        return doc
    prices_col.document.side_effect = price_doc

    # Snapshot doc (shared between users subcollection and global)
    snap_doc = MagicMock()
    if snapshot_positions is not None:
        snap_doc.exists = True
        snap_doc.to_dict.return_value = {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "total_value": sum(p.get("market_value", 0) for p in snapshot_positions),
            "positions": snapshot_positions,
            "computed_at": datetime.utcnow(),
        }
    else:
        snap_doc.exists = False
        snap_doc.to_dict.return_value = {}

    def snap_doc_get(*a, **kw):
        counter["reads"] += 1
        return snap_doc
    snap_inner = MagicMock()
    snap_inner.get.side_effect = snap_doc_get
    snap_inner.set.side_effect = lambda *a, **kw: counter.__setitem__("writes", counter["writes"] + 1)

    # Users collection — routes to themes and snapshots subcollections
    users_col = MagicMock()
    user_doc = MagicMock()
    themes_subcol = MagicMock()
    def themes_stream():
        counter["streams"] += 1
        return iter([])
    themes_subcol.stream.side_effect = themes_stream
    themes_subcol.document.return_value = MagicMock()

    snapshots_subcol = MagicMock()
    snapshots_subcol.document.return_value = snap_inner

    def user_subcollection(name):
        if name == "asset_themes":
            return themes_subcol
        if name == "portfolio_snapshots":
            return snapshots_subcol
        return MagicMock()

    user_doc.collection.side_effect = user_subcollection
    users_col.document.return_value = user_doc

    # Global snapshot collection (for anonymous)
    snapshots_col = MagicMock()
    snapshots_col.document.return_value = snap_inner

    def _collection(name):
        if name == "trades": return trades_col
        if name == "asset_prices": return prices_col
        if name == "users": return users_col
        if name == "portfolio_snapshots": return snapshots_col
        return MagicMock()

    db.collection.side_effect = _collection
    db.get_all = MagicMock(return_value=[])
    db.batch.return_value = MagicMock()

    return db, counter


@pytest.fixture(autouse=True)
def mock_firebase(monkeypatch):
    monkeypatch.setattr("firebase_admin._apps", {"default": True})


# ── Budget Tests ─────────────────────────────────────────────────────────

class TestPortfolioBudget:
    """GET /portfolio should be cheap on cache hit."""

    def test_cache_hit_reads_1_document(self):
        """Cache hit should read exactly 1 snapshot document."""
        positions = [
            {"ticker": "AAPL", "quantity": 10, "average_price": 150,
             "current_price": 170, "market_value": 1700,
             "unrealized_pnl": 200, "realized_pnl": 0, "realized_pnl_ytd": 0}
        ]
        db, counter = make_counted_db(snapshot_positions=positions)

        result = calculator.get_cached_portfolio(db, user_id="test-user")

        assert counter["reads"] == 1  # Just the snapshot lookup
        assert counter["streams"] == 0  # No collection streams
        assert counter["writes"] == 0  # No writes on cache hit
        assert len(result) == 1

    def test_cache_miss_has_bounded_cost(self):
        """Cache miss recomputes, but should not exceed reasonable bounds."""
        trades = [
            make_trade_doc("t1", "AAPL", "Buy", 150, 10),
            make_trade_doc("t2", "GOOG", "Buy", 200, 5),
        ]
        db, counter = make_counted_db(
            trade_docs=trades,
            asset_docs={
                "AAPL": {"price": 170, "primary_theme": "AI", "secondary_theme": "Tech"},
                "GOOG": {"price": 210, "primary_theme": "AI", "secondary_theme": "Tech"},
            },
        )

        result = calculator.get_cached_portfolio(db, user_id="test-user")

        # Cache miss calls calculate_portfolio + compute_and_store_snapshot
        # Streams: trades (×2 for calculate + store) + asset_themes (×2)
        # Reads: snapshot check + prices per ticker (×2)
        # Budget: should stay proportional to ticker count, not trade count
        total_ops = counter["reads"] + counter["streams"] + counter["writes"]
        assert total_ops <= 20, f"Cache miss too expensive: {counter}"


class TestDeltaUpdateBudget:
    """Trade CRUD delta should be much cheaper than full recompute."""

    def test_delta_reads_under_15(self):
        """Delta update for a single ticker should read <15 docs total."""
        snapshot_positions = [
            {"ticker": "AAPL", "quantity": 10, "average_price": 150,
             "current_price": 170, "market_value": 1700,
             "unrealized_pnl": 200, "realized_pnl": 0, "realized_pnl_ytd": 0},
            {"ticker": "GOOG", "quantity": 5, "average_price": 200,
             "current_price": 210, "market_value": 1050,
             "unrealized_pnl": 50, "realized_pnl": 0, "realized_pnl_ytd": 0},
        ]
        trades = [
            make_trade_doc("t1", "AAPL", "Buy", 150, 10),
            make_trade_doc("t2", "AAPL", "Buy", 160, 5),  # New trade
        ]
        db, counter = make_counted_db(
            trade_docs=trades,
            asset_docs={"AAPL": {"price": 170, "primary_theme": "AI"}},
            snapshot_positions=snapshot_positions,
        )

        result = calculator.apply_trade_delta(db, "test-user", "AAPL")

        # Budget: snapshot read + ticker trades stream + price read + theme read + snapshot write
        assert counter["reads"] + counter["streams"] <= 15, \
            f"Delta update too expensive: {counter}"
        assert counter["writes"] <= 1  # Single snapshot write


class TestRecomputeTickerBudget:
    """Per-ticker recompute should only read that ticker's trades."""

    def test_only_reads_one_tickers_trades(self):
        """_recompute_ticker_position should not stream all trades."""
        trades = [
            make_trade_doc("t1", "AAPL", "Buy", 150, 10),
            make_trade_doc("t2", "AAPL", "Sell", 170, 5),
        ]
        db, counter = make_counted_db(
            trade_docs=trades,
            asset_docs={"AAPL": {"price": 175, "primary_theme": "AI"}},
        )

        result = calculator._recompute_ticker_position(db, "test-user", "AAPL")

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert result["quantity"] == 5.0
        # Should stream trades once (filtered by ticker) + read price + read theme
        assert counter["streams"] <= 2  # trades + theme
        assert counter["reads"] <= 3    # price doc + theme doc + buffer
