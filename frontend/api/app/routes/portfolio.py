"""Portfolio endpoints — positions, history, recompute, backfill."""
from fastapi import APIRouter, Depends, HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime, timedelta
from typing import Optional
import logging

from ..auth import get_current_user
from ..deps import get_db
from .. import schemas, calculator

logger = logging.getLogger("portfolio")

router = APIRouter(tags=["portfolio"])

# Track in-flight refresh to avoid duplicate background refreshes
_refresh_in_progress: set[str] = set()


@router.get("/portfolio", response_model=list[schemas.PortfolioSnapshot])
def get_portfolio(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    data = calculator.get_cached_portfolio(db, user_id=user_id)

    # Stale-while-revalidate: if prices are >2 hours old and market is open,
    # trigger a background refresh
    from ..main import _is_market_open, _intraday_price_refresh
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


@router.post("/portfolio/recompute")
def recompute_portfolio(db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Manually recompute portfolio snapshot."""
    snapshot = calculator.compute_and_store_snapshot(db, user_id=user_id)
    return {
        "message": f"Portfolio recomputed: {len(snapshot.get('positions', []))} positions, ${snapshot.get('total_value', 0):,.0f} total.",
        "positions": len(snapshot.get("positions", [])),
        "total_value": snapshot.get("total_value", 0),
    }


@router.get("/portfolio/history")
def portfolio_history(period: str = "1y", db=Depends(get_db), user_id: str = Depends(get_current_user)):
    """Read precomputed portfolio snapshots for the chart."""
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

    if user_id != "anonymous":
        docs = db.collection('users').document(user_id).collection('portfolio_snapshots').stream()
    else:
        docs = db.collection('portfolio_snapshots').stream()
    result = []
    for doc in docs:
        d = doc.to_dict()
        date_str = d.get('date', doc.id)
        if date_str >= start_str:
            result.append({"date": date_str, "value": round(d.get('total_value', 0), 2)})

    result.sort(key=lambda x: x['date'])
    return result


@router.post("/portfolio/backfill-history")
def backfill_history(db=Depends(get_db)):
    """Backfill price_history with historical prices for all traded tickers."""
    import yfinance as yf
    import pandas as pd
    import math
    from ..main import get_last_trading_day, fetch_and_store_ticker_prices, get_tickers_last_price_date

    docs = db.collection('trades').stream()
    tickers = sorted(set(d.to_dict().get('ticker') for d in docs if d.to_dict().get('ticker')))

    if not tickers:
        return {"message": "No tickers found in trades.", "updated": 0, "snapshots": 0, "tickers": 0, "failed": []}

    last_dates = get_tickers_last_price_date(db)
    last_trading_day = get_last_trading_day()

    tickers_to_fetch = []
    for ticker in tickers:
        last_date = last_dates.get(ticker)
        if not last_date or last_date < last_trading_day:
            tickers_to_fetch.append(ticker)

    if not tickers_to_fetch:
        return {"message": "All tickers up to date.", "updated": 0, "snapshots": 0, "tickers": len(tickers), "failed": []}

    CHUNK_SIZE = 50
    updated = 0
    failed_tickers = []

    for i in range(0, len(tickers_to_fetch), CHUNK_SIZE):
        chunk = tickers_to_fetch[i:i + CHUNK_SIZE]
        try:
            start = last_dates.get(chunk[0], "2020-01-01")
            for t in chunk:
                t_start = last_dates.get(t, "2020-01-01")
                if t_start < start:
                    start = t_start

            data = yf.download(chunk, start=start, progress=False)
            if data.empty:
                failed_tickers.extend(chunk)
                continue

            is_multi = isinstance(data.columns, pd.MultiIndex)
            now = datetime.utcnow()

            for ticker in chunk:
                try:
                    if is_multi:
                        close_series = data['Close'][ticker].dropna()
                    else:
                        close_series = data['Close'].dropna()

                    if len(close_series) < 1:
                        failed_tickers.append(ticker)
                        continue

                    prices_map = {}
                    for idx, price in close_series.items():
                        if not math.isnan(price) and price > 0:
                            date_str = idx.strftime('%Y-%m-%d')
                            prices_map[date_str] = round(float(price), 2)

                    if prices_map:
                        db.collection('price_series').document(ticker).set({
                            "ticker": ticker,
                            "last_updated": now,
                            **{f"prices.{k}": v for k, v in prices_map.items()},
                        }, merge=True)

                        batch = db.batch()
                        batch_count = 0
                        for date_str, close_price in prices_map.items():
                            doc_id = f"{ticker}_{date_str}"
                            ref = db.collection('price_history').document(doc_id)
                            batch.set(ref, {
                                "ticker": ticker,
                                "date": date_str,
                                "close": close_price,
                                "open": close_price,
                                "high": close_price,
                                "low": close_price,
                            }, merge=True)
                            batch_count += 1
                            if batch_count >= 400:
                                batch.commit()
                                batch = db.batch()
                                batch_count = 0
                        if batch_count > 0:
                            batch.commit()

                        updated += 1
                except Exception:
                    failed_tickers.append(ticker)
        except Exception:
            failed_tickers.extend(chunk)

    # Backfill portfolio snapshots from price_series
    snapshots_written = 0
    try:
        all_trades = []
        for doc in db.collection('trades').stream():
            d = doc.to_dict()
            if 'date' in d and hasattr(d['date'], 'replace'):
                d['date'] = d['date'].replace(tzinfo=None)
            d['id'] = doc.id
            all_trades.append(d)
        all_trades.sort(key=lambda t: t.get('date', datetime.min))

        price_series_data = {}
        for doc in db.collection('price_series').stream():
            d = doc.to_dict()
            price_series_data[doc.id] = d.get('prices', {})

        all_dates = set()
        for prices in price_series_data.values():
            all_dates.update(prices.keys())
        all_dates = sorted(all_dates)

        sampled_dates = []
        last_added = None
        for d in all_dates:
            if last_added is None or (datetime.strptime(d, '%Y-%m-%d') - datetime.strptime(last_added, '%Y-%m-%d')).days >= 7:
                sampled_dates.append(d)
                last_added = d

        from collections import defaultdict

        for snap_date in sampled_dates:
            positions = defaultdict(lambda: {"quantity": 0.0, "cost_basis": 0.0})
            for trade in all_trades:
                trade_date = trade.get('date')
                if trade_date and trade_date.strftime('%Y-%m-%d') <= snap_date:
                    ticker = trade.get('ticker')
                    qty = trade.get('quantity', 0)
                    price = trade.get('price', 0)
                    if trade.get('side') == 'Buy':
                        old_qty = positions[ticker]["quantity"]
                        new_qty = old_qty + qty
                        if new_qty > 0:
                            positions[ticker]["cost_basis"] = ((old_qty * positions[ticker]["cost_basis"]) + (qty * price)) / new_qty
                        positions[ticker]["quantity"] = new_qty
                    elif trade.get('side') == 'Sell':
                        positions[ticker]["quantity"] -= qty
                        if abs(positions[ticker]["quantity"]) < 0.0001:
                            positions[ticker]["quantity"] = 0.0
                            positions[ticker]["cost_basis"] = 0.0

            total_value = 0.0
            for ticker, pos in positions.items():
                if pos["quantity"] > 0:
                    price = price_series_data.get(ticker, {}).get(snap_date, 0)
                    if not price:
                        for i in range(1, 8):
                            prev = (datetime.strptime(snap_date, '%Y-%m-%d') - timedelta(days=i)).strftime('%Y-%m-%d')
                            price = price_series_data.get(ticker, {}).get(prev, 0)
                            if price:
                                break
                    total_value += pos["quantity"] * price

            snapshot = {
                "date": snap_date,
                "total_value": round(total_value, 2),
                "positions": [],
                "computed_at": datetime.utcnow(),
            }
            db.collection('portfolio_snapshots').document(snap_date).set(snapshot)
            snapshots_written += 1
    except Exception as e:
        logger.error(f"Snapshot backfill error: {e}")

    return {
        "message": f"Backfill complete. {updated} tickers updated, {snapshots_written} snapshots written.",
        "updated": updated,
        "snapshots": snapshots_written,
        "tickers": len(tickers),
        "failed": failed_tickers,
    }
