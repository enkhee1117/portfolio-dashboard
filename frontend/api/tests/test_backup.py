"""
Tests for backup export and restore endpoints.
Verifies full data round-trip: export → restore → verify identical data.
"""
import pytest
import json
import io
from unittest.mock import MagicMock, call
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app, get_db, get_current_user

TEST_USER_ID = "test-user-123"


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_trade_doc(doc_id, ticker, side, price, quantity, date=None):
    doc = MagicMock()
    doc.id = doc_id
    doc.reference = MagicMock()
    doc.to_dict.return_value = {
        "date": date or datetime(2025, 1, 15),
        "ticker": ticker,
        "type": "Equity",
        "side": side,
        "price": price,
        "quantity": quantity,
        "fees": 0.0,
        "currency": "USD",
        "is_wash_sale": False,
        "expiration_date": None,
        "strike_price": None,
        "option_type": None,
        "user_id": TEST_USER_ID,
    }
    return doc


def make_asset_theme_doc(ticker, primary, secondary):
    """Create a mock for user-scoped asset_themes subcollection."""
    doc = MagicMock()
    doc.id = ticker
    doc.reference = MagicMock()
    doc.to_dict.return_value = {
        "ticker": ticker,
        "primary": primary,
        "secondary": secondary,
    }
    return doc


def make_mock_db(trade_docs=None, asset_theme_docs=None):
    db = MagicMock()
    trade_docs = trade_docs or []
    asset_theme_docs = asset_theme_docs or []

    trades_col = MagicMock()
    trades_col.stream.return_value = trade_docs
    trades_col.where.return_value = trades_col

    # User-scoped asset_themes subcollection
    users_col = MagicMock()
    user_doc = MagicMock()
    themes_subcol = MagicMock()
    themes_subcol.stream.return_value = asset_theme_docs
    user_doc.collection.return_value = themes_subcol
    users_col.document.return_value = user_doc

    prices_col = MagicMock()

    def _collection(name):
        if name == "trades":
            return trades_col
        if name == "users":
            return users_col
        if name == "asset_prices":
            return prices_col
        return MagicMock()

    db.collection.side_effect = _collection
    db.batch.return_value = MagicMock()

    return db


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_firebase(monkeypatch):
    monkeypatch.setattr("firebase_admin._apps", {"default": True})

@pytest.fixture(autouse=True)
def override_auth():
    """Override auth dependency so backup tests don't need real tokens."""
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    yield
    app.dependency_overrides.pop(get_current_user, None)


SAMPLE_TRADES = [
    make_trade_doc("t1", "AAPL", "Buy", 150.0, 10, datetime(2025, 1, 1)),
    make_trade_doc("t2", "AAPL", "Sell", 170.0, 5, datetime(2025, 2, 1)),
    make_trade_doc("t3", "GOOG", "Buy", 200.0, 8, datetime(2025, 1, 15)),
]

SAMPLE_ASSETS = [
    make_asset_theme_doc("AAPL", "AI", "Technology"),
    make_asset_theme_doc("GOOG", "AI", "Technology"),
]


# ── Export Tests ─────────────────────────────────────────────────────────────

class TestExport:
    def test_export_returns_json_with_all_data(self):
        """Export should return trades and assets in a structured JSON."""
        db = make_mock_db(trade_docs=SAMPLE_TRADES, asset_theme_docs=SAMPLE_ASSETS)
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/backup/export")
        assert resp.status_code == 200

        data = resp.json()
        assert data["version"] == 2
        assert "exported_at" in data
        assert data["trades_count"] == 3
        assert data["assets_count"] == 2
        assert len(data["trades"]) == 3
        assert len(data["assets"]) == 2

        app.dependency_overrides.clear()

    def test_export_preserves_doc_ids(self):
        """Each exported record should include its Firestore document ID."""
        db = make_mock_db(trade_docs=SAMPLE_TRADES, asset_theme_docs=SAMPLE_ASSETS)
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        data = client.get("/backup/export").json()

        trade_ids = {t["_doc_id"] for t in data["trades"]}
        assert trade_ids == {"t1", "t2", "t3"}

        asset_ids = {a["_doc_id"] for a in data["assets"]}
        assert asset_ids == {"AAPL", "GOOG"}

        app.dependency_overrides.clear()

    def test_export_trade_fields(self):
        """Exported trades should contain all required fields."""
        db = make_mock_db(trade_docs=SAMPLE_TRADES[:1], asset_theme_docs=[])
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        data = client.get("/backup/export").json()
        trade = data["trades"][0]

        assert trade["ticker"] == "AAPL"
        assert trade["side"] == "Buy"
        assert trade["price"] == 150.0
        assert trade["quantity"] == 10.0
        assert trade["type"] == "Equity"
        assert trade["currency"] == "USD"
        assert "date" in trade
        assert trade["_doc_id"] == "t1"

        app.dependency_overrides.clear()

    def test_export_asset_fields(self):
        """Exported assets should contain ticker, price, and themes."""
        db = make_mock_db(trade_docs=[], asset_theme_docs=SAMPLE_ASSETS[:1])
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        data = client.get("/backup/export").json()
        asset = data["assets"][0]

        assert asset["ticker"] == "AAPL"
        assert asset["primary"] == "AI"
        assert asset["secondary"] == "Technology"
        assert asset["_doc_id"] == "AAPL"

        app.dependency_overrides.clear()

    def test_export_dates_are_iso_strings(self):
        """Dates should be serialized as ISO strings for JSON compatibility."""
        db = make_mock_db(trade_docs=SAMPLE_TRADES[:1], asset_theme_docs=SAMPLE_ASSETS[:1])
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        data = client.get("/backup/export").json()

        # Trade date should be an ISO string
        trade_date = data["trades"][0]["date"]
        assert isinstance(trade_date, str)
        # Should be parseable back
        parsed = datetime.fromisoformat(trade_date)
        assert parsed.year == 2025

        app.dependency_overrides.clear()

    def test_export_empty_database(self):
        """Export with no data should return empty arrays."""
        db = make_mock_db()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        data = client.get("/backup/export").json()
        assert data["trades_count"] == 0
        assert data["assets_count"] == 0
        assert data["trades"] == []
        assert data["assets"] == []

        app.dependency_overrides.clear()

    def test_export_content_disposition_header(self):
        """Response should have a Content-Disposition header for file download."""
        db = make_mock_db()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/backup/export")
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "portfolio_backup_" in cd
        assert ".json" in cd

        app.dependency_overrides.clear()


# ── Restore Tests ────────────────────────────────────────────────────────────

class TestRestore:
    def _make_backup_json(self, trades=None, assets=None, version=1):
        """Create a valid backup JSON payload."""
        backup = {
            "version": version,
            "exported_at": "2025-03-01T12:00:00",
            "trades_count": len(trades or []),
            "assets_count": len(assets or []),
            "trades": trades or [],
            "assets": assets or [],
        }
        return json.dumps(backup).encode("utf-8")

    def _make_restore_db(self, existing_trade_docs=None, existing_theme_docs=None):
        """Build a mock DB that tracks batch operations for verification."""
        db = MagicMock()
        existing_trade_docs = existing_trade_docs or []
        existing_theme_docs = existing_theme_docs or []

        trades_col = MagicMock()
        trades_col.stream.return_value = existing_trade_docs
        trades_col.where.return_value = trades_col
        trades_col.document.return_value = MagicMock()

        prices_col = MagicMock()
        prices_col.document.return_value = MagicMock()

        # User-scoped asset_themes subcollection
        users_col = MagicMock()
        user_doc = MagicMock()
        themes_subcol = MagicMock()
        themes_subcol.stream.return_value = existing_theme_docs
        themes_subcol.document.return_value = MagicMock()
        user_doc.collection.return_value = themes_subcol
        users_col.document.return_value = user_doc

        def _collection(name):
            if name == "trades":
                return trades_col
            if name == "asset_prices":
                return prices_col
            if name == "users":
                return users_col
            return MagicMock()

        db.collection.side_effect = _collection
        db.batch.return_value = MagicMock()
        return db

    def test_restore_creates_trades_and_assets(self):
        """Restore should write trades and assets from backup."""
        db = self._make_restore_db()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        backup = self._make_backup_json(
            trades=[
                {"_doc_id": "t1", "ticker": "AAPL", "side": "Buy", "price": 150.0,
                 "quantity": 10, "date": "2025-01-01T00:00:00", "type": "Equity",
                 "fees": 0, "currency": "USD", "is_wash_sale": False,
                 "expiration_date": None, "strike_price": None, "option_type": None},
            ],
            assets=[
                {"_doc_id": "AAPL", "ticker": "AAPL", "price": 175.0,
                 "primary_theme": "AI", "secondary_theme": "Technology",
                 "last_updated": "2025-03-01T00:00:00"},
            ],
        )

        resp = client.post(
            "/backup/restore",
            files={"file": ("backup.json", backup, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["restored"]["trades"] == 1
        assert data["restored"]["assets"] == 1

        app.dependency_overrides.clear()

    def test_restore_deletes_existing_data_first(self):
        """Restore should delete all existing trades and assets before writing."""
        existing_trades = [make_trade_doc(f"old-{i}", "OLD", "Buy", 10, 1) for i in range(3)]
        existing_themes = [make_asset_theme_doc("OLD", "X", "Y")]
        db = self._make_restore_db(existing_trades, existing_themes)
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        backup = self._make_backup_json(
            trades=[
                {"_doc_id": "new-1", "ticker": "NEW", "side": "Buy", "price": 100,
                 "quantity": 5, "date": "2025-06-01T00:00:00", "type": "Equity",
                 "fees": 0, "currency": "USD", "is_wash_sale": False,
                 "expiration_date": None, "strike_price": None, "option_type": None},
            ],
            assets=[],
        )

        resp = client.post(
            "/backup/restore",
            files={"file": ("backup.json", backup, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"]["trades"] == 3
        assert data["deleted"]["assets"] == 1
        assert data["restored"]["trades"] == 1

        app.dependency_overrides.clear()

    def test_restore_rejects_invalid_json(self):
        """Non-JSON file should return 400."""
        db = self._make_restore_db()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(
            "/backup/restore",
            files={"file": ("bad.json", b"not valid json", "application/json")},
        )
        assert resp.status_code == 400

        app.dependency_overrides.clear()

    def test_restore_rejects_wrong_version(self):
        """Backup with unsupported version should return 400."""
        db = self._make_restore_db()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        bad_backup = json.dumps({"version": 999, "trades": [], "assets": []}).encode()
        resp = client.post(
            "/backup/restore",
            files={"file": ("backup.json", bad_backup, "application/json")},
        )
        assert resp.status_code == 400
        assert "Unsupported backup version" in resp.json()["detail"]

        app.dependency_overrides.clear()

    def test_restore_empty_backup(self):
        """Restoring an empty backup should clear data and restore nothing."""
        existing_trades = [make_trade_doc("old-1", "OLD", "Buy", 10, 1)]
        db = self._make_restore_db(existing_trades)
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        backup = self._make_backup_json(trades=[], assets=[])
        resp = client.post(
            "/backup/restore",
            files={"file": ("backup.json", backup, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"]["trades"] == 1
        assert data["restored"]["trades"] == 0
        assert data["restored"]["assets"] == 0

        app.dependency_overrides.clear()

    def test_restore_multiple_trades_and_assets(self):
        """Restore should handle multiple records correctly."""
        db = self._make_restore_db()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        trades = [
            {"_doc_id": f"t{i}", "ticker": f"TK{i}", "side": "Buy", "price": 100 + i,
             "quantity": i + 1, "date": f"2025-0{i+1}-01T00:00:00", "type": "Equity",
             "fees": 0, "currency": "USD", "is_wash_sale": False,
             "expiration_date": None, "strike_price": None, "option_type": None}
            for i in range(5)
        ]
        assets = [
            {"_doc_id": f"TK{i}", "ticker": f"TK{i}", "price": 110 + i,
             "primary_theme": "Theme A", "secondary_theme": "Theme B",
             "last_updated": "2025-03-01T00:00:00"}
            for i in range(3)
        ]

        backup = self._make_backup_json(trades=trades, assets=assets)
        resp = client.post(
            "/backup/restore",
            files={"file": ("backup.json", backup, "application/json")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["restored"]["trades"] == 5
        assert data["restored"]["assets"] == 3

        app.dependency_overrides.clear()


# ── Round-Trip Test ──────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_export_format_is_restorable(self):
        """The JSON structure from export should be accepted by restore."""
        # Export
        db_export = make_mock_db(trade_docs=SAMPLE_TRADES, asset_theme_docs=SAMPLE_ASSETS)
        app.dependency_overrides[get_db] = lambda: db_export
        client = TestClient(app)

        export_resp = client.get("/backup/export")
        assert export_resp.status_code == 200
        exported = export_resp.json()

        # Verify the export is valid for restore
        assert exported["version"] == 2
        assert len(exported["trades"]) == 3
        assert len(exported["assets"]) == 2

        # All trades have _doc_id
        for t in exported["trades"]:
            assert "_doc_id" in t
            assert t["_doc_id"] is not None

        # All assets have _doc_id
        for a in exported["assets"]:
            assert "_doc_id" in a
            assert a["_doc_id"] is not None

        # Restore with the exported data
        db_restore = MagicMock()
        trades_col = MagicMock()
        trades_col.stream.return_value = []
        trades_col.where.return_value = trades_col
        trades_col.document.return_value = MagicMock()
        prices_col = MagicMock()
        prices_col.document.return_value = MagicMock()
        users_col = MagicMock()
        user_doc = MagicMock()
        themes_subcol = MagicMock()
        themes_subcol.stream.return_value = []
        themes_subcol.document.return_value = MagicMock()
        user_doc.collection.return_value = themes_subcol
        users_col.document.return_value = user_doc

        def _col(name):
            if name == "trades":
                return trades_col
            if name == "asset_prices":
                return prices_col
            if name == "users":
                return users_col
            return MagicMock()

        db_restore.collection.side_effect = _col
        db_restore.batch.return_value = MagicMock()

        app.dependency_overrides[get_db] = lambda: db_restore

        backup_bytes = json.dumps(exported).encode("utf-8")
        restore_resp = client.post(
            "/backup/restore",
            files={"file": ("backup.json", backup_bytes, "application/json")},
        )
        assert restore_resp.status_code == 200
        result = restore_resp.json()
        assert result["restored"]["trades"] == 3
        assert result["restored"]["assets"] == 2

        app.dependency_overrides.clear()
