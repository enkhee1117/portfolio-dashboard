"""Admin endpoints — migration, backup/restore, CSV export."""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import Request
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime
import json
import csv
import io
import logging

from ..auth import get_current_user
from ..deps import get_db
from .. import schemas, calculator

logger = logging.getLogger("portfolio")

router = APIRouter(tags=["admin"])


@router.post("/admin/migrate-to-user")
def migrate_to_user(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """One-time migration: assign unowned trades and themes to current user."""

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

    # 2. Copy themes from asset_prices to user's asset_themes
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

    # 4. Recompute snapshot
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


@router.get("/trades/export-csv")
def export_trades_csv(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Export user's trades as a CSV file."""

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
            t.get('date', ''), ticker, t.get('side', ''), qty, price,
            round(qty * price, 2), t.get('type', 'Equity'), t.get('fees', 0),
            t.get('currency', 'USD'), themes.get('primary_theme', ''),
            themes.get('secondary_theme', ''), 'Yes' if t.get('is_wash_sale') else '',
        ])

    output.seek(0)
    filename = f"trades_export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backup/export")
def export_backup(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Export user's trades and asset themes as JSON backup."""

    trades = []
    for doc in db.collection('trades').where(filter=FieldFilter('user_id', '==', user_id)).stream():
        d = doc.to_dict()
        if 'date' in d and hasattr(d['date'], 'isoformat'):
            d['date'] = d['date'].replace(tzinfo=None).isoformat()
        if 'expiration_date' in d and d['expiration_date'] and hasattr(d['expiration_date'], 'isoformat'):
            d['expiration_date'] = d['expiration_date'].replace(tzinfo=None).isoformat()
        d['_doc_id'] = doc.id
        trades.append(d)

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


@router.post("/backup/restore")
async def restore_backup(request: Request, file: UploadFile = File(...), db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Restore user's trades and asset themes from JSON backup."""

    try:
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Backup file too large. Maximum 10MB.")
        backup = json.loads(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid backup file: {e}")

    version = backup.get("version", 1)
    if version not in (1, 2):
        raise HTTPException(status_code=400, detail="Unsupported backup version.")

    trades_data = backup.get("trades", [])
    assets_data = backup.get("assets", [])

    # Validate before deleting
    if not isinstance(trades_data, list) or not isinstance(assets_data, list):
        raise HTTPException(status_code=400, detail="Invalid backup format: trades and assets must be arrays.")
    for i, t in enumerate(trades_data):
        if not isinstance(t, dict) or "ticker" not in t or "side" not in t:
            raise HTTPException(status_code=400, detail=f"Invalid trade at index {i}: missing required fields.")
        if "date" not in t:
            raise HTTPException(status_code=400, detail=f"Invalid trade at index {i}: missing date.")
    for i, a in enumerate(assets_data):
        if not isinstance(a, dict):
            raise HTTPException(status_code=400, detail=f"Invalid asset at index {i}: not an object.")

    # Delete user's existing data
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

    # Restore trades
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

    # Restore assets
    batch = db.batch()
    batch_count = 0
    restored_assets = 0
    for a in assets_data:
        doc_id = a.pop('_doc_id', None)
        a.pop('last_updated', None)
        ticker = doc_id or a.get('ticker', '')
        if not ticker:
            continue

        if version == 1:
            theme_data = {
                'ticker': ticker,
                'primary': a.get('primary_theme', ''),
                'secondary': a.get('secondary_theme', ''),
            }
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
