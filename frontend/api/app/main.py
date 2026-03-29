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

    logger.info(f"Price refresh complete: {updated} updated, {len(failed)} failed.")
    return {"updated": updated, "failed": failed}


def _scheduled_refresh():
    """Wrapper for the scheduler — logs and catches all errors."""
    logger.info("Scheduled price refresh starting...")
    try:
        result = _run_price_refresh()
        logger.info(f"Scheduled refresh result: {result['updated']} updated, {len(result['failed'])} failed")
    except Exception as e:
        logger.error(f"Scheduled refresh error: {e}")


# APScheduler — runs daily at 5:30 PM US/Eastern (after market close)
scheduler = None

@asynccontextmanager
async def lifespan(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    global scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _scheduled_refresh,
        CronTrigger(hour=17, minute=30, timezone="US/Eastern"),
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
    data = calculator.calculate_portfolio(db)
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
        "schedule": "Daily at 5:30 PM ET (after market close)",
    }


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
