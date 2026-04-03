from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Header
from fastapi.responses import JSONResponse
from . import schemas, database, importer, calculator
from .auth import get_current_user, get_optional_user, get_user_tickers, normalize_theme
from .services.monitoring import log_error
from google.cloud.firestore_v1.base_query import FieldFilter
import os
import shutil
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger("portfolio")


# ── Shared Price Fetching Utilities ───────────────────────────────────

def fetch_and_store_ticker_prices(db, ticker: str, start: str = "2020-01-01"):
    """
    Fetch historical prices for a single ticker and store in price_series.
    Merges with existing data (won't overwrite existing dates).
    Returns number of new price points written.
    """
    import yfinance as yf
    import math

    try:
        data = yf.download(ticker, start=start, progress=False)
        if data.empty:
            return 0

        close_series = data['Close'].dropna()
        prices_map = {}
        for date_idx, close_val in close_series.items():
            close_price = float(close_val)
            if not math.isnan(close_price) and close_price > 0:
                prices_map[date_idx.strftime('%Y-%m-%d')] = round(close_price, 2)

        if prices_map:
            db.collection('price_series').document(ticker).set({
                "ticker": ticker,
                "prices": prices_map,
                "last_updated": datetime.utcnow(),
            }, merge=True)

        logger.info(f"Stored {len(prices_map)} price points for {ticker}")
        return len(prices_map)
    except Exception as e:
        logger.error(f"Failed to fetch prices for {ticker}: {e}")
        return 0


def compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI using Wilder's smoothing method (standard).
    Uses the full price history for accurate smoothed averages, not just the last N prices."""
    if len(closes) < period + 1:
        return None

    changes = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]

    # Seed with simple moving average of first `period` changes
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's smoothing: avg = (prev_avg * (period-1) + current) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_and_store_rsi(db):
    """Compute RSI for all tickers from price_series and store in asset_prices.
    Skips the full asset_prices stream — uses set(merge=True) to safely upsert."""
    docs = db.collection('price_series').stream()
    batch = db.batch()
    batch_count = 0
    computed = 0

    for doc in docs:
        ticker = doc.id
        d = doc.to_dict()
        prices_map = d.get('prices', {})
        if not prices_map:
            continue

        sorted_dates = sorted(prices_map.keys())
        closes = [prices_map[dt] for dt in sorted_dates]

        rsi = compute_rsi(closes)
        if rsi is not None:
            # set(merge=True) avoids NOT_FOUND — creates doc if missing, merges if exists
            batch.set(db.collection('asset_prices').document(ticker), {"rsi": rsi}, merge=True)
            batch_count += 1
            computed += 1

            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0

    if batch_count > 0:
        batch.commit()

    logger.info(f"RSI computed for {computed} tickers")
    return computed


def get_tickers_last_price_date(db) -> dict[str, str]:
    """Return dict of ticker -> last date in price_series (YYYY-MM-DD)."""
    result = {}
    docs = db.collection('price_series').stream()
    for doc in docs:
        d = doc.to_dict()
        prices = d.get('prices', {})
        if prices:
            result[doc.id] = max(prices.keys())
    return result


def get_last_trading_day() -> str:
    """
    Return the last US market trading day as YYYY-MM-DD.
    Uses a well-known liquid ticker (SPY) as reference.
    Falls back to yesterday if the API call fails.
    """
    import yfinance as yf
    try:
        data = yf.download("SPY", period="5d", progress=False)
        if not data.empty:
            return data.index[-1].strftime('%Y-%m-%d')
    except Exception:
        pass
    # Fallback: walk back from today skipping weekends
    from datetime import timedelta
    d = datetime.utcnow()
    for _ in range(5):
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            return d.strftime('%Y-%m-%d')
    return (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')


# ── Scheduled Price Refresh ───────────────────────────────────────────

def _get_active_tickers(db) -> list[str]:
    """Return all tickers that need price updates: from trades + existing asset_prices.
    Includes all asset_prices entries so end-of-day refresh covers everything for RSI."""
    tickers = set()
    for doc in db.collection('trades').stream():
        t = doc.to_dict().get('ticker')
        if t:
            tickers.add(t)
    # Also include existing asset_prices (some may not have trades but need RSI/history)
    for doc in db.collection('asset_prices').stream():
        tickers.add(doc.id)
    return sorted(tickers)


def _run_price_refresh():
    """Standalone price refresh function called by scheduler and API."""
    import yfinance as yf
    import pandas as pd
    import math

    db = get_db()
    tickers = _get_active_tickers(db)

    if not tickers:
        logger.info("Price refresh: no assets to update.")
        return {"updated": 0, "failed": []}

    # Download in chunks to avoid yfinance timeout at scale
    CHUNK_SIZE = 500
    all_data = None
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        try:
            chunk_data = yf.download(chunk, period='5d', progress=False)
            if all_data is None:
                all_data = chunk_data
            elif not chunk_data.empty:
                all_data = pd.concat([all_data, chunk_data], axis=1)
        except Exception as e:
            logger.error(f"Price refresh: Yahoo Finance error for chunk {i}: {e}")

    if all_data is None or all_data.empty:
        return {"updated": 0, "failed": tickers}

    data = all_data
    is_multi = isinstance(data.columns, pd.MultiIndex)
    now = datetime.utcnow()

    updated = 0
    failed = []
    asset_batch = db.batch()
    asset_batch_count = 0
    history_batch = db.batch()
    history_batch_count = 0

    for ticker in tickers:
        try:
            if is_multi:
                close_series = data['Close'][ticker].dropna()
                open_series = data['Open'][ticker].dropna()
                high_series = data['High'][ticker].dropna()
                low_series = data['Low'][ticker].dropna()
                vol_series = data['Volume'][ticker].dropna() if 'Volume' in data.columns.get_level_values(0) else pd.Series()
            else:
                close_series = data['Close'].dropna()
                open_series = data['Open'].dropna()
                high_series = data['High'].dropna()
                low_series = data['Low'].dropna()
                vol_series = data['Volume'].dropna() if 'Volume' in data.columns else pd.Series()

            if len(close_series) < 1:
                failed.append(ticker)
                continue

            close_price = float(close_series.iloc[-1])
            open_price = float(open_series.iloc[-1]) if len(open_series) > 0 else 0.0
            high_price = float(high_series.iloc[-1]) if len(high_series) > 0 else 0.0
            low_price = float(low_series.iloc[-1]) if len(low_series) > 0 else 0.0
            volume = float(vol_series.iloc[-1]) if len(vol_series) > 0 else 0.0
            latest_date = close_series.index[-1].strftime('%Y-%m-%d')
            prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else None

            daily_change = None
            daily_change_pct = None
            if prev_close and prev_close > 0 and not math.isnan(prev_close):
                daily_change = round(close_price - prev_close, 2)
                daily_change_pct = round((daily_change / prev_close) * 100, 2)

            if close_price > 0 and not math.isnan(close_price):
                doc_ref = db.collection('asset_prices').document(ticker)
                asset_batch.set(doc_ref, {
                    "ticker": ticker,
                    "price": round(close_price, 2),
                    "previous_close": round(prev_close, 2) if prev_close and not math.isnan(prev_close) else None,
                    "daily_change": daily_change,
                    "daily_change_pct": daily_change_pct,
                    "last_updated": now,
                }, merge=True)
                asset_batch_count += 1

                history_doc_id = f"{ticker}_{latest_date}"
                history_ref = db.collection('price_history').document(history_doc_id)
                history_batch.set(history_ref, {
                    "ticker": ticker,
                    "date": latest_date,
                    "open": round(open_price, 2),
                    "high": round(high_price, 2),
                    "low": round(low_price, 2),
                    "close": round(close_price, 2),
                    "previous_close": round(prev_close, 2) if prev_close and not math.isnan(prev_close) else None,
                    "volume": round(volume, 0) if not math.isnan(volume) else 0,
                })
                history_batch_count += 1
                updated += 1

                if asset_batch_count >= 400:
                    asset_batch.commit()
                    asset_batch = db.batch()
                    asset_batch_count = 0
                if history_batch_count >= 400:
                    history_batch.commit()
                    history_batch = db.batch()
                    history_batch_count = 0
            else:
                failed.append(ticker)
        except Exception:
            failed.append(ticker)

    if asset_batch_count > 0:
        asset_batch.commit()
    if history_batch_count > 0:
        history_batch.commit()

    # Also update consolidated price_series (one doc per ticker)
    for ticker in tickers:
        if ticker in failed:
            continue
        try:
            if is_multi:
                close_series = data['Close'][ticker].dropna()
            else:
                close_series = data['Close'].dropna()
            if len(close_series) > 0:
                latest_date = close_series.index[-1].strftime('%Y-%m-%d')
                close_price = float(close_series.iloc[-1])
                if close_price > 0 and not math.isnan(close_price):
                    db.collection('price_series').document(ticker).set({
                        "ticker": ticker,
                        "last_updated": now,
                        f"prices.{latest_date}": round(close_price, 2),
                    }, merge=True)
        except Exception:
            pass

    logger.info(f"Price refresh complete: {updated} updated, {len(failed)} failed.")
    return {"updated": updated, "failed": failed}


def _intraday_price_refresh():
    """Lightweight refresh: only update prices for active portfolio tickers.
    Runs on-demand when portfolio is loaded and prices are >2 hours stale during market hours."""
    import yfinance as yf
    import pandas as pd
    import math

    today = datetime.utcnow()
    if today.weekday() >= 5:
        return

    db = get_db()

    # Get active tickers from all users' latest snapshots
    active_tickers = set()
    for user_doc in db.collection('users').stream():
        snap_date = today.strftime('%Y-%m-%d')
        snap = user_doc.reference.collection('portfolio_snapshots').document(snap_date).get()
        if snap.exists:
            for p in snap.to_dict().get('positions', []):
                if p.get('quantity', 0) > 0:
                    active_tickers.add(p.get('ticker'))

    if not active_tickers:
        return

    tickers = sorted(active_tickers)
    logger.info(f"Intraday refresh: {len(tickers)} active tickers")

    try:
        data = yf.download(tickers, period='1d', progress=False)
    except Exception as e:
        logger.error(f"Intraday refresh yfinance error: {e}")
        return

    if data.empty:
        return

    is_multi = isinstance(data.columns, pd.MultiIndex)
    now = datetime.utcnow()
    batch = db.batch()
    batch_count = 0
    updated = 0

    for ticker in tickers:
        try:
            if is_multi:
                close_series = data['Close'][ticker].dropna()
            else:
                close_series = data['Close'].dropna()

            if len(close_series) < 1:
                continue

            close_price = float(close_series.iloc[-1])
            prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else None

            daily_change = None
            daily_change_pct = None
            if prev_close and prev_close > 0 and not math.isnan(prev_close):
                daily_change = round(close_price - prev_close, 2)
                daily_change_pct = round((daily_change / prev_close) * 100, 2)

            if close_price > 0 and not math.isnan(close_price):
                doc_ref = db.collection('asset_prices').document(ticker)
                batch.update(doc_ref, {
                    "price": round(close_price, 2),
                    "previous_close": round(prev_close, 2) if prev_close and not math.isnan(prev_close) else None,
                    "daily_change": daily_change,
                    "daily_change_pct": daily_change_pct,
                    "last_updated": now,
                })
                batch_count += 1
                updated += 1

                if batch_count >= 400:
                    batch.commit()
                    batch = db.batch()
                    batch_count = 0
        except Exception:
            continue

    if batch_count > 0:
        batch.commit()

    # Update prices in all users' cached snapshots
    if updated > 0:
        # Build price lookup from what we just fetched
        price_map = {}
        for ticker in tickers:
            try:
                if is_multi:
                    close_series = data['Close'][ticker].dropna()
                else:
                    close_series = data['Close'].dropna()
                if len(close_series) > 0:
                    price_map[ticker] = round(float(close_series.iloc[-1]), 2)
            except Exception:
                continue

        for user_doc in db.collection('users').stream():
            snap_date = today.strftime('%Y-%m-%d')
            snap_ref = user_doc.reference.collection('portfolio_snapshots').document(snap_date)
            snap = snap_ref.get()
            if not snap.exists:
                continue
            snapshot = snap.to_dict()
            positions = snapshot.get('positions', [])
            total_value = 0.0
            changed = False
            for p in positions:
                t = p.get('ticker')
                if t in price_map:
                    new_price = price_map[t]
                    old_price = p.get('current_price', 0)
                    if new_price != old_price:
                        p['current_price'] = new_price
                        qty = p.get('quantity', 0)
                        avg = p.get('average_price', 0)
                        p['market_value'] = round(qty * new_price, 2)
                        p['unrealized_pnl'] = round((new_price - avg) * qty, 2) if abs(qty) > 0.0001 else 0.0
                        changed = True
                total_value += p.get('market_value', 0)
            if changed:
                snapshot['total_value'] = round(total_value, 2)
                snapshot['computed_at'] = now
                snap_ref.set(snapshot)

    logger.info(f"Intraday refresh complete: {updated} tickers updated")


def _scheduled_refresh():
    """End-of-day full refresh — all tickers, RSI, full snapshot recompute."""
    today = datetime.utcnow()
    if today.weekday() >= 5:
        logger.info(f"Skipping scheduled refresh — weekend ({today.strftime('%A')})")
        return

    logger.info("End-of-day price refresh starting...")
    try:
        result = _run_price_refresh()
        if result['updated'] == 0 and len(result['failed']) == len(result.get('failed', [])):
            logger.info("No price updates — market may be closed (holiday)")
            return
        logger.info(f"Scheduled refresh result: {result['updated']} updated, {len(result['failed'])} failed")
        db = get_db()
        compute_and_store_rsi(db)
        # Full recompute for all users
        for user_doc in db.collection('users').stream():
            try:
                calculator.compute_and_store_snapshot(db, user_id=user_doc.id)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Scheduled refresh error: {e}")


# APScheduler — runs weekdays at 5:30 PM US/Eastern (after market close)
# Only starts in non-serverless environments (Vercel serverless doesn't support background threads)
scheduler = None
IS_SERVERLESS = os.environ.get("VERCEL", "") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")

@asynccontextmanager
async def lifespan(app):
    global scheduler
    if not IS_SERVERLESS:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            scheduler = BackgroundScheduler()
            # End-of-day full refresh: all tickers, RSI, full snapshot recompute
            scheduler.add_job(
                _scheduled_refresh,
                CronTrigger(
                    hour=17, minute=30,
                    day_of_week="mon-fri",
                    timezone="US/Eastern",
                ),
                id="daily_price_refresh",
                replace_existing=True,
            )
            scheduler.start()
            logger.info("Scheduler started — daily full refresh at 5:30 PM ET. Intraday: on-demand when user loads portfolio.")
        except Exception as e:
            logger.warning(f"Scheduler not started: {e}")
    else:
        logger.info("Serverless environment — scheduler disabled")
    yield
    if scheduler:
        scheduler.shutdown()
        logger.info("Price refresh scheduler stopped")


app = FastAPI(lifespan=lifespan)

# ── Rate Limiting ─────────────────────────────────────────────────────
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

_rate_limit_enabled = os.environ.get("TESTING", "") != "1"
limiter = Limiter(key_func=get_remote_address, enabled=_rate_limit_enabled)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.middleware.cors import CORSMiddleware

# Production CORS — only allow known origins
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://portfolio-dashboard-seven-lemon.vercel.app",
]
# Allow custom domain via env var (e.g., https://app.moljuurtei.com)
_custom_origin = os.environ.get("CORS_ORIGIN")
if _custom_origin:
    ALLOWED_ORIGINS.append(_custom_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Performance Monitoring Middleware ─────────────────────────────────
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Thresholds — requests exceeding these log a warning
SLOW_REQUEST_MS = 2000  # Warn if request takes >2 seconds
SLOW_CRUD_MS = 500      # Warn if trade CRUD takes >500ms

CRUD_PATHS = {"/trades/manual", "/trades/"}  # Paths that should be fast

class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        path = request.url.path
        method = request.method

        # Determine threshold
        is_crud = any(path.startswith(p) or path.endswith(p.rstrip('/')) for p in CRUD_PATHS)
        threshold = SLOW_CRUD_MS if is_crud and method in ("POST", "PUT", "DELETE") else SLOW_REQUEST_MS

        if duration_ms > threshold:
            logger.warning(
                f"SLOW REQUEST: {method} {path} took {duration_ms:.0f}ms "
                f"(threshold: {threshold}ms) status={response.status_code}"
            )
        elif duration_ms > 500:
            logger.info(f"{method} {path} {duration_ms:.0f}ms")

        # Add timing header for frontend to read
        response.headers["X-Response-Time-Ms"] = str(int(duration_ms))
        return response

app.add_middleware(PerformanceMiddleware)

# Firebase init and get_db moved to deps.py (shared with route modules)
from .deps import get_db

# ── Route Modules ─────────────────────────────────────────────────────
from .routes import cron as cron_routes, analytics as analytics_routes, admin as admin_routes
from .routes import portfolio as portfolio_routes, trades as trades_routes, assets as assets_routes
app.include_router(cron_routes.router)
app.include_router(analytics_routes.router)
app.include_router(admin_routes.router)
app.include_router(portfolio_routes.router)
app.include_router(trades_routes.router)
app.include_router(assets_routes.router)


@app.get("/")
def read_root():
    return {"message": "Portfolio Tracker API (Firebase Edition)"}


@app.get("/health")
def health_check(db=Depends(get_db)):
    """Health check endpoint — returns app status and recent errors."""
    errors = []
    try:
        docs = db.collection('error_log').order_by(
            'timestamp', direction='DESCENDING'
        ).limit(10).stream()
        for doc in docs:
            d = doc.to_dict()
            ts = d.get('timestamp')
            if ts and hasattr(ts, 'isoformat'):
                ts = ts.replace(tzinfo=None).isoformat() + "Z"
            errors.append({
                "source": d.get("source"),
                "message": d.get("message"),
                "timestamp": ts,
            })
    except Exception:
        pass

    # Check last price refresh
    last_refresh = None
    try:
        docs = db.collection('asset_prices').order_by(
            'last_updated', direction='DESCENDING'
        ).limit(1).stream()
        for doc in docs:
            lu = doc.to_dict().get('last_updated')
            if lu and hasattr(lu, 'replace'):
                last_refresh = lu.replace(tzinfo=None).isoformat() + "Z"
    except Exception:
        pass

    # Stale check: warn if prices are >26 hours old (missed daily refresh)
    price_stale = False
    if last_refresh:
        from datetime import timedelta
        last_dt = datetime.fromisoformat(last_refresh.rstrip("Z"))
        price_stale = (datetime.utcnow() - last_dt) > timedelta(hours=26)

    return {
        "status": "degraded" if price_stale or len(errors) > 5 else "healthy",
        "price_stale": price_stale,
        "last_price_refresh": last_refresh,
        "recent_errors": len(errors),
        "errors": errors,
    }

@app.get("/config")
def get_config():
    """Return feature flags and app configuration."""
    from .feature_flags import get_all_flags
    return {"features": get_all_flags()}


@app.post("/import")
@limiter.limit("5/minute")
async def import_excel(request: Request, file: UploadFile = File(...), skip_dedup: bool = False, db = Depends(get_db), user_id: str = Depends(get_current_user)):
    # Limit upload size to 10MB
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum 10MB.")
    await file.seek(0)

    file_location = f"temp_{file.filename}"
    with open(file_location, "wb+") as file_object:
        file_object.write(contents)

    try:
        result = importer.import_data(db, file_location, skip_dedup=skip_dedup, user_id=user_id)
        count = result.get("added", 0) if result else 0
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)

    # Auto-register any new trade tickers in user's asset_themes
    if count > 0 and user_id != "anonymous":
        existing_themes = set(
            doc.id for doc in db.collection('users').document(user_id).collection('asset_themes').stream()
        )
        trade_tickers = set()
        for doc in db.collection('trades').where(filter=FieldFilter('user_id', '==', user_id)).stream():
            t = doc.to_dict().get('ticker')
            if t:
                trade_tickers.add(t)
        new_tickers = trade_tickers - existing_themes
        if new_tickers:
            batch = db.batch()
            batch_count = 0
            for ticker in new_tickers:
                ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
                batch.set(ref, {'ticker': ticker, 'primary': '', 'secondary': ''})
                # Ensure shared price entry
                shared_ref = db.collection('asset_prices').document(ticker)
                batch.set(shared_ref, {'ticker': ticker, 'price': 0.0, 'last_updated': datetime.utcnow()}, merge=True)
                batch_count += 2
                if batch_count >= 400:
                    batch.commit()
                    batch = db.batch()
                    batch_count = 0
            if batch_count > 0:
                batch.commit()

    return {"message": f"Import successful. Added {count} new trades."}

def _is_market_open() -> bool:
    """Check if US stock market is likely open (weekday, 9:30 AM - 4 PM ET)."""
    from datetime import timezone, timedelta
    et = timezone(timedelta(hours=-4))  # EDT (approximate — close enough for staleness check)
    now_et = datetime.now(et)
    if now_et.weekday() >= 5:  # Weekend
        return False
    hour, minute = now_et.hour, now_et.minute
    if hour < 9 or (hour == 9 and minute < 30) or hour >= 16:
        return False
    return True


