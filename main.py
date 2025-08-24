# -*- coding: utf-8 -*-
# app.py — "Perfect" Telegram Bot (FastAPI + PTB v20 + SQLite)
# Author: you
# Notes:
# - Webhook path: /webhook
# - Health path:  /
# - Auto setWebhook if BASE_URL is provided
# - All texts are Farsi; DO NOT change emojis/labels the user asked to keep.

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

from sqlalchemy import (
    create_engine, select, func, ForeignKey, Integer, String, Text, DateTime,
    Float, Boolean
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
)

from telegram import (
    Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, MessageEntity, constants
)
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, PicklePersistence
)

# ------------- Logging -------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
log = logging.getLogger("perfect-bot")

# ------------- ENV -------------
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PORT = int(os.getenv("PORT", "8000"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # optional
CARD_NUMBER = os.getenv("CARD_NUMBER", "---- ---- ---- ----")  # will be overridable in Admin

if not TOKEN:
    log.error("BOT_TOKEN env var is required!")
    # don't exit on Koyeb; let it start for health, but will not respond
# ------------- DB -------------
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")
engine = create_engine(DB_URL, echo=False, future=True, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # tg id
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    wallet: Mapped[float] = mapped_column(Float, default=0.0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    orders: Mapped[List["Order"]] = relationship(back_populates="user")
    tickets: Mapped[List["Ticket"]] = relationship(back_populates="user")


class Admin(Base):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # tg id
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppConfig(Base):
    __tablename__ = "app_config"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80))
    days: Mapped[int] = mapped_column(Integer)
    traffic_gb: Mapped[int] = mapped_column(Integer)
    price_sell: Mapped[float] = mapped_column(Float)
    price_cost: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    configs: Mapped[List["ConfigItem"]] = relationship(back_populates="plan")


class ConfigItem(Base):
    __tablename__ = "config_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    payload: Mapped[Optional[str]] = mapped_column(Text)  # text config
    image_file_id: Mapped[Optional[str]] = mapped_column(String(200))  # optional image
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    plan: Mapped[Plan] = relationship(back_populates="configs")


class DiscountCode(Base):
    __tablename__ = "discount_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    percent: Mapped[Optional[int]] = mapped_column(Integer)  # 0..100
    amount: Mapped[Optional[float]] = mapped_column(Float)   # fixed IRR
    max_uses: Mapped[int] = mapped_column(Integer, default=0)  # 0 => unlimited
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    total_discount_given: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    config_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("config_items.id"))
    price_sell: Mapped[float] = mapped_column(Float)
    discount_applied: Mapped[float] = mapped_column(Float, default=0.0)
    price_paid: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, paid, delivered, expired, canceled
    user: Mapped[User] = relationship(back_populates="orders")
    plan: Mapped[Plan] = relationship()
    config_item: Mapped[Optional[ConfigItem]] = relationship()


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    target: Mapped[str] = mapped_column(String(20), default="wallet")  # wallet or order:<id>
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(200))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, rejected
    user: Mapped[User] = relationship()


class WalletTx(Base):
    __tablename__ = "wallet_txs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)  # +credit / -debit
    reason: Mapped[str] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="tickets")
    messages: Mapped[List["TicketMessage"]] = relationship(back_populates="ticket")


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    from_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ticket: Mapped[Ticket] = relationship(back_populates="messages")


Base.metadata.create_all(engine)

# Ensure default admin exists
with SessionLocal() as s:
    if ADMIN_ID:
        if not s.get(User, ADMIN_ID):
            s.add(User(id=ADMIN_ID, username=None, first_name="Owner", is_admin=True))
        if not s.get(Admin, ADMIN_ID):
            s.add(Admin(id=ADMIN_ID))
        s.commit()
    # ensure card in config
    if not s.get(AppConfig, "card_number"):
        s.add(AppConfig(key="card_number", value=CARD_NUMBER))
        s.commit()

# ------------- Bot & FastAPI -------------
app = FastAPI()

# Persistence to keep conversation states and some caches (safe for Koyeb ephemeral disk)
persistence = PicklePersistence(filepath="./bot_state.pickle")

application: Application = ApplicationBuilder().token(TOKEN).persistence(persistence).build()


# ------------- Utilities -------------

MAIN_MENU_BTNS = [
    [KeyboardButton("🛍 خرید کانفیگ"), KeyboardButton("🎒 آموزش قدم‌ب‌قدم")],
    [KeyboardButton("👤 حساب من"), KeyboardButton("🧾 سفارش‌های من")],
    [KeyboardButton("👛 کیف پول من")],
    [KeyboardButton("⚙️ پنل ادمین")]  # shown to admins only (we'll filter)
]
ADMIN_MENU_BTNS = [
    [KeyboardButton("💳 تغییر شماره کارت"), KeyboardButton("🧑‍💻 مدیریت ادمین‌ها")],
    [KeyboardButton("📥 رسیدهای در انتظار"), KeyboardButton("👛 کیف پول کاربر")],
    [KeyboardButton("🏷 کدهای تخفیف"), KeyboardButton("📣 اعلان همگانی")],
    [KeyboardButton("📦 مدیریت پلن و مخزن"), KeyboardButton("📈 آمار فروش")],
    [KeyboardButton("👥 کاربران")],
    [KeyboardButton("↩️ بازگشت به حالت کاربر")]
]

CANCEL_BTN = KeyboardButton("❌ انصراف")
BACK_BTN = KeyboardButton("↩️ بازگشت")

def main_menu_kb(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [row[:] for row in MAIN_MENU_BTNS]
    if not is_admin:
        rows = rows[:-1]  # remove admin line
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(ADMIN_MENU_BTNS + [[BACK_BTN]], resize_keyboard=True)

async def send_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text="منو رو از دکمه‌ها انتخاب کن 👇"):
    u = ensure_user(update.effective_user)
    await update.effective_chat.send_message(
        text,
        reply_markup=main_menu_kb(u.is_admin)
    )

def ensure_user(tguser) -> User:
    with SessionLocal() as s:
        u = s.get(User, tguser.id)
        if not u:
            u = User(id=tguser.id, username=tguser.username, first_name=tguser.first_name,
                     is_admin=(tguser.id == ADMIN_ID))
            s.add(u)
            if u.is_admin and not s.get(Admin, u.id):
                s.add(Admin(id=u.id))
            s.commit()
        else:
            changed = False
            if u.username != tguser.username:
                u.username = tguser.username or u.username
                changed = True
            if u.first_name != tguser.first_name:
                u.first_name = tguser.first_name or u.first_name
                changed = True
            if tguser.id == ADMIN_ID and not u.is_admin:
                u.is_admin = True; changed = True
            if changed: s.commit()
        return u

def get_card_number(s: Session) -> str:
    conf = s.get(AppConfig, "card_number")
    return conf.value if conf else CARD_NUMBER

def fmt_price(v: float) -> str:
    return f"{int(v):,} تومان"

def plan_stock(s: Session, plan_id: int) -> int:
    return s.scalar(select(func.count()).select_from(ConfigItem).where(
        ConfigItem.plan_id == plan_id, ConfigItem.is_used == False
    )) or 0

def order_reminder_jobs(ctx: ContextTypes.DEFAULT_TYPE, order: Order):
    # schedule reminders: 5 days before, 1 day before, at expiry
    if not order.expires_at:
        return
    j = ctx.application.job_queue
    u_id = order.user_id
    oid = order.id
    def mk(cb_text):
        async def _job(context: ContextTypes.DEFAULT_TYPE):
            try:
                await context.bot.send_message(u_id, cb_text)
            except Exception as e:
                log.warning(f"reminder job send failed: {e}")
        return _job

    now = datetime.utcnow()
    times = []
    five = order.expires_at - timedelta(days=5)
    one = order.expires_at - timedelta(days=1)
    if five > now:  times.append((five, "یادت باشه از پلنت ۵ روز مونده 😉"))
    if one > now:   times.append((one, "فقط ۱ روز تا پایان پلنت باقی مونده ⏳"))
    if order.expires_at > now: times.append((order.expires_at, "پلنت تموم شد؛ کانفیگ از «کانفیگ‌های من» حذف شد. تمدید لازمت شد خبر بده 🌱"))
    for dtm, msg in times:
        j.run_once(mk(msg), when=dtm)

# -------- Conversations (States) --------
from enum import IntEnum

class St(IntEnum):
    IDLE = 0
    BUY_SELECT_PLAN = 10
    BUY_APPLY_DISCOUNT = 11
    BUY_PAY_METHOD = 12
    BUY_WAIT_RECEIPT_PHOTO = 13
    BUY_CONFIRM_CANCEL = 14
    WALLET_TOPUP_AMOUNT = 20
    WALLET_RECEIPT = 21
    TICKET_MENU = 30
    TICKET_NEW_TITLE = 31
    TICKET_NEW_MESSAGE = 32
    ADMIN_PANEL = 40
    ADMIN_CARD_SET = 41
    ADMIN_ADD_ADMIN = 42
    ADMIN_DEL_ADMIN = 43
    ADMIN_USER_WALLET_QUERY = 44
    ADMIN_USER_WALLET_EDIT = 45
    ADMIN_CREATE_CODE = 46
    ADMIN_CODES_LIST = 47
    ADMIN_BROADCAST = 48
    ADMIN_PLANS = 49
    ADMIN_PLANS_NEW = 50
    ADMIN_PLANS_EDIT_SELECT = 51
    ADMIN_STOCK_ADD_STREAM = 52
    ADMIN_STATS = 53
    ADMIN_USERS = 54

# -------- Keyboards --------
def back_cancel_kb():
    return ReplyKeyboardMarkup([[BACK_BTN, CANCEL_BTN]], resize_keyboard=True)

def cancel_only_kb():
    return ReplyKeyboardMarkup([[CANCEL_BTN]], resize_keyboard=True)

# -------- Handlers --------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user)
    # set bot commands for PM
    await ctx.bot.set_my_commands([
        BotCommand("start", "شروع"),
        BotCommand("help", "راهنما")
    ])
    await send_main_menu(update, ctx, "سلام! منو‌ی اصلی 👇")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("برای استفاده از ربات از دکمه‌های منو استفاده کن. اگر جایی گیر کردی «❌ انصراف» رو بزن.")

# ----- USER: Wallet -----
async def wallet_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user)
    with SessionLocal() as s:
        me = s.get(User, u.id)
        text = f"👛 موجودی کیف‌پول: {fmt_price(me.wallet)}\nمی‌خوای افزایش بدی؟ مبلغ رو به کارت واریز کن و رسید رو بفرست.\n\nشماره کارت: {get_card_number(s)}"
    await update.message.reply_text("مبلغ افزایش موجودی رو بفرست (تومان):", reply_markup=cancel_only_kb())
    return St.WALLET_TOPUP_AMOUNT

async def wallet_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip().replace(",", "")
    if not msg.isdigit() or int(msg) < 10000:
        await update.message.reply_text("مبلغ نامعتبره. یه عدد (حداقل ۱۰,۰۰۰) بفرست.", reply_markup=cancel_only_kb())
        return St.WALLET_TOPUP_AMOUNT
    ctx.user_data["wallet_amount"] = int(msg)
    with SessionLocal() as s:
        card = get_card_number(s)
    await update.message.reply_text(
        f"عالی! {fmt_price(int(msg))} رو کارت‌به‌کارت کن و **رسید** رو به صورت *عکس* بفرست.\nشماره کارت: {card}\n\nیا «❌ انصراف».",
        parse_mode=constants.ParseMode.MARKDOWN, reply_markup=cancel_only_kb()
    )
    return St.WALLET_RECEIPT

async def wallet_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفاً *عکس* رسید رو بفرست.", parse_mode=constants.ParseMode.MARKDOWN)
        return St.WALLET_RECEIPT
    file_id = update.message.photo[-1].file_id
    amount = ctx.user_data.get("wallet_amount", 0)
    u = ensure_user(update.effective_user)
    with SessionLocal() as s:
        r = Receipt(user_id=u.id, amount=amount, photo_file_id=file_id, target="wallet")
        s.add(r); s.commit()
    await update.message.reply_text("رسید ثبت شد ✅ — منتظر تایید ادمین باش.\nمی‌تونی از «پنل ادمین > رسیدهای در انتظار» بررسی کنی.", reply_markup=main_menu_kb(u.is_admin))
    # notify admins
    await notify_admins_new_receipt(ctx, r_id=r.id)
    return ConversationHandler.END

async def notify_admins_new_receipt(ctx, r_id: int):
    with SessionLocal() as s:
        r = s.get(Receipt, r_id)
        if not r: return
        u = s.get(User, r.user_id)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("تایید ✅", callback_data=f"rc_ok:{r.id}"),
            InlineKeyboardButton("رد ❌", callback_data=f"rc_no:{r.id}")
        ]])
        text = (
            f"🧾 رسید جدید\nاز: @{u.username or '-'} (ID:{u.id})\n"
            f"نوع: {'کیف پول' if r.target=='wallet' else r.target}\n"
            f"مبلغ: {fmt_price(r.amount)}\nتاریخ: {r.submitted_at.strftime('%Y-%m-%d %H:%M')}"
        )
    # send to all admins
    with SessionLocal() as s:
        admins = s.scalars(select(Admin)).all()
    for a in admins:
        try:
            await ctx.bot.send_photo(a.id, r.photo_file_id, caption=text, reply_markup=kb)
        except Exception as e:
            log.warning(f"notify admin {a.id} failed: {e}")

# ----- USER: Orders / Buy -----
def plans_list_text() -> Tuple[str, List[List[KeyboardButton]]]:
    with SessionLocal() as s:
        plans = s.scalars(select(Plan).where(Plan.active == True)).all()
        if not plans:
            return ("فعلاً پلنی موجود نیست. بزودی شارژ میشه ✌️", [[BACK_BTN, CANCEL_BTN]])
        rows = []
        text_lines = ["📦 لیست پلن‌ها:"]
        for p in plans:
            stock = plan_stock(s, p.id)
            text_lines.append(f"• {p.name} | {p.days} روز | {p.traffic_gb}GB | قیمت: {fmt_price(p.price_sell)} | موجودی: {stock}")
            rows.append([KeyboardButton(f"خرید: {p.name}")])
        rows.append([BACK_BTN, CANCEL_BTN])
        return ("\n".join(text_lines), rows)

async def buy_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text, rows = plans_list_text()
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))
    return St.BUY_SELECT_PLAN

async def buy_select_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.replace("خرید:", "").strip()
    with SessionLocal() as s:
        p = s.scalar(select(Plan).where(Plan.name == title, Plan.active == True))
        if not p:
            await update.message.reply_text("این گزینه معتبر نیست.", reply_markup=back_cancel_kb())
            return St.BUY_SELECT_PLAN
        stock = plan_stock(s, p.id)
        if stock <= 0:
            # notify admins low stock
            await notify_low_stock(ctx, p.id, stock)
            await update.message.reply_text("این مخزن فعلاً خالیه؛ بزودی شارژ میشه 🙏", reply_markup=main_menu_kb(ensure_user(update.effective_user).is_admin))
            return ConversationHandler.END
        ctx.user_data["plan_id"] = p.id
        ctx.user_data["price_sell"] = p.price_sell
    await update.message.reply_text(
        "اگه کد تخفیف داری بفرست (یا بنویس «ندارم»).", reply_markup=back_cancel_kb()
    )
    return St.BUY_APPLY_DISCOUNT

async def apply_discount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code_txt = update.message.text.strip()
    if code_txt == "ندارم":
        ctx.user_data["discount"] = 0.0
        return await goto_pay_method(update, ctx)
    with SessionLocal() as s:
        dc = s.scalar(select(DiscountCode).where(func.lower(DiscountCode.code) == code_txt.lower(), DiscountCode.active == True))
        if not dc or (dc.expires_at and dc.expires_at < datetime.utcnow()) or (dc.max_uses and dc.used_count >= dc.max_uses):
            await update.message.reply_text("کد تخفیف معتبر نیست یا منقضی شده.", reply_markup=back_cancel_kb())
            return St.BUY_APPLY_DISCOUNT
        price = float(ctx.user_data["price_sell"])
        disc = min(price, (price * dc.percent / 100.0 if dc.percent else 0.0) + (dc.amount or 0.0))
        ctx.user_data["discount"] = float(int(disc))  # round down to integer rial
        ctx.user_data["discount_code_id"] = dc.id
    await update.message.reply_text(f"کد اعمال شد ✅ مقدار تخفیف: {fmt_price(ctx.user_data['discount'])}")
    return await goto_pay_method(update, ctx)

async def goto_pay_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    price = float(ctx.user_data["price_sell"])
    disc = float(ctx.user_data.get("discount", 0.0))
    payable = max(0.0, price - disc)
    ctx.user_data["payable"] = payable
    u = ensure_user(update.effective_user)
    with SessionLocal() as s:
        me = s.get(User, u.id); card = get_card_number(s)
    rows = [
        [KeyboardButton("پرداخت با کیف پول")],
        [KeyboardButton("کارت‌به‌کارت / ارسال رسید")],
        [KeyboardButton("❌ انصراف")]
    ]
    await update.message.reply_text(
        f"قیمت: {fmt_price(price)}\nتخفیف: {fmt_price(disc)}\nقابل پرداخت: {fmt_price(payable)}\n"
        f"موجودی کیف پول شما: {fmt_price(me.wallet)}\n\nیک روش پرداخت انتخاب کن:",
        reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True)
    )
    return St.BUY_PAY_METHOD

async def buy_pay_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    u = ensure_user(update.effective_user)
    payable = float(ctx.user_data.get("payable", 0.0))
    if choice == "پرداخت با کیف پول":
        with SessionLocal() as s:
            me = s.get(User, u.id)
            if me.wallet < payable:
                need = payable - me.wallet
                await update.message.reply_text(
                    f"موجودی کافی نیست. {fmt_price(need)} باید شارژ کنی. «👛 کیف پول من» رو بزن یا برگرد.", reply_markup=main_menu_kb(u.is_admin)
                )
                return ConversationHandler.END
            me.wallet -= payable
            s.add(WalletTx(user_id=u.id, amount=-payable, reason="خرید پلن"))
            # create order + assign config
            plan = s.get(Plan, ctx.user_data["plan_id"])
            cfg = s.scalar(select(ConfigItem).where(ConfigItem.plan_id == plan.id, ConfigItem.is_used == False).limit(1))
            if not cfg:
                await update.message.reply_text("متاسفانه موجودی لحظه‌ای تموم شد! مبلغ برمی‌گرده به کیف‌پولت.", reply_markup=main_menu_kb(u.is_admin))
                me.wallet += payable
                s.add(WalletTx(user_id=u.id, amount=payable, reason="بازگشت وجه: اتمام موجودی"))
                s.commit()
                await notify_low_stock(ctx, plan.id, 0)
                return ConversationHandler.END
            cfg.is_used = True
            order = Order(user_id=u.id, plan_id=plan.id, config_item_id=cfg.id,
                          price_sell=plan.price_sell, discount_applied=float(ctx.user_data.get("discount", 0.0)),
                          price_paid=payable, created_at=datetime.utcnow(),
                          expires_at=datetime.utcnow() + timedelta(days=plan.days), status="delivered")
            s.add(order)
            # update discount usage if used
            if ctx.user_data.get("discount_code_id"):
                dc = s.get(DiscountCode, ctx.user_data["discount_code_id"])
                if dc:
                    dc.used_count += 1
                    dc.total_discount_given += float(ctx.user_data["discount"])
            # stats
            me.total_spent += payable
            s.commit()
            # schedule reminders
            order_reminder_jobs(ctx, order)
            # deliver config
            if cfg.payload:
                await update.message.reply_text(f"خرید موفق 🎉\nکانفیگ:\n```\n{cfg.payload}\n```", parse_mode=constants.ParseMode.MARKDOWN)
            if cfg.image_file_id:
                await update.message.reply_photo(cfg.image_file_id, caption="تصویر کانفیگ")
            await update.message.reply_text("هر زمان خواستی از «🧾 سفارش‌های من» ببینیش.", reply_markup=main_menu_kb(u.is_admin))
        return ConversationHandler.END

    if choice == "کارت‌به‌کارت / ارسال رسید":
        with SessionLocal() as s:
            card = get_card_number(s)
        await update.message.reply_text(
            f"مبلغ {fmt_price(payable)} رو کارت‌به‌کارت کن و *عکسِ رسید* رو همینجا بفرست.\nشماره کارت: {card}\n\nیا «❌ انصراف».",
            parse_mode=constants.ParseMode.MARKDOWN,
            reply_markup=cancel_only_kb()
        )
        return St.BUY_WAIT_RECEIPT_PHOTO

    await update.message.reply_text("لغو شد.", reply_markup=main_menu_kb(u.is_admin))
    return ConversationHandler.END

async def buy_receipt_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفاً عکس رسید رو بفرست.")
        return St.BUY_WAIT_RECEIPT_PHOTO
    file_id = update.message.photo[-1].file_id
    u = ensure_user(update.effective_user)
    payable = float(ctx.user_data["payable"])
    plan_id = int(ctx.user_data["plan_id"])
    # create pending order + receipt
    with SessionLocal() as s:
        order = Order(user_id=u.id, plan_id=plan_id, price_sell=ctx.user_data["price_sell"],
                      discount_applied=float(ctx.user_data.get("discount", 0.0)), status="pending")
        s.add(order); s.commit()
        r = Receipt(user_id=u.id, amount=payable, photo_file_id=file_id, target=f"order:{order.id}")
        s.add(r); s.commit()
        await update.message.reply_text("رسید ثبت شد ✅ بعد از تایید ادمین کانفیگ ارسال می‌شه.", reply_markup=main_menu_kb(u.is_admin))
    await notify_admins_new_receipt(ctx, r_id=r.id)
    return ConversationHandler.END

# ----- Orders list -----
async def my_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user)
    with SessionLocal() as s:
        orders = s.scalars(select(Order).where(Order.user_id == u.id).order_by(Order.id.desc())).all()
    if not orders:
        await update.message.reply_text("سفارشی نداری.", reply_markup=main_menu_kb(u.is_admin)); return
    lines = ["🧾 سفارش‌های من:"]
    for o in orders[:15]:
        status = o.status
        lines.append(f"#{o.id} | {o.plan.name if o.plan else '-'} | {fmt_price(o.price_paid)} | وضعیت: {status} | پایان: {o.expires_at.strftime('%Y-%m-%d') if o.expires_at else '-'}")
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_kb(u.is_admin))

# ----- Tickets -----
async def tickets_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user)
    with SessionLocal() as s:
        tks = s.scalars(select(Ticket).where(Ticket.user_id == u.id).order_by(Ticket.id.desc())).all()
    lines = ["🎫 تیکت‌های من:"]
    for t in tks[:10]:
        lines.append(f"#{t.id} | {t.title} | {t.status}")
    lines.append("\nبرای ساخت تیکت جدید یک عنوان بفرست.")
    await update.message.reply_text("\n".join(lines), reply_markup=cancel_only_kb())
    return St.TICKET_NEW_TITLE

async def ticket_new_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    u = ensure_user(update.effective_user)
    with SessionLocal() as s:
        t = Ticket(user_id=u.id, title=title, status="open")
        s.add(t); s.commit()
        ctx.user_data["ticket_id"] = t.id
    await update.message.reply_text("متن پیام اول رو بفرست:", reply_markup=cancel_only_kb())
    return St.TICKET_NEW_MESSAGE

async def ticket_new_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    tid = ctx.user_data.get("ticket_id")
    with SessionLocal() as s:
        s.add(TicketMessage(ticket_id=tid, from_admin=False, text=text)); s.commit()
        t = s.get(Ticket, tid)
    await update.message.reply_text("تیکت ارسال شد ✅", reply_markup=main_menu_kb(ensure_user(update.effective_user).is_admin))
    # notify admins
    with SessionLocal() as s:
        admins = s.scalars(select(Admin)).all()
    for a in admins:
        try:
            await application.bot.send_message(a.id, f"🎫 تیکت جدید #{tid}\nعنوان: {t.title}\nاز: {update.effective_user.id}")
        except: pass
    return ConversationHandler.END

# ----- Admin: Receipt actions -----
async def receipt_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("rc_ok:") or data.startswith("rc_no:"):
        rid = int(data.split(":")[1])
        approve = data.startswith("rc_ok:")
        with SessionLocal() as s:
            r = s.get(Receipt, rid)
            if not r or r.status != "pending":
                await q.edit_message_caption(caption="این رسید پیدا نشد یا منقضی شده.", reply_markup=None)
                return
            r.status = "approved" if approve else "rejected"
            s.commit()
            if approve:
                if r.target == "wallet":
                    u = s.get(User, r.user_id); u.wallet += r.amount
                    s.add(WalletTx(user_id=u.id, amount=r.amount, reason="شارژ کیف پول (رسید تایید شد)"))
                    s.commit()
                elif r.target.startswith("order:"):
                    oid = int(r.target.split(":")[1])
                    o = s.get(Order, oid)
                    if o and o.status == "pending":
                        # assign config
                        plan = s.get(Plan, o.plan_id)
                        cfg = s.scalar(select(ConfigItem).where(ConfigItem.plan_id == plan.id, ConfigItem.is_used == False).limit(1))
                        if cfg:
                            cfg.is_used = True
                            o.config_item_id = cfg.id
                            o.expires_at = datetime.utcnow() + timedelta(days=plan.days)
                            o.price_paid = r.amount
                            o.status = "delivered"
                            # discount usage update if any
                            # (we can't know code here; already applied at order creation)
                            s.commit()
                            # deliver
                            try:
                                if cfg.payload:
                                    await application.bot.send_message(o.user_id, f"خرید تایید شد ✅\nکانفیگ:\n```\n{cfg.payload}\n```", parse_mode=constants.ParseMode.MARKDOWN)
                                if cfg.image_file_id:
                                    await application.bot.send_photo(o.user_id, cfg.image_file_id, caption="تصویر کانفیگ")
                            except Exception as e:
                                log.warning(f"send cfg failed: {e}")
                            order_reminder_jobs(ctx, o)
                        else:
                            # no stock -> refund to wallet
                            u = s.get(User, o.user_id)
                            u.wallet += r.amount
                            s.add(WalletTx(user_id=u.id, amount=r.amount, reason="بازگشت وجه: اتمام موجودی"))
                            o.status = "canceled"
                            s.commit()
                            await application.bot.send_message(o.user_id, "متاسفانه موجودی پلن تموم شده بود؛ مبلغ به کیف‌پولت برگشت.")
            # notify user
            try:
                await application.bot.send_message(r.user_id, f"وضعیت رسید شما: {'تایید شد ✅' if approve else 'رد شد ❌'}")
            except: pass
        await q.edit_message_caption(caption=f"رسید {'تایید' if approve else 'رد'} شد.", reply_markup=None)

# ----- Admin: Panel -----
async def admin_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user)
    if not u.is_admin:
        await update.message.reply_text("شما ادمین نیستید.", reply_markup=main_menu_kb(False)); return ConversationHandler.END
    await update.message.reply_text("پنل ادمین ⚙️", reply_markup=admin_menu_kb())
    return St.ADMIN_PANEL

async def admin_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user)
    txt = update.message.text.strip()
    if txt == "↩️ بازگشت به حالت کاربر":
        await send_main_menu(update, ctx, "بازگشت به حالت کاربر."); return ConversationHandler.END

    if txt == "💳 تغییر شماره کارت":
        await update.message.reply_text("شماره کارت جدید را ارسال کن:", reply_markup=cancel_only_kb()); return St.ADMIN_CARD_SET

    if txt == "🧑‍💻 مدیریت ادمین‌ها":
        with SessionLocal() as s:
            admins = s.scalars(select(Admin)).all()
        ids = ", ".join([str(a.id) for a in admins]) or "-"
        await update.message.reply_text(f"لیست ادمین‌ها: {ids}\nبرای افزودن، آیدی عددی را بفرست.\nبرای حذف بنویس: حذف <id>\n(ادمین پیش‌فرض حذف نمی‌شود)", reply_markup=cancel_only_kb()); return St.ADMIN_ADD_ADMIN

    if txt == "📥 رسیدهای در انتظار":
        with SessionLocal() as s:
            recs = s.scalars(select(Receipt).where(Receipt.status=="pending").order_by(Receipt.id)).all()
        if not recs:
            await update.message.reply_text("رسیدهای در انتظار: 0"); return St.ADMIN_PANEL
        for r in recs[:20]:
            with SessionLocal() as s:
                u2 = s.get(User, r.user_id)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("تایید ✅", callback_data=f"rc_ok:{r.id}"),
                                        InlineKeyboardButton("رد ❌", callback_data=f"rc_no:{r.id}")]])
            try:
                await update.message.reply_photo(r.photo_file_id,
                    caption=f"🧾 رسید #{r.id}\nاز: @{u2.username or '-'} (ID:{u2.id})\nمبلغ: {fmt_price(r.amount)}\nهدف: {r.target}\nتاریخ: {r.submitted_at.strftime('%Y-%m-%d %H:%M')}",
                    reply_markup=kb)
            except:
                await update.message.reply_text(f"🧾 رسید #{r.id} مبلغ {fmt_price(r.amount)} از {u2.id}", reply_markup=kb)
        return St.ADMIN_PANEL

    if txt == "👛 کیف پول کاربر":
        await update.message.reply_text("آیدی عددی/یوزرنیم را بفرست:", reply_markup=cancel_only_kb()); return St.ADMIN_USER_WALLET_QUERY

    if txt == "🏷 کدهای تخفیف":
        await update.message.reply_text("ساخت کد: «کد درصد مبلغ حداکثر_استفاده(۰=نامحدود) YYYY-MM-DD(تاریخ انقضا اختیاری)»\nمثال:  SALE50 50 0 100 2025-12-31\nیا بنویس «لیست»", reply_markup=cancel_only_kb()); return St.ADMIN_CREATE_CODE

    if txt == "📣 اعلان همگانی":
        await update.message.reply_text("متن اعلان را بفرست:", reply_markup=cancel_only_kb()); return St.ADMIN_BROADCAST

    if txt == "📦 مدیریت پلن و مخزن":
        with SessionLocal() as s:
            plans = s.scalars(select(Plan)).all()
        if not plans:
            await update.message.reply_text("پلنی وجود ندارد. برای ساخت بنویس: ساخت پلن")
            return St.ADMIN_PLANS
        lines = ["پلن‌ها:"]
        for p in plans:
            with SessionLocal() as s:
                stock = plan_stock(s, p.id)
            lines.append(f"#{p.id} {p.name} | {p.days}روز | {p.traffic_gb}GB | فروش: {fmt_price(p.price_sell)} | موجودی: {stock}")
        lines.append("\nبرای شارژ مخزن بنویس: شارژ <id>\nبرای پاکسازی مخزن: پاکسازی <id>\nبرای ساخت پلن: ساخت پلن")
        await update.message.reply_text("\n".join(lines), reply_markup=cancel_only_kb()); return St.ADMIN_PLANS

    if txt == "📈 آمار فروش":
        with SessionLocal() as s:
            now = datetime.utcnow()
            d7 = now - timedelta(days=7)
            d30 = now - timedelta(days=30)
            all_orders = s.scalars(select(Order).where(Order.status.in_(["delivered","expired"]))).all()
            last7 = [o for o in all_orders if o.created_at>=d7]
            last30 = [o for o in all_orders if o.created_at>=d30]
            def sum_paid(lst): return sum(o.price_paid for o in lst)
            def sum_profit(lst): return sum((o.price_paid - (o.plan.price_cost if o.plan else 0.0)) for o in lst)
            top = s.execute(
                select(User.id, User.username, func.sum(Order.price_paid).label("spent"))
                .join(Order, Order.user_id==User.id)
                .group_by(User.id)
                .order_by(func.sum(Order.price_paid).desc())
                .limit(5)
            ).all()
        lines = [
            f"۷ روز اخیر: فروش {fmt_price(sum_paid(last7))} | سود {fmt_price(sum_profit(last7))}",
            f"۳۰ روز اخیر: فروش {fmt_price(sum_paid(last30))} | سود {fmt_price(sum_profit(last30))}",
            f"کل فروش: {fmt_price(sum_paid(all_orders))}"
        ]
        lines.append("\n🧑‍💼 Top Buyers:")
        for i,(uid,un,spent) in enumerate(top,1):
            lines.append(f"{i}. @{un or '-'} ({uid}) — {fmt_price(spent)}")
        lines.append("\nریست آمار (صرفاً علامت‌گذاری): فعلاً دستی نیاز نیست؛ بر اساس تاریخ محاسبه می‌شود.")
        await update.message.reply_text("\n".join(lines)); return St.ADMIN_PANEL

    if txt == "👥 کاربران":
        with SessionLocal() as s:
            cnt = s.scalar(select(func.count()).select_from(User)) or 0
        await update.message.reply_text(f"تعداد کاربران: {cnt}\nبرای جستجو آیدی عددی/یوزرنیم را بفرست.", reply_markup=cancel_only_kb()); return St.ADMIN_USERS

    await update.message.reply_text("گزینه نامعتبر.", reply_markup=admin_menu_kb()); return St.ADMIN_PANEL

# --- Admin sub-states ---
async def admin_card_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    new = update.message.text.strip()
    with SessionLocal() as s:
        c = s.get(AppConfig, "card_number")
        if not c: s.add(AppConfig(key="card_number", value=new))
        else: c.value = new
        s.commit()
    await update.message.reply_text("شماره کارت بروزرسانی شد ✅", reply_markup=admin_menu_kb()); return St.ADMIN_PANEL

async def admin_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    with SessionLocal() as s:
        if t.startswith("حذف "):
            try:
                rid = int(t.split(" ",1)[1])
                if rid == ADMIN_ID:
                    await update.message.reply_text("ادمین پیش‌فرض قابل حذف نیست."); return St.ADMIN_ADD_ADMIN
                a = s.get(Admin, rid)
                if a: s.delete(a)
                u = s.get(User, rid)
                if u: u.is_admin = False
                s.commit()
                await update.message.reply_text("حذف شد.")
            except:
                await update.message.reply_text("فرمت نامعتبر.")
        else:
            try:
                uid = int(t)
                if not s.get(User, uid):
                    s.add(User(id=uid, first_name="-"))
                if not s.get(Admin, uid):
                    s.add(Admin(id=uid))
                u = s.get(User, uid); u.is_admin = True
                s.commit()
                await update.message.reply_text("ادمین اضافه شد ✅")
            except:
                await update.message.reply_text("فرمت نامعتبر.")
    return St.ADMIN_ADD_ADMIN

async def admin_user_wallet_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.message.text.strip().lstrip("@")
    with SessionLocal() as s:
        if q.isdigit():
            u = s.get(User, int(q))
        else:
            u = s.scalar(select(User).where(User.username == q))
        if not u:
            await update.message.reply_text("یوزر پیدا نشد.")
            return St.ADMIN_USER_WALLET_QUERY
        ctx.user_data["target_user_id"] = u.id
        await update.message.reply_text(f"کاربر {u.id} @{u.username or '-'} | موجودی: {fmt_price(u.wallet)}\n"
                                        f"برای افزایش: +100000\nبرای کاهش: -50000", reply_markup=cancel_only_kb())
    return St.ADMIN_USER_WALLET_EDIT

async def admin_user_wallet_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip().replace(",","")
    try:
        delta = float(t)
    except:
        await update.message.reply_text("عدد نامعتبر.")
        return St.ADMIN_USER_WALLET_EDIT
    uid = ctx.user_data.get("target_user_id")
    with SessionLocal() as s:
        u = s.get(User, uid)
        u.wallet += delta
        s.add(WalletTx(user_id=uid, amount=delta, reason="ادیت ادمین"))
        s.commit()
    await update.message.reply_text("بروزرسانی شد ✅"); return St.ADMIN_PANEL

async def admin_create_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if t == "لیست":
        with SessionLocal() as s:
            codes = s.scalars(select(DiscountCode)).all()
        if not codes:
            await update.message.reply_text("هیچ کدی نداریم.")
            return St.ADMIN_CREATE_CODE
        lines = []
        for c in codes:
            lines.append(f"{c.code} | % {c.percent or 0} | مبلغ {int(c.amount or 0):,} | استفاده {c.used_count}/{c.max_uses or '∞'} | انقضا {c.expires_at.date() if c.expires_at else '-'} | جمع تخفیف {int(c.total_discount_given):,}")
        await update.message.reply_text("\n".join(lines))
        return St.ADMIN_CREATE_CODE

    parts = t.split()
    if len(parts) < 4:
        await update.message.reply_text("فرمت: کد درصد مبلغ حداکثر_استفاده [YYYY-MM-DD]")
        return St.ADMIN_CREATE_CODE
    code, percent, amount, maxu = parts[:4]
    exp = None
    if len(parts) >= 5:
        try:
            exp = datetime.strptime(parts[4], "%Y-%m-%d")
        except:
            await update.message.reply_text("تاریخ نامعتبر.")
            return St.ADMIN_CREATE_CODE
    try:
        percent = int(percent); amount = float(amount); maxu = int(maxu)
    except:
        await update.message.reply_text("اعداد نامعتبر.")
        return St.ADMIN_CREATE_CODE
    with SessionLocal() as s:
        if s.scalar(select(DiscountCode).where(DiscountCode.code==code)):
            await update.message.reply_text("کد تکراری است.")
            return St.ADMIN_CREATE_CODE
        s.add(DiscountCode(code=code, percent=percent or None, amount=amount or None, max_uses=maxu, expires_at=exp))
        s.commit()
    await update.message.reply_text("کد ساخته شد ✅"); return St.ADMIN_PANEL

async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # send to all
    with SessionLocal() as s:
        users = s.scalars(select(User.id)).all()
    ok, fail = 0,0
    for uid in users:
        try:
            await application.bot.send_message(uid, f"📣 اعلان: {text}")
            ok += 1
        except:
            fail += 1
    await update.message.reply_text(f"ارسال شد. موفق: {ok}، ناموفق: {fail}")
    return St.ADMIN_PANEL

async def admin_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if t == "ساخت پلن":
        await update.message.reply_text("فرمت: نام روز حجمGB قیمت_فروش قیمت_تمام‌شده\nنمونه: برنزی 30 150 120000 80000")
        return St.ADMIN_PLANS_NEW
    if t.startswith("شارژ "):
        try:
            pid = int(t.split()[1])
            ctx.user_data["charge_plan_id"] = pid
            await update.message.reply_text("پیام‌های حاوی کانفیگ را یکی‌یکی بفرست (متن یا عکس). برای اتمام بزن: اتمام", reply_markup=cancel_only_kb())
            return St.ADMIN_STOCK_ADD_STREAM
        except:
            await update.message.reply_text("شناسه نامعتبر.")
            return St.ADMIN_PLANS
    if t.startswith("پاکسازی "):
        try:
            pid = int(t.split()[1])
            with SessionLocal() as s:
                cnt = s.query(ConfigItem).filter(ConfigItem.plan_id==pid, ConfigItem.is_used==False).delete()
                s.commit()
            await update.message.reply_text(f"مخزن پاک شد. حذف آزاد: {cnt}")
            return St.ADMIN_PLANS
        except Exception as e:
            await update.message.reply_text("خطا در پاکسازی.")
            return St.ADMIN_PLANS
    await update.message.reply_text("دستور نامعتبر."); return St.ADMIN_PLANS

async def admin_plans_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.strip().split()
    if len(parts) != 5:
        await update.message.reply_text("فرمت نادرست. نمونه: برنزی 30 150 120000 80000")
        return St.ADMIN_PLANS_NEW
    name, days, gb, price_sell, price_cost = parts
    try:
        days = int(days); gb = int(gb); price_sell = float(price_sell); price_cost = float(price_cost)
    except:
        await update.message.reply_text("اعداد نامعتبر.")
        return St.ADMIN_PLANS_NEW
    with SessionLocal() as s:
        s.add(Plan(name=name, days=days, traffic_gb=gb, price_sell=price_sell, price_cost=price_cost, active=True))
        s.commit()
    await update.message.reply_text("پلن ساخته شد ✅"); return St.ADMIN_PLANS

async def admin_stock_stream(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() == "اتمام":
        await update.message.reply_text("شارژ مخزن تمام شد ✅", reply_markup=admin_menu_kb()); return St.ADMIN_PANEL
    pid = ctx.user_data.get("charge_plan_id")
    with SessionLocal() as s:
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            s.add(ConfigItem(plan_id=pid, image_file_id=file_id))
        else:
            s.add(ConfigItem(plan_id=pid, payload=update.message.text))
        s.commit()
    await update.message.reply_text("ثبت شد. ادامه بده یا بزن «اتمام».")
    return St.ADMIN_STOCK_ADD_STREAM

async def admin_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.message.text.strip().lstrip("@")
    with SessionLocal() as s:
        if q.isdigit():
            u = s.get(User, int(q))
        else:
            u = s.scalar(select(User).where(User.username==q))
        if not u:
            await update.message.reply_text("پیدا نشد.")
            return St.ADMIN_USERS
        orders = s.scalar(select(func.count()).select_from(Order).where(Order.user_id==u.id)) or 0
    await update.message.reply_text(f"کاربر {u.id} @{u.username or '-'}\n"
                                    f"موجودی: {fmt_price(u.wallet)}\n"
                                    f"تعداد خرید: {orders}\n"
                                    f"تاریخ عضویت: {u.created_at.strftime('%Y-%m-%d')}")
    return St.ADMIN_USERS

# Low stock notifier
async def notify_low_stock(ctx, plan_id: int, stock: int):
    with SessionLocal() as s:
        p = s.get(Plan, plan_id)
        admins = s.scalars(select(Admin)).all()
    for a in admins:
        try:
            await ctx.bot.send_message(a.id, f"⚠️ مخزن پلن «{p.name}» رو به اتمام است. موجودی: {stock}")
        except: pass

# ----- Fallbacks -----
async def cancel_any(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = ensure_user(update.effective_user)
    await update.message.reply_text("لغو شد.", reply_markup=main_menu_kb(u.is_admin))
    return ConversationHandler.END

async def back_any(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # just go to main menu
    return await cancel_any(update, ctx)

# ----- Dispatcher wiring -----
conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
        MessageHandler(filters.Regex("^🛍 خرید کانفیگ$"), buy_entry),
        MessageHandler(filters.Regex("^👛 کیف پول من$"), wallet_entry),
        MessageHandler(filters.Regex("^🧾 سفارش‌های من$"), my_orders),
        MessageHandler(filters.Regex("^🎫 تیکت$"), tickets_entry),
        MessageHandler(filters.Regex("^⚙️ پنل ادمین$"), admin_entry),
        CommandHandler("help", help_cmd)
    ],
    states={
        St.BUY_SELECT_PLAN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, buy_select_plan),
            MessageHandler(filters.Regex("^↩️ بازگشت$"), back_any),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.BUY_APPLY_DISCOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, apply_discount),
            MessageHandler(filters.Regex("^↩️ بازگشت$"), buy_entry),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.BUY_PAY_METHOD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, buy_pay_method),
            MessageHandler(filters.Regex("^↩️ بازگشت$"), buy_entry),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.BUY_WAIT_RECEIPT_PHOTO: [
            MessageHandler(filters.PHOTO, buy_receipt_photo),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.WALLET_TOPUP_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_amount),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.WALLET_RECEIPT: [
            MessageHandler(filters.PHOTO, wallet_receipt),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.TICKET_NEW_TITLE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_new_title),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.TICKET_NEW_MESSAGE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, ticket_new_message),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_PANEL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_router),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_CARD_SET: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_set),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_ADD_ADMIN: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_admins),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_USER_WALLET_QUERY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_user_wallet_query),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_USER_WALLET_EDIT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_user_wallet_edit),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_CREATE_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_create_code),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_BROADCAST: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_PLANS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_plans),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_PLANS_NEW: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_plans_new),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_STOCK_ADD_STREAM: [
            MessageHandler(filters.ALL & ~filters.COMMAND, admin_stock_stream),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
        St.ADMIN_USERS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_users),
            MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        ],
    },
    fallbacks=[
        MessageHandler(filters.Regex("^❌ انصراف$"), cancel_any),
        MessageHandler(filters.Regex("^↩️ بازگشت$"), back_any),
    ],
    name="main-conv",
    persistent=True
)

application.add_handler(conv)
application.add_handler(CallbackQueryHandler(receipt_callback, pattern="^(rc_ok|rc_no):"))

# ----- FastAPI routes -----
@app.get("/", response_class=PlainTextResponse)
async def root():
    return "OK"

@app.post(WEBHOOK_PATH)
async def tg_webhook(request: Request):
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
            raise HTTPException(403, "bad secret")
    data = await request.json()
    update = Update.de_json(data=data, bot=application.bot)
    await application.update_queue.put(update)
    return JSONResponse({"ok": True})

# ----- Startup tasks -----
@app.on_event("startup")
async def on_startup():
    # run PTB application in background
    asyncio.create_task(application.initialize())
    asyncio.create_task(application.start())
    # auto set webhook
    if TOKEN and BASE_URL:
        url = f"{BASE_URL}{WEBHOOK_PATH}"
        try:
            await application.bot.set_webhook(
                url=url,
                secret_token=WEBHOOK_SECRET or None,
                allowed_updates=constants.UpdateType.ALL
            )
            log.info(f"Webhook set to: {url}")
        except Exception as e:
            log.error(f"Failed to set webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()

# ----- Local run -----
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
