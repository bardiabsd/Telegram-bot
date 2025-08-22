# ================== main.py (Full) ==================
# -*- coding: utf-8 -*-
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

# ========== ENV & BOT ==========
# از ENV بخوان؛ اگر نبود از مقادیر پیش‌فرض استفاده کن
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
APP_URL   = os.environ.get("APP_URL")   or "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"
ADMIN_IDS_ENV = os.environ.get("ADMIN_IDS")  # مثلا: "111,222"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env is missing and no fallback provided")

# ادمین پیش‌فرض (قابل مدیریت داخل ربات)
DEFAULT_ADMINS = {1743359080}
if ADMIN_IDS_ENV:
    try:
        DEFAULT_ADMINS = {int(x) for x in ADMIN_IDS_ENV.replace(" ", "").split(",") if x}
    except Exception:
        pass

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
WEBHOOK_URL = f"{APP_URL}/webhook/{BOT_TOKEN}"

# ========== Flask App ==========
app = Flask(__name__)

# ========== DB ==========
DB_PATH = "bot.db"
LOCK = threading.Lock()

def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_banned INTEGER DEFAULT 0,
            created_at TEXT
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY
        )""")
        # دکمه‌ها و متون قابل ویرایش
        cur.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        # کیف پول
        cur.execute("""CREATE TABLE IF NOT EXISTS wallets(
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )""")
        # رسیدها
        cur.execute("""CREATE TABLE IF NOT EXISTS receipts(
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            kind TEXT,            -- 'purchase' یا 'wallet'
            amount INTEGER,       -- در صورت wallet
            status TEXT,          -- 'pending','approved','rejected'
            plan_id INTEGER,      -- در صورت purchase
            image_file_id TEXT,
            created_at TEXT
        )""")
        # پلن‌ها
        cur.execute("""CREATE TABLE IF NOT EXISTS plans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            days INTEGER,
            size_gb REAL,
            price INTEGER,
            description TEXT,
            enabled INTEGER DEFAULT 1
        )""")
        # مخزن هر پلن (متن+عکس)
        cur.execute("""CREATE TABLE IF NOT EXISTS inventory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            text_cfg TEXT,
            image_file_id TEXT
        )""")
        # خریدها
        cur.execute("""CREATE TABLE IF NOT EXISTS purchases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_id INTEGER,
            price_paid INTEGER,
            coupon_code TEXT,
            delivered_at TEXT,
            expire_at TEXT
        )""")
        # کدهای تخفیف
        cur.execute("""CREATE TABLE IF NOT EXISTS coupons(
            code TEXT PRIMARY KEY,
            percent INTEGER,
            plan_id INTEGER,      -- null یعنی همه پلن‌ها
            expire_at TEXT,
            max_use INTEGER,      -- سقف استفاده
            used INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        )""")
        # تیکت‌ها
        cur.execute("""CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            status TEXT,     -- open/closed
            created_at TEXT
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS ticket_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            from_admin INTEGER,    -- 0 کاربر / 1 ادمین
            text TEXT,
            created_at TEXT
        )""")
        # دکمه‌های اصلی (فعال/غیرفعال)
        cur.execute("""CREATE TABLE IF NOT EXISTS buttons(
            key TEXT PRIMARY KEY,      -- buy,wallet,ticket,account,admin
            title TEXT,
            enabled INTEGER DEFAULT 1
        )""")
        # متون آماده
        cur.execute("""CREATE TABLE IF NOT EXISTS texts(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        # کارت به کارت
        cur.execute("""CREATE TABLE IF NOT EXISTS bank(
            key TEXT PRIMARY KEY,
            value TEXT
        )""")

        # پیش‌فرض‌ها
        cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (list(DEFAULT_ADMINS)[0],))

        defaults_buttons = {
            "buy": "خرید پلن 🛒",
            "wallet": "کیف پول 🌍",
            "ticket": "تیکت پشتیبانی 🎫",
            "account": "حساب کاربری 👤",
            "admin": "پنل ادمین 🛠"
        }
        for k,v in defaults_buttons.items():
            cur.execute("INSERT OR IGNORE INTO buttons(key,title,enabled) VALUES (?,?,1)", (k,v))

        default_texts = {
            "welcome": "سلام! به ربات خوش اومدی 👋\nاز دکمه‌های زیر استفاده کن.",
            "card_number": "شماره کارت: <b>****-****-****-****</b>\nبه نام: ....\nبعد از واریز، رسید را ارسال کنید.",
            "wallet_help": "موجودی کیف پول و تاریخچه را اینجا می‌بینی.",
            "ticket_hint": "موضوع تیکت را انتخاب کن و پیام‌ت را بنویس.",
        }
        for k,v in default_texts.items():
            cur.execute("INSERT OR IGNORE INTO texts(key,value) VALUES (?,?)", (k,v))

        cur.execute("INSERT OR IGNORE INTO bank(key,value) VALUES('card_number','---- ---- ---- ----')")
        con.commit()

init_db()

# ========== HELPERS ==========
def fa_to_en_digits(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return s.translate(trans).replace(",", "").replace("٬", "").strip()

def now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def get_setting(key: str, default: str = "") -> str:
    with db() as con:
        cur = con.cursor()
        row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def set_setting(key: str, value: str):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
        con.commit()

def get_text(key: str, default="") -> str:
    with db() as con:
        row = con.execute("SELECT value FROM texts WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def set_text(key: str, value: str):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO texts(key,value) VALUES(?,?)", (key,value))
        con.commit()

def is_admin(uid: int) -> bool:
    with db() as con:
        r = con.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone()
        return bool(r)

def add_admin(uid: int):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (uid,))
        con.commit()

def remove_admin(uid: int):
    with db() as con:
        con.execute("DELETE FROM admins WHERE user_id=?", (uid,))
        con.commit()

def user_row(message) -> Tuple[int, str, str]:
    uid = message.from_user.id
    uname = message.from_user.username or "-"
    fname = message.from_user.first_name or "-"
    with db() as con:
        con.execute("""INSERT OR IGNORE INTO users(id,username,first_name,created_at)
                    VALUES(?,?,?,?)""", (uid, uname, fname, now_str()))
        con.execute("""UPDATE users SET username=?, first_name=? WHERE id=?""", (uname, fname, uid))
        con.commit()
    return uid, uname, fname

def get_wallet(uid: int) -> int:
    with db() as con:
        con.execute("INSERT OR IGNORE INTO wallets(user_id,balance) VALUES(?,0)", (uid,))
        row = con.execute("SELECT balance FROM wallets WHERE user_id=?", (uid,)).fetchone()
        return row["balance"] if row else 0

def set_wallet(uid: int, new_balance: int):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO wallets(user_id,balance) VALUES(?,0)", (uid,))
        con.execute("UPDATE wallets SET balance=? WHERE user_id=?", (new_balance, uid))
        con.commit()

def inc_wallet(uid: int, delta: int):
    bal = get_wallet(uid) + delta
    set_wallet(uid, bal)

def main_menu(uid: int) -> types.ReplyKeyboardMarkup:
    with db() as con:
        rows = con.execute("SELECT * FROM buttons").fetchall()
    keys = {r["key"]: (r["title"], r["enabled"]) for r in rows}
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # ردیف‌های مرتب
    row1 = []
    if keys["buy"][1]:    row1.append(keys["buy"][0])
    if keys["wallet"][1]: row1.append(keys["wallet"][0])
    if row1: kb.row(*row1)

    row2 = []
    if keys["ticket"][1]:  row2.append(keys["ticket"][0])
    if keys["account"][1]: row2.append(keys["account"][0])
    if row2: kb.row(*row2)

    if is_admin(uid) and keys["admin"][1]:
        kb.row(keys["admin"][0])
    return kb

def kb_cancel() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
    return kb

def fmt_money(v: int) -> str:
    return f"{v:,}".replace(",", "٬")

# ========== STATES ==========
# کل state ها در RAM
STATE: Dict[int, Dict[str, Any]] = {}

def set_state(uid: int, **kwargs):
    STATE[uid] = STATE.get(uid, {})
    STATE[uid].update(kwargs)

def clear_state(uid: int):
    STATE.pop(uid, None)

# ========== WEBHOOK ==========
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return ""
    else:
        abort(403)

@app.route("/")
def index():
    return "OK"

# ========== BOOT: SET WEBHOOK ==========
def set_webhook_once():
    try:
        bot.delete_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"{now_str()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print(f"{now_str()} | ERROR | Failed to set webhook: {e}")

threading.Thread(target=set_webhook_once, daemon=True).start()

# ========== SCHEDULER: Expiry reminders ==========
def schedule_reminders():
    while True:
        try:
            with db() as con:
                # 3 روز مانده به انقضا
                t = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
                rows = con.execute("""SELECT p.user_id, u.username, p.expire_at, pl.name
                                      FROM purchases p
                                      JOIN users u ON u.id=p.user_id
                                      JOIN plans pl ON pl.id=p.plan_id
                                      WHERE p.expire_at BETWEEN ? AND datetime(?, '+1 minutes')""", (t, t)).fetchall()
            for r in rows:
                try:
                    bot.send_message(r["user_id"], f"⏰ یادآوری: پلن «{r['name']}» تا ۳ روز دیگر منقضی می‌شود. برای تمدید از بخش خرید پلن اقدام کنید.")
                except:
                    pass
        except:
            pass
        time.sleep(60)

threading.Thread(target=schedule_reminders, daemon=True).start()

# ========== USER HANDLERS ==========
@bot.message_handler(content_types=['text', 'photo', 'document'])
def on_message(msg: types.Message):
    uid, uname, fname = user_row(msg)

    # اگر state منتظر ورودی متنی/عددی باشد
    st = STATE.get(uid) or {}

    # انصراف با کیبورد اصلی
    if msg.text and msg.text.strip() == "انصراف":
        clear_state(uid)
        bot.send_message(uid, "عملیات لغو شد.", reply_markup=main_menu(uid))
        return

    # --- مسیرهای state ---
    if st.get("await") == "admin_add":
        val = fa_to_en_digits(msg.text or "")
        if val.isdigit():
            new_id = int(val)
            add_admin(new_id)
            clear_state(uid)
            bot.send_message(uid, f"✅ ادمین {new_id} اضافه شد.", reply_markup=main_menu(uid))
        else:
            bot.send_message(uid, "آیدی عددی معتبر نیست. دوباره ارسال کنید یا «انصراف».")
        return

    if st.get("await") == "admin_remove":
        val = fa_to_en_digits(msg.text or "")
        if val.isdigit():
            rid = int(val)
            remove_admin(rid)
            clear_state(uid)
            bot.send_message(uid, f"✅ ادمین {rid} حذف شد.", reply_markup=main_menu(uid))
        else:
            bot.send_message(uid, "آیدی عددی معتبر نیست. دوباره ارسال کنید یا «انصراف».")
        return

    if st.get("await") == "edit_text_key":
        # مرحله 2: دریافت متن جدید
        key = st.get("text_key")
        set_text(key, msg.text or "")
        clear_state(uid)
        bot.send_message(uid, "✅ متن بروزرسانی شد.", reply_markup=main_menu(uid))
        return

    if st.get("await") == "create_coupon_percent":
        val = fa_to_en_digits(msg.text or "")
        if val.isdigit() and 1 <= int(val) <= 100:
            set_state(uid, await="create_coupon_plan", coupon={"percent": int(val)})
            bot.send_message(uid, "برای کدام پلن؟\n0 = همه پلن‌ها\nیا آیدی پلن را بفرست.", reply_markup=kb_cancel())
        else:
            bot.send_message(uid, "درصد معتبر نیست (۱ تا ۱۰۰).")
        return

    if st.get("await") == "create_coupon_plan":
        v = fa_to_en_digits(msg.text or "0")
        plan_id = None
        if v.isdigit():
            if int(v) != 0:
                plan_id = int(v)
        else:
            bot.send_message(uid, "آیدی پلن یا 0 را بفرست.")
            return
        st["coupon"]["plan_id"] = plan_id
        set_state(uid, await="create_coupon_exp", coupon=st["coupon"])
        bot.send_message(uid, "تاریخ انقضا به روز: مثلا 2025-12-31", reply_markup=kb_cancel())
        return

    if st.get("await") == "create_coupon_exp":
        date_str = (msg.text or "").strip()
        try:
            if date_str:
                _ = datetime.strptime(date_str, "%Y-%m-%d")
            st["coupon"]["expire_at"] = date_str if date_str else None
            set_state(uid, await="create_coupon_cap", coupon=st["coupon"])
            bot.send_message(uid, "سقف تعداد استفاده (عدد) یا 0 برای نامحدود:", reply_markup=kb_cancel())
        except:
            bot.send_message(uid, "فرمت تاریخ معتبر نیست. مثل 2025-12-31")
        return

    if st.get("await") == "create_coupon_cap":
        val = fa_to_en_digits(msg.text or "0")
        if not val.isdigit():
            bot.send_message(uid, "فقط عدد بفرست.")
            return
        cap = int(val)
        st["coupon"]["max_use"] = None if cap == 0 else cap
        set_state(uid, await="create_coupon_code", coupon=st["coupon"])
        bot.send_message(uid, "کد/نام کوپن:", reply_markup=kb_cancel())
        return

    if st.get("await") == "create_coupon_code":
        code = (msg.text or "").strip().upper()
        c = st.get("coupon", {})
        with db() as con:
            try:
                con.execute("""INSERT INTO coupons(code,percent,plan_id,expire_at,max_use,enabled,used)
                               VALUES(?,?,?,?,?,1,0)""",
                            (code, c.get("percent"), c.get("plan_id"), c.get("expire_at"), c.get("max_use")))
                con.commit()
                bot.send_message(uid, f"✅ کد «{code}» ساخته شد.", reply_markup=main_menu(uid))
            except Exception as e:
                bot.send_message(uid, f"❌ خطا: {e}")
        clear_state(uid)
        return

    if st.get("await") == "add_plan_name":
        st["plan"] = {"name": msg.text.strip()}
        set_state(uid, await="add_plan_days", plan=st["plan"])
        bot.send_message(uid, "مدت (روز):", reply_markup=kb_cancel())
        return

    if st.get("await") == "add_plan_days":
        val = fa_to_en_digits(msg.text or "")
        if val.isdigit():
            st["plan"]["days"] = int(val)
            set_state(uid, await="add_plan_size", plan=st["plan"])
            bot.send_message(uid, "حجم (GB):", reply_markup=kb_cancel())
        else:
            bot.send_message(uid, "فقط عدد بفرست.")
        return

    if st.get("await") == "add_plan_size":
        val = fa_to_en_digits(msg.text or "")
        try:
            gb = float(val)
            st["plan"]["size_gb"] = gb
            set_state(uid, await="add_plan_price", plan=st["plan"])
            bot.send_message(uid, "قیمت (تومان):", reply_markup=kb_cancel())
        except:
            bot.send_message(uid, "عدد صحیح/اعشاری معتبر بفرست.")
        return

    if st.get("await") == "add_plan_price":
        val = fa_to_en_digits(msg.text or "")
        if val.isdigit():
            st["plan"]["price"] = int(val)
            set_state(uid, await="add_plan_desc", plan=st["plan"])
            bot.send_message(uid, "توضیحات پلن:", reply_markup=kb_cancel())
        else:
            bot.send_message(uid, "فقط عدد بفرست.")
        return

    if st.get("await") == "add_plan_desc":
        st["plan"]["description"] = msg.text or ""
        p = st["plan"]
        with db() as con:
            con.execute("""INSERT INTO plans(name,days,size_gb,price,description,enabled)
                           VALUES(?,?,?,?,?,1)""",
                        (p["name"], p["days"], p["size_gb"], p["price"], p["description"]))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, "✅ پلن اضافه شد.", reply_markup=main_menu(uid))
        return

    if st.get("await") == "inventory_add_plan":
        val = fa_to_en_digits(msg.text or "")
        if val.isdigit():
            st["inv"] = {"plan_id": int(val)}
            set_state(uid, await="inventory_text", inv=st["inv"])
            bot.send_message(uid, "متن کانفیگ (اختیاری)، سپس اگر عکس هم داری بفرست. در پایان «انصراف» را نزن!", reply_markup=kb_cancel())
        else:
            bot.send_message(uid, "آیدی پلن عددی بفرست.")
        return

    # اگر در حالت دریافت متن کانفیگ هستیم و عکس هم ممکن است بیاید
    if st.get("await") == "inventory_text":
        inv = st.get("inv", {})
        text_cfg = ""
        image_id = None
        if msg.content_type == 'photo':
            image_id = msg.photo[-1].file_id
        elif msg.text:
            text_cfg = msg.text

        with db() as con:
            con.execute("INSERT INTO inventory(plan_id,text_cfg,image_file_id) VALUES(?,?,?)",
                        (inv["plan_id"], text_cfg, image_id))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, "✅ آیتم به مخزن افزوده شد.", reply_markup=main_menu(uid))
        return

    if st.get("await") == "wallet_approve_amount":
        # ادمین مقدار شارژ را وارد می‌کند
        rid = st.get("receipt_id")
        val = fa_to_en_digits(msg.text or "")
        if val.isdigit():
            amount = int(val)
            with db() as con:
                r = con.execute("SELECT * FROM receipts WHERE id=? AND status='pending'", (rid,)).fetchone()
                if not r:
                    clear_state(uid)
                    bot.send_message(uid, "رسید یافت نشد یا قبلاً بررسی شده.", reply_markup=main_menu(uid))
                    return
                # افزایش موجودی
                inc_wallet(r["user_id"], amount)
                con.execute("UPDATE receipts SET status='approved', amount=? WHERE id=?", (amount, rid))
                con.commit()
            clear_state(uid)
            bot.send_message(uid, f"✅ {fmt_money(amount)} تومان به کیف پول کاربر اضافه شد.", reply_markup=main_menu(uid))
            try:
                bot.send_message(r["user_id"], f"✅ شارژ کیف پول شما به مبلغ {fmt_money(amount)} تومان تایید شد.")
            except: pass
        else:
            bot.send_message(uid, "فقط عدد بفرست یا «انصراف».")
        return

    if st.get("await") == "ticket_subject":
        subject = (msg.text or "").strip()
        with db() as con:
            con.execute("INSERT INTO tickets(user_id,subject,status,created_at) VALUES(?,?,?,?)",
                        (uid, subject, "open", now_str()))
            tid = con.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
            con.execute("""INSERT INTO ticket_messages(ticket_id,from_admin,text,created_at)
                        VALUES(?,?,?,?)""", (tid, 0, "تیکت ایجاد شد.", now_str()))
            con.commit()
        set_state(uid, await="ticket_message", ticket_id=tid)
        bot.send_message(uid, "متن پیام‌تان را بنویسید:", reply_markup=kb_cancel())
        return

    if st.get("await") == "ticket_message":
        tid = st.get("ticket_id")
        txt = msg.text or ""
        with db() as con:
            con.execute("""INSERT INTO ticket_messages(ticket_id,from_admin,text,created_at)
                           VALUES(?,?,?,?)""", (tid, 0, txt, now_str()))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, "✅ پیام شما ثبت شد. پاسخ از همین ترد ارسال می‌شود.", reply_markup=main_menu(uid))
        # اطلاع به ادمین‌ها
        with db() as con:
            admins = [r["user_id"] for r in con.execute("SELECT user_id FROM admins").fetchall()]
        for a in admins:
            try:
                bot.send_message(a, f"📩 پیام جدید در تیکت #{tid} از @{uname or uid}")
            except: pass
        return

    # ----- دکمه‌های اصلی -----
    if msg.text:
        txt = msg.text.strip()
        with db() as con:
            bts = {r["key"]: r["title"] for r in con.execute("SELECT key,title FROM buttons").fetchall()}
        if txt == bts.get("buy"):
            show_plans(uid)
            return
        if txt == bts.get("wallet"):
            open_wallet(uid)
            return
        if txt == bts.get("ticket"):
            open_ticket(uid)
            return
        if txt == bts.get("account"):
            open_account(uid)
            return
        if txt == bts.get("admin") and is_admin(uid):
            open_admin(uid)
            return

    # اگر عکس رسید فرستاده شود خارج از state خرید/شارژ
    if msg.content_type in ("photo", "document"):
        # از کاربر بپرس نوع رسید چیست
        fid = msg.photo[-1].file_id if msg.content_type=="photo" else msg.document.file_id
        rid = gen_receipt_id()
        with db() as con:
            con.execute("""INSERT INTO receipts(id,user_id,kind,amount,status,plan_id,image_file_id,created_at)
                        VALUES(?,?,?,?,?,?,?,?)""",
                        (rid, uid, "wallet", None, "pending", None, fid, now_str()))
            con.commit()
        bot.send_message(uid, f"🧾 رسید شما با شناسه <code>#{rid}</code> ثبت شد؛ منتظر تایید ادمین باشید.")
        notify_receipt_to_admins(rid)
        return

    # پیش‌فرض: منو
    bot.send_message(uid, get_text("welcome"), reply_markup=main_menu(uid))

# ========== FEATURES ==========
def show_plans(uid: int):
    with db() as con:
        plans = con.execute("SELECT * FROM plans WHERE enabled=1 ORDER BY id").fetchall()
    if not plans:
        bot.send_message(uid, "فعلاً پلنی موجود نیست.", reply_markup=main_menu(uid))
        return
    kb = types.InlineKeyboardMarkup()
    for p in plans:
        count = inv_count(p["id"])
        title = f"{p['name']} | {p['days']}روز | {p['size_gb']}GB | {fmt_money(p['price'])} تومان | موجودی: {count}"
        kb.add(types.InlineKeyboardButton(title, callback_data=f"pl_{p['id']}"))
    bot.send_message(uid, "📦 لیست پلن‌ها:", reply_markup=kb)

def inv_count(plan_id: int) -> int:
    with db() as con:
        r = con.execute("SELECT COUNT(*) c FROM inventory WHERE plan_id=?", (plan_id,)).fetchone()
        return r["c"] if r else 0

def open_wallet(uid: int):
    bal = get_wallet(uid)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("شارژ کیف پول ➕", callback_data="w_add"))
    kb.add(types.InlineKeyboardButton("تاریخچه تراکنش‌ها 🧾", callback_data="w_hist"))
    kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
    bot.send_message(uid, f"💰 موجودی فعلی: <b>{fmt_money(bal)}</b> تومان", reply_markup=kb)

def open_ticket(uid: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("ایجاد تیکت جدید ➕", callback_data="t_new"))
    kb.add(types.InlineKeyboardButton("تیکت‌های من 📂", callback_data="t_list"))
    kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
    bot.send_message(uid, "🎫 بخش تیکت:", reply_markup=kb)

def open_account(uid: int):
    with db() as con:
        u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        cnt = con.execute("SELECT COUNT(*) c FROM purchases WHERE user_id=?", (uid,)).fetchone()["c"]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("سفارش‌های من 🧩", callback_data="my_orders"))
    kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
    bot.send_message(uid, f"👤 آیدی عددی: <code>{uid}</code>\n"
                          f"یوزرنیم: @{u['username'] or '-'}\n"
                          f"تعداد کانفیگ خریداری‌شده: {cnt}", reply_markup=kb)

def open_admin(uid: int):
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("مدیریت ادمین‌ها", callback_data="a_admins"),
           types.InlineKeyboardButton("دکمه‌ها و متون", callback_data="a_texts"))
    kb.row(types.InlineKeyboardButton("پلن‌ها و مخزن", callback_data="a_plans"),
           types.InlineKeyboardButton("کدهای تخفیف", callback_data="a_coupons"))
    kb.row(types.InlineKeyboardButton("رسیدها/کیف پول", callback_data="a_receipts"),
           types.InlineKeyboardButton("کاربران", callback_data="a_users"))
    kb.row(types.InlineKeyboardButton("آمار فروش 📊", callback_data="a_stats"),
           types.InlineKeyboardButton("اعلان همگانی 📢", callback_data="a_broadcast"))
    kb.add(types.InlineKeyboardButton("بازگشت ⬅️", callback_data="cancel"))
    bot.send_message(uid, "🛠 پنل ادمین:", reply_markup=kb)

def notify_receipt_to_admins(rid: str):
    with db() as con:
        r = con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
        admins = [x["user_id"] for x in con.execute("SELECT user_id FROM admins").fetchall()]
    cap = f"#رسید {rid}\nاز: @{get_username(r['user_id'])} {r['user_id']}\nنوع: {r['kind']}\nوضعیت: {r['status']}"
    for a in admins:
        try:
            kb = types.InlineKeyboardMarkup()
            if r["kind"] == "wallet":
                kb.add(types.InlineKeyboardButton("تایید و ورود مبلغ شارژ", callback_data=f"ra_{rid}"))
            else:
                kb.add(types.InlineKeyboardButton("پرداخت کانفیگ", callback_data=f"rp_{rid}"))
            kb.add(types.InlineKeyboardButton("رد کردن", callback_data=f"rr_{rid}"))
            if r["image_file_id"]:
                bot.send_photo(a, r["image_file_id"], cap, reply_markup=kb)
            else:
                bot.send_message(a, cap, reply_markup=kb)
        except:
            pass

def gen_receipt_id() -> str:
    return hex(int(time.time()*1000))[2:]

def get_username(uid: int) -> str:
    with db() as con:
        r = con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        return r["username"] if r and r["username"] else "-"

# ========== CALLBACKS ==========
@bot.callback_query_handler(func=lambda c: True)
def on_cb(c: types.CallbackQuery):
    uid = c.from_user.id
    if c.data == "cancel":
        clear_state(uid)
        bot.edit_message_reply_markup(uid, c.message.message_id, reply_markup=None)
        bot.answer_callback_query(c.id, "لغو شد")
        bot.send_message(uid, "بازگشت به منو.", reply_markup=main_menu(uid))
        return

    # خرید پلن
    if c.data.startswith("pl_"):
        plan_id = int(c.data.split("_")[1])
        with db() as con:
            p = con.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not p:
            bot.answer_callback_query(c.id, "پلن یافت نشد")
            return
        stock = inv_count(plan_id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("کارت‌به‌کارت 🧾", callback_data=f"buy_cc_{plan_id}"))
        kb.add(types.InlineKeyboardButton("پرداخت از کیف پول 🪙", callback_data=f"buy_w_{plan_id}"))
        kb.add(types.InlineKeyboardButton("اعمال/حذف کد تخفیف 🎟", callback_data=f"buy_cp_{plan_id}"))
        kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
        text = (f"نام: <b>{p['name']}</b>\n"
                f"مدت: {p['days']} روز\n"
                f"حجم: {p['size_gb']}GB\n"
                f"قیمت: <b>{fmt_money(p['price'])}</b> تومان\n"
                f"موجودی: {stock}")
        bot.edit_message_text(text, uid, c.message.message_id, reply_markup=kb)
        return

    if c.data.startswith("buy_cp_"):
        plan_id = int(c.data.split("_")[2])
        set_state(uid, await="coupon_input", plan_id=plan_id)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "کد تخفیف را بفرست (برای حذف بنویس: 0):", reply_markup=kb_cancel())
        return

    if c.data.startswith("buy_w_"):
        plan_id = int(c.data.split("_")[2])
        process_wallet_payment(uid, plan_id, c)
        return

    if c.data.startswith("buy_cc_"):
        plan_id = int(c.data.split("_")[2])
        # نمایش شماره کارت + دکمه انصراف
        with db() as con:
            card = con.execute("SELECT value FROM bank WHERE key='card_number'").fetchone()["value"]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ارسال رسید 📷", callback_data=f"cc_send_{plan_id}"))
        kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
        bot.edit_message_text(f"{get_text('card_number')}\n\n<b>{card}</b>", uid, c.message.message_id, reply_markup=kb)
        return

    if c.data.startswith("cc_send_"):
        plan_id = int(c.data.split("_")[2])
        rid = gen_receipt_id()
        # رسید نوع خرید کانفیگ
        with db() as con:
            con.execute("""INSERT INTO receipts(id,user_id,kind,status,plan_id,created_at)
                           VALUES(?,?,?,?,?,?)""",
                        (rid, uid, "purchase", "pending", plan_id, now_str()))
            con.commit()
        set_state(uid, await="wait_receipt_image", receipt_id=rid)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "🧾 عکس رسید کارت‌به‌کارت را ارسال کنید. سپس منتظر تایید ادمین باشید.", reply_markup=kb_cancel())
        notify_receipt_to_admins(rid)
        return

    # کیف پول
    if c.data == "w_add":
        set_state(uid, await="wallet_add_how")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ارسال رسید کارت‌به‌کارت", callback_data="w_add_cc"))
        kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
        bot.edit_message_text("روش شارژ را انتخاب کن:", uid, c.message.message_id, reply_markup=kb)
        return

    if c.data == "w_add_cc":
        rid = gen_receipt_id()
        with db() as con:
            con.execute("""INSERT INTO receipts(id,user_id,kind,status,created_at)
                           VALUES(?,?,?,?,?)""", (rid, uid, "wallet", "pending", now_str()))
            con.commit()
        set_state(uid, await="wait_wallet_receipt", receipt_id=rid)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "🧾 عکس رسید را ارسال کن. بعد از تایید ادمین شارژ می‌شود.", reply_markup=kb_cancel())
        notify_receipt_to_admins(rid)
        return

    if c.data == "w_hist":
        with db() as con:
            rows = con.execute("""SELECT * FROM receipts WHERE user_id=? AND kind='wallet'
                                  ORDER BY created_at DESC LIMIT 20""", (uid,)).fetchall()
        if not rows:
            bot.answer_callback_query(c.id, "تاریخچه‌ای نیست.")
            return
        lines = []
        for r in rows:
            am = f"{fmt_money(r['amount'])}" if r["amount"] else "-"
            lines.append(f"#{r['id']} | مبلغ: {am} | وضعیت: {r['status']} | {r['created_at']}")
        bot.send_message(uid, "🧾 تاریخچه شارژ:\n" + "\n".join(lines))
        return

    if c.data == "t_new":
        set_state(uid, await="ticket_subject")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "موضوع تیکت را بنویس:", reply_markup=kb_cancel())
        return

    if c.data == "t_list":
        with db() as con:
            ts = con.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 15", (uid,)).fetchall()
        if not ts:
            bot.answer_callback_query(c.id, "تیکتی ندارید.")
            return
        kb = types.InlineKeyboardMarkup()
        for t in ts:
            kb.add(types.InlineKeyboardButton(f"#{t['id']} | {t['subject']} | {t['status']}", callback_data=f"t_{t['id']}"))
        kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
        bot.send_message(uid, "تیکت‌ها:", reply_markup=kb)
        return

    if c.data.startswith("t_"):
        tid = int(c.data.split("_")[1])
        with db() as con:
            ms = con.execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id", (tid,)).fetchall()
        text = "\n".join([("ادمین" if m["from_admin"] else "شما") + ": " + (m["text"] or "") for m in ms])
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ارسال پیام", callback_data=f"tmsg_{tid}"))
        kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
        bot.send_message(uid, f"گفتگو #{tid}:\n{text or 'پیامی نیست'}", reply_markup=kb)
        return

    if c.data.startswith("tmsg_"):
        tid = int(c.data.split("_")[1])
        set_state(uid, await="ticket_message", ticket_id=tid)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "متن پیام‌تان را بفرستید:", reply_markup=kb_cancel())
        return

    # ادمین‌ها
    if c.data == "a_admins" and is_admin(uid):
        with db() as con:
            lst = [str(r["user_id"]) for r in con.execute("SELECT user_id FROM admins").fetchall()]
        kb = types.InlineKeyboardMarkup()
        kb.row(types.InlineKeyboardButton("➕ افزودن", callback_data="adm_add"),
               types.InlineKeyboardButton("➖ حذف", callback_data="adm_remove"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="cancel"))
        bot.send_message(uid, "ادمین‌ها: " + ", ".join(lst), reply_markup=kb)
        return

    if c.data == "adm_add" and is_admin(uid):
        set_state(uid, await="admin_add")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "آیدی عددی ادمین جدید:", reply_markup=kb_cancel())
        return

    if c.data == "adm_remove" and is_admin(uid):
        set_state(uid, await="admin_remove")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "آیدی عددی برای حذف:", reply_markup=kb_cancel())
        return

    if c.data == "a_texts" and is_admin(uid):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("ویرایش متن خوشامد", callback_data="tx_welcome"))
        kb.add(types.InlineKeyboardButton("ویرایش شماره کارت", callback_data="tx_card"))
        kb.add(types.InlineKeyboardButton("روشن/خاموش دکمه‌ها", callback_data="tx_buttons"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="cancel"))
        bot.send_message(uid, "مدیریت متون و دکمه‌ها:", reply_markup=kb)
        return

    if c.data == "tx_buttons" and is_admin(uid):
        with db() as con:
            rows = con.execute("SELECT * FROM buttons").fetchall()
        kb = types.InlineKeyboardMarkup()
        for r in rows:
            st = "✅" if r["enabled"] else "🚫"
            kb.add(types.InlineKeyboardButton(f"{r['title']} [{st}]", callback_data=f"btn_{r['key']}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="cancel"))
        bot.send_message(uid, "برای تغییر وضعیت، روی هر گزینه بزن:", reply_markup=kb)
        return

    if c.data.startswith("btn_") and is_admin(uid):
        key = c.data.split("_")[1]
        with db() as con:
            r = con.execute("SELECT * FROM buttons WHERE key=?", (key,)).fetchone()
            new = 0 if r["enabled"] else 1
            con.execute("UPDATE buttons SET enabled=? WHERE key=?", (new, key))
            con.commit()
        bot.answer_callback_query(c.id, "بروزرسانی شد.")
        open_admin(uid)
        return

    if c.data == "tx_welcome" and is_admin(uid):
        set_state(uid, await="edit_text_key", text_key="welcome")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "متن جدید خوشامد:", reply_markup=kb_cancel())
        return

    if c.data == "tx_card" and is_admin(uid):
        set_state(uid, await="edit_card")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "شماره کارت جدید را بنویس:", reply_markup=kb_cancel())
        set_state(uid, await="edit_text_key", text_key="card_number")
        return

    if c.data == "a_plans" and is_admin(uid):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ افزودن پلن", callback_data="pl_add"))
        kb.add(types.InlineKeyboardButton("🧾 مدیریت مخزن", callback_data="inv_mng"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="cancel"))
        bot.send_message(uid, "مدیریت پلن‌ها:", reply_markup=kb)
        return

    if c.data == "pl_add" and is_admin(uid):
        set_state(uid, await="add_plan_name")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "نام پلن:", reply_markup=kb_cancel())
        return

    if c.data == "inv_mng" and is_admin(uid):
        set_state(uid, await="inventory_add_plan")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "آیدی پلن برای افزودن آیتم مخزن:", reply_markup=kb_cancel())
        return

    if c.data == "a_coupons" and is_admin(uid):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ ساخت کد تخفیف", callback_data="cp_new"))
        kb.add(types.InlineKeyboardButton("لیست کدها", callback_data="cp_list"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="cancel"))
        bot.send_message(uid, "مدیریت کدهای تخفیف:", reply_markup=kb)
        return

    if c.data == "cp_new" and is_admin(uid):
        set_state(uid, await="create_coupon_percent")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "درصد تخفیف (۱ تا ۱۰۰):", reply_markup=kb_cancel())
        return

    if c.data == "cp_list" and is_admin(uid):
        with db() as con:
            rows = con.execute("SELECT * FROM coupons ORDER BY code").fetchall()
        if not rows:
            bot.answer_callback_query(c.id, "کد فعالی نداریم.")
            return
        lines = []
        for r in rows:
            scope = "همه" if r["plan_id"] is None else f"پلن {r['plan_id']}"
            lines.append(f"{r['code']} | {r['percent']}% | {scope} | used {r['used']}/{r['max_use'] or '∞'} | تا {r['expire_at'] or '-'}")
        bot.send_message(uid, "لیست کدها:\n" + "\n".join(lines))
        return

    if c.data == "a_receipts" and is_admin(uid):
        with db() as con:
            rows = con.execute("SELECT * FROM receipts WHERE status='pending' ORDER BY created_at DESC LIMIT 20").fetchall()
        if not rows:
            bot.answer_callback_query(c.id, "رسید در انتظار نداریم.")
            return
        for r in rows:
            cap = f"🧾 #{r['id']} | از @{get_username(r['user_id'])} ({r['user_id']}) | نوع: {r['kind']} | وضعیت: {r['status']}"
            kb = types.InlineKeyboardMarkup()
            if r["kind"] == "wallet":
                kb.add(types.InlineKeyboardButton("تایید و ورود مبلغ شارژ", callback_data=f"ra_{r['id']}"))
            else:
                kb.add(types.InlineKeyboardButton("تایید خرید کانفیگ", callback_data=f"rp_{r['id']}"))
            kb.add(types.InlineKeyboardButton("رد", callback_data=f"rr_{r['id']}"))
            if r["image_file_id"]:
                try: bot.send_photo(uid, r["image_file_id"], cap, reply_markup=kb)
                except: bot.send_message(uid, cap, reply_markup=kb)
            else:
                bot.send_message(uid, cap, reply_markup=kb)
        return

    if c.data.startswith("ra_") and is_admin(uid):
        rid = c.data.split("_")[1]
        set_state(uid, await="wallet_approve_amount", receipt_id=rid)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "مبلغ شارژ (تومان) را وارد کنید:", reply_markup=kb_cancel())
        return

    if c.data.startswith("rp_") and is_admin(uid):
        rid = c.data.split("_")[1]
        with db() as con:
            r = con.execute("SELECT * FROM receipts WHERE id=? AND status='pending'", (rid,)).fetchone()
            if not r:
                bot.answer_callback_query(c.id, "یافت نشد/بررسی‌شده.")
                return
            # ارسال کانفیگ از مخزن
            plan_id = r["plan_id"]
            item = con.execute("SELECT * FROM inventory WHERE plan_id=? ORDER BY id LIMIT 1", (plan_id,)).fetchone()
            if not item:
                bot.answer_callback_query(c.id, "موجودی این پلن صفر است.")
                return
            # حذف از مخزن
            con.execute("DELETE FROM inventory WHERE id=?", (item["id"],))
            # قیمت نهایی همان قیمت پلن (بدون کیف پول)
            p = con.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            price_paid = p["price"]
            # تحویل و ثبت خرید
            delivered_at = now_str()
            expire_at = (datetime.utcnow() + timedelta(days=p["days"])).strftime("%Y-%m-%d %H:%M:%S")
            con.execute("""INSERT INTO purchases(user_id,plan_id,price_paid,coupon_code,delivered_at,expire_at)
                           VALUES(?,?,?,?,?,?)""", (r["user_id"], plan_id, price_paid, None, delivered_at, expire_at))
            con.execute("UPDATE receipts SET status='approved' WHERE id=?", (rid,))
            con.commit()
        # ارسال به کاربر
        try:
            if item["text_cfg"]:
                bot.send_message(r["user_id"], f"🎉 کانفیگ شما:\n{item['text_cfg']}")
            if item["image_file_id"]:
                bot.send_photo(r["user_id"], item["image_file_id"])
            bot.send_message(r["user_id"], "✅ خرید شما تایید و ارسال شد.")
        except: pass
        bot.answer_callback_query(c.id, "ارسال شد.")
        return

    if c.data.startswith("rr_") and is_admin(uid):
        rid = c.data.split("_")[1]
        with db() as con:
            r = con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
            if not r:
                bot.answer_callback_query(c.id, "یافت نشد.")
                return
            con.execute("UPDATE receipts SET status='rejected' WHERE id=?", (rid,))
            con.commit()
        try:
            bot.send_message(r["user_id"], "❌ رسید شما رد شد. در صورت مغایرت، با پشتیبانی در تماس باشید.")
        except: pass
        bot.answer_callback_query(c.id, "رد شد.")
        return

    if c.data == "a_users" and is_admin(uid):
        set_state(uid, await="user_search")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "آیدی عددی یا یوزرنیم را بفرست:", reply_markup=kb_cancel())
        return

    if STATE.get(uid, {}).get("await") == "user_search" and c.data:
        pass  # فقط برای جلوگیری از خطا

    if c.data == "a_stats" and is_admin(uid):
        with db() as con:
            r1 = con.execute("SELECT COUNT(*) c, COALESCE(SUM(price_paid),0) s FROM purchases").fetchone()
            buyers = con.execute("""SELECT u.id, u.username, COUNT(p.id) cnt, COALESCE(SUM(p.price_paid),0) sum
                                    FROM users u LEFT JOIN purchases p ON p.user_id=u.id
                                    GROUP BY u.id ORDER BY sum DESC, cnt DESC LIMIT 10""").fetchall()
        lines = [f"📊 آمار فروش:\n"
                 f"- تعداد کانفیگ فروخته‌شده: <b>{r1['c']}</b>\n"
                 f"- فروش کل: <b>{fmt_money(r1['s'])}</b> تومان\n",
                 "🏆 برترین خریداران:"]
        rank = 1
        for b in buyers:
            lines.append(f"{rank}. @{b['username'] or '-'} ({b['id']}) | خرید: {b['cnt']} | مجموع: {fmt_money(b['sum'])}")
            rank += 1
        bot.send_message(uid, "\n".join(lines))
        return

    if c.data == "a_broadcast" and is_admin(uid):
        set_state(uid, await="broadcast_text")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "متن اعلان همگانی را ارسال کنید:", reply_markup=kb_cancel())
        return

# ====== EXTRA: TEXT STATES OUTSIDE CALLBACK (ادمین) ======
@bot.message_handler(func=lambda m: STATE.get(m.from_user.id, {}).get("await") in ("user_search","broadcast_text","coupon_input","wait_receipt_image","wait_wallet_receipt"))
def on_state_text(msg: types.Message):
    uid = msg.from_user.id
    st = STATE.get(uid, {})

    if st.get("await") == "user_search":
        key = (msg.text or "").strip()
        qq = fa_to_en_digits(key)
        with db() as con:
            if qq.isdigit():
                u = con.execute("SELECT * FROM users WHERE id=?", (int(qq),)).fetchone()
            else:
                u = con.execute("SELECT * FROM users WHERE username=?", (key.replace("@",""),)).fetchone()
        if not u:
            bot.send_message(uid, "کاربر یافت نشد.")
            return
        with db() as con:
            cnt = con.execute("SELECT COUNT(*) c FROM purchases WHERE user_id=?", (u["id"],)).fetchone()["c"]
            bal = get_wallet(u["id"])
        kb = types.InlineKeyboardMarkup()
        kb.row(types.InlineKeyboardButton("➕ شارژ", callback_data=f"ua_{u['id']}"),
               types.InlineKeyboardButton("➖ کسر", callback_data=f"ud_{u['id']}"))
        kb.add(types.InlineKeyboardButton("بن/آنبن", callback_data=f"ub_{u['id']}"))
        bot.send_message(uid, f"👤 @{u['username'] or '-'} ({u['id']})\n"
                              f"خریدها: {cnt}\n"
                              f"موجودی کیف پول: {fmt_money(bal)} تومان", reply_markup=kb)
        clear_state(uid)
        return

    if st.get("await") == "broadcast_text":
        text = msg.text or ""
        sent = 0
        with db() as con:
            ids = [r["id"] for r in con.execute("SELECT id FROM users").fetchall()]
        for i in ids:
            try:
                bot.send_message(i, text)
                sent += 1
            except:
                pass
            time.sleep(0.02)
        bot.send_message(uid, f"✅ ارسال شد به {sent} کاربر.", reply_markup=main_menu(uid))
        clear_state(uid)
        return

    if st.get("await") == "coupon_input":
        code = (msg.text or "").strip().upper()
        if code == "0":
            set_setting(f"coupon_{uid}", "")
            bot.send_message(uid, "کد تخفیف حذف شد.")
            clear_state(uid)
            return
        # اعتبارسنجی
        ok, info = validate_coupon(code, st.get("plan_id"))
        if ok:
            set_setting(f"coupon_{uid}", code)
            bot.send_message(uid, f"✅ کد {code} اعمال شد ({info['percent']}%).")
        else:
            bot.send_message(uid, f"❌ کد نامعتبر است.")
        clear_state(uid)
        return

    if st.get("await") in ("wait_receipt_image","wait_wallet_receipt"):
        # باید عکس برسد؛ اگر متن آمد، نادیده
        bot.send_message(uid, "لطفاً تصویر رسید را ارسال کنید.", reply_markup=kb_cancel())
        return

@bot.message_handler(content_types=['photo'])
def on_photo_only(msg: types.Message):
    uid = msg.from_user.id
    st = STATE.get(uid, {})
    if st.get("await") == "wait_receipt_image":
        rid = st.get("receipt_id")
        fid = msg.photo[-1].file_id
        with db() as con:
            con.execute("UPDATE receipts SET image_file_id=? WHERE id=?", (fid, rid))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, f"✅ رسید شما ثبت شد. شناسه: <code>#{rid}</code>")
        notify_receipt_to_admins(rid)
        return
    if st.get("await") == "wait_wallet_receipt":
        rid = st.get("receipt_id")
        fid = msg.photo[-1].file_id
        with db() as con:
            con.execute("UPDATE receipts SET image_file_id=? WHERE id=?", (fid, rid))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, f"✅ رسید شارژ ثبت شد. شناسه: <code>#{rid}</code>")
        notify_receipt_to_admins(rid)
        return

# ========== COUPON & PAYMENTS ==========
def validate_coupon(code: str, plan_id: int) -> Tuple[bool, Optional[dict]]:
    with db() as con:
        c = con.execute("SELECT * FROM coupons WHERE code=? AND enabled=1", (code,)).fetchone()
    if not c:
        return False, None
    if c["plan_id"] is not None and c["plan_id"] != plan_id:
        return False, None
    if c["expire_at"]:
        try:
            if datetime.utcnow() > datetime.strptime(c["expire_at"], "%Y-%m-%d"):
                return False, None
        except:
            pass
    if c["max_use"] is not None and c["used"] >= c["max_use"]:
        return False, None
    return True, dict(c)

def apply_coupon(code: Optional[str], plan_price: int, plan_id: int) -> Tuple[int, Optional[str], int]:
    if not code:
        return plan_price, None, 0
    ok, c = validate_coupon(code, plan_id)
    if not ok:
        return plan_price, None, 0
    disc = (plan_price * c["percent"]) // 100
    final = max(plan_price - disc, 0)
    return final, c["code"], disc

def increase_coupon_use(code: Optional[str]):
    if not code: return
    with db() as con:
        con.execute("UPDATE coupons SET used=used+1 WHERE code=?", (code,))
        con.commit()

def process_wallet_payment(uid: int, plan_id: int, cb: types.CallbackQuery):
    with db() as con:
        p = con.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not p:
        bot.answer_callback_query(cb.id, "پلن یافت نشد.")
        return
    stock = inv_count(plan_id)
    if stock <= 0:
        bot.answer_callback_query(cb.id, "موجودی این پلن تمام شده.")
        return

    code = get_setting(f"coupon_{uid}", "")
    final_price, used_code, disc = apply_coupon(code or None, p["price"], plan_id)
    bal = get_wallet(uid)

    if bal < final_price:
        diff = final_price - bal
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"شارژ همین مقدار ({fmt_money(diff)} تومان)", callback_data="w_add"))
        kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel"))
        bot.edit_message_text(f"مبلغ نهایی: {fmt_money(final_price)} تومان\n"
                              f"موجودی کیف پول: {fmt_money(bal)}\n"
                              f"مابه‌التفاوت: <b>{fmt_money(diff)}</b>", uid, cb.message.message_id, reply_markup=kb)
        return

    # پرداخت از کیف پول
    with db() as con:
        item = con.execute("SELECT * FROM inventory WHERE plan_id=? ORDER BY id LIMIT 1", (plan_id,)).fetchone()
        if not item:
            bot.answer_callback_query(cb.id, "موجودی صفر است.")
            return
        con.execute("DELETE FROM inventory WHERE id=?", (item["id"],))
        inc_wallet(uid, -final_price)
        delivered_at = now_str()
        expire_at = (datetime.utcnow() + timedelta(days=p["days"])).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("""INSERT INTO purchases(user_id,plan_id,price_paid,coupon_code,delivered_at,expire_at)
                       VALUES(?,?,?,?,?,?)""", (uid, plan_id, final_price, used_code, delivered_at, expire_at))
        con.commit()
    increase_coupon_use(used_code)
    # ارسال کانفیگ
    if item["text_cfg"]:
        bot.send_message(uid, f"🎉 کانفیگ شما:\n{item['text_cfg']}")
    if item["image_file_id"]:
        bot.send_photo(uid, item["image_file_id"])
    bot.edit_message_text("✅ خرید با کیف پول انجام شد و کانفیگ ارسال شد.", uid, cb.message.message_id)

# ========== STARTUP GREETING ==========
@bot.message_handler(commands=['start'])
def start_cmd(msg: types.Message):
    uid, _, _ = user_row(msg)
    bot.send_message(uid, get_text("welcome"), reply_markup=main_menu(uid))

# =====================================================

if __name__ == "__main__":
    # اجرای محلی (اختیاری). در Koyeb فقط gunicorn از Procfile استفاده می‌کند.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
# ================= end of file =================
