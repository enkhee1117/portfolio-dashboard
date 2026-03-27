from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from . import schemas, database, importer, calculator
import os
import shutil
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
async def import_excel(file: UploadFile = File(...), db = Depends(get_db)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    
    try:
        result = importer.import_data(db, file_location)
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
        from google.cloud.firestore_v1.base_query import FieldFilter
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
    
    from google.cloud.firestore_v1.base_query import FieldFilter
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
    from google.cloud.firestore_v1.base_query import FieldFilter

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
