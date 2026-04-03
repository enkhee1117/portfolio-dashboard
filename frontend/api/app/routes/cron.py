"""Cron job endpoints — scheduled price refresh."""
from fastapi import APIRouter, HTTPException, Header, Depends
from typing import Optional
import os
import logging

from ..auth import get_current_user
from ..services.monitoring import log_error
from .. import calculator

logger = logging.getLogger("portfolio")

router = APIRouter(tags=["cron"])


@router.get("/cron/refresh-prices")
def cron_refresh_prices(authorization: Optional[str] = Header(None)):
    """Cron-triggered price refresh. Secured by CRON_SECRET env var."""
    from ..main import _run_price_refresh, compute_and_store_rsi, IS_SERVERLESS
    from ..deps import get_db

    cron_secret = os.environ.get("CRON_SECRET", "")
    if cron_secret:
        token = (authorization or "").replace("Bearer ", "")
        if token != cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron secret")
    elif IS_SERVERLESS:
        raise HTTPException(status_code=403, detail="CRON_SECRET not configured")

    db = get_db()
    result = {"updated": 0, "failed": []}
    errors = []

    try:
        result = _run_price_refresh()
    except Exception as e:
        errors.append(f"Price refresh failed: {e}")
        logger.error(f"Cron price refresh error: {e}")

    try:
        compute_and_store_rsi(db)
    except Exception as e:
        errors.append(f"RSI compute failed: {e}")
        logger.error(f"Cron RSI error: {e}")

    for user_doc in db.collection('users').stream():
        try:
            calculator.compute_and_store_snapshot(db, user_id=user_doc.id)
        except Exception as e:
            errors.append(f"Snapshot failed for {user_doc.id[:8]}: {e}")

    if errors:
        log_error(db, "cron/refresh-prices", f"{len(errors)} errors during daily refresh", "; ".join(errors))

    notify_url = os.environ.get("NOTIFY_WEBHOOK_URL")
    if notify_url:
        import urllib.request
        try:
            status = "with errors" if errors else "successfully"
            msg = f"Daily refresh completed {status}. {result['updated']} prices updated, {len(result['failed'])} failed."
            if errors:
                msg += f"\nErrors: {'; '.join(errors[:3])}"
            urllib.request.urlopen(urllib.request.Request(
                notify_url, data=msg.encode(), method="POST",
                headers={"Title": "Portfolio Tracker Daily Refresh", "Priority": "high" if errors else "default"},
            ))
        except Exception:
            pass

    return {
        "message": f"Cron refresh complete. Updated {result['updated']} prices, {len(result['failed'])} failed. {len(errors)} errors.",
        "updated": result["updated"],
        "failed_count": len(result["failed"]),
        "errors": errors,
    }
