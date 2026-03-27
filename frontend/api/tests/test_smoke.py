"""
Live smoke test — verifies the deployed Vercel API is reachable.
Run manually or in a scheduled CI job (NOT on every PR).

Usage:
    VERCEL_URL=https://portfolio-dashboard.vercel.app pytest tests/test_smoke.py -v
"""
import os
import pytest
import requests

VERCEL_URL = os.environ.get("VERCEL_URL", "").rstrip("/")


@pytest.mark.skipif(not VERCEL_URL, reason="VERCEL_URL not set — skipping smoke tests")
class TestSmokeAPI:

    def test_api_root_accessible(self):
        """GET / should return 200 and the API welcome message."""
        resp = requests.get(f"{VERCEL_URL}/api/", timeout=15)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        body = resp.json()
        assert "message" in body

    def test_trades_endpoint_accessible(self):
        """GET /api/trades should return a list (may be empty)."""
        resp = requests.get(f"{VERCEL_URL}/api/trades", timeout=15)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_portfolio_endpoint_accessible(self):
        """GET /api/portfolio should return a list."""
        resp = requests.get(f"{VERCEL_URL}/api/portfolio", timeout=15)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
