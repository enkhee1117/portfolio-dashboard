from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from . import schemas, database, importer, calculator
from google.cloud.firestore_v1.base_query import FieldFilter
import os
import shutil
import json
from datetime import datetime

app = FastAPI()

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
    updates = {k: v for k, v in asset.model_dump().items() if v is not None}
    updates['last_updated'] = datetime.utcnow()
    doc_ref.update(updates)
    # Return the full updated document
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
def refresh_prices(db=Depends(get_db)):
    """Fetch latest closing prices from Yahoo Finance for all assets and update Firestore."""
    import yfinance as yf

    docs = db.collection('asset_prices').stream()
    tickers = []
    for doc in docs:
        d = doc.to_dict()
        if d.get('ticker'):
            tickers.append(d['ticker'])

    if not tickers:
        return {"message": "No assets to update.", "updated": 0, "failed": []}

    # yfinance handles batching internally — one call for all tickers
    try:
        data = yf.download(tickers, period='1d', progress=False)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Yahoo Finance error: {e}")

    if data.empty:
        return {"message": "No price data returned.", "updated": 0, "failed": tickers}

    # Handle single vs multi-ticker response format
    is_multi = isinstance(data.columns, __import__('pandas').MultiIndex)

    updated = 0
    failed = []
    batch = db.batch()
    batch_count = 0

    for ticker in tickers:
        try:
            if is_multi:
                close_price = float(data['Close'][ticker].iloc[-1])
            else:
                # Single ticker — columns are just 'Close', 'Open', etc.
                close_price = float(data['Close'].iloc[-1])

            if close_price > 0:
                doc_ref = db.collection('asset_prices').document(ticker)
                batch.update(doc_ref, {
                    "price": round(close_price, 2),
                    "last_updated": datetime.utcnow(),
                })
                batch_count += 1
                updated += 1

                if batch_count >= 400:
                    batch.commit()
                    batch = db.batch()
                    batch_count = 0
            else:
                failed.append(ticker)
        except Exception:
            failed.append(ticker)

    if batch_count > 0:
        batch.commit()

    return {
        "message": f"Updated {updated} prices, {len(failed)} failed.",
        "updated": updated,
        "failed": failed,
    }


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
