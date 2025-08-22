# models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

# جدول کاربران
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, unique=True, index=True)  # آیدی تلگرام
    username = Column(String, nullable=True)
    balance = Column(Float, default=0.0)  # موجودی کاربر

# جدول کیف پول
class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)  # لینک به کاربر
    address = Column(String, unique=True, index=True)

# جدول تنظیمات (برای ادمین)
class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True)      # مثل: "button_deposit"
    value = Column(Boolean, default=True)  # روشن/خاموش بودن

# جدول لاگ ترا
