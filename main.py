# -*- coding: utf-8 -*-
# ------------------------------------------------------------
# Telegram Shop Bot (No Wallet) - Fresh Clean Build
# - Webhook: APP_URL/webhook/<BOT_TOKEN>
# - SQLite database: bot.db
# - Default Admin: 1743359080  (قابل مدیریت داخل بات)
#
# ENV required:
#   BOT_TOKEN   -> از BotFather
#   APP_URL     -> مثل https://your-app.koyeb.app
#
# نکته: اگر خواستی توکن/URL را هاردکد کنی، می‌توانی پایین این دو خط را تغییر دهی.
# ------------------------------------------------------------
import os
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, request, abort
import telebot
from telebot import types

# ================= ENV =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
APP_URL   = os.environ.get("APP_URL", "").rstrip("/")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env is required")
if not APP_URL:
    raise RuntimeError("APP_URL env is required")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{APP_URL}{WEBHOOK_PATH}"

# ادمین پیش‌فرض:
DEFAULT_ADMINS = {1743359080}

# ================= BOT & APP ===========
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

DB = "bot.db"
LOCK = threading.Lock()

# ================= DB ==================
def db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        cur = con.cursor()
        # کاربران
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY,
          username TEXT,
          is_banned INTEGER DEFAULT 0,
          created_at TEXT
        )""")

        # ادمین‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admins(
          user_id INTEGER PRIMARY KEY
        )""")

        # پلن‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS plans(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT,
          days INTEGER,
          traffic_gb REAL,
          price INTEGER,
          desc TEXT
        )""")

        # مخزن کانفیگ‌ها (هر ردیف یک آیتم)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          plan_id INTEGER,
          cfg_text TEXT,
          photo_file_id TEXT,
          created_at TEXT
        )""")

        # کد تخفیف
        cur.execute("""
        CREATE TABLE IF NOT EXISTS coupons(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT UNIQUE,
          percent INTEGER,
          plan_id INTEGER,     -- NULL for all plans
          uses_limit INTEGER,  -- NULL = unlimited
          used_count INTEGER DEFAULT 0,
          expires_at TEXT      -- NULL = no expiry
        )""")

        # سفارش‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          plan_id INTEGER,
          price INTEGER,
          final_price INTEGER,
          coupon_code TEXT,
          status TEXT,        -- pending / paid / canceled
          created_at TEXT
        )""")

        # رسیدها (کارت به کارت)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          order_id INTEGER,
          kind TEXT,          -- purchase
          message_id INTEGER, -- msg id in bot chat (optional)
          photo_file_id TEXT,
          text TEXT,
          status TEXT,        -- pending / approved / rejected
          created_at TEXT,
          reviewed_by INTEGER,
          reviewed_at TEXT
        )""")

        # پیام/تیکت
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          subject TEXT,
          status TEXT,       -- open / closed
          created_at TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_msgs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ticket_id INTEGER,
          sender_id INTEGER,
          text TEXT,
          created_at TEXT
        )""")

        # تنظیمات (متون، شماره کارت، متن دکمه‌ها…)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings(
          key TEXT PRIMARY KEY,
          value TEXT
        )""")

        # خریدهای تحویلی (برای «کانفیگ‌های من»)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS deliveries(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          plan_id INTEGER,
          cfg_text TEXT,
          photo_file_id TEXT,
          created_at TEXT,
          expires_at TEXT     -- تاریخ پایان اعتبار (اختیاری)
        )""")

        con.commit()

        # اولین اجرا: ادمین پیش‌فرض را وارد کن
        # (اگر قبلاً نبود)
        cur.execute("SELECT COUNT(*) c FROM admins")
        if cur.fetchone()["c"] == 0:
            for a in DEFAULT_ADMINS:
                cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (a,))
            con.commit()

        # تنظیمات پیش‌فرض
        def set_default(k, v):
            cur.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, json.dumps(v)))
        set_default("texts", {
            "main_title": "به فروشگاه خوش آمدید 👋",
            "shop": "فروشگاه 🛍",
            "my_cfgs": "کانفیگ‌های من 🧾",
            "support": "پشتیبانی 🧩",
            "profile": "پروفایل من 👤",
            "admin": "پنل ادمین 🛠",
            "back": "بازگشت ◀️",
            "cancel": "انصراف ❌",
            "buy_c2c": "کارت‌به‌کارت 💳",
            "enter_coupon": "کد تخفیف 🏷️",
            "no_stock": "ناموجود",
            "send_receipt": "رسید کارت‌به‌کارت را ارسال کنید (متن یا عکس).",
            "receipt_registered": "رسید شما ثبت شد و منتظر تأیید ادمین است.",
            "receipt_approved": "پرداخت تأیید شد ✅\nکانفیگ شما ارسال شد.",
            "receipt_rejected": "پرداخت رد شد ❌\nلطفاً با پشتیبانی در ارتباط باشید.",
            "ask_subject": "موضوع تیکت را انتخاب/وارد کنید:",
            "ticket_created": "تیکت ایجاد شد. پیام خود را بنویسید:",
            "ticket_closed": "تیکت بسته شد.",
        })
        set_default("buttons", {
            "menu": ["فروشگاه 🛍", "کیف پول ❌", "کانفیگ‌های من 🧾", "پشتیبانی 🧩", "پروفایل من 👤", "پنل ادمین 🛠"],
        })
        set_default("card_number", {"number": "6037-********-****", "holder": "Your Name"})
        con.commit()

init_db()

# ------------- helpers -------------
def is_admin(uid: int) -> bool:
    with db() as con:
        r = con.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone()
        return r is not None

def set_setting(key, val_obj):
    with db() as con:
        con.execute("REPLACE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(val_obj)))
        con.commit()

def get_setting(key, default=None):
    with db() as con:
        r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not r: return default
        try:
            return json.loads(r["value"])
        except Exception:
            return default

def add_user(u: telebot.types.User):
    with db() as con:
        con.execute("""
            INSERT OR IGNORE INTO users(id, username, created_at) VALUES(?,?,?)
        """, (u.id, u.username or "", datetime.utcnow().isoformat()))
        con.execute("""
            UPDATE users SET username=? WHERE id=?
        """, (u.username or "", u.id))
        con.commit()

def kb(rows):
    markup = types.InlineKeyboardMarkup()
    for r in rows:
        markup.row(*[types.InlineKeyboardButton(t, callback_data=d) for (t,d) in r])
    return markup

def main_menu(uid):
    rows = [
        [("فروشگاه 🛍", "shop"), ("کانفیگ‌های من 🧾", "mycfgs")],
        [("پشتیبانی 🧩", "support"), ("پروفایل من 👤", "profile")],
    ]
    if is_admin(uid):
        rows.append([("پنل ادمین 🛠", "admin")])
    return kb(rows)

def fmt_money(x):
    return f"{x:,}".replace(",", "٬") + " تومان"

# -------- Plans & Stock ----------
def list_plans_with_stock():
    with db() as con:
        rows = con.execute("""
            SELECT p.*, COALESCE((SELECT COUNT(1) FROM stock s WHERE s.plan_id=p.id),0) AS stock_count
            FROM plans p ORDER BY id DESC
        """).fetchall()
    return rows

def get_plan(pid):
    with db() as con:
        return con.execute("SELECT * FROM plans WHERE id=?", (pid,)).fetchone()

def pop_stock(plan_id):
    with db() as con:
        item = con.execute("SELECT * FROM stock WHERE plan_id=? ORDER BY id LIMIT 1", (plan_id,)).fetchone()
        if not item:
            return None
        con.execute("DELETE FROM stock WHERE id=?", (item["id"],))
        con.commit()
        return item

# ================ STATES (memory) ================
# نگهداری وضعیت‌های گفت‌وگو در حافظه
STATE = {}
def set_state(uid, **kv):
    STATE[uid] = {**STATE.get(uid, {}), **kv}
def clear_state(uid):
    STATE.pop(uid, None)
def get_state(uid, k=None, default=None):
    s = STATE.get(uid, {})
    return s.get(k, default) if k else s

# ================== BOT FLOWS ====================

@bot.message_handler(commands=["start"])
def on_start(m):
    add_user(m.from_user)
    bot.send_message(m.chat.id, get_setting("texts")["main_title"], reply_markup=main_menu(m.from_user.id))

@bot.message_handler(func=lambda m: True, content_types=["text", "photo"])
def on_message(m):
    uid = m.from_user.id
    add_user(m.from_user)

    st = get_state(uid)

    # دریافت رسید در حالت خرید
    if st.get("await") == "receipt":
        # ثبت رسید
        photo_id = None
        text = None
        if m.photo:
            photo_id = m.photo[-1].file_id
            text = m.caption or ""
        else:
            text = m.text or ""

        with db() as con:
            con.execute("""
              INSERT INTO receipts(user_id, order_id, kind, message_id, photo_file_id, text, status, created_at)
              VALUES(?,?,?,?,?,?,?,?)
            """, (uid, st["order_id"], "purchase", m.message_id, photo_id, text, "pending", datetime.utcnow().isoformat()))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, get_setting("texts")["receipt_registered"], reply_markup=main_menu(uid))

        # اطلاع به ادمین‌ها
        notify_admins_new_receipt(st["order_id"], uid)
        return

    # تیکت: ایجاد/پاسخ
    if st.get("await") == "ticket_subject":
        subj = (m.text or "").strip()
        if not subj:
            bot.reply_to(m, "موضوع خالی است. دوباره بفرستید.")
            return
        with db() as con:
            con.execute("INSERT INTO tickets(user_id, subject, status, created_at) VALUES(?,?,?,?)",
                        (uid, subj, "open", datetime.utcnow().isoformat()))
            tid = con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            con.commit()
        set_state(uid, await="ticket_msg", ticket_id=tid)
        bot.send_message(uid, get_setting("texts")["ticket_created"], reply_markup=kb([[("بازگشت ◀️","back")]]))
        return

    if st.get("await") == "ticket_msg":
        txt = (m.text or (m.caption or "")).strip()
        if not txt:
            bot.reply_to(m, "پیام خالی است.")
            return
        with db() as con:
            con.execute("INSERT INTO ticket_msgs(ticket_id, sender_id, text, created_at) VALUES(?,?,?,?)",
                        (st["ticket_id"], uid, txt, datetime.utcnow().isoformat()))
            con.commit()
        bot.send_message(uid, "ارسال شد ✅", reply_markup=kb([[("بستن تیکت 🔒","ticket_close")],[("بازگشت ◀️","back")]]))
        # ارسال برای ادمین‌ها
        for a in get_admin_ids():
            if a == uid: continue
            bot.send_message(a, f"پیام جدید در تیکت #{st['ticket_id']} از <code>{uid}</code>:\n\n{txt}",
                             reply_markup=kb([[("پاسخ به کاربر","reply_ticket_"+str(st["ticket_id"]))]]))
        return

    # اگر حالت خاصی نداریم، منو را نشان بدهیم
    if m.text and m.text.startswith("/"):  # دستورات را بی‌اثر کنیم (فقط دکمه‌ای)
        return
    bot.send_message(m.chat.id, "از دکمه‌ها استفاده کنید 👇", reply_markup=main_menu(uid))

# ================ CALLBACKS ======================

def get_admin_ids():
    with db() as con:
        rows = con.execute("SELECT user_id FROM admins").fetchall()
        return [r["user_id"] for r in rows]

def notify_admins_new_receipt(order_id, user_id):
    with db() as con:
        o = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        u = con.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        p = con.execute("SELECT * FROM plans WHERE id=?", (o["plan_id"],)).fetchone()
    uname = ("@" + (u["username"] or "—")) if u else "—"
    txt = (f"🧾 رسید جدید #R{order_id}\n"
           f"از: {uname} <code>{user_id}</code>\n"
           f"پلن: {p['name'] if p else o['plan_id']}\n"
           f"مبلغ: {fmt_money(o['final_price'])}\n"
           f"وضعیت: pending")
    for a in get_admin_ids():
        bot.send_message(a, txt, reply_markup=kb([
            [("مشاهده/بررسی", f"admin_receipt_{order_id}")]
        ]))

@bot.callback_query_handler(func=lambda c: True)
def on_cb(c: types.CallbackQuery):
    uid = c.from_user.id
    add_user(c.from_user)

    data = c.data or ""
    if data == "back":
        clear_state(uid)
        bot.edit_message_text("به منوی اصلی برگشتید.", c.message.chat.id, c.message.id, reply_markup=main_menu(uid))
        return

    # ---------- Shop ----------
    if data == "shop":
        rows = list_plans_with_stock()
        if not rows:
            bot.edit_message_text("فعلاً پلنی تعریف نشده.", c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","back")]]))
            return
        keys = []
        for r in rows:
            name = f"{r['name']} — {fmt_money(r['price'])} ({'موجود: '+str(r['stock_count']) if r['stock_count']>0 else 'ناموجود'})"
            disabled = r['stock_count'] == 0
            keys.append([(("🚫 "+name) if disabled else name, f"plan_{r['id']}" if not disabled else f"noop")])
        keys.append([("بازگشت ◀️","back")])
        bot.edit_message_text("فروشگاه 🛍\nیک پلن انتخاب کنید:", c.message.chat.id, c.message.id, reply_markup=kb(keys))
        return

    if data.startswith("plan_"):
        pid = int(data.split("_")[1])
        p = get_plan(pid)
        if not p:
            bot.answer_callback_query(c.id, "پلن یافت نشد")
            return
        txt = (f"<b>{p['name']}</b>\n"
               f"مدت: {p['days']} روز\n"
               f"حجم: {int(p['traffic_gb'])} GB\n"
               f"قیمت: {fmt_money(p['price'])}\n\n"
               f"{p['desc'] or ''}")
        set_state(uid, choose_plan=pid, coupon_code=None)
        bot.edit_message_text(txt, c.message.chat.id, c.message.id, reply_markup=kb([
            [("کارت‌به‌کارت 💳", "buy_c2c"), ("کد تخفیف 🏷️","enter_coupon")],
            [("انصراف ❌","back")]
        ]))
        return

    if data == "enter_coupon":
        set_state(uid, await="coupon")
        bot.answer_callback_query(c.id, "کد تخفیف را ارسال کنید")
        bot.send_message(uid, "کد تخفیف را وارد کنید:", reply_markup=kb([[("انصراف ❌","cancel_coupon")]]))
        return

    if data == "cancel_coupon":
        st = get_state(uid)
        set_state(uid, await=None, coupon_code=None)
        bot.send_message(uid, "کد تخفیف حذف شد.", reply_markup=main_menu(uid))
        return

    if data == "buy_c2c":
        st = get_state(uid)
        pid = st.get("choose_plan")
        if not pid:
            bot.answer_callback_query(c.id, "ابتدا پلن را انتخاب کنید")
            return
        p = get_plan(pid)
        if not p:
            bot.answer_callback_query(c.id, "پلن نامعتبر")
            return
        final = p["price"]
        cc = st.get("coupon_code")
        if cc:
            ok, percent = validate_coupon(cc, pid)
            if ok:
                final = max(0, int(round(p["price"] * (100 - percent) / 100.0)))
            else:
                set_state(uid, coupon_code=None)
        # ساخت سفارش
        with db() as con:
            con.execute("""INSERT INTO orders(user_id, plan_id, price, final_price, coupon_code, status, created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (uid, pid, p["price"], final, st.get("coupon_code"), "pending", datetime.utcnow().isoformat()))
            oid = con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            con.commit()
        set_state(uid, await="receipt", order_id=oid)
        card = get_setting("card_number")
        bot.edit_message_text(
            f"مبلغ قابل پرداخت: <b>{fmt_money(final)}</b>\n\n"
            f"کارت به کارت:\n<code>{card['number']}</code>\nبه نام: {card['holder']}\n\n"
            f"{get_setting('texts')['send_receipt']}",
            c.message.chat.id, c.message.id, reply_markup=kb([[("انصراف ❌","back")]]))
        return

    if data.startswith("noop"):
        bot.answer_callback_query(c.id)
        return

    # ---------- My Configs ----------
    if data == "mycfgs":
        with db() as con:
            rows = con.execute("""
                 SELECT d.*, p.name as plan_name FROM deliveries d
                 LEFT JOIN plans p ON p.id=d.plan_id
                 WHERE d.user_id=? ORDER BY d.id DESC LIMIT 10
            """, (uid,)).fetchall()
        if not rows:
            bot.edit_message_text("هنوز کانفیگی دریافت نکردید.", c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","back")]]))
            return
        bot.edit_message_text("۱۰ کانفیگ آخر شما:", c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","back")]]))
        for r in rows:
            t = f"پلن: {r['plan_name'] or r['plan_id']}\nتاریخ: {r['created_at']}"
            if r["cfg_text"]:
                bot.send_message(uid, t + "\n\n" + f"<code>{r['cfg_text']}</code>")
            if r["photo_file_id"]:
                bot.send_photo(uid, r["photo_file_id"], caption=t)
        return

    # ---------- Support ----------
    if data == "support":
        set_state(uid, await="ticket_subject")
        bot.edit_message_text(get_setting("texts")["ask_subject"], c.message.chat.id, c.message.id,
                              reply_markup=kb([[("بازگشت ◀️","back")]]))
        return

    if data.startswith("ticket_close"):
        st = get_state(uid)
        tid = st.get("ticket_id")
        if tid:
            with db() as con:
                con.execute("UPDATE tickets SET status='closed' WHERE id=?", (tid,))
                con.commit()
            clear_state(uid)
            bot.edit_message_text(get_setting("texts")["ticket_closed"], c.message.chat.id, c.message.id, reply_markup=main_menu(uid))
        else:
            bot.answer_callback_query(c.id, "تیکت فعال ندارید.")
        return

    # ---------- Profile ----------
    if data == "profile":
        with db() as con:
            r = con.execute("SELECT COUNT(*) c FROM deliveries WHERE user_id=?", (uid,)).fetchone()
        bot.edit_message_text(f"آیدی: <code>{uid}</code>\n"
                              f"یوزرنیم: @{c.from_user.username or '—'}\n"
                              f"تعداد کانفیگ دریافتی: {r['c']}",
                              c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","back")]]))
        return

    # ---------- Admin Panel ----------
    if data == "admin":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "دسترسی ندارید")
            return
        bot.edit_message_text("پنل ادمین 🛠", c.message.chat.id, c.message.id, reply_markup=kb([
            [("پلن‌ها 📦","adm_plans"), ("مخزن 🗃️","adm_stock")],
            [("کد تخفیف 🏷️","adm_coupons"), ("ادمین‌ها 👑","adm_admins")],
            [("اعلان همگانی 📢","adm_broadcast"), ("آمار فروش 📊","adm_stats")],
            [("تنظیمات (متون/کارت) ⚙️","adm_settings")],
            [("بازگشت ◀️","back")]
        ]))
        return

    # --- Admin: Plans ---
    if data == "adm_plans":
        if not is_admin(uid): return
        rows = list_plans_with_stock()
        keys = [[(f"{r['id']} | {r['name']} ({r['stock_count']})", f"adm_plan_{r['id']}")] for r in rows]
        keys.append([("➕ افزودن پلن","adm_plan_add")])
        keys.append([("بازگشت ◀️","admin")])
        bot.edit_message_text("مدیریت پلن‌ها:", c.message.chat.id, c.message.id, reply_markup=kb(keys))
        return

    if data == "adm_plan_add":
        if not is_admin(uid): return
        set_state(uid, await="add_plan_name", plan_new={})
        bot.send_message(uid, "نام پلن را بفرستید:")
        return

    if data.startswith("adm_plan_"):
        if not is_admin(uid): return
        pid = int(data.split("_")[2])
        p = get_plan(pid)
        if not p:
            bot.answer_callback_query(c.id, "پلن یافت نشد")
            return
        bot.edit_message_text(
            f"پلن #{p['id']}\n<b>{p['name']}</b>\n{p['days']} روز | {int(p['traffic_gb'])}GB | {fmt_money(p['price'])}\n\n{p['desc'] or ''}",
            c.message.chat.id, c.message.id,
            reply_markup=kb([
                [("ویرایش ✏️", f"adm_plan_edit_{pid}"), ("حذف 🗑", f"adm_plan_del_{pid}")],
                [("بازگشت ◀️","adm_plans")]
            ]))
        return

    if data.startswith("adm_plan_edit_"):
        if not is_admin(uid): return
        pid = int(data.split("_")[3])
        set_state(uid, await="edit_plan", edit_plan_id=pid, edit_step="name")
        bot.send_message(uid, "ویرایش پلن: نام جدید را بفرستید.")
        return

    if data.startswith("adm_plan_del_"):
        if not is_admin(uid): return
        pid = int(data.split("_")[3])
        with db() as con:
            con.execute("DELETE FROM plans WHERE id=?", (pid,))
            con.execute("DELETE FROM stock WHERE plan_id=?", (pid,))
            con.commit()
        bot.answer_callback_query(c.id, "حذف شد")
        bot.edit_message_text("حذف شد.", c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","adm_plans")]]))
        return

    # --- Admin: Stock ---
    if data == "adm_stock":
        if not is_admin(uid): return
        rows = list_plans_with_stock()
        if not rows:
            bot.edit_message_text("ابتدا پلن بسازید.", c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","admin")]]))
            return
        keys = [[(f"{r['id']} | {r['name']} (موجودی: {r['stock_count']})", f"adm_stock_plan_{r['id']}")] for r in rows]
        keys.append([("بازگشت ◀️","admin")])
        bot.edit_message_text("مدیریت مخزن:", c.message.chat.id, c.message.id, reply_markup=kb(keys))
        return

    if data.startswith("adm_stock_plan_"):
        if not is_admin(uid): return
        pid = int(data.split("_")[3])
        with db() as con:
            cnt = con.execute("SELECT COUNT(*) c FROM stock WHERE plan_id=?", (pid,)).fetchone()["c"]
        bot.edit_message_text(f"مخزن پلن #{pid} | موجودی: {cnt}", c.message.chat.id, c.message.id, reply_markup=kb([
            [("➕ افزودن متن","adm_stock_addtxt_"+str(pid)), ("➕ افزودن عکس","adm_stock_addpic_"+str(pid))],
            [("🗑 حذف یکی","adm_stock_pop_"+str(pid))],
            [("بازگشت ◀️","adm_stock")]
        ]))
        return

    if data.startswith("adm_stock_addtxt_"):
        if not is_admin(uid): return
        pid = int(data.split("_")[3])
        set_state(uid, await="stock_add_text", stock_plan=pid)
        bot.send_message(uid, "متن/کانفیگ را بفرستید (به صورت متن).")
        return

    if data.startswith("adm_stock_addpic_"):
        if not is_admin(uid): return
        pid = int(data.split("_")[3])
        set_state(uid, await="stock_add_photo", stock_plan=pid)
        bot.send_message(uid, "عکس/QR کانفیگ را بفرستید (به صورت عکس).")
        return

    if data.startswith("adm_stock_pop_"):
        if not is_admin(uid): return
        pid = int(data.split("_")[3])
        it = pop_stock(pid)
        bot.answer_callback_query(c.id, "یک آیتم از مخزن حذف شد." if it else "مخزن خالی است.")
        return

    # --- Admin: Coupons ---
    if data == "adm_coupons":
        if not is_admin(uid): return
        with db() as con:
            rows = con.execute("SELECT * FROM coupons ORDER BY id DESC LIMIT 20").fetchall()
        keys = [[(f"{r['code']} | {r['percent']}% | used {r['used_count']}/{r['uses_limit'] or '∞'}", f"coupon_{r['id']}")] for r in rows]
        keys.append([("➕ ساخت کد","coupon_add")])
        keys.append([("بازگشت ◀️","admin")])
        bot.edit_message_text("کدهای تخفیف:", c.message.chat.id, c.message.id, reply_markup=kb(keys))
        return

    if data == "coupon_add":
        if not is_admin(uid): return
        set_state(uid, await="coupon_new_percent", coupon_new={})
        bot.send_message(uid, "درصد تخفیف را وارد کنید (عدد 1..100):")
        return

    if data.startswith("coupon_") and data != "coupon_add":
        if not is_admin(uid): return
        cid = int(data.split("_")[1])
        with db() as con:
            r = con.execute("SELECT * FROM coupons WHERE id=?", (cid,)).fetchone()
        if not r:
            bot.answer_callback_query(c.id, "کد یافت نشد")
            return
        txt = (f"کد: <code>{r['code']}</code>\n"
               f"درصد: {r['percent']}%\n"
               f"پلن: {r['plan_id'] or 'همه'}\n"
               f"استفاده شده: {r['used_count']}/{r['uses_limit'] or '∞'}\n"
               f"انقضا: {r['expires_at'] or 'ندارد'}")
        bot.edit_message_text(txt, c.message.chat.id, c.message.id, reply_markup=kb([
            [("🗑 حذف", f"coupon_del_{cid}")],
            [("بازگشت ◀️","adm_coupons")]
        ]))
        return

    if data.startswith("coupon_del_"):
        if not is_admin(uid): return
        cid = int(data.split("_")[2])
        with db() as con:
            con.execute("DELETE FROM coupons WHERE id=?", (cid,))
            con.commit()
        bot.answer_callback_query(c.id, "حذف شد")
        bot.edit_message_text("حذف شد.", c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","adm_coupons")]]))
        return

    # --- Admin: Admins ---
    if data == "adm_admins":
        if not is_admin(uid): return
        ids = get_admin_ids()
        keys = [[(str(a), f"adm_admin_{a}")] for a in ids]
        keys.append([("➕ افزودن ادمین","adm_admin_add")])
        keys.append([("بازگشت ◀️","admin")])
        bot.edit_message_text("ادمین‌ها:", c.message.chat.id, c.message.id, reply_markup=kb(keys))
        return

    if data == "adm_admin_add":
        if not is_admin(uid): return
        set_state(uid, await="add_admin")
        bot.send_message(uid, "آیدی عددی ادمین جدید را وارد کنید:")
        return

    if data.startswith("adm_admin_"):
        if not is_admin(uid): return
        aid = int(data.split("_")[2])
        if aid in DEFAULT_ADMINS:
            bot.answer_callback_query(c.id, "ادمین پیش‌فرض قابل حذف نیست.")
            return
        with db() as con:
            con.execute("DELETE FROM admins WHERE user_id=?", (aid,))
            con.commit()
        bot.answer_callback_query(c.id, "حذف شد.")
        return

    # --- Admin: Broadcast ---
    if data == "adm_broadcast":
        if not is_admin(uid): return
        set_state(uid, await="broadcast_text")
        bot.send_message(uid, "متن پیام همگانی را بفرستید:")
        return

    # --- Admin: Stats ---
    if data == "adm_stats":
        if not is_admin(uid): return
        with db() as con:
            s = con.execute("SELECT COUNT(*) c, COALESCE(SUM(final_price),0) sum FROM orders WHERE status='paid'").fetchone()
            buyers = con.execute("""
               SELECT u.id, u.username, COUNT(d.id) cnt
               FROM deliveries d JOIN users u ON u.id=d.user_id
               GROUP BY u.id ORDER BY cnt DESC LIMIT 5
            """).fetchall()
        txt = f"📊 آمار فروش\nتعداد فروش: {s['c']}\nمبلغ کل: {fmt_money(int(s['sum']))}\n\nخریداران برتر:\n"
        for r in buyers:
            txt += f"• <code>{r['id']}</code> @{r['username'] or '—'} — {r['cnt']} کانفیگ\n"
        bot.edit_message_text(txt, c.message.chat.id, c.message.id, reply_markup=kb([[("بازگشت ◀️","admin")]]))
        return

    # --- Admin: Settings ---
    if data == "adm_settings":
        if not is_admin(uid): return
        card = get_setting("card_number")
        bot.edit_message_text(f"تنظیمات:\nکارت: <code>{card['number']}</code> ({card['holder']})",
                              c.message.chat.id, c.message.id,
                              reply_markup=kb([
                                  [("ویرایش شماره کارت 💳","set_card")],
                                  [("ویرایش متون/دکمه‌ها ✏️","set_texts")],
                                  [("بازگشت ◀️","admin")]
                              ]))
        return

    if data == "set_card":
        if not is_admin(uid): return
        set_state(uid, await="set_card_number")
        bot.send_message(uid, "شماره کارت و نام صاحب کارت را این‌طور بفرست:\n\n6037-****-****-**** | Ali Ahmadi")
        return

    if data == "set_texts":
        if not is_admin(uid): return
        set_state(uid, await="set_texts_json")
        cur = get_setting("texts")
        bot.send_message(uid, "JSON متون را بفرست (کلیدها حفظ شوند):\n"+json.dumps(cur, ensure_ascii=False, indent=2))
        return

    # --- Admin: Review Receipt ---
    if data.startswith("admin_receipt_"):
        if not is_admin(uid): return
        oid = int(data.split("_")[2])
        with db() as con:
            o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            u = con.execute("SELECT username FROM users WHERE id=?", (o["user_id"],)).fetchone()
            p = con.execute("SELECT * FROM plans WHERE id=?", (o["plan_id"],)).fetchone()
            r = con.execute("SELECT * FROM receipts WHERE order_id=? ORDER BY id DESC LIMIT 1", (oid,)).fetchone()
        if not r:
            bot.answer_callback_query(c.id, "رسیدی برای این سفارش نیست")
            return
        txt = (f"🧾 رسید #{r['id']} برای سفارش #{oid}\n"
               f"کاربر: @{u['username'] or '—'} <code>{o['user_id']}</code>\n"
               f"پلن: {p['name'] if p else o['plan_id']}\n"
               f"مبلغ: {fmt_money(o['final_price'])}\n"
               f"وضعیت: {r['status']}")
        kbrows = [[("تأیید ✅", f"approve_{oid}_{r['id']}"), ("رد ❌", f"reject_{oid}_{r['id']}")],
                  [("بازگشت ◀️","admin")]]
        bot.edit_message_text(txt, c.message.chat.id, c.message.id, reply_markup=kb(kbrows))
        if r["photo_file_id"]:
            bot.send_photo(uid, r["photo_file_id"], caption=r["text"] or "")
        elif r["text"]:
            bot.send_message(uid, r["text"])
        return

    if data.startswith("approve_") or data.startswith("reject_"):
        if not is_admin(uid): return
        parts = data.split("_")
        action, oid, rid = parts[0], int(parts[1]), int(parts[2])
        approve = (action == "approve")
        with db() as con:
            r = con.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
            o = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            if not r or not o:
                bot.answer_callback_query(c.id, "یافت نشد")
                return
            if r["status"] != "pending":
                bot.answer_callback_query(c.id, "بررسی شده است")
                return
            # بروزرسانی رسید/سفارش
            con.execute("UPDATE receipts SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                        ("approved" if approve else "rejected", uid, datetime.utcnow().isoformat(), rid))
            if approve:
                con.execute("UPDATE orders SET status='paid' WHERE id=?", (oid,))
            else:
                con.execute("UPDATE orders SET status='canceled' WHERE id=?", (oid,))
            con.commit()

        if approve:
            # ارسال کانفیگ از مخزن
            item = pop_stock(o["plan_id"])
            if not item:
                bot.send_message(o["user_id"], "پرداخت تأیید شد اما مخزن خالی است. لطفاً با پشتیبانی تماس بگیرید.")
            else:
                with db() as con:
                    con.execute("""INSERT INTO deliveries(user_id, plan_id, cfg_text, photo_file_id, created_at, expires_at)
                                   VALUES(?,?,?,?,?,?)""",
                                (o["user_id"], o["plan_id"], item["cfg_text"], item["photo_file_id"],
                                 datetime.utcnow().isoformat(),
                                 (datetime.utcnow() + timedelta(days=get_plan(o["plan_id"])["days"])).isoformat()))
                    con.commit()
                cap = "تحویل سفارش ✅"
                if item["cfg_text"]:
                    bot.send_message(o["user_id"], cap+"\n\n<code>"+item["cfg_text"]+"</code>")
                if item["photo_file_id"]:
                    bot.send_photo(o["user_id"], item["photo_file_id"], caption=cap)
                bot.send_message(o["user_id"], get_setting("texts")["receipt_approved"])
        else:
            bot.send_message(o["user_id"], get_setting("texts")["receipt_rejected"])

        bot.answer_callback_query(c.id, "انجام شد.")
        return

# =============== TEXT INPUT STEPS (Admin & Coupon etc) ===============

@bot.message_handler(func=lambda m: True, content_types=["text","photo"])
def admin_steps(m):
    uid = m.from_user.id
    st = get_state(uid)

    # افزودن پلن (stepper)
    if st.get("await") == "add_plan_name" and is_admin(uid):
        st["plan_new"]["name"] = (m.text or "").strip()
        set_state(uid, await="add_plan_days", plan_new=st["plan_new"])
        bot.send_message(uid, "مدت (روز) را وارد کنید:")
        return
    if st.get("await") == "add_plan_days" and is_admin(uid):
        try:
            st["plan_new"]["days"] = int((m.text or "").strip())
            set_state(uid, await="add_plan_traffic", plan_new=st["plan_new"])
            bot.send_message(uid, "حجم (GB) را وارد کنید (عدد):")
        except:
            bot.send_message(uid, "عدد معتبر بفرست.")
        return
    if st.get("await") == "add_plan_traffic" and is_admin(uid):
        try:
            st["plan_new"]["traffic_gb"] = float((m.text or "").strip())
            set_state(uid, await="add_plan_price", plan_new=st["plan_new"])
            bot.send_message(uid, "قیمت (تومان) را وارد کنید (عدد):")
        except:
            bot.send_message(uid, "عدد معتبر بفرست.")
        return
    if st.get("await") == "add_plan_price" and is_admin(uid):
        try:
            st["plan_new"]["price"] = int((m.text or "").strip())
            set_state(uid, await="add_plan_desc", plan_new=st["plan_new"])
            bot.send_message(uid, "توضیح پلن را ارسال کنید (می‌تواند خالی باشد):")
        except:
            bot.send_message(uid, "عدد معتبر بفرست.")
        return
    if st.get("await") == "add_plan_desc" and is_admin(uid):
        st["plan_new"]["desc"] = (m.text or "").strip()
        with db() as con:
            con.execute("""INSERT INTO plans(name,days,traffic_gb,price,desc) VALUES(?,?,?,?,?)""",
                        (st["plan_new"]["name"], st["plan_new"]["days"], st["plan_new"]["traffic_gb"],
                         st["plan_new"]["price"], st["plan_new"]["desc"]))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, "پلن افزوده شد ✅")
        return

    # ویرایش پلن
    if st.get("await") == "edit_plan" and is_admin(uid):
        step = st.get("edit_step")
        pid  = st.get("edit_plan_id")
        val  = (m.text or "").strip()
        with db() as con:
            if step == "name":
                con.execute("UPDATE plans SET name=? WHERE id=?", (val, pid))
                nxt = "days"; bot.send_message(uid,"روز (عدد) را بفرست:")
            elif step == "days":
                try:
                    con.execute("UPDATE plans SET days=? WHERE id=?", (int(val), pid))
                    nxt = "traffic"; bot.send_message(uid,"حجم GB (عدد) را بفرست:")
                except:
                    bot.send_message(uid,"عدد معتبر بفرست.")
                    return
            elif step == "traffic":
                try:
                    con.execute("UPDATE plans SET traffic_gb=? WHERE id=?", (float(val), pid))
                    nxt = "price"; bot.send_message(uid,"قیمت (تومان) عدد:")
                except:
                    bot.send_message(uid,"عدد معتبر بفرست.")
                    return
            elif step == "price":
                try:
                    con.execute("UPDATE plans SET price=? WHERE id=?", (int(val), pid))
                    nxt = "desc"; bot.send_message(uid,"توضیح جدید:")
                except:
                    bot.send_message(uid,"عدد معتبر بفرست."); return
            elif step == "desc":
                con.execute("UPDATE plans SET desc=? WHERE id=?", (val, pid))
                nxt = None
                bot.send_message(uid,"به‌روزرسانی شد ✅")
            con.commit()
        if nxt:
            set_state(uid, await="edit_plan", edit_plan_id=pid, edit_step=nxt)
        else:
            clear_state(uid)
        return

    # افزودن به مخزن
    if st.get("await") == "stock_add_text" and is_admin(uid):
        cfg = (m.text or "").strip()
        with db() as con:
            con.execute("INSERT INTO stock(plan_id, cfg_text, photo_file_id, created_at) VALUES(?,?,?,?)",
                        (st["stock_plan"], cfg, None, datetime.utcnow().isoformat()))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, "آیتم متنی افزوده شد ✅")
        return
    if st.get("await") == "stock_add_photo" and is_admin(uid):
        if not m.photo:
            bot.send_message(uid, "باید عکس بفرستی.")
            return
        fid = m.photo[-1].file_id
        with db() as con:
            con.execute("INSERT INTO stock(plan_id, cfg_text, photo_file_id, created_at) VALUES(?,?,?,?)",
                        (st["stock_plan"], None, fid, datetime.utcnow().isoformat()))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, "عکس افزوده شد ✅")
        return

    # ساخت کد تخفیف
    if st.get("await") == "coupon_new_percent" and is_admin(uid):
        try:
            pct = int((m.text or "").strip())
            if not (1 <= pct <= 100): raise ValueError()
            st["coupon_new"]["percent"] = pct
            set_state(uid, await="coupon_new_scope", coupon_new=st["coupon_new"])
            bot.send_message(uid, "کد برای همه پلن‌ها باشد؟ بنویس: all\nیا آیدی پلن را بفرست:")
        except:
            bot.send_message(uid, "یک عدد 1..100 بفرست.")
        return
    if st.get("await") == "coupon_new_scope" and is_admin(uid):
        v = (m.text or "").strip().lower()
        if v == "all":
            st["coupon_new"]["plan_id"] = None
        else:
            try:
                st["coupon_new"]["plan_id"] = int(v)
            except:
                bot.send_message(uid, "«all» یا آیدی پلن را بفرست.")
                return
        set_state(uid, await="coupon_new_limit", coupon_new=st["coupon_new"])
        bot.send_message(uid, "حداکثر تعداد استفاده؟ عدد یا بنویس: inf")
        return
    if st.get("await") == "coupon_new_limit" and is_admin(uid):
        v = (m.text or "").strip().lower()
        uses_limit = None if v in ("inf","∞") else int(v)
        st["coupon_new"]["uses_limit"] = uses_limit
        set_state(uid, await="coupon_new_exp", coupon_new=st["coupon_new"])
        bot.send_message(uid, "تاریخ انقضا؟ (YYYY-MM-DD) یا بنویس: none")
        return
    if st.get("await") == "coupon_new_exp" and is_admin(uid):
        v = (m.text or "").strip().lower()
        exp = None
        if v != "none":
            try:
                exp = datetime.strptime(v, "%Y-%m-%d").isoformat()
            except:
                bot.send_message(uid, "فرمت تاریخ غلط است.")
                return
        st["coupon_new"]["expires_at"] = exp
        set_state(uid, await="coupon_new_code", coupon_new=st["coupon_new"])
        bot.send_message(uid, "کد (انگلیسی/عدد) را بفرست:")
        return
    if st.get("await") == "coupon_new_code" and is_admin(uid):
        code = (m.text or "").strip()
        cn = st["coupon_new"]
        with db() as con:
            con.execute("""INSERT INTO coupons(code, percent, plan_id, uses_limit, expires_at)
                           VALUES(?,?,?,?,?)""", (code, cn["percent"], cn["plan_id"], cn["uses_limit"], cn["expires_at"]))
            con.commit()
        clear_state(uid)
        bot.send_message(uid, "کد ساخته شد ✅")
        return

    # مدیریت ادمین‌ها
    if st.get("await") == "add_admin" and is_admin(uid):
        try:
            nid = int((m.text or "").strip())
            with db() as con:
                con.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (nid,))
                con.commit()
            clear_state(uid)
            bot.send_message(uid, "افزوده شد ✅")
        except:
            bot.send_message(uid, "آیدی عددی معتبر بفرست.")
        return

    # اعلان همگانی
    if st.get("await") == "broadcast_text" and is_admin(uid):
        text = (m.text or (m.caption or "")).strip()
        clear_state(uid)
        count = 0
        with db() as con:
            rows = con.execute("SELECT id FROM users WHERE is_banned=0").fetchall()
        for r in rows:
            try:
                if m.photo:
                    bot.send_photo(r["id"], m.photo[-1].file_id, caption=text)
                else:
                    bot.send_message(r["id"], text)
                count += 1
                time.sleep(0.03)
            except:
                pass
        bot.send_message(uid, f"ارسال شد به {count} نفر ✅")
        return

    # تنظیمات: کارت
    if st.get("await") == "set_card_number" and is_admin(uid):
        try:
            raw = (m.text or "").strip()
            parts = [p.strip() for p in raw.split("|", 1)]
            number = parts[0]
            holder = parts[1] if len(parts) > 1 else ""
            set_setting("card_number", {"number": number, "holder": holder})
            clear_state(uid)
            bot.send_message(uid, "ذخیره شد ✅")
        except:
            bot.send_message(uid, "فرمت ورودی نادرست بود.")
        return

    # تنظیمات: متون
    if st.get("await") == "set_texts_json" and is_admin(uid):
        try:
            obj = json.loads(m.text)
            set_setting("texts", obj)
            clear_state(uid)
            bot.send_message(uid, "ذخیره شد ✅")
        except Exception as e:
            bot.send_message(uid, f"JSON نامعتبر:\n{e}")
        return

    # کوپن برای کاربر
    if st.get("await") == "coupon":
        code = (m.text or "").strip()
        st["coupon_code"] = code
        set_state(uid, **st, await=None)
        bot.send_message(uid, "کد ثبت شد ✅", reply_markup=main_menu(uid))
        return

# ------------ Coupon validate -------------
def validate_coupon(code: str, plan_id: int):
    with db() as con:
        r = con.execute("SELECT * FROM coupons WHERE code=?", (code,)).fetchone()
        if not r:
            return (False, 0)
        # محدودیت پلن
        if r["plan_id"] and r["plan_id"] != plan_id:
            return (False, 0)
        # تاریخ انقضا
        if r["expires_at"]:
            if datetime.utcnow() > datetime.fromisoformat(r["expires_at"]):
                return (False, 0)
        # محدودیت تعداد
        if r["uses_limit"] and r["used_count"] >= r["uses_limit"]:
            return (False, 0)
        # مصرف را ثبت کن
        con.execute("UPDATE coupons SET used_count=used_count+1 WHERE id=?", (r["id"],))
        con.commit()
        return (True, r["percent"])

# ================== FLASK (Webhook) ===================

@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.data.decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

def set_webhook_once():
    try:
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print("Failed to set webhook:", e)

# ================== RUN ===================
set_webhook_once()

# برای اجرای محلی (polling) فقط برای تست:
# if __name__ == "__main__":
#     bot.infinity_polling()
