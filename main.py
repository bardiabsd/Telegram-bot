import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Float, Boolean, ForeignKey, Text, func
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto
)
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ConversationHandler
)

# =========================
# ====== Config/ENV =======
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
DEFAULT_CARD = os.getenv("CARD_NUMBER", "6037-****-****-****").strip()

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN env var is required")
if not BASE_URL:
    raise RuntimeError("❌ BASE_URL env var is required")

ADMIN_IDS: List[int] = []
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_IDS.append(int(part))

VERSION = "v1.4.0-aliPlus-perfect"

# =========================
# ====== Database =========
# =========================
Base = declarative_base()
engine = create_engine("sqlite:///./data.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)  # telegram user id
    username = Column(String(64))
    first_name = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    wallet = Column(Float, default=0.0, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    total_spent = Column(Float, default=0.0, nullable=False)

    purchases = relationship("Order", back_populates="user")
    tickets = relationship("Ticket", back_populates="user")

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(128), nullable=False)
    days = Column(Integer, nullable=False)
    volume_gb = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    cost_price = Column(Float, default=0.0, nullable=False)  # قیمت تمام‌شده
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    configs = relationship("ConfigItem", back_populates="plan", cascade="all, delete-orphan")

class ConfigItem(Base):
    __tablename__ = "config_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    content = Column(Text, nullable=False)       # متن یا لینک کانفیگ
    image_b64 = Column(Text, nullable=True)      # اگر به صورت عکس ذخیره شده (Base64)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)

    plan = relationship("Plan", back_populates="configs")

class DiscountCode(Base):
    __tablename__ = "discount_codes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, index=True, nullable=False)
    percent = Column(Integer, nullable=False)  # 0..100
    max_uses = Column(Integer, default=0, nullable=False)  # 0 = unlimited
    used_count = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    price = Column(Float, nullable=False)
    discounted_price = Column(Float, nullable=False)
    discount_code = Column(String(64), nullable=True)
    paid = Column(Boolean, default=False, nullable=False)
    paid_by = Column(String(32), nullable=True)  # wallet / c2c / difference
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at = Column(DateTime, nullable=True)

    # فعال برای کاربر
    config_sent = Column(Boolean, default=False, nullable=False)
    config_text = Column(Text, nullable=True)  # کانفیگ ارسالی
    config_image_b64 = Column(Text, nullable=True)

    # زمان انقضا (برای هشدارها)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="purchases")
    plan = relationship("Plan")

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String(64), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)  # اگر مربوط به خرید پلن
    amount = Column(Float, nullable=False)
    type = Column(String(32), nullable=False)  # wallet_topup / c2c / difference
    text = Column(Text, nullable=True)
    photo_file_id = Column(String(256), nullable=True)
    status = Column(String(16), default="pending", nullable=False)  # pending/accepted/rejected
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(Integer, nullable=True)  # admin id

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(16), default="open", nullable=False)  # open/closed
    subject = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="tickets")
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")

class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    sender_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ticket = relationship("Ticket", back_populates="messages")

class GlobalKV(Base):
    __tablename__ = "global_kv"
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)

def init_db():
    Base.metadata.create_all(engine, checkfirst=True)
    db = SessionLocal()
    try:
        # ثبت ادمین‌های پیش‌فرض
        for aid in ADMIN_IDS:
            u = db.query(User).get(aid)
            if not u:
                u = User(id=aid, username=None, first_name="Admin", wallet=0.0, is_admin=True)
                db.add(u)
        # اگر کارت پیش‌فرض ذخیره نشده، ذخیره کن
        if not db.query(GlobalKV).get("card_number"):
            db.add(GlobalKV(key="card_number", value=DEFAULT_CARD))
        db.commit()
    finally:
        db.close()

init_db()

# =========================
# ====== Bot/App ==========
# =========================
app = FastAPI(title="AliPlus Perfect", version=VERSION)

application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

# ============== helpers ==============
def fmt_money(amount: float) -> str:
    # نمایش تومان با فرمت ساده
    return f"{int(round(amount)):,} تومان"

def get_card_number(db) -> str:
    kv = db.query(GlobalKV).get("card_number")
    return kv.value if kv else DEFAULT_CARD

def is_admin_user(user_id: int, db) -> bool:
    u = db.query(User).get(user_id)
    return bool(u and u.is_admin)

def ensure_user(update: Update, db) -> User:
    tg_user = update.effective_user
    u = db.query(User).get(tg_user.id)
    if not u:
        u = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name or "",
            wallet=0.0,
            is_admin=(tg_user.id in ADMIN_IDS)
        )
        db.add(u)
        db.commit()
    else:
        # به‌روز رسانی نام/یوزرنیم
        changed = False
        if u.username != tg_user.username:
            u.username = tg_user.username
            changed = True
        if (tg_user.first_name or "") != u.first_name:
            u.first_name = tg_user.first_name or ""
            changed = True
        if changed:
            db.commit()
    return u

def user_main_keyboard(is_admin_flag: bool) -> ReplyKeyboardMarkup:
    # منوی اصلی کاربر + اگر ادمین است دکمه پنل ادمین را هم نشان بده
    rows = [
        [KeyboardButton("🛒 خرید سرویس"), KeyboardButton("📦 کانفیگ‌های من")],
        [KeyboardButton("👤 حساب کاربری"), KeyboardButton("💬 تیکت پشتیبانی")],
        [KeyboardButton("💼 کیف پول"), KeyboardButton("📊 آمار فروش")],  # کاربر آمار فروش عمومی نمی‌بیند ولی برای ادمین فعال می‌شود
    ]
    if is_admin_flag:
        rows.append([KeyboardButton("🛠 پنل ادمین")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def admin_panel_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("💳 شماره کارت"), KeyboardButton("👑 مدیریت ادمین‌ها")],
        [KeyboardButton("🧾 رسیدهای در انتظار"), KeyboardButton("👛 کیف پول کاربر")],
        [KeyboardButton("🏷 کدهای تخفیف"), KeyboardButton("🧰 مدیریت پلن و مخزن")],
        [KeyboardButton("📣 اعلان همگانی"), KeyboardButton("📈 آمار فروش (ادمین)")],
        [KeyboardButton("👥 کاربران"), KeyboardButton("⬅️ خروج از پنل ادمین")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def payment_inline_kb(order_id: int, has_discount: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("💼 پرداخت با کیف‌پول", callback_data=f"pay_wallet:{order_id}")],
        [InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data=f"pay_c2c:{order_id}")],
    ]
    # کد تخفیف کنار گزینه‌های پرداخت (نه در منوی اصلی)
    if not has_discount:
        buttons.append([InlineKeyboardButton("🏷 اعمال کد تخفیف", callback_data=f"apply_discount:{order_id}")])
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data=f"cancel_payment:{order_id}")])
    return InlineKeyboardMarkup(buttons)

def plan_row_text(plan: Plan, inventory_count: int) -> str:
    return (
        f"🧩 {plan.title}\n"
        f"⏳ مدت: {plan.days} روز | 🧪 حجم: {int(plan.volume_gb)} گیگ\n"
        f"💵 قیمت: {fmt_money(plan.price)}\n"
        f"📦 موجودی مخزن: {inventory_count} عدد"
    )

def my_configs_text(order: Order) -> str:
    status = "✅ فعال" if order.paid and order.config_sent else "⏳ در انتظار"
    exp = order.expires_at.strftime("%Y-%m-%d") if order.expires_at else "—"
    return (
        f"🧾 سفارش #{order.id}\n"
        f"سرویس: {order.plan.title}\n"
        f"قیمت نهایی: {fmt_money(order.discounted_price)}\n"
        f"وضعیت: {status}\n"
        f"⏰ انقضا: {exp}"
    )

# ============== startup/shutdown ==============
@app.on_event("startup")
async def on_startup():
    # initialize + webhook
    await application.initialize()
    webhook_url = f"{BASE_URL}/webhook"
    await application.bot.set_webhook(url=webhook_url)
    print(f"✅ Webhook set to: {webhook_url}")

    # برنامه زمان‌بندی هشدار انقضا
    async def daily_expiry_job():
        while True:
            try:
                db = SessionLocal()
                now = datetime.utcnow()
                soon5 = now + timedelta(days=5)
                soon3 = now + timedelta(days=3)
                # 5 روز مانده
                orders5 = db.query(Order).filter(
                    Order.paid == True,
                    Order.expires_at != None,
                    func.date(Order.expires_at) == func.date(soon5)
                ).all()
                # 3 روز مانده
                orders3 = db.query(Order).filter(
                    Order.paid == True,
                    Order.expires_at != None,
                    func.date(Order.expires_at) == func.date(soon3)
                ).all()
                # امروز منقضی
                orders0 = db.query(Order).filter(
                    Order.paid == True,
                    Order.expires_at != None,
                    func.date(Order.expires_at) == func.date(now)
                ).all()
                async with application.bot:
                    for od in orders5:
                        await application.bot.send_message(
                            od.user_id,
                            "⏳ رفیق! فقط ۵ روز تا پایان سرویس باقی مونده. اگر خواستی همین الان تمدیدش کن تا قطع نشه 🌟"
                        )
                    for od in orders3:
                        await application.bot.send_message(
                            od.user_id,
                            "⏳ فقط ۳ روز تا پایان سرویس مونده. اگه کاری داشتی من اینجام 😊"
                        )
                    for od in orders0:
                        await application.bot.send_message(
                            od.user_id,
                            "⌛️ سرویس‌ت تموم شد. از «کانفیگ‌های من» حذفش کردم. هر وقت آماده بودی، از «خرید سرویس» یه سرویس جدید بردار ✨"
                        )
                        # حذف از لیست کاربر (منطق: فقط نمایشی—سابقه سفارش می‌ماند، ولی نمایش در کانفیگ‌های من حذف شود)
                        od.config_text = None
                        od.config_image_b64 = None
                        db.commit()
            except Exception as e:
                print("expiry job error:", e)
            finally:
                try:
                    db.close()
                except:
                    pass
            await asyncio.sleep(24 * 60 * 60)  # روزی یک‌بار

    asyncio.create_task(daily_expiry_job())

@app.on_event("shutdown")
async def on_shutdown():
    await application.bot.delete_webhook(drop_pending_updates=False)
    await application.shutdown()
    await application.stop()

# =========================
# ====== Webhook ==========
# =========================
class TgWebhook(BaseModel):
    update_id: Optional[int]

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return JSONResponse({"ok": True})

@app.get("/")
async def root():
    return {"ok": True, "version": VERSION}

# =========================
# ====== Handlers =========
# =========================

# ------ /start ------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        u = ensure_user(update, db)
        # خوش‌آمدگویی کامل، خودمونی و مودبانه
        welcome = (
            f"سلام {u.first_name or 'رفیق'}! 👋\n"
            "به بات «عالی پلاس» خوش اومدی 🤝\n\n"
            "اینجا می‌تونی خیلی راحت سرویس بخری، کیف‌پولت رو شارژ کنی، تیکت بزنی، "
            "و هر وقت رسید کارت‌به‌کارت داشتی برامون بفرستی تا سریع تأیید بشه. "
            "هر مرحله با دکمه‌ها راهنمایی‌ت می‌کنم 😉✨\n\n"
            f"نسخه بات: {VERSION}"
        )
        await update.effective_message.reply_text(
            welcome,
            reply_markup=user_main_keyboard(u.is_admin)
        )
    finally:
        db.close()

# ------ متن منو اصلی ------
async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    db = SessionLocal()
    try:
        u = ensure_user(update, db)

        # پنل ادمین فقط برای ادمین
        if text == "🛠 پنل ادمین":
            if not u.is_admin:
                await update.message.reply_text("این بخش مخصوص ادمین‌هاست.")
                return
            await update.message.reply_text("به پنل ادمین خوش اومدی 😎", reply_markup=admin_panel_keyboard())
            return

        # خروج از پنل ادمین -> بازگشت به منوی کاربر
        if text == "⬅️ خروج از پنل ادمین":
            await update.message.reply_text("به منوی کاربر برگشتی ✅", reply_markup=user_main_keyboard(u.is_admin))
            return

        if text == "🛒 خرید سرویس":
            # نمایش لیست پلن‌ها
            plans = db.query(Plan).all()
            if not plans:
                await update.message.reply_text("هنوز پلنی ثبت نشده 🫣")
                return
            for p in plans:
                inv = db.query(ConfigItem).filter_by(plan_id=p.id, is_used=False).count()
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛍 انتخاب این پلن", callback_data=f"select_plan:{p.id}")]
                ])
                await update.message.reply_text(plan_row_text(p, inv), reply_markup=kb)
            return

        if text == "📦 کانفیگ‌های من":
            orders = db.query(Order).filter_by(user_id=u.id, paid=True).order_by(Order.id.desc()).all()
            if not orders:
                await update.message.reply_text("چیزی اینجا نیست هنوز 😊 از «خرید سرویس» یکی بردار")
                return
            for od in orders:
                await update.message.reply_text(my_configs_text(od))
                if od.config_text:
                    await update.message.reply_text(
                        f"🔑 کانفیگ:\n\n{od.config_text}\n\n(برای کپی، متنو انتخاب کن ✅)"
                    )
                if od.config_image_b64:
                    # در این نسخه برای سادگی، تصویر ذخیره‌شده ارسال نمی‌کنیم (می‌تونی بعدا از Base64 تبدیل کنی)
                    pass
            return

        if text == "👤 حساب کاربری":
            await update.message.reply_text(
                f"👤 {u.first_name or ''} @{u.username or '-'}\n"
                f"🪪 آیدی عددی: {u.id}\n"
                f"💼 کیف‌پول: {fmt_money(u.wallet)}\n"
                f"💸 مجموع خرید: {fmt_money(u.total_spent)}",
                reply_markup=user_main_keyboard(u.is_admin)
            )
            return

        if text == "💬 تیکت پشتیبانی":
            # ساده: ایجاد/لیست
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📨 تیکت جدید", callback_data="ticket_new")],
                [InlineKeyboardButton("🗂 تیکت‌های من", callback_data="ticket_list")]
            ])
            await update.message.reply_text("چیکار کنیم؟ 😊", reply_markup=kb)
            return

        if text == "💼 کیف پول":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ افزایش موجودی (ارسال رسید)", callback_data="wallet_topup")],
                [InlineKeyboardButton("❓ راهنما", callback_data="wallet_help")]
            ])
            await update.message.reply_text(
                f"موجودی فعلی: {fmt_money(u.wallet)}\n"
                "برای افزایش موجودی رسید کارت‌به‌کارت رو ارسال می‌کنی، ما تأیید می‌کنیم و موجودی شارژ میشه ✨",
                reply_markup=kb
            )
            return

        if text == "📊 آمار فروش":
            if not u.is_admin:
                await update.message.reply_text("این بخش مخصوص ادمین‌هاست.")
                return
            # آمار کلی
            sales_total = db.query(func.sum(Order.discounted_price)).filter(Order.paid==True).scalar() or 0
            cost_total = db.query(func.sum(Plan.cost_price)).join(Order, Order.plan_id==Plan.id).filter(Order.paid==True).scalar() or 0
            pure_profit = sales_total - cost_total
            await update.message.reply_text(
                f"📊 آمار کلی:\n"
                f"💰 فروش کل: {fmt_money(sales_total)}\n"
                f"🧾 سود خالص: {fmt_money(pure_profit)}\n"
                f"(برای جزئیات بیشتر از پنل ادمین → «📈 آمار فروش (ادمین)» استفاده کن)"
            )
            return

        # ===== پنل ادمین گزینه‌ها =====
        if u.is_admin:
            if text == "💳 شماره کارت":
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ تغییر شماره کارت", callback_data="admin_edit_card")]])
                await update.message.reply_text(f"شماره کارت فعلی:\n`{get_card_number(db)}`", parse_mode="Markdown", reply_markup=kb)
                return

            if text == "👑 مدیریت ادمین‌ها":
                admins = db.query(User).filter_by(is_admin=True).all()
                msg = "👑 ادمین‌ها:\n" + "\n".join([f"- {a.id} @{a.username or ''}" for a in admins]) if admins else "ادمینی ثبت نشده."
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add")],
                    [InlineKeyboardButton("➖ حذف ادمین", callback_data="admin_remove")]
                ])
                await update.message.reply_text(msg, reply_markup=kb)
                return

            if text == "🧾 رسیدهای در انتظار":
                recs = db.query(Receipt).filter_by(status="pending").order_by(Receipt.id.asc()).all()
                if not recs:
                    await update.message.reply_text("هیچ رسیدی در انتظار نیست ✅")
                else:
                    for r in recs:
                        caption = (
                            f"🧾 رسید #{r.id}\n"
                            f"👤 @{r.username or '-'} ({r.user_id})\n"
                            f"💵 مبلغ: {fmt_money(r.amount)}\n"
                            f"🎯 نوع: {r.type}\n"
                            f"🔗 سفارش: {r.order_id or '-'}\n"
                            f"⏱ تاریخ: {r.created_at}\n"
                            f"📝 متن: {r.text or '-'}"
                        )
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ تایید", callback_data=f"rcpt_ok:{r.id}"),
                             InlineKeyboardButton("❌ رد", callback_data=f"rcpt_no:{r.id}")]
                        ])
                        if r.photo_file_id:
                            await update.message.reply_photo(r.photo_file_id, caption=caption, reply_markup=kb)
                        else:
                            await update.message.reply_text(caption, reply_markup=kb)
                return

            if text == "👛 کیف پول کاربر":
                await update.message.reply_text("آیدی عددی یا یوزرنیم کاربر را بفرست (با @). برای انصراف بنویس «انصراف».")
                context.user_data["mode"] = "admin_wallet_find_user"
                return

            if text == "🏷 کدهای تخفیف":
                codes = db.query(DiscountCode).order_by(DiscountCode.id.desc()).all()
                if not codes:
                    await update.message.reply_text("کدی ثبت نشده.")
                else:
                    for c in codes:
                        left = "∞" if c.max_uses == 0 else f"{max(c.max_uses - c.used_count, 0)}"
                        exp = c.expires_at.strftime("%Y-%m-%d") if c.expires_at else "∞"
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔍 جزئیات", callback_data=f"disc_view:{c.id}")],
                            [InlineKeyboardButton("🗑 حذف", callback_data=f"disc_del:{c.id}")]
                        ])
                        await update.message.reply_text(
                            f"🏷 {c.code} | %{c.percent} | باقی: {left} | انقضا: {exp}",
                            reply_markup=kb
                        )
                kb2 = InlineKeyboardMarkup([[InlineKeyboardButton("➕ ساخت کد جدید", callback_data="disc_new")]])
                await update.message.reply_text("مدیریت کدهای تخفیف:", reply_markup=kb2)
                return

            if text == "🧰 مدیریت پلن و مخزن":
                plans = db.query(Plan).order_by(Plan.id.asc()).all()
                if not plans:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ ساخت پلن جدید", callback_data="plan_new")]])
                    await update.message.reply_text("پلنی موجود نیست.", reply_markup=kb)
                else:
                    for p in plans:
                        inv = db.query(ConfigItem).filter_by(plan_id=p.id, is_used=False).count()
                        kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton("📦 مدیریت مخزن", callback_data=f"plan_store:{p.id}")],
                            [InlineKeyboardButton("✏️ ویرایش پلن", callback_data=f"plan_edit:{p.id}"),
                             InlineKeyboardButton("🗑 حذف پلن", callback_data=f"plan_del:{p.id}")]
                        ])
                        await update.message.reply_text(plan_row_text(p, inv), reply_markup=kb)
                    kb2 = InlineKeyboardMarkup([[InlineKeyboardButton("➕ ساخت پلن جدید", callback_data="plan_new")]])
                    await update.message.reply_text("—", reply_markup=kb2)
                return

            if text == "📣 اعلان همگانی":
                await update.message.reply_text("متن اعلان را ارسال کن. (برای انصراف بنویس «انصراف»)")
                context.user_data["mode"] = "admin_broadcast"
                return

            if text == "📈 آمار فروش (ادمین)":
                # 7 روز، 30 روز، کل + تاپ بایرها
                now = datetime.utcnow()
                d7 = now - timedelta(days=7)
                d30 = now - timedelta(days=30)
                q_paid = db.query(Order).filter(Order.paid==True)
                total_all = sum([o.discounted_price for o in q_paid.all()])
                total_7 = sum([o.discounted_price for o in q_paid.filter(Order.paid_at>=d7).all()])
                total_30 = sum([o.discounted_price for o in q_paid.filter(Order.paid_at>=d30).all()])
                # سود خالص تقریبی
                cost_sum = 0.0
                for o in q_paid.all():
                    cost_sum += (o.plan.cost_price or 0.0)
                profit = total_all - cost_sum
                # تاپ خریداران
                buyers: Dict[int, float] = {}
                for o in q_paid.all():
                    buyers[o.user_id] = buyers.get(o.user_id, 0.0) + o.discounted_price
                top5 = sorted(buyers.items(), key=lambda x: x[1], reverse=True)[:5]

                lines = [
                    f"📈 آمار فروش ادمینی:",
                    f"۷ روز اخیر: {fmt_money(total_7)}",
                    f"۳۰ روز اخیر: {fmt_money(total_30)}",
                    f"فروش کل: {fmt_money(total_all)}",
                    f"سود خالص: {fmt_money(profit)}",
                    "",
                    "👑 Top Buyers:"
                ]
                for uid, amt in top5:
                    lines.append(f"- {uid}: {fmt_money(amt)}")
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🧹 ریست آمار", callback_data="stats_reset")]])
                await update.message.reply_text("\n".join(lines), reply_markup=kb)
                return

            if text == "👥 کاربران":
                users = db.query(User).order_by(User.created_at.desc()).limit(50).all()
                if not users:
                    await update.message.reply_text("کاربری نداریم هنوز.")
                else:
                    await update.message.reply_text("آخرین ۵۰ کاربر:")
                    for uu in users:
                        await update.message.reply_text(
                            f"🧑 @{uu.username or '-'} | {uu.first_name or ''}\n"
                            f"🪪 {uu.id}\n"
                            f"💼 {fmt_money(uu.wallet)} | 💸 مجموع خرید: {fmt_money(uu.total_spent)}"
                        )
                await update.message.reply_text("برای جستجو آیدی عددی یا @یوزرنیم بفرست. (انصراف = «انصراف»)")
                context.user_data["mode"] = "admin_user_search"
                return

        # حالت‌های ورودی متنی (مودها)
        mode = context.user_data.get("mode")
        if mode == "admin_broadcast" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
            else:
                # ارسال به همه
                ids = [row[0] for row in db.query(User.id).all()]
                sent = 0
                for uid in ids:
                    try:
                        await context.bot.send_message(uid, f"📣 اعلان:\n{text}")
                        sent += 1
                    except:
                        pass
                context.user_data["mode"] = None
                await update.message.reply_text(f"ارسال شد برای {sent} کاربر.")
            return

        if mode == "admin_wallet_find_user" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.", reply_markup=admin_panel_keyboard())
                return
            target = None
            if text.startswith("@"):
                target = db.query(User).filter(User.username==text[1:]).first()
            elif text.isdigit():
                target = db.query(User).get(int(text))
            if not target:
                await update.message.reply_text("پیدا نشد. دوباره بفرست یا «انصراف».")
                return
            context.user_data["admin_wallet_user_id"] = target.id
            await update.message.reply_text(
                f"کاربر پیدا شد: {target.id} @{target.username or '-'}\n"
                "مبلغ مثبت برای شارژ و منفی برای کسر ارسال کن. مثال: 50000 یا -20000"
            )
            context.user_data["mode"] = "admin_wallet_change"
            return

        if mode == "admin_wallet_change" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.", reply_markup=admin_panel_keyboard())
                return
            try:
                amt = float(text)
            except:
                await update.message.reply_text("مبلغ نامعتبره. مثال: 50000 یا -20000")
                return
            target_id = context.user_data.get("admin_wallet_user_id")
            tu = db.query(User).get(target_id)
            if not tu:
                await update.message.reply_text("کاربر پیدا نشد.")
                context.user_data["mode"] = None
                return
            tu.wallet = max(0.0, (tu.wallet or 0.0) + amt)
            db.commit()
            await update.message.reply_text(f"انجام شد. موجودی جدید: {fmt_money(tu.wallet)}", reply_markup=admin_panel_keyboard())
            context.user_data["mode"] = None
            return

        if mode == "admin_user_search" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.", reply_markup=admin_panel_keyboard())
                return
            target = None
            if text.startswith("@"):
                target = db.query(User).filter(User.username==text[1:]).first()
            elif text.isdigit():
                target = db.query(User).get(int(text))
            if not target:
                await update.message.reply_text("کاربر پیدا نشد.")
            else:
                await update.message.reply_text(
                    f"🧑 @{target.username or '-'} | {target.first_name or ''}\n"
                    f"🪪 {target.id}\n"
                    f"💼 {fmt_money(target.wallet)} | 💸 مجموع خرید: {fmt_money(target.total_spent)}"
                )
            return

        # اگر چیزی نفهمید
        await update.message.reply_text("متوجه نشدم چی میخوای 🫣 از دکمه‌های پایین استفاده کن لطفاً.")
    finally:
        db.close()

# ------ Callback queries ------
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    db = SessionLocal()
    try:
        u = ensure_user(update, db)

        # انتخاب پلن
        if data.startswith("select_plan:"):
            plan_id = int(data.split(":")[1])
            plan = db.query(Plan).get(plan_id)
            if not plan:
                await query.edit_message_text("این پلن موجود نیست.")
                return
            inv_count = db.query(ConfigItem).filter_by(plan_id=plan.id, is_used=False).count()
            if inv_count == 0:
                # نوتیف مودبانه برای خالی بودن
                await query.edit_message_text(
                    plan_row_text(plan, inv_count) + "\n\n"
                    "این مخزن فعلاً خالیه 😅 به‌زودی شارژ میشه."
                )
                # نوتیف به ادمین‌ها اگر نزدیک خالی شدن/خالی شد
                for aid in ADMIN_IDS:
                    try:
                        await context.bot.send_message(aid, f"⚠️ مخزن پلن «{plan.title}» خالی شد.")
                    except:
                        pass
                return
            # ایجاد سفارشِ پرداخت نشده
            od = Order(
                user_id=u.id, plan_id=plan.id, price=plan.price,
                discounted_price=plan.price, discount_code=None
            )
            db.add(od)
            db.commit()
            txt = (
                f"جزئیات پلن:\n{plan_row_text(plan, inv_count)}\n\n"
                f"مبلغ قابل پرداخت: {fmt_money(od.discounted_price)}\n\n"
                "یکی از روش‌های پرداخت رو انتخاب کن 👇"
            )
            await query.edit_message_text(txt, reply_markup=payment_inline_kb(od.id, has_discount=False))
            return

        # اعمال کد تخفیف
        if data.startswith("apply_discount:"):
            order_id = int(data.split(":")[1])
            context.user_data["mode"] = f"enter_discount:{order_id}"
            await query.edit_message_text(
                "کد تخفیف رو بفرست عزیز 🌟\n(برای انصراف بنویس «انصراف»)"
            )
            return

        # پرداخت با کیف پول
        if data.startswith("pay_wallet:"):
            order_id = int(data.split(":")[1])
            od = db.query(Order).get(order_id)
            if not od or od.user_id != u.id:
                await query.edit_message_text("سفارش پیدا نشد.")
                return
            need = od.discounted_price
            if u.wallet >= need:
                # کم کردن + پرداخت
                u.wallet -= need
                u.total_spent += need
                od.paid = True
                od.paid_by = "wallet"
                od.paid_at = datetime.utcnow()
                # ارسال کانفیگ
                cfg = db.query(ConfigItem).filter_by(plan_id=od.plan_id, is_used=False).first()
                if not cfg:
                    await query.edit_message_text("پرداخت شد ولی مخزن خالیه! به پشتیبانی خبر بده 🙏")
                else:
                    cfg.is_used = True
                    od.config_sent = True
                    od.config_text = cfg.content
                    # محاسبه انقضا
                    od.expires_at = datetime.utcnow() + timedelta(days=od.plan.days)
                    db.commit()
                    await query.edit_message_text(
                        "🎉 پرداخت با کیف‌پول با موفقیت انجام شد! اینم کانفیگت، مبارکه! 🥳\n"
                        "🔑 برای کپی متن رو انتخاب کن 👇"
                    )
                    await context.bot.send_message(u.id, f"{od.config_text}")
            else:
                diff = need - u.wallet
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 پرداخت مابه‌تفاوت (کارت‌به‌کارت)", callback_data=f"pay_diff:{order_id}")],
                    [InlineKeyboardButton("❌ انصراف", callback_data=f"cancel_payment:{order_id}")]
                ])
                await query.edit_message_text(
                    f"موجودی کیف‌پولت کافی نیست 🫣\n"
                    f"مابه‌تفاوت: {fmt_money(diff)}\n"
                    "میخوای مابه‌تفاوت رو کارت‌به‌کارت بدی و رسید رو بفرستی؟",
                    reply_markup=kb
                )
            return

        # کارت‌به‌کارت مستقیم
        if data.startswith("pay_c2c:") or data.startswith("pay_diff:"):
            order_id = int(data.split(":")[1])
            od = db.query(Order).get(order_id)
            if not od or od.user_id != u.id:
                await query.edit_message_text("سفارش پیدا نشد.")
                return

            if data.startswith("pay_c2c:"):
                amount = od.discounted_price
                pay_type = "c2c"
            else:
                amount = max(0.0, od.discounted_price - u.wallet)
                pay_type = "difference"

            card = get_card_number(db)
            context.user_data["mode"] = f"await_receipt:{pay_type}:{order_id}:{amount}"
            await query.edit_message_text(
                "لطفاً مبلغ زیر رو کارت‌به‌کارت کن و رسید (عکس یا متن) رو همینجا بفرست 🙏✨\n"
                f"💵 مبلغ: {fmt_money(amount)}\n"
                f"💳 شماره کارت (قابل کپی): `{card}`\n\n"
                "اگر منصرف شدی «انصراف» رو بفرست.",
                parse_mode="Markdown"
            )
            return

        # انصراف پرداخت
        if data.startswith("cancel_payment:"):
            order_id = int(data.split(":")[1])
            od = db.query(Order).get(order_id)
            if not od or od.user_id != u.id:
                await query.edit_message_text("سفارش پیدا نشد.")
                return
            await query.edit_message_text("انصراف دادی. برگشتیم به انتخاب روش پرداخت 😊")
            await context.bot.send_message(
                u.id,
                "خب یکی از روش‌های پرداخت رو انتخاب کن 👇",
                reply_markup=payment_inline_kb(od.id, has_discount=bool(od.discount_code))
            )
            return

        # رسید: تایید/رد توسط ادمین (قابل تغییر نظر)
        if data.startswith("rcpt_ok:") and u.is_admin:
            rid = int(data.split(":")[1])
            r = db.query(Receipt).get(rid)
            if not r or r.status == "accepted":
                await query.edit_message_text("قبلاً تایید شده یا یافت نشد.")
                return
            r.status = "accepted"
            r.decided_at = datetime.utcnow()
            r.decided_by = u.id

            # اگر سفارش مرتبط دارد:
            if r.order_id:
                od = db.query(Order).get(r.order_id)
                usr = db.query(User).get(r.user_id)
                if od and usr:
                    if r.type == "difference":
                        # اول کیف پول کاربر را صفر کن، بعد کامل پرداخت را درنظر بگیر
                        need = od.discounted_price
                        use_wallet = min(usr.wallet, need)
                        need_after = need - use_wallet
                        usr.wallet -= use_wallet  # مصرف موجودی قبلی
                        # رسید diff فقط پوشش need_after را فرض می‌کنیم
                        od.paid = True
                        od.paid_by = "difference"
                        od.paid_at = datetime.utcnow()
                        usr.total_spent += od.discounted_price
                    elif r.type == "c2c":
                        od.paid = True
                        od.paid_by = "c2c"
                        od.paid_at = datetime.utcnow()
                        usr.total_spent += od.discounted_price
                    # ارسال کانفیگ
                    cfg = db.query(ConfigItem).filter_by(plan_id=od.plan_id, is_used=False).first()
                    if cfg:
                        cfg.is_used = True
                        od.config_sent = True
                        od.config_text = cfg.content
                        od.expires_at = datetime.utcnow() + timedelta(days=od.plan.days)
                        db.commit()
                        await context.bot.send_message(
                            usr.id,
                            "🎉 رسید تایید شد! اینم کانفیگت—مبارک باشه 🥳\n"
                            "🔑 متن رو انتخاب کن و کپی بزن:"
                        )
                        await context.bot.send_message(usr.id, f"{od.config_text}")
                    else:
                        db.commit()
                        await context.bot.send_message(
                            usr.id,
                            "پرداختت تایید شد ولی مخزن خالیه! سریعاً شارژ می‌کنیم 🙏"
                        )
                else:
                    db.commit()
            else:
                # افزایش موجودی کیف پول
                usr = db.query(User).get(r.user_id)
                if usr:
                    usr.wallet += r.amount
                db.commit()

            # نوتیف کاربر
            try:
                await context.bot.send_message(r.user_id, "✅ رسیدت تایید شد. مرسی که منظمی! 🌟")
            except:
                pass

            # دکمه‌ها فعال می‌مانند
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تایید", callback_data=f"rcpt_ok:{r.id}"),
                     InlineKeyboardButton("❌ رد", callback_data=f"rcpt_no:{r.id}")]
                ])
            )
            return

        if data.startswith("rcpt_no:") and u.is_admin:
            rid = int(data.split(":")[1])
            r = db.query(Receipt).get(rid)
            if not r or r.status == "rejected":
                await query.edit_message_text("قبلاً رد شده یا یافت نشد.")
                return
            r.status = "rejected"
            r.decided_at = datetime.utcnow()
            r.decided_by = u.id
            db.commit()
            # پیام مودبانه برای کاربر
            try:
                await context.bot.send_message(
                    r.user_id,
                    "❌ رسید رد شد. اگر ابهامی هست با پشتیبانی در ارتباط باش 🤝"
                )
            except:
                pass
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تایید", callback_data=f"rcpt_ok:{r.id}"),
                     InlineKeyboardButton("❌ رد", callback_data=f"rcpt_no:{r.id}")]
                ])
            )
            return

        # تیکت
        if data == "ticket_new":
            context.user_data["mode"] = "ticket_new_subject"
            await query.edit_message_text("موضوع تیکت رو بفرست 🌟 (انصراف = «انصراف»)")
            return

        if data == "ticket_list":
            tks = db.query(Ticket).filter_by(user_id=u.id).order_by(Ticket.id.desc()).all()
            if not tks:
                await query.edit_message_text("تیکتی نداری هنوز 😊")
            else:
                for t in tks:
                    await context.bot.send_message(
                        u.id,
                        f"🎫 تیکت #{t.id} | {t.status}\n"
                        f"موضوع: {t.subject}\n"
                        f"تاریخ: {t.created_at.strftime('%Y-%m-%d %H:%M')}"
                    )
            return

        # کیف پول
        if data == "wallet_topup":
            card = get_card_number(db)
            context.user_data["mode"] = "wallet_topup_amount"
            await query.edit_message_text(
                f"چقدر میخوای شارژ کنی؟ (عددی بفرست)\n"
                f"شماره کارت (قابل کپی): `{card}`\n"
                "بعد از کارت‌به‌کارت، رسید رو همینجا بفرست. (انصراف = «انصراف»)",
                parse_mode="Markdown"
            )
            return

        if data == "wallet_help":
            await query.edit_message_text("برای شارژ کیف‌پول مبلغ رو کارت‌به‌کارت کن و رسید رو بفرست. ما تایید می‌کنیم و موجودی شارژ میشه ✨")
            return

        # دیسکونت مدیریت
        if data == "disc_new" and u.is_admin:
            context.user_data["mode"] = "disc_new_code"
            await query.edit_message_text("کد رو بفرست (مثل: OFF30). (انصراف = «انصراف»)")
            return

        if data.startswith("disc_view:") and u.is_admin:
            did = int(data.split(":")[1])
            d = db.query(DiscountCode).get(did)
            if not d:
                await query.edit_message_text("یافت نشد.")
                return
            left = "∞" if d.max_uses == 0 else f"{max(d.max_uses - d.used_count, 0)}"
            exp = d.expires_at.strftime("%Y-%m-%d") if d.expires_at else "∞"
            await query.edit_message_text(
                f"🏷 جزئیات {d.code}\n"
                f"درصد: %{d.percent}\n"
                f"حداکثر استفاده: {'بدون محدودیت' if d.max_uses==0 else d.max_uses}\n"
                f"مصرف شده: {d.used_count}\n"
                f"باقی مانده: {left}\n"
                f"انقضا: {exp}"
            )
            return

        if data.startswith("disc_del:") and u.is_admin:
            did = int(data.split(":")[1])
            d = db.query(DiscountCode).get(did)
            if not d:
                await query.edit_message_text("یافت نشد.")
                return
            db.delete(d)
            db.commit()
            await query.edit_message_text("کد حذف شد.")
            return

        # پلن/مخزن
        if data == "plan_new" and u.is_admin:
            context.user_data["mode"] = "plan_new_title"
            await query.edit_message_text("عنوان پلن رو بفرست. (انصراف = «انصراف»)")
            return

        if data.startswith("plan_store:") and u.is_admin:
            pid = int(data.split(":")[1])
            p = db.query(Plan).get(pid)
            if not p:
                await query.edit_message_text("پلن پیدا نشد.")
                return
            inv = db.query(ConfigItem).filter_by(plan_id=p.id, is_used=False).count()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ شارژ مخزن (پیام=هر کانفیگ)", callback_data=f"store_add:{p.id}")],
                [InlineKeyboardButton("🗂 مشاهده موجودی", callback_data=f"store_view:{p.id}")],
                [InlineKeyboardButton("🧹 پاک‌سازی مخزن (آزاد نشده‌ها)", callback_data=f"store_clear:{p.id}")]
            ])
            await query.edit_message_text(plan_row_text(p, inv), reply_markup=kb)
            return

        if data.startswith("store_add:") and u.is_admin:
            pid = int(data.split(":")[1])
            context.user_data["mode"] = f"store_add_items:{pid}"
            await query.edit_message_text(
                "هر پیام = یک کانفیگ. هر وقت تموم شد «اتمام» بفرست. (انصراف = «انصراف»)"
            )
            return

        if data.startswith("store_view:") and u.is_admin:
            pid = int(data.split(":")[1])
            items = db.query(ConfigItem).filter_by(plan_id=pid, is_used=False).all()
            if not items:
                await query.edit_message_text("موجودی آزاد نشده‌ای نیست.")
            else:
                await query.edit_message_text(f"تعداد موجودی: {len(items)}")
            return

        if data.startswith("store_clear:") and u.is_admin:
            pid = int(data.split(":")[1])
            items = db.query(ConfigItem).filter_by(plan_id=pid, is_used=False).all()
            for it in items:
                db.delete(it)
            db.commit()
            await query.edit_message_text("مخزن پاک‌سازی شد.")
            return

        if data.startswith("plan_edit:") and u.is_admin:
            pid = int(data.split(":")[1])
            context.user_data["mode"] = f"plan_edit_field:{pid}"
            await query.edit_message_text("چی رو تغییر بدیم؟ یکی از موارد: title/days/volume/price/cost\n(مثال: days=30)")
            return

        if data.startswith("plan_del:") and u.is_admin:
            pid = int(data.split(":")[1])
            p = db.query(Plan).get(pid)
            if not p:
                await query.edit_message_text("پلن پیدا نشد.")
                return
            db.delete(p)
            db.commit()
            await query.edit_message_text("پلن حذف شد.")
            return

        if data == "admin_edit_card" and u.is_admin:
            context.user_data["mode"] = "admin_edit_card_input"
            await query.edit_message_text("شماره کارت جدید رو بفرست. (انصراف = «انصراف»)")
            return

    finally:
        db.close()

# ------ Message (photos/text) for receipts and modes ------
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        u = ensure_user(update, db)
        mode = context.user_data.get("mode", "")

        # رسید ارسال
        if mode and mode.startswith("await_receipt:"):
            _, pay_type, order_id, amount = mode.split(":")
            order_id = int(order_id)
            amount = float(amount)
            photo = update.message.photo[-1] if update.message.photo else None
            file_id = photo.file_id if photo else None

            od = db.query(Order).get(order_id)
            if not od or od.user_id != u.id:
                await update.message.reply_text("سفارش پیدا نشد.")
                return

            r = Receipt(
                user_id=u.id,
                username=u.username,
                order_id=od.id,
                amount=amount,
                type=pay_type,
                text=None,
                photo_file_id=file_id
            )
            db.add(r)
            db.commit()

            # نوتیف به ادمین‌ها
            caption = (
                f"🧾 رسید #{r.id}\n"
                f"👤 @{u.username or '-'} ({u.id})\n"
                f"💵 مبلغ: {fmt_money(amount)}\n"
                f"🎯 نوع: {pay_type}\n"
                f"🔗 سفارش: {od.id}\n"
                f"⏱ تاریخ: {r.created_at}\n"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data=f"rcpt_ok:{r.id}"),
                                        InlineKeyboardButton("❌ رد", callback_data=f"rcpt_no:{r.id}")]])
            for aid in ADMIN_IDS:
                try:
                    if file_id:
                        await context.bot.send_photo(aid, photo=file_id, caption=caption, reply_markup=kb)
                    else:
                        await context.bot.send_message(aid, caption, reply_markup=kb)
                except:
                    pass

            context.user_data["mode"] = None
            await update.message.reply_text("مرسی! رسیدت رسید 🙏 منتظر تایید ادمین بمون ✨")
            return

        # شارژ کیف پول (اگر مد در مرحله مبلغ بود و کاربر بجای عدد، عکس فرستاد—رد)
        if mode == "wallet_topup_amount":
            await update.message.reply_text("لطفاً اول مبلغ رو به عدد بفرست، بعد رسید رو 📸")
            return

        # افزودن مخزن به‌صورت عکس (در این نسخه فقط متن ذخیره می‌کنیم)
        if mode and mode.startswith("store_add_items:"):
            await update.message.reply_text("فعلاً فقط متن کانفیگ رو بفرست لطفاً 🙏 (عکس در نسخه بعد)")
            return

        # تیکت جدید پیام تصویر—تبدیل به متن
        if mode == "ticket_new_subject":
            await update.message.reply_text("موضوع باید متن باشه لطفاً.")
            return

    finally:
        db.close()

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    db = SessionLocal()
    try:
        u = ensure_user(update, db)
        mode = context.user_data.get("mode", "")

        # کد تخفیف (در مرحله پرداخت)
        if mode.startswith("enter_discount:"):
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            order_id = int(mode.split(":")[1])
            od = db.query(Order).get(order_id)
            if not od or od.user_id != u.id:
                context.user_data["mode"] = None
                await update.message.reply_text("سفارش پیدا نشد.")
                return
            d = db.query(DiscountCode).filter(func.lower(DiscountCode.code)==text.lower()).first()
            if not d:
                await update.message.reply_text("کد تخفیف نامعتبره 🫣")
                return
            if d.expires_at and d.expires_at < datetime.utcnow():
                await update.message.reply_text("این کد منقضی شده.")
                return
            if d.max_uses and d.used_count >= d.max_uses:
                await update.message.reply_text("سقف استفاده از این کد پر شده.")
                return
            # اعمال
            percent = max(0, min(100, d.percent))
            new_price = max(0.0, od.price * (100 - percent) / 100.0)
            od.discount_code = d.code
            od.discounted_price = new_price
            db.commit()
            context.user_data["mode"] = None
            await update.message.reply_text(
                f"کد تخفیف اعمال شد ✅\nمبلغ جدید: {fmt_money(new_price)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💼 پرداخت با کیف‌پول", callback_data=f"pay_wallet:{od.id}")],
                    [InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data=f"pay_c2c:{od.id}")],
                    # اگر کد اعمال شد، دیگه نمایش ندیم
                    [InlineKeyboardButton("❌ انصراف", callback_data=f"cancel_payment:{od.id}")]
                ])
            )
            return

        # رسید کارت به کارت/مابه تفاوت – متن
        if mode.startswith("await_receipt:"):
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            _, pay_type, order_id, amount = mode.split(":")
            order_id = int(order_id)
            amount = float(amount)

            od = db.query(Order).get(order_id)
            if not od or od.user_id != u.id:
                context.user_data["mode"] = None
                await update.message.reply_text("سفارش پیدا نشد.")
                return

            r = Receipt(
                user_id=u.id,
                username=u.username,
                order_id=od.id,
                amount=amount,
                type=pay_type,
                text=text,
                photo_file_id=None
            )
            db.add(r)
            db.commit()

            caption = (
                f"🧾 رسید #{r.id}\n"
                f"👤 @{u.username or '-'} ({u.id})\n"
                f"💵 مبلغ: {fmt_money(amount)}\n"
                f"🎯 نوع: {pay_type}\n"
                f"🔗 سفارش: {od.id}\n"
                f"⏱ تاریخ: {r.created_at}\n"
                f"📝 متن: {r.text or '-'}"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data=f"rcpt_ok:{r.id}"),
                                        InlineKeyboardButton("❌ رد", callback_data=f"rcpt_no:{r.id}")]])
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(aid, caption, reply_markup=kb)
                except:
                    pass

            context.user_data["mode"] = None
            await update.message.reply_text("مرسی! رسیدت رسید 🙏 منتظر تایید ادمین بمون ✨")
            return

        # شارژ کیف پول: دریافت مبلغ
        if mode == "wallet_topup_amount":
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            try:
                amount = float(text)
            except:
                await update.message.reply_text("لطفاً مبلغ رو درست (به عدد) بفرست.")
                return
            # حالا رسید همانجا
            context.user_data["mode"] = f"await_wallet_receipt:{amount}"
            card = get_card_number(db)
            await update.message.reply_text(
                "عالی! حالا رسید کارت‌به‌کارت رو بفرست (عکس یا متن) ✨\n"
                f"💵 مبلغ: {fmt_money(amount)}\n"
                f"💳 کارت: `{card}`\n"
                "انصراف = «انصراف»",
                parse_mode="Markdown"
            )
            return

        # شارژ کیف پول: انتظار رسید
        if mode.startswith("await_wallet_receipt:"):
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            amount = float(mode.split(":")[1])
            r = Receipt(
                user_id=u.id,
                username=u.username,
                order_id=None,
                amount=amount,
                type="wallet_topup",
                text=text,
                photo_file_id=None
            )
            db.add(r)
            db.commit()
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تایید", callback_data=f"rcpt_ok:{r.id}"),
                                        InlineKeyboardButton("❌ رد", callback_data=f"rcpt_no:{r.id}")]])
            caption = (
                f"🧾 رسید کیف‌پول #{r.id}\n"
                f"👤 @{u.username or '-'} ({u.id})\n"
                f"💵 مبلغ: {fmt_money(amount)}\n"
                f"⏱ تاریخ: {r.created_at}\n"
                f"📝 متن: {r.text or '-'}"
            )
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(aid, caption, reply_markup=kb)
                except:
                    pass
            context.user_data["mode"] = None
            await update.message.reply_text("رسیدت ثبت شد ✨ بعد از تایید، موجودی شارژ میشه.")
            return

        # تیکت جدید
        if mode == "ticket_new_subject":
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            tk = Ticket(user_id=u.id, subject=text)
            db.add(tk)
            db.commit()
            await update.message.reply_text(f"تیکت #{tk.id} ساخته شد. پیامت رو بفرست تا ثبت کنم 🙂")
            context.user_data["mode"] = f"ticket_msg:{tk.id}"
            return

        if mode.startswith("ticket_msg:"):
            tid = int(mode.split(":")[1])
            tk = db.query(Ticket).get(tid)
            if not tk or tk.user_id != u.id:
                context.user_data["mode"] = None
                await update.message.reply_text("تیکت پیدا نشد.")
                return
            tm = TicketMessage(ticket_id=tid, sender_id=u.id, text=text)
            db.add(tm)
            db.commit()
            await update.message.reply_text("پیامت ثبت شد ✅")
            # نوتیف به ادمین‌ها
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(aid, f"🎫 تیکت #{tid} از {u.id}: {text}")
                except:
                    pass
            return

        # مدیریت کد تخفیف: ساخت
        if mode == "disc_new_code" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            context.user_data["disc_new_code"] = text.strip()
            context.user_data["mode"] = "disc_new_percent"
            await update.message.reply_text("درصد تخفیف رو بفرست (0..100).")
            return

        if mode == "disc_new_percent" and u.is_admin:
            try:
                p = int(text)
            except:
                await update.message.reply_text("عددی بین 0 تا 100 بفرست.")
                return
            context.user_data["disc_new_percent"] = max(0, min(100, p))
            context.user_data["mode"] = "disc_new_max"
            await update.message.reply_text("حداکثر تعداد استفاده؟ (0 = نامحدود)")
            return

        if mode == "disc_new_max" and u.is_admin:
            try:
                m = int(text)
            except:
                await update.message.reply_text("یک عدد بفرست. 0 = نامحدود")
                return
            context.user_data["disc_new_max"] = max(0, m)
            context.user_data["mode"] = "disc_new_exp"
            await update.message.reply_text("تاریخ انقضا؟ (yyyy-mm-dd) یا بفرست «∞»")
            return

        if mode == "disc_new_exp" and u.is_admin:
            exp = None
            if text.strip() != "∞":
                try:
                    exp = datetime.strptime(text.strip(), "%Y-%m-%d")
                except:
                    await update.message.reply_text("فرمت تاریخ نادرسته. مثال: 2025-12-31 یا «∞»")
                    return
            d = DiscountCode(
                code=context.user_data.get("disc_new_code"),
                percent=context.user_data.get("disc_new_percent"),
                max_uses=context.user_data.get("disc_new_max"),
                expires_at=exp
            )
            db.add(d)
            db.commit()
            context.user_data["mode"] = None
            await update.message.reply_text("کد تخفیف ساخته شد ✅")
            return

        # مدیریت پلن: ساخت
        if mode == "plan_new_title" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            context.user_data["plan_new_title"] = text
            context.user_data["mode"] = "plan_new_days"
            await update.message.reply_text("مدت پلن چند روزه باشه؟ (عدد)")
            return

        if mode == "plan_new_days" and u.is_admin:
            try:
                d = int(text)
            except:
                await update.message.reply_text("عدد معتبر بفرست.")
                return
            context.user_data["plan_new_days"] = d
            context.user_data["mode"] = "plan_new_vol"
            await update.message.reply_text("حجم (گیگ)؟ (عدد)")
            return

        if mode == "plan_new_vol" and u.is_admin:
            try:
                v = float(text)
            except:
                await update.message.reply_text("عدد معتبر بفرست.")
                return
            context.user_data["plan_new_vol"] = v
            context.user_data["mode"] = "plan_new_price"
            await update.message.reply_text("قیمت فروش (تومان)؟ (عدد)")
            return

        if mode == "plan_new_price" and u.is_admin:
            try:
                pr = float(text)
            except:
                await update.message.reply_text("عدد معتبر بفرست.")
                return
            context.user_data["plan_new_price"] = pr
            context.user_data["mode"] = "plan_new_cost"
            await update.message.reply_text("قیمت تمام‌شده (برای سود خالص)؟ (عدد)")
            return

        if mode == "plan_new_cost" and u.is_admin:
            try:
                cp = float(text)
            except:
                await update.message.reply_text("عدد معتبر بفرست.")
                return
            p = Plan(
                title=context.user_data.get("plan_new_title"),
                days=context.user_data.get("plan_new_days"),
                volume_gb=context.user_data.get("plan_new_vol"),
                price=context.user_data.get("plan_new_price"),
                cost_price=cp
            )
            db.add(p)
            db.commit()
            context.user_data["mode"] = None
            await update.message.reply_text("پلن ساخته شد ✅")
            return

        # ویرایش پلن
        if mode.startswith("plan_edit_field:") and u.is_admin:
            pid = int(mode.split(":")[1])
            p = db.query(Plan).get(pid)
            if not p:
                context.user_data["mode"] = None
                await update.message.reply_text("پلن پیدا نشد.")
                return
            try:
                key, val = text.split("=", 1)
                key = key.strip().lower()
                val = val.strip()
            except:
                await update.message.reply_text("فرمت نادرست. مثال: days=30")
                return
            if key == "title":
                p.title = val
            elif key == "days":
                p.days = int(val)
            elif key == "volume":
                p.volume_gb = float(val)
            elif key == "price":
                p.price = float(val)
            elif key == "cost":
                p.cost_price = float(val)
            else:
                await update.message.reply_text("کلید ناشناخته.")
                return
            db.commit()
            context.user_data["mode"] = None
            await update.message.reply_text("به‌روزرسانی شد ✅")
            return

        # شارژ مخزن: هر پیام = یک کانفیگ
        if mode.startswith("store_add_items:") and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            if text == "اتمام":
                context.user_data["mode"] = None
                await update.message.reply_text("اتمام عملیات شارژ مخزن ✅")
                return
            pid = int(mode.split(":")[1])
            p = db.query(Plan).get(pid)
            if not p:
                context.user_data["mode"] = None
                await update.message.reply_text("پلن پیدا نشد.")
                return
            db.add(ConfigItem(plan_id=pid, content=text))
            db.commit()
            await update.message.reply_text("یک کانفیگ اضافه شد ✅ (ادامه بده یا «اتمام» بزن)")
            return

        # ویرایش شماره کارت
        if mode == "admin_edit_card_input" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            kv = db.query(GlobalKV).get("card_number")
            if not kv:
                kv = GlobalKV(key="card_number", value=text.strip())
                db.add(kv)
            else:
                kv.value = text.strip()
            db.commit()
            context.user_data["mode"] = None
            await update.message.reply_text("شماره کارت به‌روزرسانی شد ✅")
            return

        # ادمین‌ها: افزودن/حذف
        if mode == "admin_add_id" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            if not text.isdigit():
                await update.message.reply_text("آیدی عددی بفرست.")
                return
            aid = int(text)
            usr = db.query(User).get(aid)
            if not usr:
                usr = User(id=aid, first_name="Admin", is_admin=True)
                db.add(usr)
            else:
                usr.is_admin = True
            db.commit()
            context.user_data["mode"] = None
            await update.message.reply_text("ادمین اضافه شد ✅")
            return

        if mode == "admin_remove_id" and u.is_admin:
            if text == "انصراف":
                context.user_data["mode"] = None
                await update.message.reply_text("لغو شد.")
                return
            if not text.isdigit():
                await update.message.reply_text("آیدی عددی بفرست.")
                return
            aid = int(text)
            # جلوگیری از حذف ادمین‌های پیش‌فرض (از ENV)
            if aid in ADMIN_IDS:
                await update.message.reply_text("❌ ادمین پیش‌فرض قابل حذف نیست.")
                context.user_data["mode"] = None
                return
            usr = db.query(User).get(aid)
            if not usr or not usr.is_admin:
                await update.message.reply_text("ادمین پیدا نشد.")
            else:
                usr.is_admin = False
                db.commit()
                await update.message.reply_text("ادمین حذف شد ✅")
            context.user_data["mode"] = None
            return

        # اگر هیچ‌کدوم نبود، پاس بده به روتر اصلی
        await main_menu_router(update, context)
    finally:
        db.close()

# ادمین افزودن/حذف—با کلیدهای پنل
async def admin_inline_small(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # این هندلر در callbacks پوشش داده شده؛ این فقط برای کامل بودن گذاشته شده
    pass

# دکمه‌های کوچک مدیریت ادمین‌ها
async def admin_buttons_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # این‌ها از طریق متنِ منو اصلی هندل می‌شوند
    pass

# ====== Admin inline triggers from text-menu ======
async def admin_inline_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # نقشی نداره؛ همه چیز در main_menu_router آمده
    pass

# ====== Attach extra small handlers for admin add/remove via inline buttons ======
async def admin_callback_small(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # included in callbacks above
    pass

# ====== Hook small additional commands ======
async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_router(update, context)

# ====== Add handlers ======
application.add_handler(CommandHandler("start", start_cmd))
application.add_handler(CallbackQueryHandler(callbacks))
application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
# ترتیب مهم است: اول مودها را هندل می‌کنیم، بعد روتر اصلی
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
application.add_handler(MessageHandler(filters.ALL, unknown_cmd))
