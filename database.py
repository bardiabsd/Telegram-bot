from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

# مسیر دیتابیس SQLite
DATABASE_URL = "sqlite:///database.sqlite3"

# ساخت Engine
engine = create_engine(DATABASE_URL, echo=False)

# Base برای مدل‌ها
Base = declarative_base()

# مدل کاربر
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    wallet = Column(Float, default=0.0, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    total_spent = Column(Float, default=0.0, nullable=False)

# مدل کد تخفیف
class DiscountCode(Base):
    __tablename__ = "discount_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False)
    percent = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# مدل تراکنش (شارژ کیف پول و خرید)
class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(String(20), nullable=False)  # deposit یا purchase
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# ساخت جداول (فقط اگه وجود نداشتن)
Base.metadata.create_all(engine, checkfirst=True)

# ساخت Session
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Dependency برای گرفتن سشن
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
