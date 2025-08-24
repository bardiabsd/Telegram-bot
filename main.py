# main.py
# ==========================================
# Bot "Aali Plus" — تک‌فایل فشرده‌شده (Final, single-file)
# FastAPI (Webhook) + python-telegram-bot v20 + SQLite(SQLAlchemy)
# ENV: BOT_TOKEN, BASE_URL, ADMIN_IDS (comma), CARD_NUMBER
# ==========================================

import os, asyncio, enum, json, datetime as dt, math, re, uuid, traceback
from typing import Optional, List, Dict, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from pydantic import BaseModel

# FastAPI fallback برای Koyeb/ASGI
try:
    app = FastAPI()
except Exception:
    app = None
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    ReplyKeyboardRemove, InputMediaPhoto, Message, User as TgUser, BotCommand,
)
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters
)

# ==============================
# ENV & Globals
# ==============================
BOT_TOKEN  = os.getenv("BOT_TOKEN","https://live-avivah-bardiabsd-cd8d676a.koyeb.app").strip()
BASE_URL   = os.getenv("BASE_URL", "").strip().rstrip("/")
ADMIN_IDS  = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
CARD_NUMBER = os.getenv("CARD_NUMBER", "6037-********-****-****")

if not BOT_TOKEN or not BASE_URL:
    print("⚠️ Set BOT_TOKEN and BASE_URL envs before run.")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL  = f"{BASE_URL}{WEBHOOK_PATH}"

# ==============================
# DB
# ==============================
Base = declarative_base()
engine = create_engine("sqlite:///bot.db", connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(bind=engine, autocommit=False, autoflush=False))
Base.metadata.create_all(engine, checkfirst=True)
def now():
    return dt.datetime.utcnow()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)  # telegram user id
    username = Column(String(64))
    first_name = Column(String(128))
    created_at = Column(DateTime, default=now, nullable=False)
    wallet = Column(Float, default=0.0, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    total_spent = Column(Float, default=0.0, nullable=False)
    purchases = relationship("Purchase", back_populates="user")
    tickets = relationship("Ticket", back_populates="user")

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)

class Admin(Base):
    __tablename__ = "admins"
    user_id = Column(Integer, primary_key=True)

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)  # e.g. "پلن 1 ماهه 100 گیگ 🇮🇷"
    days = Column(Integer, nullable=False)
    volume_gb = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)  # فروش
    cost_price = Column(Float, default=0.0, nullable=False)  # قیمت تمام‌شده (برای سود خالص)
    # computed stock via relation
    configs = relationship("ConfigItem", back_populates="plan", cascade="all, delete-orphan")

class ConfigItem(Base):
    __tablename__ = "config_repo"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    content_type = Column(String(16), default="text")  # "text"|"photo"
    text_content = Column(Text)  # کانفیگ متنی
    photo_file_id = Column(String(256))  # کانفیگ به صورت عکس (file_id تلگرام)
    created_at = Column(DateTime, default=now, nullable=False)
    plan = relationship("Plan", back_populates="configs")

class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)
    expire_at = Column(DateTime, nullable=False)
    price_paid = Column(Float, default=0.0, nullable=False)
    discount_code = Column(String(64))
    config_payload_id = Column(Integer, ForeignKey("config_repo.id"))  # چه کانفیگی تحویل شد
    active = Column(Boolean, default=True, nullable=False)
    # حفظ برای نمایش در «کانفیگ‌های من»
    delivered_type = Column(String(16), default="text")
    delivered_text = Column(Text)
    delivered_photo_file_id = Column(String(256))
    user = relationship("User", back_populates="purchases")
    plan = relationship("Plan")
    delivered_item = relationship("ConfigItem")

class ReceiptKind(str, enum.Enum):
    TOPUP = "TOPUP"
    DIFF  = "DIFF"
    CARD  = "CARD"  # کارت‌به‌کارت مستقیم خرید پلن

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(8), nullable=False) # ReceiptKind
    status = Column(String(16), default="PENDING", nullable=False)  # PENDING|APPROVED|REJECTED
    text = Column(Text)
    photo_file_id = Column(String(256))
    created_at = Column(DateTime, default=now, nullable=False)
    reviewed_at = Column(DateTime)
    admin_id = Column(Integer)  # reviewer
    # context fields
    plan_id = Column(Integer, ForeignKey("plans.id"))    # برای CARD/DIFF
    price_due = Column(Float, default=0.0, nullable=False)  # مبلغ مورد نیاز
    amount_approved = Column(Float, default=0.0, nullable=False)  # مبلغ تایید شده توسط ادمین (برای TOPUP/DIFF)
    user = relationship("User")
    plan = relationship("Plan")

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)
    status = Column(String(16), default="OPEN")  # OPEN|CLOSED
    subject = Column(String(128))
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")
    user = relationship("User", back_populates="tickets")

class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text)
    created_at = Column(DateTime, default=now, nullable=False)
    ticket = relationship("Ticket", back_populates="messages")
    user = relationship("User")

class Discount(Base):
    __tablename__ = "discounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False)
    percent = Column(Integer, default=0, nullable=False)  # 0..100
    max_uses = Column(Integer, default=0, nullable=False)  # 0=unlimited
    used_count = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime)  # nullable = no expiry
    total_discount_toman = Column(Float, default=0.0, nullable=False)

class StatReset(Base):
    __tablename__ = "stats_reset"
    id = Column(Integer, primary_key=True, autoincrement=True)
    reset_at = Column(DateTime, default=now, nullable=False)

Base.metadata.create_all(engine)

# Ensure default admins in table
def ensure_bootstrap_admins():
    db = SessionLocal()
    try:
        for aid in ADMIN_IDS:
            if not db.query(Admin).get(aid):
                db.add(Admin(user_id=aid))
        # flag users.is_admin = True for ADMIN_IDS
        for aid in ADMIN_IDS:
            u = db.query(User).get(aid)
            if u:
                u.is_admin = True
        # ensure settings: card_number
        if not db.query(Setting).get("card_number"):
            db.add(Setting(key="card_number", value=CARD_NUMBER))
        if db.query(StatReset).count() == 0:
            db.add(StatReset())
        db.commit()
    finally:
        db.close()

ensure_bootstrap_admins()

# ==============================
# Helpers
# ==============================
def money(n: float) -> str:
    n = round(float(n), 2)
    s = f"{int(n):,}".replace(",", "،")
    return f"{s} تومان"

def get_card_number() -> str:
    db = SessionLocal()
    try:
        s = db.query(Setting).get("card_number")
        return s.value if s else CARD_NUMBER
    finally:
        db.close()

def set_card_number(v: str):
    db = SessionLocal()
    try:
        s = db.query(Setting).get("card_number")
        if not s:
            s = Setting(key="card_number", value=v)
            db.add(s)
        else:
            s.value = v
        db.commit()
    finally:
        db.close()

def user_is_admin(uid: int) -> bool:
    db = SessionLocal()
    try:
        if uid in ADMIN_IDS: return True
        a = db.query(Admin).get(uid)
        return a is not None
    finally:
        db.close()

def plans_as_rows(db) -> List[Plan]:
    return db.query(Plan).order_by(Plan.days.asc(), Plan.volume_gb.asc()).all()

def plan_stock(db, plan_id: int) -> int:
    return db.query(ConfigItem).filter(ConfigItem.plan_id==plan_id).count()

def discount_valid(db, code: str) -> Optional[Discount]:
    d = db.query(Discount).filter(Discount.code==code.upper()).first()
    if not d: return None
    if d.expires_at and d.expires_at < now(): return None
    if d.max_uses > 0 and d.used_count >= d.max_uses: return None
    return d

def apply_discount(price: float, percent: int) -> Tuple[float, float]:
    disc = (price * percent) / 100.0
    final = max(0.0, price - disc)
    return final, disc

def top_buyers_since(db, since: Optional[dt.datetime]) -> List[Tuple[User, float, int]]:
    q = db.query(Purchase.user_id, func.sum(Purchase.price_paid), func.count(Purchase.id)).filter(Purchase.active==True)
    if since:
        q = q.filter(Purchase.created_at >= since)
    q = q.group_by(Purchase.user_id).order_by(func.sum(Purchase.price_paid).desc())
    res = []
    for uid, total, cnt in q.limit(5).all():
        u = db.query(User).get(uid)
        if u:
            res.append((u, float(total or 0), int(cnt)))
    return res

def calc_profit(db, since: Optional[dt.datetime]) -> Tuple[float, float, float]:
    q = db.query(Purchase).filter(Purchase.active==True)
    if since: q = q.filter(Purchase.created_at >= since)
    sale = 0.0
    cost = 0.0
    for p in q.all():
        sale += p.price_paid
        if p.plan and p.plan.cost_price:
            cost += p.plan.cost_price
    return sale, cost, sale - cost

def get_stats_since(days: int) -> Tuple[float,float,float,int]:
    db = SessionLocal()
    try:
        since = now() - dt.timedelta(days=days)
        sale,cost,profit = calc_profit(db, since)
        count = db.query(Purchase).filter(Purchase.created_at >= since, Purchase.active==True).count()
        return sale,cost,profit,count
    finally:
        db.close()

def get_stats_all() -> Tuple[float,float,float,int]:
    db = SessionLocal()
    try:
        sale,cost,profit = calc_profit(db, None)
        count = db.query(Purchase).filter(Purchase.active==True).count()
        return sale,cost,profit,count
    finally:
        db.close()

def get_stats_since_reset() -> Tuple[float,float,float,int,dt.datetime]:
    db = SessionLocal()
    try:
        last = db.query(StatReset).order_by(StatReset.reset_at.desc()).first()
        since = last.reset_at if last else None
        sale,cost,profit = calc_profit(db, since)
        count = db.query(Purchase).filter(Purchase.active==True, Purchase.created_at >= (since or dt.datetime.min)).count()
        return sale,cost,profit,count,(since or dt.datetime.min)
    finally:
        db.close()

def reset_stats():
    db = SessionLocal()
    try:
        db.add(StatReset())
        db.commit()
    finally:
        db.close()

# ==============================
# State Machine In-Memory
# ==============================
class Step(str, enum.Enum):
    IDLE="IDLE"
    # خرید
    SELECT_PLAN="SELECT_PLAN"
    PLAN_DETAIL="PLAN_DETAIL"
    APPLY_DISCOUNT="APPLY_DISCOUNT"
    PAY_MENU="PAY_MENU"
    PAY_WALLET_CONFIRM="PAY_WALLET_CONFIRM"
    PAY_DIFF_WAIT_RECEIPT="PAY_DIFF_WAIT_RECEIPT"
    PAY_CARD_WAIT_RECEIPT="PAY_CARD_WAIT_RECEIPT"
    # کیف پول
    TOPUP_WAIT_RECEIPT="TOPUP_WAIT_RECEIPT"
    # تیکت
    TICKET_ENTER_SUBJECT="TICKET_ENTER_SUBJECT"
    TICKET_ENTER_MESSAGE="TICKET_ENTER_MESSAGE"
    # ادمین
    ADMIN_MODE="ADMIN_MODE"
    ADMIN_SET_CARD="ADMIN_SET_CARD"
    ADMIN_ADD_ADMIN="ADMIN_ADD_ADMIN"
    ADMIN_DEL_ADMIN="ADMIN_DEL_ADMIN"
    ADMIN_WALLET_ADJ_USER="ADMIN_WALLET_ADJ_USER"
    ADMIN_WALLET_ADJ_AMOUNT="ADMIN_WALLET_ADJ_AMOUNT"
    ADMIN_DISC_NEW_CODE="ADMIN_DISC_NEW_CODE"
    ADMIN_DISC_NEW_PERCENT="ADMIN_DISC_NEW_PERCENT"
    ADMIN_DISC_NEW_MAXUSES="ADMIN_DISC_NEW_MAXUSES"
    ADMIN_DISC_NEW_EXP="ADMIN_DISC_NEW_EXP"
    ADMIN_BROADCAST="ADMIN_BROADCAST"
    ADMIN_PLAN_NEW_NAME="ADMIN_PLAN_NEW_NAME"
    ADMIN_PLAN_NEW_DAYS="ADMIN_PLAN_NEW_DAYS"
    ADMIN_PLAN_NEW_VOL="ADMIN_PLAN_NEW_VOL"
    ADMIN_PLAN_NEW_PRICE="ADMIN_PLAN_NEW_PRICE"
    ADMIN_PLAN_NEW_COST="ADMIN_PLAN_NEW_COST"
    ADMIN_REPO_SELECT_PLAN="ADMIN_REPO_SELECT_PLAN"
    ADMIN_REPO_ADD_MODE="ADMIN_REPO_ADD_MODE"
    ADMIN_REPO_ADD_TEXT="ADMIN_REPO_ADD_TEXT"
    ADMIN_REPO_ADD_PHOTO="ADMIN_REPO_ADD_PHOTO"
    ADMIN_REPO_BULK_MODE="ADMIN_REPO_BULK_MODE"
    ADMIN_REPO_BULK_DONE="ADMIN_REPO_BULK_DONE"

user_state: Dict[int, Dict] = {}

def st(uid:int) -> Dict:
    if uid not in user_state: user_state[uid]={"step":Step.IDLE}
    return user_state[uid]

def set_step(uid:int, step:Step, **kwargs):
    s = st(uid)
    s["step"]=step
    for k,v in kwargs.items():
        s[k]=v

def clear_step(uid:int):
    user_state[uid]={"step":Step.IDLE}

# ==============================
# UI (Keyboards & Texts)
# ==============================
def kb_main(uid:int, is_admin:bool=False):
    # کاربر: منوی اصلی (کیبورد منو)
    # مرتب + ایموجی‌ها
    user_rows = [
        ["🛍 خرید سرویس", "🧾 کانفیگ‌های من"],
        ["💳 کیف پول", "🎟️ تیکت‌ها"],
        ["ℹ️ آموزش", "📊 آمار فروش"],
    ]
    if is_admin:
        user_rows.append(["🛠 پنل ادمین"])
    return ReplyKeyboardMarkup(user_rows, resize_keyboard=True)

def kb_admin_main():
    rows = [
        ["💳 تغییر شماره کارت", "👤 مدیریت ادمین‌ها"],
        ["📥 رسیدهای در انتظار", "👛 کیف پول کاربر"],
        ["🏷️ کُدهای تخفیف", "📢 اعلان همگانی"],
        ["🧩 مدیریت پلن و مخزن", "📈 آمار فروش"],
        ["🔙 بازگشت به منوی کاربر"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_back_cancel():
    return ReplyKeyboardMarkup([["🔙 بازگشت", "❌ انصراف"]], resize_keyboard=True)

def kb_buy_flow():
    # کارت به کارت + پرداخت با کیف پول + کد تخفیف + برگشت
    rows = [
        ["🧾 اعمال کد تخفیف"],
        ["💼 پرداخت با کیف پول", "🏦 کارت به کارت"],
        ["🔙 بازگشت"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_ticket_menu():
    return ReplyKeyboardMarkup([["🆕 تیکت جدید", "📚 سابقه تیکت‌ها"], ["🔙 بازگشت"]], resize_keyboard=True)

def kb_admin_receipt_actions(receipt_id: int, kind: ReceiptKind):
    # برای TOPUP/DIFF: رد ❌ و تایید + ورود مبلغ ✅
    # برای CARD: رد ❌ و تایید ✅
    if kind in [ReceiptKind.TOPUP, ReceiptKind.DIFF]:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ رد", callback_data=f"rc_rej:{receipt_id}")],
            [InlineKeyboardButton("✅ تایید + ورود مبلغ", callback_data=f"rc_ok_amt:{receipt_id}")]
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ رد", callback_data=f"rc_rej:{receipt_id}")],
            [InlineKeyboardButton("✅ تایید", callback_data=f"rc_ok:{receipt_id}")]
        ])

def kb_repo_plan_actions(pid:int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن کانفیگ متنی", callback_data=f"rp_add_text:{pid}")],
        [InlineKeyboardButton("🖼 افزودن کانفیگ عکس", callback_data=f"rp_add_photo:{pid}")],
        [InlineKeyboardButton("📦 مشاهده موجودی", callback_data=f"rp_view:{pid}")],
        [InlineKeyboardButton("🧹 پاک‌سازی مخزن", callback_data=f"rp_clear:{pid}")]
    ])

def kb_repo_bulk_finish():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ اتمام", callback_data="rp_bulk_done")]])

# ==============================
# Bot (Application)
# ==============================
application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

# ==============================
# Text blocks (خلاصه و مودبانه)
# (توجه: به درخواست شما، متن‌ها خودمونی و ایموجی‌دارند و ثابت نگه داشته شده‌اند)
# ==============================
WELCOME = (
    "سلام رفیق 👋\n"
    "به بات «عالی پلاس» خوش اومدی! 🌟\n"
    "اینجا می‌تونی خیلی راحت و امن سرویس‌هات رو بخری، وضعیت کانفیگ‌هات رو ببینی، با کیف پول پرداخت کنی، "
    "رسید کارت‌به‌کارت بفرستی، تیکت بسازی و کلی امکانات ریز و درشت دیگه 😍\n\n"
    "از منوی پایین یکی از گزینه‌ها رو بزن تا شروع کنیم ✨"
)

HELP_TEXT = (
    "📘 آموزش قدم‌به‌قدم:\n\n"
    "1) از «🛍 خرید سرویس» یکی از پلن‌ها رو انتخاب کن. موجودی هر پلن کنارش نمایش داده میشه.\n"
    "2) می‌تونی «🧾 اعمال کد تخفیف» بزنی و بعدش بین «💼 پرداخت با کیف پول» یا «🏦 کارت به کارت» انتخاب کنی.\n"
    "3) اگه کیف پولت کم بود، ربات خیلی خودمونی بهت میگه چقدر ما‌به‌تفاوت میشه و ازت می‌خواد کارت‌به‌کارت کنی و رسید رو بفرستی.\n"
    "4) تیکت لازم داشتی از «🎟️ تیکت‌ها» استفاده کن؛ می‌تونی سابقه‌ت رو هم ببینی.\n"
    "5) «🧾 کانفیگ‌های من» همیشه کانفیگ‌ها رو برای کپی دوباره نگه می‌داره تا تاریخ انقضا.\n"
    "6) «💳 کیف پول» برای شارژ موجودی با ارسال رسید کارت‌به‌کارت.\n"
    "موفق باشی رفیق! 💙"
)

# ==============================
# Core Handlers
# ==============================
async def ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> User:
    tg: TgUser = update.effective_user
    db = SessionLocal()
    try:
        u = db.query(User).get(tg.id)
        if not u:
            u = User(id=tg.id, username=tg.username, first_name=tg.first_name, is_admin=user_is_admin(tg.id))
            db.add(u); db.commit()
        else:
            # sync admin flag
            was = u.is_admin
            u.is_admin = user_is_admin(tg.id)
            if u.is_admin != was:
                db.commit()
        return u
    finally:
        db.close()

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = await ensure_user(update, context)
    clear_step(u.id)
    await update.effective_message.reply_text(WELCOME, reply_markup=kb_main(u.id, u.is_admin))

async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = await ensure_user(update, context)
    s = st(u.id).get("step", Step.IDLE)

    text = (update.effective_message.text or "").strip()

    # ===== Global navigation =====
    if text == "🔙 بازگشت":
        clear_step(u.id)
        await update.effective_message.reply_text("برگشتیم به منوی قبلی ✨", reply_markup=kb_main(u.id, u.is_admin))
        return
    if text == "❌ انصراف":
        clear_step(u.id)
        await update.effective_message.reply_text("عملیات لغو شد ✅", reply_markup=kb_main(u.id, u.is_admin))
        return

    # ===== Main menu =====
    if text == "🛍 خرید سرویس":
        await show_plans(update, context, u.id)
        return

    if text == "🧾 کانفیگ‌های من":
        await my_configs(update, context, u.id)
        return

    if text == "💳 کیف پول":
        await wallet_menu(update, context, u.id)
        return

    if text == "🎟️ تیکت‌ها":
        await ticket_menu(update, context, u.id)
        return

    if text == "ℹ️ آموزش":
        await update.effective_message.reply_text(HELP_TEXT, reply_markup=kb_main(u.id, u.is_admin))
        return

    if text == "📊 آمار فروش":
        await stats_menu_user(update, context, u.id)
        return

    if text == "🛠 پنل ادمین" and user_is_admin(u.id):
        set_step(u.id, Step.ADMIN_MODE)
        await update.effective_message.reply_text("پنل ادمین باز شد 👨🏻‍💻", reply_markup=kb_admin_main())
        return

    # ===== Admin menu =====
    if s == Step.ADMIN_MODE:
        if text == "🔙 بازگشت به منوی کاربر":
            clear_step(u.id)
            await update.effective_message.reply_text("بازگشت به حالت کاربر ✅", reply_markup=kb_main(u.id, u.is_admin))
            return

        if text == "💳 تغییر شماره کارت":
            set_step(u.id, Step.ADMIN_SET_CARD)
            await update.effective_message.reply_text("شماره کارت جدید رو بفرست (با خط تیره‌های مرتب) 💳", reply_markup=kb_back_cancel())
            return

        if text == "👤 مدیریت ادمین‌ها":
            await admin_manage_admins(update, context, u.id)
            return

        if text == "📥 رسیدهای در انتظار":
            await admin_list_pending_receipts(update, context, u.id)
            return

        if text == "👛 کیف پول کاربر":
            set_step(u.id, Step.ADMIN_WALLET_ADJ_USER)
            st(u.id)["wallet_adj_target"]=None
            await update.effective_message.reply_text("آیدی عددی یا یوزرنیم کاربر رو بفرست 🆔", reply_markup=kb_back_cancel())
            return

        if text == "🏷️ کُدهای تخفیف":
            await admin_discounts_menu(update, context, u.id)
            return

        if text == "📢 اعلان همگانی":
            set_step(u.id, Step.ADMIN_BROADCAST)
            await update.effective_message.reply_text("متن اعلان برای همه‌ی کاربران رو بفرست 📣", reply_markup=kb_back_cancel())
            return

        if text == "🧩 مدیریت پلن و مخزن":
            await admin_plans_and_repo(update, context, u.id)
            return

        if text == "📈 آمار فروش":
            await admin_stats_panel(update, context, u.id)
            return

    # ===== Admin steps =====
    if s == Step.ADMIN_SET_CARD:
        v = text
        if len(v) < 8:
            await update.effective_message.reply_text("شماره کارت معتبر نیست. دوباره بفرست 🙏")
            return
        set_card_number(v)
        clear_step(u.id)
        await update.effective_message.reply_text(f"شماره کارت با موفقیت تغییر کرد ✅\n\n🔢 {get_card_number()}", reply_markup=kb_admin_main())
        return

    if s == Step.ADMIN_WALLET_ADJ_USER:
        target = None
        db = SessionLocal()
        try:
            if text.isdigit():
                target = db.query(User).get(int(text))
            else:
                t = text.lstrip("@")
                target = db.query(User).filter(User.username==t).first()
            if not target:
                await update.effective_message.reply_text("کاربر پیدا نشد 🙏 دوباره آیدی عددی یا یوزرنیم بده.")
                return
            st(u.id)["wallet_adj_target"]=target.id
            set_step(u.id, Step.ADMIN_WALLET_ADJ_AMOUNT)
            await update.effective_message.reply_text(
                f"کاربر: {target.first_name or ''} @{target.username or '-'}\n"
                f"موجودی فعلی: {money(target.wallet)}\n\n"
                f"مبلغ (+ برای افزایش، - برای کاهش) رو بفرست. مثال: 20000 یا -5000",
                reply_markup=kb_back_cancel()
            )
        finally:
            db.close()
        return

    if s == Step.ADMIN_WALLET_ADJ_AMOUNT:
        try:
            amt = float(text)
        except:
            await update.effective_message.reply_text("عدد معتبر بفرست 🙏")
            return
        db = SessionLocal()
        try:
            target_id = st(u.id).get("wallet_adj_target")
            target = db.query(User).get(target_id)
            if not target:
                await update.effective_message.reply_text("کاربر یافت نشد.")
                clear_step(u.id); return
            target.wallet = max(0.0, (target.wallet or 0.0) + amt)
            db.commit()
            await update.effective_message.reply_text(
                f"انجام شد ✅\nموجودی جدید {target.first_name or ''}: {money(target.wallet)}",
                reply_markup=kb_admin_main()
            )
            clear_step(u.id)
        finally:
            db.close()
        return

    if s == Step.ADMIN_DISC_NEW_CODE:
        code = re.sub(r"\s+", "", text).upper()
        if not code or len(code) < 3:
            await update.effective_message.reply_text("کد معتبر نیست. دوباره بفرست.")
            return
        st(u.id)["disc_code"]=code
        set_step(u.id, Step.ADMIN_DISC_NEW_PERCENT)
        await update.effective_message.reply_text("درصد تخفیف رو بفرست (0..100) 📉", reply_markup=kb_back_cancel())
        return

    if s == Step.ADMIN_DISC_NEW_PERCENT:
        try:
            p = int(text)
        except:
            await update.effective_message.reply_text("درصد صحیح بفرست (0..100) 🙏")
            return
        if p<0 or p>100:
            await update.effective_message.reply_text("درصد باید بین 0 و 100 باشه.")
            return
        st(u.id)["disc_percent"]=p
        set_step(u.id, Step.ADMIN_DISC_NEW_MAXUSES)
        await update.effective_message.reply_text("حداکثر دفعات استفاده رو بفرست (0=نامحدود) ♾️", reply_markup=kb_back_cancel())
        return

    if s == Step.ADMIN_DISC_NEW_MAXUSES:
        try:
            mu = int(text)
        except:
            await update.effective_message.reply_text("عدد صحیح بفرست 🙏")
            return
        st(u.id)["disc_max"]=mu
        set_step(u.id, Step.ADMIN_DISC_NEW_EXP)
        await update.effective_message.reply_text("تاریخ انقضا رو بفرست (YYYY-MM-DD) یا بنویس 'بدون' 📅", reply_markup=kb_back_cancel())
        return

    if s == Step.ADMIN_DISC_NEW_EXP:
        exp=None
        if text.strip()!="بدون":
            try:
                exp = dt.datetime.strptime(text.strip(), "%Y-%m-%d")
            except:
                await update.effective_message.reply_text("فرمت تاریخ اشتباهه. مثلا 2025-12-31")
                return
        db=SessionLocal()
        try:
            code=st(u.id)["disc_code"]; percent=st(u.id)["disc_percent"]; mx=st(u.id)["disc_max"]
            if db.query(Discount).filter(Discount.code==code).first():
                await update.effective_message.reply_text("این کد وجود داره. کد دیگری انتخاب کن.")
                return
            d=Discount(code=code, percent=percent, max_uses=mx, expires_at=exp)
            db.add(d); db.commit()
            await update.effective_message.reply_text(f"کد تخفیف ساخته شد ✅\n{code} — {percent}%\nحداکثر استفاده: {mx}\nانقضا: {exp or 'بدون'}",
                                                      reply_markup=kb_admin_main())
            clear_step(u.id)
        finally:
            db.close()
        return

    if s == Step.ADMIN_BROADCAST:
        txt = text
        db=SessionLocal()
        try:
            ids=[u.id for u in db.query(User).all()]
        finally: db.close()
        cnt=0
        for uid in ids:
            try:
                await context.bot.send_message(chat_id=uid, text=f"📣 {txt}")
                cnt+=1
            except: pass
        clear_step(u.id)
        await update.effective_message.reply_text(f"ارسال شد ✅ ({cnt} کاربر)", reply_markup=kb_admin_main())
        return

    if s == Step.ADMIN_PLAN_NEW_NAME:
        st(u.id)["new_plan_name"]=text
        set_step(u.id, Step.ADMIN_PLAN_NEW_DAYS)
        await update.effective_message.reply_text("مدت پلن چند روزه‌ست؟ (عدد) 📆", reply_markup=kb_back_cancel()); return
    if s == Step.ADMIN_PLAN_NEW_DAYS:
        try: d=int(text)
        except: await update.effective_message.reply_text("عدد معتبر بفرست."); return
        st(u.id)["new_plan_days"]=d
        set_step(u.id, Step.ADMIN_PLAN_NEW_VOL)
        await update.effective_message.reply_text("حجم پلن چند گیگابایته؟ (عدد) 📦", reply_markup=kb_back_cancel()); return
    if s == Step.ADMIN_PLAN_NEW_VOL:
        try: v=int(text)
        except: await update.effective_message.reply_text("عدد معتبر بفرست."); return
        st(u.id)["new_plan_vol"]=v
        set_step(u.id, Step.ADMIN_PLAN_NEW_PRICE)
        await update.effective_message.reply_text("قیمت فروش پلن؟ (تومان) 💵", reply_markup=kb_back_cancel()); return
    if s == Step.ADMIN_PLAN_NEW_PRICE:
        try: pr=float(text)
        except: await update.effective_message.reply_text("عدد معتبر بفرست."); return
        st(u.id)["new_plan_price"]=pr
        set_step(u.id, Step.ADMIN_PLAN_NEW_COST)
        await update.effective_message.reply_text("قیمت تمام‌شده پلن؟ (برای محاسبه سود) 🧮", reply_markup=kb_back_cancel()); return
    if s == Step.ADMIN_PLAN_NEW_COST:
        try: cp=float(text)
        except: await update.effective_message.reply_text("عدد معتبر بفرست."); return
        db=SessionLocal()
        try:
            pl=Plan(
                name=st(u.id)["new_plan_name"], days=st(u.id)["new_plan_days"],
                volume_gb=st(u.id)["new_plan_vol"], price=st(u.id)["new_plan_price"],
                cost_price=cp
            )
            db.add(pl); db.commit()
            clear_step(u.id)
            await update.effective_message.reply_text("پلن ساخته شد ✅", reply_markup=kb_admin_main())
        finally: db.close()
        return

    # ===== Tickets =====
    if s == Step.TICKET_ENTER_SUBJECT:
        st(u.id)["ticket_subject"]=text
        set_step(u.id, Step.TICKET_ENTER_MESSAGE)
        await update.effective_message.reply_text("متن پیام تیکت رو بنویس 📝", reply_markup=kb_back_cancel())
        return
    if s == Step.TICKET_ENTER_MESSAGE:
        db=SessionLocal()
        try:
            t=Ticket(user_id=u.id, subject=st(u.id)["ticket_subject"])
            db.add(t); db.flush()
            db.add(TicketMessage(ticket_id=t.id, user_id=u.id, text=text))
            db.commit()
            clear_step(u.id)
            await update.effective_message.reply_text("تیکت ثبت شد ✅ پشتیبانی بزودی پاسخ می‌ده.", reply_markup=kb_main(u.id, u.is_admin))
        finally: db.close()
        return

    # ===== Buy flow =====
    if s == Step.PLAN_DETAIL or s == Step.APPLY_DISCOUNT or s == Step.PAY_MENU:
        await handle_buy_flow_text(update, context, u, text)
        return

    # ===== Wallet topup =====
    if s == Step.TOPUP_WAIT_RECEIPT:
        # انتظار رسید: فقط با عکس/متن هندل میشه؛ برای متن رسید همینجا بگیریم
        rid = await create_receipt(u.id, kind=ReceiptKind.TOPUP, text=text)
        await notify_admins_new_receipt(context, rid)
        clear_step(u.id)
        await update.effective_message.reply_text("مرسی 🙏 رسیدت رسید. بعد از تایید ادمین، کیف پولت شارژ میشه. ✨",
                                                  reply_markup=kb_main(u.id, u.is_admin))
        return

    # اگر به اینجا رسید:
    await update.effective_message.reply_text("متوجه نشدم چی می‌خوای 🤔 لطفاً از منوی پایین انتخاب کن.", reply_markup=kb_main(u.id, u.is_admin))

# ==============================
# Buy Flow Helpers
# ==============================
async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        pls = plans_as_rows(db)
        if not pls:
            await update.effective_message.reply_text("فعلاً پلنی ثبت نشده 🙏", reply_markup=kb_main(uid, user_is_admin(uid)))
            return
        lines=["🛍 لیست پلن‌ها:\n"]
        for p in pls:
            stock = plan_stock(db, p.id)
            lines.append(
                f"• {p.name}\n"
                f"⏳ مدت: {p.days} روز | 🧰 حجم: {p.volume_gb}GB | 💵 قیمت: {money(p.price)} | 📦 موجودی مخزن: {stock}\n"
                f"/plan_{p.id}\n"
            )
        await update.effective_message.reply_text("\n".join(lines))
        set_step(uid, Step.SELECT_PLAN)
    finally: db.close()

async def show_plan_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int, plan_id:int):
    db=SessionLocal()
    try:
        p = db.query(Plan).get(plan_id)
        if not p:
            await update.effective_message.reply_text("پلن پیدا نشد 🙏"); return
        stock = plan_stock(db, plan_id)
        s = st(uid)
        s["selected_plan_id"]=plan_id
        s["applied_discount"]=None
        txt = (
            f"🔘 {p.name}\n\n"
            f"⏳ مدت: {p.days} روز\n🧰 حجم: {p.volume_gb}GB\n"
            f"💵 قیمت: {money(p.price)}\n"
            f"📦 موجودی مخزن: {stock}\n\n"
            f"یه گزینه رو انتخاب کن👇"
        )
        set_step(uid, Step.PLAN_DETAIL)
        await update.effective_message.reply_text(txt, reply_markup=kb_buy_flow())
    finally: db.close()

async def handle_buy_flow_text(update: Update, context: ContextTypes.DEFAULT_TYPE, u:User, text:str):
    s = st(u.id); pid = s.get("selected_plan_id")
    if not pid:
        await update.effective_message.reply_text("اول یک پلن انتخاب کن 🙏"); return
    db=SessionLocal()
    try:
        plan = db.query(Plan).get(pid)
        if not plan:
            await update.effective_message.reply_text("پلن پیدا نشد 🙏"); return

        # اعمال کد تخفیف
        if text == "🧾 اعمال کد تخفیف":
            set_step(u.id, Step.APPLY_DISCOUNT)
            await update.effective_message.reply_text("کد تخفیف رو بفرست (مثلاً OFF30) 🎟️", reply_markup=kb_back_cancel())
            return

        if st(u.id)["step"] == Step.APPLY_DISCOUNT and re.match(r"^[A-Za-z0-9_-]+$", text):
            d = discount_valid(db, text)
            if not d:
                await update.effective_message.reply_text("کد تخفیف نامعتبره یا منقضی شده 😅", reply_markup=kb_buy_flow()); 
                set_step(u.id, Step.PLAN_DETAIL)
                return
            final, disc = apply_discount(plan.price, d.percent)
            s["applied_discount"]={"code":d.code,"percent":d.percent,"final":final,"disc":disc}
            await update.effective_message.reply_text(
                f"کد {d.code} اعمال شد ✅\n"
                f"تخفیف: {money(disc)}\n"
                f"مبلغ جدید: {money(final)}",
                reply_markup=kb_buy_flow()
            )
            set_step(u.id, Step.PLAN_DETAIL)
            return

        # پرداخت با کیف پول
        if text == "💼 پرداخت با کیف پول":
            price = s.get("applied_discount",{}).get("final", plan.price)
            if (u.wallet or 0.0) >= price:
                # خرید مستقیم
                await perform_purchase_deliver(update, context, u.id, plan.id, price, s.get("applied_discount",{}).get("code"))
                clear_step(u.id)
                return
            else:
                diff = price - (u.wallet or 0.0)
                set_step(u.id, Step.PAY_WALLET_CONFIRM)
                await update.effective_message.reply_text(
                    f"کیف پولت {money(u.wallet)} ـه و قیمت این پلن {money(price)}.\n"
                    f"ما‌به‌تفاوت میشه {money(diff)} 💳\n\n"
                    f"اگه اوکی هست کارت‌به‌کارت کن به این شماره:\n"
                    f"🔢 {get_card_number()}\n"
                    f"و بعد «رسید» رو بفرست. 🙏",
                    reply_markup=ReplyKeyboardMarkup([["📤 ارسال رسید ما‌به‌تفاوت"], ["🔙 بازگشت"]], resize_keyboard=True)
                )
                s["diff_amount"]=diff
                return

        if st(u.id)["step"] == Step.PAY_WALLET_CONFIRM and text == "📤 ارسال رسید ما‌به‌تفاوت":
            set_step(u.id, Step.PAY_DIFF_WAIT_RECEIPT)
            await update.effective_message.reply_text("عکس رسید یا متن رسید کارت‌به‌کارت ما‌به‌تفاوت رو بفرست 📸🧾", reply_markup=kb_back_cancel())
            return

        # کارت به کارت مستقیم خرید پلن
        if text == "🏦 کارت به کارت":
            set_step(u.id, Step.PAY_CARD_WAIT_RECEIPT)
            price = s.get("applied_discount",{}).get("final", plan.price)
            await update.effective_message.reply_text(
                f"عالی! لطفاً مبلغ {money(price)} رو کارت‌به‌کارت کن به:\n"
                f"🔢 {get_card_number()}\n\n"
                f"و بعد رسید رو همینجا بفرست (عکس یا متن) 🙏",
                reply_markup=kb_back_cancel()
            )
            s["card_price"]=price
            return

        # اگر چیز دیگری نوشت
        await update.effective_message.reply_text("از گزینه‌های زیر انتخاب کن لطفاً 🙏", reply_markup=kb_buy_flow())
    finally:
        db.close()

async def perform_purchase_deliver(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int, plan_id:int, price_paid:float, disc_code:Optional[str]):
    db=SessionLocal()
    try:
        user = db.query(User).get(uid)
        plan = db.query(Plan).get(plan_id)
        if not plan:
            await update.effective_message.reply_text("پلن یافت نشد 🙏"); return
        stock_item = db.query(ConfigItem).filter(ConfigItem.plan_id==plan_id).order_by(ConfigItem.id.asc()).first()
        if not stock_item:
            await update.effective_message.reply_text("مخزن این پلن فعلاً خالیه 😅 بزودی شارژ میشه.", reply_markup=kb_main(uid, user_is_admin(uid)))
            return
        # کسر از کیف پول در صورت خرید کیف پولی
        if (user.wallet or 0.0) >= price_paid:
            user.wallet = (user.wallet or 0.0) - price_paid
        user.total_spent = (user.total_spent or 0.0) + price_paid

        expire_at = now() + dt.timedelta(days=plan.days)
        p = Purchase(
            user_id=uid, plan_id=plan_id, created_at=now(), expire_at=expire_at,
            price_paid=price_paid, discount_code=disc_code,
            config_payload_id=stock_item.id, active=True,
            delivered_type=stock_item.content_type,
            delivered_text=stock_item.text_content,
            delivered_photo_file_id=stock_item.photo_file_id
        )
        # حذف از مخزن
        db.delete(stock_item)
        # به‌روزرسانی discount usage
        if disc_code:
            d = db.query(Discount).filter(Discount.code==disc_code).first()
            if d:
                d.used_count += 1
                d.total_discount_toman += (plan.price - price_paid)
        db.add(p); db.commit()

        # ارسال به کاربر
        if p.delivered_type == "photo" and p.delivered_photo_file_id:
            await update.effective_message.reply_photo(
                p.delivered_photo_file_id,
                caption=(
                    f"تبریک! خریدت موفق بود 🎉\n"
                    f"کانفیگ برات ارسال شد. (قابل کپی)\n"
                    f"⏳ انقضا: {p.expire_at.date()}"
                ),
                reply_markup=kb_main(uid, user_is_admin(uid))
            )
        else:
            await update.effective_message.reply_text(
                f"تبریک! خریدت موفق بود 🎉\n"
                f"اینم کانفیگ:\n\n"
                f"{p.delivered_text or '—'}\n\n"
                f"⏳ انقضا: {p.expire_at.date()}",
                reply_markup=kb_main(uid, user_is_admin(uid))
            )
    finally:
        db.close()

# ==============================
# Wallet & Receipts
# ==============================
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        u=db.query(User).get(uid)
        await update.effective_message.reply_text(
            f"💳 کیف پول تو: {money(u.wallet)}\n\n"
            f"اگه میخوای شارژ کنی، کارت‌به‌کارت کن به:\n"
            f"🔢 {get_card_number()}\n"
            f"و بعد رسید رو بفرست تا تایید کنیم ✨",
            reply_markup=ReplyKeyboardMarkup([["📤 ارسال رسید شارژ"], ["🔙 بازگشت"]], resize_keyboard=True)
        )
        set_step(uid, Step.TOPUP_WAIT_RECEIPT)
    finally: db.close()

async def my_configs(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        items = db.query(Purchase).filter(Purchase.user_id==uid, Purchase.active==True).order_by(Purchase.created_at.desc()).all()
        if not items:
            await update.effective_message.reply_text("فعلاً کانفیگ فعالی نداری 🙂", reply_markup=kb_main(uid, user_is_admin(uid)))
            return
        for p in items:
            remain = (p.expire_at - now()).days
            base = f"🧾 {p.plan.name}\n⏳ انقضا: {p.expire_at.date()} (حدود {max(0, remain)} روز)"
            if p.delivered_type=="photo" and p.delivered_photo_file_id:
                await update.effective_message.reply_photo(p.delivered_photo_file_id, caption=base)
            else:
                await update.effective_message.reply_text(base + f"\n\n{p.delivered_text or ''}")
    finally: db.close()

async def create_receipt(uid:int, kind:ReceiptKind, text:str=None, photo_file_id:str=None, plan_id:int=None, price_due:float=0.0) -> int:
    db=SessionLocal()
    try:
        r=Receipt(
            user_id=uid, kind=kind.value, text=text, photo_file_id=photo_file_id,
            plan_id=plan_id, price_due=price_due
        )
        db.add(r); db.commit()
        return r.id
    finally: db.close()

async def notify_admins_new_receipt(context: ContextTypes.DEFAULT_TYPE, rid:int):
    db=SessionLocal()
    try:
        r=db.query(Receipt).get(rid); u=db.query(User).get(r.user_id)
        kind_map={"TOPUP":"شارژ کیف پول","DIFF":"پرداخت ما‌به‌تفاوت","CARD":"کارت‌به‌کارت خرید پلن"}
        txt = (
            f"📥 رسید جدید ({kind_map.get(r.kind,r.kind)})\n"
            f"کاربر: {u.first_name or ''} @{u.username or '-'} ({u.id})\n"
            f"زمان: {r.created_at}\n"
            f"پلن: {db.query(Plan).get(r.plan_id).name if r.plan_id else '-'}\n"
            f"مبلغ مورد نیاز/فاکتور: {money(r.price_due)}\n"
            f"وضعیت: {r.status}\n"
            f"نوع رسید: {'عکس' if r.photo_file_id else 'متن'}"
        )
        for admin in db.query(Admin).all():
            try:
                if r.photo_file_id:
                    await context.bot.send_photo(chat_id=admin.user_id, photo=r.photo_file_id, caption=txt, reply_markup=kb_admin_receipt_actions(r.id, ReceiptKind(r.kind)))
                else:
                    await context.bot.send_message(chat_id=admin.user_id, text=f"{txt}\n\nمتن:\n{r.text or '-'}", reply_markup=kb_admin_receipt_actions(r.id, ReceiptKind(r.kind)))
            except: pass
    finally: db.close()

# ==============================
# Tickets
# ==============================
async def ticket_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    await update.effective_message.reply_text("بخش تیکت 🎟️", reply_markup=kb_ticket_menu())

async def ticket_history(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        tks=db.query(Ticket).filter(Ticket.user_id==uid).order_by(Ticket.created_at.desc()).all()
        if not tks:
            await update.effective_message.reply_text("هنوز تیکتی نساختی 🙂", reply_markup=kb_ticket_menu()); return
        for t in tks:
            await update.effective_message.reply_text(f"تیکت #{t.id} — {t.status}\nموضوع: {t.subject or '-'}\nتاریخ: {t.created_at}")
    finally: db.close()

async def ticket_new(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    set_step(uid, Step.TICKET_ENTER_SUBJECT)
    await update.effective_message.reply_text("موضوع تیکت رو بفرست ✍️", reply_markup=kb_back_cancel())

# ==============================
# Stats
# ==============================
async def stats_menu_user(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    s7 = get_stats_since(7)
    s30 = get_stats_since(30)
    sall = get_stats_all()
    msg = (
        "📊 آمار فروش (نمای کاربر):\n\n"
        f"۷ روز اخیر: فروش {money(s7[0])} | تعداد {s7[3]}\n"
        f"۳۰ روز اخیر: فروش {money(s30[0])} | تعداد {s30[3]}\n"
        f"کل: فروش {money(sall[0])} | تعداد {sall[3]}"
    )
    await update.effective_message.reply_text(msg, reply_markup=kb_main(uid, user_is_admin(uid)))

async def admin_stats_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        s7 = get_stats_since(7)
        s30 = get_stats_since(30)
        sa, sb, sc, cnt, since = get_stats_since_reset()
        tb = top_buyers_since(db, since)
        lines = [
            "📈 آمار فروش (ادمین):",
            f"۷ روز: فروش {money(s7[0])} | هزینه {money(s7[1])} | سود {money(s7[2])} | تعداد {s7[3]}",
            f"۳۰ روز: فروش {money(s30[0])} | هزینه {money(s30[1])} | سود {money(s30[2])} | تعداد {s30[3]}",
            f"از ریست ({since.date()}): فروش {money(sa)} | هزینه {money(sb)} | سود {money(sc)} | تعداد {cnt}",
            "\n👑 Top Buyers:"
        ]
        rank=1
        for u, tot, c in tb:
            lines.append(f"{rank}. {u.first_name or ''} @{u.username or '-'} — {money(tot)} ({c} خرید)")
            rank+=1
        lines.append("\nبرای ریست آمار، دستور /reset_stats را بزن (فقط ادمین).")
        await update.effective_message.reply_text("\n".join(lines), reply_markup=kb_admin_main())
    finally: db.close()

# ==============================
# Admin Panels
# ==============================
async def admin_manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        admins = [a.user_id for a in db.query(Admin).all()]
        lines=["👤 مدیریت ادمین‌ها","ادمین‌های فعلی:"]
        for a in admins:
            lines.append(f"• {a} {'(پیش‌فرض)' if a in ADMIN_IDS else ''}")
        lines.append("\nبرای افزودن: /add_admin <user_id>\nبرای حذف: /del_admin <user_id>")
        await update.effective_message.reply_text("\n".join(lines), reply_markup=kb_admin_main())
    finally: db.close()

async def admin_list_pending_receipts(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        rs=db.query(Receipt).filter(Receipt.status=="PENDING").order_by(Receipt.created_at.asc()).all()
        if not rs:
            await update.effective_message.reply_text("چیزی تو صف رسیدگی نیست ✅", reply_markup=kb_admin_main()); return
        for r in rs:
            u=db.query(User).get(r.user_id)
            txt = (
                f"📥 رسید #{r.id} — {r.kind}\n"
                f"کاربر: {u.first_name or ''} @{u.username or '-'} ({u.id})\n"
                f"زمان: {r.created_at}\n"
                f"پلن: {db.query(Plan).get(r.plan_id).name if r.plan_id else '-'}\n"
                f"مبلغ مورد نیاز/فاکتور: {money(r.price_due)}\n"
                f"وضعیت: {r.status}\n"
                f"نوع رسید: {'عکس' if r.photo_file_id else 'متن'}"
            )
            if r.photo_file_id:
                await update.effective_message.reply_photo(r.photo_file_id, caption=txt, reply_markup=kb_admin_receipt_actions(r.id, ReceiptKind(r.kind)))
            else:
                await update.effective_message.reply_text(f"{txt}\n\nمتن:\n{r.text or '-'}", reply_markup=kb_admin_receipt_actions(r.id, ReceiptKind(r.kind)))
    finally: db.close()

async def admin_discounts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        ds=db.query(Discount).order_by(Discount.id.desc()).all()
        lines=["🏷️ کدهای تخفیف:"]
        if not ds:
            lines.append("فعلاً هیچ کدی ثبت نشده.")
        else:
            for d in ds:
                lines.append(f"• {d.code} — {d.percent}% | استفاده: {d.used_count}/{d.max_uses or '∞'} | انقضا: {d.expires_at or 'بدون'} | جمع تخفیف: {money(d.total_discount_toman)}")
        lines.append("\nساخت کد جدید: /new_discount")
        await update.effective_message.reply_text("\n".join(lines), reply_markup=kb_admin_main())
    finally: db.close()

async def admin_plans_and_repo(update: Update, context: ContextTypes.DEFAULT_TYPE, uid:int):
    db=SessionLocal()
    try:
        pls = plans_as_rows(db)
        if not pls:
            await update.effective_message.reply_text("پلنی موجود نیست. /new_plan برای ساخت پلن.", reply_markup=kb_admin_main()); return
        for p in pls:
            stock=plan_stock(db, p.id)
            await update.effective_message.reply_text(
                f"🧩 {p.name}\n"
                f"⏳ {p.days} روز | 🧰 {p.volume_gb}GB | 💵 {money(p.price)} | 📦 موجودی مخزن: {stock}",
                reply_markup=kb_repo_plan_actions(p.id)
            )
        await update.effective_message.reply_text("ساخت پلن جدید: /new_plan", reply_markup=kb_admin_main())
    finally: db.close()

# ==============================
# Commands (ادمین)
# ==============================
async def cmd_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = await ensure_user(update, context)
    if not user_is_admin(u.id):
        return
    if not context.args:
        await update.effective_message.reply_text("استفاده: /add_admin <user_id>")
        return
    try:
        uid=int(context.args[0])
    except:
        await update.effective_message.reply_text("user_id نامعتبر.")
        return
    if uid in ADMIN_IDS:
        await update.effective_message.reply_text("ادمین پیش‌فرض رو نمی‌تونی اضافه/حذف کنی؛ خودش ادمینه.")
        return
    db=SessionLocal()
    try:
        if db.query(Admin).get(uid):
            await update.effective_message.reply_text("قبلاً ادمین شده.")
        else:
            db.add(Admin(user_id=uid)); db.commit()
            usr=db.query(User).get(uid)
            if usr:
                usr.is_admin=True; db.commit()
            await update.effective_message.reply_text("ادمین افزوده شد ✅")
    finally: db.close()

async def cmd_del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = await ensure_user(update, context)
    if not user_is_admin(u.id): return
    if not context.args:
        await update.effective_message.reply_text("استفاده: /del_admin <user_id>")
        return
    try:
        uid=int(context.args[0])
    except:
        await update.effective_message.reply_text("user_id نامعتبر."); return
    if uid in ADMIN_IDS:
        await update.effective_message.reply_text("❌ حذف ادمین پیش‌فرض مجاز نیست.")
        return
    db=SessionLocal()
    try:
        a=db.query(Admin).get(uid)
        if not a:
            await update.effective_message.reply_text("ادمین نبود.")
        else:
            db.delete(a); db.commit()
            usr=db.query(User).get(uid)
            if usr:
                usr.is_admin=False; db.commit()
            await update.effective_message.reply_text("ادمین حذف شد ✅")
    finally: db.close()

async def cmd_new_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=await ensure_user(update, context)
    if not user_is_admin(u.id): return
    set_step(u.id, Step.ADMIN_DISC_NEW_CODE)
    await update.effective_message.reply_text("کد تخفیف رو بفرست (مثلاً OFF30) 🎟️", reply_markup=kb_back_cancel())

async def cmd_new_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=await ensure_user(update, context)
    if not user_is_admin(u.id): return
    set_step(u.id, Step.ADMIN_PLAN_NEW_NAME)
    await update.effective_message.reply_text("اسم پلن رو بفرست ✍️", reply_markup=kb_back_cancel())

async def cmd_reset_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=await ensure_user(update, context)
    if not user_is_admin(u.id): return
    reset_stats()
    await update.effective_message.reply_text("آمار ریست شد ✅", reply_markup=kb_admin_main())

# ==============================
# Callback Queries (رسیدها، مخزن)
# ==============================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()
    u = await ensure_user(update, context)
    if data.startswith("rc_rej:"):
        rid=int(data.split(":")[1])
        await admin_receipt_reject(update, context, u.id, rid)
        return
    if data.startswith("rc_ok_amt:"):
        rid=int(data.split(":")[1])
        await admin_receipt_ok_amount(update, context, u.id, rid)
        return
    if data.startswith("rc_ok:"):
        rid=int(data.split(":")[1])
        await admin_receipt_ok(update, context, u.id, rid)
        return
    if data.startswith("rp_add_text:"):
        pid=int(data.split(":")[1])
        set_step(u.id, Step.ADMIN_REPO_ADD_TEXT); st(u.id)["repo_plan_id"]=pid
        await q.message.reply_text("متن کانفیگ رو بفرست (هر پیام = یک کانفیگ). برای پایان روی «✅ اتمام» بزن.", reply_markup=kb_repo_bulk_finish()); 
        return
    if data=="rp_bulk_done":
        clear_step(u.id)
        await q.message.reply_text("افزودن پایان یافت ✅", reply_markup=kb_admin_main()); return
    if data.startswith("rp_add_photo:"):
        pid=int(data.split(":")[1])
        set_step(u.id, Step.ADMIN_REPO_ADD_PHOTO); st(u.id)["repo_plan_id"]=pid
        await q.message.reply_text("عکس کانفیگ رو بفرست (هر عکس = یک کانفیگ). برای پایان روی «✅ اتمام» بزن.", reply_markup=kb_repo_bulk_finish()); 
        return
    if data.startswith("rp_view:"):
        pid=int(data.split(":")[1]); await repo_view(update, context, pid); return
    if data.startswith("rp_clear:"):
        pid=int(data.split(":")[1]); await repo_clear(update, context, pid); return

async def admin_receipt_reject(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id:int, rid:int):
    db=SessionLocal()
    try:
        r=db.query(Receipt).get(rid)
        if not r or r.status!="PENDING": return
        r.status="REJECTED"; r.reviewed_at=now(); r.admin_id=admin_id
        db.commit()
        try:
            await context.bot.send_message(chat_id=r.user_id, text="😕 رسیدت رد شد. در صورت ابهام با پشتیبانی در ارتباط باش. 🙏")
        except: pass
        await update.effective_message.reply_text("رد شد ✅ (کاربر مطلع شد)")
    finally: db.close()

async def admin_receipt_ok(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id:int, rid:int):
    # برای CARD (خرید مستقیم) — بدون ورود مبلغ
    db=SessionLocal()
    try:
        r=db.query(Receipt).get(rid)
        if not r or r.status!="PENDING": return
        if r.kind!="CARD":
            await update.effective_message.reply_text("این دکمه فقط برای کارت‌به‌کارت مستقیمه."); return
        # تحویل پلن
        await fake_update_for_delivery(context, r.user_id, r.plan_id, r.price_due)
        r.status="APPROVED"; r.reviewed_at=now(); r.admin_id=admin_id
        db.commit()
        await update.effective_message.reply_text("تایید شد ✅ کانفیگ ارسال گردید.")
    finally: db.close()

async def admin_receipt_ok_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id:int, rid:int):
    # برای TOPUP و DIFF — با ورود مبلغ
    db=SessionLocal()
    try:
        r=db.query(Receipt).get(rid)
        if not r or r.status!="PENDING": return
        if r.kind not in ["TOPUP","DIFF"]:
            await update.effective_message.reply_text("این دکمه مخصوص شارژ کیف پول/ما‌به‌تفاوته."); return
        # از ادمین می‌خواهیم مبلغ تاییدی را بفرستد — با next message (با state transient داخل memory برای ادمین)
        s = st(admin_id)
        s["enter_amount_for_receipt"]=rid
        await update.effective_message.reply_text("مبلغ تایید شده را ارسال کنید (تومان):")
    finally: db.close()

async def repo_view(update: Update, context: ContextTypes.DEFAULT_TYPE, pid:int):
    db=SessionLocal()
    try:
        p=db.query(Plan).get(pid); cnt=plan_stock(db, pid)
        await update.effective_message.reply_text(f"📦 مخزن {p.name}\nموجودی: {cnt}")
    finally: db.close()

async def repo_clear(update: Update, context: ContextTypes.DEFAULT_TYPE, pid:int):
    db=SessionLocal()
    try:
        db.query(ConfigItem).filter(ConfigItem.plan_id==pid).delete()
        db.commit()
        await update.effective_message.reply_text("مخزن پاک‌سازی شد ✅")
    finally: db.close()

async def fake_update_for_delivery(context: ContextTypes.DEFAULT_TYPE, uid:int, plan_id:int, price:float):
    # برای رویدادهای تایید دستی کارت‌به‌کارت یا ما‌به‌تفاوت پس از تایید، تحویل داده شود.
    # یک پیام به خود کاربر می‌فرستیم و از perform_purchase_deliver استفاده می‌کنیم
    # اینجا نمی‌دانیم discount_code؛ None
    class DummyUpdate:
        effective_message: Message
        def __init__(self, bot, chat_id):
            self.effective_message = type("M", (), {})()
            async def send_message(text, reply_markup=None):
                await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            async def reply_text(text, reply_markup=None):
                await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            async def reply_photo(photo, caption=None, reply_markup=None):
                await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, reply_markup=reply_markup)
            self.effective_message.reply_text = reply_text
            self.effective_message.reply_photo = reply_photo
    dummy = DummyUpdate(context.bot, uid)
    await perform_purchase_deliver(dummy, context, uid, plan_id, price, None)

# ==============================
# Photo/Text Receipts (Message handlers)
# ==============================
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = await ensure_user(update, context)
    s = st(u.id)
    ph = update.message.photo
    if not ph:
        return
    file_id = ph[-1].file_id

    # حالت‌های انتظار رسید:
    if s.get("step") == Step.TOPUP_WAIT_RECEIPT:
        rid = await create_receipt(u.id, kind=ReceiptKind.TOPUP, photo_file_id=file_id)
        await notify_admins_new_receipt(context, rid)
        clear_step(u.id)
        await update.effective_message.reply_text("مرسی 🙏 رسیدت رسید. بعد از تایید ادمین، کیف پولت شارژ میشه. ✨", reply_markup=kb_main(u.id, u.is_admin))
        return

    if s.get("step") == Step.PAY_DIFF_WAIT_RECEIPT:
        pid = s.get("selected_plan_id"); amt = s.get("diff_amount", 0.0)
        rid = await create_receipt(u.id, kind=ReceiptKind.DIFF, photo_file_id=file_id, plan_id=pid, price_due=amt)
        await notify_admins_new_receipt(context, rid)
        clear_step(u.id)
        await update.effective_message.reply_text("رسید ما‌به‌تفاوت دریافت شد 🙏 بعد از تایید ادمین، خرید تکمیل میشه. ✨", reply_markup=kb_main(u.id, u.is_admin))
        return

    if s.get("step") == Step.PAY_CARD_WAIT_RECEIPT:
        pid = s.get("selected_plan_id"); price = s.get("card_price", 0.0)
        rid = await create_receipt(u.id, kind=ReceiptKind.CARD, photo_file_id=file_id, plan_id=pid, price_due=price)
        await notify_admins_new_receipt(context, rid)
        clear_step(u.id)
        await update.effective_message.reply_text("رسید کارت‌به‌کارت دریافت شد 🙏 به‌محض تایید، کانفیگ برات ارسال میشه. ✨", reply_markup=kb_main(u.id, u.is_admin))
        return

    # افزودن کانفیگ عکس در مخزن
    if s.get("step") == Step.ADMIN_REPO_ADD_PHOTO and user_is_admin(u.id):
        pid = s.get("repo_plan_id")
        if not pid:
            await update.effective_message.reply_text("ابتدا پلن را انتخاب کن.")
            return
        db=SessionLocal()
        try:
            db.add(ConfigItem(plan_id=pid, content_type="photo", photo_file_id=file_id))
            db.commit()
            await update.effective_message.reply_text("یک کانفیگ عکس اضافه شد ✅ (برای پایان «✅ اتمام»)")
        finally: db.close()
        return

async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # همه متنی‌ها اول برن fallback_text (استیت‌ماشین مدیریت می‌کند)
    await fallback_text(update, context)

# ==============================
# Special -> Admin entering amount (for receipts)
# ==============================
async def on_admin_enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = await ensure_user(update, context)
    s = st(u.id)
    key="enter_amount_for_receipt"
    if key not in s: 
        return
    rid = s[key]
    try:
        amt = float((update.effective_message.text or "0").strip())
    except:
        await update.effective_message.reply_text("عدد معتبر بفرست 🙏")
        return
    db=SessionLocal()
    try:
        r=db.query(Receipt).get(rid)
        if not r or r.status!="PENDING":
            del s[key]; return
        # اعمال تأثیر: برای TOPUP -> افزایش کیف پول، برای DIFF -> تکمیل خرید
        if r.kind=="TOPUP":
            uu=db.query(User).get(r.user_id)
            uu.wallet = max(0.0, (uu.wallet or 0.0) + amt)
            r.amount_approved = amt
            r.status="APPROVED"; r.reviewed_at=now(); r.admin_id=u.id
            db.commit()
            try:
                await context.bot.send_message(chat_id=r.user_id, text=f"شارژ کیف پول تایید شد ✅\nمبلغ: {money(amt)}\nموجودی جدید: {money(uu.wallet)}")
            except: pass
            await update.effective_message.reply_text("شارژ کیف پول انجام شد ✅")
        elif r.kind=="DIFF":
            # تکمیل خرید با تحویل کانفیگ؛ مبلغ تاییدی اهمیتی برای کسر ندارد چون ما‌به‌تفاوت کارت به کارت بوده
            r.amount_approved = amt
            await fake_update_for_delivery(context, r.user_id, r.plan_id, r.price_due + 0.0)  # قیمت نهایی همان اختلاف + موجودی قبلی که قبلاً کسر نمی‌شود؛ سناریو: خرید با کیف پول ناقص + diff کارتی -> تحویل کامل
            r.status="APPROVED"; r.reviewed_at=now(); r.admin_id=u.id
            db.commit()
            await update.effective_message.reply_text("پرداخت ما‌به‌تفاوت تایید شد ✅ و کانفیگ ارسال گردید.")
        del s[key]
    finally:
        db.close()

# ==============================
# Commands (User shortcuts)
# ==============================
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message.text.strip()
    m = m.replace("/","")
    if not m.startswith("plan_"): return
    try:
        pid=int(m.split("_")[1])
    except: return
    await show_plan_detail(update, context, update.effective_user.id, pid)

# ==============================
# Message Router for specific text buttons inside sections
# ==============================
async def router_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.effective_message.text or "").strip()

    if text=="🆕 تیکت جدید":
        await ticket_new(update, context, update.effective_user.id); return
    if text=="📚 سابقه تیکت‌ها":
        await ticket_history(update, context, update.effective_user.id); return

# ==============================
# Expiry notifier (background)
# ==============================
async def expiry_notifier(app: Application):
    while True:
        try:
            db=SessionLocal()
            try:
                ps = db.query(Purchase).filter(Purchase.active==True).all()
                for p in ps:
                    days_left = (p.expire_at - now()).days
                    msg=None
                    if days_left in [5,3,1]:
                        msg=f"یادآوری ⏳\nکانفیگ {p.plan.name} در {days_left} روز آینده منقضی میشه."
                    elif days_left < 0:
                        p.active=False
                        msg=f"کانفیگ {p.plan.name} منقضی شد و از «کانفیگ‌های من» حذف شد. ❤️"
                        db.commit()
                    if msg:
                        try: await app.bot.send_message(chat_id=p.user_id, text=msg)
                        except: pass
            finally:
                db.close()
        except: pass
        await asyncio.sleep(3600)  # هر ساعت چک کن

# ==============================
# FastAPI & Webhook
# ==============================
api = FastAPI()

class TgUpdate(BaseModel):
    update_id: int

@api.on_event("startup")
async def on_startup():
    # مهم: initialize قبل از start برای HTTPXRequest
    await application.initialize()
    await application.bot.set_webhook(WEBHOOK_URL, allowed_updates=["message","callback_query"])
    await application.start()
    # set commands (optional)
    try:
        await application.bot.set_my_commands([
            BotCommand("start","شروع/ری‌استارت"),
            BotCommand("new_plan","ساخت پلن (ادمین)"),
            BotCommand("new_discount","کد تخفیف جدید (ادمین)"),
            BotCommand("add_admin","افزودن ادمین (ادمین)"),
            BotCommand("del_admin","حذف ادمین (ادمین)"),
            BotCommand("reset_stats","ریست آمار (ادمین)"),
        ])
    except: pass
    # run notifier
    application.create_task(expiry_notifier(application))
    print("✅ Bot started & webhook set.")

@api.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()

@api.post(WEBHOOK_PATH)
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, application.bot)
    try:
        await application.process_update(update)
    except Exception as e:
        traceback.print_exc()
    return JSONResponse({"ok": True})

@api.get("/")
async def health():
    return PlainTextResponse("OK")

# ==============================
# PTB Handlers registration
# ==============================
application.add_handler(CommandHandler("start", start_cmd))
application.add_handler(CommandHandler("add_admin", cmd_add_admin))
application.add_handler(CommandHandler("del_admin", cmd_del_admin))
application.add_handler(CommandHandler("new_discount", cmd_new_discount))
application.add_handler(CommandHandler("new_plan", cmd_new_plan))
application.add_handler(CommandHandler("reset_stats", cmd_reset_stats))
application.add_handler(MessageHandler(filters.Regex(r"^/plan_\d+$"), cmd_plan))

# دکمه‌های منوها
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router_buttons))

# متن‌ها (fallback/state)
application.add_handler(MessageHandler(filters.PHOTO, on_photo))
# مسیر ویژه ورود مبلغ تایید رسید (ادمین)
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_admin_enter_amount))
# بقیه‌ی متنی‌ها
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_message))

application.add_handler(CallbackQueryHandler(on_callback))

# ==============================
# Run (Uvicorn expects `api` as ASGI app)
# ==============================
# uvicorn main:api --host 0.0.0.0 --port 8000
