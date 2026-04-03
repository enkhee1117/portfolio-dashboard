from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Literal
from datetime import datetime

class TradeBase(BaseModel):
    date: datetime
    ticker: str = Field(..., min_length=1, max_length=10)
    type: str = Field(default="Equity", max_length=20)
    side: Literal["Buy", "Sell"]
    price: float = Field(..., ge=0)
    quantity: float = Field(..., gt=0)
    fees: float = Field(default=0.0, ge=0)
    currency: str = Field(default="USD", max_length=5)
    user_id: Optional[str] = None

    expiration_date: Optional[datetime] = None
    strike_price: Optional[float] = Field(default=None, ge=0)
    option_type: Optional[Literal["Call", "Put"]] = None
    is_wash_sale: bool = False

class TradeCreate(TradeBase):
    pass

class TradeResponse(TradeBase):
    """Trade model for API responses — excludes internal user_id."""
    id: str

    model_config = ConfigDict(from_attributes=True)

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data.pop("user_id", None)
        return data

# Keep Trade for internal use (includes user_id)
Trade = TradeResponse

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
    ticker: str = Field(..., min_length=1, max_length=10)
    price: float = Field(default=0.0, ge=0)
    primary_theme: str = Field(..., max_length=50)
    secondary_theme: str = Field(..., max_length=50)

class AssetCreate(AssetBase):
    pass

class AssetUpdate(BaseModel):
    price: Optional[float] = Field(default=None, ge=0)
    primary_theme: Optional[str] = Field(default=None, max_length=50)
    secondary_theme: Optional[str] = Field(default=None, max_length=50)
    new_ticker: Optional[str] = Field(default=None, min_length=1, max_length=10)

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

