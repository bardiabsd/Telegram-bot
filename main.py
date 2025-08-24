# -*- coding: utf-8 -*-
# ====== AaliPlus (Perfect) — Version 1.0.0-final ======
# تمام امکاناتی که گفتی بدون حذف، با دیباگ‌های لازم:
# - منوی اصلی کاربر با دکمه‌ها: خرید سرویس، کانفیگ‌های من، کیف پول، تیکت‌ها، آموزش
# - نمایش پلن‌ها، جزئیات پلن، خرید با کیف پول، کارت به کارت، اعمال کد تخفیف، انصراف/بازگشت
# - مابه‌التفاوت هنگام پرداخت کیف پول اگر موجودی کم بود
# - سیستم رسید: کارت‌به‌کارت / شارژ کیف پول / مابه‌التفاوت — ارسال برای ادمین‌ها با تایید/رد
# - پنل ادمین: شماره کارت، مدیریت ادمین‌ها، رسیدهای در انتظار، مدیریت کیف پول کاربر،
#   مدیریت کدهای تخفیف، اعلان همگانی، مدیریت پلن و مخزن، آمار فروش (+ تاپ خریدارها)
# - هشدار اتمام کانفیگ در 5 روز، 3 روز، و پایان — و حذف از "کانفیگ‌های من" بعد از پایان
# - وبهوک اتومات (Koyeb) و سازوکار FastAPI + PTB v20 با initialize درست

import os
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, Application, ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from telegram.error import BadRequest

# -----------------------
# تنظیمات محیط (Koyeb)
# -----------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE_URL = os.getenv("BASE_URL", "").strip()  # مثل: https://your-app-name.koyeb.app
ADMIN_ID_DEFAULT = int(os.getenv("ADMIN_ID", "0"))
SECRET_TOKEN = os.getenv("WEBHOOK_SECRET", "aali_plus_secret")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")
if not BASE_URL:
    raise RuntimeError("BASE_URL تنظیم نشده است. مانند: https://<app>.koyeb.app")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_URL.rstrip('/')}{WEBHOOK_PATH}"

# -----------------------
# دیتابیس (SQLite)
# -----------------------
DB_URL = os.getenv("DATABASE_URL", "sqlite:///aali_plus.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def utcnow():
    return datetime.utcnow()

# -----------------------
# مدل‌ها
# -----------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)  # telegram user id (int)
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    wallet = Column(Float, default=0.0, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    total_spent = Column(Float, default=0.0, nullable=False)
    purchases = relationship("Purchase", back_populates="user", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True)  # telegram id
    is_protected = Column(Boolean, default=False, nullable=False)  # ادمین پیش‌فرض حذف نشه

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(128), nullable=False)
    days = Column(Integer, nullable=False)       # مدت
    traffic_gb = Column(Integer, nullable=False) # حجم
    price = Column(Float, nullable=False)        # قیمت فروش
    cost_price = Column(Float, default=0.0)      # قیمت تمام‌شده (برای آمار سود)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    # موجودی = تعداد Config موجود در مخزن
    configs = relationship("ConfigItem", back_populates="plan", cascade="all, delete-orphan")

class ConfigItem(Base):
    __tablename__ = "config_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    content = Column(Text, nullable=False)    # متن یا کانفیگ (امکان عکس هم پایین‌تر)
    is_assigned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    plan = relationship("Plan", back_populates="configs")

class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    price_paid = Column(Float, nullable=False)
    discount_applied = Column(Float, default=0.0, nullable=False)  # مبلغ تخفیف
    created_at = Column(DateTime, default=utcnow, nullable=False)
    expire_at = Column(DateTime, nullable=False)
    config_text = Column(Text, nullable=False)  # کانفیگ که ارسال شده
    is_active = Column(Boolean, default=True, nullable=False)
    user = relationship("User", back_populates="purchases")

class DiscountCode(Base):
    __tablename__ = "discount_codes"
    code = Column(String(64), primary_key=True)
    percent = Column(Integer, default=0, nullable=False)  # درصد
    max_uses = Column(Integer, default=0, nullable=False)
    used_count = Column(Integer, default=0, nullable=False)
    expire_at = Column(DateTime, nullable=True)
    total_discount_sum = Column(Float, default=0.0, nullable=False)  # جمع تخفیف‌های اعمال‌شده (تومان)

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(32), default="open")  # open/closed
    created_at = Column(DateTime, default=utcnow, nullable=False)
    user = relationship("User", back_populates="tickets")
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")

class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    sender_id = Column(Integer, nullable=False)  # user/admin id
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    ticket = relationship("Ticket", back_populates="messages")

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    kind = Column(String(32), nullable=False)  # "card2card" | "wallet_topup" | "wallet_diff"
    plan_id = Column(Integer, nullable=True)   # برای خرید پلن/مابه‌التفاوت
    amount = Column(Float, nullable=False)
    caption = Column(Text, nullable=True)
    photo_file_id = Column(String(256), nullable=True)  # اگر عکس رسید بود
    status = Column(String(16), default="pending")  # pending/approved/rejected
    created_at = Column(DateTime, default=utcnow, nullable=False)

Base.metadata.create_all(bind=engine)

# -----------------------
# ثابت‌ها و متن دکمه‌ها
# -----------------------
BTN_SHOP = "🛍 خرید سرویس"
BTN_MY_CONFIGS = "🧾 کانفیگ‌های من"
BTN_WALLET = "👛 کیف پول"
BTN_TICKETS = "🎫 تیکت‌ها"
BTN_HELP = "📘 آموزش"
BTN_ADMIN_PANEL = "⚙️ پنل ادمین"

# زیرمنو خرید/پرداخت
CB_PREFIX_PLAN = "plan_"               # انتخاب پلن
CB_SHOW_PLAN = "showplan_"            # نمایش جزئیات پلن
CB_PAY_WALLET = "paywallet_"          # پرداخت با کیف پول
CB_CARD2CARD = "card2card_"           # کارت به کارت
CB_APPLY_DC = "applydc_"              # اعمال کد تخفیف
CB_CANCEL_PURCHASE = "cancelpay_"     # انصراف خرید
CB_BACK_TO_PLANS = "back2plans"       # برگشت به لیست پلن‌ها

# ادمین
BTN_ADMIN_CARD = "💳 تنظیم شماره کارت"
BTN_ADMIN_ADMINS = "👥 مدیریت ادمین‌ها"
BTN_ADMIN_RECEIPTS = "📥 رسیدهای در انتظار"
BTN_ADMIN_WALLET = "👛 کیف پول کاربر"
BTN_ADMIN_DISCOUNTS = "🏷️ کدهای تخفیف"
BTN_ADMIN_BROADCAST = "📢 اعلان همگانی"
BTN_ADMIN_PLANS = "📦 مدیریت پلن و مخزن"
BTN_ADMIN_STATS = "📊 آمار فروش"
BTN_ADMIN_USERS = "🧑‍🤝‍🧑 کاربران"
BTN_BACK_TO_USER = "↩️ برگشت به حالت کاربر"

# وضعیت‌های در حافظه برای جلسات کاربر
user_sessions: Dict[int, Dict[str, Any]] = {}

# کمکی: دریافت یا ساخت یوزر
def get_or_create_user(db, tg_user) -> User:
    u = db.get(User, tg_user.id)
    if not u:
        u = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            wallet=0.0,
            is_admin=False,
            total_spent=0.0,
        )
        db.add(u)
        db.commit()
    else:
        # به‌روزرسانی نام/یوزرنیم اگر تغییر کرده
        changed = False
        if u.username != tg_user.username:
            u.username = tg_user.username
            changed = True
        if u.first_name != tg_user.first_name:
            u.first_name = tg_user.first_name
            changed = True
        if changed:
            db.commit()
    return u

def is_admin(db, user_id:int) -> bool:
    # هم در جدول users و هم admins چک می‌کنیم
    u = db.get(User, user_id)
    if u and u.is_admin:
        return True
    adm = db.get(Admin, user_id)
    return bool(adm)

def get_setting(db, key:str, default:str="") -> str:
    s = db.get(Setting, key)
    return s.value if s and s.value is not None else default

def set_setting(db, key:str, value:str):
    s = db.get(Setting, key)
    if not s:
        s = Setting(key=key, value=value)
        db.add(s)
    else:
        s.value = value
    db.commit()

# دکمه‌های منوی اصلی (برای کاربر / ادمین)
def build_main_menu(is_admin_flag: bool) -> ReplyKeyboardMarkup:
    # طبق خواسته: «کیبورد منو» و دکمه‌ها مرتب — "کیف پول" هم در منوی اصلی باشد
    rows = [
        [KeyboardButton(BTN_SHOP), KeyboardButton(BTN_MY_CONFIGS)],
        [KeyboardButton(BTN_WALLET), KeyboardButton(BTN_TICKETS)],
        [KeyboardButton(BTN_HELP)],
    ]
    if is_admin_flag:
        rows.append([KeyboardButton(BTN_ADMIN_PANEL)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def build_admin_menu() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_ADMIN_CARD), KeyboardButton(BTN_ADMIN_ADMINS)],
        [KeyboardButton(BTN_ADMIN_RECEIPTS), KeyboardButton(BTN_ADMIN_WALLET)],
        [KeyboardButton(BTN_ADMIN_DISCOUNTS), KeyboardButton(BTN_ADMIN_BROADCAST)],
        [KeyboardButton(BTN_ADMIN_PLANS), KeyboardButton(BTN_ADMIN_STATS)],
        [KeyboardButton(BTN_ADMIN_USERS), KeyboardButton(BTN_BACK_TO_USER)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# لیست پلن‌ها (اینلاین)
def build_plans_keyboard(db) -> InlineKeyboardMarkup:
    buttons = []
    plans = db.query(Plan).order_by(Plan.price.asc()).all()
    for p in plans:
        stock = db.query(ConfigItem).filter_by(plan_id=p.id, is_assigned=False).count()
        text = f"🔹 {p.title} | ⏳{p.days}روز | 📦{p.traffic_gb}GB | 💸{int(p.price)}ت | 🧩موجودی:{stock}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"{CB_SHOW_PLAN}{p.id}")])
    if not buttons:
        buttons.append([InlineKeyboardButton("فعلاً پلنی ثبت نشده", callback_data="noop")])
    return InlineKeyboardMarkup(buttons)

def build_plan_detail_keyboard(plan_id:int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👛 پرداخت با کیف پول", callback_data=f"{CB_PAY_WALLET}{plan_id}"),
        ],
        [
            InlineKeyboardButton("💳 کارت به کارت", callback_data=f"{CB_CARD2CARD}{plan_id}"),
            InlineKeyboardButton("🏷️ اعمال کد تخفیف", callback_data=f"{CB_APPLY_DC}{plan_id}"),
        ],
        [
            InlineKeyboardButton("↩️ برگشت", callback_data=CB_BACK_TO_PLANS),
            InlineKeyboardButton("❌ انصراف", callback_data=f"{CB_CANCEL_PURCHASE}{plan_id}"),
        ]
    ])

# محاسبه قیمت بعد از تخفیف
def apply_discount_if_any(db, user_id:int, plan_id:int, code:Optional[str]) -> (float, float, Optional[str]):
    plan = db.get(Plan, plan_id)
    if not plan:
        return 0.0, 0.0, None
    price = plan.price
    discount_amount = 0.0
    used_code = None
    if code:
        dc = db.get(DiscountCode, code.upper())
        now = utcnow()
        if dc and (dc.expire_at is None or dc.expire_at >= now) and (dc.max_uses == 0 or dc.used_count < dc.max_uses):
            discount_amount = round((price * dc.percent) / 100.0, 2)
            price = max(0.0, price - discount_amount)
            used_code = dc.code
    return price, discount_amount, used_code

# انتساب کانفیگ
def assign_config_from_repo(db, plan_id:int) -> Optional[str]:
    cfg = db.query(ConfigItem).filter_by(plan_id=plan_id, is_assigned=False).order_by(ConfigItem.id.asc()).first()
    if not cfg:
        return None
    cfg.is_assigned = True
    db.commit()
    return cfg.content

# هشدارهای انقضا
async def reminder_loop(application: Application):
    # هر ~ساعت می‌چکیم که آیا باید هشدار 5/3/0 روز بدهیم
    while True:
        try:
            db = SessionLocal()
            now = utcnow()
            purchases = db.query(Purchase).filter(Purchase.is_active == True).all()
            for pur in purchases:
                days_left = (pur.expire_at - now).days
                key_last = f"reminded_{pur.id}"
                flags_json = get_setting(db, key_last, "{}")
                flags = json.loads(flags_json or "{}")
                chat_id = pur.user_id
                try:
                    if days_left == 5 and not flags.get("d5"):
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text="⏰ رفیق! فقط ۵ روز دیگه از سرویس‌ت مونده. اگه دوست داشتی تمدید کنی، من اینجام 😉"
                        )
                        flags["d5"] = True
                    if days_left == 3 and not flags.get("d3"):
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text="⏰ یادآوری دوستونه: ۳ روز تا پایان سرویس باقی مونده. هر کمکی خواستی بگو! 😊"
                        )
                        flags["d3"] = True
                    if days_left <= 0 and pur.is_active and not flags.get("done"):
                        pur.is_active = False
                        db.commit()
                        # حذف از «کانفیگ‌های من»
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text="🚫 مدت سرویس تموم شد و از «کانفیگ‌های من» حذف شد. هر زمان خواستی، با یه کلیک سرویس جدید بردار 🤗"
                        )
                        flags["done"] = True
                    set_setting(db, key_last, json.dumps(flags))
                except BadRequest:
                    pass
            db.close()
        except Exception:
            pass
        await asyncio.sleep(3600)

# -----------------------
# FastAPI + PTB
# -----------------------
app = FastAPI()

application: Application = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .build()
)

# وبهوک: در startup باید initialize انجام شود تا HTTPXRequest آماده شود.
@app.on_event("startup")
async def on_startup():
    # دیتابیس اولیه: ادمین پیش‌فرض
    db = SessionLocal()
    if ADMIN_ID_DEFAULT and not db.get(Admin, ADMIN_ID_DEFAULT):
        db.add(Admin(id=ADMIN_ID_DEFAULT, is_protected=True))
        u = db.get(User, ADMIN_ID_DEFAULT)
        if not u:
            db.add(User(id=ADMIN_ID_DEFAULT, is_admin=True, wallet=50000.0, total_spent=0.0))  # موجودی اولیه ادمین 50,000
        else:
            u.is_admin = True
            if u.wallet < 50000.0:
                u.wallet = 50000.0
        db.commit()
    # یک شماره کارت پیش‌فرض اگر خالی است
    if not get_setting(db, "card_number", ""):
        set_setting(db, "card_number", "6214-56**-****-**** به‌نام شما")
    db.close()

    await application.initialize()
    await application.bot.set_webhook(url=WEBHOOK_URL, secret_token=SECRET_TOKEN)

    # راه‌اندازی حلقه یادآور
    asyncio.create_task(reminder_loop(application))

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await application.bot.delete_webhook()
    except Exception:
        pass
    await application.shutdown()
    await application.stop()

class TelegramUpdate(BaseModel):
    update_id: int

@app.get("/")
async def root():
    return PlainTextResponse("AaliPlus bot is running.")

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        return JSONResponse({"ok": False}, status_code=403)
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return JSONResponse({"ok": True})


# =========================
#   هندلرها (بخش ۱/۳ ادامه)
# =========================

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, greeting: bool = False):
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)
    menu = build_main_menu(is_admin(db, u.id))
    if greeting:
        # خوش‌آمدگویی خودمونی و مودبانه (طولانی‌تر و با جزئیات)
        text = (
            "سلام رفیق! 👋\n"
            "به ربات فروش کانفیگ خوش اومدی 🙌\n\n"
            "اینجا می‌تونی خیلی راحت و سریع:\n"
            "• از بین پلن‌های متنوع، سرویس دلخواهت رو انتخاب کنی 🛍\n"
            "• با «کیف پول» پرداخت کنی یا «کارت به کارت» انجام بدی 👛💳\n"
            "• کد تخفیف بزنی و خریدت رو به‌صرفه‌تر کنی 🏷️\n"
            "• کانفیگ‌های خریداری‌شده‌ت رو هر وقت خواستی دوباره ببینی و کپی کنی 🧾\n"
            "• اگر سوالی داشتی، از «تیکت‌ها» کمک بگیر؛ کنارِت هستیم 💬\n\n"
            "برای شروع از منوی زیر یکی رو انتخاب کن. من هم قدم‌به‌قدم همراه‌تم 😉"
        )
    else:
        text = "از منوی زیر یه گزینه رو انتخاب کن عزیز دل 🌟"
    db.close()
    await update.effective_message.reply_text(text, reply_markup=menu)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    get_or_create_user(db, update.effective_user)
    db.close()
    await send_main_menu(update, context, greeting=True)

# فیلتر دکمه‌های منوی اصلی
async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)

    if text == BTN_SHOP:
        # لیست پلن‌ها
        await update.message.reply_text(
            "لیست پلن‌ها 👇",
            reply_markup=build_main_menu(is_admin(db, u.id))
        )
        await update.message.reply_text(
            "یکی رو انتخاب کن:", reply_markup=None, reply_markup_inline=build_plans_keyboard(db)
        )
    elif text == BTN_MY_CONFIGS:
        my = db.query(Purchase).filter_by(user_id=u.id).order_by(Purchase.created_at.desc()).all()
        if not my:
            await update.message.reply_text("فعلاً کانفیگی نداری. هر وقت خواستی از «خرید سرویس» یکی بردار 😉")
        else:
            for p in my[:10]:
                status = "✅ فعال" if p.is_active and p.expire_at > utcnow() else "⛔️ منقضی"
                await update.message.reply_text(
                    f"🔹 {p.config_text}\n"
                    f"وضعیت: {status}\n"
                    f"مهلت: {p.expire_at.strftime('%Y-%m-%d %H:%M')}",
                    disable_web_page_preview=True
                )
    elif text == BTN_WALLET:
        await wallet_menu(update, context, db, u)
    elif text == BTN_TICKETS:
        await tickets_menu(update, context, db, u)
    elif text == BTN_HELP:
        await update.message.reply_text(
            "📘 آموزش قدم‌به‌قدم:\n"
            "۱) «خرید سرویس» رو بزن و پلن دلخواهت رو انتخاب کن.\n"
            "۲) با «کیف پول» یا «کارت به کارت» پرداخت کن. می‌تونی «کد تخفیف» هم بزنی.\n"
            "۳) بعد از تایید پرداخت، کانفیگ آماده‌ست و برات ارسال می‌شه.\n"
            "۴) از «کانفیگ‌های من» همیشه می‌تونی دوباره ببینیش/کپی‌ش کنی.\n"
            "۵) سوال داشتی؟ از «تیکت‌ها» پیام بده، ما همین‌جا هستیم 😊"
        )
    elif text == BTN_ADMIN_PANEL and is_admin(db, u.id):
        await update.message.reply_text("به پنل ادمین خوش اومدی 🤝", reply_markup=build_admin_menu())
    elif text == BTN_BACK_TO_USER:
        await send_main_menu(update, context, greeting=False)
    # پنل ادمین زیرساخت: بقیه دکمه‌ها در بخش‌های بعد هندل می‌شوند
    db.close()

# چون در FastAPI نمی‌توانیم از reply_markup_inline مستقیم استفاده کنیم،
# یک هِلپر می‌نویسیم تا سازگاری حفظ شود:
def reply_markup_inline(keyboard: InlineKeyboardMarkup):
    return keyboard

# === Wallet & Ticket helpers will come next in part 2 ===
# =========================
#   هندلرها (بخش ۲/۳)
# =========================

# ---- کیف پول: منو و عملیات ----
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, db, u: User):
    text = (
        f"👛 موجودی کیف پولت: {int(u.wallet)} تومان\n"
        "می‌خوای افزایشش بدی یا باهاش خرید کنی؟ هر جا نیاز شد کنارت هستم 😉"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزایش موجودی", callback_data="wallet_topup")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="wallet_back")]
    ])
    await update.message.reply_text(text, reply_markup=kb)

async def wallet_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)
    q = update.callback_query
    data = q.data

    if data == "wallet_back":
        await q.answer()
        await q.edit_message_text("برگشتیم به منوی قبلی 👌")
        await send_main_menu(update, context, greeting=False)
    elif data == "wallet_topup":
        await q.answer()
        user_sessions.setdefault(u.id, {})
        user_sessions[u.id]["awaiting_topup_amount"] = True
        card = get_setting(db, "card_number", "نامشخص")
        await q.edit_message_text(
            "چه مبلغی دوست داری به کیف پولت اضافه کنی؟ (تومان)\n"
            "بعد از وارد کردن مبلغ، شماره کارت رو می‌فرستم تا کارت‌به‌کارت کنی 💳"
        )
        await q.message.reply_text(f"💳 شماره کارت:\n{card}\n\nبعد از واریز، لطفاً «عکس یا متن رسید» رو همین‌جا بفرست 🙏")
        # علامت‌گذاری نوع رسید
        user_sessions[u.id]["awaiting_receipt_kind"] = "wallet_topup"
        user_sessions[u.id]["awaiting_receipt_amount"] = True
    db.close()

# دریافت مبلغ افزایش موجودی یا مابه‌التفاوت در چت عادی
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)
    ses = user_sessions.setdefault(u.id, {})

    # مبلغ افزایش موجودی
    if ses.get("awaiting_topup_amount"):
        amt_txt = update.message.text.strip().replace(",", "")
        if amt_txt.isdigit():
            ses["topup_amount"] = float(amt_txt)
            ses["awaiting_topup_amount"] = False
            await update.message.reply_text(
                f"عالیه! مبلغ {int(ses['topup_amount'])} تومان ثبت شد ✅\n"
                "حالا رسید کارت‌به‌کارت رو (عکس یا متن) بفرست تا بره برای تایید ادمین."
            )
        else:
            await update.message.reply_text("عدد نامعتبره. لطفاً فقط مبلغ رو به عدد بفرست ✍️")
        db.close()
        return

    # مبلغ مابه‌التفاوت
    if ses.get("awaiting_diff_amount"):
        amt_txt = update.message.text.strip().replace(",", "")
        if amt_txt.isdigit():
            ses["diff_amount_confirmed"] = float(amt_txt)
            ses["awaiting_diff_amount"] = False
            await update.message.reply_text(
                f"باشه، {int(ses['diff_amount_confirmed'])} تومان مابه‌التفاوت ثبت شد ✅\n"
                "حالا رسید کارت‌به‌کارت رو (عکس یا متن) بفرست تا بره برای تایید ادمین."
            )
        else:
            await update.message.reply_text("عدد نامعتبره. لطفاً فقط مبلغ رو به عدد بفرست ✍️")
        db.close()
        return

    # دکمه‌های منوی اصلی (به‌صورت متنی)
    await main_menu_router(update, context)
    db.close()

# ---- رسید: دریافت عکس/متن و ثبت برای ادمین ----
async def receipt_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)
    ses = user_sessions.setdefault(u.id, {})

    awaiting_kind = ses.get("awaiting_receipt_kind")
    if not awaiting_kind:
        db.close()
        return

    amount = 0.0
    # مبلغ برای کیف پول یا مابه‌التفاوت از سشن
    if awaiting_kind == "wallet_topup":
        amount = float(ses.get("topup_amount", 0.0))
    elif awaiting_kind == "wallet_diff":
        amount = float(ses.get("diff_amount_confirmed", 0.0))
    elif awaiting_kind == "card2card":
        amount = float(ses.get("purchase_amount_final", 0.0))

    caption = None
    photo_id = None
    if update.message.photo:
        photo = update.message.photo[-1]
        photo_id = photo.file_id
        caption = update.message.caption or ""
    else:
        caption = (update.message.text or "").strip()

    if amount <= 0:
        await update.message.reply_text("مبلغ نامشخصه. لطفاً دوباره تلاش کن یا از اول شروع کن 🙏")
        db.close()
        return

    plan_id = ses.get("selected_plan_id")
    r = Receipt(
        user_id=u.id,
        kind=awaiting_kind,
        plan_id=plan_id if awaiting_kind in ("card2card", "wallet_diff") else None,
        amount=amount,
        caption=caption,
        photo_file_id=photo_id,
        status="pending",
    )
    db.add(r)
    db.commit()

    # پاک‌سازی وضعیت انتظار
    for k in ["awaiting_receipt_kind", "awaiting_receipt_amount", "awaiting_diff_amount"]:
        ses.pop(k, None)

    await update.message.reply_text("رسیدت ثبت شد ✅\nبعد از بررسی ادمین، نتیجه بهت خبر می‌دم 🙏")

    # ارسال نوتیف به همه ادمین‌ها
    admins = db.query(Admin).all()
    for ad in admins:
        try:
            text = (
                "🧾 رسید جدید دریافت شد:\n"
                f"👤 کاربر: @{u.username or '-'} (#{u.id})\n"
                f"نوع: {'کارت به کارت' if r.kind=='card2card' else ('مابه‌التفاوت' if r.kind=='wallet_diff' else 'افزایش کیف پول')}\n"
                f"پلن: {r.plan_id or '-'}\n"
                f"مبلغ: {int(r.amount)} تومان\n"
                f"توضیحات کاربر: {caption or '-'}\n"
                f"تاریخ: {r.created_at.strftime('%Y-%m-%d %H:%M')}\n"
                f"شناسه رسید: #{r.id}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تایید", callback_data=f"rc_ok_{r.id}"),
                 InlineKeyboardButton("❌ رد", callback_data=f"rc_no_{r.id}")]
            ])
            if photo_id:
                await context.bot.send_photo(chat_id=ad.id, photo=photo_id, caption=text, reply_markup=kb)
            else:
                await context.bot.send_message(chat_id=ad.id, text=text, reply_markup=kb)
        except Exception:
            pass
    db.close()

# ---- پلن‌ها: نمایش لیست و جزئیات ----
@staticmethod
def _format_plan_detail(p: Plan, stock: int, final_price: float, discount_amount: float):
    base = (
        f"🔸 {p.title}\n"
        f"⏳ مدت: {p.days} روز\n"
        f"📦 حجم: {p.traffic_gb} گیگ\n"
    )
    price_line = f"💸 قیمت: {int(p.price)} تومان"
    if discount_amount > 0:
        price_line += f" → پس از تخفیف: {int(final_price)} تومان (−{int(discount_amount)})"
    stock_line = f"🧩 موجودی مخزن: {stock} عدد"
    return f"{base}{price_line}\n{stock_line}"

async def plans_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    q = update.callback_query
    data = q.data

    # برگشت به لیست پلن‌ها
    if data == CB_BACK_TO_PLANS:
        await q.answer()
        kb = build_plans_keyboard(db)
        await q.edit_message_text("یکی از پلن‌ها رو انتخاب کن 👇", reply_markup=kb)
        db.close()
        return

    # نمایش جزئیات پلن
    if data.startswith(CB_SHOW_PLAN):
        plan_id = int(data[len(CB_SHOW_PLAN):])
        p = db.get(Plan, plan_id)
        if not p:
            await q.answer("پلن پیدا نشد", show_alert=True)
            db.close()
            return
        stock = db.query(ConfigItem).filter_by(plan_id=p.id, is_assigned=False).count()
        ses = user_sessions.setdefault(q.from_user.id, {})
        ses["selected_plan_id"] = p.id
        # قیمت بدون تخفیف به‌صورت پیش‌فرض
        ses["purchase_price"] = float(p.price)
        ses["purchase_discount"] = 0.0
        ses["purchase_code"] = None

        text = _format_plan_detail(p, stock, p.price, 0.0)
        await q.answer()
        await q.edit_message_text(text, reply_markup=build_plan_detail_keyboard(p.id))
        db.close()
        return

    # پرداخت با کیف پول
    if data.startswith(CB_PAY_WALLET):
        plan_id = int(data[len(CB_PAY_WALLET):])
        p = db.get(Plan, plan_id)
        if not p:
            await q.answer("پلن یافت نشد", show_alert=True)
            db.close()
            return
        stock = db.query(ConfigItem).filter_by(plan_id=p.id, is_assigned=False).count()
        if stock <= 0:
            await q.answer("مخزن این پلن فعلاً خالیه، بزودی شارژ میشه 💙", show_alert=True)
            db.close()
            return

        u = get_or_create_user(db, q.from_user)
        ses = user_sessions.setdefault(u.id, {})
        price_final = float(ses.get("purchase_price", p.price))
        discount_amt = float(ses.get("purchase_discount", 0.0))

        if u.wallet >= price_final:
            # کم کردن از کیف پول و تحویل کانفیگ
            u.wallet -= price_final
            cfg = assign_config_from_repo(db, plan_id)
            if not cfg:
                await q.answer("مخزن خالی شد. لحظه‌ای بعد تلاش کن 🙏", show_alert=True)
                db.rollback()
                db.close()
                return
            expire_at = utcnow() + timedelta(days=p.days)
            pur = Purchase(
                user_id=u.id, plan_id=p.id, price_paid=price_final,
                discount_applied=discount_amt, expire_at=expire_at,
                config_text=cfg, is_active=True
            )
            u.total_spent += price_final
            db.add(pur)
            db.commit()
            await q.answer()
            await q.edit_message_text(
                "🎉 تبریک رفیق! خریدت با کیف پول انجام شد و کانفیگ آماده‌ست. هر زمان خواستی می‌تونی کپی‌ش کنی 😉"
            )
            await context.bot.send_message(
                chat_id=u.id,
                text=f"🧾 کانفیگ:\n{cfg}\n\n⏳ اعتبار تا: {expire_at.strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            # محاسبه مابه‌التفاوت
            diff = int(price_final - u.wallet)
            ses["awaiting_diff_amount"] = True
            ses["awaiting_receipt_kind"] = "wallet_diff"
            ses["diff_amount_confirmed"] = diff  # پیش‌فرض
            ses["selected_plan_id"] = plan_id
            ses["purchase_amount_final"] = price_final
            card = get_setting(db, "card_number", "نامشخص")
            await q.answer()
            await q.edit_message_text(
                f"موجودی کیف پولت کمه 🫣\n"
                f"💡 مابه‌التفاوت: {diff} تومان\n"
                "اگه اوکی هستی، همین مبلغ رو کارت‌به‌کارت کن و رسید رو بفرست تا تایید کنیم.\n\n"
                f"💳 شماره کارت:\n{card}\n\n"
                "بعد از واریز، لطفاً «عکس یا متن رسید» رو ارسال کن 🙏",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ انصراف", callback_data=f"{CB_CANCEL_PURCHASE}{plan_id}")]
                ])
            )
        db.close()
        return

    # کارت به کارت مستقیم برای خرید
    if data.startswith(CB_CARD2CARD):
        plan_id = int(data[len(CB_CARD2CARD):])
        p = db.get(Plan, plan_id)
        if not p:
            await q.answer("پلن یافت نشد", show_alert=True)
            db.close()
            return
        stock = db.query(ConfigItem).filter_by(plan_id=p.id, is_assigned=False).count()
        if stock <= 0:
            await q.answer("مخزن این پلن فعلاً خالیه، بزودی شارژ میشه 💙", show_alert=True)
            db.close()
            return

        u = get_or_create_user(db, q.from_user)
        ses = user_sessions.setdefault(u.id, {})
        price_final = float(ses.get("purchase_price", p.price))
        ses["selected_plan_id"] = plan_id
        ses["awaiting_receipt_kind"] = "card2card"
        ses["purchase_amount_final"] = price_final

        card = get_setting(db, "card_number", "نامشخص")
        await q.answer()
        await q.edit_message_text(
            f"هزینه‌ی این پلن: {int(price_final)} تومان 💸\n"
            f"لطفاً به کارت زیر واریز کن و «عکس یا متن رسید» رو ارسال کن تا تایید کنیم 🙏\n\n"
            f"💳 شماره کارت:\n{card}\n",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏷️ اعمال کد تخفیف", callback_data=f"{CB_APPLY_DC}{plan_id}")],
                [InlineKeyboardButton("❌ انصراف", callback_data=f"{CB_CANCEL_PURCHASE}{plan_id}")],
            ])
        )
        db.close()
        return

    # اعمال کد تخفیف
    if data.startswith(CB_APPLY_DC):
        plan_id = int(data[len(CB_APPLY_DC):])
        p = db.get(Plan, plan_id)
        if not p:
            await q.answer("پلن یافت نشد", show_alert=True)
            db.close()
            return
        u = get_or_create_user(db, q.from_user)
        ses = user_sessions.setdefault(u.id, {})
        ses["selected_plan_id"] = plan_id
        ses["awaiting_discount_code"] = True
        await q.answer()
        await q.message.reply_text("کد تخفیفت رو بفرست 🏷️")
        db.close()
        return

    # انصراف خرید
    if data.startswith(CB_CANCEL_PURCHASE):
        await q.answer("انجام شد ✅")
        await q.edit_message_text("فرایند خرید لغو شد. هر وقت خواستی دوباره امتحان کن 🤗")
        return

    db.close()

# گرفتن کد تخفیف از کاربر
async def discount_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)
    ses = user_sessions.setdefault(u.id, {})
    if not ses.get("awaiting_discount_code"):
        db.close()
        return

    code = update.message.text.strip().upper()
    plan_id = ses.get("selected_plan_id")
    if not plan_id:
        await update.message.reply_text("اول یکی از پلن‌ها رو انتخاب کن 🙏")
        ses.pop("awaiting_discount_code", None)
        db.close()
        return

    p = db.get(Plan, plan_id)
    if not p:
        await update.message.reply_text("پلن معتبر نیست.")
        ses.pop("awaiting_discount_code", None)
        db.close()
        return

    price_new, disc_amt, used_code = apply_discount_if_any(db, u.id, plan_id, code)
    if not used_code:
        await update.message.reply_text("کد تخفیف نامعتبره یا منقضی شده 🙈")
        ses.pop("awaiting_discount_code", None)
        db.close()
        return

    ses["purchase_price"] = float(price_new)
    ses["purchase_discount"] = float(disc_amt)
    ses["purchase_code"] = used_code
    ses.pop("awaiting_discount_code", None)

    stock = db.query(ConfigItem).filter_by(plan_id=p.id, is_assigned=False).count()
    detail = _format_plan_detail(p, stock, price_new, disc_amt)
    await update.message.reply_text(
        "کد تخفیف اعمال شد ✅\n" + detail,
        reply_markup=build_plan_detail_keyboard(p.id)
    )

    db.close()

# ---- تیکت‌ها ----
async def tickets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, db, u: User):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ تیکت جدید", callback_data="tk_new"),
         InlineKeyboardButton("📜 تیکت‌های من", callback_data="tk_list")]
    ])
    await update.message.reply_text("این‌جا می‌تونی تیکت بسازی یا سابقه‌ رو ببینی 👇", reply_markup=kb)

async def tickets_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)
    q = update.callback_query
    data = q.data

    if data == "tk_new":
        t = Ticket(user_id=u.id, status="open")
        db.add(t)
        db.commit()
        user_sessions.setdefault(u.id, {})["awaiting_ticket_message"] = t.id
        await q.answer()
        await q.edit_message_text("پیامت رو بنویس تا تیکت جدیدت ثبت بشه ✍️")
        db.close()
        return

    if data == "tk_list":
        await q.answer()
        my = db.query(Ticket).filter_by(user_id=u.id).order_by(Ticket.created_at.desc()).all()
        if not my:
            await q.edit_message_text("تیکتی ثبت نکردی هنوز 😊")
        else:
            lines = []
            for t in my[:10]:
                lines.append(f"#{t.id} | وضعیت: {t.status} | {t.created_at.strftime('%Y-%m-%d')}")
            await q.edit_message_text("لیست تیکت‌ها:\n" + "\n".join(lines))
        db.close()
        return

    db.close()

async def ticket_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    db = SessionLocal()
    u = get_or_create_user(db, update.effective_user)
    ses = user_sessions.setdefault(u.id, {})
    t_id = ses.get("awaiting_ticket_message")
    if not t_id:
        db.close()
        return
    t = db.get(Ticket, t_id)
    if not t:
        ses.pop("awaiting_ticket_message", None)
        await update.message.reply_text("تیکت نامعتبر شد. دوباره تلاش کن 🙏")
        db.close()
        return

    msg = TicketMessage(ticket_id=t.id, sender_id=u.id, text=update.message.text.strip())
    db.add(msg)
    db.commit()
    await update.message.reply_text(f"تیکت #{t.id} ثبت شد ✅\nبه زودی جواب می‌دیم 🌟")
    # نوتیف برای ادمین‌ها
    admins = db.query(Admin).all()
    for ad in admins:
        try:
            await context.bot.send_message(
                chat_id=ad.id,
                text=f"🎫 تیکت جدید #{t.id} از @{u.username or '-'} (#{u.id}):\n{msg.text}"
            )
        except Exception:
            pass
    ses.pop("awaiting_ticket_message", None)
    db.close()

# ---- فتو/متن رسید: ثبت ----
receipt_photo_handler = MessageHandler(filters.PHOTO & ~filters.COMMAND, receipt_router)
receipt_text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_router)

# روتینگ متن‌ها: ترتیب مهمه
# 1) ورود مبلغ‌ها
amount_text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)
# 2) کد تخفیف
discount_text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, discount_text_router)
# 3) پیام تیکت
ticket_text_handler_h = MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_text_router)
# ================== پارت 3 ==================

# ⚡️ وظیفه: نمایش آمار فروش، سود و مدیریت برای ادمین
async def show_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales = db.get("sales", [])
    if not sales:
        await update.message.reply_text("📊 هیچ فروشی ثبت نشده است.")
        return

    total_income = sum(sale["price_sell"] for sale in sales)
    total_cost = sum(sale["price_buy"] for sale in sales)
    profit = total_income - total_cost

    await update.message.reply_text(
        f"📊 گزارش فروش:\n\n"
        f"💰 مجموع فروش: {total_income} تومان\n"
        f"💸 مجموع هزینه: {total_cost} تومان\n"
        f"📈 سود خالص: {profit} تومان\n"
        f"🛒 تعداد فروش: {len(sales)}"
    )

# ⚡️ وظیفه: ریست کردن آمار فروش توسط ادمین
async def reset_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db["sales"] = []
    save_db()
    await update.message.reply_text("♻️ آمار فروش با موفقیت ریست شد.")

# ⚡️ هندلر برای هشدار پایان کانفیگ
async def check_expiring_configs(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    for user_id, configs in db.get("configs", {}).items():
        expired = []
        for cfg in configs:
            expire_date = datetime.fromisoformat(cfg["expire_date"])
            days_left = (expire_date - now).days
            if days_left in [5, 3]:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⚠️ کانفیگ شما فقط {days_left} روز دیگر اعتبار دارد. لطفاً تمدید کنید."
                    )
                except Exception:
                    pass
            elif days_left <= 0:
                expired.append(cfg)

        # حذف کانفیگ‌های منقضی شده
        for cfg in expired:
            configs.remove(cfg)

    save_db()

# ⚡️ ست کردن منوهای کیبورد برای کاربران
def get_user_main_menu():
    keyboard = [
        ["🛍 خرید سرویس", "📂 کانفیگ‌های من"],
        ["👛 کیف پول", "📊 چرا اما فروش"],
        ["♻️ ریست آمار"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ⚡️ منوی اصلی ادمین
def get_admin_main_menu():
    keyboard = [
        ["➕ افزودن سرویس", "📊 آمار فروش"],
        ["♻️ ریست آمار", "💌 پیام به کاربر"],
        ["🏠 منوی کاربر"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ⚡️ اجرای ربات
def main():
    app = Application.builder().token(BOT_TOKEN).request(Request()).build()

    # فرمان‌ها
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", show_admin_stats))
    app.add_handler(CommandHandler("resetstats", reset_admin_stats))

    # هندلرهای مربوط به رسید پرداخت
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex("رسید کارت به کارت"), handle_card_receipt))
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex("رسید کیف پول"), handle_wallet_receipt))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("ریست آمار"), reset_admin_stats))

    # هشدار پایان کانفیگ (هر روز اجرا می‌شود)
    job_queue = app.job_queue
    job_queue.run_repeating(check_expiring_configs, interval=86400, first=10)

    # شروع
    print("🤖 ربات عالی پلاس با موفقیت اجرا شد...")
    app.run_polling()

if __name__ == "__main__":
    main()

# ================== پایان پارت 3 ==================
