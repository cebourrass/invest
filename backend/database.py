import datetime
import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Database path (stored in the same directory as the project)
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "portfolio.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # PEA, PER, Assurance Vie, Compte-Titres, Autre
    creation_date = Column(String, nullable=True)  # Format: YYYY-MM-DD

    holdings = relationship("Holding", back_populates="account", cascade="all, delete-orphan")

class Holding(Base):
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    name = Column(String, nullable=False)
    isin_or_symbol = Column(String, nullable=True)
    quantity = Column(Float, nullable=False, default=0.0)
    buy_price = Column(Float, nullable=False, default=0.0)  # Purchase price unit in EUR
    is_manual = Column(Boolean, default=False)
    manual_price = Column(Float, nullable=True)  # Used if is_manual is True or fallback needed
    category = Column(String, nullable=False, default="Autre")  # ETF, OPCVM, Actions, Immobilier, Crypto, Fonds Euros, Cash

    account = relationship("Account", back_populates="holdings")

class PortfolioHistory(Base):
    __tablename__ = "portfolio_history"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    total_value = Column(Float, nullable=False)
    total_gain = Column(Float, nullable=False)
    total_cost = Column(Float, nullable=False)

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)

def init_db():
    # Run manual migration first to ensure new column exists in SQLite
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if inspector.has_table("accounts"):
        columns = [c['name'] for c in inspector.get_columns('accounts')]
        if 'creation_date' not in columns:
            with engine.begin() as conn:
                from sqlalchemy import text
                conn.execute(text("ALTER TABLE accounts ADD COLUMN creation_date VARCHAR"))

    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Seed settings first
        if db.query(SystemSetting).count() == 0:
            db.add_all([
                SystemSetting(key="update_hour", value="20"),
                SystemSetting(key="update_minute", value="00"),
                SystemSetting(key="update_interval", value="daily")
            ])
            db.commit()

        # Let's seed with some sample accounts if none exist, so the user has an immediate starting point
        if db.query(Account).count() == 0:
            pea = Account(name="PEA EasyBourse", type="PEA")
            av = Account(name="Assurance Vie Linxea", type="Assurance Vie", creation_date="2020-01-01")
            per = Account(name="PER Suravenir", type="PER")
            
            db.add_all([pea, av, per])
            db.commit()
            
            # Seed holdings
            db.refresh(pea)
            db.refresh(av)
            db.refresh(per)
            
            # LU1681043599 is Amundi MSCI World (CW8)
            h1 = Holding(
                account_id=pea.id, 
                name="Amundi MSCI World ETF (CW8)", 
                isin_or_symbol="LU1681043599", 
                quantity=10, 
                buy_price=450.0, 
                is_manual=False, 
                category="ETF"
            )
            # FR0010096395 is LVMH
            h2 = Holding(
                account_id=pea.id, 
                name="LVMH", 
                isin_or_symbol="FR0000121014", 
                quantity=2, 
                buy_price=750.0, 
                is_manual=False, 
                category="Actions"
            )
            # A manual fund for AV (like Fonds Euros)
            h3 = Holding(
                account_id=av.id, 
                name="Suravenir Rendement (Fonds Euros)", 
                isin_or_symbol="", 
                quantity=5000, 
                buy_price=1.0, 
                is_manual=True, 
                manual_price=1.0, 
                category="Fonds Euros"
            )
            
            db.add_all([h1, h2, h3])
            db.commit()
            
            # Initial history record
            hist = PortfolioHistory(
                timestamp=datetime.datetime.utcnow() - datetime.timedelta(days=1),
                total_value=11000.0,
                total_gain=500.0,
                total_cost=10500.0
            )
            db.add(hist)
            db.commit()
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
