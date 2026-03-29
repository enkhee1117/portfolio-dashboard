from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from . import schemas, database, importer, calculator
from google.cloud.firestore_v1.base_query import FieldFilter
import os
import shutil
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager

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

def _run_price_refresh():
    """Standalone price refresh function called by scheduler and API."""
    import yfinance as yf
    import pandas as pd
    import math

    db = get_db()
    docs = db.collection('asset_prices').stream()
    tickers = [d.to_dict().get('ticker') for d in docs if d.to_dict().get('ticker')]

    if not tickers:
        logger.info("Price refresh: no assets to update.")
        return {"updated": 0, "failed": []}

    try:
        data = yf.download(tickers, period='5d', progress=False)
    except Exception as e:
        logger.error(f"Price refresh: Yahoo Finance error: {e}")
        return {"updated": 0, "failed": tickers}

    if data.empty:
        return {"updated": 0, "failed": tickers}

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
                asset_batch.update(doc_ref, {
                    "price": round(close_price, 2),
                    "previous_close": round(prev_close, 2) if prev_close and not math.isnan(prev_close) else None,
                    "daily_change": daily_change,
                    "daily_change_pct": daily_change_pct,
                    "last_updated": now,
                })
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


def _scheduled_refresh():
    """Wrapper for the scheduler — skips weekends/holidays, logs errors."""
    # Skip if today is not a trading day (weekends, holidays)
    today = datetime.utcnow()
    if today.weekday() >= 5:  # Saturday=5, Sunday=6
        logger.info(f"Skipping scheduled refresh — weekend ({today.strftime('%A')})")
        return

    logger.info("Scheduled price refresh starting...")
    try:
        result = _run_price_refresh()
        if result['updated'] == 0 and len(result['failed']) == len(result.get('failed', [])):
            logger.info("No price updates — market may be closed (holiday)")
            return
        logger.info(f"Scheduled refresh result: {result['updated']} updated, {len(result['failed'])} failed")
        # Recompute today's portfolio snapshot with updated prices
        db = get_db()
        calculator.compute_and_store_snapshot(db)
    except Exception as e:
        logger.error(f"Scheduled refresh error: {e}")


# APScheduler — runs weekdays at 5:30 PM US/Eastern (after market close)
scheduler = None

@asynccontextmanager
async def lifespan(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    global scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _scheduled_refresh,
        CronTrigger(
            hour=17, minute=30,
            day_of_week="mon-fri",  # Skip weekends
            timezone="US/Eastern",
        ),
        id="daily_price_refresh",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Price refresh scheduler started — daily at 5:30 PM ET")
    yield
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

def get_db():
    import firebase_admin
    from firebase_admin import credentials, firestore
    
    if not firebase_admin._apps:
        cred_path = os.path.join(os.path.dirname(__file__), "..", "firebase-credentials.json")
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        elif "FIREBASE_CREDENTIALS_JSON" in os.environ:
            import json
            cred_dict = json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"])
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    return firestore.client()

@app.get("/")
def read_root():
    return {"message": "Portfolio Tracker API (Firebase Edition)"}

@app.post("/import")
async def import_excel(file: UploadFile = File(...), skip_dedup: bool = False, db = Depends(get_db)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)

    try:
        result = importer.import_data(db, file_location, skip_dedup=skip_dedup)
        count = result.get("added", 0) if result else 0
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)

    return {"message": f"Import successful. Added {count} new trades."}

@app.get("/portfolio", response_model=list[schemas.PortfolioSnapshot])
def get_portfolio(db = Depends(get_db)):
    data = calculator.get_cached_portfolio(db)
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
def get_trades(db = Depends(get_db)):
    docs = db.collection('trades').stream()
    result = [parse_firestore_doc(d) for d in docs]
    result.sort(key=lambda x: x.date, reverse=True)
    return result

@app.post("/trades/manual", response_model=schemas.Trade)
def create_trade(trade: schemas.TradeCreate, force: bool = False, db = Depends(get_db)):
    if not force:
        trades_docs = db.collection('trades').where(filter=FieldFilter('ticker', '==', trade.ticker)).stream()
        for doc in trades_docs:
            d = doc.to_dict()
            if d.get('side') == trade.side and d.get('price') == trade.price and d.get('quantity') == trade.quantity:
                raise HTTPException(status_code=409, detail="Duplicate trade detected.")
                
    trade_data = trade.model_dump()
    doc_ref = db.collection('trades').document()
    doc_ref.set(trade_data)
    
    trades_docs = db.collection('trades').where(filter=FieldFilter('ticker', '==', trade.ticker)).stream()
    all_trades = [parse_firestore_doc(d) for d in trades_docs]
        
    from . import wash_sales
    wash_sales.detect_wash_sales(all_trades, db)

    # Recompute today's snapshot
    try:
        calculator.compute_and_store_snapshot(db)
    except Exception:
        pass

    trade_data['id'] = doc_ref.id
    return schemas.Trade(**trade_data)

@app.delete("/trades/{trade_id}")
def delete_trade(trade_id: str, db = Depends(get_db)):
    doc_ref = db.collection('trades').document(trade_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Trade not found")
        
    ticker = doc.to_dict().get('ticker')
    doc_ref.delete()
    
    trades_docs = db.collection('trades').where(filter=FieldFilter('ticker', '==', ticker)).stream()
    all_trades = [parse_firestore_doc(d) for d in trades_docs]
        
    from . import wash_sales
    wash_sales.detect_wash_sales(all_trades, db)

    try:
        calculator.compute_and_store_snapshot(db)
    except Exception:
        pass

    return {"message": "Trade deleted successfully"}

@app.put("/trades/{trade_id}", response_model=schemas.Trade)
def update_trade(trade_id: str, trade: schemas.TradeCreate, db = Depends(get_db)):
    doc_ref = db.collection('trades').document(trade_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Trade not found")
        
    old_ticker = doc.to_dict().get('ticker')
    trade_data = trade.model_dump()
    doc_ref.update(trade_data)
    
    from . import wash_sales

    def re_run_ticker(ticker_name):
        tdocs = db.collection('trades').where(filter=FieldFilter('ticker', '==', ticker_name)).stream()
        trlist = [parse_firestore_doc(d) for d in tdocs]
        wash_sales.detect_wash_sales(trlist, db)

    if old_ticker and old_ticker != trade.ticker:
        re_run_ticker(old_ticker)
        
    re_run_ticker(trade.ticker)

    try:
        calculator.compute_and_store_snapshot(db)
    except Exception:
        pass

    trade_data['id'] = trade_id
    if hasattr(trade_data['date'], 'replace'):
        trade_data['date'] = trade_data['date'].replace(tzinfo=None)
    return schemas.Trade(**trade_data)


# ── Asset / Theme Management ──────────────────────────────────────────

@app.get("/assets", response_model=list[schemas.Asset])
def list_assets(db=Depends(get_db)):
    docs = db.collection('asset_prices').stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        if 'last_updated' in d and hasattr(d['last_updated'], 'replace'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None)
        results.append(schemas.Asset(**d))
    results.sort(key=lambda a: a.ticker)
    return results


@app.get("/assets/themes")
def list_themes(db=Depends(get_db)):
    docs = db.collection('asset_prices').stream()
    primary_set: set[str] = set()
    secondary_set: set[str] = set()
    for doc in docs:
        d = doc.to_dict()
        if d.get('primary_theme'):
            primary_set.add(d['primary_theme'])
        if d.get('secondary_theme'):
            secondary_set.add(d['secondary_theme'])
    return {
        "primary": sorted(primary_set),
        "secondary": sorted(secondary_set),
    }


@app.post("/assets", response_model=schemas.Asset, status_code=201)
def create_asset(asset: schemas.AssetCreate, db=Depends(get_db)):
    ticker = asset.ticker.upper()
    doc_ref = db.collection('asset_prices').document(ticker)
    if doc_ref.get().exists:
        raise HTTPException(status_code=409, detail=f"Asset '{ticker}' already exists.")
    data = {
        "ticker": ticker,
        "price": asset.price,
        "primary_theme": asset.primary_theme,
        "secondary_theme": asset.secondary_theme,
        "last_updated": datetime.utcnow(),
    }
    doc_ref.set(data)

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

    data['last_updated'] = data['last_updated'].replace(tzinfo=None)
    return schemas.Asset(**data)


@app.put("/assets/{ticker}", response_model=schemas.Asset)
def update_asset(ticker: str, asset: schemas.AssetUpdate, db=Depends(get_db)):
    ticker = ticker.upper()
    doc_ref = db.collection('asset_prices').document(ticker)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found.")

    new_ticker = asset.new_ticker.upper() if asset.new_ticker else None

    # If renaming ticker, create new doc, update trades, delete old doc
    if new_ticker and new_ticker != ticker:
        new_doc_ref = db.collection('asset_prices').document(new_ticker)
        if new_doc_ref.get().exists:
            raise HTTPException(status_code=409, detail=f"Asset '{new_ticker}' already exists.")

        # Copy data to new doc
        old_data = doc.to_dict()
        updates = {k: v for k, v in asset.model_dump().items() if v is not None and k != 'new_ticker'}
        old_data.update(updates)
        old_data['ticker'] = new_ticker
        old_data['last_updated'] = datetime.utcnow()
        new_doc_ref.set(old_data)

        # Update all trades with the old ticker
        trades_docs = db.collection('trades').where(
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

        # Delete old asset doc
        doc_ref.delete()

        d = new_doc_ref.get().to_dict()
        if 'last_updated' in d and hasattr(d['last_updated'], 'replace'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None)
        return schemas.Asset(**d)
    else:
        # Normal update (no rename)
        updates = {k: v for k, v in asset.model_dump().items() if v is not None and k != 'new_ticker'}
        updates['last_updated'] = datetime.utcnow()
        doc_ref.update(updates)
        d = doc_ref.get().to_dict()
        if 'last_updated' in d and hasattr(d['last_updated'], 'replace'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None)
        return schemas.Asset(**d)


@app.delete("/assets/{ticker}")
def delete_asset(ticker: str, db=Depends(get_db)):
    ticker = ticker.upper()
    doc_ref = db.collection('asset_prices').document(ticker)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found.")
    doc_ref.delete()
    return {"message": f"Asset '{ticker}' deleted successfully."}


# ── Theme Management ─────────────────────────────────────────────────

@app.get("/themes/summary")
def themes_summary(db=Depends(get_db)):
    """Return all themes with asset counts."""
    primary: dict[str, int] = {}
    secondary: dict[str, int] = {}
    docs = db.collection('asset_prices').stream()
    for doc in docs:
        d = doc.to_dict()
        pt = d.get('primary_theme')
        st = d.get('secondary_theme')
        if pt:
            primary[pt] = primary.get(pt, 0) + 1
        if st:
            secondary[st] = secondary.get(st, 0) + 1
    return {
        "primary": sorted([{"name": k, "count": v} for k, v in primary.items()], key=lambda x: -x["count"]),
        "secondary": sorted([{"name": k, "count": v} for k, v in secondary.items()], key=lambda x: -x["count"]),
    }


@app.put("/themes/rename")
def rename_theme(body: dict, db=Depends(get_db)):
    """Rename a theme across all assets. Body: {old_name, new_name, field: primary|secondary|both}"""
    old_name = body.get("old_name", "").strip()
    new_name = body.get("new_name", "").strip()
    field = body.get("field", "both")

    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="old_name and new_name are required.")
    if old_name == new_name:
        return {"message": "Names are the same.", "updated": 0}

    docs = db.collection('asset_prices').stream()
    batch = db.batch()
    batch_count = 0
    updated = 0

    for doc in docs:
        d = doc.to_dict()
        changes = {}
        if field in ("primary", "both") and d.get('primary_theme') == old_name:
            changes['primary_theme'] = new_name
        if field in ("secondary", "both") and d.get('secondary_theme') == old_name:
            changes['secondary_theme'] = new_name
        if changes:
            changes['last_updated'] = datetime.utcnow()
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
def combine_themes(body: dict, db=Depends(get_db)):
    """Merge source theme into target. Body: {source, target, field: primary|secondary|both}"""
    source = body.get("source", "").strip()
    target = body.get("target", "").strip()
    field = body.get("field", "both")

    if not source or not target:
        raise HTTPException(status_code=400, detail="source and target are required.")
    if source == target:
        return {"message": "Source and target are the same.", "updated": 0}

    docs = db.collection('asset_prices').stream()
    batch = db.batch()
    batch_count = 0
    updated = 0

    for doc in docs:
        d = doc.to_dict()
        changes = {}
        if field in ("primary", "both") and d.get('primary_theme') == source:
            changes['primary_theme'] = target
        if field in ("secondary", "both") and d.get('secondary_theme') == source:
            changes['secondary_theme'] = target
        if changes:
            changes['last_updated'] = datetime.utcnow()
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
def delete_theme(name: str, field: str = "both", db=Depends(get_db)):
    """Remove a theme from all assets (sets to empty string)."""
    docs = db.collection('asset_prices').stream()
    batch = db.batch()
    batch_count = 0
    updated = 0

    for doc in docs:
        d = doc.to_dict()
        changes = {}
        if field in ("primary", "both") and d.get('primary_theme') == name:
            changes['primary_theme'] = ""
        if field in ("secondary", "both") and d.get('secondary_theme') == name:
            changes['secondary_theme'] = ""
        if changes:
            changes['last_updated'] = datetime.utcnow()
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


# ── Price Refresh (Yahoo Finance) ─────────────────────────────────────

@app.post("/assets/refresh-prices")
def refresh_prices():
    """Manual trigger for price refresh (uses shared _run_price_refresh)."""
    result = _run_price_refresh()
    return {
        "message": f"Updated {result['updated']} prices, {len(result['failed'])} failed.",
        "updated": result["updated"],
        "failed": result["failed"],
    }


@app.get("/assets/refresh-status")
def refresh_status(db=Depends(get_db)):
    """Return auto-refresh schedule info and last refresh timestamp."""
    # Last refresh
    latest = None
    docs = db.collection('asset_prices').stream()
    for doc in docs:
        d = doc.to_dict()
        lu = d.get('last_updated')
        if lu:
            if hasattr(lu, 'replace'):
                lu = lu.replace(tzinfo=None)
            if latest is None or lu > latest:
                latest = lu

    # Next scheduled run
    next_run = None
    if scheduler and scheduler.get_job("daily_price_refresh"):
        job = scheduler.get_job("daily_price_refresh")
        if job.next_run_time:
            next_run = job.next_run_time.isoformat()

    return {
        "last_refresh": (latest.isoformat() + "Z") if latest else None,
        "next_scheduled": next_run,
        "schedule": "Weekdays at 5:30 PM ET (after market close)",
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
def portfolio_history(period: str = "1y", db=Depends(get_db)):
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

    # Read from portfolio_snapshots collection — sorted by date
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
def theme_baskets(period: str = "1y", db=Depends(get_db)):
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

    # Load assets grouped by primary theme
    assets_docs = db.collection('asset_prices').stream()
    theme_tickers: dict[str, list[str]] = defaultdict(list)
    for doc in assets_docs:
        d = doc.to_dict()
        theme = d.get('primary_theme')
        ticker = d.get('ticker')
        if theme and ticker:
            theme_tickers[theme].append(ticker)

    # Load price_series for all tickers
    all_tickers = set()
    for tickers_list in theme_tickers.values():
        all_tickers.update(tickers_list)

    prices: dict[str, dict[str, float]] = {}  # ticker -> {date: close}
    for ticker in all_tickers:
        doc = db.collection('price_series').document(ticker).get()
        if doc.exists:
            d = doc.to_dict()
            prices[ticker] = d.get('prices', {})

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


# ── CSV Export (Trades) ───────────────────────────────────────────────

@app.get("/trades/export-csv")
def export_trades_csv(db=Depends(get_db)):
    """Export all trades as a CSV file for tax or analytics purposes."""
    from fastapi.responses import StreamingResponse
    import csv, io

    docs = db.collection('trades').stream()
    trades = []
    for doc in docs:
        d = doc.to_dict()
        if 'date' in d and hasattr(d['date'], 'strftime'):
            d['date'] = d['date'].strftime('%Y-%m-%d')
        if 'expiration_date' in d and d.get('expiration_date') and hasattr(d['expiration_date'], 'strftime'):
            d['expiration_date'] = d['expiration_date'].strftime('%Y-%m-%d')
        trades.append(d)

    trades.sort(key=lambda t: t.get('date', ''))

    # Fetch asset themes to include in export
    asset_data = {}
    for doc in db.collection('asset_prices').stream():
        ad = doc.to_dict()
        asset_data[ad.get('ticker')] = {
            'primary_theme': ad.get('primary_theme', ''),
            'secondary_theme': ad.get('secondary_theme', ''),
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
def export_backup(db=Depends(get_db)):
    """Export all trades and asset data as a single JSON backup file."""

    # Export trades
    trades = []
    for doc in db.collection('trades').stream():
        d = doc.to_dict()
        # Convert datetime to ISO string for JSON serialization
        if 'date' in d and hasattr(d['date'], 'isoformat'):
            d['date'] = d['date'].replace(tzinfo=None).isoformat()
        if 'expiration_date' in d and d['expiration_date'] and hasattr(d['expiration_date'], 'isoformat'):
            d['expiration_date'] = d['expiration_date'].replace(tzinfo=None).isoformat()
        d['_doc_id'] = doc.id
        trades.append(d)

    # Export assets
    assets = []
    for doc in db.collection('asset_prices').stream():
        d = doc.to_dict()
        if 'last_updated' in d and d['last_updated'] and hasattr(d['last_updated'], 'isoformat'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None).isoformat()
        d['_doc_id'] = doc.id
        assets.append(d)

    backup = {
        "version": 1,
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
async def restore_backup(file: UploadFile = File(...), db=Depends(get_db)):
    """Restore trades and assets from a JSON backup file. Replaces all existing data."""
    try:
        content = await file.read()
        backup = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid backup file: {e}")

    if backup.get("version") != 1:
        raise HTTPException(status_code=400, detail="Unsupported backup version.")

    trades_data = backup.get("trades", [])
    assets_data = backup.get("assets", [])

    # --- Delete existing data ---
    # Delete all trades
    existing_trades = db.collection('trades').stream()
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

    # Delete all assets
    existing_assets = db.collection('asset_prices').stream()
    batch = db.batch()
    batch_count = 0
    deleted_assets = 0
    for doc in existing_assets:
        batch.delete(doc.reference)
        batch_count += 1
        deleted_assets += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count > 0:
        batch.commit()

    # --- Restore trades ---
    batch = db.batch()
    batch_count = 0
    restored_trades = 0
    for t in trades_data:
        doc_id = t.pop('_doc_id', None)
        # Convert ISO date strings back to datetime
        if 'date' in t and isinstance(t['date'], str):
            t['date'] = datetime.fromisoformat(t['date'])
        if 'expiration_date' in t and isinstance(t.get('expiration_date'), str):
            t['expiration_date'] = datetime.fromisoformat(t['expiration_date'])

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

    # --- Restore assets ---
    batch = db.batch()
    batch_count = 0
    restored_assets = 0
    for a in assets_data:
        doc_id = a.pop('_doc_id', None)
        if 'last_updated' in a and isinstance(a.get('last_updated'), str):
            a['last_updated'] = datetime.fromisoformat(a['last_updated'])

        doc_ref = db.collection('asset_prices').document(doc_id or a.get('ticker', ''))
        batch.set(doc_ref, a)
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
