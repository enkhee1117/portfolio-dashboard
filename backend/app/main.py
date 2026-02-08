from fastapi import FastAPI, Depends, UploadFile, File
from sqlalchemy.orm import Session
from . import models, schemas, database, importer, calculator
import os
import shutil

# Create tables
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

origins = [
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def read_root():
    return {"message": "Portfolio Tracker API"}

@app.post("/import")
async def import_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    
    try:
        result = importer.import_data(db, file_location)
        count = result.get("added", 0) if result else 0
    finally:
        os.remove(file_location)
        
    return {"message": f"Import successful. Added {count} new trades."}

@app.get("/portfolio", response_model=list[schemas.PortfolioSnapshotBase]) # Schema needs to match dict or use ORM
def get_portfolio(db: Session = Depends(get_db)):
    # Calculate on the fly for now
    data = calculator.calculate_portfolio(db)
    # create default date
    from datetime import datetime
    
    # Map dictionary to schema
    return [
        schemas.PortfolioSnapshotBase(
            date=datetime.utcnow(),
            ticker=item["ticker"],
            quantity=item["quantity"],
            average_price=item["average_price"],
            current_price=item["current_price"],
            market_value=item["market_value"],
            unrealized_pnl=item["unrealized_pnl"],
            realized_pnl=item["realized_pnl"],
            primary_theme=item.get("primary_theme"),
            secondary_theme=item.get("secondary_theme")
        )
        for item in data
    ]

@app.get("/trades", response_model=list[schemas.Trade])
def get_trades(db: Session = Depends(get_db)):
    return db.query(models.Trade).order_by(models.Trade.date.desc()).all()

@app.post("/trades/manual", response_model=schemas.Trade)
def create_trade(trade: schemas.TradeCreate, force: bool = False, db: Session = Depends(get_db)):
    # 1. Check for duplicates
    # We check if there is an existing trade with same:
    # Date, Ticker, Side, Price, Quantity
    # Note: Dates might need careful comparison (timezone etc). 
    # Provided trade.date is naive or consistent with DB.
    
    if not force:
        existing = db.query(models.Trade).filter(
            models.Trade.ticker == trade.ticker,
            models.Trade.side == trade.side,
            models.Trade.price == trade.price,
            models.Trade.quantity == trade.quantity
            # Date comparison can be tricky with exact timestamps. 
            # We'll check if absolute difference is small or exact match.
            # For now, exact match on the day/time provided.
        ).all()
        
        for t in existing:
            # Compare dates
            # If trade.date matches t.date exactly?
            if t.date == trade.date:
                 from fastapi import HTTPException
                 raise HTTPException(status_code=409, detail="Duplicate trade detected. Use force=true to proceed.")

    db_trade = models.Trade(**trade.model_dump())
    db.add(db_trade)
    db.commit()
    db.refresh(db_trade)
    
    # Run wash sale detection for this ticker
    # We need to pass ALL trades for this ticker to the detector to be accurate
    # or at least enough history. 
    # Ideally, we should re-run for the specific ticker.
    all_trades = db.query(models.Trade).filter(models.Trade.ticker == db_trade.ticker).all()
    from . import wash_sales
    wash_sales.detect_wash_sales(all_trades)
    db.commit()
    db.refresh(db_trade)
    db.commit()
    db.refresh(db_trade)
    
    return db_trade

@app.delete("/trades/{trade_id}")
def delete_trade(trade_id: int, db: Session = Depends(get_db)):
    base_query = db.query(models.Trade).filter(models.Trade.id == trade_id)
    db_trade = base_query.first()
    if not db_trade:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trade not found")
    
    ticker = db_trade.ticker
    base_query.delete(synchronize_session=False)
    db.commit()
    
    # Re-run wash sale for the affected ticker
    all_trades = db.query(models.Trade).filter(models.Trade.ticker == ticker).all()
    from . import wash_sales
    wash_sales.detect_wash_sales(all_trades)
    db.commit()
    
    return {"message": "Trade deleted successfully"}

@app.put("/trades/{trade_id}", response_model=schemas.Trade)
def update_trade(trade_id: int, trade: schemas.TradeCreate, db: Session = Depends(get_db)):
    db_query = db.query(models.Trade).filter(models.Trade.id == trade_id)
    db_trade = db_query.first()
    if not db_trade:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trade not found")
    
    old_ticker = db_trade.ticker
    
    # Update fields
    update_data = trade.model_dump()
    db_query.update(update_data, synchronize_session=False)
    db.commit()
    db.refresh(db_trade)
    
    # Re-run wash sales
    # 1. For old ticker (if changed)
    if old_ticker != db_trade.ticker:
         all_trades_old = db.query(models.Trade).filter(models.Trade.ticker == old_ticker).all()
         from . import wash_sales
         wash_sales.detect_wash_sales(all_trades_old)
    
    # 2. For new/current ticker
    all_trades_new = db.query(models.Trade).filter(models.Trade.ticker == db_trade.ticker).all()
    from . import wash_sales
    wash_sales.detect_wash_sales(all_trades_new)
    
    db.commit()
    db.refresh(db_trade)
    return db_trade
