import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Holding, PortfolioHistory, SystemSetting, init_db
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

def reschedule_portfolio_job(hour: int, minute: int, interval: str):
    """
    Dynamically update the triggers for the background job without restarting the server.
    """
    global _scheduler
    if not _scheduler:
        logger.warning("Rescheduling failed: Scheduler is not active.")
        return False
        
    try:
        # Remove old job
        try:
            _scheduler.remove_job("portfolio_daily_snapshot")
        except Exception:
            pass # Job might not exist
            
        trigger_args = {
            "hour": hour,
            "minute": minute
        }
        if interval == "weekly":
            trigger_args["day_of_week"] = "mon"
            
        _scheduler.add_job(
            update_portfolio_snapshot,
            'cron',
            id="portfolio_daily_snapshot",
            replace_existing=True,
            **trigger_args
        )
        logger.info(f"Dynamically rescheduled snapshot job: {interval} at {hour:02d}:{minute:02d}")
        return True
    except Exception as e:
        logger.error(f"Failed to reschedule snapshot job: {str(e)}")
        return False

def start_scheduler():
    """
    Starts the APScheduler background thread.
    """
    global _scheduler
    _scheduler = BackgroundScheduler()
    
    # Read settings from DB
    db = SessionLocal()
    try:
        hour_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_hour").first()
        min_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_minute").first()
        int_setting = db.query(SystemSetting).filter(SystemSetting.key == "update_interval").first()
        
        hour = int(hour_setting.value) if hour_setting else 20
        minute = int(min_setting.value) if min_setting else 0
        interval = int_setting.value if int_setting else "daily"
    except Exception as e:
        logger.error(f"Error loading scheduler settings: {e}")
        hour = 20
        minute = 0
        interval = "daily"
    finally:
        db.close()
        
    trigger_args = {
        "hour": hour,
        "minute": minute
    }
    if interval == "weekly":
        trigger_args["day_of_week"] = "mon"

    _scheduler.add_job(
        update_portfolio_snapshot, 
        'cron', 
        id="portfolio_daily_snapshot",
        replace_existing=True,
        **trigger_args
    )
    
    _scheduler.start()
    logger.info(f"Background scheduler started. Portfolio snapshots will run {interval} at {hour:02d}:{minute:02d}.")
    
    # Run a snapshot calculation once on startup in the background to ensure data is updated
    try:
        _scheduler.add_job(update_portfolio_snapshot, 'date', run_date=datetime.now())
    except Exception as e:
        logger.error(f"Failed to queue initial snapshot job: {str(e)}")
        
    return _scheduler
