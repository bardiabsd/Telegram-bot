# main.py
# -*- coding: utf-8 -*-

import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List

from flask import Flask, request, abort
import telebot
from telebot import types

# ================= ENV & BOT =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL", "").rstrip("/")
ADMIN_IDS_ENV = os.environ.get("ADMIN_IDS", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# ادمین‌ها (می‌توانی از ADMIN_IDS هم ست کنی)
DEFAULT_ADMINS = {1743359080}
if ADMIN_IDS_ENV:
    try:
        DEFAULT_ADMINS = {int(x) for x in ADMIN_IDS_ENV.replace(" ", "").split(",") if x}
    except Exception:
        pass

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")

# ================= DB Helpers =================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    con = db()
    cur = con.cursor()

    # کاربران
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        tg_id INTEGER UNIQUE,
        username TEXT,
        is_banned INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    # تنظیمات (متن‌ها/دکمه‌ها و کانفیگ کلی)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    # پلن‌ها
    cur.execute("""
    CREATE TABLE IF NOT EXISTS plans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        days INTEGER,
        volume_gb INTEGER,
        price INTEGER,
        description TEXT,
        active INTEGER DEFAULT 1
    )""")

    # مخزن کانفیگ هر پلن
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER,
        text_config TEXT,
        image_url TEXT,
        used INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(plan_id) REFERENCES plans(id)
    )""")

    # سفارش‌ها/خریدها
    cur.execute("""
    CREATE TABLE IF NOT EXISTS purchases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan_id INTEGER,
        amount INTEGER,
        coupon_code TEXT,
        delivered INTEGER DEFAULT 0,
        delivered_at TEXT,
        expire_at TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    # کیف‌پول
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wallet(
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        updated_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    # تراکنش‌های کیف‌پول
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wallet_tx(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        kind TEXT, -- 'topup' | 'purchase' | 'admin_adj'
        note TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    # رسیدها
    cur.execute("""
    CREATE TABLE IF NOT EXISTS receipts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kind TEXT, -- 'purchase' | 'topup'
        target_plan_id INTEGER,
        expected_amount INTEGER,
        image_file_id TEXT,
        text TEXT,
        status TEXT, -- 'pending' | 'approved' | 'rejected'
        admin_note TEXT,
        created_at TEXT,
        decided_at TEXT
    )""")

    # کوپن‌ها
    cur.execute("""
    CREATE TABLE IF NOT EXISTS coupons(
        code TEXT PRIMARY KEY,
        percent INTEGER,
        plan_id INTEGER, -- nullable: برای همه
        valid_until TEXT, -- ISO
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1
    )""")

    # تیکت‌ها
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject TEXT,
        status TEXT, -- 'open' | 'closed'
        created_at TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ticket_messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER,
        from_admin INTEGER DEFAULT 0,
        text TEXT,
        created_at TEXT
    )""")

    # وضعیت‌های کاربر (FSM)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS states(
        user_id INTEGER PRIMARY KEY,
        data TEXT
    )""")

    con.commit()

    # تنظیمات پیش‌فرض اگر نبود
    if not get_setting("ui_texts"):
        defaults = {
            "main_menu_title": "سلام! به فروشگاه خوش آمدی 👋",
            "btn_buy": "📦 خرید پلن",
            "btn_wallet": "🪙 کیف پول",
            "btn_tickets": "🎫 پشتیبانی",
            "btn_account": "👤 حساب کاربری",
            "btn_admin": "🛠 پنل ادمین",
            "plans_title": "لیست پلن‌ها:",
            "no_plans": "فعلاً پلنی موجود نیست.",
            "plan_soldout": "ناموجود",
            "plan_details": "پلن: {name}\nمدت: {days} روز\nحجم: {vol} گیگ\nقیمت: {price} تومان\n{desc}",
            "buy_actions": "یک گزینه پرداخت انتخاب کن:",
            "btn_card": "💳 کارت‌به‌کارت",
            "btn_wallet_pay": "🪙 پرداخت با کیف پول",
            "btn_cancel": "❌ انصراف",
            "coupon_prompt": "کد تخفیف داری؟ بفرست یا «-» بزن برای رد شدن.",
            "coupon_ok": "✅ کد اعمال شد: {percent}%\nمبلغ جدید: {new_amount} تومان",
            "coupon_bad": "❌ کد معتبر نیست یا منقضی شده.",
            "wallet_balance": "موجودی فعلی: {amount} تومان",
            "wallet_need_more": "موجودی کافی نیست.\nمبلغ موردنیاز: {need} تومان",
            "btn_charge_diff": "شارژ همین مقدار",
            "receipt_registered": "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین…",
            "paid_and_sent": "✅ خرید شما تکمیل شد. کانفیگ ارسال شد.",
            "account_summary": "آیدی: <code>{tg_id}</code>\nیوزرنیم: @{username}\nتعداد خرید: {count}\nموجودی کیف‌پول: {balance} تومان",
            "admin_only": "این بخش مخصوص ادمین است.",
            "admin_panel": "🛠 پنل ادمین\n/approve_receipts - رسیدهای در انتظار\n/add_balance - شارژ دستی\n/edit_texts - ویرایش متن/دکمه‌ها (JSON)"
        }
        set_setting("ui_texts", json.dumps(defaults, ensure_ascii=False))

def get_setting(key: str) -> Optional[str]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row["value"] if row else None

def set_setting(key: str, value: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    con.commit()

def get_texts() -> Dict[str, str]:
    raw = get_setting("ui_texts")
    return json.loads(raw) if raw else {}

# ================= Utilities =================
def now_iso() -> str:
    return datetime.utcnow().isoformat()

def ensure_user(message) -> int:
    tg_id = message.from_user.id
    username = message.from_user.username or ""
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id=?", (tg_id,))
    row = cur.fetchone()
    if row:
        uid = row["id"]
        cur.execute("UPDATE users SET username=? WHERE id=?", (username, uid))
    else:
        cur.execute("INSERT INTO users(tg_id, username, created_at) VALUES(?,?,?)", (tg_id, username, now_iso()))
        uid = cur.lastrowid
    con.commit()
    return uid

def user_wallet(user_id: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT balance FROM wallet WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO wallet(user_id, balance, updated_at) VALUES(?,?,?)", (user_id, 0, now_iso()))
        con.commit()
        return 0
    return int(row["balance"])

def wallet_add(user_id: int, amount: int, kind: str, note: str = ""):
    con = db()
    cur = con.cursor()
    bal = user_wallet(user_id) + amount
    if bal < 0: bal = 0
    cur.execute("INSERT INTO wallet_tx(user_id, amount, kind, note, created_at) VALUES(?,?,?,?,?)",
                (user_id, amount, kind, note, now_iso()))
    cur.execute("INSERT INTO wallet(user_id, balance, updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET balance=?, updated_at=?",
                (user_id, bal, now_iso(), bal, now_iso()))
    con.commit()

def plans_with_stock() -> List[sqlite3.Row]:
    con = db()
    cur = con.cursor()
    cur.execute("""
       SELECT p.*, 
       (SELECT COUNT(*) FROM inventory i WHERE i.plan_id=p.id AND i.used=0) AS stock
       FROM plans p WHERE p.active=1 ORDER BY p.id ASC
    """)
    return cur.fetchall()

def plan_by_id(pid: int) -> Optional[sqlite3.Row]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM plans WHERE id=?", (pid,))
    return cur.fetchone()

def take_config_from_stock(pid: int) -> Optional[sqlite3.Row]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM inventory WHERE plan_id=? AND used=0 ORDER BY id ASC LIMIT 1", (pid,))
    item = cur.fetchone()
    if not item:
        return None
    cur.execute("UPDATE inventory SET used=1 WHERE id=?", (item["id"],))
    con.commit()
    return item

def create_purchase(user_id: int, pid: int, amount: int, coupon: Optional[str]) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO purchases(user_id, plan_id, amount, coupon_code, created_at) VALUES(?,?,?,?,?)",
                (user_id, pid, amount, coupon or "", now_iso()))
    con.commit()
    return cur.lastrowid

def count_user_purchases(user_id: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM purchases WHERE user_id=?", (user_id,))
    return int(cur.fetchone()["c"])

def set_state(user_id: int, data: Dict[str, Any]):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO states(user_id, data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=?",
                (user_id, json.dumps(data, ensure_ascii=False), json.dumps(data, ensure_ascii=False)))
    con.commit()

def get_state(user_id: int) -> Dict[str, Any]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT data FROM states WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return json.loads(row["data"]) if row else {}

def clear_state(user_id: int):
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM states WHERE user_id=?", (user_id,))
    con.commit()

def check_coupon(code: str, plan_id: int) -> Optional[sqlite3.Row]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM coupons WHERE code=? AND active=1", (code,))
    c = cur.fetchone()
    if not c:
        return None
    if c["plan_id"] and int(c["plan_id"]) != int(plan_id):
        return None
    if c["valid_until"]:
        if datetime.utcnow() > datetime.fromisoformat(c["valid_until"]):
            return None
    if c["max_uses"] and int(c["used_count"]) >= int(c["max_uses"]):
        return None
    return c

def use_coupon(code: str):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE coupons SET used_count=used_count+1 WHERE code=?", (code,))
    con.commit()

def is_admin(tg_id: int) -> bool:
    return tg_id in DEFAULT_ADMINS

# ================= Keyboards =================
def main_menu_kb(is_admin_flag: bool) -> types.ReplyKeyboardMarkup:
    t = get_texts()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row1 = [types.KeyboardButton(t.get("btn_buy", "📦 خرید پلن")),
            types.KeyboardButton(t.get("btn_wallet", "🪙 کیف پول"))]
    row2 = [types.KeyboardButton(t.get("btn_tickets", "🎫 پشتیبانی")),
            types.KeyboardButton(t.get("btn_account", "👤 حساب کاربری"))]
    kb.add(*row1)
    kb.add(*row2)
    if is_admin_flag:
        kb.add(types.KeyboardButton(t.get("btn_admin", "🛠 پنل ادمین")))
    return kb

def plans_kb() -> types.InlineKeyboardMarkup:
    t = get_texts()
    kb = types.InlineKeyboardMarkup()
    for p in plans_with_stock():
        name = p["name"]
        stock = int(p["stock"])
        label = f"{name} ({stock})" if stock > 0 else f"{name} - {t.get('plan_soldout','ناموجود')}"
        cb = f"plan:{p['id']}" if stock > 0 else f"noop:{p['id']}"
        kb.add(types.InlineKeyboardButton(label, callback_data=cb))
    return kb

def buy_actions_kb(pid: int) -> types.InlineKeyboardMarkup:
    t = get_texts()
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(t.get("btn_card", "💳 کارت‌به‌کارت"), callback_data=f"paycard:{pid}"))
    kb.add(types.InlineKeyboardButton(t.get("btn_wallet_pay", "🪙 پرداخت با کیف پول"), callback_data=f"paywallet:{pid}"))
    kb.add(types.InlineKeyboardButton(t.get("btn_cancel", "❌ انصراف"), callback_data="cancel"))
    return kb

# ================= User Flow =================
@bot.message_handler(commands=["start"])
def start_cmd(m):
    init_db()
    uid = ensure_user(m)
    t = get_texts()
    kb = main_menu_kb(is_admin(m.from_user.id))
    bot.send_message(m.chat.id, t.get("main_menu_title", "سلام!"), reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == get_texts().get("btn_buy", "📦 خرید پلن"))
def buy_entry(m):
    t = get_texts()
    plist = plans_with_stock()
    if not plist:
        bot.send_message(m.chat.id, t.get("no_plans", "فعلاً پلنی موجود نیست."))
        return
    bot.send_message(m.chat.id, t.get("plans_title", "پلن‌ها:"), reply_markup=types.ReplyKeyboardRemove())
    bot.send_message(m.chat.id, "👇 یکی را انتخاب کن:", reply_markup=plans_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan:") or c.data.startswith("noop:"))
def on_plan_select(c):
    if c.data.startswith("noop:"):
        bot.answer_callback_query(c.id, "این پلن ناموجود است.")
        return
    pid = int(c.data.split(":")[1])
    p = plan_by_id(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن موجود نیست.")
        return
    t = get_texts()
    txt = t.get("plan_details", "").format(
        name=p["name"], days=p["days"], vol=p["volume_gb"], price=p["price"], desc=p["description"] or ""
    )
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    bot.send_message(c.message.chat.id, txt)
    # درخواست کوپن
    bot.send_message(c.message.chat.id, t.get("coupon_prompt", "کد تخفیف داری؟"), reply_markup=types.ForceReply(selective=False))
    # ذخیره وضعیت
    st = {"await_coupon_for_plan": pid}
    set_state(c.from_user.id, st)

@bot.message_handler(func=lambda m: bool(get_state(m.from_user.id).get("await_coupon_for_plan")))
def on_coupon_message(m):
    st = get_state(m.from_user.id)
    pid = int(st["await_coupon_for_plan"])
    p = plan_by_id(pid)
    t = get_texts()
    code = (m.text or "").strip()
    final_amount = int(p["price"])
    applied = None
    if code and code != "-":
        c = check_coupon(code, pid)
        if c:
            percent = int(c["percent"])
            final_amount = max(0, final_amount * (100 - percent) // 100)
            applied = c["code"]
            bot.reply_to(m, t.get("coupon_ok", "✅ کد اعمال شد").format(percent=percent, new_amount=final_amount))
        else:
            bot.reply_to(m, t.get("coupon_bad", "❌ کد معتبر نیست."))
    # ذخیره وضعیت پرداخت
    st = {
        "selected_plan": pid,
        "final_amount": final_amount,
        "coupon": applied
    }
    set_state(m.from_user.id, st)
    bot.send_message(m.chat.id, t.get("buy_actions", "روش پرداخت:"), reply_markup=buy_actions_kb(pid))

@bot.callback_query_handler(func=lambda c: c.data.startswith("paywallet:") or c.data.startswith("paycard:") or c.data=="cancel")
def on_pay_action(c):
    t = get_texts()
    if c.data == "cancel":
        clear_state(c.from_user.id)
        bot.answer_callback_query(c.id, "لغو شد.")
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
        bot.send_message(c.message.chat.id, "به منوی اصلی برگشتی.", reply_markup=main_menu_kb(is_admin(c.from_user.id)))
        return

    pid = int(c.data.split(":")[1])
    st = get_state(c.from_user.id)
    final_amount = int(st.get("final_amount", 0)) or int(plan_by_id(pid)["price"])
    coupon = st.get("coupon")

    if c.data.startswith("paywallet:"):
        uid = ensure_user(c.message)
        bal = user_wallet(uid)
        if bal >= final_amount:
            # کسر و تحویل
            wallet_add(uid, -final_amount, "purchase", f"plan:{pid}")
            deliver_config(uid, c.message.chat.id, pid, final_amount, coupon)
            clear_state(c.from_user.id)
            bot.answer_callback_query(c.id, "پرداخت از کیف‌پول انجام شد.")
            bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
        else:
            need = final_amount - bal
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(t.get("btn_charge_diff", "شارژ همین مقدار"), callback_data=f"charge:{need}:{pid}"))
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id,
                             t.get("wallet_need_more", "کمبود موجودی").format(need=need))
            bot.send_message(c.message.chat.id, t.get("wallet_balance", "موجودی: {amount}").format(amount=bal), reply_markup=kb)
    else:
        # کارت به کارت -> ثبت رسید
        st["await_receipt"] = {"kind": "purchase", "plan_id": pid, "expected": final_amount, "coupon": coupon}
        set_state(c.from_user.id, st)
        bot.answer_callback_query(c.id, "رسید کارت‌به‌کارت را ارسال کنید (عکس یا متن).")
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)

@bot.callback_query_handler(func=lambda c: c.data.startswith("charge:"))
def on_charge_diff(c):
    _, need, pid = c.data.split(":")
    need = int(need)
    st = get_state(c.from_user.id)
    st["await_receipt"] = {"kind": "topup", "plan_id": int(pid), "expected": need, "coupon": st.get("coupon")}
    set_state(c.from_user.id, st)
    bot.answer_callback_query(c.id, "رسید واریز را ارسال کنید.")

# دریافت رسید (عکس یا متن)
@bot.message_handler(content_types=["photo", "text"], func=lambda m: bool(get_state(m.from_user.id).get("await_receipt")))
def on_receipt(m):
    uid = ensure_user(m)
    st = get_state(m.from_user.id)
    info = st["await_receipt"]
    kind = info["kind"]
    pid = int(info.get("plan_id") or 0)
    expected = int(info.get("expected") or 0)
    coupon = info.get("coupon")

    image_file_id = None
    text = None
    if m.content_type == "photo":
        image_file_id = m.photo[-1].file_id
        text = (m.caption or "").strip()
    else:
        text = (m.text or "").strip()

    con = db()
    cur = con.cursor()
    cur.execute("""INSERT INTO receipts(user_id, kind, target_plan_id, expected_amount, image_file_id, text, status, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (uid, kind, pid, expected, image_file_id, text, "pending", now_iso()))
    rid = cur.lastrowid
    con.commit()

    # اطلاع به ادمین‌ها
    for admin_id in DEFAULT_ADMINS:
        try:
            cap = f"رسید جدید #{rid}\nنوع: {('خرید کانفیگ' if kind=='purchase' else 'شارژ کیف پول')}\nمبلغ مورد انتظار: {expected} تومان\nاز: @{m.from_user.username or '-'} ({m.from_user.id})"
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("✅ تأیید", callback_data=f"rc_ok:{rid}"))
            kb.add(types.InlineKeyboardButton("❌ رد", callback_data=f"rc_no:{rid}"))
            if image_file_id:
                bot.send_photo(admin_id, image_file_id, caption=cap, reply_markup=kb)
            else:
                bot.send_message(admin_id, cap + (f"\nمتن: {text}" if text else ""), reply_markup=kb)
        except Exception:
            pass

    clear_state(m.from_user.id)
    bot.reply_to(m, get_texts().get("receipt_registered", "رسید ثبت شد؛ منتظر تأیید ادمین…"))

# تأیید/رد رسید توسط ادمین
@bot.callback_query_handler(func=lambda c: c.data.startswith("rc_ok:") or c.data.startswith("rc_no:"))
def on_receipt_admin(c):
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, get_texts().get("admin_only", "ادمین نیستی"))
        return
    rid = int(c.data.split(":")[1])
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM receipts WHERE id=?", (rid,))
    r = cur.fetchone()
    if not r or r["status"] != "pending":
        bot.answer_callback_query(c.id, "یافت نشد یا بررسی شده.")
        return

    status = "approved" if c.data.startswith("rc_ok:") else "rejected"
    cur.execute("UPDATE receipts SET status=?, decided_at=? WHERE id=?", (status, now_iso(), rid))
    con.commit()

    # اقدام بر اساس نوع
    if status == "approved":
        uid = int(r["user_id"])
        chat_id = int(r["user_id"])
        if r["kind"] == "topup":
            wallet_add(uid, int(r["expected_amount"]), "topup", f"receipt:{rid}")
            bot.answer_callback_query(c.id, "شارژ شد.")
            bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
            # اطلاع به کاربر
            try:
                bot.send_message(chat_id, "✅ شارژ کیف پول تأیید شد.")
            except Exception:
                pass
        else:
            # purchase
            pid = int(r["target_plan_id"])
            final = int(r["expected_amount"])
            deliver_config(uid, chat_id, pid, final, None)
            bot.answer_callback_query(c.id, "خرید تأیید و ارسال شد.")
            bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    else:
        bot.answer_callback_query(c.id, "رسید رد شد.")
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
        try:
            bot.send_message(int(r["user_id"]), "❌ رسید رد شد. در صورت نیاز با پشتیبانی در تماس باشید.")
        except Exception:
            pass

# تحویل کانفیگ و ثبت خرید
def deliver_config(user_id: int, chat_id: int, plan_id: int, amount: int, coupon: Optional[str]):
    p = plan_by_id(plan_id)
    item = take_config_from_stock(plan_id)
    if not item:
        bot.send_message(chat_id, "❗️ موجودی این پلن تمام شد. لطفاً با پشتیبانی تماس بگیرید.")
        return
    pur_id = create_purchase(user_id, plan_id, amount, coupon)
    # محاسبه تاریخ انقضا
    expire = datetime.utcnow() + timedelta(days=int(p["days"]))
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE purchases SET delivered=1, delivered_at=?, expire_at=? WHERE id=?",
                (now_iso(), expire.isoformat(), pur_id))
    con.commit()
    # ارسال
    if item["image_url"]:
        try:
            bot.send_photo(chat_id, item["image_url"], caption=item["text_config"] or "")
        except Exception:
            bot.send_message(chat_id, item["text_config"] or "")
    else:
        bot.send_message(chat_id, item["text_config"] or "")
    bot.send_message(chat_id, get_texts().get("paid_and_sent", "✅ خرید شما تکمیل شد."))

# =============== Wallet / Tickets / Account ===============
@bot.message_handler(func=lambda m: m.text == get_texts().get("btn_wallet", "🪙 کیف پول"))
def wallet_menu(m):
    uid = ensure_user(m)
    bal = user_wallet(uid)
    bot.send_message(m.chat.id, get_texts().get("wallet_balance", "موجودی: {amount}").format(amount=bal))

@bot.message_handler(func=lambda m: m.text == get_texts().get("btn_tickets", "🎫 پشتیبانی"))
def tickets_menu(m):
    uid = ensure_user(m)
    st = {"await_ticket_subject": True}
    set_state(m.from_user.id, st)
    bot.send_message(m.chat.id, "موضوع تیکت را بنویس:", reply_markup=types.ForceReply(selective=False))

@bot.message_handler(func=lambda m: bool(get_state(m.from_user.id).get("await_ticket_subject")))
def ticket_subject(m):
    uid = ensure_user(m)
    subject = (m.text or "").strip()
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO tickets(user_id, subject, status, created_at) VALUES(?,?,?,?)",
                (uid, subject, "open", now_iso()))
    tid = cur.lastrowid
    con.commit()
    clear_state(m.from_user.id)
    bot.reply_to(m, f"تیکت #{tid} ایجاد شد. پیام خود را در ادامه همین گفتگو بنویسید (ادمین پاسخ خواهد داد).")

@bot.message_handler(func=lambda m: m.text == get_texts().get("btn_account", "👤 حساب کاربری"))
def account_menu(m):
    uid = ensure_user(m)
    bal = user_wallet(uid)
    cnt = count_user_purchases(uid)
    bot.send_message(m.chat.id, get_texts().get("account_summary", "").format(
        tg_id=m.from_user.id, username=m.from_user.username or "-", count=cnt, balance=bal
    ))

# ================= Admin =================
@bot.message_handler(func=lambda m: m.text == get_texts().get("btn_admin", "🛠 پنل ادمین"))
def admin_panel(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, get_texts().get("admin_only", "ادمین نیستی"))
        return
    bot.send_message(m.chat.id, get_texts().get("admin_panel", "پنل ادمین"))

@bot.message_handler(commands=["approve_receipts"])
def approve_list(m):
    if not is_admin(m.from_user.id):
        return
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM receipts WHERE status='pending' ORDER BY id ASC LIMIT 20")
    rows = cur.fetchall()
    if not rows:
        bot.reply_to(m, "رسیدی در انتظار نیست.")
        return
    for r in rows:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ تأیید", callback_data=f"rc_ok:{r['id']}"))
        kb.add(types.InlineKeyboardButton("❌ رد", callback_data=f"rc_no:{r['id']}"))
        txt = f"#{r['id']} | نوع: {r['kind']} | مبلغ: {r['expected_amount']} | کاربر: {r['user_id']}"
        if r["image_file_id"]:
            bot.send_photo(m.chat.id, r["image_file_id"], caption=txt, reply_markup=kb)
        else:
            if r["text"]:
                txt += f"\nمتن: {r['text']}"
            bot.send_message(m.chat.id, txt, reply_markup=kb)

@bot.message_handler(commands=["add_balance"])
def add_balance_cmd(m):
    if not is_admin(m.from_user.id):
        return
    bot.reply_to(m, "فرمت: /add_balance <user_tg_id> <amount>", reply=False)

@bot.message_handler(regexp=r"^/add_balance\s+(\d+)\s+(-?\d+)$")
def add_balance_apply(m):
    if not is_admin(m.from_user.id):
        return
    parts = m.text.split()
    tg = int(parts[1]); amount = int(parts[2])
    # یافتن user_id
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id=?", (tg,))
    row = cur.fetchone()
    if not row:
        bot.reply_to(m, "کاربر یافت نشد.")
        return
    uid = int(row["id"])
    wallet_add(uid, amount, "admin_adj", f"by:{m.from_user.id}")
    bot.reply_to(m, "انجام شد.")

@bot.message_handler(commands=["edit_texts"])
def edit_texts(m):
    if not is_admin(m.from_user.id):
        return
    current = json.dumps(get_texts(), ensure_ascii=False, indent=2)
    bot.send_message(m.chat.id, "JSON فعلی متن/دکمه‌ها:\n<pre>"+telebot.util.escape(current)+"</pre>")
    set_state(m.from_user.id, {"await_texts_json": True})
    bot.send_message(m.chat.id, "نسخهٔ ویرایش‌شده را ارسال کن (کل JSON).", reply_markup=types.ForceReply(selective=False))

@bot.message_handler(func=lambda m: bool(get_state(m.from_user.id).get("await_texts_json")))
def on_texts_json(m):
    if not is_admin(m.from_user.id):
        return
    try:
        data = json.loads(m.text)
        assert isinstance(data, dict)
        set_setting("ui_texts", json.dumps(data, ensure_ascii=False))
        clear_state(m.from_user.id)
        bot.reply_to(m, "ذخیره شد ✅")
    except Exception as e:
        bot.reply_to(m, f"ارور در JSON: {e}")

# ================= Webhook & Flask =================
@app.route("/", methods=["GET"])
def index():
    return "OK"

@app.route("/health", methods=["GET"])
def health():
    return "healthy"

@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    if not APP_URL:
        return "APP_URL env not set", 400
    url = f"{APP_URL}/webhook"
    s = bot.set_webhook(url=url, max_connections=40, allowed_updates=["message","callback_query"])
    return f"set_webhook={s} to {url}"

@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

# ================= Gunicorn entry =================
if __name__ == "__main__":
    init_db()
    if APP_URL:
        try:
            bot.set_webhook(url=f"{APP_URL}/webhook", max_connections=40)
        except Exception:
            pass
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
