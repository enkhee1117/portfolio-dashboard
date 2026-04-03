"""Trade endpoints — CRUD, wash sales recheck."""
from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import Request
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime
from typing import Optional
import logging

from ..auth import get_current_user
from ..deps import get_db
from .. import schemas, calculator

logger = logging.getLogger("portfolio")

router = APIRouter(tags=["trades"])


def parse_firestore_doc(doc) -> schemas.Trade:
    d = doc.to_dict()
    d['id'] = doc.id
    if 'date' in d and hasattr(d['date'], 'replace'):
        d['date'] = d['date'].replace(tzinfo=None)
    return schemas.Trade(**d)


def _fetch_live_price(ticker: str) -> float:
    """Quick single-ticker price lookup from Yahoo Finance."""
    try:
        import yfinance as yf
        data = yf.download(ticker, period='1d', progress=False)
        if not data.empty:
            return round(float(data['Close'].iloc[-1]), 2)
    except Exception:
        pass
    return 0.0


def _ensure_asset_price(db, ticker: str):
    """Ensure shared asset_prices entry exists with a live price."""
    shared_ref = db.collection('asset_prices').document(ticker)
    doc = shared_ref.get()
    if not doc.exists:
        price = _fetch_live_price(ticker)
        shared_ref.set({'ticker': ticker, 'price': price, 'last_updated': datetime.utcnow()})
    elif doc.to_dict().get('price', 0) == 0:
        price = _fetch_live_price(ticker)
        if price > 0:
            shared_ref.update({'price': price, 'last_updated': datetime.utcnow()})


def _invalidate_snapshot_cache(db, user_id: str):
    """Delete today's cached snapshot so next GET /portfolio recomputes."""
    today = datetime.utcnow().strftime('%Y-%m-%d')
    try:
        if user_id != "anonymous":
            db.collection('users').document(user_id).collection('portfolio_snapshots').document(today).delete()
        else:
            db.collection('portfolio_snapshots').document(today).delete()
    except Exception:
        pass


@router.get("/trades", response_model=list[schemas.Trade])
def get_trades(
    limit: int = 50,
    offset: int = 0,
    ticker: Optional[str] = None,
    db=Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """List trades with pagination. Pass limit=0 for all trades."""
    query = db.collection('trades')
    if user_id != "anonymous":
        query = query.where(filter=FieldFilter('user_id', '==', user_id))
    if ticker:
        query = query.where(filter=FieldFilter('ticker', '==', ticker.upper()))

    docs = query.stream()
    result = [parse_firestore_doc(d) for d in docs]
    result.sort(key=lambda x: x.date, reverse=True)

    total = len(result)
    if limit > 0:
        result = result[offset:offset + limit]
    return result


@router.post("/trades/manual", response_model=schemas.Trade)
def create_trade(request: Request, trade: schemas.TradeCreate, force: bool = False, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    from ..main import limiter  # Rate limiter from main app
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

    # Auto-register ticker
    ticker_upper = trade.ticker
    theme_ref = db.collection('users').document(user_id).collection('asset_themes').document(ticker_upper)
    if not theme_ref.get().exists:
        theme_ref.set({'ticker': ticker_upper, 'primary': '', 'secondary': ''})
        _ensure_asset_price(db, ticker_upper)

    # Delta-update snapshot
    if not calculator.apply_trade_delta(db, user_id, trade.ticker):
        _invalidate_snapshot_cache(db, user_id)

    trade_data['id'] = doc_ref.id
    return schemas.Trade(**trade_data)


@router.delete("/trades/{trade_id}")
def delete_trade(trade_id: str, db=Depends(get_db), user_id: str = Depends(get_current_user)):
    doc_ref = db.collection('trades').document(trade_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Trade not found")

    trade_data = doc.to_dict()
    if user_id != "anonymous" and trade_data.get('user_id') and trade_data['user_id'] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this trade")

    ticker = trade_data.get('ticker')
    doc_ref.delete()

    if not calculator.apply_trade_delta(db, user_id, ticker):
        _invalidate_snapshot_cache(db, user_id)

    return {"message": "Trade deleted successfully"}


@router.put("/trades/{trade_id}", response_model=schemas.Trade)
def update_trade(trade_id: str, trade: schemas.TradeCreate, db=Depends(get_db), user_id: str = Depends(get_current_user)):
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


@router.post("/trades/recheck-wash-sales")
def recheck_wash_sales(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Rerun wash sale detection across all user's trades."""
    from .. import wash_sales

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
