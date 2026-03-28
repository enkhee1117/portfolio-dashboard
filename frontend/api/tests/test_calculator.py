"""
Tests for portfolio calculator: quantity, avg price, market value,
unrealized P&L, realized P&L, theme attachment, and edge cases.

All tests run offline with mocked Firestore.
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime
from app import calculator, schemas


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_trade_doc(doc_id, ticker, side, price, quantity, date=None):
    """Create a mock Firestore document snapshot for a trade."""
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = {
        "date": date or datetime(2025, 1, 1),
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
    }
    return doc


def make_asset_doc(ticker, price, primary_theme=None, secondary_theme=None):
    """Create a mock Firestore document snapshot for asset_prices."""
    doc = MagicMock()
    doc.id = ticker
    doc.to_dict.return_value = {
        "ticker": ticker,
        "price": price,
        "primary_theme": primary_theme,
        "secondary_theme": secondary_theme,
    }
    return doc


def make_db(trade_docs=None, asset_docs=None):
    """Build a mock Firestore client with trade and asset data."""
    db = MagicMock()
    trade_docs = trade_docs or []
    asset_docs = asset_docs or []

    trades_col = MagicMock()
    trades_col.stream.return_value = trade_docs

    prices_col = MagicMock()
    prices_col.stream.return_value = asset_docs

    def _collection(name):
        if name == "trades":
            return trades_col
        if name == "asset_prices":
            return prices_col
        return MagicMock()

    db.collection.side_effect = _collection
    return db


def find_ticker(results, ticker):
    """Find a specific ticker in calculator results."""
    matches = [r for r in results if r["ticker"] == ticker]
    return matches[0] if matches else None


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_firebase(monkeypatch):
    monkeypatch.setattr("firebase_admin._apps", {"default": True})


# ── Basic Quantity Tests ─────────────────────────────────────────────────────

class TestQuantity:
    def test_single_buy(self):
        """A single buy should show correct quantity."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 150.0, 10)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos is not None
        assert pos["quantity"] == 10.0

    def test_multiple_buys(self):
        """Multiple buys should accumulate quantity."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 150.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Buy", 160.0, 5, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["quantity"] == 15.0

    def test_buy_then_sell(self):
        """Buy then partial sell should reduce quantity."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 150.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 160.0, 3, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["quantity"] == 7.0

    def test_full_sell_zeroes_quantity(self):
        """Selling all shares should result in quantity 0."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 150.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 160.0, 10, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # Position exists (has realized P&L) but quantity is 0
        assert pos is not None
        assert pos["quantity"] == 0.0

    def test_negative_quantity_from_oversell(self):
        """Selling more than owned creates negative quantity (short)."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 150.0, 5, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 160.0, 10, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["quantity"] == -5.0


# ── Average Price Tests ──────────────────────────────────────────────────────

class TestAveragePrice:
    def test_single_buy_avg_price(self):
        """Single buy: avg price = buy price."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 150.0, 10),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["average_price"] == 150.0

    def test_weighted_average_two_buys(self):
        """Two buys at different prices should give weighted average."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Buy", 200.0, 10, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (10*100 + 10*200) / 20 = 150
        assert pos["average_price"] == 150.0

    def test_weighted_average_unequal_lots(self):
        """Weighted average with different lot sizes."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 30, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Buy", 200.0, 10, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (30*100 + 10*200) / 40 = 125
        assert pos["average_price"] == 125.0

    def test_sell_does_not_change_avg_price(self):
        """Selling shares should not alter average cost basis."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 20, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 120.0, 5, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["average_price"] == 100.0
        assert pos["quantity"] == 15.0

    def test_cost_basis_resets_on_full_close(self):
        """When position is fully sold and rebought, avg price should be the new buy price."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 120.0, 10, datetime(2025, 1, 2)),
            make_trade_doc("t3", "AAPL", "Buy", 200.0, 5, datetime(2025, 1, 3)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["quantity"] == 5.0
        assert pos["average_price"] == 200.0  # NOT contaminated by old 100.0

    def test_sgov_scenario(self):
        """
        Real-world SGOV bug: multiple buy/sell/buy cycles.
        The avg price must reflect only the cost of shares currently held.
        """
        db = make_db(trade_docs=[
            make_trade_doc("t1", "SGOV", "Buy",   100.39, 8,    datetime(2024, 10, 7)),
            make_trade_doc("t2", "SGOV", "Sell",  100.43, 8,    datetime(2024, 10, 10)),
            make_trade_doc("t3", "SGOV", "Buy",   100.48, 8,    datetime(2024, 10, 11)),
            make_trade_doc("t4", "SGOV", "Sell",   95.50, 8,    datetime(2024, 10, 17)),
            make_trade_doc("t5", "SGOV", "Buy",   100.68, 80,   datetime(2024, 10, 29)),
            make_trade_doc("t6", "SGOV", "Sell",  100.38, 10,   datetime(2024, 11, 6)),
            make_trade_doc("t7", "SGOV", "Sell",  100.39, 5,    datetime(2024, 11, 7)),
            make_trade_doc("t8", "SGOV", "Sell",  100.43, 15,   datetime(2024, 11, 8)),
            make_trade_doc("t9", "SGOV", "Sell",  100.43, 20,   datetime(2024, 11, 11)),
            make_trade_doc("t10", "SGOV", "Sell", 100.43, 10,   datetime(2024, 11, 11)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "SGOV")
        assert pos["quantity"] == 20.0
        assert pos["average_price"] == 100.68


# ── Market Value Tests ───────────────────────────────────────────────────────

class TestMarketValue:
    def test_market_value_with_current_price(self):
        """Market value = quantity * current price from asset_prices."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 150.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 200.0)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["market_value"] == 2000.0  # 10 * 200

    def test_market_value_zero_without_price_data(self):
        """If no asset_prices entry exists, current_price=0 so market_value=0."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 150.0, 10)],
            asset_docs=[],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["current_price"] == 0.0
        assert pos["market_value"] == 0.0

    def test_market_value_after_partial_sell(self):
        """Market value uses remaining quantity."""
        db = make_db(
            trade_docs=[
                make_trade_doc("t1", "AAPL", "Buy", 150.0, 10, datetime(2025, 1, 1)),
                make_trade_doc("t2", "AAPL", "Sell", 160.0, 4, datetime(2025, 1, 2)),
            ],
            asset_docs=[make_asset_doc("AAPL", 170.0)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["quantity"] == 6.0
        assert pos["market_value"] == 1020.0  # 6 * 170


# ── Unrealized P&L Tests ─────────────────────────────────────────────────────

class TestUnrealizedPnL:
    def test_unrealized_gain(self):
        """Price went up: unrealized P&L is positive."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 120.0)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (120 - 100) * 10 = 200
        assert pos["unrealized_pnl"] == 200.0

    def test_unrealized_loss(self):
        """Price went down: unrealized P&L is negative."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 100.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 80.0)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (80 - 100) * 10 = -200
        assert pos["unrealized_pnl"] == -200.0

    def test_unrealized_zero_when_fully_closed(self):
        """No unrealized P&L when position is fully closed."""
        db = make_db(
            trade_docs=[
                make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
                make_trade_doc("t2", "AAPL", "Sell", 120.0, 10, datetime(2025, 1, 2)),
            ],
            asset_docs=[make_asset_doc("AAPL", 150.0)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["unrealized_pnl"] == 0.0


# ── Realized P&L Tests ───────────────────────────────────────────────────────

class TestRealizedPnL:
    def test_realized_gain(self):
        """Sell above avg cost: positive realized P&L."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 120.0, 10, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (120 - 100) * 10 = 200
        assert pos["realized_pnl"] == 200.0

    def test_realized_loss(self):
        """Sell below avg cost: negative realized P&L."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 80.0, 10, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (80 - 100) * 10 = -200
        assert pos["realized_pnl"] == -200.0

    def test_partial_sell_realized(self):
        """Partial sell should realize P&L only on sold shares."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 150.0, 3, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (150 - 100) * 3 = 150
        assert pos["realized_pnl"] == 150.0

    def test_multiple_sells_accumulate(self):
        """Multiple sells accumulate realized P&L."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 20, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 120.0, 5, datetime(2025, 1, 2)),
            make_trade_doc("t3", "AAPL", "Sell", 110.0, 5, datetime(2025, 1, 3)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # (120-100)*5 + (110-100)*5 = 100 + 50 = 150
        assert pos["realized_pnl"] == 150.0

    def test_buy_sell_buy_sell_realized(self):
        """Close a position, reopen, and close again — both realized amounts counted."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "AAPL", "Sell", 120.0, 10, datetime(2025, 1, 2)),
            make_trade_doc("t3", "AAPL", "Buy", 130.0, 10, datetime(2025, 1, 3)),
            make_trade_doc("t4", "AAPL", "Sell", 150.0, 10, datetime(2025, 1, 4)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        # First round: (120-100)*10 = 200
        # Second round: (150-130)*10 = 200
        # Total = 400
        assert pos["realized_pnl"] == 400.0


# ── Theme Attachment Tests ───────────────────────────────────────────────────

class TestThemes:
    def test_themes_attached_from_asset_prices(self):
        """Themes from asset_prices collection are attached to positions."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 150.0, 10)],
            asset_docs=[make_asset_doc("AAPL", 200.0, "AI", "Technology")],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["primary_theme"] == "AI"
        assert pos["secondary_theme"] == "Technology"

    def test_no_themes_when_asset_not_registered(self):
        """If ticker has no asset_prices entry, themes are None."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 150.0, 10)],
            asset_docs=[],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["primary_theme"] is None
        assert pos["secondary_theme"] is None


# ── Chronological Ordering Tests ─────────────────────────────────────────────

class TestOrdering:
    def test_trades_processed_chronologically(self):
        """
        Trades inserted in wrong order should still produce correct results.
        This was the SGOV bug: Firestore returns docs in arbitrary order.
        """
        # Insert sell BEFORE buy (wrong order) — calculator must sort by date
        db = make_db(trade_docs=[
            make_trade_doc("t2", "AAPL", "Sell", 160.0, 5, datetime(2025, 1, 10)),
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
        ])
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["quantity"] == 5.0
        assert pos["average_price"] == 100.0
        # (160 - 100) * 5 = 300
        assert pos["realized_pnl"] == 300.0


# ── Multi-Ticker Tests ───────────────────────────────────────────────────────

class TestMultiTicker:
    def test_independent_tickers(self):
        """Different tickers are tracked independently."""
        db = make_db(
            trade_docs=[
                make_trade_doc("t1", "AAPL", "Buy", 150.0, 10, datetime(2025, 1, 1)),
                make_trade_doc("t2", "GOOG", "Buy", 200.0, 5, datetime(2025, 1, 1)),
            ],
            asset_docs=[
                make_asset_doc("AAPL", 160.0, "AI", "Technology"),
                make_asset_doc("GOOG", 210.0, "AI", "Technology"),
            ],
        )
        results = calculator.calculate_portfolio(db)

        aapl = find_ticker(results, "AAPL")
        assert aapl["quantity"] == 10.0
        assert aapl["average_price"] == 150.0
        assert aapl["market_value"] == 1600.0
        assert aapl["unrealized_pnl"] == 100.0

        goog = find_ticker(results, "GOOG")
        assert goog["quantity"] == 5.0
        assert goog["average_price"] == 200.0
        assert goog["market_value"] == 1050.0
        assert goog["unrealized_pnl"] == 50.0

    def test_sell_one_ticker_doesnt_affect_another(self):
        """Selling AAPL shouldn't change GOOG position."""
        db = make_db(trade_docs=[
            make_trade_doc("t1", "AAPL", "Buy", 100.0, 10, datetime(2025, 1, 1)),
            make_trade_doc("t2", "GOOG", "Buy", 200.0, 5, datetime(2025, 1, 1)),
            make_trade_doc("t3", "AAPL", "Sell", 120.0, 10, datetime(2025, 1, 2)),
        ])
        results = calculator.calculate_portfolio(db)

        goog = find_ticker(results, "GOOG")
        assert goog["quantity"] == 5.0
        assert goog["average_price"] == 200.0


# ── Edge Cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_portfolio(self):
        """No trades should return empty results."""
        db = make_db()
        results = calculator.calculate_portfolio(db)
        assert results == []

    def test_fractional_shares(self):
        """Should handle fractional quantities correctly."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "AAPL", "Buy", 150.0, 0.5)],
            asset_docs=[make_asset_doc("AAPL", 160.0)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "AAPL")
        assert pos["quantity"] == 0.5
        assert pos["market_value"] == 80.0  # 0.5 * 160

    def test_very_small_price(self):
        """Penny stocks should calculate correctly."""
        db = make_db(
            trade_docs=[make_trade_doc("t1", "PENNY", "Buy", 0.05, 10000)],
            asset_docs=[make_asset_doc("PENNY", 0.10)],
        )
        results = calculator.calculate_portfolio(db)
        pos = find_ticker(results, "PENNY")
        assert pos["quantity"] == 10000
        assert pos["average_price"] == 0.05
        assert pos["market_value"] == 1000.0  # 10000 * 0.10
        assert pos["unrealized_pnl"] == 500.0  # (0.10 - 0.05) * 10000
