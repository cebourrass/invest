import os
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.database import init_db, get_db, Account, Holding, PortfolioHistory, SystemSetting, RecurringDeposit, RecurringDepositHistory
from backend.prices import fetch_price_for_holding
from backend.scheduler import start_scheduler, update_portfolio_snapshot, setup_jobs_for_all_types, execute_recurring_deposit, record_portfolio_snapshot

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
    invested_amount: Optional[float] = Field(0.0, example=10000.0)
    cash_balance: Optional[float] = Field(0.0, example=500.0)

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    creation_date: Optional[str] = None
    invested_amount: Optional[float] = None
    cash_balance: Optional[float] = None

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
    total_invested: Optional[float] = 0.0

    class Config:
        from_attributes = True

class PortfolioSummary(BaseModel):
    total_value: float
    total_cost: float
    total_gain: float
    total_gain_pct: float
    total_invested: float
    total_invested_gain: float
    total_invested_gain_pct: float
    holdings: List[HoldingSchema]
    allocation_by_account: dict
    allocation_by_category: dict
    profitability_periods: dict

class RecurringDepositBase(BaseModel):
    account_id: int
    holding_id: Optional[int] = None
    name: str
    amount: float
    frequency: str  # daily, weekly, monthly
    day_of_period: int
    is_active: Optional[bool] = True
    next_execution_date: str

class RecurringDepositCreate(RecurringDepositBase):
    pass

class RecurringDepositUpdate(BaseModel):
    account_id: Optional[int] = None
    holding_id: Optional[int] = None
    name: Optional[str] = None
    amount: Optional[float] = None
    frequency: Optional[str] = None
    day_of_period: Optional[int] = None
    is_active: Optional[bool] = None
    next_execution_date: Optional[str] = None

class RecurringDepositSchema(RecurringDepositBase):
    id: int
    last_execution_date: Optional[str] = None
    account_name: str
    holding_name: Optional[str] = None

    class Config:
        from_attributes = True

class RecurringDepositHistorySchema(BaseModel):
    id: int
    recurring_deposit_id: int
    execution_date: datetime
    amount: float
    status: str
    details: Optional[str] = None
    deposit_name: str
    account_name: str

    class Config:
        from_attributes = True


# --- Endpoints ---

# 1. Accounts API
@app.get("/api/accounts", response_model=List[AccountSchema])
def get_accounts(db: Session = Depends(get_db)):
    return db.query(Account).all()

@app.post("/api/accounts", response_model=AccountSchema, status_code=status.HTTP_201_CREATED)
def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    db_account = Account(
        name=account.name, 
        type=account.type, 
        creation_date=account.creation_date,
        invested_amount=account.invested_amount or 0.0,
        cash_balance=account.cash_balance or 0.0
    )
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
def calculate_period_return(
    db: Session, 
    now_val: float, 
    now_cost: float, 
    now_invested: float, 
    delta: timedelta
) -> dict:
    target_time = datetime.utcnow() - delta
    snap = db.query(PortfolioHistory).filter(PortfolioHistory.timestamp <= target_time).order_by(PortfolioHistory.timestamp.desc()).first()
    if not snap:
        snap = db.query(PortfolioHistory).order_by(PortfolioHistory.timestamp.asc()).first()
        
    if not snap:
        return {
            "portfolio_return_abs": 0.0,
            "portfolio_return_pct": 0.0,
            "invested_return_abs": 0.0,
            "invested_return_pct": 0.0,
            "available": False,
            "date": "-"
        }
        
    snap_val = snap.total_value
    snap_cost = snap.total_cost
    snap_invested = getattr(snap, 'total_invested', 0.0) or 0.0
    if snap_invested == 0.0:
        snap_invested = snap_cost
        
    # Portfolio performance (vs Cost)
    gain_now = now_val - now_cost
    gain_start = snap_val - snap_cost
    port_gain_diff = gain_now - gain_start
    port_base = snap_val if snap_val > 0 else snap_cost
    port_gain_pct = (port_gain_diff / port_base * 100) if port_base > 0 else 0.0
    
    # Invested performance (vs Invested Money)
    inv_gain_now = now_val - now_invested
    inv_gain_start = snap_val - snap_invested
    inv_gain_diff = inv_gain_now - inv_gain_start
    inv_base = snap_val if snap_val > 0 else snap_invested
    inv_gain_pct = (inv_gain_diff / inv_base * 100) if inv_base > 0 else 0.0
    
    return {
        "portfolio_return_abs": port_gain_diff,
        "portfolio_return_pct": port_gain_pct,
        "invested_return_abs": inv_gain_diff,
        "invested_return_pct": inv_gain_pct,
        "available": True,
        "date": snap.timestamp.strftime("%d/%m/%Y")
    }

@app.get("/api/portfolio/summary", response_model=PortfolioSummary)
def get_portfolio_summary(db: Session = Depends(get_db)):
    accounts = db.query(Account).all()
    holdings = db.query(Holding).all()
    
    account_map = {acc.id: acc for acc in accounts}
    
    holding_schemas = []
    total_cash = sum(acc.cash_balance or 0.0 for acc in accounts)
    total_value = total_cash
    total_cost = total_cash
    
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
    
    # Add cash to account allocations and categories
    for acc in accounts:
        allocation_by_account[acc.name] = allocation_by_account.get(acc.name, 0.0) + (acc.cash_balance or 0.0)
    
    if total_cash > 0.0:
        allocation_by_category["Cash"] = allocation_by_category.get("Cash", 0.0) + total_cash

    # Save the updated prices cache
    if holdings:
        db.commit()
        
    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost > 0 else 0.0
    
    total_invested = sum(acc.invested_amount or 0.0 for acc in accounts)
    total_invested_gain = total_value - total_invested
    total_invested_gain_pct = (total_invested_gain / total_invested * 100) if total_invested > 0 else 0.0
    
    profitability_periods = {}
    periods = {
        "1d": timedelta(days=1),
        "1w": timedelta(days=7),
        "1m": timedelta(days=30),
        "5m": timedelta(days=150),
        "1y": timedelta(days=365)
    }
    for name, delta in periods.items():
        profitability_periods[name] = calculate_period_return(db, total_value, total_cost, total_invested, delta)
        
    profitability_periods["global"] = {
        "portfolio_return_abs": total_gain,
        "portfolio_return_pct": total_gain_pct,
        "invested_return_abs": total_invested_gain,
        "invested_return_pct": total_invested_gain_pct,
        "available": True,
        "date": "Origine"
    }
    
    return PortfolioSummary(
        total_value=total_value,
        total_cost=total_cost,
        total_gain=total_gain,
        total_gain_pct=total_gain_pct,
        total_invested=total_invested,
        total_invested_gain=total_invested_gain,
        total_invested_gain_pct=total_invested_gain_pct,
        holdings=holding_schemas,
        allocation_by_account=allocation_by_account,
        allocation_by_category=allocation_by_category,
        profitability_periods=profitability_periods
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

def aggregate_history(records: List[PortfolioHistory], period: str) -> List[PortfolioHistory]:
    if not records:
        return []
    
    # Sort records chronologically
    records = sorted(records, key=lambda r: r.timestamp)
    
    # Filter by period threshold
    now = datetime.utcnow()
    if period == "1d":
        threshold = now - timedelta(hours=24)
        records = [r for r in records if r.timestamp >= threshold]
    elif period == "10d":
        threshold = now - timedelta(days=10)
        records = [r for r in records if r.timestamp >= threshold]
    elif period == "1m":
        threshold = now - timedelta(days=30)
        records = [r for r in records if r.timestamp >= threshold]
    elif period == "3m":
        threshold = now - timedelta(days=90)
        records = [r for r in records if r.timestamp >= threshold]
    elif period == "1y":
        threshold = now - timedelta(days=365)
        records = [r for r in records if r.timestamp >= threshold]
    elif period == "5y":
        threshold = now - timedelta(days=5 * 365)
        records = [r for r in records if r.timestamp >= threshold]
    
    if not records:
        return []

    # Aggregation/Grouping: we want to keep the last record for each interval
    aggregated = []
    
    if period == "1d":
        # Group by hour: key is (year, month, day, hour)
        groups = {}
        for r in records:
            key = (r.timestamp.year, r.timestamp.month, r.timestamp.day, r.timestamp.hour)
            groups[key] = r
        aggregated = list(groups.values())
        
    elif period in ("10d", "1m", "3m", "1y"):
        # Group by day: key is (year, month, day)
        groups = {}
        for r in records:
            key = (r.timestamp.year, r.timestamp.month, r.timestamp.day)
            groups[key] = r
        aggregated = list(groups.values())
        
    elif period == "5y":
        # Group by week: key is (year, week_number)
        groups = {}
        for r in records:
            iso = r.timestamp.isocalendar()
            key = (iso[0], iso[1])
            groups[key] = r
        aggregated = list(groups.values())
        
    else:  # "all"
        span_days = (records[-1].timestamp - records[0].timestamp).days
        if span_days <= 365:
            # Group by day
            groups = {}
            for r in records:
                key = (r.timestamp.year, r.timestamp.month, r.timestamp.day)
                groups[key] = r
            aggregated = list(groups.values())
        elif span_days <= 5 * 365:
            # Group by week
            groups = {}
            for r in records:
                iso = r.timestamp.isocalendar()
                key = (iso[0], iso[1])
                groups[key] = r
            aggregated = list(groups.values())
        else:
            # Group by month: key is (year, month)
            groups = {}
            for r in records:
                key = (r.timestamp.year, r.timestamp.month)
                groups[key] = r
            aggregated = list(groups.values())
            
    return sorted(aggregated, key=lambda r: r.timestamp)

@app.get("/api/portfolio/history", response_model=List[HistorySchema])
def get_portfolio_history(period: str = "1m", db: Session = Depends(get_db)):
    records = db.query(PortfolioHistory).all()
    for r in records:
        if getattr(r, 'total_invested', None) is None or r.total_invested == 0.0:
            r.total_invested = r.total_cost
    return aggregate_history(records, period)

@app.delete("/api/portfolio/history", status_code=status.HTTP_200_OK)
def delete_portfolio_history(keep_days: Optional[int] = None, db: Session = Depends(get_db)):
    """
    Cleans up portfolio history snapshots.
    If keep_days is provided, deletes snapshots older than keep_days.
    Otherwise deletes all history and creates a fresh snapshot of current state to avoid empty graphs.
    """
    try:
        if keep_days is not None:
            cutoff = datetime.utcnow() - timedelta(days=keep_days)
            db.query(PortfolioHistory).filter(PortfolioHistory.timestamp < cutoff).delete()
            db.commit()
            logger.info(f"Cleaned up portfolio history snapshots older than {keep_days} days.")
            return {"status": "success", "message": f"Historique de plus de {keep_days} jours supprimé."}
        else:
            db.query(PortfolioHistory).delete()
            db.commit()
            
            # Immediately record a fresh snapshot so the UI has at least one starting point and doesn't break
            record_portfolio_snapshot(db)
            
            logger.info("Cleared all portfolio history snapshots and recorded a fresh snapshot.")
            return {"status": "success", "message": "Tout l'historique a été réinitialisé."}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting portfolio history: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression de l'historique : {str(e)}")

# 4. System Settings API
@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    db_settings = db.query(SystemSetting).all()
    return {s.key: s.value for s in db_settings}

@app.put("/api/settings")
def update_settings(settings: dict, db: Session = Depends(get_db)):
    try:
        hour = int(settings.get("update_hour", 20))
        minute = int(settings.get("update_minute", 0))
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Heure ou minute invalide")

    allowed_keys = {
        "update_hour": str(hour),
        "update_minute": str(minute),
        "refresh_freq_PEA": settings.get("refresh_freq_PEA", "jour"),
        "refresh_freq_PER": settings.get("refresh_freq_PER", "jour"),
        "refresh_freq_Assurance Vie": settings.get("refresh_freq_Assurance Vie", "jour"),
        "refresh_freq_Compte-Titres": settings.get("refresh_freq_Compte-Titres", "jour"),
        "refresh_freq_Crypto Wallet": settings.get("refresh_freq_Crypto Wallet", "jour"),
        "refresh_freq_Autre": settings.get("refresh_freq_Autre", "jour"),
    }

    valid_freqs = {"minute", "5minutes", "hour", "jour", "manuel"}
    for key in list(allowed_keys.keys())[2:]:  # skip hour and minute
        if allowed_keys[key] not in valid_freqs:
            raise HTTPException(status_code=400, detail=f"Fréquence invalide pour {key}")

    for key, val in allowed_keys.items():
        db_setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not db_setting:
            db_setting = SystemSetting(key=key)
            db.add(db_setting)
        db_setting.value = val

    db.commit()

    # Trigger hot rescheduling of scheduler
    success = setup_jobs_for_all_types(db)
    
    return {
        "status": "success" if success else "error",
        "message": "Settings updated successfully." if success else "Settings saved but failed to update scheduler."
    }


# 5. Recurring Deposits API
@app.get("/api/deposits", response_model=List[RecurringDepositSchema])
def get_deposits(db: Session = Depends(get_db)):
    deposits = db.query(RecurringDeposit).all()
    results = []
    for dep in deposits:
        # Get account name
        acc = db.query(Account).filter(Account.id == dep.account_id).first()
        acc_name = acc.name if acc else "Inconnu"
        # Get holding name
        holding_name = None
        if dep.holding_id:
            h = db.query(Holding).filter(Holding.id == dep.holding_id).first()
            holding_name = h.name if h else "Inconnu"
            
        results.append(RecurringDepositSchema(
            id=dep.id,
            account_id=dep.account_id,
            holding_id=dep.holding_id,
            name=dep.name,
            amount=dep.amount,
            frequency=dep.frequency,
            day_of_period=dep.day_of_period,
            is_active=dep.is_active,
            next_execution_date=dep.next_execution_date,
            last_execution_date=dep.last_execution_date,
            account_name=acc_name,
            holding_name=holding_name
        ))
    return results

@app.post("/api/deposits", response_model=RecurringDepositSchema, status_code=status.HTTP_201_CREATED)
def create_deposit(deposit: RecurringDepositCreate, db: Session = Depends(get_db)):
    # Check if account exists
    acc = db.query(Account).filter(Account.id == deposit.account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
        
    # Check if holding exists if specified
    holding_name = None
    if deposit.holding_id:
        h = db.query(Holding).filter(Holding.id == deposit.holding_id).first()
        if not h:
            raise HTTPException(status_code=404, detail="Holding not found")
        holding_name = h.name
        
    db_deposit = RecurringDeposit(
        account_id=deposit.account_id,
        holding_id=deposit.holding_id,
        name=deposit.name,
        amount=deposit.amount,
        frequency=deposit.frequency,
        day_of_period=deposit.day_of_period,
        is_active=deposit.is_active,
        next_execution_date=deposit.next_execution_date
    )
    db.add(db_deposit)
    db.commit()
    db.refresh(db_deposit)
    
    return RecurringDepositSchema(
        id=db_deposit.id,
        account_id=db_deposit.account_id,
        holding_id=db_deposit.holding_id,
        name=db_deposit.name,
        amount=db_deposit.amount,
        frequency=db_deposit.frequency,
        day_of_period=db_deposit.day_of_period,
        is_active=db_deposit.is_active,
        next_execution_date=db_deposit.next_execution_date,
        last_execution_date=db_deposit.last_execution_date,
        account_name=acc.name,
        holding_name=holding_name
    )

@app.put("/api/deposits/{deposit_id}", response_model=RecurringDepositSchema)
def update_deposit(deposit_id: int, deposit_update: RecurringDepositUpdate, db: Session = Depends(get_db)):
    db_deposit = db.query(RecurringDeposit).filter(RecurringDeposit.id == deposit_id).first()
    if not db_deposit:
        raise HTTPException(status_code=404, detail="Recurring deposit not found")
        
    update_data = deposit_update.dict(exclude_unset=True)
    for key, val in update_data.items():
        setattr(db_deposit, key, val)
        
    db.commit()
    db.refresh(db_deposit)
    
    # Get account name
    acc = db.query(Account).filter(Account.id == db_deposit.account_id).first()
    acc_name = acc.name if acc else "Inconnu"
    # Get holding name
    holding_name = None
    if db_deposit.holding_id:
        h = db.query(Holding).filter(Holding.id == db_deposit.holding_id).first()
        holding_name = h.name if h else "Inconnu"
        
    return RecurringDepositSchema(
        id=db_deposit.id,
        account_id=db_deposit.account_id,
        holding_id=db_deposit.holding_id,
        name=db_deposit.name,
        amount=db_deposit.amount,
        frequency=db_deposit.frequency,
        day_of_period=db_deposit.day_of_period,
        is_active=db_deposit.is_active,
        next_execution_date=db_deposit.next_execution_date,
        last_execution_date=db_deposit.last_execution_date,
        account_name=acc_name,
        holding_name=holding_name
    )

@app.delete("/api/deposits/history", status_code=status.HTTP_200_OK)
def delete_deposit_history(keep_days: Optional[int] = None, db: Session = Depends(get_db)):
    """
    Cleans up recurring deposit execution logs.
    If keep_days is provided, deletes logs older than keep_days.
    Otherwise deletes all execution logs.
    """
    try:
        if keep_days is not None:
            cutoff = datetime.utcnow() - timedelta(days=keep_days)
            db.query(RecurringDepositHistory).filter(RecurringDepositHistory.execution_date < cutoff).delete()
            db.commit()
            logger.info(f"Cleaned up deposit history logs older than {keep_days} days.")
            return {"status": "success", "message": f"Historique des versements de plus de {keep_days} jours supprimé."}
        else:
            db.query(RecurringDepositHistory).delete()
            db.commit()
            logger.info("Cleared all recurring deposit execution logs.")
            return {"status": "success", "message": "Tout l'historique des versements a été supprimé."}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting deposit history: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression de l'historique : {str(e)}")

@app.delete("/api/deposits/{deposit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deposit(deposit_id: int, db: Session = Depends(get_db)):
    db_deposit = db.query(RecurringDeposit).filter(RecurringDeposit.id == deposit_id).first()
    if not db_deposit:
        raise HTTPException(status_code=404, detail="Recurring deposit not found")
    db.delete(db_deposit)
    db.commit()
    return None

@app.post("/api/deposits/{deposit_id}/trigger")
def trigger_deposit(deposit_id: int, db: Session = Depends(get_db)):
    """
    Manually triggers execution of a recurring deposit right now.
    """
    db_deposit = db.query(RecurringDeposit).filter(RecurringDeposit.id == deposit_id).first()
    if not db_deposit:
        raise HTTPException(status_code=404, detail="Recurring deposit not found")
        
    success, details = execute_recurring_deposit(db, db_deposit)
    
    status_str = "success" if success else "failed"
    
    # Create execution history log
    log = RecurringDepositHistory(
        recurring_deposit_id=db_deposit.id,
        amount=db_deposit.amount,
        status=status_str,
        details=details,
        execution_date=datetime.utcnow()
    )
    db.add(log)
    
    if success:
        # Advance next execution date
        try:
            import calendar
            next_dt = datetime.strptime(db_deposit.next_execution_date, "%Y-%m-%d")
            today_dt = datetime.utcnow()
            
            while next_dt.date() <= today_dt.date():
                if db_deposit.frequency == "daily":
                    next_dt += timedelta(days=1)
                elif db_deposit.frequency == "weekly":
                    next_dt += timedelta(weeks=1)
                elif db_deposit.frequency == "monthly":
                    month = next_dt.month
                    year = next_dt.year
                    day = db_deposit.day_of_period
                    
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                    
                    last_day = calendar.monthrange(year, month)[1]
                    target_day = min(day, last_day)
                    next_dt = datetime(year, month, target_day)
                    
            db_deposit.next_execution_date = next_dt.strftime("%Y-%m-%d")
            db_deposit.last_execution_date = today_dt.strftime("%Y-%m-%d")
            
        except Exception as ex:
            logger.error(f"Error advancing date on manual trigger: {ex}")
            
        db.commit()
        # Record a portfolio snapshot
        record_portfolio_snapshot(db)
        return {"status": "success", "message": "Versement exécuté avec succès.", "details": details}
    else:
        db.commit() # save failure log
        raise HTTPException(status_code=400, detail=f"Échec de l'exécution: {details}")

@app.get("/api/deposits/history", response_model=List[RecurringDepositHistorySchema])
def get_deposit_history(db: Session = Depends(get_db)):
    records = db.query(RecurringDepositHistory).all()
    results = []
    # Sort descending (most recent first)
    records = sorted(records, key=lambda r: r.execution_date, reverse=True)
    
    for rec in records:
        dep = db.query(RecurringDeposit).filter(RecurringDeposit.id == rec.recurring_deposit_id).first()
        dep_name = dep.name if dep else "Versement Supprimé"
        
        acc_name = "Inconnu"
        if dep:
            acc = db.query(Account).filter(Account.id == dep.account_id).first()
            acc_name = acc.name if acc else "Inconnu"
            
        results.append(RecurringDepositHistorySchema(
            id=rec.id,
            recurring_deposit_id=rec.recurring_deposit_id,
            execution_date=rec.execution_date,
            amount=rec.amount,
            status=rec.status,
            details=rec.details,
            deposit_name=dep_name,
            account_name=acc_name
        ))
    return results




# --- Serve Static Web Files ---

# Create frontend folder if it doesn't exist to prevent mounting errors during startup
os.makedirs("frontend", exist_ok=True)

# Mount the static files router to serve index.html at root '/'
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
