from pydantic import BaseModel, ConfigDict
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
    is_wash_sale: bool = False

class TradeCreate(TradeBase):
    pass

class Trade(TradeBase):
    id: str

    model_config = ConfigDict(from_attributes=True)

class PortfolioSnapshotBase(BaseModel):
    date: datetime
    ticker: str
    quantity: float
    average_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    realized_pnl_ytd: float = 0.0
    primary_theme: Optional[str] = None
    secondary_theme: Optional[str] = None

class PortfolioSnapshot(PortfolioSnapshotBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


# --- Asset / Theme Management ---

class AssetBase(BaseModel):
    ticker: str
    price: float = 0.0
    primary_theme: str
    secondary_theme: str

class AssetCreate(AssetBase):
    pass

class AssetUpdate(BaseModel):
    price: Optional[float] = None
    primary_theme: Optional[str] = None
    secondary_theme: Optional[str] = None
    new_ticker: Optional[str] = None  # For renaming ticker

class Asset(AssetBase):
    last_updated: Optional[datetime] = None
    previous_close: Optional[float] = None
    daily_change: Optional[float] = None
    daily_change_pct: Optional[float] = None
    rsi: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


# --- Price History (for charting & analytics) ---

class PriceHistoryEntry(BaseModel):
    ticker: str
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    previous_close: Optional[float] = None
    volume: Optional[float] = None

