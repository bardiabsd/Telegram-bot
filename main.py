import os
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from flask import Flask, request, abort
import telebot
from telebot import types

# ========= ENV & BOT =========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
APP_URL = os.environ.get("APP_URL", "").strip().rstrip("/")
ADMIN_IDS_ENV = os.environ.get("ADMIN_IDS", "").strip()

# توکن را می‌توانی اینجا هاردکد هم بکنی (اما بهتره ENV باشد)
if not BOT_TOKEN:
    # fallback (در صورت نیاز): BOT_TOKEN = "8339...."  # <-- امن نیست، فقط برای تست
    raise RuntimeError("BOT_TOKEN env is required")

# ادمین‌ها
DEFAULT_ADMINS = {1743359080}
if ADMIN_IDS_ENV:
    try:
        DEFAULT_ADMINS = {int(x) for x in ADMIN_IDS_ENV.split(",") if x.strip()}
    except Exception:
        pass

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ========= DATABASE =========
DB_PATH = os.environ.get("DB_PATH", "db.sqlite3")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    conn = get_db()
    c = conn.cursor()

    # کاربران
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ادمین‌ها
    c.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY
    )
    """)

    # تنظیمات (متون، دکمه‌ها، فلگ‌ها)
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # کیف‌پول
    c.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0
    )
    """)

    # پلن‌ها
    c.execute("""
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        days INTEGER,
        volume_gb REAL,
        price INTEGER,
        description TEXT,
        active INTEGER DEFAULT 1
    )
    """)

    # مخزن هر پلن: کانفیگ‌ها (متن + تصویر به صورت file_id)
    c.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER,
        text TEXT,
        image_file_id TEXT,
        used INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # کد تخفیف
    c.execute("""
    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        percent INTEGER,
        plan_id INTEGER,          -- NULL یعنی همه پلن‌ها
        expires_at TEXT,          -- ISO
        max_uses INTEGER,         -- NULL یعنی نامحدود
        used_count INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1
    )
    """)

    # رسیدها (شارژ/خرید)
    c.execute("""
    CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT,                 -- 'wallet' یا 'purchase'
        status TEXT DEFAULT 'pending', -- pending/approved/rejected
        amount INTEGER,            -- مبلغ شارژ یا پرداخت
        expected INTEGER,          -- مبلغ انتظار (برای خرید یا مابه‌التفاوت)
        plan_id INTEGER,           -- اگر خرید کانفیگ باشد
        coupon_code TEXT,
        note TEXT,                 -- توضیحات کاربر
        photo_file_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT,
        reviewer_id INTEGER
    )
    """)

    # سفارش‌ها
    c.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan_id INTEGER,
        price INTEGER,
        discount_percent INTEGER,
        final_amount INTEGER,
        coupon_code TEXT,
        delivered_at TEXT,
        expires_at TEXT,
        notified_3d INTEGER DEFAULT 0
    )
    """)

    # تیکت‌ها
    c.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject TEXT,
        status TEXT DEFAULT 'open', -- open/closed
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # پیام‌های تیکت
    c.execute("""
    CREATE TABLE IF NOT EXISTS ticket_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER,
        user_id INTEGER,
        from_admin INTEGER DEFAULT 0,
        text TEXT,
        photo_file_id TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ثبت کاربران جدید در جدول ادمین‌ها (defaults)
    for uid in DEFAULT_ADMINS:
        c.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (uid,))

    # چند متن و دکمه پیش‌فرض
    defaults = {
        "TXT_WELCOME": "سلام! خوش اومدی 🌹\nاز دکمه‌های زیر استفاده کن.",
        "BTN_SHOP": "🛒 خرید پلن",
        "BTN_WALLET": "🪙 کیف پول",
        "BTN_SUPPORT": "🎫 تیکت پشتیبانی",
        "BTN_MY": "👤 حساب کاربری",
        "BTN_ADMIN": "👑 پنل ادمین",
        "CARD2CARD_TEXT": "لطفاً رسید کارت‌به‌کارت را ارسال کنید.",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v))

    conn.commit()
    conn.close()

db_init()

# ========= HELPERS =========
def is_admin(user_id: int) -> bool:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (int(user_id),))
    row = cur.fetchone()
    conn.close()
    return row is not None

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()

def ensure_user(m: types.Message):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users(id, username, first_name, last_name)
        VALUES(?,?,?,?)
    """, (m.from_user.id, m.from_user.username, m.from_user.first_name, m.from_user.last_name))
    conn.commit()
    conn.close()

def wallet_balance(user_id: int) -> int:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM wallets WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["balance"] if row else 0

def wallet_add(user_id: int, amount: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO wallets(user_id, balance) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance", (user_id, amount))
    conn.commit()
    conn.close()

def wallet_subtract(user_id: int, amount: int) -> bool:
    bal = wallet_balance(user_id)
    if bal < amount:
        return False
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE wallets SET balance=balance-? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()
    return True

def list_plans_with_stock() -> List[sqlite3.Row]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*,
               (SELECT COUNT(1) FROM inventory i WHERE i.plan_id=p.id AND i.used=0) AS stock
        FROM plans p
        WHERE p.active=1
        ORDER BY p.id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_plan(plan_id: int) -> Optional[sqlite3.Row]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*,
               (SELECT COUNT(1) FROM inventory i WHERE i.plan_id=p.id AND i.used=0) AS stock
        FROM plans p WHERE p.id=?
    """, (plan_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_free_inventory(plan_id: int) -> Optional[sqlite3.Row]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory WHERE plan_id=? AND used=0 ORDER BY id ASC LIMIT 1", (plan_id,))
    row = cur.fetchone()
    conn.close()
    return row

def mark_inventory_used(inv_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE inventory SET used=1 WHERE id=?", (inv_id,))
    conn.commit()
    conn.close()

def validate_coupon(code: str, plan_id: int) -> Tuple[int, str]:
    """
    خروجی: (درصد تخفیف، پیام خطا یا خالی)
    """
    code = code.strip().upper()
    if not code:
        return 0, "کدی وارد نشده"

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM coupons WHERE code=? AND active=1", (code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return 0, "کد تخفیف نامعتبر است."

    # تاریخ انقضا
    if row["expires_at"]:
        try:
            if datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
                conn.close()
                return 0, "کد تخفیف منقضی شده است."
        except Exception:
            pass

    # محدودیت پلن
    if row["plan_id"] and int(row["plan_id"]) != int(plan_id):
        conn.close()
        return 0, "این کد مخصوص پلن دیگری است."

    # سقف استفاده
    if row["max_uses"] and row["used_count"] >= row["max_uses"]:
        conn.close()
        return 0, "سقف استفاده از این کد پر شده است."

    percent = max(0, min(100, int(row["percent"])))
    conn.close()
    return percent, ""

def increment_coupon_use(code: Optional[str]):
    if not code:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE coupons SET used_count=used_count+1 WHERE code=?", (code,))
    conn.commit()
    conn.close()

def create_order_and_deliver(user_id: int, plan_id: int, price: int, discount_percent: int, final_amount: int, coupon_code: Optional[str]) -> bool:
    # تحویل کانفیگ
    inv = get_free_inventory(plan_id)
    if not inv:
        return False

    plan = get_plan(plan_id)
    if not plan:
        return False

    delivered_at = datetime.utcnow()
    expires_at = delivered_at + timedelta(days=int(plan["days"] or 30))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders(user_id, plan_id, price, discount_percent, final_amount, coupon_code, delivered_at, expires_at)
        VALUES(?,?,?,?,?,?,?,?)
    """, (
        user_id, plan_id, price, discount_percent, final_amount, coupon_code or None,
        delivered_at.isoformat(), expires_at.isoformat()
    ))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    # ارسال به کاربر
    text = inv["text"] or "بدون متن"
    try:
        bot.send_message(user_id, f"✅ پلن شما تحویل شد.\n\n<b>{plan['name']}</b>\n⏳ اعتبار تا: <code>{expires_at.date()}</code>")
        if text:
            bot.send_message(user_id, f"<b>کانفیگ:</b>\n<code>{text}</code>")
        if inv["image_file_id"]:
            bot.send_photo(user_id, inv["image_file_id"], caption="تصویر کانفیگ")
    except Exception as e:
        print("SEND ERROR:", e)

    # کم کردن از مخزن
    mark_inventory_used(inv["id"])

    # افزایش استفاده‌ی کد
    increment_coupon_use(coupon_code)

    return True

def notify_admins(text: str, reply_markup=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM admins")
    rows = cur.fetchall()
    conn.close()
    for r in rows:
        try:
            bot.send_message(r["user_id"], text, reply_markup=reply_markup)
        except:
            pass

# ========= USER STATE (Cart/Flows) =========
user_state: Dict[int, Dict[str, Any]] = {}

def clear_state(uid: int):
    user_state.pop(uid, None)

# ========= KEYBOARDS =========
def main_menu(uid: int) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(get_setting("BTN_SHOP", "🛒 خرید پلن"), get_setting("BTN_WALLET", "🪙 کیف پول"))
    kb.add(get_setting("BTN_SUPPORT", "🎫 تیکت پشتیبانی"), get_setting("BTN_MY", "👤 حساب کاربری"))
    if is_admin(uid):
        kb.add(get_setting("BTN_ADMIN", "👑 پنل ادمین"))
    return kb

def plans_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    plans = list_plans_with_stock()
    for p in plans:
        name = f"{p['name']} — {p['price']}T ({int(p['stock'])} موجود)"
        btn = types.InlineKeyboardButton(
            text=("⛔ " + name) if p["stock"] == 0 else name,
            callback_data=f"plan_{p['id']}"
        )
        if p["stock"] == 0:
            btn = types.InlineKeyboardButton(text=f"⛔ {name}", callback_data=f"nostock_{p['id']}")
        kb.add(btn)
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"))
    return kb

def plan_detail_keyboard(plan_id: int, can_buy: bool):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏷 اعمال/حذف کد تخفیف", callback_data=f"coupon_{plan_id}"))
    if can_buy:
        kb.add(
            types.InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data=f"payc2c_{plan_id}"),
            types.InlineKeyboardButton("🪙 خرید با کیف پول", callback_data=f"paywallet_{plan_id}")
        )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_plans"))
    return kb

def wallet_menu(uid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("➕ شارژ کیف پول (ارسال رسید)", callback_data="wallet_charge"),
        types.InlineKeyboardButton("🧾 تاریخچه سفارش‌ها", callback_data="orders_history")
    )
    kb.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"))
    return kb

def admin_menu() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📦 مدیریت پلن‌ها", "📂 مدیریت مخزن")
    kb.add("🏷 کد تخفیف", "🧾 رسیدها")
    kb.add("🪙 کیف پول (ادمین)", "🎫 تیکت‌ها")
    kb.add("👥 کاربران", "📊 آمار")
    kb.add("🛠 متن/دکمه‌ها", "📢 اعلان همگانی")
    kb.add("👑 ادمین‌ها", "🔙 بازگشت")
    return kb

# ========= START / MENU =========
@bot.message_handler(commands=['start'])
def start_cmd(m: types.Message):
    ensure_user(m)
    clear_state(m.from_user.id)
    bot.send_message(m.chat.id, get_setting("TXT_WELCOME", "سلام!"), reply_markup=main_menu(m.from_user.id))

@bot.message_handler(commands=['whoami'])
def whoami(m: types.Message):
    bot.reply_to(m, f"🆔 <code>{m.from_user.id}</code>\n👑 Admin: {'✅' if is_admin(m.from_user.id) else '❌'}")

# ========= USER FLOWS =========
@bot.message_handler(func=lambda x: x.text == get_setting("BTN_SHOP", "🛒 خرید پلن"))
def shop_btn(m: types.Message):
    bot.send_message(m.chat.id, "📦 لیست پلن‌ها:", reply_markup=types.ReplyKeyboardRemove())
    bot.send_message(m.chat.id, "یک پلن انتخاب کنید:", reply_markup=plans_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("nostock_"))
def nostock_cb(c: types.CallbackQuery):
    bot.answer_callback_query(c.id, "موجودی این پلن تمام شده است.", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "back_plans")
def back_plans(c: types.CallbackQuery):
    bot.edit_message_text("📦 لیست پلن‌ها:", chat_id=c.message.chat.id, message_id=c.message.message_id, reply_markup=plans_keyboard())

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def back_main(c: types.CallbackQuery):
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except:
        pass
    bot.send_message(c.message.chat.id, "منوی اصلی:", reply_markup=main_menu(c.from_user.id))

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_"))
def plan_detail(c: types.CallbackQuery):
    plan_id = int(c.data.split("_")[1])
    p = get_plan(plan_id)
    if not p:
        bot.answer_callback_query(c.id, "پلن یافت نشد.", show_alert=True)
        return
    if int(p["stock"]) == 0:
        kb = plan_detail_keyboard(plan_id, False)
    else:
        kb = plan_detail_keyboard(plan_id, True)

    # نگهداری state سبد
    st = user_state.setdefault(c.from_user.id, {})
    st["current_plan"] = plan_id
    st.pop("coupon", None)

    desc = f"<b>{p['name']}</b>\n💰 قیمت: <b>{p['price']}T</b>\n⏳ اعتبار: {p['days']} روز\n📦 حجم: {p['volume_gb']} GB\n\n{p['description'] or ''}\n\nموجودی: {p['stock']}"
    try:
        bot.edit_message_text(desc, chat_id=c.message.chat.id, message_id=c.message.message_id, reply_markup=kb)
    except:
        bot.send_message(c.message.chat.id, desc, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coupon_"))
def coupon_flow(c: types.CallbackQuery):
    plan_id = int(c.data.split("_")[1])
    st = user_state.setdefault(c.from_user.id, {})
    st["current_plan"] = plan_id
    st["await_coupon"] = True
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "کد تخفیف را ارسال کنید.\nبرای حذف کد، کلمه «حذف» را بفرستید.")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("await_coupon") and bool(m.text))
def coupon_apply(m: types.Message):
    st = user_state.setdefault(m.from_user.id, {})
    plan_id = st.get("current_plan")
    if m.text.strip() == "حذف":
        st.pop("coupon", None)
        st["await_coupon"] = False
        bot.reply_to(m, "کد تخفیف حذف شد ✅")
        show_plan_after_coupon(m.chat.id, plan_id)
        return

    percent, err = validate_coupon(m.text, plan_id)
    if err:
        bot.reply_to(m, f"⛔ {err}")
    else:
        st["coupon"] = m.text.strip().upper()
        bot.reply_to(m, f"✅ کد اعمال شد: {percent}%")
    st["await_coupon"] = False
    show_plan_after_coupon(m.chat.id, plan_id)

def show_plan_after_coupon(chat_id: int, plan_id: int):
    p = get_plan(plan_id)
    if not p:
        bot.send_message(chat_id, "پلن یافت نشد.")
        return
    st = user_state.setdefault(chat_id, {})
    coupon = st.get("coupon")
    percent = 0
    if coupon:
        percent, _ = validate_coupon(coupon, plan_id)
    price = int(p["price"])
    final = max(0, price - (price * percent // 100))
    text = f"<b>{p['name']}</b>\n💰 قیمت: <b>{price}T</b>\n"
    if percent:
        text += f"🎟 تخفیف: {percent}% → مبلغ نهایی: <b>{final}T</b>\n"
    text += f"⏳ اعتبار: {p['days']} روز\n📦 حجم: {p['volume_gb']} GB\n\n{p['description'] or ''}\n\nموجودی: {p['stock']}"
    kb = plan_detail_keyboard(plan_id, int(p["stock"]) > 0)
    bot.send_message(chat_id, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("paywallet_"))
def pay_wallet(c: types.CallbackQuery):
    plan_id = int(c.data.split("_")[1])
    p = get_plan(plan_id)
    if not p:
        bot.answer_callback_query(c.id, "پلن یافت نشد.", show_alert=True)
        return
    st = user_state.setdefault(c.from_user.id, {})
    coupon = st.get("coupon")
    percent = 0
    if coupon:
        percent, _ = validate_coupon(coupon, plan_id)
    price = int(p["price"])
    final = max(0, price - (price * percent // 100))

    bal = wallet_balance(c.from_user.id)
    if bal >= final:
        # خرید مستقیم از کیف پول
        if not create_order_and_deliver(c.from_user.id, plan_id, price, percent, final, coupon):
            bot.answer_callback_query(c.id, "موجودی کانفیگ این پلن کافی نیست.", show_alert=True)
            return
        wallet_subtract(c.from_user.id, final)
        bot.answer_callback_query(c.id, "خرید موفق ✅")
        clear_state(c.from_user.id)
    else:
        # مابه‌التفاوت
        diff = final - bal
        st["await_receipt"] = {"kind": "wallet", "expected": diff, "note": "شارژ جهت خرید پلن", "plan_id": plan_id, "final": final, "coupon": coupon, "percent": percent, "price": price}
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, f"موجودی کیف پول کافی نیست.\nمابه‌التفاوت: <b>{diff}T</b>\nلطفاً رسید واریز همین مقدار را ارسال کنید.")
        bot.send_message(c.message.chat.id, get_setting("CARD2CARD_TEXT", "لطفاً رسید کارت‌به‌کارت را ارسال کنید."))

@bot.callback_query_handler(func=lambda c: c.data.startswith("payc2c_"))
def pay_c2c(c: types.CallbackQuery):
    plan_id = int(c.data.split("_")[1])
    p = get_plan(plan_id)
    if not p:
        bot.answer_callback_query(c.id, "پلن یافت نشد.", show_alert=True)
        return
    st = user_state.setdefault(c.from_user.id, {})
    coupon = st.get("coupon")
    percent = 0
    if coupon:
        percent, _ = validate_coupon(coupon, plan_id)
    price = int(p["price"])
    final = max(0, price - (price * percent // 100))

    st["await_receipt"] = {"kind": "purchase", "plan_id": plan_id, "expected": final, "coupon": coupon, "percent": percent, "price": price}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"مبلغ نهایی: <b>{final}T</b>\n{get_setting('CARD2CARD_TEXT','لطفاً رسید را ارسال کنید.')}")

# ----------- ارسال رسید (عمومی) -----------
@bot.message_handler(content_types=['photo', 'text'])
def handle_receipt_or_text(m: types.Message):
    st = user_state.get(m.from_user.id, {})
    if st.get("await_receipt"):
        data = st["await_receipt"]
        photo_id = None
        note = None
        if m.photo:
            photo_id = m.photo[-1].file_id
            note = m.caption or ""
        else:
            note = m.text

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO receipts(user_id, kind, amount, expected, plan_id, coupon_code, note, photo_file_id)
            VALUES(?,?,?,?,?,?,?,?)
        """, (
            m.from_user.id,
            data["kind"],
            None,  # مبلغ واقعی را ادمین در تایید وارد می‌کند
            data.get("expected"),
            data.get("plan_id"),
            data.get("coupon"),
            note,
            photo_id
        ))
        rid = cur.lastrowid
        conn.commit()
        conn.close()

        # اطلاع به ادمین‌ها
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton(f"✅ تایید {rid}", callback_data=f"rc_ok_{rid}"),
            types.InlineKeyboardButton(f"❌ رد {rid}", callback_data=f"rc_no_{rid}")
        )
        info = f"🧾 رسید جدید #{rid}\n👤 @{m.from_user.username or '-'} ({m.from_user.id})\nنوع: {data['kind']}\nانتظار: {data.get('expected') or '-'}T\nپلن: {data.get('plan_id') or '-'}\nکد: {data.get('coupon') or '-'}"
        notify_admins(info, kb)
        bot.reply_to(m, "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین…")
        # اگر این رسید برای «مابه‌التفاوت» بود، state باقی می‌ماند تا ادمین تایید کند
        return

    # پیام‌های تیکت
    t_state = st.get("ticket_open")
    if t_state:
        ticket_id = t_state["ticket_id"]
        photo_id = m.photo[-1].file_id if m.photo else None
        txt = m.caption if m.photo else m.text

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ticket_messages(ticket_id, user_id, from_admin, text, photo_file_id)
            VALUES(?,?,?,?,?)
        """, (ticket_id, m.from_user.id, 0, txt, photo_id))
        conn.commit()
        conn.close()

        bot.reply_to(m, "پیام شما در تیکت ثبت شد ✅")
        # اطلاع به ادمین
        notify_admins(f"📥 پیام جدید در تیکت #{ticket_id} از {m.from_user.id}")

# ========= WALLET =========
@bot.message_handler(func=lambda x: x.text == get_setting("BTN_WALLET", "🪙 کیف پول"))
def wallet_btn(m: types.Message):
    bal = wallet_balance(m.from_user.id)
    bot.send_message(m.chat.id, f"موجودی فعلی: <b>{bal}T</b>", reply_markup=wallet_menu(m.from_user.id))

@bot.callback_query_handler(func=lambda c: c.data == "wallet_charge")
def wallet_charge(c: types.CallbackQuery):
    st = user_state.setdefault(c.from_user.id, {})
    st["await_receipt"] = {"kind": "wallet", "expected": None, "note": "شارژ کیف پول"}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "رسید شارژ کیف پول را ارسال کنید.")
    bot.send_message(c.message.chat.id, get_setting("CARD2CARD_TEXT", "لطفاً رسید کارت‌به‌کارت را ارسال کنید."))

@bot.callback_query_handler(func=lambda c: c.data == "orders_history")
def orders_history(c: types.CallbackQuery):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT o.*, p.name as plan_name
        FROM orders o
        LEFT JOIN plans p ON p.id=o.plan_id
        WHERE o.user_id=?
        ORDER BY o.id DESC LIMIT 20
    """, (c.from_user.id,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "سفارشی ثبت نشده.")
        return
    txt = "🧾 سفارش‌های شما:\n"
    for r in rows:
        txt += f"#{r['id']} • {r['plan_name'] or '-'} • {r['final_amount']}T • {r['delivered_at'][:10]}\n"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt)

# ========= SUPPORT / TICKETS =========
@bot.message_handler(func=lambda x: x.text == get_setting("BTN_SUPPORT", "🎫 تیکت پشتیبانی"))
def support_btn(m: types.Message):
    kb = types.InlineKeyboardMarkup()
    for s in ["مشکل اتصال", "سوال قبل خرید", "مشکل پرداخت", "سایر"]:
        kb.add(types.InlineKeyboardButton(s, callback_data=f"topen_{s}"))
    kb.add(types.InlineKeyboardButton("🎟 تیکت‌های من", callback_data="tlist"))
    bot.send_message(m.chat.id, "یک موضوع انتخاب کنید:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("topen_"))
def ticket_open(c: types.CallbackQuery):
    subject = c.data.split("_",1)[1]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO tickets(user_id, subject) VALUES(?,?)", (c.from_user.id, subject))
    tid = cur.lastrowid
    conn.commit()
    conn.close()

    st = user_state.setdefault(c.from_user.id, {})
    st["ticket_open"] = {"ticket_id": tid}

    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"🎫 تیکت #{tid} ایجاد شد. پیام خود را ارسال کنید.")
    notify_admins(f"🎫 تیکت جدید #{tid} از {c.from_user.id} • موضوع: {subject}")

@bot.callback_query_handler(func=lambda c: c.data == "tlist")
def ticket_list(c: types.CallbackQuery):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 20", (c.from_user.id,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "تیکتی ندارید.")
        return
    txt = "🎟 تیکت‌های شما:\n"
    for t in rows:
        txt += f"#{t['id']} • {t['subject']} • {t['status']}\n"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt)

# ========= ACCOUNT =========
@bot.message_handler(func=lambda x: x.text == get_setting("BTN_MY", "👤 حساب کاربری"))
def my_account(m: types.Message):
    uid = m.from_user.id
    bal = wallet_balance(uid)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) as cnt FROM orders WHERE user_id=?", (uid,))
    cnt = cur.fetchone()["cnt"]
    conn.close()

    txt = f"👤 آیدی: <code>{uid}</code>\n@{m.from_user.username or '-'}\n🪙 موجودی: <b>{bal}T</b>\n🛍 تعداد کانفیگ خریداری‌شده: <b>{cnt}</b>"
    bot.send_message(m.chat.id, txt)

# ========= ADMIN =========
@bot.message_handler(func=lambda x: x.text == get_setting("BTN_ADMIN", "👑 پنل ادمین"))
def admin_panel(m: types.Message):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "⛔ دسترسی ندارید.")
        return
    bot.send_message(m.chat.id, "پنل ادمین:", reply_markup=admin_menu())

# --- مدیریت پلن‌ها ---
@bot.message_handler(func=lambda x: x.text == "📦 مدیریت پلن‌ها")
def manage_plans(m: types.Message):
    if not is_admin(m.from_user.id):
        return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن پلن", callback_data="p_add"))
    kb.add(types.InlineKeyboardButton("📜 لیست پلن‌ها", callback_data="p_list"))
    bot.send_message(m.chat.id, "مدیریت پلن‌ها:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "p_list")
def p_list_cb(c: types.CallbackQuery):
    rows = list_plans_with_stock()
    if not rows:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "پلنی موجود نیست.")
        return
    txt = "📜 پلن‌ها:\n"
    for p in rows:
        txt += f"#{p['id']} • {p['name']} • {p['price']}T • {p['days']}روز • موجودی:{p['stock']} • {'فعال' if p['active'] else 'غیرفعال'}\n"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt)

@bot.callback_query_handler(func=lambda c: c.data == "p_add")
def p_add_cb(c: types.CallbackQuery):
    st = user_state.setdefault(c.from_user.id, {})
    st["add_plan"] = {"step": 1}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "نام پلن را بفرستید:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_plan", {}).get("step") == 1)
def p_add_name(m: types.Message):
    st = user_state[m.from_user.id]["add_plan"]
    st["name"] = m.text.strip()
    st["step"] = 2
    bot.reply_to(m, "مدت (روز) را بفرستید:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_plan", {}).get("step") == 2)
def p_add_days(m: types.Message):
    st = user_state[m.from_user.id]["add_plan"]
    try:
        st["days"] = int(m.text.strip())
    except:
        bot.reply_to(m, "عدد صحیح بفرستید.")
        return
    st["step"] = 3
    bot.reply_to(m, "حجم (GB) را بفرستید:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_plan", {}).get("step") == 3)
def p_add_volume(m: types.Message):
    st = user_state[m.from_user.id]["add_plan"]
    try:
        st["volume_gb"] = float(m.text.strip())
    except:
        bot.reply_to(m, "عدد معتبر بفرستید.")
        return
    st["step"] = 4
    bot.reply_to(m, "قیمت (T) را بفرستید:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_plan", {}).get("step") == 4)
def p_add_price(m: types.Message):
    st = user_state[m.from_user.id]["add_plan"]
    try:
        st["price"] = int(m.text.strip())
    except:
        bot.reply_to(m, "عدد صحیح بفرستید.")
        return
    st["step"] = 5
    bot.reply_to(m, "توضیحات پلن:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_plan", {}).get("step") == 5)
def p_add_desc(m: types.Message):
    st = user_state[m.from_user.id]["add_plan"]
    st["description"] = m.text.strip()
    # ذخیره
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO plans(name, days, volume_gb, price, description, active)
        VALUES(?,?,?,?,?,1)
    """, (st["name"], st["days"], st["volume_gb"], st["price"], st["description"]))
    conn.commit()
    conn.close()
    bot.reply_to(m, "پلن ثبت شد ✅")
    user_state[m.from_user.id].pop("add_plan", None)

# --- مدیریت مخزن ---
@bot.message_handler(func=lambda x: x.text == "📂 مدیریت مخزن")
def manage_inventory(m: types.Message):
    if not is_admin(m.from_user.id):
        return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن کانفیگ به پلن", callback_data="inv_add"))
    kb.add(types.InlineKeyboardButton("📦 وضعیت مخزن", callback_data="inv_list"))
    bot.send_message(m.chat.id, "مدیریت مخزن:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "inv_list")
def inv_list_cb(c: types.CallbackQuery):
    rows = list_plans_with_stock()
    if not rows:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "پلنی موجود نیست.")
        return
    txt = "📦 وضعیت مخزن:\n"
    for p in rows:
        txt += f"{p['name']}: {p['stock']} کانفیگ آماده\n"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt)

@bot.callback_query_handler(func=lambda c: c.data == "inv_add")
def inv_add_cb(c: types.CallbackQuery):
    st = user_state.setdefault(c.from_user.id, {})
    st["add_inv"] = {"step": 1}
    bot.answer_callback_query(c.id)
    # انتخاب پلن
    kb = types.InlineKeyboardMarkup()
    for p in list_plans_with_stock():
        kb.add(types.InlineKeyboardButton(p["name"], callback_data=f"ainv_plan_{p['id']}"))
    bot.send_message(c.message.chat.id, "برای افزودن کانفیگ، یک پلن انتخاب کنید:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ainv_plan_"))
def achoose_plan_for_inv(c: types.CallbackQuery):
    pid = int(c.data.split("_")[-1])
    st = user_state.setdefault(c.from_user.id, {})
    ai = st.setdefault("add_inv", {})
    ai["plan_id"] = pid
    ai["step"] = 2
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "متن کانفیگ را بفرستید (بعداً می‌توانید عکس هم بفرستید).")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_inv", {}).get("step") == 2)
def inv_add_text(m: types.Message):
    st = user_state[m.from_user.id]["add_inv"]
    st["text"] = m.text
    st["step"] = 3
    bot.reply_to(m, "اگر تصویر هم دارید، همین الآن ارسال کنید؛ وگرنه بنویسید «تمام».")

@bot.message_handler(content_types=['photo', 'text'])
def inv_add_image_or_finish(m: types.Message):
    # این هندلر عمومی است؛ با دقت تشخیص بدیم در فلوی افزودن کانفیگ هستیم
    st = user_state.get(m.from_user.id, {}).get("add_inv")
    if not st or st.get("step") != 3:
        return  # اجازه بده سایر هندلرها عمل کنند (این یکی فقط برای state خاصه)

    photo_id = None
    if m.photo:
        photo_id = m.photo[-1].file_id
        # ذخیره و پایان
    elif (m.text or "").strip() != "تمام":
        # هنوز تمام نشده؛ شاید متن اضافه‌ای فرستاده، اما ما فقط یک عکس یا کلمه «تمام» می‌خواهیم
        bot.reply_to(m, "اگر تصویری ندارید، کلمه «تمام» را بفرستید.")
        return

    # ذخیره در مخزن
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO inventory(plan_id, text, image_file_id, used)
        VALUES(?,?,?,0)
    """, (st["plan_id"], st.get("text"), photo_id))
    conn.commit()
    conn.close()

    user_state[m.from_user.id].pop("add_inv", None)
    bot.reply_to(m, "کانفیگ به مخزن افزوده شد ✅")

# --- رسیدها ---
@bot.message_handler(func=lambda x: x.text == "🧾 رسیدها")
def receipts_admin(m: types.Message):
    if not is_admin(m.from_user.id):
        return
    show_inbox(m.chat.id)

def show_inbox(chat_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM receipts WHERE status='pending' ORDER BY id ASC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        bot.send_message(chat_id, "صندوق رسیدها خالی است.")
        return
    for r in rows:
        txt = f"🧾 #{r['id']} • {r['kind']}\nکاربر: {r['user_id']}\nانتظار: {r['expected'] or '-'}T\nپلن: {r['plan_id'] or '-'}\nکد: {r['coupon_code'] or '-'}\nیادداشت: {r['note'] or '-'}"
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton(f"✅ تایید #{r['id']}", callback_data=f"rc_ok_{r['id']}"),
            types.InlineKeyboardButton(f"❌ رد #{r['id']}", callback_data=f"rc_no_{r['id']}")
        )
        if r["photo_file_id"]:
            try:
                bot.send_photo(chat_id, r["photo_file_id"], caption=txt, reply_markup=kb)
                continue
            except:
                pass
        bot.send_message(chat_id, txt, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rc_ok_") or c.data.startswith("rc_no_"))
def receipt_action(c: types.CallbackQuery):
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "دسترسی ندارید.", show_alert=True)
        return
    parts = c.data.split("_")
    action = parts[1]
    rid = int(parts[2])

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM receipts WHERE id=?", (rid,))
    r = cur.fetchone()
    if not r:
        conn.close()
        bot.answer_callback_query(c.id, "یافت نشد.")
        return
    if r["status"] != "pending":
        conn.close()
        bot.answer_callback_query(c.id, "رسید قبلاً رسیدگی شده.")
        return

    if action == "no":
        cur.execute("UPDATE receipts SET status='rejected', reviewed_at=?, reviewer_id=? WHERE id=?", (datetime.utcnow().isoformat(), c.from_user.id, rid))
        conn.commit()
        conn.close()
        bot.answer_callback_query(c.id, "رد شد.")
        bot.send_message(r["user_id"], f"⛔ رسید #{rid} رد شد. اگر فکر می‌کنید اشتباه است، با پشتیبانی در تماس باشید.")
        return

    # Approve → درخواست مبلغ
    conn.close()
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"✅ مقدار تایید برای رسید #{rid} را بفرستید (عدد T):")
    st = user_state.setdefault(c.from_user.id, {})
    st["await_rc_amount"] = {"rid": rid}

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and user_state.get(m.from_user.id, {}).get("await_rc_amount"))
def rc_amount_enter(m: types.Message):
    st = user_state[m.from_user.id]["await_rc_amount"]
    rid = st["rid"]
    try:
        amount = int(m.text.strip())
    except:
        bot.reply_to(m, "عدد صحیح بفرستید.")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM receipts WHERE id=?", (rid,))
    r = cur.fetchone()
    if not r or r["status"] != "pending":
        conn.close()
        bot.reply_to(m, "رسید یافت نشد یا رسیدگی شده.")
        user_state[m.from_user.id].pop("await_rc_amount", None)
        return

    # ثبت تایید
    cur.execute("UPDATE receipts SET status='approved', amount=?, reviewed_at=?, reviewer_id=? WHERE id=?", (amount, datetime.utcnow().isoformat(), m.from_user.id, rid))
    conn.commit()
    conn.close()

    # اعمال اثر: wallet یا purchase
    if r["kind"] == "wallet":
        wallet_add(r["user_id"], amount)
        bot.send_message(r["user_id"], f"✅ شارژ کیف پول شما تایید شد. مبلغ: <b>{amount}T</b>\nموجودی جدید: <b>{wallet_balance(r['user_id'])}T</b>")
    else:
        # خرید کانفیگ: تحویل خودکار
        # اگر plan_id None بود (شارژ جهت خرید از مسیر دیگر)، کاری نکنیم
        if r["plan_id"]:
            plan = get_plan(int(r["plan_id"]))
            if not plan:
                bot.send_message(r["user_id"], "⛔ خطا در پلن. با پشتیبانی تماس بگیرید.")
            else:
                # محاسبه نهایی با توجه به expected (ممکنه ادمین کمتر/بیشتر تایید کند)
                price = int(plan["price"])
                coupon = r["coupon_code"]
                percent = 0
                if coupon:
                    percent, _ = validate_coupon(coupon, plan["id"])
                final = r["expected"] or max(0, price - (price * percent // 100))
                # اگر مبلغ تاییدشده >= مبلغ نهایی باشد، تحویل
                if amount >= final:
                    ok = create_order_and_deliver(r["user_id"], plan["id"], price, percent, final, coupon)
                    if ok:
                        bot.send_message(r["user_id"], f"✅ خرید شما تایید شد و کانفیگ ارسال شد.")
                    else:
                        bot.send_message(r["user_id"], "⛔ موجودی مخزن کافی نیست. لطفاً با پشتیبانی در تماس باشید.")
                else:
                    bot.send_message(r["user_id"], f"⛔ مبلغ تاییدشده کمتر از مبلغ نهایی است. لطفاً مابه‌التفاوت را واریز کنید.")
        else:
            # وقتی رسید خرید بوده ولی plan_id تنظیم نشده
            bot.send_message(r["user_id"], "✅ رسید خرید تایید شد.")

    user_state[m.from_user.id].pop("await_rc_amount", None)
    try:
        show_inbox(m.chat.id)
    except:
        pass

# --- کیف‌پول (ادمین) ---
@bot.message_handler(func=lambda x: x.text == "🪙 کیف پول (ادمین)")
def wallet_admin(m: types.Message):
    if not is_admin(m.from_user.id):
        return
    bot.send_message(m.chat.id, "دستورات:\n/add_balance <user_id> <amount>\n/sub_balance <user_id> <amount>")

@bot.message_handler(commands=['add_balance','sub_balance'])
def wallet_admin_cmd(m: types.Message):
    if not is_admin(m.from_user.id):
        return
    parts = m.text.split()
    if len(parts) != 3:
        bot.reply_to(m, "فرمت: /add_balance 123 50")
        return
    uid = int(parts[1]); amt = int(parts[2])
    if m.text.startswith("/add_balance"):
        wallet_add(uid, amt)
        bot.reply_to(m, f"✅ {amt}T به کیف پول {uid} افزوده شد.")
    else:
        ok = wallet_subtract(uid, amt)
        bot.reply_to(m, "✅ کسر شد." if ok else "⛔ موجودی کافی نیست.")

# --- کد تخفیف ---
@bot.message_handler(func=lambda x: x.text == "🏷 کد تخفیف")
def coupon_admin(m: types.Message):
    if not is_admin(m.from_user.id): return
    bot.send_message(m.chat.id, "دستورات:\n/add_coupon\n/list_coupons\n/toggle_coupon CODE\n/del_coupon CODE")

@bot.message_handler(commands=['add_coupon'])
def add_coupon_cmd(m: types.Message):
    if not is_admin(m.from_user.id): return
    st = user_state.setdefault(m.from_user.id, {})
    st["add_coupon"] = {"step": 1}
    bot.reply_to(m, "کد (مثلاً OFF20) را بفرستید:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_coupon", {}).get("step") == 1)
def add_coupon_code(m: types.Message):
    st = user_state[m.from_user.id]["add_coupon"]
    st["code"] = m.text.strip().upper()
    st["step"] = 2
    bot.reply_to(m, "درصد تخفیف (0..100):")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_coupon", {}).get("step") == 2)
def add_coupon_percent(m: types.Message):
    st = user_state[m.from_user.id]["add_coupon"]
    try:
        p = int(m.text.strip()); assert 0 <= p <= 100
    except:
        bot.reply_to(m, "درصد نامعتبر.")
        return
    st["percent"] = p
    st["step"] = 3
    bot.reply_to(m, "محدود به پلن خاص؟ آیدی پلن یا «همه»:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_coupon", {}).get("step") == 3)
def add_coupon_plan(m: types.Message):
    st = user_state[m.from_user.id]["add_coupon"]
    plan_id = None
    if m.text.strip() != "همه":
        try:
            plan_id = int(m.text.strip())
        except:
            bot.reply_to(m, "آیدی یا «همه».")
            return
    st["plan_id"] = plan_id
    st["step"] = 4
    bot.reply_to(m, "تاریخ انقضا (YYYY-MM-DD) یا «بدون»:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_coupon", {}).get("step") == 4)
def add_coupon_exp(m: types.Message):
    st = user_state[m.from_user.id]["add_coupon"]
    exp = None
    if m.text.strip() != "بدون":
        try:
            dt = datetime.strptime(m.text.strip(), "%Y-%m-%d")
            exp = datetime(dt.year, dt.month, dt.day).isoformat()
        except:
            bot.reply_to(m, "فرمت تاریخ نادرست.")
            return
    st["expires_at"] = exp
    st["step"] = 5
    bot.reply_to(m, "سقف تعداد استفاده یا «بدون»:")

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("add_coupon", {}).get("step") == 5)
def add_coupon_max(m: types.Message):
    st = user_state[m.from_user.id]["add_coupon"]
    max_uses = None
    if m.text.strip() != "بدون":
        try:
            max_uses = int(m.text.strip())
        except:
            bot.reply_to(m, "عدد صحیح یا «بدون».")
            return
    # ذخیره
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO coupons(code, percent, plan_id, expires_at, max_uses, active)
        VALUES(?,?,?,?,?,1)
    """, (st["code"], st["percent"], st["plan_id"], st["expires_at"], max_uses))
    conn.commit()
    conn.close()
    bot.reply_to(m, "کد تخفیف ثبت شد ✅")
    user_state[m.from_user.id].pop("add_coupon", None)

@bot.message_handler(commands=['list_coupons'])
def list_coupons_cmd(m: types.Message):
    if not is_admin(m.from_user.id): return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM coupons ORDER BY id DESC LIMIT 50")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(m, "لیستی وجود ندارد.")
        return
    txt = "🏷 کدها:\n"
    for r in rows:
        txt += f"{r['code']} • {r['percent']}% • plan:{r['plan_id'] or 'همه'} • used:{r['used_count']}/{r['max_uses'] or '∞'} • {'فعال' if r['active'] else 'غیرفعال'}\n"
    bot.reply_to(m, txt)

@bot.message_handler(commands=['toggle_coupon'])
def toggle_coupon_cmd(m: types.Message):
    if not is_admin(m.from_user.id): return
    parts = m.text.split()
    if len(parts) != 2:
        bot.reply_to(m, "فرمت: /toggle_coupon CODE")
        return
    code = parts[1].upper()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE coupons SET active=1-active WHERE code=?", (code,))
    if cur.rowcount == 0:
        txt = "یافت نشد."
    else:
        txt = "تغییر وضعیت انجام شد."
    conn.commit()
    conn.close()
    bot.reply_to(m, txt)

@bot.message_handler(commands=['del_coupon'])
def del_coupon_cmd(m: types.Message):
    if not is_admin(m.from_user.id): return
    parts = m.text.split()
    if len(parts) != 2:
        bot.reply_to(m, "فرمت: /del_coupon CODE")
        return
    code = parts[1].upper()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM coupons WHERE code=?", (code,))
    conn.commit()
    conn.close()
    bot.reply_to(m, "حذف شد." if cur.rowcount else "پیدا نشد.")

# --- کاربران / ادمین‌ها ---
@bot.message_handler(func=lambda x: x.text == "👥 کاربران")
def users_admin(m: types.Message):
    if not is_admin(m.from_user.id): return
    bot.send_message(m.chat.id, "دستورات:\n/find_user <id_or_username>\n/top_buyers")

@bot.message_handler(commands=['find_user'])
def find_user(m: types.Message):
    if not is_admin(m.from_user.id): return
    q = m.text.split(maxsplit=1)
    if len(q) != 2:
        bot.reply_to(m, "فرمت: /find_user something")
        return
    key = q[1].strip().lstrip("@")
    conn = get_db()
    cur = conn.cursor()
    if key.isdigit():
        cur.execute("SELECT * FROM users WHERE id=?", (int(key),))
    else:
        cur.execute("SELECT * FROM users WHERE username=?", (key,))
    u = cur.fetchone()
    if not u:
        bot.reply_to(m, "پیدا نشد.")
        conn.close()
        return
    cur.execute("SELECT COUNT(1) as cnt, COALESCE(SUM(final_amount),0) as sum FROM orders WHERE user_id=?", (u["id"],))
    stat = cur.fetchone()
    conn.close()
    bot.reply_to(m, f"👤 {u['id']} @{u['username'] or '-'}\nخریدها: {stat['cnt']} • جمع پرداخت: {stat['sum']}T\nموجودی: {wallet_balance(u['id'])}T")

@bot.message_handler(commands=['top_buyers'])
def top_buyers(m: types.Message):
    if not is_admin(m.from_user.id): return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.id, u.username, COUNT(o.id) as cnt, COALESCE(SUM(o.final_amount),0) as total
        FROM orders o JOIN users u ON u.id=o.user_id
        GROUP BY u.id, u.username
        ORDER BY total DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    conn.close()
    if not rows:
        bot.reply_to(m, "هنوز سفارشی نیست.")
        return
    txt = "🏆 Top Buyers:\n"
    for r in rows:
        txt += f"{r['id']} @{r['username'] or '-'} • {r['cnt']} خرید • {r['total']}T\n"
    bot.reply_to(m, txt)

@bot.message_handler(func=lambda x: x.text == "👑 ادمین‌ها")
def admins_menu(m: types.Message):
    if not is_admin(m.from_user.id): return
    bot.send_message(m.chat.id, "دستورات:\n/add_admin <id>\n/del_admin <id>\n/list_admins")

@bot.message_handler(commands=['add_admin','del_admin','list_admins'])
def admins_cmd(m: types.Message):
    if not is_admin(m.from_user.id): return
    if m.text.startswith("/list_admins"):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM admins")
        rows = cur.fetchall()
        conn.close()
        txt = "ادمین‌ها:\n" + "\n".join([str(r["user_id"]) for r in rows]) if rows else "لیست خالی است."
        bot.reply_to(m, txt)
        return
    parts = m.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(m, "فرمت: /add_admin 123 یا /del_admin 123")
        return
    uid = int(parts[1])
    conn = get_db()
    cur = conn.cursor()
    if m.text.startswith("/add_admin"):
        cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (uid,))
        txt = "افزوده شد."
    else:
        cur.execute("DELETE FROM admins WHERE user_id=?", (uid,))
        txt = "حذف شد."
    conn.commit()
    conn.close()
    bot.reply_to(m, txt)

# --- آمار ---
@bot.message_handler(func=lambda x: x.text == "📊 آمار")
def stats_menu(m: types.Message):
    if not is_admin(m.from_user.id): return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) as c FROM users"); users = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(1) as c FROM orders"); orders = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(final_amount),0) as s FROM orders"); income = cur.fetchone()["s"]
    conn.close()
    bot.send_message(m.chat.id, f"👥 کاربران: {users}\n🧾 سفارش‌ها: {orders}\n💰 درآمد کل: {income}T")

# --- متن/دکمه‌ها ---
@bot.message_handler(func=lambda x: x.text == "🛠 متن/دکمه‌ها")
def texts_menu(m: types.Message):
    if not is_admin(m.from_user.id): return
    bot.send_message(m.chat.id, "دستورات:\n/set_text KEY VALUE\n(keys: TXT_WELCOME, BTN_SHOP, BTN_WALLET, BTN_SUPPORT, BTN_MY, BTN_ADMIN, CARD2CARD_TEXT)")

@bot.message_handler(commands=['set_text'])
def set_text_cmd(m: types.Message):
    if not is_admin(m.from_user.id): return
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(m, "فرمت: /set_text KEY VALUE")
        return
    key, val = parts[1], parts[2]
    set_setting(key, val)
    bot.reply_to(m, f"به‌روزرسانی شد: {key}")

# --- اعلان همگانی ---
@bot.message_handler(func=lambda x: x.text == "📢 اعلان همگانی")
def broadcast_menu(m: types.Message):
    if not is_admin(m.from_user.id): return
    st = user_state.setdefault(m.from_user.id, {})
    st["await_broadcast"] = True
    bot.send_message(m.chat.id, "متن اعلان را بفرستید:")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and user_state.get(m.from_user.id, {}).get("await_broadcast"))
def do_broadcast(m: types.Message):
    user_state[m.from_user.id].pop("await_broadcast", None)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users")
    ids = [r["id"] for r in cur.fetchall()]
    conn.close()
    cnt = 0
    for uid in ids:
        try:
            bot.send_message(uid, m.text)
            cnt += 1
        except:
            pass
    bot.reply_to(m, f"ارسال شد به {cnt} کاربر.")

# ========= SCHEDULER: Expiry reminders =========
def reminder_worker():
    while True:
        try:
            conn = get_db()
            cur = conn.cursor()
            now = datetime.utcnow()
            border = now + timedelta(days=3)
            cur.execute("""
                SELECT o.id, o.user_id, o.expires_at, p.name as plan_name
                FROM orders o JOIN plans p ON p.id=o.plan_id
                WHERE o.notified_3d=0 AND datetime(o.expires_at) <= datetime(?) AND datetime(o.expires_at) > datetime(?)
            """, (border.isoformat(), now.isoformat()))
            rows = cur.fetchall()
            for r in rows:
                try:
                    exp_date = r["expires_at"][:10]
                    bot.send_message(r["user_id"], f"⏰ یادآوری: اعتبار پلن <b>{r['plan_name']}</b> تا <code>{exp_date}</code> به پایان می‌رسد. برای تمدید اقدام کنید.")
                    cur.execute("UPDATE orders SET notified_3d=1 WHERE id=?", (r["id"],))
                except:
                    pass
            conn.commit()
            conn.close()
        except Exception as e:
            print("REMINDER ERROR:", e)
        time.sleep(3600)  # هر یک ساعت

threading.Thread(target=reminder_worker, daemon=True).start()

# ========= FLASK & WEBHOOK =========
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route("/health", methods=["GET"])
def health():
    return "healthy", 200

@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    else:
        abort(403)

@app.route("/setwebhook", methods=["GET"])
def setwebhook():
    if not APP_URL or not APP_URL.startswith("http"):
        return "APP_URL is not set correctly", 400
    wh = f"{APP_URL}/webhook/{BOT_TOKEN}"
    try:
        bot.remove_webhook()
        ok = bot.set_webhook(url=wh, allowed_updates=["message","callback_query"])
        return f"set_webhook: {ok} → {wh}", 200
    except Exception as e:
        return f"err: {e}", 500

# ========= RUN (for local debug only) =========
if __name__ == "__main__":
    # برای تست محلی (بدون گانیکورن): app.run(...)
    # در دپلوی، گانیکورن main:app استفاده می‌شود و وبهوک را با /setwebhook ست کن.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
