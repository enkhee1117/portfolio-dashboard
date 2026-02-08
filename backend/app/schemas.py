from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class TradeBase(BaseModel):
    date: datetime
    ticker: str
    type: str
    side: str
    price: float
    quantity: float
    fees: float = 0.0
    currency: str = "USD"
    
    expiration_date: Optional[datetime] = None
    strike_price: Optional[float] = None
    option_type: Optional[str] = None # Call, Put

class TradeCreate(TradeBase):
    pass

class Trade(TradeBase):
    id: int

    class Config:
        from_attributes = True

class PortfolioSnapshotBase(BaseModel):
    date: datetime
    ticker: str
    quantity: float
    average_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float

class PortfolioSnapshot(PortfolioSnapshotBase):
    id: int

    class Config:
        from_attributes = True
