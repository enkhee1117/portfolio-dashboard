"""Asset and theme management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import Request
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime
import threading
import logging

from ..auth import get_current_user, get_user_tickers, normalize_theme
from ..deps import get_db
from .. import schemas

logger = logging.getLogger("portfolio")

router = APIRouter(tags=["assets"])


def _fetch_live_price(ticker: str) -> float:
    try:
        import yfinance as yf
        data = yf.download(ticker, period='1d', progress=False)
        if not data.empty:
            return round(float(data['Close'].iloc[-1]), 2)
    except Exception:
        pass
    return 0.0


# ── Asset CRUD ───────────────────────────────────────────────────────

@router.get("/assets", response_model=list[schemas.Asset])
def list_assets(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """List assets for the authenticated user."""
    user_themes: dict[str, dict] = {}
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        user_themes[doc.id] = doc.to_dict()

    if not user_themes:
        return []

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


@router.get("/assets/themes")
def list_themes(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    primary_set: set[str] = set()
    secondary_set: set[str] = set()
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        d = doc.to_dict()
        if d.get('primary'): primary_set.add(d['primary'])
        if d.get('secondary'): secondary_set.add(d['secondary'])
    return {"primary": sorted(primary_set), "secondary": sorted(secondary_set)}


@router.post("/assets", response_model=schemas.Asset, status_code=201)
def create_asset(asset: schemas.AssetCreate, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    ticker = asset.ticker.upper()
    user_theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
    user_tickers_set = get_user_tickers(db, user_id)
    if ticker in user_tickers_set:
        raise HTTPException(status_code=409, detail=f"Asset '{ticker}' already exists.")

    shared_ref = db.collection('asset_prices').document(ticker)
    if not shared_ref.get().exists:
        price = _fetch_live_price(ticker) or asset.price
        shared_ref.set({"ticker": ticker, "price": price, "last_updated": datetime.utcnow()})

    user_theme_ref.set({
        "ticker": ticker,
        "primary": normalize_theme(asset.primary_theme),
        "secondary": normalize_theme(asset.secondary_theme),
    })

    try:
        from ..main import fetch_and_store_ticker_prices
        threading.Thread(target=fetch_and_store_ticker_prices, args=(db, ticker), daemon=True).start()
    except Exception:
        pass

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


@router.put("/assets/{ticker}", response_model=schemas.Asset)
def update_asset(ticker: str, asset: schemas.AssetUpdate, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    ticker = ticker.upper()
    user_tickers_set = get_user_tickers(db, user_id)
    if ticker not in user_tickers_set:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found.")

    new_ticker = asset.new_ticker.upper() if asset.new_ticker else None

    if new_ticker and new_ticker != ticker:
        if new_ticker in user_tickers_set:
            raise HTTPException(status_code=409, detail=f"Asset '{new_ticker}' already exists.")

        trades_docs = db.collection('trades').where(
            filter=FieldFilter('user_id', '==', user_id)
        ).where(filter=FieldFilter('ticker', '==', ticker)).stream()
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

        old_theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
        old_theme_doc = old_theme_ref.get()
        theme_data = old_theme_doc.to_dict() if old_theme_doc.exists else {}
        if asset.primary_theme is not None:
            theme_data['primary'] = normalize_theme(asset.primary_theme)
        if asset.secondary_theme is not None:
            theme_data['secondary'] = normalize_theme(asset.secondary_theme)
        theme_data['ticker'] = new_ticker
        db.collection('users').document(user_id).collection('asset_themes').document(new_ticker).set(theme_data)
        if old_theme_doc.exists:
            old_theme_ref.delete()

        new_shared_ref = db.collection('asset_prices').document(new_ticker)
        if not new_shared_ref.get().exists:
            old_shared = db.collection('asset_prices').document(ticker).get()
            seed = old_shared.to_dict() if old_shared.exists else {}
            seed['ticker'] = new_ticker
            seed['last_updated'] = datetime.utcnow()
            new_shared_ref.set(seed)

        price_data = new_shared_ref.get().to_dict() or {}
        d = {
            "ticker": new_ticker, "price": price_data.get("price", 0.0),
            "primary_theme": theme_data.get("primary", ""), "secondary_theme": theme_data.get("secondary", ""),
            "last_updated": price_data.get("last_updated"), "previous_close": price_data.get("previous_close"),
            "daily_change": price_data.get("daily_change"), "daily_change_pct": price_data.get("daily_change_pct"),
            "rsi": price_data.get("rsi"),
        }
        if d['last_updated'] and hasattr(d['last_updated'], 'replace'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None)
        return schemas.Asset(**d)
    else:
        theme_updates = {}
        if asset.primary_theme is not None:
            theme_updates['primary'] = normalize_theme(asset.primary_theme)
        if asset.secondary_theme is not None:
            theme_updates['secondary'] = normalize_theme(asset.secondary_theme)
        if theme_updates:
            theme_updates['ticker'] = ticker
            db.collection('users').document(user_id).collection('asset_themes').document(ticker).set(theme_updates, merge=True)

        price_doc = db.collection('asset_prices').document(ticker).get()
        price_data = price_doc.to_dict() if price_doc.exists else {}
        theme_doc = db.collection('users').document(user_id).collection('asset_themes').document(ticker).get()
        themes = theme_doc.to_dict() if theme_doc.exists else {}
        d = {
            "ticker": ticker, "price": price_data.get("price", 0.0),
            "primary_theme": themes.get("primary") or price_data.get("primary_theme", ""),
            "secondary_theme": themes.get("secondary") or price_data.get("secondary_theme", ""),
            "last_updated": price_data.get("last_updated"), "previous_close": price_data.get("previous_close"),
            "daily_change": price_data.get("daily_change"), "daily_change_pct": price_data.get("daily_change_pct"),
            "rsi": price_data.get("rsi"),
        }
        if d['last_updated'] and hasattr(d['last_updated'], 'replace'):
            d['last_updated'] = d['last_updated'].replace(tzinfo=None)
        return schemas.Asset(**d)


@router.delete("/assets/{ticker}")
def delete_asset(ticker: str, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Remove asset from user's list. Does NOT delete shared price data."""
    ticker = ticker.upper()
    theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker)
    if not theme_ref.get().exists:
        raise HTTPException(status_code=404, detail=f"Asset '{ticker}' not found in your assets.")
    theme_ref.delete()
    return {"message": f"Asset '{ticker}' removed from your portfolio."}


# ── Theme Management ─────────────────────────────────────────────────

@router.get("/themes/summary")
def themes_summary(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    primary: dict[str, int] = {}
    secondary: dict[str, int] = {}
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        d = doc.to_dict()
        pt = d.get('primary')
        st = d.get('secondary')
        if pt: primary[pt] = primary.get(pt, 0) + 1
        if st: secondary[st] = secondary.get(st, 0) + 1
    return {
        "primary": sorted([{"name": k, "count": v} for k, v in primary.items()], key=lambda x: -x["count"]),
        "secondary": sorted([{"name": k, "count": v} for k, v in secondary.items()], key=lambda x: -x["count"]),
    }


@router.put("/themes/rename")
def rename_theme(body: dict, db=Depends(get_db), user_id: str = Depends(get_current_user)):
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


@router.post("/themes/combine")
def combine_themes(body: dict, db=Depends(get_db), user_id: str = Depends(get_current_user)):
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


@router.delete("/themes/{name}")
def delete_theme(name: str, field: str = "both", db=Depends(get_db), user_id: str = Depends(get_current_user)):
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


# ── Price Refresh ────────────────────────────────────────────────────

@router.post("/assets/refresh-prices")
def refresh_prices(request: Request):
    """Manual trigger for price refresh."""
    from ..main import _run_price_refresh, compute_and_store_rsi, limiter
    result = _run_price_refresh()
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


@router.get("/assets/refresh-status")
def refresh_status(db=Depends(get_db)):
    """Return refresh schedule and last update time."""
    latest = None
    try:
        docs = db.collection('asset_prices').order_by('last_updated', direction='DESCENDING').limit(1).stream()
        for doc in docs:
            lu = doc.to_dict().get('last_updated')
            if lu and hasattr(lu, 'replace'):
                latest = lu.replace(tzinfo=None)
    except Exception:
        pass

    from ..main import scheduler
    next_run = None
    if scheduler and scheduler.get_job("daily_price_refresh"):
        job = scheduler.get_job("daily_price_refresh")
        if job.next_run_time:
            next_run = job.next_run_time.isoformat()

    return {
        "last_refresh": (latest.isoformat() + "Z") if latest else None,
        "next_scheduled": next_run,
        "schedule": "Intraday: on-demand (if >2h stale during market hours). End-of-day: Vercel Cron at 5:30 PM ET weekdays.",
    }
