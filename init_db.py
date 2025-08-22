from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import os

# گرفتن آدرس دیتابیس از متغیر محیطی
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data.db")

engine = create_engine(DATABASE_URL)
Base = declarative_base()


# جدول کاربران
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)   # آیدی عددی کاربر (از تلگرام)
    username = Column(String, nullable=True)
    wallet_balance = Column(Float, default=0.0)
    is_banned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    purchases = relationship("Purchase", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    tickets = relationship("Ticket", back_populates="user")


# جدول پلن‌ها
class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    duration_days = Column(Integer, nullable=False)
    traffic_gb = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    active = Column(Boolean, default=True)

    configs = relationship("Config", back_populates="plan")
    purchases = relationship("Purchase", back_populates="plan")


# جدول کانفیگ‌های هر پلن (مخزن)
class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"))
    content = Column(Text, nullable=False)   # متن کانفیگ
    image_url = Column(String, nullable=True)  # اگه عکس هم داشته باشه
    used = Column(Boolean, default=False)

    plan = relationship("Plan", back_populates="configs")


# خریدهای کاربران
class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    plan_id = Column(Integer, ForeignKey("plans.id"))
    final_price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expire_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="purchases")
    plan = relationship("Plan", back_populates="purchases")


# تراکنش‌های کیف پول
class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)  # charge / purchase / admin_adjust
    created_at = Column(DateTime, default=datetime.utcnow)
    description = Column(Text, nullable=True)

    user = relationship("User", back_populates="transactions")


# رسیدها (برای کارت به کارت یا شارژ)
class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    image_url = Column(String, nullable=True)
    purpose = Column(String, nullable=False)  # wallet / purchase
    amount = Column(Float, nullable=True)
    status = Column(String, default="pending")  # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.utcnow)


# تیکت پشتیبانی
class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subject = Column(String, nullable=False)
    status = Column(String, default="open")  # open / closed
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="tickets")
    messages = relationship("TicketMessage", back_populates="ticket")


# پیام‌های داخل تیکت
class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    sender = Column(String, nullable=False)  # user / admin
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="messages")


# کدهای تخفیف
class DiscountCode(Base):
    __tablename__ = "discount_codes"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    percent = Column(Integer, nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)  # None = همه پلن‌ها
    expire_at = Column(DateTime, nullable=True)
    max_usage = Column(Integer, nullable=True)
    used_count = Column(Integer, default=0)
    active = Column(Boolean, default=True)


# ساخت دیتابیس
def init_db():
    Base.metadata.create_all(engine)
    print("✅ Database initialized successfully!")


if __name__ == "__main__":
    init_db()
