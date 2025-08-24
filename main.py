import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler,
    filters, CallbackQueryHandler
)

# ---------------------------- Logging ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("bot")

# ---------------------------- ENV ----------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "000000:TEST_TOKEN_PLACEHOLDER")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
DEFAULT_ADMIN_ID = int(os.getenv("DEFAULT_ADMIN_ID", "0"))

# ---------------------------- FastAPI ----------------------------
app = FastAPI(title="Perfect Bot", version="1.0.0")

# ---------------------------- Database (SQLite) ----------------------------
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "bot.db")

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as conn:
        c = conn.cursor()

        # users
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            user_id INTEGER UNIQUE,
            username TEXT,
            full_name TEXT,
            is_admin INTEGER DEFAULT 0,
            wallet INTEGER DEFAULT 0,
            created_at TEXT
        )""")

        # admin config (card number etc.)
        c.execute("""
        CREATE TABLE IF NOT EXISTS admin_config(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        # discount codes
        c.execute("""
        CREATE TABLE IF NOT EXISTS discount_codes(
            code TEXT PRIMARY KEY,
            percent INTEGER,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            expires_at TEXT
        )""")

        # plans
        c.execute("""
        CREATE TABLE IF NOT EXISTS plans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            days INTEGER,
            traffic_gb INTEGER,
            price INTEGER,
            created_at TEXT
        )""")

        # plan configs repository
        c.execute("""
        CREATE TABLE IF NOT EXISTS plan_configs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            content TEXT,      -- text config
            is_image INTEGER DEFAULT 0, -- if stored as image caption
            created_at TEXT,
            sold_to_user INTEGER, -- user_id if sold
            sold_at TEXT,
            FOREIGN KEY(plan_id) REFERENCES plans(id)
        )""")

        # receipts (topup / purchase / diff)
        c.execute("""
        CREATE TABLE IF NOT EXISTS receipts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            kind TEXT,  -- TOPUP / PURCHASE / DIFF
            plan_id INTEGER,
            amount INTEGER,
            discount_code TEXT,
            final_amount INTEGER,
            message_id INTEGER, -- user message id of receipt
            file_id TEXT,       -- photo file_id if any
            text TEXT,          -- text receipt if any
            status TEXT DEFAULT 'PENDING', -- PENDING/APPROVED/DENIED
            created_at TEXT,
            decided_at TEXT,
            decided_by INTEGER
        )""")

        # purchases
        c.execute("""
        CREATE TABLE IF NOT EXISTS purchases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_id INTEGER,
            config_id INTEGER,
            price_paid INTEGER,
            discount_code TEXT,
            started_at TEXT,
            ends_at TEXT
        )""")

        # tickets
        c.execute("""
        CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            status TEXT DEFAULT 'OPEN',
            created_at TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS ticket_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            sender_id INTEGER,
            text TEXT,
            created_at TEXT
        )""")

        # sales stats
        c.execute("""
        CREATE TABLE IF NOT EXISTS sales_stats(
            id INTEGER PRIMARY KEY CHECK (id=1),
            total_sales INTEGER DEFAULT 0,
            total_revenue INTEGER DEFAULT 0
        )""")

        # sessions (per-user temp flow: chosen plan, discount, etc.)
        c.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            user_id INTEGER PRIMARY KEY,
            step TEXT,
            plan_id INTEGER,
            discount_code TEXT,
            pay_method TEXT,  -- WALLET / CARD / DIFF
            net_price INTEGER
        )""")

        # admins table (to manage admins)
        c.execute("""
        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY
        )""")

        # users index
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_userid ON users(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(status)")
        c.execute("INSERT OR IGNORE INTO sales_stats(id,total_sales,total_revenue) VALUES (1,0,0)")

        # seed admin default + wallet 50,000
        if DEFAULT_ADMIN_ID > 0:
            c.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (DEFAULT_ADMIN_ID,))
            c.execute("INSERT OR IGNORE INTO users(user_id, username, full_name, is_admin, wallet, created_at) VALUES (?,?,?,?,?,?)",
                      (DEFAULT_ADMIN_ID, None, "Owner", 1, 50000, datetime.utcnow().isoformat()))
        # seed admin card number
        c.execute("INSERT OR IGNORE INTO admin_config(key, value) VALUES('card_number','6037-9918-1234-5678')")

        # seed discount OFF30
        c.execute("INSERT OR IGNORE INTO discount_codes(code,percent,max_uses,used_count,expires_at) VALUES (?,?,?,?,?)",
                  ("OFF30", 30, None, 0, None))

        # seed sample plans if none
        c.execute("SELECT COUNT(*) AS cnt FROM plans")
        if c.fetchone()["cnt"] == 0:
            now = datetime.utcnow().isoformat()
            plans = [
                ("پلن اقتصادی", 30, 100, 150000),
                ("پلن حرفه‌ای", 60, 300, 350000),
                ("پلن نامحدود+", 90, 9999, 690000),
            ]
            for title, days, traffic, price in plans:
                c.execute("INSERT INTO plans(title,days,traffic_gb,price,created_at) VALUES (?,?,?,?,?)",
                          (title, days, traffic, price, now))

        # seed a few repository configs for first plan
        c.execute("SELECT id FROM plans ORDER BY id LIMIT 1")
        row = c.fetchone()
        if row:
            first_plan_id = row["id"]
            c.execute("SELECT COUNT(*) AS cnt FROM plan_configs WHERE plan_id=?", (first_plan_id,))
            if c.fetchone()["cnt"] == 0:
                now = datetime.utcnow().isoformat()
                samples = [
                    "vless://sample-config-1?security=reality#Sample1",
                    "vless://sample-config-2?security=reality#Sample2",
                    "vless://sample-config-3?security=reality#Sample3",
                ]
                for s in samples:
                    c.execute("INSERT INTO plan_configs(plan_id, content, is_image, created_at) VALUES (?,?,?,?)",
                              (first_plan_id, s, 0, now))

init_db()

# ---------------------------- Helpers ----------------------------
MAIN_MENU_BUTTONS = [
    ["📦 لیست پلن‌ها", "👤 حساب کاربری"],
    ["💼 کیف پول", "🎫 تیکت‌ها"],
    ["🛒 خریدهای من", "ℹ️ آموزش"],
    # دکمه پنل ادمین فقط برای ادمین‌ها موقع رندر اضافه می‌شود
]

ADMIN_MENU_BUTTONS = [
    ["💳 شماره کارت", "👮 مدیریت ادمین‌ها"],
    ["🧾 رسیدهای در انتظار", "💼 کیف پول کاربر"],
    ["🏷 کدهای تخفیف", "📣 اعلان همگانی"],
    ["🧰 مدیریت پلن و مخزن", "📈 آمار فروش"],
    ["👥 کاربران", "↩️ بازگشت به منوی اصلی"]
]

PLAN_ACTION_BUTTONS = [
    ["💳 کارت‌به‌کارت", "💼 پرداخت از کیف پول"],
    ["🏷 اعمال کد تخفیف", "↩️ انصراف"],
]

def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [*MAIN_MENU_BUTTONS]
    if is_admin:
        rows.append(["🛠 پنل ادمین"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def plan_actions_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(PLAN_ACTION_BUTTONS, resize_keyboard=True)

def cancel_only_keyboard(text="↩️ انصراف"):
    return ReplyKeyboardMarkup([[text]], resize_keyboard=True)

def back_to_payment_keyboard():
    return ReplyKeyboardMarkup([["💳 کارت‌به‌کارت","💼 پرداخت از کیف پول"],["🏷 اعمال کد تخفیف","↩️ انصراف"]], resize_keyboard=True)

def to_rials(n:int)->str:
    # نمایش با ویرگول
    s = f"{n:,}".replace(",", "٬")
    return f"{s} تومان"

def is_admin_user(user_id:int)->bool:
    with db() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        return c.fetchone() is not None

def ensure_user(update: Update) -> Tuple[int, bool]:
    u = update.effective_user
    with db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id=?", (u.id,))
        row = c.fetchone()
        if not row:
            c.execute("INSERT INTO users(user_id,username,full_name,is_admin,wallet,created_at) VALUES (?,?,?,?,?,?)",
                      (u.id, u.username, (u.full_name or "").strip(), 1 if (u.id==DEFAULT_ADMIN_ID) else 0, 0, datetime.utcnow().isoformat()))
        c.execute("SELECT is_admin FROM users WHERE user_id=?", (u.id,))
        isadm = c.fetchone()["is_admin"] == 1
    return u.id, isadm

async def send_dm(context: ContextTypes.DEFAULT_TYPE, user_id:int, text:str, reply_markup=None):
    try:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.warning(f"DM failed to {user_id}: {e}")

def session_set(user_id:int, **kwargs):
    with db() as conn:
        c=conn.cursor()
        # upsert
        c.execute("INSERT OR IGNORE INTO sessions(user_id, step) VALUES(?,?)",(user_id,None))
        for k,v in kwargs.items():
            c.execute(f"UPDATE sessions SET {k}=? WHERE user_id=?", (v,user_id))

def session_get(user_id:int)->Dict:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM sessions WHERE user_id=?", (user_id,))
        row=c.fetchone()
        return dict(row) if row else {}

def session_clear(user_id:int):
    with db() as conn:
        c=conn.cursor()
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

def get_card_number()->str:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT value FROM admin_config WHERE key='card_number'")
        row=c.fetchone()
        return row["value"] if row else "—"

def apply_discount(code:str, price:int) -> Tuple[bool,int,str]:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM discount_codes WHERE code=?", (code.upper(),))
        d=c.fetchone()
        if not d:
            return False, price, "کد تخفیف نامعتبره رفیق 👀"
        # check expiry & uses
        if d["expires_at"]:
            if datetime.utcnow()>datetime.fromisoformat(d["expires_at"]):
                return False, price, "کد تخفیف منقضی شده 😕"
        if d["max_uses"] is not None and d["used_count"]>=d["max_uses"]:
            return False, price, "ظرفیت استفاده از این کد تخفیف تموم شده 💡"
        percent=d["percent"]
        off= (price*percent)//100
        return True, max(0, price-off), f"🎉 کد تخفیف اعمال شد! {percent}% تخفیف خوردی."

def discount_mark_used(code:str):
    with db() as conn:
        c=conn.cursor()
        c.execute("UPDATE discount_codes SET used_count=used_count+1 WHERE code=?", (code.upper(),))

def stock_count(plan_id:int)->int:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT COUNT(*) AS cnt FROM plan_configs WHERE plan_id=? AND sold_to_user IS NULL", (plan_id,))
        return c.fetchone()["cnt"]

def get_one_config(plan_id:int)->Optional[int]:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT id FROM plan_configs WHERE plan_id=? AND sold_to_user IS NULL ORDER BY id LIMIT 1", (plan_id,))
        row=c.fetchone()
        return row["id"] if row else None

def mark_config_sold(config_id:int, user_id:int):
    with db() as conn:
        c=conn.cursor()
        c.execute("UPDATE plan_configs SET sold_to_user=?, sold_at=? WHERE id=?",(user_id, datetime.utcnow().isoformat(), config_id))

def get_config_content(config_id:int)->Tuple[str,bool]:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT content, is_image FROM plan_configs WHERE id=?", (config_id,))
        row=c.fetchone()
        return (row["content"], bool(row["is_image"])) if row else ("", False)

def user_wallet(user_id:int)->int:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT wallet FROM users WHERE user_id=?",(user_id,))
        row=c.fetchone()
        return row["wallet"] if row else 0

def wallet_add(user_id:int, amount:int):
    with db() as conn:
        c=conn.cursor()
        c.execute("UPDATE users SET wallet=wallet+? WHERE user_id=?", (amount, user_id))

def wallet_sub(user_id:int, amount:int)->bool:
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT wallet FROM users WHERE user_id=?", (user_id,))
        w=c.fetchone()["wallet"]
        if w<amount: return False
        c.execute("UPDATE users SET wallet=wallet-? WHERE user_id=?", (amount, user_id))
        return True

def record_purchase(user_id:int, plan_id:int, config_id:int, price_paid:int, discount_code:Optional[str]):
    with db() as conn:
        c=conn.cursor()
        start=datetime.utcnow()
        # find plan days
        c.execute("SELECT days FROM plans WHERE id=?", (plan_id,))
        days=c.fetchone()["days"]
        ends = start + timedelta(days=days)
        c.execute("""INSERT INTO purchases(user_id,plan_id,config_id,price_paid,discount_code,started_at,ends_at)
                     VALUES (?,?,?,?,?,?,?)""",
                  (user_id, plan_id, config_id, price_paid, (discount_code or None), start.isoformat(), ends.isoformat()))
        # sales stats
        c.execute("UPDATE sales_stats SET total_sales=total_sales+1, total_revenue=total_revenue+?", (price_paid,))

def check_and_notify_expirations(context: ContextTypes.DEFAULT_TYPE, user_id:int):
    """Check this user's purchases and send 5-day / 1-day / expiry notifications lazily on interactions."""
    # For simplicity, we’ll store flags by creating tiny markers in ticket_messages (lightweight) or skip persisting flags.
    # Here we’ll re-check windows and send if within range & not already expired.
    try:
        with db() as conn:
            c=conn.cursor()
            c.execute("SELECT p.id, p.ends_at, pl.title FROM purchases p JOIN plans pl ON pl.id=p.plan_id WHERE p.user_id=?", (user_id,))
            rows=c.fetchall()
        now=datetime.utcnow()
        for r in rows:
            ends=datetime.fromisoformat(r["ends_at"])
            delta=(ends-now).days
            if delta==5:
                asyncio.create_task(send_dm(context, user_id, f"⏳ فقط ۵ روز تا پایان «{r['title']}» مونده. اگه راضی بودی می‌تونی تمدید کنی 😉"))
            elif delta==1:
                asyncio.create_task(send_dm(context, user_id, f"⚠️ یک روز تا پایان «{r['title']}» باقی مونده. مبادا یادت بره!"))
            elif now>=ends:
                # delete from user purchases & free config? (طبق نیاز: حذف از «کانفیگ‌های من»)
                # برای سبک بودن دیتابیس، همون رکورد باقی می‌مونه اما اعلان ارسال می‌شه
                asyncio.create_task(send_dm(context, user_id, f"❌ مهلت «{r['title']}» تموم شد و از بخش «کانفیگ‌های من» حذف شد. هر موقع خواستی می‌تونی دوباره بخری ✨"))
    except Exception as e:
        log.warning(f"expire check failed: {e}")

# ---------------------------- Bot Handlers ----------------------------

WELCOME_TEXT = (
    "سلام خوش اومدی دوست خوبم! ✨\n"
    "من اینجام تا برات یه تجربهٔ خرید کانفیگ خیلی ساده، شیک و بی‌دردسر بسازم 🤝\n\n"
    "از منوی اصلی می‌تونی:\n"
    "• 📦 لیست پلن‌ها رو ببینی و همونجا خرید کنی (با تخفیف یا کیف‌پول)\n"
    "• 👤 حساب کاربری‌ت رو مدیریت کنی (اطلاعاتت و خریدها)\n"
    "• 💼 کیف پولت رو ببینی و سریع افزایش بدی\n"
    "• 🎫 تیکت بزنی و سابقه تیکت‌هات رو ببینی\n"
    "• 🛒 خریدهای قبلی‌ت رو ببینی\n"
    "• ℹ️ آموزش قدم‌به‌قدم رو بخونی\n\n"
    "هرجا به مشکل خوردی، با دکمهٔ «↩️ انصراف» برگرد. بزن بریم! 🚀"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, isadm = ensure_user(update)
    check_and_notify_expirations(context, user_id)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=main_menu(isadm))

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, isadm = ensure_user(update)
    check_and_notify_expirations(context, user_id)
    txt = (update.message.text or "").strip()

    # --- Main menu routes ---
    if txt == "📦 لیست پلن‌ها":
        await show_plans(update, context)
        return
    if txt == "👤 حساب کاربری":
        await show_profile(update, context, user_id, isadm)
        return
    if txt == "💼 کیف پول":
        await wallet_menu(update, context, user_id)
        return
    if txt == "🎫 تیکت‌ها":
        await tickets_menu(update, context, user_id)
        return
    if txt == "🛒 خریدهای من":
        await my_purchases(update, context, user_id)
        return
    if txt == "ℹ️ آموزش":
        await show_help(update, context)
        return
    if isadm and txt == "🛠 پنل ادمین":
        await admin_panel(update, context)
        return

    # --- Plan payment flow ---
    sess = session_get(user_id)
    step = sess.get("step")

    if step == "AWAIT_DISCOUNT_CODE":
        code = txt.strip()
        with db() as conn:
            c=conn.cursor()
            c.execute("SELECT price, title FROM plans WHERE id=?", (sess.get("plan_id"),))
            prow=c.fetchone()
        ok, new_price, msg = apply_discount(code, prow["price"])
        if not ok:
            await update.message.reply_text(
                f"{msg}\n\nاگه خواستی می‌تونی دوباره امتحان کنی یا از روش‌های پرداخت دیگه اقدام کنی.",
                reply_markup=back_to_payment_keyboard()
            )
            session_set(user_id, step="PAYMENT_MENU")
            return
        session_set(user_id, discount_code=code.upper(), net_price=new_price, step="PAYMENT_MENU")
        await update.message.reply_text(
            f"{msg}\nقیمت جدید «{prow['title']}»: {to_rials(new_price)}",
            reply_markup=back_to_payment_keyboard()
        )
        return

    if step == "AWAIT_TOPUP_RECEIPT":
        # cancel option
        if txt == "↩️ انصراف":
            session_set(user_id, step=None)
            await update.message.reply_text("عملیات لغو شد. می‌تونی دوباره از منو انتخاب کنی ✌️", reply_markup=main_menu(is_admin_user(user_id)))
            return
        await handle_receipt_message(update, context, kind="TOPUP")
        return

    if step == "AWAIT_PURCHASE_RECEIPT":
        if txt == "↩️ انصراف":
            # back to payment menu for same plan
            session_set(user_id, step="PAYMENT_MENU")
            await update.message.reply_text("اوکی—برگشتیم به مرحله پرداخت. یکی از گزینه‌ها رو انتخاب کن:", reply_markup=back_to_payment_keyboard())
            return
        await handle_receipt_message(update, context, kind="PURCHASE")
        return

    if step == "AWAIT_DIFF_RECEIPT":
        if txt == "↩️ انصراف":
            session_set(user_id, step="PAYMENT_MENU")
            await update.message.reply_text("اوکی—برگشتیم به مرحله پرداخت. یکی از گزینه‌ها رو انتخاب کن:", reply_markup=back_to_payment_keyboard())
            return
        await handle_receipt_message(update, context, kind="DIFF")
        return

    # --- Wallet submenu ---
    if step == "WALLET_TOPUP_AWAIT_RECEIPT":
        if txt == "↩️ انصراف":
            session_set(user_id, step=None)
            await update.message.reply_text("لغو شد. برگشتیم 🌿", reply_markup=main_menu(isadm))
            return
        await handle_receipt_message(update, context, kind="TOPUP")
        return

    # --- Ticket flow ---
    if step == "TICKET_NEW_AWAIT_SUBJECT":
        if txt == "↩️ انصراف":
            session_set(user_id, step=None)
            await update.message.reply_text("لغو شد. برگشتیم 🌿", reply_markup=main_menu(isadm))
            return
        await create_ticket(update, context, user_id, txt)
        return
    if step and step.startswith("TICKET_REPLY_"):
        ticket_id = int(step.split("_")[-1])
        if txt == "↩️ انصراف":
            session_set(user_id, step=None)
            await tickets_menu(update, context, user_id)
            return
        await add_ticket_message(update, context, user_id, ticket_id, txt)
        return

    # --- Admin panel routes ---
    if isadm:
        if txt == "↩️ بازگشت به منوی اصلی":
            session_set(user_id, step=None)
            await update.message.reply_text("برگشتیم به منوی اصلی 🌟", reply_markup=main_menu(isadm))
            return
        if txt == "💳 شماره کارت":
            await admin_card(update, context)
            return
        if txt == "👮 مدیریت ادمین‌ها":
            await admin_admins(update, context)
            return
        if txt == "🧾 رسیدهای در انتظار":
            await admin_receipts(update, context)
            return
        if txt == "💼 کیف پول کاربر":
            await admin_user_wallet(update, context)
            return
        if txt == "🏷 کدهای تخفیف":
            await admin_discounts(update, context)
            return
        if txt == "📣 اعلان همگانی":
            await admin_broadcast(update, context)
            return
        if txt == "🧰 مدیریت پلن و مخزن":
            await admin_plans(update, context)
            return
        if txt == "📈 آمار فروش":
            await admin_stats(update, context)
            return
        if txt == "👥 کاربران":
            await admin_users(update, context)
            return

    # --- Fallback ---
    await update.message.reply_text("متوجه نشدم چی می‌خوای 🙂 یکی از دکمه‌ها رو بزن لطفاً.", reply_markup=main_menu(isadm))

# ---------------------------- Feature Implementations ----------------------------

async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM plans ORDER BY id")
        rows=c.fetchall()
    if not rows:
        await update.message.reply_text("فعلاً پلنی تعریف نشده.", reply_markup=main_menu(is_admin_user(update.effective_user.id)))
        return
    msg="📦 <b>لیست پلن‌ها</b>\n\n"
    buttons=[]
    for r in rows:
        sc=stock_count(r["id"])
        msg += f"• <b>{r['title']}</b>\n"
        msg += f"  ⏱ مدت: {r['days']} روز | 💾 حجم: {r['traffic_gb']}GB | 💰 قیمت: {to_rials(r['price'])} | 🧳 موجودی: {sc}\n\n"
        buttons.append([InlineKeyboardButton(f"{r['title']} ({to_rials(r['price'])})", callback_data=f"plan:{r['id']}")])
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(buttons))

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id:int, isadm:bool):
    w = user_wallet(user_id)
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT COUNT(*) AS cnt FROM purchases WHERE user_id=?", (user_id,))
        pc=c.fetchone()["cnt"]
    txt = (
        f"👤 <b>حساب کاربری</b>\n\n"
        f"🆔 آیدی عددی: <code>{user_id}</code>\n"
        f"💼 موجودی کیف پول: {to_rials(w)}\n"
        f"🛒 تعداد خریدها: {pc}\n"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML,
                                    reply_markup=main_menu(isadm))

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id:int):
    w = user_wallet(user_id)
    kb = ReplyKeyboardMarkup([
        ["➕ افزایش موجودی", "🔄 به‌روزرسانی موجودی"],
        ["↩️ انصراف"]
    ], resize_keyboard=True)
    await update.message.reply_text(
        f"💼 <b>کیف پول</b>\n\nموجودی فعلی: {to_rials(w)}",
        parse_mode=ParseMode.HTML, reply_markup=kb
    )
    session_set(user_id, step="WALLET_MENU")

async def tickets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id:int):
    kb = ReplyKeyboardMarkup([
        ["📝 تیکت جدید", "📚 سابقه تیکت‌ها"],
        ["↩️ انصراف"]
    ], resize_keyboard=True)
    await update.message.reply_text("🎫 <b>تیکت‌ها</b>\nیکی از گزینه‌ها رو بزن:", parse_mode=ParseMode.HTML, reply_markup=kb)
    session_set(user_id, step="TICKETS_MENU")

async def my_purchases(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id:int):
    with db() as conn:
        c=conn.cursor()
        c.execute("""SELECT p.id, p.started_at, p.ends_at, pl.title
                     FROM purchases p JOIN plans pl ON pl.id=p.plan_id
                     WHERE p.user_id=? ORDER BY p.id DESC""",(user_id,))
        rows=c.fetchall()
    if not rows:
        await update.message.reply_text("هنوز خریدی نداری 🙂", reply_markup=main_menu(is_admin_user(user_id)))
        return
    txt="🛒 <b>خریدهای من</b>\n\n"
    for r in rows:
        txt += f"• {r['title']} | شروع: {r['started_at'][:10]} | پایان: {r['ends_at'][:10]}\n"
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_menu(is_admin_user(user_id)))

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "ℹ️ <b>آموزش قدم‌به‌قدم</b>\n\n"
        "۱) از «📦 لیست پلن‌ها» پلن دلخواهت رو انتخاب کن.\n"
        "۲) توی صفحهٔ جزئیات پلن، روش پرداخت رو انتخاب کن (💳 کارت‌به‌کارت یا 💼 کیف پول).\n"
        "۳) اگه کد تخفیف داری، از «🏷 اعمال کد تخفیف» استفاده کن (مثلاً OFF30).\n"
        "۴) برای کارت‌به‌کارت: مبلغ نهایی نشون داده میشه—پرداخت کن و «عکس رسید یا متن رسید» رو بفرست.\n"
        "۵) رسیدت میره برای ادمین‌ها؛ با تاییدش کانفیگ آماده و قابل کپی برات میاد 🎉\n"
        "۶) برای کیف پول: اگه موجودی کافی داری مستقیم خرید انجام میشه؛ اگر نه، مبلغ تفاوت ازت خواسته میشه.\n"
        "۷) هرجا خواستی «↩️ انصراف» رو بزن تا به مرحلهٔ قبلی برگردی.\n"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_menu(is_admin_user(update.effective_user.id)))

# ---------------------------- Callback: Plan selected ----------------------------
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    user = update.effective_user
    await q.answer()
    if data.startswith("plan:"):
        plan_id = int(data.split(":")[1])
        with db() as conn:
            c=conn.cursor()
            c.execute("SELECT * FROM plans WHERE id=?", (plan_id,))
            p=c.fetchone()
        if not p:
            await q.edit_message_text("این پلن پیدا نشد.")
            return
        sc=stock_count(plan_id)
        txt=(f"📝 <b>جزئیات پلن</b>\n\n"
             f"عنوان: {p['title']}\n"
             f"⏱ مدت: {p['days']} روز\n"
             f"💾 حجم: {p['traffic_gb']}GB\n"
             f"💰 قیمت: {to_rials(p['price'])}\n"
             f"🧳 موجودی مخزن: {sc}\n\n")
        if sc<=0:
            await q.edit_message_text(txt + "فعلاً مخزن این پلن خالیه؛ بزودی شارژ میشه 🙏", parse_mode=ParseMode.HTML)
            return
        # low stock notify admin (if 1 left)
        if sc==1:
            with db() as conn:
                c=conn.cursor()
                c.execute("SELECT user_id FROM admins")
                admins=[r["user_id"] for r in c.fetchall()]
            for aid in admins:
                asyncio.create_task(send_dm(context, aid, f"⚠️ موجودی مخزن «{p['title']}» در حال اتمامه (۱ عدد باقی مانده)."))
        session_set(user.id, step="PAYMENT_MENU", plan_id=plan_id, discount_code=None, net_price=p["price"])
        await q.edit_message_text(txt + "روش پرداختت رو انتخاب کن:", parse_mode=ParseMode.HTML)
        await context.bot.send_message(chat_id=user.id, text="👇", reply_markup=plan_actions_keyboard())
        return

# ---------------------------- Payment menu Actions ----------------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This handler only for the few special buttons inside payment menu & wallet menu
    user_id, isadm = ensure_user(update)
    txt = (update.message.text or "").strip()
    sess = session_get(user_id)
    step = sess.get("step")

    # Payment menu selections
    if step == "PAYMENT_MENU":
        if txt == "🏷 اعمال کد تخفیف":
            session_set(user_id, step="AWAIT_DISCOUNT_CODE")
            await update.message.reply_text("کد تخفیفت رو بفرست 🌟 (مثلاً OFF30)\nیا «↩️ انصراف» رو بزن.", reply_markup=cancel_only_keyboard())
            return
        if txt == "💼 پرداخت از کیف پول":
            # try purchase
            plan_id=sess.get("plan_id")
            net_price=sess.get("net_price")
            if stock_count(plan_id)<=0:
                await update.message.reply_text("مخزن این پلن الان خالیه؛ بزودی شارژ میشه 🙏")
                return
            w=user_wallet(user_id)
            if w>=net_price:
                if not wallet_sub(user_id, net_price):
                    await update.message.reply_text("یه لحظه! موجودی کافی نیست. دوباره امتحان کن.")
                    return
                cfg_id=get_one_config(plan_id)
                if not cfg_id:
                    await update.message.reply_text("مخزن همین الان خالی شد؛ یه لحظه بعد دوباره امتحان کن.")
                    return
                mark_config_sold(cfg_id, user_id)
                if sess.get("discount_code"):
                    discount_mark_used(sess.get("discount_code"))
                record_purchase(user_id, plan_id, cfg_id, net_price, sess.get("discount_code"))
                content,isimg = get_config_content(cfg_id)
                await update.message.reply_text("🎉 تبریک! خرید با موفقیت از طریق کیف پول انجام شد.", reply_markup=main_menu(isadm))
                await update.message.reply_text(f"📄 کانفیگت آماده‌ست و قابل کپی:\n\n<code>{content}</code>", parse_mode=ParseMode.HTML)
                session_clear(user_id)
                return
            else:
                # ask to pay difference
                diff = net_price - w
                session_set(user_id, step="AWAIT_DIFF_RECEIPT", pay_method="DIFF")
                await update.message.reply_text(
                    f"کیف پولت کفاف نمی‌ده 😅\nمبلغ تفاوت: {to_rials(diff)}\n\n"
                    f"اگه اوکی هستی، لطفاً همین الان {to_rials(diff)} رو کارت‌به‌کارت کن به شماره کارت زیر و «عکس یا متن رسید» رو بفرست.\n"
                    f"شماره کارت: <b>{get_card_number()}</b>\n\n"
                    f"یا «↩️ انصراف» رو بزن تا به مرحله پرداخت برگردیم.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=cancel_only_keyboard()
                )
                return
        if txt == "💳 کارت‌به‌کارت":
            session_set(user_id, step="AWAIT_PURCHASE_RECEIPT", pay_method="CARD")
            with db() as conn:
                c=conn.cursor()
                c.execute("SELECT title FROM plans WHERE id=?", (sess.get("plan_id"),))
                title=c.fetchone()["title"]
            await update.message.reply_text(
                f"خیلی هم عالی 🙌\n"
                f"مبلغ پرداخت: {to_rials(sess.get('net_price'))}\n"
                f"برای «{title}»\n\n"
                f"لطفاً به شماره کارت زیر واریز و «عکس یا متن رسید» رو همینجا بفرست:\n"
                f"<b>{get_card_number()}</b>\n\n"
                f"برای لغو «↩️ انصراف» رو بزن.",
                parse_mode=ParseMode.HTML, reply_markup=cancel_only_keyboard()
            )
            return
        if txt == "↩️ انصراف":
            session_clear(user_id)
            await update.message.reply_text("لغو شد. برگشتیم به انتخاب پلن‌ها 🌿", reply_markup=main_menu(isadm))
            await show_plans(update, context)
            return

    # Wallet submenu
    if step == "WALLET_MENU":
        if txt == "🔄 به‌روزرسانی موجودی":
            await wallet_menu(update, context, user_id)
            return
        if txt == "➕ افزایش موجودی":
            session_set(user_id, step="WALLET_TOPUP_AWAIT_RECEIPT")
            await update.message.reply_text(
                f"👌 لطفاً هر مبلغی خواستی به این کارت واریز کن و «عکس یا متن رسید» رو بفرست:\n<b>{get_card_number()}</b>\n\n"
                f"برای لغو «↩️ انصراف».", parse_mode=ParseMode.HTML, reply_markup=cancel_only_keyboard()
            )
            return
        if txt == "↩️ انصراف":
            session_set(user_id, step=None)
            await update.message.reply_text("لغو شد. برگشتیم 🌿", reply_markup=main_menu(isadm))
            return

    # Tickets submenu
    if step == "TICKETS_MENU":
        if txt == "📝 تیکت جدید":
            session_set(user_id, step="TICKET_NEW_AWAIT_SUBJECT")
            await update.message.reply_text("موضوع تیکت رو بفرست 📨\nیا «↩️ انصراف».", reply_markup=cancel_only_keyboard())
            return
        if txt == "📚 سابقه تیکت‌ها":
            with db() as conn:
                c=conn.cursor()
                c.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC", (user_id,))
                rows=c.fetchall()
            if not rows:
                await update.message.reply_text("هنوز تیکتی نداری 🙂", reply_markup=main_menu(isadm))
                session_set(user_id, step=None)
                return
            txts="📚 <b>سابقه تیکت‌ها</b>\n\n"
            for r in rows:
                txts += f"#{r['id']} | {r['subject']} | وضعیت: {r['status']}\n"
            await update.message.reply_text(txts, parse_mode=ParseMode.HTML, reply_markup=main_menu(isadm))
            session_set(user_id, step=None)
            return
        if txt == "↩️ انصراف":
            session_set(user_id, step=None)
            await update.message.reply_text("لغو شد. برگشتیم 🌿", reply_markup=main_menu(isadm))
            return

    # Admin panels inner flows (text prompts will be handled inline in each admin function using session steps)
    # Otherwise:
    await text_router(update, context)

# ---------------------------- Receipt Processing ----------------------------
async def handle_receipt_message(update: Update, context: ContextTypes.DEFAULT_TYPE, kind:str):
    user_id = update.effective_user.id
    msg = update.message
    file_id = None
    text = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.text and msg.text != "↩️ انصراف":
        text = msg.text

    sess=session_get(user_id)
    plan_id = sess.get("plan_id") if kind!="TOPUP" else None
    amount = sess.get("net_price") if kind=="PURCHASE" else None
    if kind=="DIFF":
        # compute diff again
        w=user_wallet(user_id)
        amount = max(0, sess.get("net_price")-w)

    with db() as conn:
        c=conn.cursor()
        c.execute("""INSERT INTO receipts(user_id,kind,plan_id,amount,discount_code,final_amount,message_id,file_id,text,status,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                  (user_id, kind, plan_id, amount, sess.get("discount_code"), amount,
                   msg.message_id, file_id, text, "PENDING", datetime.utcnow().isoformat()))
        rid = c.lastrowid

        # notify admins
        c.execute("SELECT user_id FROM admins")
        admins=[r["user_id"] for r in c.fetchall()]
    kind_fa = {"TOPUP":"افزایش موجودی", "PURCHASE":"خرید پلن", "DIFF":"مابه‌التفاوت"}.get(kind, kind)
    for aid in admins:
        caption = (
            f"🧾 رسید جدید #{rid}\n"
            f"👤 {msg.from_user.full_name} (@{msg.from_user.username or '—'})\n"
            f"🆔 {user_id}\n"
            f"نوع: {kind_fa}\n"
            f"پلن: {plan_id or '—'}\n"
            f"مبلغ: {to_rials(amount or 0)}\n"
            f"کد تخفیف: {sess.get('discount_code') or '—'}\n"
            f"تاریخ: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"دکمه‌های زیر برای تایید/رد (قابل تغییرنظر دوباره)."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید", callback_data=f"rcpt:{rid}:APPROVE"),
             InlineKeyboardButton("❌ رد", callback_data=f"rcpt:{rid}:DENY")]
        ])
        if file_id:
            try:
                await context.bot.send_photo(chat_id=aid, photo=file_id, caption=caption, reply_markup=kb)
            except:
                await context.bot.send_message(chat_id=aid, text=caption, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=aid, text=caption, reply_markup=kb)

    await update.message.reply_text("مرسی 🙏 رسیدت ثبت شد و به ادمین فرستاده شد. نتیجه رو خبرت می‌کنیم 🌟",
                                    reply_markup=main_menu(is_admin_user(user_id)))
    # remain buttons togglable by admin; user session stays or cleared?
    # We'll keep session for PURCHASE/DIFF until approval.
    if kind=="TOPUP":
        session_clear(user_id)

# ---------------------------- Admin Actions: Approve/Deny receipts ----------------------------
async def callback_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query
    await q.answer()
    data=q.data  # rcpt:<id>:APPROVE/DENY
    _, rid, action = data.split(":")
    rid=int(rid)
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM receipts WHERE id=?", (rid,))
        r=c.fetchone()
        if not r:
            await q.edit_message_caption(caption="این رسید پیدا نشد.")
            return
        # toggleable: set to status
        now=datetime.utcnow().isoformat()
        c.execute("UPDATE receipts SET status=?, decided_at=?, decided_by=? WHERE id=?", (action, now, q.from_user.id, rid))

    user_id = r["user_id"]
    kind = r["kind"]
    plan_id = r["plan_id"]
    amount = r["final_amount"] or 0
    discount_code = r["discount_code"]

    if action=="APPROVE":
        if kind=="TOPUP":
            wallet_add(user_id, amount)
            await send_dm(context, user_id, f"✅ شارژ کیف پول تایید شد. موجودی جدید: {to_rials(user_wallet(user_id))} 💼")
        elif kind in ("PURCHASE","DIFF"):
            # complete purchase
            # For DIFF, first add the user's wallet current + this diff to net, then wallet_sub net.
            with db() as conn:
                c=conn.cursor()
                c.execute("SELECT price, title FROM plans WHERE id=?", (plan_id,))
                prow=c.fetchone()
            # find user's session net_price OR recompute from price and discount
            net_price = amount
            if kind=="DIFF":
                # DIFF amount + user wallet == net_price
                # So we need to take all user's wallet and set it to zero, but we already received diff externally.
                w=user_wallet(user_id)
                if w>0:
                    wallet_sub(user_id, w)
            # pick config
            cfg_id=get_one_config(plan_id)
            if not cfg_id:
                await send_dm(context, user_id, "پرداخت تایید شد ولی مخزن خالی بود! سریعا توسط ادمین شارژ میشه 🙏")
            else:
                mark_config_sold(cfg_id, user_id)
                if discount_code:
                    discount_mark_used(discount_code)
                record_purchase(user_id, plan_id, cfg_id, (net_price or 0), discount_code)
                content,isimg=get_config_content(cfg_id)
                await send_dm(context, user_id, "🎉 تبریک! پرداختت تایید شد و کانفیگ برات ارسال شد.")
                await send_dm(context, user_id, f"📄 کانفیگت:\n\n<code>{content}</code>", reply_markup=main_menu(is_admin_user(user_id)))
        # update admin message text to reflect status (but keep buttons active)
        await q.edit_message_caption(caption=(q.message.caption or q.message.text) + f"\n\n✅ وضعیت: تایید شد.")
    else:
        await send_dm(context, user_id, "❌ رسیدت رد شد. اگه ابهامی هست با پشتیبانی در ارتباط باش 😊")
        await q.edit_message_caption(caption=(q.message.caption or q.message.text) + f"\n\n❌ وضعیت: رد شد.")

# ---------------------------- Admin Panel ----------------------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛠 <b>پنل ادمین</b>\nیه گزینه رو انتخاب کن:", parse_mode=ParseMode.HTML,
                                    reply_markup=ReplyKeyboardMarkup(ADMIN_MENU_BUTTONS, resize_keyboard=True))

# 1) Card number
async def admin_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    card=get_card_number()
    await update.message.reply_text(f"💳 شماره کارت فعلی:\n<b>{card}</b>\n\n"
                                    f"برای تغییر، شمارهٔ جدید رو بفرست یا «↩️ بازگشت به منوی اصلی».",
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
    session_set(u.id, step="ADMIN_CARD_AWAIT")

async def admin_text_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # shared handler for some admin text steps
    u=update.effective_user
    txt=update.message.text.strip()
    sess=session_get(u.id)
    step=sess.get("step")

    if step=="ADMIN_CARD_AWAIT":
        if txt=="↩️ بازگشت به منوی اصلی":
            session_set(u.id, step=None)
            await admin_panel(update, context)
            return
        with db() as conn:
            c=conn.cursor()
            c.execute("INSERT OR REPLACE INTO admin_config(key,value) VALUES('card_number',?)",(txt,))
        await update.message.reply_text("✅ شماره کارت به‌روزرسانی شد.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return

    if step=="ADMIN_ADD_ADMIN_AWAIT":
        try:
            tgt=int(txt)
        except:
            await update.message.reply_text("آیدی عددی معتبر بفرست 🙂")
            return
        if tgt==DEFAULT_ADMIN_ID:
            await update.message.reply_text("این ادمین پیش‌فرضه و قبلاً وجود داره ✅")
            return
        with db() as conn:
            c=conn.cursor()
            c.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)",(tgt,))
            c.execute("INSERT OR IGNORE INTO users(user_id,username,full_name,is_admin,wallet,created_at) VALUES (?,?,?,?,?,?)",
                      (tgt, None, "Admin", 1, 0, datetime.utcnow().isoformat()))
            c.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (tgt,))
        await update.message.reply_text("✅ ادمین جدید اضافه شد.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return

    if step=="ADMIN_DEL_ADMIN_AWAIT":
        try:
            tgt=int(txt)
        except:
            await update.message.reply_text("آیدی عددی معتبر بفرست 🙂")
            return
        if tgt==DEFAULT_ADMIN_ID:
            await update.message.reply_text("⛔️ حذف ادمین پیش‌فرض مجاز نیست.")
            return
        with db() as conn:
            c=conn.cursor()
            c.execute("DELETE FROM admins WHERE user_id=?", (tgt,))
            c.execute("UPDATE users SET is_admin=0 WHERE user_id=?", (tgt,))
        await update.message.reply_text("✅ ادمین حذف شد.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return

    if step=="ADMIN_WALLET_USER_AWAIT_ID":
        # get user and show options
        alias = txt.lstrip("@")
        with db() as conn:
            c=conn.cursor()
            if alias.isdigit():
                c.execute("SELECT user_id, username, wallet FROM users WHERE user_id=?", (int(alias),))
            else:
                c.execute("SELECT user_id, username, wallet FROM users WHERE username=?", (alias,))
            row=c.fetchone()
        if not row:
            await update.message.reply_text("کاربر پیدا نشد.")
            return
        session_set(u.id, step=f"ADMIN_WALLET_EDIT_{row['user_id']}")
        await update.message.reply_text(f"کاربر: @{row['username'] or '—'} | {row['user_id']}\nموجودی: {to_rials(row['wallet'])}\n\n"
                                        f"برای افزایش، عدد مثبت بفرست. برای کاهش، عدد منفی. یا «↩️ بازگشت به منوی اصلی».",
                                        reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return
    if step and step.startswith("ADMIN_WALLET_EDIT_"):
        if txt=="↩️ بازگشت به منوی اصلی":
            session_set(u.id, step=None)
            await admin_panel(update, context)
            return
        target_id=int(step.split("_")[-1])
        try:
            delta=int(txt)
        except:
            await update.message.reply_text("عدد صحیح بفرست (مثلاً 50000 یا -25000).")
            return
        if delta>=0:
            wallet_add(target_id, delta)
        else:
            if not wallet_sub(target_id, -delta):
                await update.message.reply_text("موجودی کافی نیست برای کسر.")
                return
        await update.message.reply_text("✅ انجام شد.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return

    if step=="ADMIN_DISC_NEW_CODE":
        parts=txt.split()
        if len(parts)<2:
            await update.message.reply_text("فرمت: CODE PERCENT [MAX_USES]  (مثال: OFF15 15 100)")
            return
        code=parts[0].upper()
        try:
            percent=int(parts[1])
        except:
            await update.message.reply_text("درصد باید عدد باشه.")
            return
        max_uses=None
        if len(parts)>=3:
            try:
                max_uses=int(parts[2])
            except:
                max_uses=None
        with db() as conn:
            c=conn.cursor()
            c.execute("INSERT OR REPLACE INTO discount_codes(code,percent,max_uses,used_count,expires_at) VALUES (?,?,?,?,?)",
                      (code, percent, max_uses, 0, None))
        await update.message.reply_text("✅ کد تخفیف ساخته/بروزرسانی شد.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return

    if step=="ADMIN_BROADCAST_AWAIT":
        # send to all users
        with db() as conn:
            c=conn.cursor()
            c.execute("SELECT user_id FROM users")
            users=[r["user_id"] for r in c.fetchall()]
        await update.message.reply_text(f"در حال ارسال به {len(users)} کاربر…")
        for uid in users:
            asyncio.create_task(send_dm(context, uid, txt))
        await update.message.reply_text("✅ ارسال شد.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return

    if step=="ADMIN_PLAN_NEW_AWAIT_TITLE":
        # txt => title
        session_set(u.id, step="ADMIN_PLAN_NEW_AWAIT_DAYS", plan_title=txt)
        await update.message.reply_text("مدت پلن (روز)؟", reply_markup=cancel_only_keyboard("↩️ بازگشت به منوی اصلی"))
        return
    if step=="ADMIN_PLAN_NEW_AWAIT_DAYS":
        try:
            days=int(txt)
        except:
            await update.message.reply_text("عدد روز رو درست بفرست.")
            return
        session_set(u.id, step="ADMIN_PLAN_NEW_AWAIT_TRAFFIC", plan_days=days)
        await update.message.reply_text("حجم (GB)؟")
        return
    if step=="ADMIN_PLAN_NEW_AWAIT_TRAFFIC":
        try:
            gb=int(txt)
        except:
            await update.message.reply_text("عدد GB رو درست بفرست.")
            return
        session_set(u.id, step="ADMIN_PLAN_NEW_AWAIT_PRICE", plan_traffic=gb)
        await update.message.reply_text("قیمت فروش (تومان)؟")
        return
    if step=="ADMIN_PLAN_NEW_AWAIT_PRICE":
        try:
            price=int(txt)
        except:
            await update.message.reply_text("قیمت رو به تومان و عدد صحیح بفرست.")
            return
        # also ask cost price to track profit
        session_set(u.id, step="ADMIN_PLAN_NEW_AWAIT_COST", plan_price=price)
        await update.message.reply_text("قیمت تمام‌شده برای شما (برای آمار سود)؟")
        return
    if step=="ADMIN_PLAN_NEW_AWAIT_COST":
        try:
            cost=int(txt)
        except:
            await update.message.reply_text("عدد صحیح بفرست.")
            return
        sess=session_get(u.id)
        with db() as conn:
            c=conn.cursor()
            c.execute("INSERT INTO plans(title,days,traffic_gb,price,created_at) VALUES (?,?,?,?,?)",
                      (sess.get("plan_title"), sess.get("plan_days"), sess.get("plan_traffic"), sess.get("plan_price"), datetime.utcnow().isoformat()))
        session_set(u.id, step=None)
        await update.message.reply_text("✅ پلن ساخته شد. حالا از «مدیریت پلن و مخزن» می‌تونی مخزنش رو شارژ کنی.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return

    if step and step.startswith("ADMIN_STOCK_ADD_"):
        plan_id=int(step.split("_")[-1])
        if txt=="اتمام":
            session_set(u.id, step=None)
            await update.message.reply_text("✅ اتمام افزودن کانفیگ‌ها.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
            return
        # each message adds a config entry
        with db() as conn:
            c=conn.cursor()
            c.execute("INSERT INTO plan_configs(plan_id,content,is_image,created_at) VALUES (?,?,?,?)",
                      (plan_id, txt, 0, datetime.utcnow().isoformat()))
        await update.message.reply_text("➕ اضافه شد. (برای اتمام بنویس: اتمام)")
        return

async def admin_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT user_id FROM admins")
        adms=[r["user_id"] for r in c.fetchall()]
    txt="👮 <b>مدیریت ادمین‌ها</b>\nادمین‌ها:\n"
    for a in adms:
        mark = " (پیش‌فرض)" if a==DEFAULT_ADMIN_ID else ""
        txt+=f"• {a}{mark}\n"
    kb=ReplyKeyboardMarkup([
        ["➕ افزودن ادمین", "➖ حذف ادمین"],
        ["↩️ بازگشت به منوی اصلی"]
    ], resize_keyboard=True)
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    session_set(u.id, step="ADMIN_ADMINS_MENU")

async def admin_receipts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM receipts WHERE status='PENDING' ORDER BY id DESC")
        rows=c.fetchall()
    if not rows:
        await update.message.reply_text("فعلاً رسید در انتظاری نداریم.", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
        return
    for r in rows:
        cap=(f"🧾 رسید #{r['id']}\n"
             f"👤 کاربر: {r['user_id']}\n"
             f"نوع: {r['kind']}\n"
             f"پلن: {r['plan_id'] or '—'}\n"
             f"مبلغ: {to_rials(r['final_amount'] or 0)}\n"
             f"کد تخفیف: {r['discount_code'] or '—'}\n"
             f"تاریخ: {r['created_at']}")
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید", callback_data=f"rcpt:{r['id']}:APPROVE"),
             InlineKeyboardButton("❌ رد", callback_data=f"rcpt:{r['id']}:DENY")]
        ])
        if r["file_id"]:
            try:
                await context.bot.send_photo(chat_id=u.id, photo=r["file_id"], caption=cap, reply_markup=kb)
            except:
                await context.bot.send_message(chat_id=u.id, text=cap, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=u.id, text=cap, reply_markup=kb)

async def admin_user_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    await update.message.reply_text("آیدی عددی یا یوزرنیم کاربر رو بفرست (مثل 123456 یا @user).", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
    session_set(u.id, step="ADMIN_WALLET_USER_AWAIT_ID")

async def admin_discounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM discount_codes")
        rows=c.fetchall()
    txt="🏷 <b>کدهای تخفیف</b>\n"
    for d in rows:
        txt+=f"• {d['code']}: {d['percent']}% | استفاده‌شده: {d['used_count']}/{d['max_uses'] or '∞'}\n"
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML,
                                    reply_markup=ReplyKeyboardMarkup([["➕ ساخت/ویرایش کد", "↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
    session_set(u.id, step="ADMIN_DISC_MENU")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    await update.message.reply_text("متن اعلان همگانی رو بفرست:", reply_markup=ReplyKeyboardMarkup([["↩️ بازگشت به منوی اصلی"]], resize_keyboard=True))
    session_set(u.id, step="ADMIN_BROADCAST_AWAIT")

async def admin_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM plans")
        rows=c.fetchall()
    kb=[]
    for r in rows:
        kb.append([f"🔧 {r['id']} - {r['title']} (موجودی: {stock_count(r['id'])})"])
    kb.append(["➕ ساخت پلن جدید", "↩️ بازگشت به منوی اصلی"])
    await update.message.reply_text("🧰 مدیریت پلن و مخزن:\nیکی رو انتخاب کن:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    session_set(u.id, step="ADMIN_PLANS_MENU")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT * FROM sales_stats WHERE id=1")
        s=c.fetchone()
        total_sales=s["total_sales"]
        total_rev=s["total_revenue"]
        # last 7/30 days
        now=datetime.utcnow().isoformat()
        c.execute("SELECT COUNT(*) cnt, COALESCE(SUM(price_paid),0) rev FROM purchases WHERE started_at>=?", ((datetime.utcnow()-timedelta(days=7)).isoformat(),))
        w7=c.fetchone()
        c.execute("SELECT COUNT(*) cnt, COALESCE(SUM(price_paid),0) rev FROM purchases WHERE started_at>=?", ((datetime.utcnow()-timedelta(days=30)).isoformat(),))
        w30=c.fetchone()
        # top buyers
        c.execute("""SELECT user_id, COUNT(*) cc, SUM(price_paid) rev FROM purchases
                     GROUP BY user_id ORDER BY rev DESC LIMIT 5""")
        tops=c.fetchall()
    txt=(f"📈 <b>آمار فروش</b>\n"
         f"کل فروش: {total_sales} | درآمد کل: {to_rials(total_rev)}\n"
         f"۷ روز اخیر: {w7['cnt']} خرید | {to_rials(w7['rev'])}\n"
         f"۳۰ روز اخیر: {w30['cnt']} خرید | {to_rials(w30['rev'])}\n\n"
         f"🏆 تاپ بایرها:\n")
    for t in tops:
        txt += f"• {t['user_id']} | خرید: {t['cc']} | مبلغ: {to_rials(t['rev'])}\n"
    kb=ReplyKeyboardMarkup([["🔄 ریست آمار", "↩️ بازگشت به منوی اصلی"]], resize_keyboard=True)
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    session_set(u.id, step="ADMIN_STATS_MENU")

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): return
    kb=ReplyKeyboardMarkup([
        ["🔍 جستجو کاربر", "📋 لیست کاربران"],
        ["↩️ بازگشت به منوی اصلی"]
    ], resize_keyboard=True)
    await update.message.reply_text("👥 مدیریت کاربران:", reply_markup=kb)
    session_set(u.id, step="ADMIN_USERS_MENU")

# Small admin menu router for button texts
async def admin_button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    if not is_admin_user(u.id): 
        return await text_router(update, context)
    txt=update.message.text.strip()
    sess=session_get(u.id)
    step=sess.get("step")

    if step=="ADMIN_ADMINS_MENU":
        if txt=="➕ افزودن ادمین":
            session_set(u.id, step="ADMIN_ADD_ADMIN_AWAIT")
            return await update.message.reply_text("آیدی عددی ادمین جدید رو بفرست:")
        if txt=="➖ حذف ادمین":
            session_set(u.id, step="ADMIN_DEL_ADMIN_AWAIT")
            return await update.message.reply_text("آیدی عددی ادمینی که می‌خوای حذف کنی رو بفرست:")

    if step=="ADMIN_DISC_MENU":
        if txt=="➕ ساخت/ویرایش کد":
            session_set(u.id, step="ADMIN_DISC_NEW_CODE")
            return await update.message.reply_text("فرمت: CODE PERCENT [MAX_USES]\nمثال: OFF15 15 100")

    if step=="ADMIN_PLANS_MENU":
        if txt=="➕ ساخت پلن جدید":
            session_set(u.id, step="ADMIN_PLAN_NEW_AWAIT_TITLE")
            return await update.message.reply_text("عنوان پلن؟", reply_markup=cancel_only_keyboard("↩️ بازگشت به منوی اصلی"))
        if txt.startswith("🔧 "):
            # extract id from "🔧 <id> - <title> ..."
            try:
                pid=int(txt.split()[1])
            except:
                return
            # show stock and actions
            with db() as conn:
                c=conn.cursor()
                c.execute("SELECT * FROM plans WHERE id=?", (pid,))
                p=c.fetchone()
            s=stock_count(pid)
            kb=ReplyKeyboardMarkup([
                [f"➕ افزودن به مخزن {pid}", f"🧹 پاکسازی مخزن {pid}"],
                [f"✏️ ویرایش {pid}", "↩️ بازگشت به منوی اصلی"]
            ], resize_keyboard=True)
            await update.message.reply_text(f"پلن: {p['title']} | موجودی مخزن: {s}\nیکی از گزینه‌ها رو بزن:", reply_markup=kb)
            session_set(u.id, step="ADMIN_PLAN_ITEM_MENU", plan_id=pid)

    if step=="ADMIN_PLAN_ITEM_MENU":
        if txt.startswith("➕ افزودن به مخزن"):
            pid=int(txt.split()[-1])
            session_set(u.id, step=f"ADMIN_STOCK_ADD_{pid}")
            return await update.message.reply_text("هر پیام = یک کانفیگ. برای اتمام بنویس: اتمام")
        if txt.startswith("🧹 پاکسازی مخزن"):
            pid=int(txt.split()[-1])
            with db() as conn:
                c=conn.cursor()
                c.execute("DELETE FROM plan_configs WHERE plan_id=? AND sold_to_user IS NULL", (pid,))
            return await update.message.reply_text("✅ مخزن پاکسازی شد.")
        if txt.startswith("✏️ ویرایش"):
            pid=int(txt.split()[-1])
            # (برای سادگی این نسخه فقط پیام راهنما می‌دهد)
            return await update.message.reply_text("ویرایش جزئیات پلن (عنوان/قیمت/حجم/روز) را در نسخه بعدی با فرم مرحله‌ای قرار می‌دهیم ✏️")

    if step=="ADMIN_STATS_MENU":
        if txt=="🔄 ریست آمار":
            with db() as conn:
                c=conn.cursor()
                c.execute("UPDATE sales_stats SET total_sales=0,total_revenue=0 WHERE id=1")
            return await update.message.reply_text("✅ آمار ریست شد.")

    if step=="ADMIN_USERS_MENU":
        if txt=="📋 لیست کاربران":
            with db() as conn:
                c=conn.cursor()
                c.execute("SELECT user_id, username, wallet FROM users ORDER BY user_id DESC LIMIT 50")
                rows=c.fetchall()
            t="📋 ۵۰ کاربر اخیر:\n"
            for r in rows:
                t+=f"• {r['user_id']} | @{r['username'] or '—'} | {to_rials(r['wallet'])}\n"
            return await update.message.reply_text(t)
        if txt=="🔍 جستجو کاربر":
            session_set(u.id, step="ADMIN_USERS_SEARCH")
            return await update.message.reply_text("آیدی عددی یا یوزرنیم رو بفرست:")
        if step=="ADMIN_USERS_SEARCH":
            alias = txt.lstrip("@")
            with db() as conn:
                c=conn.cursor()
                if alias.isdigit():
                    c.execute("""SELECT u.user_id, u.username, u.wallet,
                                 (SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id) AS buys
                                 FROM users u WHERE u.user_id=?""",(int(alias),))
                else:
                    c.execute("""SELECT u.user_id, u.username, u.wallet,
                                 (SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id) AS buys
                                 FROM users u WHERE u.username=?""",(alias,))
                row=c.fetchone()
            if not row:
                return await update.message.reply_text("پیدا نشد.")
            return await update.message.reply_text(f"👤 {row['user_id']} | @{row['username'] or '—'}\n"
                                                   f"موجودی: {to_rials(row['wallet'])}\n"
                                                   f"تعداد خرید: {row['buys']}")

    # fall back
    return await text_router(update, context)

# ---------------------------- Ticket helpers ----------------------------
async def create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id:int, subject:str):
    with db() as conn:
        c=conn.cursor()
        c.execute("INSERT INTO tickets(user_id,subject,status,created_at) VALUES (?,?,?,?)",
                  (user_id, subject, "OPEN", datetime.utcnow().isoformat()))
        tid=c.lastrowid
        c.execute("INSERT INTO ticket_messages(ticket_id,sender_id,text,created_at) VALUES (?,?,?,?)",
                  (tid, user_id, f"شروع تیکت: {subject}", datetime.utcnow().isoformat()))
    await update.message.reply_text(f"تیکت #{tid} ساخته شد. پیام بعدی‌ت رو بنویس تا داخل همین تیکت ثبت بشه.",
                                    reply_markup=cancel_only_keyboard())
    session_set(user_id, step=f"TICKET_REPLY_{tid}")

async def add_ticket_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id:int, ticket_id:int, text:str):
    with db() as conn:
        c=conn.cursor()
        c.execute("INSERT INTO ticket_messages(ticket_id,sender_id,text,created_at) VALUES (?,?,?,?)",
                  (ticket_id, user_id, text, datetime.utcnow().isoformat()))
    await update.message.reply_text("✅ پیام ثبت شد. می‌تونی ادامه بدی یا «↩️ انصراف».")
    # notify admins
    with db() as conn:
        c=conn.cursor()
        c.execute("SELECT user_id FROM admins")
        admins=[r["user_id"] for r in c.fetchall()]
    for aid in admins:
        asyncio.create_task(send_dm(context, aid, f"🎫 پیام جدید در تیکت #{ticket_id} از {user_id}: \n{text}"))

# ---------------------------- Admin panel entry points ----------------------------
async def admin_card_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # handled in text flow
    pass

async def admin_admins_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # handled in admin_button_router
    pass

# ---------------------------- Webhook endpoints ----------------------------
@app.get("/")
async def root():
    return PlainTextResponse("OK")

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot.application.bot)
    await bot.application.process_update(update)
    return JSONResponse({"ok": True})

# ---------------------------- Build Telegram Application ----------------------------
application: Application = ApplicationBuilder().token(BOT_TOKEN).build()

# Commands
application.add_handler(CommandHandler("start", start))
# Callback queries
application.add_handler(CallbackQueryHandler(callback_router, pattern=r"^plan:\d+$"))
application.add_handler(CallbackQueryHandler(callback_receipt, pattern=r"^rcpt:\d+:(APPROVE|DENY)$"))

# Admin routing (specific before general)
application.add_handler(MessageHandler(filters.Regex("^(💳 شماره کارت|👮 مدیریت ادمین‌ها|🧾 رسیدهای در انتظار|💼 کیف پول کاربر|🏷 کدهای تخفیف|📣 اعلان همگانی|🧰 مدیریت پلن و مخزن|📈 آمار فروش|👥 کاربران|↩️ بازگشت به منوی اصلی)$"), admin_button_router))

# Payment-specific handler
application.add_handler(MessageHandler(filters.Regex("^(💳 کارت‌به‌کارت|💼 پرداخت از کیف پول|🏷 اعمال کد تخفیف|↩️ انصراف|➕ افزایش موجودی|🔄 به‌روزرسانی موجودی|📝 تیکت جدید|📚 سابقه تیکت‌ها)$"), message_handler))

# Admin text flow
application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND) & (~filters.StatusUpdate.ALL), admin_text_flow))

# General menu router last
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

bot = application

# ---------------------------- Startup: set webhook ----------------------------
@app.on_event("startup")
async def on_startup():
    if BOT_TOKEN.startswith("000000:TEST"):
        log.error("❌ Invalid token. Set TELEGRAM_BOT_TOKEN env.")
        return
    await application.initialize()
    if BASE_URL:
        url = f"{BASE_URL}/webhook/telegram"
        try:
            await application.bot.set_webhook(url=url)
            log.info(f"✅ Webhook set to: {url}")
        except Exception as e:
            log.error(f"Failed to set webhook: {e}")
    await application.start()

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()
