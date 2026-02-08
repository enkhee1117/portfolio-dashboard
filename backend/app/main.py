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
def create_trade(trade: schemas.TradeCreate, db: Session = Depends(get_db)):
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
    
    return db_trade
