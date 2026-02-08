from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Boolean, TypeDecorator
from .database import Base
from datetime import datetime

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)
    ticker = Column(String, index=True)
    type = Column(String) # Equity, Option
    side = Column(String) # Buy, Sell
    price = Column(Float)
    quantity = Column(Float)
    fees = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    
    # Specific to Options
    expiration_date = Column(DateTime, nullable=True)
    strike_price = Column(Float, nullable=True)
    option_type = Column(String, nullable=True) # Call, Put


class AssetPrice(Base):
    __tablename__ = "asset_prices"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True)
    price = Column(Float)
    last_updated = Column(DateTime, default=datetime.utcnow)

class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)
    ticker = Column(String, index=True)
    quantity = Column(Float)
    average_price = Column(Float)
    current_price = Column(Float)
    market_value = Column(Float)
    unrealized_pnl = Column(Float)
    realized_pnl = Column(Float)
