import os
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.database import init_db, get_db, Account, Holding, PortfolioHistory, SystemSetting
from backend.prices import fetch_price_for_holding
from backend.scheduler import start_scheduler, update_portfolio_snapshot, reschedule_portfolio_job

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lifespan context manager for startup and shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up Investment Portfolio Tracker Backend...")
    init_db()
    app.state.scheduler = start_scheduler()
    yield
    # Shutdown
    logger.info("Shutting down Investment Portfolio Tracker Backend...")
    app.state.scheduler.shutdown()

app = FastAPI(
    title="Investment Portfolio Tracker API",
    description="Backend API for managing accounts, holdings, and pricing",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configurations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Schemas ---
class AccountBase(BaseModel):
    name: str = Field(..., example="PEA EasyBourse")
    type: str = Field(..., example="PEA") # PEA, PER, Assurance Vie, Compte-Titres, Autre
    creation_date: Optional[str] = Field(None, example="2020-01-01")

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    creation_date: Optional[str] = None

class AccountSchema(AccountBase):
    id: int

    class Config:
        from_attributes = True

class HoldingBase(BaseModel):
    account_id: int
    name: str
    isin_or_symbol: Optional[str] = ""
    quantity: float
    buy_price: float
    is_manual: bool = False
    manual_price: Optional[float] = 0.0
    category: str = "Autre" # ETF, OPCVM, Actions, Immobilier, Crypto, Fonds Euros, Cash, Autre

class HoldingCreate(HoldingBase):
    pass

class HoldingUpdate(BaseModel):
    name: Optional[str] = None
    isin_or_symbol: Optional[str] = None
    quantity: Optional[float] = None
    buy_price: Optional[float] = None
    is_manual: Optional[bool] = None
    manual_price: Optional[float] = None
    category: Optional[str] = None

class HoldingSchema(HoldingBase):
    id: int
    current_price: Optional[float] = 0.0
    total_value: Optional[float] = 0.0
    total_cost: Optional[float] = 0.0
    gain_loss: Optional[float] = 0.0
    gain_loss_pct: Optional[float] = 0.0

    class Config:
        from_attributes = True

class HistorySchema(BaseModel):
    id: int
    timestamp: datetime
    total_value: float
    total_gain: float
    total_cost: float

    class Config:
        from_attributes = True

class PortfolioSummary(BaseModel):
    total_value: float
    total_cost: float
    total_gain: float
    total_gain_pct: float
    holdings: List[HoldingSchema]
    allocation_by_account: dict
    allocation_by_category: dict


# --- Endpoints ---

# 1. Accounts API
@app.get("/api/accounts", response_model=List[AccountSchema])
def get_accounts(db: Session = Depends(get_db)):
    return db.query(Account).all()

@app.post("/api/accounts", response_model=AccountSchema, status_code=status.HTTP_201_CREATED)
def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    db_account = Account(name=account.name, type=account.type, creation_date=account.creation_date)
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account

@app.put("/api/accounts/{account_id}", response_model=AccountSchema)
def update_account(account_id: int, account_update: AccountUpdate, db: Session = Depends(get_db)):
    db_account = db.query(Account).filter(Account.id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    update_data = account_update.dict(exclude_unset=True)
    for key, val in update_data.items():
        setattr(db_account, key, val)
        
    db.commit()
    db.refresh(db_account)
    return db_account

@app.delete("/api/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, db: Session = Depends(get_db)):
    db_account = db.query(Account).filter(Account.id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(db_account)
    db.commit()
    return None


# 2. Holdings API
@app.get("/api/holdings", response_model=List[HoldingSchema])
def get_holdings(db: Session = Depends(get_db)):
    holdings = db.query(Holding).all()
    result = []
    for h in holdings:
        price = fetch_price_for_holding(h.isin_or_symbol, h.is_manual, h.manual_price)
        cost = h.quantity * h.buy_price
        val = h.quantity * (price or 0.0)
        gain = val - cost
        gain_pct = (gain / cost * 100) if cost > 0 else 0.0
        
        result.append(HoldingSchema(
            id=h.id,
            account_id=h.account_id,
            name=h.name,
            isin_or_symbol=h.isin_or_symbol,
            quantity=h.quantity,
            buy_price=h.buy_price,
            is_manual=h.is_manual,
            manual_price=h.manual_price,
            category=h.category,
            current_price=price,
            total_value=val,
            total_cost=cost,
            gain_loss=gain,
            gain_loss_pct=gain_pct
        ))
    return result

@app.post("/api/holdings", response_model=HoldingSchema, status_code=status.HTTP_201_CREATED)
def create_holding(holding: HoldingCreate, db: Session = Depends(get_db)):
    # Check if account exists
    acc = db.query(Account).filter(Account.id == holding.account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    db_holding = Holding(
        account_id=holding.account_id,
        name=holding.name,
        isin_or_symbol=holding.isin_or_symbol,
        quantity=holding.quantity,
        buy_price=holding.buy_price,
        is_manual=holding.is_manual,
        manual_price=holding.manual_price,
        category=holding.category
    )
    db.add(db_holding)
    db.commit()
    db.refresh(db_holding)
    
    # Calculate values for schema response
    price = fetch_price_for_holding(db_holding.isin_or_symbol, db_holding.is_manual, db_holding.manual_price)
    cost = db_holding.quantity * db_holding.buy_price
    val = db_holding.quantity * (price or 0.0)
    gain = val - cost
    gain_pct = (gain / cost * 100) if cost > 0 else 0.0

    return HoldingSchema(
        id=db_holding.id,
        account_id=db_holding.account_id,
        name=db_holding.name,
        isin_or_symbol=db_holding.isin_or_symbol,
        quantity=db_holding.quantity,
        buy_price=db_holding.buy_price,
        is_manual=db_holding.is_manual,
        manual_price=db_holding.manual_price,
        category=db_holding.category,
        current_price=price,
        total_value=val,
        total_cost=cost,
        gain_loss=gain,
        gain_loss_pct=gain_pct
    )

@app.put("/api/holdings/{holding_id}", response_model=HoldingSchema)
def update_holding(holding_id: int, holding_update: HoldingUpdate, db: Session = Depends(get_db)):
    db_holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not db_holding:
        raise HTTPException(status_code=404, detail="Holding not found")
        
    update_data = holding_update.dict(exclude_unset=True)
    for key, val in update_data.items():
        setattr(db_holding, key, val)
        
    db.commit()
    db.refresh(db_holding)
    
    price = fetch_price_for_holding(db_holding.isin_or_symbol, db_holding.is_manual, db_holding.manual_price)
    cost = db_holding.quantity * db_holding.buy_price
    val = db_holding.quantity * (price or 0.0)
    gain = val - cost
    gain_pct = (gain / cost * 100) if cost > 0 else 0.0

    return HoldingSchema(
        id=db_holding.id,
        account_id=db_holding.account_id,
        name=db_holding.name,
        isin_or_symbol=db_holding.isin_or_symbol,
        quantity=db_holding.quantity,
        buy_price=db_holding.buy_price,
        is_manual=db_holding.is_manual,
        manual_price=db_holding.manual_price,
        category=db_holding.category,
        current_price=price,
        total_value=val,
        total_cost=cost,
        gain_loss=gain,
        gain_loss_pct=gain_pct
    )

@app.delete("/api/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(holding_id: int, db: Session = Depends(get_db)):
    db_holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not db_holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    db.delete(db_holding)
    db.commit()
    return None


# 3. Portfolio Summary & History
@app.get("/api/portfolio/summary", response_model=PortfolioSummary)
def get_portfolio_summary(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    holdings = db.query(Holding).all()
    
    account_map = {acc.id: acc for acc in accounts}
    
    holding_schemas = []
    total_value = 0.0
    total_cost = 0.0
    
    allocation_by_account = {}
    allocation_by_category = {}

    for h in holdings:
        price = fetch_price_for_holding(h.isin_or_symbol, h.is_manual, h.manual_price)
        cost = h.quantity * h.buy_price
        val = h.quantity * (price or 0.0)
        gain = val - cost
        gain_pct = (gain / cost * 100) if cost > 0 else 0.0
        
        total_value += val
        total_cost += cost
        
        acc = account_map.get(h.account_id)
        acc_name = acc.name if acc else "Inconnu"
        
        # Categorized allocation tracking
        allocation_by_account[acc_name] = allocation_by_account.get(acc_name, 0.0) + val
        allocation_by_category[h.category] = allocation_by_category.get(h.category, 0.0) + val
        
        # Cache current price temporarily in the DB (non-manual only)
        if not h.is_manual and price is not None and h.manual_price != price:
            h.manual_price = price
            
        holding_schemas.append(HoldingSchema(
            id=h.id,
            account_id=h.account_id,
            name=h.name,
            isin_or_symbol=h.isin_or_symbol,
            quantity=h.quantity,
            buy_price=h.buy_price,
            is_manual=h.is_manual,
            manual_price=h.manual_price,
            category=h.category,
            current_price=price,
            total_value=val,
            total_cost=cost,
            gain_loss=gain,
            gain_loss_pct=gain_pct
        ))
    
    # Save the updated prices cache
    if holdings:
        db.commit()
        
    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost > 0 else 0.0
    
    return PortfolioSummary(
        total_value=total_value,
        total_cost=total_cost,
        total_gain=total_gain,
        total_gain_pct=total_gain_pct,
        holdings=holding_schemas,
        allocation_by_account=allocation_by_account,
        allocation_by_category=allocation_by_category
    )

@app.post("/api/portfolio/refresh")
def force_refresh_portfolio(db: Session = Depends(get_db)):
    """
    Triggers manual prices update and creates a new portfolio snapshot entry.
    """
    logger.info("Manual portfolio refresh triggered")
    try:
        update_portfolio_snapshot()
        return {"status": "success", "message": "Prices refreshed and snapshot recorded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Refresh failed: {str(e)}")

@app.get("/api/portfolio/history", response_model=List[HistorySchema])
def get_portfolio_history(db: Session = Depends(get_db)):
    return db.query(PortfolioHistory).order_by(PortfolioHistory.timestamp.asc()).all()

# 4. System Settings API
class SettingsUpdate(BaseModel):
    update_hour: int = Field(..., ge=0, le=23)
    update_minute: int = Field(..., ge=0, le=59)
    update_interval: str = Field(..., example="daily")

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    db_settings = db.query(SystemSetting).all()
    return {s.key: s.value for s in db_settings}

@app.put("/api/settings")
def update_settings(settings: SettingsUpdate, db: Session = Depends(get_db)):
    h_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_hour").first()
    m_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_minute").first()
    i_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_interval").first()
    
    if not h_setting:
        h_setting = SystemSetting(key="update_hour")
        db.add(h_setting)
    if not m_setting:
        m_setting = SystemSetting(key="update_minute")
        db.add(m_setting)
    if not i_setting:
        i_setting = SystemSetting(key="update_interval")
        db.add(i_setting)
        
    h_setting.value = str(settings.update_hour)
    m_setting.value = str(settings.update_minute)
    i_setting.value = settings.update_interval
    
    db.commit()
    
    # Trigger hot rescheduling of scheduler
    success = reschedule_portfolio_job(
        hour=settings.update_hour,
        minute=settings.update_minute,
        interval=settings.update_interval
    )
    
    return {
        "status": "success" if success else "error",
        "message": "Settings updated successfully." if success else "Settings saved but failed to update scheduler."
    }


# --- Serve Static Web Files ---

# Create frontend folder if it doesn't exist to prevent mounting errors during startup
os.makedirs("frontend", exist_ok=True)

# Mount the static files router to serve index.html at root '/'
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
