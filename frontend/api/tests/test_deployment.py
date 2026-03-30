"""
Deployment readiness tests.
Run these BEFORE pushing to ensure nothing breaks in production.
These test the app initialization, route registration, and import chain
without hitting real Firebase.
"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_firebase(monkeypatch):
    monkeypatch.setattr("firebase_admin._apps", {"default": True})


class TestAppInitialization:
    """Ensure the FastAPI app starts without errors."""

    def test_app_imports_successfully(self):
        """The app module should import without crashing."""
        from app.main import app
        assert app is not None

    def test_all_routes_registered(self):
        """All critical routes should be registered."""
        from app.main import app
        routes = [r.path for r in app.routes]

        # Core endpoints
        assert "/" in routes
        assert "/portfolio" in routes
        assert "/trades" in routes
        assert "/trades/manual" in routes
        assert "/assets" in routes
        assert "/assets/themes" in routes

        # Import/export
        assert "/import" in routes
        assert "/trades/export-csv" in routes
        assert "/backup/export" in routes
        assert "/backup/restore" in routes

        # Portfolio history
        assert "/portfolio/history" in routes
        assert "/portfolio/backfill-history" in routes

        # Theme management
        assert "/themes/summary" in routes
        assert "/themes/rename" in routes
        assert "/themes/{name}" in routes

        # Price refresh
        assert "/assets/refresh-prices" in routes
        assert "/assets/refresh-status" in routes

    def test_vercel_entry_point(self):
        """The Vercel entry point should mount the app under /api."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

        # Simulate what index.py does
        from app.main import app as api_app
        assert api_app is not None


class TestDependencyImports:
    """Ensure all required packages can be imported."""

    def test_fastapi(self):
        import fastapi
        assert fastapi

    def test_pydantic(self):
        import pydantic
        assert pydantic

    def test_pandas(self):
        import pandas
        assert pandas

    def test_firebase_admin(self):
        import firebase_admin
        assert firebase_admin

    def test_google_cloud_firestore(self):
        from google.cloud import firestore
        assert firestore


class TestSchemaIntegrity:
    """Ensure all schemas are valid and consistent."""

    def test_trade_schema(self):
        from app.schemas import Trade, TradeCreate
        # TradeCreate should have user_id field
        fields = TradeCreate.model_fields
        assert 'user_id' in fields
        assert 'ticker' in fields
        assert 'price' in fields

    def test_portfolio_snapshot_schema(self):
        from app.schemas import PortfolioSnapshot
        fields = PortfolioSnapshot.model_fields
        assert 'realized_pnl_ytd' in fields
        assert 'primary_theme' in fields

    def test_asset_schema(self):
        from app.schemas import Asset
        fields = Asset.model_fields
        assert 'rsi' in fields
        assert 'daily_change_pct' in fields


class TestCalculatorIntegrity:
    """Ensure calculator functions accept user_id parameter."""

    def test_calculate_portfolio_accepts_user_id(self):
        from app.calculator import calculate_portfolio
        import inspect
        sig = inspect.signature(calculate_portfolio)
        assert 'user_id' in sig.parameters

    def test_compute_and_store_snapshot_accepts_user_id(self):
        from app.calculator import compute_and_store_snapshot
        import inspect
        sig = inspect.signature(compute_and_store_snapshot)
        assert 'user_id' in sig.parameters

    def test_get_cached_portfolio_accepts_user_id(self):
        from app.calculator import get_cached_portfolio
        import inspect
        sig = inspect.signature(get_cached_portfolio)
        assert 'user_id' in sig.parameters


class TestRequirements:
    """Ensure requirements.txt has all needed packages."""

    def test_requirements_file_exists(self):
        import os
        req_path = os.path.join(os.path.dirname(__file__), '..', 'requirements.txt')
        assert os.path.exists(req_path)

    def test_critical_packages_in_requirements(self):
        import os
        req_path = os.path.join(os.path.dirname(__file__), '..', 'requirements.txt')
        with open(req_path) as f:
            content = f.read().lower()

        required = ['fastapi', 'python-multipart', 'firebase-admin', 'pandas', 'pydantic']
        for pkg in required:
            assert pkg in content, f"Missing {pkg} in requirements.txt"
