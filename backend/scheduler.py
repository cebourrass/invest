import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Account, Holding, PortfolioHistory, SystemSetting, init_db, RecurringDeposit, RecurringDepositHistory
from backend.prices import fetch_price_for_holding

logger = logging.getLogger(__name__)

# Global reference to scheduler
_scheduler = None

def update_portfolio_snapshot():
    """
    Background job that recalculates total portfolio value and writes to history.
    """
    logger.info("Starting scheduled portfolio snapshot calculation...")
    db: Session = SessionLocal()
    try:
        # Initialise database tables if they don't exist yet
        init_db()
        
        holdings = db.query(Holding).all()
        accounts = db.query(Account).all()
        if not holdings and not accounts:
            logger.info("No holdings or accounts found in database. Skipping snapshot.")
            return

        total_cash = sum(acc.cash_balance or 0.0 for acc in accounts)
        total_value = total_cash
        total_cost = total_cash
        
        total_invested = sum(acc.invested_amount or 0.0 for acc in accounts)

        for holding in holdings:
            # Fetch the current price
            current_price = fetch_price_for_holding(
                isin_or_symbol=holding.isin_or_symbol,
                is_manual=holding.is_manual,
                manual_price=holding.manual_price
            )
            
            # If the automatic price fetching succeeded, we can temporarily store it 
            # in manual_price so that the front-end has the cached price.
            # But we don't want to overwrite manual holdings.
            if not holding.is_manual and current_price is not None:
                holding.manual_price = current_price
            
            # Value calculations
            holding_cost = holding.quantity * holding.buy_price
            holding_value = holding.quantity * (current_price or 0.0)
            
            total_value += holding_value
            total_cost += holding_cost

        db.commit() # Save any updated cached manual_prices
        
        total_gain = total_value - total_cost

        # Create history record
        snapshot = PortfolioHistory(
            timestamp=datetime.utcnow(),
            total_value=total_value,
            total_gain=total_gain,
            total_cost=total_cost,
            total_invested=total_invested
        )
        db.add(snapshot)
        db.commit()
        logger.info(f"Portfolio snapshot recorded successfully. Total Value: {total_value:.2f} EUR, Gain: {total_gain:.2f} EUR")
    except Exception as e:
        logger.error(f"Error during portfolio snapshot execution: {str(e)}")
        db.rollback()
    finally:
        db.close()

def record_portfolio_snapshot(db: Session):
    """
    Recalculates the total portfolio value and writes to history.
    Does not fetch prices from Yahoo Finance; uses the database manual_price cache.
    """
    holdings = db.query(Holding).all()
    accounts = db.query(Account).all()
    if not holdings and not accounts:
        return
    
    total_cash = sum(acc.cash_balance or 0.0 for acc in accounts)
    total_value = total_cash
    total_cost = total_cash
    
    for holding in holdings:
        price = holding.manual_price or 0.0
        total_value += holding.quantity * price
        total_cost += holding.quantity * holding.buy_price
    
    total_invested = sum(acc.invested_amount or 0.0 for acc in accounts)
    
    total_gain = total_value - total_cost
    snapshot = PortfolioHistory(
        timestamp=datetime.utcnow(),
        total_value=total_value,
        total_gain=total_gain,
        total_cost=total_cost,
        total_invested=total_invested
    )
    db.add(snapshot)
    db.commit()
    logger.info(f"Portfolio snapshot recorded. Total: {total_value:.2f} EUR, Gain: {total_gain:.2f} EUR")

def update_prices_for_account_type(account_type: str):
    """
    Background job that updates prices for all non-manual holdings of a specific account type,
    then records a new portfolio snapshot.
    """
    logger.info(f"Starting scheduled price update for account type: {account_type}...")
    db: Session = SessionLocal()
    try:
        holdings = db.query(Holding).join(Account).filter(Account.type == account_type).all()
        if not holdings:
            logger.info(f"No holdings found for account type {account_type}. Skipping update.")
            return

        for holding in holdings:
            if not holding.is_manual:
                current_price = fetch_price_for_holding(
                    isin_or_symbol=holding.isin_or_symbol,
                    is_manual=holding.is_manual,
                    manual_price=holding.manual_price
                )
                if current_price is not None:
                    holding.manual_price = current_price
        
        db.commit()
        logger.info(f"Prices updated in DB for account type: {account_type}")
        
        # Take a snapshot of the portfolio after updating this type
        record_portfolio_snapshot(db)
        
    except Exception as e:
        logger.error(f"Error during price update for {account_type}: {str(e)}")
        db.rollback()
    finally:
        db.close()

def setup_jobs_for_all_types(db: Session = None):
    """
    Remove all existing account-type jobs and schedule new ones based on current settings.
    """
    global _scheduler
    if not _scheduler:
        logger.warning("Rescheduling failed: Scheduler is not active.")
        return False
        
    local_db = None
    if db is None:
        local_db = SessionLocal()
        db = local_db
        
    try:
        # Retrieve settings from DB
        default_freqs = {
            "PEA": "jour",
            "PER": "jour",
            "Assurance Vie": "jour",
            "Compte-Titres": "jour",
            "Crypto Wallet": "jour",
            "Autre": "jour"
        }
        
        hour_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_hour").first()
        min_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_minute").first()
        
        hour = int(hour_setting.value) if hour_setting else 20
        minute = int(min_setting.value) if min_setting else 0
        
        freqs = {}
        for acc_type in default_freqs.keys():
            key = f"refresh_freq_{acc_type}"
            setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            freqs[acc_type] = setting.value if setting else default_freqs[acc_type]
            
        # Clean up existing jobs starting with "refresh_"
        existing_jobs = _scheduler.get_jobs()
        for job in existing_jobs:
            if job.id.startswith("refresh_"):
                _scheduler.remove_job(job.id)
        
        # Remove legacy daily job if exists
        try:
            _scheduler.remove_job("portfolio_daily_snapshot")
        except Exception:
            pass
                
        # Now schedule jobs for each account type
        for acc_type, freq in freqs.items():
            job_id = f"refresh_{acc_type}"
            
            if freq == "minute":
                _scheduler.add_job(
                    update_prices_for_account_type,
                    'cron',
                    args=[acc_type],
                    id=job_id,
                    replace_existing=True,
                    minute='*'
                )
                logger.info(f"Scheduled job {job_id} to run every minute")
                
            elif freq == "5minutes":
                _scheduler.add_job(
                    update_prices_for_account_type,
                    'cron',
                    args=[acc_type],
                    id=job_id,
                    replace_existing=True,
                    minute='*/5'
                )
                logger.info(f"Scheduled job {job_id} to run every 5 minutes")
                
            elif freq == "hour":
                _scheduler.add_job(
                    update_prices_for_account_type,
                    'cron',
                    args=[acc_type],
                    id=job_id,
                    replace_existing=True,
                    minute='0'
                )
                logger.info(f"Scheduled job {job_id} to run every hour at minute 0")
                
            elif freq == "jour":
                _scheduler.add_job(
                    update_prices_for_account_type,
                    'cron',
                    args=[acc_type],
                    id=job_id,
                    replace_existing=True,
                    hour=hour,
                    minute=minute
                )
                logger.info(f"Scheduled job {job_id} to run daily at {hour:02d}:{minute:02d}")
                
            elif freq == "manuel":
                logger.info(f"Job {job_id} is manual. No automatic schedule.")
                
        return True
    except Exception as e:
        logger.error(f"Failed to setup scheduled jobs: {str(e)}")
        return False
    finally:
        if local_db:
            local_db.close()

def execute_recurring_deposit(db: Session, deposit: RecurringDeposit) -> tuple[bool, str]:
    """
    Executes a single recurring deposit:
    - Increases the account's invested_amount
    - If a holding is targeted, increases its quantity and updates its average buy price
    - Returns (success: bool, details: str)
    """
    try:
        # 1. Update account invested amount
        account = db.query(Account).filter(Account.id == deposit.account_id).first()
        if not account:
            return False, f"Compte support (ID {deposit.account_id}) introuvable."
        
        account.invested_amount = (account.invested_amount or 0.0) + deposit.amount
        
        details = ""
        # 2. Update holding if targeted
        if deposit.holding_id:
            holding = db.query(Holding).filter(Holding.id == deposit.holding_id).first()
            if not holding:
                return False, f"Placement (ID {deposit.holding_id}) introuvable."
            
            # Fetch the current price
            current_price = fetch_price_for_holding(
                isin_or_symbol=holding.isin_or_symbol,
                is_manual=holding.is_manual,
                manual_price=holding.manual_price
            )
            
            # Fallback to manual_price if current_price couldn't be fetched
            price_used = current_price
            was_fallback = False
            if (price_used is None or price_used <= 0.0) and holding.manual_price:
                price_used = holding.manual_price
                was_fallback = True
            
            if price_used is not None and price_used > 0.0:
                # Update holding quantity and purchase price
                old_qty = holding.quantity or 0.0
                old_buy_price = holding.buy_price or 0.0
                
                qty_added = deposit.amount / price_used
                new_qty = old_qty + qty_added
                
                # New average cost price
                new_buy_price = (old_qty * old_buy_price + deposit.amount) / new_qty
                
                holding.quantity = new_qty
                holding.buy_price = new_buy_price
                
                # Update cached price if it was an automatic lookup and was successful
                if not holding.is_manual and current_price is not None:
                    holding.manual_price = current_price
                
                details = f"Achat de {qty_added:.4f} parts de {holding.name} au cours de {price_used:.2f} €"
                if was_fallback:
                    details += " (Cours estimé / hors ligne)"
            else:
                return False, f"Impossible de déterminer le cours de l'actif {holding.name} (pas de prix de repli)."
        else:
            account.cash_balance = (account.cash_balance or 0.0) + deposit.amount
            details = f"Crédit libre de {deposit.amount:.2f} € ajouté sur le solde de liquidités."
            
        return True, details
    except Exception as e:
        return False, f"Erreur lors de l'exécution : {str(e)}"

def process_recurring_deposits():
    """
    Checks all active recurring deposits and executes any that are due.
    """
    logger.info("Checking for due recurring deposits...")
    db: Session = SessionLocal()
    try:
        import calendar
        
        # Today's date string
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Get active deposits where next_execution_date <= today
        due_deposits = db.query(RecurringDeposit).filter(
            RecurringDeposit.is_active == True,
            RecurringDeposit.next_execution_date <= today_str
        ).all()
        
        if not due_deposits:
            logger.info("No recurring deposits are due today.")
            return
        
        executed_any = False
        for deposit in due_deposits:
            logger.info(f"Executing recurring deposit: {deposit.name} (Amount: {deposit.amount:.2f} EUR)")
            
            # Execute deposit logic
            success, details = execute_recurring_deposit(db, deposit)
            
            status_str = "success" if success else "failed"
            
            # Create execution history log
            log = RecurringDepositHistory(
                recurring_deposit_id=deposit.id,
                amount=deposit.amount,
                status=status_str,
                details=details,
                execution_date=datetime.utcnow()
            )
            db.add(log)
            
            if success:
                # Advance next execution date
                try:
                    next_dt = datetime.strptime(deposit.next_execution_date, "%Y-%m-%d")
                    today_dt = datetime.utcnow()
                    
                    # Ensure the next execution date is strictly in the future
                    while next_dt.date() <= today_dt.date():
                        if deposit.frequency == "daily":
                            next_dt += timedelta(days=1)
                        elif deposit.frequency == "weekly":
                            next_dt += timedelta(weeks=1)
                        elif deposit.frequency == "monthly":
                            # Safe month adding logic
                            month = next_dt.month
                            year = next_dt.year
                            day = deposit.day_of_period
                            
                            month += 1
                            if month > 12:
                                month = 1
                                year += 1
                            
                            last_day = calendar.monthrange(year, month)[1]
                            target_day = min(day, last_day)
                            next_dt = datetime(year, month, target_day)
                        elif deposit.frequency == "quarterly":
                            # Safe quarterly (3 months) adding logic
                            month = next_dt.month
                            year = next_dt.year
                            day = deposit.day_of_period
                            
                            month += 3
                            if month > 12:
                                year += (month - 1) // 12
                                month = (month - 1) % 12 + 1
                            
                            last_day = calendar.monthrange(year, month)[1]
                            target_day = min(day, last_day)
                            next_dt = datetime(year, month, target_day)
                            
                    deposit.next_execution_date = next_dt.strftime("%Y-%m-%d")
                    deposit.last_execution_date = today_str
                    executed_any = True
                except Exception as ex:
                    logger.error(f"Error updating next date for deposit {deposit.name}: {ex}")
            
            db.commit()
            
        if executed_any:
            # Record a portfolio snapshot to capture the new invested amount & holding quantities
            record_portfolio_snapshot(db)
            
    except Exception as e:
        logger.error(f"Error processing recurring deposits: {e}")
        db.rollback()
    finally:
        db.close()

def start_scheduler():
    """
    Starts the APScheduler background thread.
    """
    global _scheduler
    _scheduler = BackgroundScheduler()
    
    # Initialize DB first if tables don't exist
    init_db()
    
    # Read settings and setup jobs
    db = SessionLocal()
    try:
        setup_jobs_for_all_types(db)
    except Exception as e:
        logger.error(f"Error loading scheduler settings: {e}")
    finally:
        db.close()
        
    _scheduler.start()
    logger.info("Background scheduler started and jobs successfully scheduled.")
    
    # Run a snapshot calculation once on startup in the background to ensure data is updated
    try:
        _scheduler.add_job(update_portfolio_snapshot, 'date', run_date=datetime.now())
    except Exception as e:
        logger.error(f"Failed to queue initial snapshot job: {str(e)}")
        
    # Check recurring deposits once on startup
    try:
        _scheduler.add_job(process_recurring_deposits, 'date', run_date=datetime.now())
    except Exception as e:
        logger.error(f"Failed to queue initial recurring deposits check: {str(e)}")
        
    # Schedule recurring deposits check job to run hourly at minute 5
    try:
        _scheduler.add_job(
            process_recurring_deposits,
            'cron',
            minute='5',
            id="recurring_deposits_hourly",
            replace_existing=True
        )
        logger.info("Scheduled recurring deposits check job to run hourly at minute 5")
    except Exception as e:
        logger.error(f"Failed to schedule recurring deposits job: {str(e)}")
        
    return _scheduler
