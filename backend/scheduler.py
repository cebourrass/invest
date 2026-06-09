import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Account, Holding, PortfolioHistory, SystemSetting, init_db
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
        if not holdings:
            logger.info("No holdings found in database. Skipping snapshot.")
            return

        total_value = 0.0
        total_cost = 0.0

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
            total_cost=total_cost
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
    if not holdings:
        return
    total_value = 0.0
    total_cost = 0.0
    for holding in holdings:
        price = holding.manual_price or 0.0
        total_value += holding.quantity * price
        total_cost += holding.quantity * holding.buy_price
    
    total_gain = total_value - total_cost
    snapshot = PortfolioHistory(
        timestamp=datetime.utcnow(),
        total_value=total_value,
        total_gain=total_gain,
        total_cost=total_cost
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
        
    return _scheduler
