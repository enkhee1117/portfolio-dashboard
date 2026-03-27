"""
Wash sale tests using schemas.Trade (no ORM, no database).
A mock Firestore db is passed in so no real Firebase calls happen.
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime
from app import schemas, wash_sales


def make_trade(id, date_str, ticker, side, price, quantity, trade_type="Equity", is_wash_sale=False):
    return schemas.Trade(
        id=id,
        date=datetime.strptime(date_str, "%Y-%m-%d"),
        ticker=ticker,
        type=trade_type,
        side=side,
        price=price,
        quantity=quantity,
        currency="USD",
        fees=0.0,
        is_wash_sale=is_wash_sale,
    )


@pytest.fixture
def mock_db():
    """Minimal Firestore mock — batch commits silently succeed."""
    db = MagicMock()
    batch = MagicMock()
    db.batch.return_value = batch
    db.collection.return_value.document.return_value = MagicMock()
    return db


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_simple_loss_no_wash_sale(mock_db):
    """Buy then Sell at loss, no replacement → not a wash sale."""
    trades = [
        make_trade("1", "2024-01-01", "AAPL", "Buy",  150.0, 10),
        make_trade("2", "2024-02-01", "AAPL", "Sell", 140.0, 10),  # -$100
    ]
    result = wash_sales.detect_wash_sales(trades, mock_db)
    assert result == {}
    assert not trades[1].is_wash_sale


def test_wash_sale_triggered(mock_db):
    """Sell at loss + replacement buy within 30 days → wash sale."""
    trades = [
        make_trade("1", "2024-01-01", "AAPL", "Buy",  150.0, 10),
        make_trade("2", "2024-02-01", "AAPL", "Sell", 140.0, 10),  # loss
        make_trade("3", "2024-02-15", "AAPL", "Buy",  145.0, 10),  # +14 days
    ]
    result = wash_sales.detect_wash_sales(trades, mock_db)
    assert result.get("2") is True
    assert trades[1].is_wash_sale


def test_profit_not_a_wash_sale(mock_db):
    """Sell at profit + replacement buy within 30 days → NOT a wash sale."""
    trades = [
        make_trade("1", "2024-01-01", "AAPL", "Buy",  150.0, 10),
        make_trade("2", "2024-02-01", "AAPL", "Sell", 160.0, 10),  # profit
        make_trade("3", "2024-02-15", "AAPL", "Buy",  165.0, 10),
    ]
    result = wash_sales.detect_wash_sales(trades, mock_db)
    assert result == {}
    assert not trades[1].is_wash_sale


def test_replacement_outside_30_days_no_wash_sale(mock_db):
    """Replacement buy > 30 days after sell → NOT a wash sale."""
    trades = [
        make_trade("1", "2024-01-01", "AAPL", "Buy",  150.0, 10),
        make_trade("2", "2024-02-01", "AAPL", "Sell", 140.0, 10),
        make_trade("3", "2024-03-05", "AAPL", "Buy",  145.0, 10),  # +33 days
    ]
    result = wash_sales.detect_wash_sales(trades, mock_db)
    assert result == {}
    assert not trades[1].is_wash_sale


def test_fifo_net_profit_no_wash_sale(mock_db):
    """
    FIFO across two lots: net P&L is positive even though one lot is a loss.
    Implementation aggregates at trade level → no wash sale flag.
    """
    trades = [
        make_trade("1", "2024-01-01", "TSLA", "Buy",  100.0, 10),
        make_trade("2", "2024-01-15", "TSLA", "Buy",  120.0, 10),
        make_trade("3", "2024-02-01", "TSLA", "Sell", 110.0, 15),  # net +$50
        make_trade("4", "2024-02-10", "TSLA", "Buy",  115.0,  5),
    ]
    result = wash_sales.detect_wash_sales(trades, mock_db)
    assert result == {}
    assert not trades[2].is_wash_sale


def test_multiple_tickers_isolated(mock_db):
    """Wash sale detection is per-ticker; GOOG loss should not affect AAPL."""
    trades = [
        make_trade("1", "2024-01-01", "AAPL", "Buy",  150.0, 10),
        make_trade("2", "2024-02-01", "AAPL", "Sell", 160.0, 10),  # AAPL profit
        make_trade("3", "2024-01-01", "GOOG", "Buy",  200.0, 5),
        make_trade("4", "2024-02-01", "GOOG", "Sell", 180.0, 5),   # GOOG loss
        make_trade("5", "2024-02-10", "GOOG", "Buy",  185.0, 5),   # GOOG replacement
    ]
    result = wash_sales.detect_wash_sales(trades, mock_db)
    # GOOG sell (id=4) should be flagged
    assert result.get("4") is True
    # AAPL sell (id=2) should NOT be flagged
    assert "2" not in result
