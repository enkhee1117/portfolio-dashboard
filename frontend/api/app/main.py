from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Header
from fastapi.responses import JSONResponse
from . import schemas, database, importer, calculator
from google.cloud.firestore_v1.base_query import FieldFilter
import os
import shutil
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger("portfolio")


# ── Authentication ────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """Extract user_id from Firebase ID token. Raises 401 if not authenticated."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        from firebase_admin import auth
        token = authorization.replace("Bearer ", "")
        decoded = auth.verify_id_token(token)
        return decoded['uid']
    except Exception as e:
        logger.warning(f"Auth token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_optional_user(authorization: Optional[str] = Header(None)) -> str:
    """Extract user_id if token present, otherwise return 'anonymous'. For shared endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        return "anonymous"
    try:
        from firebase_admin import auth
        token = authorization.replace("Bearer ", "")
        decoded = auth.verify_id_token(token)
        return decoded['uid']
    except Exception:
        return "anonymous"


def get_user_tickers(db, user_id: str) -> set[str]:
    """Return the set of tickers a user owns from their asset_themes subcollection.
    This is the fast path — asset_themes is the user's asset registry,
    populated by migration, import, and manual registration."""
    tickers: set[str] = set()
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        tickers.add(doc.id)
    return tickers


def normalize_theme(name: str) -> str:
    """Normalize theme names to Title Case for consistent grouping."""
    return name.strip().title() if name else ""


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
    """Compute RSI from a list of closing prices (most recent last). Returns None if not enough data."""
    if len(closes) < period + 1:
        return None
    # Use last (period + 1) prices to get (period) changes
    recent = closes[-(period + 1):]
    changes = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
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

from fastapi.middleware.cors import CORSMiddleware
origins = ["http://localhost:3000", "*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

def _init_firebase():
    import firebase_admin
    from firebase_admin import credentials
    if firebase_admin._apps:
        return
    cred_path = os.path.join(os.path.dirname(__file__), "..", "firebase-credentials.json")
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    elif "FIREBASE_CREDENTIALS_JSON" in os.environ:
        cred_dict = json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()

_init_firebase()

def get_db():
    from firebase_admin import firestore
    return firestore.client()

@app.get("/")
def read_root():
    return {"message": "Portfolio Tracker API (Firebase Edition)"}

@app.post("/import")
async def import_excel(file: UploadFile = File(...), skip_dedup: bool = False, db = Depends(get_db), user_id: str = Depends(get_current_user)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)

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


# Track in-flight refresh to avoid duplicate background refreshes
_refresh_in_progress: set[str] = set()


@app.get("/portfolio", response_model=list[schemas.PortfolioSnapshot])
def get_portfolio(db = Depends(get_db), user_id: str = Depends(get_current_user)):
    data = calculator.get_cached_portfolio(db, user_id=user_id)

    # Stale-while-revalidate: if prices are >2 hours old and market is open,
    # trigger a background refresh. Serve cached data immediately.
    if _is_market_open() and user_id not in _refresh_in_progress:
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            snap_ref = db.collection('users').document(user_id).collection('portfolio_snapshots').document(today)
            snap = snap_ref.get()
            if snap.exists:
                computed_at = snap.to_dict().get('computed_at')
                if computed_at:
                    if hasattr(computed_at, 'replace'):
                        computed_at = computed_at.replace(tzinfo=None)
                    age_minutes = (datetime.utcnow() - computed_at).total_seconds() / 60
                    if age_minutes > 120:
                        import threading
                        _refresh_in_progress.add(user_id)
                        def _bg_refresh():
                            try:
                                _intraday_price_refresh()
                            finally:
                                _refresh_in_progress.discard(user_id)
                        threading.Thread(target=_bg_refresh, daemon=True).start()
        except Exception:
            pass

    portfolios = []
    for i, item in enumerate(data):
        item['id'] = str(i)
        portfolios.append(schemas.PortfolioSnapshot(**item))
    return portfolios

def parse_firestore_doc(doc) -> schemas.Trade:
    d = doc.to_dict()
    d['id'] = doc.id
    if 'date' in d and hasattr(d['date'], 'replace'):
        d['date'] = d['date'].replace(tzinfo=None)
    else:
        # Just in case timestamp isn't loaded correctly fallback to dict value if it's already string/naive
        pass
    return schemas.Trade(**d)

@app.get("/trades", response_model=list[schemas.Trade])
def get_trades(
    limit: int = 50,
    offset: int = 0,
    ticker: Optional[str] = None,
    db = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """List trades with pagination. Pass limit=0 for all trades (export/backup use)."""
    query = db.collection('trades')
    if user_id != "anonymous":
        query = query.where(filter=FieldFilter('user_id', '==', user_id))
    if ticker:
        query = query.where(filter=FieldFilter('ticker', '==', ticker.upper()))

    docs = query.stream()
    result = [parse_firestore_doc(d) for d in docs]
    result.sort(key=lambda x: x.date, reverse=True)

    # Paginate (Firestore doesn't support offset natively with compound filters,
    # so we paginate in-memory after streaming)
    total = len(result)
    if limit > 0:
        result = result[offset:offset + limit]
    return result

def _fetch_live_price(ticker: str) -> float:
    """Quick single-ticker price lookup from Yahoo Finance. Returns 0 on failure."""
    try:
        import yfinance as yf
        data = yf.download(ticker, period='1d', progress=False)
        if not data.empty:
            return round(float(data['Close'].iloc[-1]), 2)
    except Exception:
        pass
    return 0.0


def _ensure_asset_price(db, ticker: str):
    """Ensure shared asset_prices entry exists with a live price. Creates if missing."""
    shared_ref = db.collection('asset_prices').document(ticker)
    if not shared_ref.get().exists:
        price = _fetch_live_price(ticker)
        shared_ref.set({
            'ticker': ticker,
            'price': price,
            'last_updated': datetime.utcnow(),
        })
    elif db.collection('asset_prices').document(ticker).get().to_dict().get('price', 0) == 0:
        # Price is 0 — try to fetch a real one
        price = _fetch_live_price(ticker)
        if price > 0:
            shared_ref.update({'price': price, 'last_updated': datetime.utcnow()})


def _invalidate_snapshot_cache(db, user_id: str):
    """Delete today's cached snapshot so the next GET /portfolio triggers a fresh compute.
    This is cheap (1 delete) vs full recompute (~2500 reads)."""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    try:
        if user_id != "anonymous":
            db.collection('users').document(user_id).collection('portfolio_snapshots').document(today).delete()
        else:
            db.collection('portfolio_snapshots').document(today).delete()
    except Exception:
        pass


@app.post("/trades/manual", response_model=schemas.Trade)
def create_trade(trade: schemas.TradeCreate, force: bool = False, db = Depends(get_db), user_id: str = Depends(get_current_user)):
    # Normalize ticker to uppercase
    trade.ticker = trade.ticker.upper()
    if not force:
        query = db.collection('trades').where(filter=FieldFilter('ticker', '==', trade.ticker))
        if user_id != "anonymous":
            query = query.where(filter=FieldFilter('user_id', '==', user_id))
        for doc in query.stream():
            d = doc.to_dict()
            if d.get('side') == trade.side and d.get('price') == trade.price and d.get('quantity') == trade.quantity:
                raise HTTPException(status_code=409, detail="Duplicate trade detected.")

    trade_data = trade.model_dump()
    trade_data['user_id'] = user_id
    doc_ref = db.collection('trades').document()
    doc_ref.set(trade_data)

    # Auto-register ticker in user's asset_themes if not already there
    ticker_upper = trade.ticker.upper() if trade.ticker else trade.ticker
    theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker_upper)
    if not theme_ref.get().exists:
        theme_ref.set({'ticker': ticker_upper, 'primary': '', 'secondary': ''})
    # Ensure shared price entry exists with a live price
    _ensure_asset_price(db, ticker_upper)

    # Delta-update the cached snapshot for just this ticker (~5 reads vs ~2500 full recompute)
    if not calculator.apply_trade_delta(db, user_id, trade.ticker):
        _invalidate_snapshot_cache(db, user_id)  # Fallback if no cached snapshot

    trade_data['id'] = doc_ref.id
    return schemas.Trade(**trade_data)

@app.delete("/trades/{trade_id}")
def delete_trade(trade_id: str, db = Depends(get_db), user_id: str = Depends(get_current_user)):
    doc_ref = db.collection('trades').document(trade_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Verify ownership
    trade_data = doc.to_dict()
    if user_id != "anonymous" and trade_data.get('user_id') and trade_data['user_id'] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this trade")

    ticker = trade_data.get('ticker')
    doc_ref.delete()

    # Delta-update snapshot for just this ticker
    if not calculator.apply_trade_delta(db, user_id, ticker):
        _invalidate_snapshot_cache(db, user_id)

    return {"message": "Trade deleted successfully"}

@app.put("/trades/{trade_id}", response_model=schemas.Trade)
def update_trade(trade_id: str, trade: schemas.TradeCreate, db = Depends(get_db), user_id: str = Depends(get_current_user)):
    trade.ticker = trade.ticker.upper()
    doc_ref = db.collection('trades').document(trade_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Trade not found")

    existing = doc.to_dict()
    if user_id != "anonymous" and existing.get('user_id') and existing['user_id'] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this trade")

    old_ticker = existing.get('ticker')
    trade_data = trade.model_dump()
    trade_data['user_id'] = user_id
    doc_ref.update(trade_data)

    # Delta-update affected ticker(s)
    tickers_to_update = {trade.ticker}
    if old_ticker and old_ticker != trade.ticker:
        tickers_to_update.add(old_ticker)
    for t in tickers_to_update:
        if not calculator.apply_trade_delta(db, user_id, t):
            _invalidate_snapshot_cache(db, user_id)
            break

    trade_data['id'] = trade_id
    if hasattr(trade_data['date'], 'replace'):
        trade_data['date'] = trade_data['date'].replace(tzinfo=None)
    return schemas.Trade(**trade_data)


# ── Asset / Theme Management ──────────────────────────────────────────

@app.get("/assets", response_model=list[schemas.Asset])
def list_assets(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """List assets for the authenticated user (from asset_themes registry)."""
    # Single stream of user's asset registry — this IS the ticker list + themes
    user_themes: dict[str, dict] = {}
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        user_themes[doc.id] = doc.to_dict()

    if not user_themes:
        return []

    # Batch-read all price docs in one round trip instead of N sequential reads
    price_refs = [db.collection('asset_prices').document(t) for t in user_themes.keys()]
    price_docs = db.get_all(price_refs)
    price_data_map: dict[str, dict] = {}
    for doc in price_docs:
        if doc.exists:
            price_data_map[doc.id] = doc.to_dict()

    results = []
    for ticker, themes in user_themes.items():
        price_data = price_data_map.get(ticker, {})

        asset_dict = {
            "ticker": ticker,
            "price": price_data.get("price", 0.0),
            "primary_theme": themes.get("primary") or price_data.get("primary_theme", ""),
            "secondary_theme": themes.get("secondary") or price_data.get("secondary_theme", ""),
            "last_updated": price_data.get("last_updated"),
            "previous_close": price_data.get("previous_close"),
            "daily_change": price_data.get("daily_change"),
            "daily_change_pct": price_data.get("daily_change_pct"),
            "rsi": price_data.get("rsi"),
        }
        if asset_dict['last_updated'] and hasattr(asset_dict['last_updated'], 'replace'):
            asset_dict['last_updated'] = asset_dict['last_updated'].replace(tzinfo=None)
        results.append(schemas.Asset(**asset_dict))
    results.sort(key=lambda a: a.ticker)
    return results


@app.get("/assets/themes")
def list_themes(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    primary_set: set[str] = set()
    secondary_set: set[str] = set()

    docs = db.collection('users').document(user_id).collection('asset_themes').stream()
    for doc in docs:
        d = doc.to_dict()
        if d.get('primary'): primary_set.add(d['primary'])
        if d.get('secondary'): secondary_set.add(d['secondary'])

    return {
        "primary": sorted(primary_set),
        "secondary": sorted(secondary_set),
    }


@app.post("/assets", response_model=schemas.Asset, status_code=201)
def create_asset(asset: schemas.AssetCreate, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    ticker = asset.ticker.upper()

    # Check if user already has this asset
    user_theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
    user_tickers = get_user_tickers(db, user_id)
    if ticker in user_tickers:
        raise HTTPException(status_code=409, detail=f"Asset '{ticker}' already exists.")

    # Ensure shared price entry exists with a live price
    shared_ref = db.collection('asset_prices').document(ticker)
    if not shared_ref.get().exists:
        price = _fetch_live_price(ticker) or asset.price
        shared_ref.set({
            "ticker": ticker,
            "price": price,
            "last_updated": datetime.utcnow(),
        })

    # Write themes to user-scoped collection (normalized to Title Case)
    user_theme_ref.set({
        "ticker": ticker,
        "primary": normalize_theme(asset.primary_theme),
        "secondary": normalize_theme(asset.secondary_theme),
    })

    # Auto-fetch historical prices for this new ticker (best-effort)
    try:
        import threading
        threading.Thread(
            target=fetch_and_store_ticker_prices,
            args=(db, ticker),
            daemon=True,
        ).start()
    except Exception:
        pass

    # Build response from shared price data + user themes
    price_data = shared_ref.get().to_dict() or {}
    data = {
        "ticker": ticker,
        "price": price_data.get("price", asset.price),
        "primary_theme": asset.primary_theme,
        "secondary_theme": asset.secondary_theme,
        "last_updated": price_data.get("last_updated"),
    }
    if data['last_updated'] and hasattr(data['last_updated'], 'replace'):
        data['last_updated'] = data['last_updated'].replace(tzinfo=None)
    return schemas.Asset(**data)


@app.put("/assets/{ticker}", response_model=schemas.Asset)
def update_asset(ticker: str, asset: schemas.AssetUpdate, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    ticker = ticker.upper()
    user_tickers = get_user_tickers(db, user_id)
    if ticker not in user_tickers:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found.")

    new_ticker = asset.new_ticker.upper() if asset.new_ticker else None

    if new_ticker and new_ticker != ticker:
        # Rename: check new ticker not already in user's list
        if new_ticker in user_tickers:
            raise HTTPException(status_code=409, detail=f"Asset '{new_ticker}' already exists.")

        # Update only this user's trades
        trades_docs = db.collection('trades').where(
            filter=FieldFilter('user_id', '==', user_id)
        ).where(
            filter=FieldFilter('ticker', '==', ticker)
        ).stream()
        batch = db.batch()
        batch_count = 0
        for tdoc in trades_docs:
            batch.update(tdoc.reference, {'ticker': new_ticker})
            batch_count += 1
            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0
        if batch_count > 0:
            batch.commit()

        # Move user's asset_themes doc
        old_theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
        old_theme_doc = old_theme_ref.get()
        theme_data = old_theme_doc.to_dict() if old_theme_doc.exists else {}
        # Apply any theme updates from this request
        if asset.primary_theme is not None:
            theme_data['primary'] = normalize_theme(asset.primary_theme)
        if asset.secondary_theme is not None:
            theme_data['secondary'] = normalize_theme(asset.secondary_theme)
        theme_data['ticker'] = new_ticker
        db.collection('users').document(user_id).collection('asset_themes').document(new_ticker).set(theme_data)
        if old_theme_doc.exists:
            old_theme_ref.delete()

        # Ensure shared price entry exists for new ticker
        new_shared_ref = db.collection('asset_prices').document(new_ticker)
        if not new_shared_ref.get().exists:
            old_shared = db.collection('asset_prices').document(ticker).get()
            seed = old_shared.to_dict() if old_shared.exists else {}
            seed['ticker'] = new_ticker
            seed['last_updated'] = datetime.utcnow()
            new_shared_ref.set(seed)

        # Build response
        price_data = new_shared_ref.get().to_dict() or {}
        d = {
            "ticker": new_ticker,
            "price": price_data.get("price", 0.0),
            "primary_theme": theme_data.get("primary", ""),
            "secondary_theme": theme_data.get("secondary", ""),
            "last_updated": price_data.get("last_updated"),
            "previous_close": price_data.get("previous_close"),
            "daily_change": price_data.get("daily_change"),
            "daily_change_pct": price_data.get("daily_change_pct"),
            "rsi": price_data.get("rsi"),
        }
        if d['last_updated'] and hasattr(d['last_updated'], 'replace'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None)
        return schemas.Asset(**d)
    else:
        # Theme update only — write to user's asset_themes
        theme_updates = {}
        if asset.primary_theme is not None:
            theme_updates['primary'] = normalize_theme(asset.primary_theme)
        if asset.secondary_theme is not None:
            theme_updates['secondary'] = normalize_theme(asset.secondary_theme)
        if theme_updates:
            theme_updates['ticker'] = ticker
            db.collection('users').document(user_id).collection('asset_themes').document(ticker).set(
                theme_updates, merge=True
            )

        # Build response
        price_doc = db.collection('asset_prices').document(ticker).get()
        price_data = price_doc.to_dict() if price_doc.exists else {}
        theme_doc = db.collection('users').document(user_id).collection('asset_themes').document(ticker).get()
        themes = theme_doc.to_dict() if theme_doc.exists else {}
        d = {
            "ticker": ticker,
            "price": price_data.get("price", 0.0),
            "primary_theme": themes.get("primary") or price_data.get("primary_theme", ""),
            "secondary_theme": themes.get("secondary") or price_data.get("secondary_theme", ""),
            "last_updated": price_data.get("last_updated"),
            "previous_close": price_data.get("previous_close"),
            "daily_change": price_data.get("daily_change"),
            "daily_change_pct": price_data.get("daily_change_pct"),
            "rsi": price_data.get("rsi"),
        }
        if d['last_updated'] and hasattr(d['last_updated'], 'replace'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None)
        return schemas.Asset(**d)


@app.delete("/assets/{ticker}")
def delete_asset(ticker: str, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Remove asset from user's list. Does NOT delete shared price data."""
    ticker = ticker.upper()
    theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
    if not theme_ref.get().exists:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found in your assets.")
    theme_ref.delete()
    return {"message": f"Asset '{ticker}' removed from your portfolio."}


# ── Theme Management ─────────────────────────────────────────────────

@app.get("/themes/summary")
def themes_summary(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Return all themes with asset counts (user-scoped)."""
    primary: dict[str, int] = {}
    secondary: dict[str, int] = {}

    docs = db.collection('users').document(user_id).collection('asset_themes').stream()
    for doc in docs:
        d = doc.to_dict()
        pt = d.get('primary')
        st = d.get('secondary')
        if pt: primary[pt] = primary.get(pt, 0) + 1
        if st: secondary[st] = secondary.get(st, 0) + 1

    return {
        "primary": sorted([{"name": k, "count": v} for k, v in primary.items()], key=lambda x: -x["count"]),
        "secondary": sorted([{"name": k, "count": v} for k, v in secondary.items()], key=lambda x: -x["count"]),
    }


@app.put("/themes/rename")
def rename_theme(body: dict, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Rename a theme across user's assets."""
    old_name = body.get("old_name", "").strip()
    new_name = body.get("new_name", "").strip()
    field = body.get("field", "both")

    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="old_name and new_name are required.")
    if old_name == new_name:
        return {"message": "Names are the same.", "updated": 0}

    docs = db.collection('users').document(user_id).collection('asset_themes').stream()

    batch = db.batch()
    batch_count = 0
    updated = 0

    for doc in docs:
        d = doc.to_dict()
        changes = {}
        if field in ("primary", "both") and d.get('primary') == old_name:
            changes['primary'] = new_name
        if field in ("secondary", "both") and d.get('secondary') == old_name:
            changes['secondary'] = new_name
        if changes:
            batch.update(doc.reference, changes)
            batch_count += 1
            updated += 1
            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0

    if batch_count > 0:
        batch.commit()

    return {"message": f"Renamed '{old_name}' to '{new_name}'. {updated} assets updated.", "updated": updated}


@app.post("/themes/combine")
def combine_themes(body: dict, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Merge source theme into target."""
    source = body.get("source", "").strip()
    target = body.get("target", "").strip()
    field = body.get("field", "both")

    if not source or not target:
        raise HTTPException(status_code=400, detail="source and target are required.")
    if source == target:
        return {"message": "Source and target are the same.", "updated": 0}

    docs = db.collection('users').document(user_id).collection('asset_themes').stream()

    batch = db.batch()
    batch_count = 0
    updated = 0

    for doc in docs:
        d = doc.to_dict()
        changes = {}
        if field in ("primary", "both") and d.get('primary') == source:
            changes['primary'] = target
        if field in ("secondary", "both") and d.get('secondary') == source:
            changes['secondary'] = target
        if changes:
            batch.update(doc.reference, changes)
            batch_count += 1
            updated += 1
            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0

    if batch_count > 0:
        batch.commit()

    return {"message": f"Combined '{source}' into '{target}'. {updated} assets updated.", "updated": updated}


@app.delete("/themes/{name}")
def delete_theme(name: str, field: str = "both", db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Remove a theme from user's assets."""
    docs = db.collection('users').document(user_id).collection('asset_themes').stream()

    batch = db.batch()
    batch_count = 0
    updated = 0

    for doc in docs:
        d = doc.to_dict()
        changes = {}
        if field in ("primary", "both") and d.get('primary') == name:
            changes['primary'] = ""
        if field in ("secondary", "both") and d.get('secondary') == name:
            changes['secondary'] = ""
        if changes:
            batch.update(doc.reference, changes)
            batch_count += 1
            updated += 1
            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0

    if batch_count > 0:
        batch.commit()

    return {"message": f"Deleted theme '{name}'. {updated} assets updated.", "updated": updated}


# ── On-Demand Recompute ───────────────────────────────────────────────

@app.post("/portfolio/recompute")
def recompute_portfolio(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Manually recompute portfolio snapshot. Use after adding trades or when dashboard feels stale."""
    snapshot = calculator.compute_and_store_snapshot(db, user_id=user_id)
    return {
        "message": f"Portfolio recomputed: {len(snapshot.get('positions', []))} positions, ${snapshot.get('total_value', 0):,.0f} total.",
        "positions": len(snapshot.get("positions", [])),
        "total_value": snapshot.get("total_value", 0),
    }


@app.post("/trades/recheck-wash-sales")
def recheck_wash_sales(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Rerun wash sale detection across all user's trades. Run after bulk imports or edits."""
    from . import wash_sales

    # Group trades by ticker
    all_docs = db.collection('trades').where(filter=FieldFilter('user_id', '==', user_id)).stream()
    by_ticker: dict[str, list] = {}
    for doc in all_docs:
        d = doc.to_dict()
        t = d.get('ticker', '')
        if t not in by_ticker:
            by_ticker[t] = []
        by_ticker[t].append(parse_firestore_doc(doc))

    total_flagged = 0
    for ticker, trades in by_ticker.items():
        flagged = wash_sales.detect_wash_sales(trades, db)
        total_flagged += flagged if isinstance(flagged, int) else 0

    return {
        "message": f"Wash sale detection complete. Checked {sum(len(v) for v in by_ticker.values())} trades across {len(by_ticker)} tickers.",
        "tickers_checked": len(by_ticker),
        "trades_checked": sum(len(v) for v in by_ticker.values()),
    }


# ── Price Refresh (Yahoo Finance) ─────────────────────────────────────

@app.post("/assets/refresh-prices")
def refresh_prices():
    """Manual trigger for price refresh (uses shared _run_price_refresh)."""
    result = _run_price_refresh()
    # Compute RSI from price_series after refresh
    try:
        db = get_db()
        compute_and_store_rsi(db)
    except Exception:
        pass
    return {
        "message": f"Updated {result['updated']} prices, {len(result['failed'])} failed.",
        "updated": result["updated"],
        "failed": result["failed"],
    }


@app.get("/assets/refresh-status")
def refresh_status(db=Depends(get_db)):
    """Return auto-refresh schedule info and last refresh timestamp."""
    # Last refresh — single ordered query instead of streaming all docs
    latest = None
    try:
        from google.cloud.firestore_v1 import query as firestore_query
        docs = db.collection('asset_prices').order_by(
            'last_updated', direction='DESCENDING'
        ).limit(1).stream()
        for doc in docs:
            lu = doc.to_dict().get('last_updated')
            if lu and hasattr(lu, 'replace'):
                latest = lu.replace(tzinfo=None)
    except Exception:
        pass

    # Next scheduled run
    next_run = None
    if scheduler and scheduler.get_job("daily_price_refresh"):
        job = scheduler.get_job("daily_price_refresh")
        if job.next_run_time:
            next_run = job.next_run_time.isoformat()

    return {
        "last_refresh": (latest.isoformat() + "Z") if latest else None,
        "next_scheduled": next_run,
        "schedule": "Intraday: on-demand when you load the portfolio (if >2 hours stale during market hours). Full refresh: 5:30 PM ET.",
    }


# ── Portfolio History ─────────────────────────────────────────────────

@app.post("/portfolio/backfill-history")
def backfill_history(db=Depends(get_db)):
    """Backfill price_history collection with historical prices for all traded tickers."""
    import yfinance as yf
    import pandas as pd
    import math

    # Get all unique tickers and earliest trade date
    trades_docs = db.collection('trades').stream()
    tickers = set()
    earliest = None
    for doc in trades_docs:
        d = doc.to_dict()
        tickers.add(d.get('ticker'))
        dt = d.get('date')
        if hasattr(dt, 'replace'):
            dt = dt.replace(tzinfo=None)
        if dt and (earliest is None or dt < earliest):
            earliest = dt

    if not tickers or not earliest:
        return {"message": "No trades found.", "written": 0}

    # Smart gap detection: compare against last trading day, not calendar date
    all_tickers = sorted(tickers)
    last_dates = get_tickers_last_price_date(db)
    last_trading = get_last_trading_day()
    start_str = earliest.strftime('%Y-%m-%d')

    logger.info(f"Last trading day: {last_trading}")

    # Separate into: new (no data), stale (has data but not current), fresh (up to date)
    new_tickers = []
    stale_tickers = {}  # ticker -> start_date (day after last known)
    fresh_count = 0

    for ticker in all_tickers:
        if ticker not in last_dates:
            new_tickers.append(ticker)
        else:
            last = last_dates[ticker]
            if last < last_trading:
                # Need data from the day after last known date
                from datetime import timedelta
                next_day = (datetime.strptime(last, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
                stale_tickers[ticker] = next_day
            else:
                fresh_count += 1

    tickers_to_download = new_tickers + list(stale_tickers.keys())

    logger.info(
        f"Backfill: {len(new_tickers)} new, {len(stale_tickers)} stale, "
        f"{fresh_count} fresh (skipped). Downloading {len(tickers_to_download)} tickers."
    )

    written = 0
    failed_tickers = []

    if tickers_to_download:
        # For new tickers: download from earliest trade date
        # For stale tickers: download from their last known date (saves bandwidth)
        # Use earliest date as start for the batch (yfinance filters per-ticker internally)
        download_start = start_str
        if not new_tickers and stale_tickers:
            # All stale — start from the earliest stale date
            download_start = min(stale_tickers.values())

        try:
            data = yf.download(tickers_to_download, start=download_start, progress=False)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Yahoo Finance error: {e}")

        if data.empty:
            logger.warning("Yahoo Finance returned no data")
        else:
            is_multi = isinstance(data.columns, pd.MultiIndex)

            for ticker in tickers_to_download:
                try:
                    if is_multi:
                        close_series = data['Close'][ticker].dropna()
                    else:
                        close_series = data['Close'].dropna()

                    # For stale tickers, only keep dates after their last known date
                    min_date = stale_tickers.get(ticker, start_str)

                    prices_map = {}
                    for date_idx, close_val in close_series.items():
                        close_price = float(close_val)
                        if math.isnan(close_price) or close_price <= 0:
                            continue
                        date_str = date_idx.strftime('%Y-%m-%d')
                        if date_str >= min_date:
                            prices_map[date_str] = round(close_price, 2)
                            written += 1

                    if prices_map:
                        db.collection('price_series').document(ticker).set({
                            "ticker": ticker,
                            "prices": prices_map,
                            "last_updated": datetime.utcnow(),
                        }, merge=True)

                except Exception:
                    failed_tickers.append(ticker)

    # --- Phase 2: Backfill portfolio snapshots at weekly intervals ---
    logger.info("Backfilling portfolio snapshots...")
    from collections import defaultdict

    # Reload trades sorted by date
    trades_docs2 = db.collection('trades').stream()
    trades = []
    for doc in trades_docs2:
        d = doc.to_dict()
        dt = d.get('date')
        if hasattr(dt, 'replace'):
            dt = dt.replace(tzinfo=None)
        d['date'] = dt
        trades.append(d)
    trades.sort(key=lambda t: t['date'])

    # Build weekly sample dates from earliest trade to now
    sample_dates = []
    if trades:
        d = trades[0]['date']
        now = datetime.utcnow()
        while d <= now:
            sample_dates.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=7)
        sample_dates.append(now.strftime('%Y-%m-%d'))

    # Load consolidated price_series into memory (one doc per ticker)
    price_cache: dict[str, float] = {}
    ps_docs = db.collection('price_series').stream()
    for doc in ps_docs:
        dd = doc.to_dict()
        ticker = dd.get('ticker', doc.id)
        prices_map = dd.get('prices', {})
        for date_key, close in prices_map.items():
            if close and close > 0:
                price_cache[f"{ticker}_{date_key}"] = close
    logger.info(f"Loaded {len(price_cache)} price points from price_series")

    def find_price(ticker, date_str):
        key = f"{ticker}_{date_str}"
        if key in price_cache:
            return price_cache[key]
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        for i in range(1, 6):
            prev = (dt - timedelta(days=i)).strftime('%Y-%m-%d')
            if f"{ticker}_{prev}" in price_cache:
                return price_cache[f"{ticker}_{prev}"]
        return None

    # Replay trades and store snapshots
    positions = defaultdict(lambda: {"quantity": 0.0, "cost_basis": 0.0})
    trade_idx = 0
    snap_batch = db.batch()
    snap_count = 0
    snapshots_written = 0

    for date_str in sample_dates:
        while trade_idx < len(trades) and trades[trade_idx]['date'].strftime('%Y-%m-%d') <= date_str:
            t = trades[trade_idx]
            ticker = t.get('ticker')
            if t.get('type') == 'Equity':
                qty = t.get('quantity', 0)
                price = t.get('price', 0)
                if t.get('side') == 'Buy':
                    cur = positions[ticker]
                    new_qty = cur["quantity"] + qty
                    if new_qty > 0:
                        cur["cost_basis"] = ((cur["quantity"] * cur["cost_basis"]) + (qty * price)) / new_qty
                    cur["quantity"] = new_qty
                elif t.get('side') == 'Sell':
                    positions[ticker]["quantity"] -= qty
                    if abs(positions[ticker]["quantity"]) < 0.0001:
                        positions[ticker] = {"quantity": 0.0, "cost_basis": 0.0}
            trade_idx += 1

        total_value = 0.0
        for ticker, pos in positions.items():
            if abs(pos["quantity"]) < 0.0001:
                continue
            cp = find_price(ticker, date_str)
            if cp:
                total_value += pos["quantity"] * cp

        snap_batch.set(db.collection('portfolio_snapshots').document(date_str), {
            "date": date_str,
            "total_value": round(total_value, 2),
            "positions": [],  # Skip full position detail for historical (saves storage)
            "computed_at": datetime.utcnow(),
        })
        snap_count += 1
        snapshots_written += 1
        if snap_count >= 400:
            snap_batch.commit()
            snap_batch = db.batch()
            snap_count = 0

    if snap_count > 0:
        snap_batch.commit()

    # Also store today's full snapshot
    calculator.compute_and_store_snapshot(db)

    logger.info(f"Backfilled {snapshots_written} portfolio snapshots")

    return {
        "message": f"Backfilled {written} price records ({len(new_tickers)} new, {len(stale_tickers)} updated, {fresh_count} already fresh). {snapshots_written} snapshots stored.",
        "written": written,
        "snapshots": snapshots_written,
        "tickers": len(tickers),
        "failed": failed_tickers,
    }


@app.get("/portfolio/history")
def portfolio_history(period: str = "1y", db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Read precomputed portfolio snapshots for the chart."""
    from datetime import timedelta

    now = datetime.utcnow()
    if period == "ytd":
        start_str = f"{now.year}-01-01"
    else:
        period_map = {
            "1m": timedelta(days=30),
            "3m": timedelta(days=90),
            "6m": timedelta(days=180),
            "1y": timedelta(days=365),
            "all": timedelta(days=365 * 10),
        }
        delta = period_map.get(period, timedelta(days=365))
        start_str = (now - delta).strftime('%Y-%m-%d')

    # Read from user-scoped or global snapshots
    if user_id != "anonymous":
        docs = db.collection('users').document(user_id).collection('portfolio_snapshots').stream()
    else:
        docs = db.collection('portfolio_snapshots').stream()
    result = []
    for doc in docs:
        d = doc.to_dict()
        date_str = d.get('date', doc.id)
        if date_str >= start_str:
            result.append({
                "date": date_str,
                "value": round(d.get('total_value', 0), 2),
            })

    result.sort(key=lambda x: x['date'])
    return result


# ── Theme Basket Comparison ───────────────────────────────────────────

@app.get("/analytics/theme-baskets")
def theme_baskets(period: str = "1y", db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Compare theme basket performance. Each basket starts at $10,000."""
    from datetime import timedelta
    from collections import defaultdict

    now = datetime.utcnow()
    if period == "ytd":
        start_str = f"{now.year}-01-01"
    else:
        period_map = {
            "1m": timedelta(days=30),
            "3m": timedelta(days=90),
            "6m": timedelta(days=180),
            "1y": timedelta(days=365),
            "all": timedelta(days=365 * 10),
        }
        delta = period_map.get(period, timedelta(days=365))
        start_str = (now - delta).strftime('%Y-%m-%d')
    INITIAL_VALUE = 10000.0

    # Load user's assets grouped by primary theme (user-scoped)
    theme_tickers: dict[str, list[str]] = defaultdict(list)
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        d = doc.to_dict()
        theme = d.get('primary')
        ticker = doc.id
        if theme and ticker:
            theme_tickers[theme].append(ticker)

    # Batch-read price_series for all tickers (one round trip)
    all_tickers = set()
    for tickers_list in theme_tickers.values():
        all_tickers.update(tickers_list)

    prices: dict[str, dict[str, float]] = {}  # ticker -> {date: close}
    if all_tickers:
        price_refs = [db.collection('price_series').document(t) for t in all_tickers]
        for doc in db.get_all(price_refs):
            if doc.exists:
                d = doc.to_dict()
                prices[doc.id] = d.get('prices', {})

    # Collect all available dates across all tickers within period
    all_dates = set()
    for ticker_prices in prices.values():
        for date_str in ticker_prices:
            if date_str >= start_str:
                all_dates.add(date_str)
    all_dates = sorted(all_dates)

    if not all_dates:
        return {"themes": []}

    # Sample weekly to keep response manageable
    sampled_dates = []
    last_added = None
    for d in all_dates:
        if last_added is None or (datetime.strptime(d, '%Y-%m-%d') - datetime.strptime(last_added, '%Y-%m-%d')).days >= 5:
            sampled_dates.append(d)
            last_added = d
    if all_dates[-1] not in sampled_dates:
        sampled_dates.append(all_dates[-1])

    # Compute basket performance for each theme
    result_themes = []

    for theme, tickers_list in sorted(theme_tickers.items()):
        # Find tickers with price data at the start date
        valid_tickers = []
        for ticker in tickers_list:
            if ticker in prices:
                tp = prices[ticker]
                # Find earliest available price on or after start
                start_price = None
                for d in sampled_dates[:10]:  # check first few dates
                    if d in tp and tp[d] > 0:
                        start_price = tp[d]
                        break
                if start_price:
                    valid_tickers.append((ticker, start_price))

        if not valid_tickers:
            continue

        # Equal weight: each stock gets $10,000 / N
        per_stock = INITIAL_VALUE / len(valid_tickers)
        # Compute initial shares for each stock
        holdings = [(ticker, per_stock / start_price) for ticker, start_price in valid_tickers]

        # Compute basket value at each date
        data_points = []
        for date_str in sampled_dates:
            basket_val = 0.0
            for ticker, shares in holdings:
                tp = prices.get(ticker, {})
                # Find price on or before this date
                price = tp.get(date_str)
                if not price:
                    dt = datetime.strptime(date_str, '%Y-%m-%d')
                    for i in range(1, 6):
                        prev = (dt - timedelta(days=i)).strftime('%Y-%m-%d')
                        if prev in tp:
                            price = tp[prev]
                            break
                if price:
                    basket_val += shares * price

            if basket_val > 0:
                data_points.append({"date": date_str, "value": round(basket_val, 2)})

        if data_points:
            start_val = data_points[0]["value"]
            end_val = data_points[-1]["value"]
            return_pct = ((end_val - start_val) / start_val * 100) if start_val > 0 else 0

            result_themes.append({
                "name": theme,
                "stocks": len(valid_tickers),
                "start_value": round(start_val, 2),
                "end_value": round(end_val, 2),
                "return_pct": round(return_pct, 2),
                "data": data_points,
            })

    # Sort by return descending
    result_themes.sort(key=lambda t: t["return_pct"], reverse=True)

    return {"themes": result_themes}


# ── Data Migration ────────────────────────────────────────────────────

@app.post("/admin/migrate-to-user")
def migrate_to_user(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """
    One-time migration: assign current user's UID to all unowned trades,
    copy themes from asset_prices to user's subcollection, and
    copy portfolio_snapshots to user's subcollection.
    Only works for authenticated users.
    """
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Must be authenticated to migrate data.")

    # 1. Assign user_id to all trades that don't have one
    trades = db.collection('trades').stream()
    batch = db.batch()
    batch_count = 0
    trades_migrated = 0
    for doc in trades:
        d = doc.to_dict()
        if not d.get('user_id') or d['user_id'] == 'anonymous':
            batch.update(doc.reference, {'user_id': user_id})
            batch_count += 1
            trades_migrated += 1
            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0
    if batch_count > 0:
        batch.commit()

    # 2. Copy themes from asset_prices to user's asset_themes subcollection
    # First, get all tickers the user has trades for
    user_tickers = set()
    for doc in db.collection('trades').where(filter=FieldFilter('user_id', '==', user_id)).stream():
        t = doc.to_dict().get('ticker')
        if t:
            user_tickers.add(t)

    assets = db.collection('asset_prices').stream()
    batch = db.batch()
    batch_count = 0
    themes_migrated = 0
    for doc in assets:
        d = doc.to_dict()
        ticker = d.get('ticker', doc.id)
        p_theme = d.get('primary_theme')
        s_theme = d.get('secondary_theme')
        # Migrate if asset has themes OR user has trades for it
        if p_theme or s_theme or ticker in user_tickers:
            theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
            batch.set(theme_ref, {
                'ticker': ticker,
                'primary': p_theme or '',
                'secondary': s_theme or '',
            }, merge=True)
            batch_count += 1
            themes_migrated += 1
            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0
    if batch_count > 0:
        batch.commit()

    # 3. Copy portfolio_snapshots to user's subcollection
    snapshots = db.collection('portfolio_snapshots').stream()
    batch = db.batch()
    batch_count = 0
    snapshots_migrated = 0
    for doc in snapshots:
        d = doc.to_dict()
        user_snap_ref = db.collection('users').document(user_id).collection('portfolio_snapshots').document(doc.id)
        batch.set(user_snap_ref, d, merge=True)
        batch_count += 1
        snapshots_migrated += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count > 0:
        batch.commit()

    # 4. Recompute today's snapshot for this user
    try:
        calculator.compute_and_store_snapshot(db, user_id=user_id)
    except Exception:
        pass

    return {
        "message": f"Migration complete for user {user_id[:8]}...",
        "trades_migrated": trades_migrated,
        "themes_migrated": themes_migrated,
        "snapshots_migrated": snapshots_migrated,
    }


# ── CSV Export (Trades) ───────────────────────────────────────────────

@app.get("/trades/export-csv")
def export_trades_csv(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Export user's trades as a CSV file for tax or analytics purposes."""
    from fastapi.responses import StreamingResponse
    import csv, io

    docs = db.collection('trades').where(filter=FieldFilter('user_id', '==', user_id)).stream()
    trades = []
    for doc in docs:
        d = doc.to_dict()
        if 'date' in d and hasattr(d['date'], 'strftime'):
            d['date'] = d['date'].strftime('%Y-%m-%d')
        if 'expiration_date' in d and d.get('expiration_date') and hasattr(d['expiration_date'], 'strftime'):
            d['expiration_date'] = d['expiration_date'].strftime('%Y-%m-%d')
        trades.append(d)

    trades.sort(key=lambda t: t.get('date', ''))

    # Fetch user's asset themes to include in export
    asset_data = {}
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        ad = doc.to_dict()
        asset_data[doc.id] = {
            'primary_theme': ad.get('primary', ''),
            'secondary_theme': ad.get('secondary', ''),
        }

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date', 'Ticker', 'Side', 'Quantity', 'Price', 'Total',
        'Type', 'Fees', 'Currency', 'Primary Theme', 'Secondary Theme',
        'Is Wash Sale',
    ])

    for t in trades:
        ticker = t.get('ticker', '')
        qty = t.get('quantity', 0)
        price = t.get('price', 0)
        themes = asset_data.get(ticker, {})
        writer.writerow([
            t.get('date', ''),
            ticker,
            t.get('side', ''),
            qty,
            price,
            round(qty * price, 2),
            t.get('type', 'Equity'),
            t.get('fees', 0),
            t.get('currency', 'USD'),
            themes.get('primary_theme', ''),
            themes.get('secondary_theme', ''),
            'Yes' if t.get('is_wash_sale') else '',
        ])

    output.seek(0)
    filename = f"trades_export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Export / Restore Backup ───────────────────────────────────────────

@app.get("/backup/export")
def export_backup(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Export user's trades and asset themes as a single JSON backup file."""

    # Export user's trades
    trades = []
    for doc in db.collection('trades').where(filter=FieldFilter('user_id', '==', user_id)).stream():
        d = doc.to_dict()
        if 'date' in d and hasattr(d['date'], 'isoformat'):
            d['date'] = d['date'].replace(tzinfo=None).isoformat()
        if 'expiration_date' in d and d['expiration_date'] and hasattr(d['expiration_date'], 'isoformat'):
            d['expiration_date'] = d['expiration_date'].replace(tzinfo=None).isoformat()
        d['_doc_id'] = doc.id
        trades.append(d)

    # Export user's asset themes
    assets = []
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        d = doc.to_dict()
        d['_doc_id'] = doc.id
        assets.append(d)

    backup = {
        "version": 2,
        "user_id": user_id,
        "exported_at": datetime.utcnow().isoformat(),
        "trades_count": len(trades),
        "assets_count": len(assets),
        "trades": trades,
        "assets": assets,
    }

    return JSONResponse(
        content=backup,
        headers={
            "Content-Disposition": f'attachment; filename="portfolio_backup_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json"'
        },
    )


@app.post("/backup/restore")
async def restore_backup(file: UploadFile = File(...), db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Restore user's trades and asset themes from a JSON backup file."""
    try:
        content = await file.read()
        backup = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid backup file: {e}")

    version = backup.get("version", 1)
    if version not in (1, 2):
        raise HTTPException(status_code=400, detail="Unsupported backup version.")

    trades_data = backup.get("trades", [])
    assets_data = backup.get("assets", [])

    # --- Delete user's existing data only ---
    # Delete user's trades
    existing_trades = db.collection('trades').where(filter=FieldFilter('user_id', '==', user_id)).stream()
    batch = db.batch()
    batch_count = 0
    deleted_trades = 0
    for doc in existing_trades:
        batch.delete(doc.reference)
        batch_count += 1
        deleted_trades += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count > 0:
        batch.commit()

    # Delete user's asset themes
    existing_themes = db.collection('users').document(user_id).collection('asset_themes').stream()
    batch = db.batch()
    batch_count = 0
    deleted_assets = 0
    for doc in existing_themes:
        batch.delete(doc.reference)
        batch_count += 1
        deleted_assets += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count > 0:
        batch.commit()

    # --- Restore trades (stamp with user_id) ---
    batch = db.batch()
    batch_count = 0
    restored_trades = 0
    for t in trades_data:
        doc_id = t.pop('_doc_id', None)
        if 'date' in t and isinstance(t['date'], str):
            t['date'] = datetime.fromisoformat(t['date'])
        if 'expiration_date' in t and isinstance(t.get('expiration_date'), str):
            t['expiration_date'] = datetime.fromisoformat(t['expiration_date'])
        t['user_id'] = user_id

        doc_ref = db.collection('trades').document(doc_id) if doc_id else db.collection('trades').document()
        batch.set(doc_ref, t)
        batch_count += 1
        restored_trades += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count > 0:
        batch.commit()

    # --- Restore assets to user-scoped asset_themes ---
    batch = db.batch()
    batch_count = 0
    restored_assets = 0
    for a in assets_data:
        doc_id = a.pop('_doc_id', None)
        a.pop('last_updated', None)  # Not relevant for user themes
        ticker = doc_id or a.get('ticker', '')
        if not ticker:
            continue

        # Version 1 (legacy): fields are primary_theme/secondary_theme in shared format
        # Version 2 (user-scoped): fields are primary/secondary
        if version == 1:
            theme_data = {
                'ticker': ticker,
                'primary': a.get('primary_theme', ''),
                'secondary': a.get('secondary_theme', ''),
            }
            # Ensure shared price entry exists for price refresh
            shared_ref = db.collection('asset_prices').document(ticker)
            if not shared_ref.get().exists:
                shared_ref.set({'ticker': ticker, 'price': a.get('price', 0.0), 'last_updated': datetime.utcnow()})
        else:
            theme_data = {
                'ticker': ticker,
                'primary': a.get('primary', ''),
                'secondary': a.get('secondary', ''),
            }

        doc_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
        batch.set(doc_ref, theme_data)
        batch_count += 1
        restored_assets += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count > 0:
        batch.commit()

    return {
        "message": f"Restore complete. {restored_trades} trades and {restored_assets} assets restored.",
        "deleted": {"trades": deleted_trades, "assets": deleted_assets},
        "restored": {"trades": restored_trades, "assets": restored_assets},
    }
