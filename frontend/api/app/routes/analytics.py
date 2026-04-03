"""Analytics endpoints — theme basket comparison."""
from fastapi import APIRouter, Depends
from datetime import datetime, timedelta
from collections import defaultdict

from ..auth import get_current_user

router = APIRouter(tags=["analytics"])


@router.get("/analytics/theme-baskets")
def theme_baskets(period: str = "1y", user_id: str = Depends(get_current_user)):
    """Compare theme basket performance. Each basket starts at $10,000."""
    from ..main import get_db
    db = get_db()

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

    # Load user's assets grouped by primary theme
    theme_tickers: dict[str, list[str]] = defaultdict(list)
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        d = doc.to_dict()
        theme = d.get('primary')
        ticker = doc.id
        if theme and ticker:
            theme_tickers[theme].append(ticker)

    # Batch-read price_series
    all_tickers = set()
    for tickers_list in theme_tickers.values():
        all_tickers.update(tickers_list)

    prices: dict[str, dict[str, float]] = {}
    if all_tickers:
        price_refs = [db.collection('price_series').document(t) for t in all_tickers]
        for doc in db.get_all(price_refs):
            if doc.exists:
                d = doc.to_dict()
                prices[doc.id] = d.get('prices', {})

    # Collect dates within period
    all_dates = sorted(d for tp in prices.values() for d in tp if d >= start_str)
    all_dates = sorted(set(all_dates))

    if not all_dates:
        return {"themes": []}

    # Sample weekly
    sampled_dates = []
    last_added = None
    for d in all_dates:
        if last_added is None or (datetime.strptime(d, '%Y-%m-%d') - datetime.strptime(last_added, '%Y-%m-%d')).days >= 5:
            sampled_dates.append(d)
            last_added = d
    if all_dates[-1] not in sampled_dates:
        sampled_dates.append(all_dates[-1])

    result_themes = []

    for theme, tickers_list in sorted(theme_tickers.items()):
        valid_tickers = []
        for ticker in tickers_list:
            if ticker in prices:
                tp = prices[ticker]
                start_price = None
                for d in sampled_dates[:10]:
                    if d in tp and tp[d] > 0:
                        start_price = tp[d]
                        break
                if start_price:
                    valid_tickers.append((ticker, start_price))

        if not valid_tickers:
            continue

        per_stock = INITIAL_VALUE / len(valid_tickers)
        holdings = [(ticker, per_stock / start_price) for ticker, start_price in valid_tickers]

        data_points = []
        for date_str in sampled_dates:
            basket_val = 0.0
            for ticker, shares in holdings:
                tp = prices.get(ticker, {})
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

    result_themes.sort(key=lambda t: t["return_pct"], reverse=True)
    return {"themes": result_themes}
