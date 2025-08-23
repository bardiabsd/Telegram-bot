# main.py
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

# ===================== ENV & DEFAULTS =====================

BOT_TOKEN = os.environ.get(
    "BOT_TOKEN",
    "8339013760:AAEgr1PBFX59xc4cFTN2fWinWHJUGWivdo"  # ← fallback: همان که قبلاً دادی
)
APP_URL = os.environ.get(
    "APP_URL",
    "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"  # ← fallback: همان که قبلاً دادی
)

DEFAULT_ADMINS = {1743359080}  # ← ادمین پیش‌فرض (خودت)

WEBHOOK_URL = f"{APP_URL}/webhook/{BOT_TOKEN}"

# ===================== BOT & APP =====================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ===================== DATABASE =====================

DB = "bot.db"
LOCK = threading.Lock()

def db():
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    cur = con.cursor()
    cur.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS wallet(
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS receipts(
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            kind TEXT,              -- 'wallet' | 'purchase'
            amount INTEGER,         -- مبلغ مورد انتظار (برای wallet) یا مبلغ نهایی خرید
            status TEXT,            -- 'pending' | 'approved' | 'rejected'
            media TEXT,             -- json: {"type": "photo|text", "file_id"|"text": ...}
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS plans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            days INTEGER,
            traffic_gb REAL,
            price INTEGER,
            description TEXT,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS inventory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            payload TEXT,           -- json: {"text": "...", "photo_id": "..."}
            delivered INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_id INTEGER,
            price INTEGER,
            coupon_code TEXT,
            delivered INTEGER DEFAULT 0,
            delivered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS coupons(
            code TEXT PRIMARY KEY,
            percent INTEGER,
            only_plan_id INTEGER,   -- NULL => همه پلن‌ها
            expire_at TEXT,         -- ISO or NULL
            max_uses INTEGER,       -- NULL => نامحدود
            used_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            status TEXT,           -- 'open' | 'closed'
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ticket_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            sender TEXT,           -- 'user' | 'admin'
            text TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS states(
            user_id INTEGER PRIMARY KEY,
            json TEXT
        );

        CREATE TABLE IF NOT EXISTS buttons_texts(
            key TEXT PRIMARY KEY,
            text TEXT,
            enabled INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            meta TEXT,
            created_at TEXT
        );
        """
    )
    con.commit()
    # ادمین پیش‌فرض
    cur.execute("SELECT COUNT(*) c FROM admins")
    if cur.fetchone()["c"] == 0:
        for aid in DEFAULT_ADMINS:
            cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (aid,))
    # دکمه‌ها و متون پیش‌فرض
    defaults = {
        "btn_buy": "خرید پلن 🛒",
        "btn_wallet": "کیف پول 🌍",
        "btn_ticket": "تیکت پشتیبانی 🎫",
        "btn_profile": "حساب کاربری 👤",
        "btn_admin": "پنل ادمین 🛠",

        "btn_wallet_charge": "شارژ کیف پول",
        "btn_wallet_history": "تاریخچه تراکنش‌ها",
        "btn_back": "بازگشت ⬅️",

        "btn_admin_plans": "مدیریت پلن‌ها",
        "btn_admin_inventory": "مخزن کانفیگ",
        "btn_admin_coupons": "کد تخفیف",
        "btn_admin_admins": "مدیریت ادمین‌ها",
        "btn_admin_receipts": "رسیدهای جدید",
        "btn_admin_broadcast": "اعلان همگانی",
        "btn_admin_texts": "دکمه‌ها و متون",
        "btn_admin_wallet": "کیف پول (ادمین)",
        "btn_admin_stats": "آمار فروش",

        "card_number": "---- ---- ---- ----"  # در پنل ادمین قابل ویرایش
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO buttons_texts(key, text) VALUES(?,?)", (k, v))
    con.commit()
    con.close()

def get_text(key: str) -> str:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT text FROM buttons_texts WHERE key=?", (key,))
    r = cur.fetchone()
    con.close()
    return r["text"] if r else key

def set_text(key: str, value: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO buttons_texts(key,text) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET text=excluded.text",
        (key, value),
    )
    con.commit()
    con.close()

def is_enabled(key: str) -> bool:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT enabled FROM buttons_texts WHERE key=?", (key,))
    r = cur.fetchone()
    con.close()
    return bool(r and r["enabled"])

def set_enabled(key: str, flag: bool):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE buttons_texts SET enabled=? WHERE key=?", (1 if flag else 0, key))
    con.commit()
    con.close()

def is_admin(uid: int) -> bool:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,))
    ok = cur.fetchone() is not None
    con.close()
    return ok

def ensure_user(message: types.Message):
    uid = message.from_user.id
    uname = message.from_user.username or ""
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(id, username, created_at) VALUES(?,?,?)",
                (uid, uname, datetime.utcnow().isoformat()))
    cur.execute("INSERT OR IGNORE INTO wallet(user_id,balance) VALUES(?,0)", (uid,))
    con.commit()
    con.close()

def get_state(uid: int) -> Dict[str, Any]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT json FROM states WHERE user_id=?", (uid,))
    r = cur.fetchone()
    con.close()
    if r and r["json"]:
        try:
            return json.loads(r["json"])
        except Exception:
            return {}
    return {}

def set_state(uid: int, **kwargs):
    st = get_state(uid)
    st.update(kwargs)
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO states(user_id,json) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET json=excluded.json",
                (uid, json.dumps(st, ensure_ascii=False)))
    con.commit()
    con.close()

def clear_state(uid: int):
    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM states WHERE user_id=?", (uid,))
    con.commit()
    con.close()

def money(n: int) -> str:
    return f"{n:,}".replace(",", "٬")

# ===================== MENUS =====================

def main_menu(uid: int) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row1 = []
    if is_enabled("btn_buy"): row1.append(get_text("btn_buy"))
    if is_enabled("btn_wallet"): row1.append(get_text("btn_wallet"))
    kb.row(*row1)
    row2 = []
    if is_enabled("btn_ticket"): row2.append(get_text("btn_ticket"))
    if is_enabled("btn_profile"): row2.append(get_text("btn_profile"))
    kb.row(*row2)
    if is_admin(uid) and is_enabled("btn_admin"):
        kb.row(get_text("btn_admin"))
    return kb

def back_menu() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(get_text("btn_back"))
    return kb

# ===================== WEBHOOK =====================

@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    abort(403)

# ===================== HELPERS =====================

def list_plans() -> List[sqlite3.Row]:
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT p.*, 
          (SELECT COUNT(*) FROM inventory i WHERE i.plan_id=p.id AND i.delivered=0) AS stock
        FROM plans p WHERE p.active=1 ORDER BY price ASC
    """)
    rows = cur.fetchall()
    con.close()
    return rows

def get_wallet(uid: int) -> int:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT balance FROM wallet WHERE user_id=?", (uid,))
    r = cur.fetchone()
    con.close()
    return r["balance"] if r else 0

def add_wallet(uid: int, amount: int, reason: str):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE wallet SET balance=balance+? WHERE user_id=?", (amount, uid))
    cur.execute("INSERT INTO logs(user_id,action,meta,created_at) VALUES(?,?,?,?)",
                (uid, "wallet_change", json.dumps({"amount": amount, "reason": reason}, ensure_ascii=False), datetime.utcnow().isoformat()))
    con.commit()
    con.close()

def consume_inventory(plan_id: int) -> Optional[Dict[str, Any]]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id, payload FROM inventory WHERE plan_id=? AND delivered=0 ORDER BY id LIMIT 1", (plan_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return None
    cur.execute("UPDATE inventory SET delivered=1 WHERE id=?", (row["id"],))
    con.commit()
    con.close()
    try:
        return json.loads(row["payload"])
    except Exception:
        return {"text": row["payload"]}

def apply_coupon(amount: int, code: Optional[str], plan_id: int) -> Tuple[int, Optional[sqlite3.Row], Optional[str]]:
    if not code:
        return amount, None, None
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM coupons WHERE code=? AND active=1", (code,))
    c = cur.fetchone()
    if not c:
        con.close()
        return amount, None, "کد تخفیف نامعتبر است."
    if c["only_plan_id"] and c["only_plan_id"] != plan_id:
        con.close()
        return amount, None, "این کد مخصوص پلن دیگری است."
    if c["expire_at"]:
        if datetime.utcnow() > datetime.fromisoformat(c["expire_at"]):
            con.close()
            return amount, None, "مهلت این کد به پایان رسیده."
    if c["max_uses"] and c["used_count"] >= c["max_uses"]:
        con.close()
        return amount, None, "سقف استفاده از این کد پر شده."
    percent = int(c["percent"])
    off = (amount * percent) // 100
    final = max(0, amount - off)
    con.close()
    return final, c, None

def increment_coupon(code: str):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE coupons SET used_count=used_count+1 WHERE code=?", (code,))
    con.commit()
    con.close()

def notify_admins(text: str):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT user_id FROM admins")
    ids = [r["user_id"] for r in cur.fetchall()]
    con.close()
    for aid in ids:
        try:
            bot.send_message(aid, text)
        except Exception:
            pass

def send_config_to_user(uid: int, payload: Dict[str, Any]):
    # ارسال کانفیگ (متن + عکس اختیاری)
    txt = payload.get("text") or ""
    photo_id = payload.get("photo_id")
    if photo_id:
        bot.send_photo(uid, photo=photo_id, caption=txt or "کانفیگ شما", reply_markup=main_menu(uid))
    else:
        bot.send_message(uid, txt or "کانفیگ شما", reply_markup=main_menu(uid))

# ===================== START / MAIN =====================

@bot.message_handler(commands=["start"])
def handle_start(message: types.Message):
    ensure_user(message)
    uid = message.from_user.id
    clear_state(uid)
    bot.send_message(
        uid,
        "سلام! خوش اومدی 🌟\nاز منوی زیر انتخاب کن:",
        reply_markup=main_menu(uid)
    )

@bot.message_handler(func=lambda m: True, content_types=["text"])
def text_router(message: types.Message):
    ensure_user(message)
    uid = message.from_user.id
    text = (message.text or "").strip()

    # منوی اصلی
    if text == get_text("btn_buy"):
        show_plans(uid)
        return
    if text == get_text("btn_wallet"):
        show_wallet(uid)
        return
    if text == get_text("btn_ticket"):
        ticket_menu(uid)
        return
    if text == get_text("btn_profile"):
        show_profile(uid)
        return
    if text == get_text("btn_admin") and is_admin(uid):
        show_admin_panel(uid)
        return

    # بازگشت
    if text == get_text("btn_back"):
        clear_state(uid)
        bot.send_message(uid, "به منوی اصلی برگشتی.", reply_markup=main_menu(uid))
        return

    # حالت‌ها (state)
    st = get_state(uid)
    await_key = st.get("await_key")

    if await_key == "charge_amount_admin":
        # ورودی عددی برای شارژ کیف پول کاربر توسط ادمین
        try:
            amount = int(text.replace(" ", ""))
            target = st.get("target_user")
            if not target:
                raise ValueError("no target")
            add_wallet(target, amount, reason="admin_charge")
            clear_state(uid)
            bot.send_message(uid, f"✅ {money(amount)} تومان به کیف پول کاربر {target} اضافه شد.", reply_markup=main_menu(uid))
            bot.send_message(target, f"🎉 کیف پول شما توسط ادمین {money(amount)} تومان شارژ شد.")
        except Exception:
            bot.send_message(uid, "لطفاً فقط عدد وارد کن (تومان).", reply_markup=back_menu())
        return

    if await_key == "enter_coupon":
        st["coupon_code"] = text.upper()
        set_state(uid, **st)
        bot.send_message(uid, "کد ثبت شد. حالا نوع پرداخت را انتخاب کن:", reply_markup=payment_menu(uid))
        return

    if await_key == "pay_by_wallet_confirm":
        # هر چیزی تایپ کند، نادیده گرفته می‌شود؛ با دکمه‌ها ادامه بده
        bot.send_message(uid, "برای ادامه از دکمه‌های زیر استفاده کن.", reply_markup=payment_menu(uid))
        return

    if await_key == "ticket_subject":
        # اجازه چند کلمه‌ای
        subj = text
        st_t = {"await_key": "ticket_text", "ticket_subject": subj}
        set_state(uid, **st_t)
        bot.send_message(uid, "متن تیکت را بنویس:", reply_markup=back_menu())
        return

    if await_key == "ticket_text":
        subject = st.get("ticket_subject", "بدون موضوع")
        con = db()
        cur = con.cursor()
        cur.execute("INSERT INTO tickets(user_id,subject,status,created_at) VALUES(?,?,?,?)",
                    (uid, subject, "open", datetime.utcnow().isoformat()))
        tid = cur.lastrowid
        cur.execute("INSERT INTO ticket_messages(ticket_id,sender,text,created_at) VALUES(?,?,?,?)",
                    (tid, "user", text, datetime.utcnow().isoformat()))
        con.commit()
        con.close()
        clear_state(uid)
        bot.send_message(uid, f"✅ تیکت #{tid} ثبت شد. از منوی «تیکت‌های من» پیگیری کن.", reply_markup=main_menu(uid))
        notify_admins(f"📩 تیکت جدید #{tid} از <code>{uid}</code>\nموضوع: {subject}")
        return

    if await_key == "admin_broadcast":
        # ارسال همگانی
        msg = text
        threading.Thread(target=broadcast_worker, args=(uid, msg), daemon=True).start()
        clear_state(uid)
        bot.send_message(uid, "در حال ارسال… گزارش نهایی برایت می‌آید.", reply_markup=main_menu(uid))
        return

    if await_key == "coupon_make_percent":
        try:
            percent = int(text)
            set_state(uid, await_key="coupon_make_bind_plan", coupon={"percent": percent})
            bot.send_message(uid, "کد برای همه پلن‌ها باشد یا شناسه پلن را بفرست؟\n(بنویس: all یا مثلاً 1)", reply_markup=back_menu())
        except Exception:
            bot.send_message(uid, "درصد را درست وارد کن (مثلاً 20).", reply_markup=back_menu())
        return

    if await_key == "coupon_make_bind_plan":
        c = get_state(uid).get("coupon", {})
        if text.lower() == "all":
            c["only_plan_id"] = None
        else:
            try:
                c["only_plan_id"] = int(text)
            except Exception:
                bot.send_message(uid, "یا all بنویس یا شناسه‌ی عددی پلن.", reply_markup=back_menu())
                return
        set_state(uid, await_key="coupon_make_expire", coupon=c)
        bot.send_message(uid, "تاریخ انقضا را بفرست (YYYY-MM-DD) یا بنویس: none", reply_markup=back_menu())
        return

    if await_key == "coupon_make_expire":
        c = get_state(uid).get("coupon", {})
        if text.lower() == "none":
            c["expire_at"] = None
        else:
            try:
                d = datetime.strptime(text, "%Y-%m-%d")
                # پایان روز
                c["expire_at"] = (d + timedelta(days=1) - timedelta(seconds=1)).isoformat()
            except Exception:
                bot.send_message(uid, "فرمت تاریخ درست نیست. مثل: 2025-12-31 یا none", reply_markup=back_menu())
                return
        set_state(uid, await_key="coupon_make_limit", coupon=c)
        bot.send_message(uid, "سقف تعداد استفاده؟ (عدد یا none)", reply_markup=back_menu())
        return

    if await_key == "coupon_make_limit":
        c = get_state(uid).get("coupon", {})
        if text.lower() == "none":
            c["max_uses"] = None
        else:
            try:
                c["max_uses"] = int(text)
            except Exception:
                bot.send_message(uid, "عدد یا none وارد کن.", reply_markup=back_menu())
                return
        set_state(uid, await_key="coupon_make_code", coupon=c)
        bot.send_message(uid, "نام/کد دلخواه را بفرست (مثلاً: OFF20)", reply_markup=back_menu())
        return

    if await_key == "coupon_make_code":
        c = get_state(uid).get("coupon", {})
        code = text.upper()
        c["code"] = code
        # ذخیره
        con = db()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO coupons(code,percent,only_plan_id,expire_at,max_uses,used_count,active)
            VALUES(?,?,?,?,?,?,1)
        """, (c["code"], c["percent"], c.get("only_plan_id"), c.get("expire_at"), c.get("max_uses"), 0))
        con.commit()
        con.close()
        clear_state(uid)
        bot.send_message(uid, f"✅ کد «{code}» ساخته شد.", reply_markup=main_menu(uid))
        return

    # اگر هیچ‌کدام نبود:
    bot.send_message(uid, "گزینه نامعتبر است.", reply_markup=main_menu(uid))

# ===================== BUY FLOW =====================

def show_plans(uid: int):
    rows = list_plans()
    if not rows:
        bot.send_message(uid, "فعلاً پلنی موجود نیست.", reply_markup=main_menu(uid))
        return
    kb = types.InlineKeyboardMarkup()
    for p in rows:
        title = f"{p['name']} • {money(p['price'])} تومان • موجودی: {p['stock']}"
        kb.add(types.InlineKeyboardButton(title, callback_data=f"plan:{p['id']}"))
    bot.send_message(uid, "لیست پلن‌ها:", reply_markup=kb)

def payment_menu(uid: int) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("کارت‌به‌کارت", "پرداخت با کیف پول")
    kb.row("اعمال/حذف کد تخفیف")
    kb.row(get_text("btn_back"))
    return kb

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan:"))
def plan_details(c: types.CallbackQuery):
    uid = c.from_user.id
    pid = int(c.data.split(":")[1])
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT p.*,
          (SELECT COUNT(*) FROM inventory i WHERE i.plan_id=p.id AND i.delivered=0) AS stock
        FROM plans p WHERE p.id=?
    """, (pid,))
    p = cur.fetchone()
    con.close()
    if not p:
        bot.answer_callback_query(c.id, "پلن یافت نشد.")
        return
    txt = (f"<b>{p['name']}</b>\n"
           f"قیمت: {money(p['price'])} تومان\n"
           f"مدت: {p['days']} روز | حجم: {p['traffic_gb']} GB\n"
           f"موجودی مخزن: {p['stock']}\n\n"
           f"{p['description'] or ''}")
    if p["stock"] <= 0:
        bot.edit_message_text(txt + "\n\n❌ موجودی این پلن تمام شده.", c.message.chat.id, c.message.id)
        return
    set_state(uid, selected_plan=pid, coupon_code=None, await_key=None)
    bot.edit_message_text(txt + "\n\nروش پرداخت را انتخاب کن:", c.message.chat.id, c.message.id)
    bot.send_message(uid, "در صورت داشتن کد تخفیف، دکمه‌ی مربوطه را بزن.", reply_markup=payment_menu(uid))

@bot.message_handler(func=lambda m: m.text in ["اعمال/حذف کد تخفیف"])
def coupon_entry(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    if not st.get("selected_plan"):
        bot.send_message(uid, "ابتدا یک پلن انتخاب کن.", reply_markup=main_menu(uid))
        return
    bot.send_message(uid, "کد تخفیف را بفرست (یا بنویس: none برای حذف).", reply_markup=back_menu())
    set_state(uid, await_key="enter_coupon")

@bot.message_handler(func=lambda m: m.text == "پرداخت با کیف پول")
def pay_with_wallet(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    pid = st.get("selected_plan")
    if not pid:
        bot.send_message(uid, "ابتدا یک پلن انتخاب کن.", reply_markup=main_menu(uid))
        return

    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM plans WHERE id=?", (pid,))
    p = cur.fetchone()
    con.close()
    if not p:
        bot.send_message(uid, "پلن یافت نشد.", reply_markup=main_menu(uid))
        return

    final, cobj, err = apply_coupon(p["price"], st.get("coupon_code"), pid)
    if err:
        bot.send_message(uid, err, reply_markup=payment_menu(uid))
        return

    bal = get_wallet(uid)
    if bal >= final:
        # پرداخت و ارسال
        add_wallet(uid, -final, reason="buy_plan")
        inv = consume_inventory(pid)
        if not inv:
            bot.send_message(uid, "موجودی مخزن این پلن کافی نیست. پول به کیف پول برگشت داده شد.", reply_markup=main_menu(uid))
            add_wallet(uid, final, reason="refund_no_inventory")
            return
        # ثبت سفارش
        con = db()
        cur = con.cursor()
        cur.execute("INSERT INTO orders(user_id,plan_id,price,coupon_code,delivered,delivered_at) VALUES(?,?,?,?,1,?)",
                    (uid, pid, final, st.get("coupon_code"), datetime.utcnow().isoformat()))
        con.commit()
        con.close()
        if cobj: increment_coupon(cobj["code"])
        send_config_to_user(uid, inv)
        bot.send_message(uid, f"✅ خرید تکمیل شد. مبلغ پرداختی: {money(final)} تومان", reply_markup=main_menu(uid))
        notify_admins(f"🧾 خرید جدید توسط <code>{uid}</code> | پلن #{pid} | مبلغ: {money(final)}")
    else:
        need = final - bal
        set_state(uid, await_key="pay_by_wallet_confirm", need_amount=need, expected_final=final, plan_id=pid)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(f"شارژ همین مقدار ({money(need)})")
        kb.row(get_text("btn_back"))
        bot.send_message(uid, f"موجودی کافی نیست.\nکمبود: {money(need)} تومان", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text and m.text.startswith("شارژ همین مقدار"))
def charge_exact(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    need = st.get("need_amount")
    if not need:
        bot.send_message(uid, "در حال حاضر خرید فعالی نیست.", reply_markup=main_menu(uid))
        return
    # ساخت رسید «خرید کانفیگ»
    rid = f"{int(time.time()*1000)}#{uid}"
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO receipts(id,user_id,kind,amount,status,media,created_at)
        VALUES(?,?,?,?,?,?,?)
    """, (rid, uid, "purchase", need, "pending", json.dumps({"type": "text", "text": "auto_need_amount"}), datetime.utcnow().isoformat()))
    con.commit()
    con.close()
    bot.send_message(uid, "📤 رسید را ارسال کن و نوع پرداخت را کارت‌به‌کارت انتخاب کن.\nپس از تایید ادمین، خرید تکمیل می‌شود.", reply_markup=main_menu(uid))
    notify_admins(f"🧾 رسید جدید (خرید کانفیگ)\nID: <code>{rid}</code>\nکاربر: <code>{uid}</code>\nمبلغ: {money(need)}")

@bot.message_handler(func=lambda m: m.text == "کارت‌به‌کارت")
def pay_card_to_card(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    if not st.get("selected_plan"):
        bot.send_message(uid, "ابتدا پلن را انتخاب کن.", reply_markup=main_menu(uid))
        return
    card = get_text("card_number")
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("ارسال رسید")
    kb.row(get_text("btn_back"))
    bot.send_message(uid, f"✅ شماره کارت:\n<code>{card}</code>\n\nمبلغ را کارت‌به‌کارت کن و سپس دکمه «ارسال رسید» را بزن.", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "ارسال رسید")
def prompt_receipt(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    if not st.get("selected_plan"):
        bot.send_message(uid, "ابتدا پلن را انتخاب کن.", reply_markup=main_menu(uid))
        return
    set_state(uid, await_key="send_receipt", receipt_kind=("purchase" if st.get("selected_plan") else "wallet"))
    bot.send_message(uid, "عکس یا متن رسید را بفرست.\n(پس از ارسال، پیام تأیید خودکار می‌آید.)", reply_markup=back_menu())

@bot.message_handler(content_types=["photo", "text"], func=lambda m: get_state(m.from_user.id).get("await_key") == "send_receipt")
def receive_receipt(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    kind = st.get("receipt_kind") or "purchase"
    amount_expected = st.get("expected_final") or st.get("need_amount") or 0

    if message.content_type == "photo":
        file_id = message.photo[-1].file_id
        media = {"type": "photo", "file_id": file_id}
    else:
        media = {"type": "text", "text": message.text or ""}

    rid = f"{hex(int(time.time()*1000))[2:8]}#{uid}"
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO receipts(id,user_id,kind,amount,status,media,created_at)
        VALUES(?,?,?,?,?,?,?)
    """, (rid, uid, kind, amount_expected, "pending", json.dumps(media, ensure_ascii=False), datetime.utcnow().isoformat()))
    con.commit()
    con.close()

    clear_state(uid)
    bot.send_message(uid, f"<code>#{rid}</code> رسید شما ثبت شد؛ منتظر تأیید ادمین…", reply_markup=main_menu(uid))
    # اطلاع به ادمین‌ها
    uname = f"@{message.from_user.username}" if message.from_user.username else "-"
    notify_admins(f"🧾 رسید جدید #{rid}\nاز: {uname} <code>{uid}</code>\nنوع: {kind}\nوضعیت: pending")

# ===================== WALLET =====================

def show_wallet(uid: int):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(get_text("btn_wallet_charge"), get_text("btn_wallet_history"))
    kb.row(get_text("btn_back"))
    bal = get_wallet(uid)
    bot.send_message(uid, f"موجودی فعلی: <b>{money(bal)}</b> تومان", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == get_text("btn_wallet_charge"))
def wallet_charge(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="send_receipt", receipt_kind="wallet", expected_final=0)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("کارت‌به‌کارت")
    kb.row(get_text("btn_back"))
    bot.send_message(uid, "روش شارژ را انتخاب کن:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == get_text("btn_wallet_history"))
def wallet_history(message: types.Message):
    uid = message.from_user.id
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM logs WHERE user_id=? AND action='wallet_change' ORDER BY id DESC LIMIT 10", (uid,))
    rows = cur.fetchall()
    con.close()
    if not rows:
        bot.send_message(uid, "هنوز تراکنشی ثبت نشده.", reply_markup=main_menu(uid))
        return
    lines = []
    for r in rows:
        meta = json.loads(r["meta"])
        lines.append(f"{meta.get('reason','-')}: {money(meta.get('amount',0))} | {r['created_at'][:19]}")
    bot.send_message(uid, "۱۰ تراکنش اخیر:\n" + "\n".join(lines), reply_markup=main_menu(uid))

# ===================== TICKETS =====================

def ticket_menu(uid: int):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("تیکت جدید", "تیکت‌های من")
    kb.row(get_text("btn_back"))
    bot.send_message(uid, "پشتیبانی:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "تیکت جدید")
def ticket_new(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="ticket_subject")
    bot.send_message(uid, "موضوع تیکت را بنویس:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: m.text == "تیکت‌های من")
def ticket_list(message: types.Message):
    uid = message.from_user.id
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 15", (uid,))
    rows = cur.fetchall()
    con.close()
    if not rows:
        bot.send_message(uid, "هیچ تیکتی نداری.", reply_markup=main_menu(uid))
        return
    kb = types.InlineKeyboardMarkup()
    for r in rows:
        kb.add(types.InlineKeyboardButton(f"#{r['id']} • {r['status']}", callback_data=f"tk:{r['id']}"))
    bot.send_message(uid, "لیست تیکت‌ها:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tk:"))
def ticket_open(c: types.CallbackQuery):
    uid = c.from_user.id
    tid = int(c.data.split(":")[1])
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM tickets WHERE id=? AND user_id=?", (tid, uid))
    t = cur.fetchone()
    if not t:
        bot.answer_callback_query(c.id, "تیکت یافت نشد.")
        con.close()
        return
    cur.execute("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id", (tid,))
    msgs = cur.fetchall()
    con.close()
    txt = [f"تیکت #{tid} • وضعیت: {t['status']}"]
    for m in msgs:
        who = "👤" if m["sender"] == "user" else "🛠"
        txt.append(f"{who} {m['text']}")
    kb = types.InlineKeyboardMarkup()
    if t["status"] == "open":
        kb.add(types.InlineKeyboardButton("ارسال پیام", callback_data=f"tksend:{tid}"))
        kb.add(types.InlineKeyboardButton("بستن تیکت", callback_data=f"tkclose:{tid}"))
    bot.edit_message_text("\n\n".join(txt), c.message.chat.id, c.message.id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tksend:"))
def ticket_send_msg(c: types.CallbackQuery):
    uid = c.from_user.id
    tid = int(c.data.split(":")[1])
    set_state(uid, await_key="ticket_user_reply", ticket_id=tid)
    bot.answer_callback_query(c.id)
    bot.send_message(uid, "پیامت را بنویس:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "ticket_user_reply")
def ticket_user_reply(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    tid = st.get("ticket_id")
    if not tid:
        clear_state(uid)
        bot.send_message(uid, "تیکت یافت نشد.", reply_markup=main_menu(uid))
        return
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO ticket_messages(ticket_id,sender,text,created_at) VALUES(?,?,?,?)",
                (tid, "user", message.text, datetime.utcnow().isoformat()))
    con.commit()
    con.close()
    clear_state(uid)
    bot.send_message(uid, "ارسال شد.", reply_markup=main_menu(uid))
    notify_admins(f"📥 پیام جدید در تیکت #{tid} از <code>{uid}</code>")

# ===================== PROFILE =====================

def show_profile(uid: int):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) c FROM orders WHERE user_id=?", (uid,))
    cnt = cur.fetchone()["c"]
    uname = "-"
    cur.execute("SELECT username FROM users WHERE id=?", (uid,))
    r = cur.fetchone()
    if r and r["username"]:
        uname = f"@{r['username']}"
    con.close()
    bot.send_message(uid, f"آیدی عددی: <code>{uid}</code>\nیوزرنیم: {uname}\nتعداد کانفیگ‌های خریداری‌شده: {cnt}", reply_markup=main_menu(uid))

# ===================== ADMIN =====================

def show_admin_panel(uid: int):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(get_text("btn_admin_plans"), get_text("btn_admin_inventory"))
    kb.row(get_text("btn_admin_coupons"), get_text("btn_admin_admins"))
    kb.row(get_text("btn_admin_receipts"), get_text("btn_admin_wallet"))
    kb.row(get_text("btn_admin_texts"), get_text("btn_admin_broadcast"))
    kb.row(get_text("btn_admin_stats"))
    kb.row(get_text("btn_back"))
    bot.send_message(uid, "پنل ادمین:", reply_markup=kb)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_admins"))
def admin_admins(message: types.Message):
    uid = message.from_user.id
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("افزودن ادمین", "حذف ادمین")
    kb.row(get_text("btn_back"))
    bot.send_message(uid, "مدیریت ادمین‌ها:", reply_markup=kb)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "افزودن ادمین")
def admin_add_admin(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="add_admin")
    bot.send_message(uid, "آیدی عددی کاربر را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "add_admin")
def admin_add_admin_value(message: types.Message):
    uid = message.from_user.id
    try:
        target = int(message.text.replace(" ", ""))
        con = db()
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (target,))
        con.commit()
        con.close()
        clear_state(uid)
        bot.send_message(uid, f"✅ {target} به ادمین‌ها اضافه شد.", reply_markup=main_menu(uid))
    except Exception:
        bot.send_message(uid, "فقط عدد بفرست.", reply_markup=back_menu())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "حذف ادمین")
def admin_del_admin(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="del_admin")
    bot.send_message(uid, "آیدی عددی را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "del_admin")
def admin_del_admin_value(message: types.Message):
    uid = message.from_user.id
    try:
        target = int(message.text.replace(" ", ""))
        con = db()
        cur = con.cursor()
        cur.execute("DELETE FROM admins WHERE user_id=?", (target,))
        con.commit()
        con.close()
        clear_state(uid)
        bot.send_message(uid, f"❌ {target} از ادمین‌ها حذف شد.", reply_markup=main_menu(uid))
    except Exception:
        bot.send_message(uid, "فقط عدد بفرست.", reply_markup=back_menu())

# ----- مدیریت پلن‌ها (ساده و کاربردی) -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_plans"))
def admin_plans(message: types.Message):
    uid = message.from_user.id
    rows = list_plans()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("افزودن پلن")
    kb.row(get_text("btn_back"))
    lines = []
    for p in rows:
        lines.append(f"#{p['id']} • {p['name']} • {money(p['price'])} • موجودی:{p['stock']}")
    bot.send_message(uid, "پلن‌های فعال:\n" + ("\n".join(lines) if lines else "—"), reply_markup=kb)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "افزودن پلن")
def admin_add_plan(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="add_plan_name", plan_new={})
    bot.send_message(uid, "نام پلن را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "add_plan_name")
def admin_add_plan_name(message: types.Message):
    uid = message.from_user.id
    p = get_state(uid).get("plan_new", {})
    p["name"] = message.text
    set_state(uid, await_key="add_plan_days", plan_new=p)
    bot.send_message(uid, "مدت (روز) را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "add_plan_days")
def admin_add_plan_days(message: types.Message):
    uid = message.from_user.id
    try:
        days = int(message.text.replace(" ", ""))
    except Exception:
        bot.send_message(uid, "عدد صحیح وارد کن.", reply_markup=back_menu())
        return
    p = get_state(uid).get("plan_new", {})
    p["days"] = days
    set_state(uid, await_key="add_plan_traffic", plan_new=p)
    bot.send_message(uid, "حجم (GB) را بفرست (مثلاً 50):", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "add_plan_traffic")
def admin_add_plan_traffic(message: types.Message):
    uid = message.from_user.id
    try:
        traffic = float(message.text.replace(" ", ""))
    except Exception:
        bot.send_message(uid, "عدد درست وارد کن.", reply_markup=back_menu())
        return
    p = get_state(uid).get("plan_new", {})
    p["traffic_gb"] = traffic
    set_state(uid, await_key="add_plan_price", plan_new=p)
    bot.send_message(uid, "قیمت (تومان) را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "add_plan_price")
def admin_add_plan_price(message: types.Message):
    uid = message.from_user.id
    try:
        price = int(message.text.replace(" ", ""))
    except Exception:
        bot.send_message(uid, "عدد صحیح وارد کن.", reply_markup=back_menu())
        return
    p = get_state(uid).get("plan_new", {})
    p["price"] = price
    set_state(uid, await_key="add_plan_desc", plan_new=p)
    bot.send_message(uid, "توضیحات پلن:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "add_plan_desc")
def admin_add_plan_desc(message: types.Message):
    uid = message.from_user.id
    p = get_state(uid).get("plan_new", {})
    p["description"] = message.text
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO plans(name,days,traffic_gb,price,description,active) VALUES(?,?,?,?,?,1)",
                (p["name"], p["days"], p["traffic_gb"], p["price"], p["description"]))
    con.commit()
    con.close()
    clear_state(uid)
    bot.send_message(uid, "✅ پلن افزوده شد.", reply_markup=main_menu(uid))

# ----- مخزن -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_inventory"))
def admin_inventory(message: types.Message):
    uid = message.from_user.id
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("افزودن کانفیگ به مخزن")
    kb.row(get_text("btn_back"))
    rows = list_plans()
    lines = []
    for p in rows:
        lines.append(f"پلن #{p['id']} • {p['name']} • موجودی: {p['stock']}")
    bot.send_message(uid, "وضعیت مخزن:\n" + ("\n".join(lines) if lines else "—"), reply_markup=kb)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "افزودن کانفیگ به مخزن")
def admin_inventory_add(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="inv_plan_id")
    bot.send_message(uid, "شناسه پلن را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "inv_plan_id")
def admin_inventory_pid(message: types.Message):
    uid = message.from_user.id
    try:
        pid = int(message.text.replace(" ", ""))
        set_state(uid, await_key="inv_text", inv_plan_id=pid)
        bot.send_message(uid, "متن کانفیگ را بفرست (در صورت داشتن عکس، بعداً هم می‌تونی بدهی).", reply_markup=back_menu())
    except Exception:
        bot.send_message(uid, "عدد درست وارد کن.", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "inv_text", content_types=["text"])
def admin_inventory_text(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    set_state(uid, await_key="inv_photo_opt", inv_text=message.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("بدون عکس", "ارسال عکس")
    kb.row(get_text("btn_back"))
    bot.send_message(uid, "عکس هم می‌فرستی؟", reply_markup=kb)

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "inv_photo_opt" and m.text == "بدون عکس")
def admin_inventory_no_photo(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    payload = {"text": st.get("inv_text")}
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO inventory(plan_id,payload,delivered) VALUES(?,?,0)",
                (st.get("inv_plan_id"), json.dumps(payload, ensure_ascii=False)))
    con.commit()
    con.close()
    clear_state(uid)
    bot.send_message(uid, "✅ اضافه شد.", reply_markup=main_menu(uid))

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "inv_photo_opt", content_types=["photo"])
def admin_inventory_with_photo(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    photo_id = message.photo[-1].file_id
    payload = {"text": st.get("inv_text"), "photo_id": photo_id}
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO inventory(plan_id,payload,delivered) VALUES(?,?,0)",
                (st.get("inv_plan_id"), json.dumps(payload, ensure_ascii=False)))
    con.commit()
    con.close()
    clear_state(uid)
    bot.send_message(uid, "✅ اضافه شد.", reply_markup=main_menu(uid))

# ----- رسیدها -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_receipts"))
def admin_receipts(message: types.Message):
    uid = message.from_user.id
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM receipts WHERE status='pending' ORDER BY created_at ASC LIMIT 20")
    rows = cur.fetchall()
    con.close()
    if not rows:
        bot.send_message(uid, "رسیدی در انتظار نیست.", reply_markup=main_menu(uid))
        return
    for r in rows:
        show_receipt_card(uid, r)

def show_receipt_card(admin_id: int, r: sqlite3.Row):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("تأیید", callback_data=f"rcok:{r['id']}"))
    kb.add(types.InlineKeyboardButton("رد", callback_data=f"rcno:{r['id']}"))
    m = json.loads(r["media"])
    cap = (f"<code>#{r['id']}</code> رسید\n"
           f"از: <code>{r['user_id']}</code>\n"
           f"نوع: {r['kind']}\n"
           f"وضعیت: {r['status']}")
    if m.get("type") == "photo":
        bot.send_photo(admin_id, m["file_id"], caption=cap, reply_markup=kb)
    else:
        bot.send_message(admin_id, cap + f"\nمتن: {m.get('text','')}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith(("rcok:", "rcno:")))
def admin_receipt_action(c: types.CallbackQuery):
    action, rid = c.data.split(":")
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM receipts WHERE id=?", (rid,))
    r = cur.fetchone()
    if not r or r["status"] != "pending":
        bot.answer_callback_query(c.id, "اعتبار ندارد/رسیدگی شده.")
        con.close()
        return

    if action == "rcno":
        cur.execute("UPDATE receipts SET status='rejected' WHERE id=?", (rid,))
        con.commit()
        con.close()
        bot.edit_message_caption("❌ رد شد.", c.message.chat.id, c.message.id) if c.message.caption else bot.edit_message_text("❌ رد شد.", c.message.chat.id, c.message.id)
        bot.send_message(r["user_id"], "❌ رسید شما رد شد. در صورت ابهام با پشتیبانی در تماس باشید.")
        return

    # تأیید
    if r["kind"] == "wallet":
        # ادمین باید مبلغ را وارد کند
        set_state(c.from_user.id, await_key="charge_amount_admin", target_user=r["user_id"], receipt_id=r["id"])
        bot.answer_callback_query(c.id)
        bot.send_message(c.from_user.id, "مبلغ شارژ (تومان) را وارد کنید:", reply_markup=back_menu())
    else:
        # purchase: باید کانفیگ بفرستیم
        # از state خرید کاربر چیزی نداریم؛ فقط از موجودی مخزن همان پلنی که انتخاب کرده بود (راه ساده: از ارزان‌ترین یا ID ثبت‌شده؟)
        # در این نسخه ساده: از آخرین plan انتخاب‌شده کاربر استفاده می‌کنیم؛ اگر نبود، ارور می‌دهیم.
        cur.execute("SELECT json FROM states WHERE user_id=?", (r["user_id"],))
        srow = cur.fetchone()
        pid = None
        if srow and srow["json"]:
            try:
                pid = json.loads(srow["json"]).get("plan_id") or json.loads(srow["json"]).get("selected_plan")
            except Exception:
                pid = None
        if not pid:
            # fallback: ارزان‌ترین پلن موجود
            cur.execute("SELECT id FROM plans WHERE active=1 ORDER BY price ASC LIMIT 1")
            t = cur.fetchone()
            pid = t["id"] if t else None

        if not pid:
            bot.answer_callback_query(c.id, "پلنی برای این رسید پیدا نشد.")
            con.close()
            return

        inv = consume_inventory(pid)
        if not inv:
            bot.answer_callback_query(c.id, "مخزن خالی است.")
            con.close()
            return

        cur.execute("UPDATE receipts SET status='approved' WHERE id=?", (rid,))
        cur.execute("INSERT INTO orders(user_id,plan_id,price,coupon_code,delivered,delivered_at) VALUES(?,?,?,?,1,?)",
                    (r["user_id"], pid, r["amount"] or 0, None, datetime.utcnow().isoformat()))
        con.commit()
        con.close()

        send_config_to_user(r["user_id"], inv)
        bot.edit_message_caption("✅ تایید و ارسال شد.", c.message.chat.id, c.message.id) if c.message.caption else bot.edit_message_text("✅ تایید و ارسال شد.", c.message.chat.id, c.message.id)
        bot.send_message(r["user_id"], "✅ رسید تایید شد و کانفیگ برایتان ارسال گردید.")

# ----- کیف پول (ادمین) -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_wallet"))
def admin_wallet(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="wallet_admin_target")
    bot.send_message(uid, "آیدی عددی کاربر را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "wallet_admin_target")
def admin_wallet_target(message: types.Message):
    uid = message.from_user.id
    try:
        target = int(message.text.replace(" ", ""))
        set_state(uid, await_key="charge_amount_admin", target_user=target)
        bot.send_message(uid, "مبلغ شارژ (تومان) را وارد کنید:", reply_markup=back_menu())
    except Exception:
        bot.send_message(uid, "فقط عدد بفرست.", reply_markup=back_menu())

# ----- دکمه‌ها و متون -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_texts"))
def admin_texts(message: types.Message):
    uid = message.from_user.id
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("ویرایش متن دکمه/مقدار", "فعال/غیرفعال‌سازی دکمه")
    kb.row("تغییر شماره کارت")
    kb.row(get_text("btn_back"))
    bot.send_message(uid, "مدیریت دکمه‌ها و متون:", reply_markup=kb)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "ویرایش متن دکمه/مقدار")
def admin_texts_edit(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="texts_edit_key")
    bot.send_message(uid, "کلید موردنظر را بفرست (مثل: btn_buy یا card_number).", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "texts_edit_key")
def admin_texts_edit_key(message: types.Message):
    uid = message.from_user.id
    key = message.text.strip()
    set_state(uid, await_key="texts_edit_value", edit_key=key)
    bot.send_message(uid, f"متن جدید برای «{key}» را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "texts_edit_value")
def admin_texts_edit_value(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    key = st.get("edit_key")
    set_text(key, message.text)
    clear_state(uid)
    bot.send_message(uid, "✅ به‌روزرسانی شد.", reply_markup=main_menu(uid))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "فعال/غیرفعال‌سازی دکمه")
def admin_toggle_button(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="toggle_key")
    bot.send_message(uid, "کلید دکمه را بفرست (مثلاً: btn_buy).", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "toggle_key")
def admin_toggle_button_key(message: types.Message):
    uid = message.from_user.id
    key = message.text.strip()
    flag = not is_enabled(key)
    set_enabled(key, flag)
    clear_state(uid)
    bot.send_message(uid, f"وضعیت «{key}»: {'فعال' if flag else 'غیرفعال'}", reply_markup=main_menu(uid))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "تغییر شماره کارت")
def admin_change_card(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="change_card")
    bot.send_message(uid, "شماره کارت جدید را بفرست:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_key") == "change_card")
def admin_change_card_value(message: types.Message):
    uid = message.from_user.id
    set_text("card_number", message.text.strip())
    clear_state(uid)
    bot.send_message(uid, "✅ شماره کارت ثبت شد.", reply_markup=main_menu(uid))

# ----- کوپن -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_coupons"))
def admin_coupons(message: types.Message):
    uid = message.from_user.id
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("ساخت کد تخفیف")
    kb.row(get_text("btn_back"))
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM coupons ORDER BY active DESC, used_count DESC LIMIT 20")
    rows = cur.fetchall()
    con.close()
    if rows:
        lines = []
        for c in rows:
            scope = "همه" if not c["only_plan_id"] else f"پلن #{c['only_plan_id']}"
            exp = c["expire_at"] or "—"
            lines.append(f"{c['code']} • %{c['percent']} • {scope} • استفاده: {c['used_count']} • انقضا: {exp}")
        bot.send_message(uid, "لیست کدها:\n" + "\n".join(lines), reply_markup=kb)
    else:
        bot.send_message(uid, "فعلاً کدی موجود نیست.", reply_markup=kb)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "ساخت کد تخفیف")
def admin_coupon_make(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="coupon_make_percent", coupon={})
    bot.send_message(uid, "درصد تخفیف را وارد کن (مثلاً 20):", reply_markup=back_menu())

# ----- اعلان همگانی -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_broadcast"))
def admin_broadcast(message: types.Message):
    uid = message.from_user.id
    set_state(uid, await_key="admin_broadcast")
    bot.send_message(uid, "متن پیام همگانی را بفرست:", reply_markup=back_menu())

def broadcast_worker(admin_id: int, text: str):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id FROM users")
    ids = [r["id"] for r in cur.fetchall()]
    con.close()
    ok = 0
    for u in ids:
        try:
            bot.send_message(u, text)
            ok += 1
            time.sleep(0.03)
        except Exception:
            pass
    bot.send_message(admin_id, f"✅ ارسال شد برای {ok} نفر.")

# ----- آمار فروش -----

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == get_text("btn_admin_stats"))
def admin_stats(message: types.Message):
    uid = message.from_user.id
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) cnt, COALESCE(SUM(price),0) total FROM orders")
    r = cur.fetchone()
    cnt, total = r["cnt"], r["total"]
    cur.execute("""
        SELECT user_id, COUNT(*) cnt, COALESCE(SUM(price),0) total
        FROM orders GROUP BY user_id ORDER BY total DESC LIMIT 10
    """)
    tops = cur.fetchall()
    con.close()
    lines = [f"📊 فروش کل: {cnt} کانفیگ • {money(total)} تومان"]
    if tops:
        lines.append("\n👑 برترین خریداران:")
        rank = 1
        for t in tops:
            lines.append(f"{rank}. <code>{t['user_id']}</code> • {t['cnt']} عدد • {money(t['total'])} تومان")
            rank += 1
    bot.send_message(uid, "\n".join(lines), reply_markup=main_menu(uid))

# ===================== BOOT =====================

def set_webhook_once():
    try:
        bot.remove_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print("Failed to set webhook:", e)

if __name__ == "__main__":
    init_db()
    set_webhook_once()
    # روی Koyeb، gunicorn این فایل را اجرا می‌کند؛ ولی برای اجرا محلی هم قابل استفاده است:
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
