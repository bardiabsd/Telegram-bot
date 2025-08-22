# -*- coding: utf-8 -*-
import os
import re
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from flask import Flask, request, abort
import requests

# =====================[ ENV ]=====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
APP_URL = os.environ.get("APP_URL", "").strip()
DEFAULT_ADMIN_ID = int(os.environ.get("DEFAULT_ADMIN_ID", "1743359080"))
CARD_NUMBER = os.environ.get("CARD_NUMBER", "6037-9915-XXXX-XXXX").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env is required")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# =====================[ FLASK ]===================
app = Flask(__name__)

# =====================[ DB ]======================
DB_PATH = "bot.db"
_db_lock = threading.Lock()

def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with _db_lock, db() as con:
        cur = con.cursor()
        # کاربران
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            wallet INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            created_at TEXT
        );
        """)
        # ادمین‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        );
        """)
        # پلن‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            days INTEGER,
            traffic_gb REAL,
            price INTEGER,
            desc TEXT,
            active INTEGER DEFAULT 1
        );
        """)
        # مخزن کانفیگ هر پلن
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            text_config TEXT,
            photo_file_id TEXT,
            created_at TEXT,
            sent INTEGER DEFAULT 0,
            FOREIGN KEY(plan_id) REFERENCES plans(id)
        );
        """)
        # سفارش‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_id INTEGER,
            price INTEGER,
            coupon_code TEXT,
            final_price INTEGER,
            delivered INTEGER DEFAULT 0,
            expire_at TEXT,
            created_at TEXT
        );
        """)
        # رسیدها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            type TEXT, -- wallet/config
            amount INTEGER,
            status TEXT, -- pending/approved/rejected
            image_file_id TEXT,
            note TEXT,
            created_at TEXT
        );
        """)
        # تراکنش‌های کیف پول
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_tx (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TEXT
        );
        """)
        # کدهای تخفیف
        cur.execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            percent INTEGER,
            plan_id INTEGER, -- NULL=all
            expire_at TEXT,
            max_uses INTEGER,
            used INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        );
        """)
        # تیکت‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            status TEXT, -- open/closed
            created_at TEXT
        );
        """)
        # پیام‌های تیکت
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_msgs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            from_admin INTEGER,
            text TEXT,
            created_at TEXT
        );
        """)
        # تنظیمات متنی/دکمه‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            val TEXT
        );
        """)
        # فلگ نمایش/مخفی‌سازی دکمه‌ها
        cur.execute("""
        CREATE TABLE IF NOT EXISTS toggles (
            key TEXT PRIMARY KEY,
            on INTEGER
        );
        """)
        # نگه‌داری state کاربر (برای ری‌استارت نشدن جریان‌ها)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY,
            state TEXT,
            data TEXT
        );
        """)

        # ادمین پیش‌فرض
        cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (DEFAULT_ADMIN_ID,))

        # مقادیر پیش‌فرض تنظیمات و دکمه‌ها
        defaults_settings = {
            "welcome": "سلام 👋 خوش اومدی!\nیکی از گزینه‌ها رو انتخاب کن:",
            "card_number": CARD_NUMBER,
            "support_note": "رسید شما ثبت شد؛ منتظر تأیید ادمین باشید.",
            "expiry_reminder_days": "3"
        }
        for k, v in defaults_settings.items():
            cur.execute("INSERT OR IGNORE INTO settings(key, val) VALUES (?,?)", (k, v))

        default_buttons = {
            "btn_buy": "خرید پلن 🛒",
            "btn_wallet": "کیف پول 🌍",
            "btn_ticket": "تیکت پشتیبانی 🎫",
            "btn_profile": "حساب کاربری 👤",
            "btn_admin": "پنل ادمین 🛠",
            # ساب‌منوها
            "btn_wallet_charge": "شارژ کیف پول 💳",
            "btn_wallet_history": "تاریخچه کیف پول",
            "btn_wallet_back": "انصراف",
            "btn_buy_list": "لیست پلن‌ها",
            "btn_buy_back": "انصراف",
            "btn_apply_coupon": "اعمال کد تخفیف",
            "btn_pay_wallet": "پرداخت با کیف پول",
            "btn_pay_card": "کارت‌به‌کارت",
            "btn_cancel": "انصراف",
        }
        for k, v in default_buttons.items():
            cur.execute("INSERT OR IGNORE INTO settings(key, val) VALUES (?,?)", (k, v))

        default_toggles = {
            "buy": 1,
            "wallet": 1,
            "ticket": 1,
            "profile": 1,
            "admin": 1
        }
        for k, on in default_toggles.items():
            cur.execute("INSERT OR IGNORE INTO toggles(key, on) VALUES (?,?)", (k, on))

        con.commit()

init_db()

# =====================[ UTIL ]====================

def now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def get_setting(key: str, default: str = "") -> str:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT val FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row["val"] if row else default

def set_setting(key: str, val: str):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO settings(key,val) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET val=excluded.val", (key, val))
        con.commit()

def toggle_get(key: str) -> bool:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT on FROM toggles WHERE key=?", (key,))
        row = cur.fetchone()
        return bool(row["on"]) if row else True

def toggle_set(key: str, on: bool):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO toggles(key,on) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET on=excluded.on", (key, 1 if on else 0))
        con.commit()

def is_admin(uid: int) -> bool:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,))
        return cur.fetchone() is not None

def ensure_user(u: dict):
    uid = u["id"]
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO users(id, username, first_name, last_name, created_at) VALUES (?,?,?,?,?)",
                    (uid, u.get("username"), u.get("first_name"), u.get("last_name"), now_str()))
        cur.execute("UPDATE users SET username=?, first_name=?, last_name=? WHERE id=?",
                    (u.get("username"), u.get("first_name"), u.get("last_name"), uid))
        con.commit()

def get_wallet(uid: int) -> int:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT wallet FROM users WHERE id=?", (uid,))
        row = cur.fetchone()
        return row["wallet"] if row else 0

def wallet_add(uid: int, amount: int, reason: str):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("UPDATE users SET wallet = COALESCE(wallet,0) + ? WHERE id=?", (amount, uid))
        cur.execute("INSERT INTO wallet_tx(user_id, amount, reason, created_at) VALUES (?,?,?,?)",
                    (uid, amount, reason, now_str()))
        con.commit()

def wallet_sub(uid: int, amount: int, reason: str) -> bool:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT wallet FROM users WHERE id=?", (uid,))
        row = cur.fetchone()
        bal = row["wallet"] if row else 0
        if bal < amount:
            return False
        cur.execute("UPDATE users SET wallet = wallet - ? WHERE id=?", (amount, uid))
        cur.execute("INSERT INTO wallet_tx(user_id, amount, reason, created_at) VALUES (?,?,?,?)",
                    (uid, -amount, reason, now_str()))
        con.commit()
        return True

def digits(s: str) -> str:
    return re.sub(r"[^\d]", "", s or "")

def fmt_toman(n: int) -> str:
    return f"{n:,} تومان"

def safe_post(method: str, data: dict):
    try:
        requests.post(f"{API}/{method}", json=data, timeout=15)
    except Exception:
        pass

def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    safe_post("sendMessage", data)

def edit_message(chat_id: int, message_id: int, text: str, reply_markup: Optional[dict] = None):
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = reply_markup
    safe_post("editMessageText", data)

def send_photo(chat_id: int, file_id: str, caption: Optional[str] = None, reply_markup: Optional[dict] = None):
    data = {"chat_id": chat_id, "photo": file_id}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"
    if reply_markup:
        data["reply_markup"] = reply_markup
    safe_post("sendPhoto", data)

def answer_callback_query(qid: str, text: Optional[str] = None, show_alert: bool = False):
    data = {"callback_query_id": qid}
    if text:
        data["text"] = text
        data["show_alert"] = show_alert
    safe_post("answerCallbackQuery", data)

# ===== USER STATE (برای دیالوگ‌های چندمرحله‌ای حتی بعد از ری‌استارت) =====
def set_state(uid: int, next_state: Optional[str], data: Optional[dict] = None):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO user_state(user_id, state, data) VALUES (?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, data=excluded.data",
                    (uid, next_state, json.dumps(data or {})))
        con.commit()

def get_state(uid: int) -> Tuple[Optional[str], dict]:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT state, data FROM user_state WHERE user_id=?", (uid,))
        row = cur.fetchone()
        if not row:
            return None, {}
        return row["state"], json.loads(row["data"] or "{}")

def clear_state(uid: int):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("DELETE FROM user_state WHERE user_id=?", (uid,))
        con.commit()

# =====================[ KEYBOARDS ]====================

def kb(rows: List[List[Tuple[str, str]]]) -> dict:
    # rows: [[(text, data), ...], ...]
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in r] for r in rows]}

def main_menu(uid: int) -> dict:
    rows = []
    if toggle_get("buy"):
        rows.append([(get_setting("btn_buy"), "menu_buy")])
    if toggle_get("wallet"):
        rows.append([(get_setting("btn_wallet"), "menu_wallet")])
    if toggle_get("ticket"):
        rows.append([(get_setting("btn_ticket"), "menu_ticket")])
    if toggle_get("profile"):
        rows.append([(get_setting("btn_profile"), "menu_profile")])
    if toggle_get("admin") and is_admin(uid):
        rows.append([(get_setting("btn_admin"), "menu_admin")])
    return kb(rows)

def admin_menu() -> dict:
    rows = [
        [("👑 مدیریت ادمین‌ها", "adm_admins"), ("🧩 دکمه‌ها و متون", "adm_texts")],
        [("📦 پلن‌ها و مخزن", "adm_plans"), ("🏷 کدهای تخفیف", "adm_coupons")],
        [("🪙 کیف پول", "adm_wallet"), ("🧾 رسیدها", "adm_receipts")],
        [("👥 کاربران", "adm_users"), ("📢 اعلان همگانی", "adm_broadcast")],
        [("📊 آمار فروش", "adm_stats")],
        [("بازگشت ↩️", "back_home")]
    ]
    return kb(rows)

# =====================[ BUSINESS LOGIC ]====================

def plans_list(active_only=True) -> List[sqlite3.Row]:
    with _db_lock, db() as con:
        cur = con.cursor()
        if active_only:
            cur.execute("SELECT * FROM plans WHERE active=1 ORDER BY id")
        else:
            cur.execute("SELECT * FROM plans ORDER BY id")
        return cur.fetchall()

def plan_stock_count(plan_id: int) -> int:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(1) c FROM stock WHERE plan_id=? AND sent=0", (plan_id,))
        return cur.fetchone()["c"]

def stock_pop(plan_id: int) -> Optional[sqlite3.Row]:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM stock WHERE plan_id=? AND sent=0 ORDER BY id LIMIT 1", (plan_id,))
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("UPDATE stock SET sent=1 WHERE id=?", (row["id"],))
        con.commit()
        return row

def coupon_calc(code: str, plan_id: int, price: int) -> Tuple[bool, int, Optional[sqlite3.Row], str]:
    if not code:
        return True, price, None, ""
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM coupons WHERE code=? AND active=1", (code,))
        c = cur.fetchone()
        if not c:
            return False, price, None, "کد تخفیف نامعتبر است."
        if c["plan_id"] and c["plan_id"] != plan_id:
            return False, price, None, "این کد برای این پلن معتبر نیست."
        if c["expire_at"]:
            if datetime.utcnow() > datetime.strptime(c["expire_at"], "%Y-%m-%d %H:%M:%S"):
                return False, price, None, "کد تخفیف منقضی شده است."
        if c["max_uses"] and c["used"] >= c["max_uses"]:
            return False, price, None, "سقف استفاده از این کد تکمیل شده است."
        percent = max(0, min(90, int(c["percent"])))
        final = max(0, int(round(price * (100 - percent) / 100)))
        return True, final, c, ""

def coupon_use_inc(code: str):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("UPDATE coupons SET used = used + 1 WHERE code=?", (code,))
        con.commit()

def order_create(uid: int, plan_id: int, price: int, coupon_code: Optional[str], final_price: int) -> int:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO orders(user_id, plan_id, price, coupon_code, final_price, created_at) VALUES (?,?,?,?,?,?)",
                    (uid, plan_id, price, coupon_code, final_price, now_str()))
        con.commit()
        return cur.lastrowid

def order_set_delivered(order_id: int, expire_at: Optional[str]):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("UPDATE orders SET delivered=1, expire_at=? WHERE id=?", (expire_at, order_id))
        con.commit()

def receipt_create(uid: int, r_id: str, kind: str, amount: int, image_file_id: Optional[str], note: str):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO receipts(id, user_id, type, amount, status, image_file_id, note, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (r_id, uid, kind, amount, "pending", image_file_id, note, now_str()))
        con.commit()

def receipt_set_status(rid: str, status: str):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("UPDATE receipts SET status=? WHERE id=?", (status, rid))
        con.commit()

def stats_summary() -> Tuple[int, int, List[sqlite3.Row], List[sqlite3.Row]]:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT COALESCE(SUM(final_price),0) rev, COUNT(1) cnt FROM orders WHERE delivered=1")
        r = cur.fetchone()
        rev = r["rev"] or 0
        cnt = r["cnt"] or 0

        cur.execute("""
        SELECT p.name, COUNT(o.id) cnt, COALESCE(SUM(o.final_price),0) sum
        FROM orders o JOIN plans p ON p.id=o.plan_id
        WHERE o.delivered=1
        GROUP BY p.id ORDER BY sum DESC
        """)
        by_plan = cur.fetchall()

        cur.execute("""
        SELECT u.id uid, COALESCE(u.username,'') uname, COUNT(o.id) cnt, COALESCE(SUM(o.final_price),0) sum
        FROM orders o JOIN users u ON u.id=o.user_id
        WHERE o.delivered=1
        GROUP BY u.id ORDER BY sum DESC LIMIT 15
        """)
        top_buyers = cur.fetchall()

        return rev, cnt, by_plan, top_buyers

# =====================[ FLOW HELPERS ]====================

def show_home(uid: int):
    send_message(uid, get_setting("welcome"), main_menu(uid))

def show_wallet(uid: int):
    bal = get_wallet(uid)
    rows = [
        [(get_setting("btn_wallet_charge"), "w_charge")],
        [(get_setting("btn_wallet_history"), "w_history")],
        [(get_setting("btn_wallet_back"), "back_home")]
    ]
    send_message(uid, f"💼 موجودی فعلی: <b>{bal:,}</b> تومان", kb(rows))

def show_plans(uid: int):
    ps = plans_list(active_only=True)
    if not ps:
        send_message(uid, "هیچ پلنی فعال نیست.", kb([ [("بازگشت ↩️","back_home")] ]))
        return
    rows = []
    for p in ps:
        stock = plan_stock_count(p["id"])
        title = f"{p['name']} • {p['days']}روز/{p['traffic_gb']}GB • {p['price']:,} تومان • موجودی:{stock}"
        rows.append([(title, f"plan_{p['id']}")])
    rows.append([("بازگشت ↩️", "back_home")])
    send_message(uid, "📦 لیست پلن‌ها:", kb(rows))

def show_plan_detail(uid: int, pid: int, coupon_code: Optional[str] = None):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM plans WHERE id=?", (pid,))
        p = cur.fetchone()
        if not p:
            send_message(uid, "پلن یافت نشد.", kb([[("بازگشت ↩️","menu_buy")]]))
            return
    stock = plan_stock_count(pid)
    price = p["price"]
    ok, final, cobj, err = coupon_calc(coupon_code or "", pid, price)
    if coupon_code and not ok:
        send_message(uid, f"❌ {err}", kb([[("بازگشت ↩️", f"plan_{pid}")]]))
        return
    desc = p["desc"] or "-"
    lines = [
        f"🛍 <b>{p['name']}</b>",
        f"⏳ مدت: {p['days']} روز",
        f"📶 حجم: {p['traffic_gb']} GB",
        f"💰 قیمت: {price:,} تومان",
        f"🏷 موجودی کانفیگ: {stock}",
        f"ℹ️ توضیح: {desc}"
    ]
    if coupon_code and ok:
        lines.append(f"🎁 کد «{coupon_code}» اعمال شد → مبلغ نهایی: <b>{final:,}</b> تومان")
    rows = [
        [(get_setting("btn_apply_coupon"), f"applyc_{pid}")],
        [(get_setting("btn_pay_wallet"), f"payw_{pid}_{coupon_code or ''}")],
        [(get_setting("btn_pay_card"), f"payc_{pid}_{coupon_code or ''}")],
        [(get_setting("btn_buy_back"), "menu_buy")]
    ]
    send_message(uid, "\n".join(lines), kb(rows))

def start_ticket(uid: int):
    set_state(uid, "ticket_wait_text", {})
    send_message(uid, "📝 پیام تیکت را بنویسید (هر متنی خواستید، چند خطی هم می‌پذیریم).", kb([[("انصراف", "back_home")]]))

# =====================[ CALLBACK HANDLER ]====================

def handle_callback(q: dict):
    data = q["data"]
    uid = q["from"]["id"]
    qid = q["id"]
    chat_id = q["message"]["chat"]["id"]
    answer_callback_query(qid)

    if data == "back_home":
        clear_state(uid)
        show_home(uid)
        return

    # ----- منوها -----
    if data == "menu_wallet":
        show_wallet(uid)
        return
    if data == "menu_buy":
        show_plans(uid)
        return
    if data == "menu_ticket":
        start_ticket(uid)
        return
    if data == "menu_profile":
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT id, username, wallet FROM users WHERE id=?", (uid,))
            u = cur.fetchone()
            cur.execute("SELECT COUNT(1) c FROM orders WHERE user_id=? AND delivered=1", (uid,))
            c = cur.fetchone()["c"]
        txt = [
            f"🆔 آیدی عددی: <code>{u['id']}</code>",
            f"👤 یوزرنیم: @{u['username']}" if u['username'] else "👤 یوزرنیم: -",
            f"🛒 تعداد کانفیگ‌های خریداری‌شده: <b>{c}</b>",
            f"💼 موجودی کیف پول: <b>{u['wallet']:,}</b> تومان"
        ]
        send_message(uid, "\n".join(txt), kb([[("سفارش‌های من", "my_orders")],[("بازگشت ↩️","back_home")]]))
        return
    if data == "my_orders":
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("""SELECT o.id, o.final_price, o.expire_at, p.name FROM orders o 
                           JOIN plans p ON p.id=o.plan_id 
                           WHERE o.user_id=? AND o.delivered=1 ORDER BY o.id DESC LIMIT 20""", (uid,))
            rows = cur.fetchall()
        if not rows:
            send_message(uid, "سفارشی ثبت شده ندارید.", kb([[("بازگشت ↩️","menu_profile")]]))
        else:
            lines = ["📦 سفارش‌های شما:"]
            for r in rows:
                lines.append(f"• #{r['id']} | {r['name']} | مبلغ: {r['final_price']:,} | انقضا: {r['expire_at'] or '-'}")
            send_message(uid, "\n".join(lines), kb([[("بازگشت ↩️","menu_profile")]]))
        return

    if data == "menu_admin":
        if not is_admin(uid):
            send_message(uid, "⛔ این بخش مخصوص ادمین‌هاست.")
            return
        send_message(uid, "پنل ادمین:", admin_menu())
        return

    # ======== کیف پول ========
    if data == "w_charge":
        set_state(uid, "wallet_wait_amount", {})
        send_message(uid, "مبلغ شارژ (تومان) را ارسال کنید:", kb([[("انصراف","menu_wallet")]]))
        return
    if data == "w_history":
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM wallet_tx WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))
            rows = cur.fetchall()
        if not rows:
            send_message(uid, "تاریخچه‌ای یافت نشد.", kb([[("بازگشت ↩️","menu_wallet")]]))
        else:
            lines = ["📜 تاریخچه کیف پول:"]
            for r in rows:
                sign = "➕" if r["amount"] > 0 else "➖"
                lines.append(f"{sign} {abs(r['amount']):,} | {r['reason']} | {r['created_at']}")
            send_message(uid, "\n".join(lines), kb([[("بازگشت ↩️","menu_wallet")]]))
        return

    # ======== خرید پلن ========
    if data.startswith("plan_"):
        pid = int(data.split("_",1)[1])
        show_plan_detail(uid, pid)
        return
    if data.startswith("applyc_"):
        pid = int(data.split("_",1)[1])
        set_state(uid, "coupon_wait_code", {"plan_id": pid})
        send_message(uid, "کد تخفیف را وارد کنید:", kb([[("انصراف","menu_buy")]]))
        return
    if data.startswith("payw_"):
        _, rest = data.split("_",1)
        pid_str, code = rest.split("_",1)
        pid = int(pid_str)
        # ایجاد سفارش و پرداخت با کیف پول
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM plans WHERE id=?", (pid,))
            p = cur.fetchone()
        if not p or not p["active"]:
            send_message(uid, "پلن در دسترس نیست.")
            return
        ok, final, cobj, err = coupon_calc(code, pid, p["price"])
        if not ok:
            send_message(uid, f"❌ {err}")
            return
        bal = get_wallet(uid)
        if bal < final:
            diff = final - bal
            rows = [[(f"شارژ همین مقدار ({diff:,})", f"charge_diff_{pid}_{code}_{diff}")],
                    [("بازگشت ↩️","menu_buy")]]
            send_message(uid, f"موجودی ناکافی است. مابه‌التفاوت: <b>{diff:,}</b> تومان", kb(rows))
            return
        # پرداخت
        if not wallet_sub(uid, final, f"خرید پلن #{pid}"):
            send_message(uid, "پرداخت ناموفق. دوباره تلاش کنید.")
            return
        order_id = order_create(uid, pid, p["price"], code if code else None, final)
        # ارسال کانفیگ
        cfg = stock_pop(pid)
        if not cfg:
            send_message(uid, "❌ متأسفانه موجودی مخزن این پلن صفر است. مبلغ به کیف پول برگشت داده شد.")
            wallet_add(uid, final, "بازگشت وجه - عدم موجودی")
            return
        # تحویل
        exp = (datetime.utcnow() + timedelta(days=int(p["days"]))).strftime("%Y-%m-%d")
        order_set_delivered(order_id, exp)
        if code:
            coupon_use_inc(code)
        if cfg["photo_file_id"]:
            send_photo(uid, cfg["photo_file_id"], caption=cfg["text_config"] or "")
        else:
            send_message(uid, cfg["text_config"] or "(بدون متن)")
        send_message(uid, f"✅ پلن خریداری شد و ارسال شد.\n⏳ تاریخ انقضا: <b>{exp}</b>")
        return

    if data.startswith("charge_diff_"):
        _, pid, code, diff = data.split("_",3)
        set_state(uid, "wallet_wait_amount_exact", {"need": int(diff), "target": "buy", "plan_id": int(pid), "coupon": code})
        send_message(uid, f"برای تکمیل خرید، رسید شارژ <b>{int(diff):,}</b> تومان را بفرستید.\n"
                          f"ابتدا عکس رسید را ارسال کنید، سپس عدد مبلغ را وارد کنید.\n"
                          f"یا اگر بدون عکس است، فقط عدد مبلغ را بفرستید.\n"
                          f"پس از ثبت رسید، منتظر تأیید ادمین باشید.", kb([[("انصراف","back_home")]]))
        return

    if data.startswith("payc_"):
        _, pid, code = data.split("_",2)
        set_state(uid, "card_receipt_wait", {"plan_id": int(pid), "coupon": code})
        card = get_setting("card_number", CARD_NUMBER)
        send_message(uid, f"💳 اطلاعات کارت:\n<code>{card}</code>\n\n"
                          f"پس از واریز، «رسید» را بفرستید. می‌تونی عکس/اسکرین‌شات ارسال کنی.\n"
                          f"زیر همین گفتگو منتظر تأیید می‌مونیم.", kb([[("انصراف","menu_buy")]]))
        return

    # ======== پنل ادمین ========
    if data == "adm_admins":
        rows = [[("➕ افزودن ادمین", "adm_admins_add")], [("➖ حذف ادمین", "adm_admins_del")], [("↩️ بازگشت","menu_admin")]]
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT user_id FROM admins ORDER BY user_id")
            ads = cur.fetchall()
        lines = ["👑 ادمین‌ها:"]
        for a in ads:
            lines.append(f"• <code>{a['user_id']}</code>")
        send_message(uid, "\n".join(lines), kb(rows)); return
    if data == "adm_admins_add":
        set_state(uid, "adm_admins_add_wait", {})
        send_message(uid, "آیدی عددی کاربر را بفرستید:", kb([[("انصراف","menu_admin")]])); return
    if data == "adm_admins_del":
        set_state(uid, "adm_admins_del_wait", {})
        send_message(uid, "آیدی عددی ادمین را جهت حذف بفرستید:", kb([[("انصراف","menu_admin")]])); return

    if data == "adm_texts":
        rows = [
            [("ویرایش متن خوش‌آمد", "txt_welcome"), ("شماره کارت", "txt_card")],
            [("ویرایش برچسب دکمه‌ها", "txt_buttons")],
            [("روشن/خاموش کردن دکمه‌ها", "tog_buttons")],
            [("↩️ بازگشت","menu_admin")]
        ]
        send_message(uid, "ویرایش متون و دکمه‌ها:", kb(rows)); return
    if data == "txt_welcome":
        set_state(uid, "txt_welcome_wait", {})
        send_message(uid, "متن خوش‌آمد جدید را بفرست:", kb([[("انصراف","adm_texts")]])); return
    if data == "txt_card":
        set_state(uid, "txt_card_wait", {})
        send_message(uid, "شماره کارت جدید را بفرست:", kb([[("انصراف","adm_texts")]])); return
    if data == "txt_buttons":
        # لیست کلیدهایی که قابل ویرایشند
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT key, val FROM settings WHERE key LIKE 'btn_%' ORDER BY key")
            s = cur.fetchall()
        rows = []
        for r in s:
            rows.append([(f"{r['key']} = {r['val']}", f"btn_edit_{r['key']}")])
        rows.append([("↩️ بازگشت","adm_texts")])
        send_message(uid, "یک مورد را انتخاب کن:", kb(rows)); return
    if data.startswith("btn_edit_"):
        key = data[len("btn_edit_"):]
        set_state(uid, "btn_edit_wait", {"key": key})
        send_message(uid, f"برچسب جدید برای <code>{key}</code> را بفرست:", kb([[("انصراف","txt_buttons")]])); return
    if data == "tog_buttons":
        rows = []
        for k in ["buy","wallet","ticket","profile","admin"]:
            rows.append([(f"{k} : {'ON' if toggle_get(k) else 'OFF'}", f"tog_{k}")])
        rows.append([("↩️ بازگشت","adm_texts")])
        send_message(uid, "برای تغییر وضعیت هر دکمه، روی آن بزن:", kb(rows)); return
    if data.startswith("tog_"):
        key = data.split("_",1)[1]
        toggle_set(key, not toggle_get(key))
        handle_callback({"data": "tog_buttons", "from":{"id":uid}, "id":"dummy", "message": {"chat":{"id":uid}}})
        return

    if data == "adm_plans":
        rows = [[("➕ افزودن پلن", "plan_add")],[("ویرایش/حذف پلن", "plan_edit")],[("📦 مدیریت مخزن", "stock_mgmt")],[("↩️ بازگشت","menu_admin")]]
        send_message(uid, "مدیریت پلن‌ها:", kb(rows)); return
    if data == "plan_add":
        set_state(uid, "plan_add_name", {})
        send_message(uid, "نام پلن را بفرست:", kb([[("انصراف","adm_plans")]])); return
    if data == "plan_edit":
        ps = plans_list(active_only=False)
        if not ps:
            send_message(uid, "پلنی وجود ندارد.", kb([[("↩️ بازگشت","adm_plans")]])); return
        rows = []
        for p in ps:
            rows.append([(f"{p['id']}. {p['name']} | {'ON' if p['active'] else 'OFF'}", f"pedit_{p['id']}")])
        rows.append([("↩️ بازگشت","adm_plans")])
        send_message(uid, "پلن برای ویرایش:", kb(rows)); return
    if data.startswith("pedit_"):
        pid = int(data.split("_",1)[1])
        rows = [
            [("نام", f"pchg_name_{pid}"), ("مدت(روز)", f"pchg_days_{pid}")],
            [("حجم(GB)", f"pchg_traffic_{pid}"), ("قیمت", f"pchg_price_{pid}")],
            [("توضیح", f"pchg_desc_{pid}"), ("روشن/خاموش", f"pchg_toggle_{pid}")],
            [("❌ حذف", f"pdel_{pid}")],
            [("↩️ بازگشت","plan_edit")]
        ]
        send_message(uid, f"ویرایش پلن #{pid}:", kb(rows)); return
    if data.startswith("pchg_"):
        typ, pid = data.split("_",1)
        kind, pid = typ, int(pid)
        field = kind.replace("pchg_","")
        set_state(uid, "plan_change_field", {"pid": pid, "field": field})
        send_message(uid, f"مقدار جدید برای {field} را بفرست:", kb([[("انصراف","plan_edit")]])); return
    if data.startswith("pdel_"):
        pid = int(data.split("_",1)[1])
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM plans WHERE id=?", (pid,))
            con.commit()
        send_message(uid, "پلن حذف شد.", kb([[("↩️ بازگشت","adm_plans")]])); return
    if data.startswith("pchg_toggle_"):
        pid = int(data.split("_")[-1])
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("UPDATE plans SET active = 1 - active WHERE id=?", (pid,))
            con.commit()
        handle_callback({"data":"plan_edit","from":{"id":uid},"id":"x","message":{"chat":{"id":uid}}})
        return

    if data == "stock_mgmt":
        ps = plans_list(active_only=False)
        if not ps:
            send_message(uid, "پلنی وجود ندارد.", kb([[("↩️ بازگشت","adm_plans")]])); return
        rows = []
        for p in ps:
            rows.append([(f"{p['id']}. {p['name']} (موجودی:{plan_stock_count(p['id'])})", f"stock_{p['id']}")])
        rows.append([("↩️ بازگشت","adm_plans")])
        send_message(uid, "مخزن پلن‌ها:", kb(rows)); return
    if data.startswith("stock_"):
        pid = int(data.split("_",1)[1])
        rows = [
            [("➕ افزودن کانفیگ", f"stock_add_{pid}")],
            [("🗑 حذف کانفیگ‌های ارسال‌شده", f"stock_purge_{pid}")],
            [("↩️ بازگشت","stock_mgmt")]
        ]
        send_message(uid, f"مدیریت مخزن پلن #{pid}", kb(rows)); return
    if data.startswith("stock_add_"):
        pid = int(data.split("_",2)[2])
        set_state(uid, "stock_add_wait_text", {"pid": pid, "photo": None})
        send_message(uid, "متن کانفیگ را بفرست. (در صورت نیاز بعدش عکس هم می‌تونی بفرستی)", kb([[("انصراف","stock_mgmt")]])); return
    if data.startswith("stock_purge_"):
        pid = int(data.split("_",2)[2])
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM stock WHERE plan_id=? AND sent=1", (pid,))
            con.commit()
        send_message(uid, "کانفیگ‌های ارسال‌شده پاک شدند.", kb([[("↩️ بازگشت","stock_mgmt")]])); return

    if data == "adm_coupons":
        rows = [[("➕ ساخت کد", "cp_create")],[("🗒 لیست/حذف", "cp_list")],[("↩️ بازگشت","menu_admin")]]
        send_message(uid, "مدیریت کدهای تخفیف:", kb(rows)); return
    if data == "cp_create":
        set_state(uid, "cp_percent", {})
        send_message(uid, "٪ درصد تخفیف را بفرست (مثال 20):", kb([[("انصراف","adm_coupons")]])); return
    if data == "cp_list":
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM coupons ORDER BY active DESC, used DESC")
            rows = cur.fetchall()
        if not rows:
            send_message(uid, "کدی ثبت نشده.", kb([[("↩️ بازگشت","adm_coupons")]]))
        else:
            out = ["🗒 کدها:"]
            kb_rows = []
            for r in rows:
                scope = "همه" if not r["plan_id"] else f"پلن #{r['plan_id']}"
                out.append(f"• {r['code']} | {r['percent']}% | {scope} | استفاده:{r['used']}/{r['max_uses'] or '∞'} | "
                           f"انقضا:{r['expire_at'] or '-'} | {'فعال' if r['active'] else 'غیرفعال'}")
                kb_rows.append([(f"❌ حذف {r['code']}", f"cp_del_{r['code']}")])
            kb_rows.append([("↩️ بازگشت","adm_coupons")])
            send_message(uid, "\n".join(out), kb(kb_rows))
        return
    if data.startswith("cp_del_"):
        code = data.split("_",2)[2]
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM coupons WHERE code=?", (code,))
            con.commit()
        handle_callback({"data":"cp_list","from":{"id":uid},"id":"x","message":{"chat":{"id":uid}}})
        return

    if data == "adm_wallet":
        set_state(uid, "adm_wallet_user", {})
        send_message(uid, "آیدی عددی کاربر را بفرست تا کیف پولش را مدیریت کنیم:", kb([[("انصراف","menu_admin")]])); return

    if data == "adm_receipts":
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM receipts WHERE status='pending' ORDER BY created_at ASC")
            rows = cur.fetchall()
        if not rows:
            send_message(uid, "رسید در انتظار وجود ندارد.", kb([[("↩️ بازگشت","menu_admin")]]))
        else:
            for r in rows:
                cap = (f"#{r['id']} رسید 🧾\n"
                       f"از: <code>{r['user_id']}</code>\n"
                       f"نوع: {r['type']}\n"
                       f"مبلغ: {r['amount']:,}\n"
                       f"وضعیت: pending\n")
                rows_kb = kb([
                    [("✅ تأیید", f"rc_ok_{r['id']}"), ("❌ رد", f"rc_no_{r['id']}")]
                ])
                if r["image_file_id"]:
                    send_photo(uid, r["image_file_id"], cap, rows_kb)
                else:
                    send_message(uid, cap, rows_kb)
        return
    if data.startswith("rc_ok_"):
        rid = data.split("_",2)[2]
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM receipts WHERE id=?", (rid,))
            r = cur.fetchone()
        if not r or r["status"] != "pending":
            send_message(uid, "این رسید معتبر نیست.")
            return
        if r["type"] == "wallet":
            # ادمین باید مبلغ را وارد کند
            set_state(uid, "rc_ok_amount", {"rid": rid})
            send_message(uid, "مبلغ تأیید نهایی (تومان) را وارد کن:", kb([[("انصراف","adm_receipts")]]))
        elif r["type"] == "config":
            # خرید کانفیگ: ارسال خودکار
            receipt_set_status(rid, "approved")
            # اطلاعات سفارش در note ذخیره شده
            try:
                meta = json.loads(r["note"] or "{}")
            except Exception:
                meta = {}
            pid = int(meta.get("plan_id", 0))
            code = meta.get("coupon", "")
            price = int(meta.get("final", 0))
            # ارسال
            ok = finalize_config_purchase(r["user_id"], pid, code, price, from_receipt=True)
            if ok:
                send_message(uid, "سفارش کاربر ارسال شد ✅")
            else:
                send_message(uid, "عدم موجودی مخزن؛ وجه برمی‌گردد.")
                wallet_add(r["user_id"], price, "بازگشت وجه - عدم موجودی")
            return
        return
    if data.startswith("rc_no_"):
        rid = data.split("_",2)[2]
        receipt_set_status(rid, "rejected")
        # اطلاع کاربر
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT user_id FROM receipts WHERE id=?", (rid,))
            u = cur.fetchone()
        if u:
            send_message(u["user_id"], "❌ رسید شما رد شد. برای پیگیری با پشتیبانی در تماس باشید.")
        send_message(uid, "رسید رد شد.")
        return

    if data == "adm_users":
        set_state(uid, "adm_users_wait", {})
        send_message(uid, "آیدی/یوزرنیم را بفرست (مثلا 123 یا @user):", kb([[("انصراف","menu_admin")]])); return

    if data == "adm_broadcast":
        set_state(uid, "broadcast_wait_text", {})
        send_message(uid, "متن اعلان همگانی را بفرست:", kb([[("انصراف","menu_admin")]])); return

    if data == "adm_stats":
        rev, cnt, by_plan, top = stats_summary()
        lines = [f"📊 آمار فروش",
                 f"• تعداد کانفیگ تحویل‌شده: <b>{cnt}</b>",
                 f"• درآمد کل: <b>{rev:,}</b> تومان",
                 "",
                 "فروش به تفکیک پلن:"]
        if not by_plan:
            lines.append("—")
        else:
            for r in by_plan:
                lines.append(f"• {r['name']}: {r['cnt']} عدد | {r['sum']:,} تومان")
        lines.append("")
        lines.append("Top Buyers:")
        if not top:
            lines.append("—")
        else:
            for i, r in enumerate(top, 1):
                uname = f"@{r['uname']}" if r['uname'] else r['uid']
                lines.append(f"{i}) {uname} • تعداد: {r['cnt']} • مجموع: {r['sum']:,}")
        send_message(uid, "\n".join(lines), kb([[("↩️ بازگشت","menu_admin")]]))
        return

# ===== finalize purchase from receipt path =====
def finalize_config_purchase(uid: int, pid: int, coupon: str, final: int, from_receipt: bool) -> bool:
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM plans WHERE id=?", (pid,))
        p = cur.fetchone()
    if not p:
        send_message(uid, "پلن یافت نشد.")
        return False
    cfg = stock_pop(pid)
    if not cfg:
        return False
    order_id = order_create(uid, pid, p["price"], coupon if coupon else None, final)
    exp = (datetime.utcnow() + timedelta(days=int(p["days"]))).strftime("%Y-%m-%d")
    order_set_delivered(order_id, exp)
    if coupon:
        coupon_use_inc(coupon)
    if cfg["photo_file_id"]:
        send_photo(uid, cfg["photo_file_id"], caption=cfg["text_config"] or "")
    else:
        send_message(uid, cfg["text_config"] or "(بدون متن)")
    send_message(uid, f"✅ پلن خریداری شد و ارسال شد.\n⏳ تاریخ انقضا: <b>{exp}</b>")
    return True

# =====================[ MESSAGE HANDLER ]====================

def handle_message(m: dict):
    u = m["from"]
    uid = u["id"]
    ensure_user(u)

    text = m.get("text", "")
    photo = m.get("photo")

    state, data = get_state(uid)

    # ===== دریافت عکس رسید در حالت‌های مرتبط =====
    if photo and state in {"card_receipt_wait", "wallet_wait_amount_exact"}:
        # ذخیره file_id آخرین سایز
        file_id = photo[-1]["file_id"]
        data["photo_file_id"] = file_id
        set_state(uid, state, data)
        send_message(uid, "📷 عکس رسید ذخیره شد. حالا مبلغ را (به تومان) بفرست.")
        return

    # ===== جریان‌های متنی =====
    if state == "wallet_wait_amount":
        amt = digits(text)
        if not amt:
            send_message(uid, "❌ لطفاً فقط عدد وارد کنید:", kb([[("انصراف","menu_wallet")]])); return
        amt = int(amt)
        rid = f"{uid}-{int(time.time())}"
        receipt_create(uid, rid, "wallet", amt, data.get("photo_file_id"), "")
        # اطلاع به ادمین‌ها
        notify_admins_new_receipt(rid)
        clear_state(uid)
        send_message(uid, get_setting("support_note"))
        return

    if state == "wallet_wait_amount_exact":
        need = int(data.get("need", 0))
        amt = digits(text)
        if not amt:
            send_message(uid, "❌ لطفاً فقط عدد وارد کنید:"); return
        amt = int(amt)
        rid = f"{uid}-{int(time.time())}"
        receipt_create(uid, rid, "wallet", amt, data.get("photo_file_id"), "")
        notify_admins_new_receipt(rid)
        clear_state(uid)
        send_message(uid, get_setting("support_note"))
        return

    if state == "coupon_wait_code":
        pid = int(data["plan_id"])
        code = text.strip()
        clear_state(uid)
        show_plan_detail(uid, pid, coupon_code=code)
        return

    if state == "card_receipt_wait":
        pid = int(data["plan_id"])
        code = data.get("coupon", "")
        amt = digits(text)
        photo_file_id = data.get("photo_file_id")
        if not amt and not photo_file_id:
            # ممکنه کاربر اول مبلغ بده یا اول عکس؛ هر دو قابل‌قبول
            # اگر فقط مبلغ فرستاد، ذخیره کن و منتظر عکس نشیم
            amt = digits(text)
        final_amt = int(amt or "0")
        rid = f"{uid}-{int(time.time())}"
        meta = {"plan_id": pid, "coupon": code, "final": final_amt}
        receipt_create(uid, rid, "config", final_amt, photo_file_id, json.dumps(meta))
        notify_admins_new_receipt(rid)
        clear_state(uid)
        send_message(uid, get_setting("support_note"))
        return

    if state == "ticket_wait_text":
        # ایجاد تیکت و ارسال به ادمین
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("INSERT INTO tickets(user_id, status, created_at) VALUES (?,?,?)", (uid, "open", now_str()))
            tid = cur.lastrowid
            cur.execute("INSERT INTO ticket_msgs(ticket_id, from_admin, text, created_at) VALUES (?,?,?,?)",
                        (tid, 0, text, now_str()))
            con.commit()
        clear_state(uid)
        send_message(uid, "✅ تیکت شما ثبت شد. پاسخ از همین گفتگو ارسال می‌شود.", kb([[("بازگشت ↩️","back_home")]]))
        notify_admins_ticket(uid, text)
        return

    if state == "adm_admins_add_wait" and is_admin(uid):
        x = digits(text)
        if not x:
            send_message(uid, "❌ عدد معتبر بفرست."); return
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (int(x),))
            con.commit()
        clear_state(uid)
        send_message(uid, "✅ اضافه شد.", admin_menu()); return

    if state == "adm_admins_del_wait" and is_admin(uid):
        x = digits(text)
        if not x:
            send_message(uid, "❌ عدد معتبر بفرست."); return
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM admins WHERE user_id=?", (int(x),))
            con.commit()
        clear_state(uid)
        send_message(uid, "✅ حذف شد.", admin_menu()); return

    if state == "txt_welcome_wait" and is_admin(uid):
        set_setting("welcome", text)
        clear_state(uid)
        send_message(uid, "✅ ذخیره شد.", admin_menu()); return

    if state == "txt_card_wait" and is_admin(uid):
        set_setting("card_number", text)
        clear_state(uid)
        send_message(uid, "✅ شماره کارت بروزرسانی شد.", admin_menu()); return

    if state == "btn_edit_wait" and is_admin(uid):
        key = data["key"]
        set_setting(key, text)
        clear_state(uid)
        send_message(uid, "✅ برچسب دکمه تغییر کرد.", admin_menu()); return

    if state == "plan_add_name" and is_admin(uid):
        set_state(uid, "plan_add_days", {"name": text})
        send_message(uid, "مدت (روز) را بفرست:"); return
    if state == "plan_add_days" and is_admin(uid):
        d = digits(text)
        if not d: send_message(uid, "فقط عدد روز را بفرست:"); return
        data["days"] = int(d)
        set_state(uid, "plan_add_traffic", data)
        send_message(uid, "حجم (GB) را بفرست:"); return
    if state == "plan_add_traffic" and is_admin(uid):
        t = re.sub(r"[^\d\.]", "", text)
        if not t: send_message(uid, "فقط عدد حجم (مثلا 50):"); return
        data["traffic"] = float(t)
        set_state(uid, "plan_add_price", data)
        send_message(uid, "قیمت (تومان) را بفرست:"); return
    if state == "plan_add_price" and is_admin(uid):
        p = digits(text)
        if not p: send_message(uid, "فقط رقم قیمت:"); return
        data["price"] = int(p)
        set_state(uid, "plan_add_desc", data)
        send_message(uid, "توضیح پلن را بفرست (می‌تونی خالی بگذاری):"); return
    if state == "plan_add_desc" and is_admin(uid):
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("INSERT INTO plans(name, days, traffic_gb, price, desc, active) VALUES (?,?,?,?,?,1)",
                        (data["name"], data["days"], data["traffic"], data["price"], text))
            con.commit()
        clear_state(uid)
        send_message(uid, "✅ پلن اضافه شد.", admin_menu()); return

    if state == "plan_change_field" and is_admin(uid):
        pid = data["pid"]; field = data["field"]
        val = text
        if field in ("days","price"):
            v = digits(val)
            if not v:
                send_message(uid, "فقط رقم معتبر بفرست."); return
            val = int(v)
        if field == "traffic":
            v = re.sub(r"[^\d\.]","", val)
            if not v:
                send_message(uid, "فقط عدد (ممکن است اعشاری) بفرست."); return
            field = "traffic_gb"; val = float(v)
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute(f"UPDATE plans SET {field}=? WHERE id=?", (val, pid))
            con.commit()
        clear_state(uid)
        send_message(uid, "✅ بروزرسانی شد.", admin_menu()); return

    if state == "stock_add_wait_text" and is_admin(uid):
        data["text"] = text
        set_state(uid, "stock_add_wait_photo", data)
        send_message(uid, "اگر عکسی برای این کانفیگ داری بفرست؛ در غیر این صورت «انصراف» را بزن.", kb([[("انصراف","stock_mgmt")]])); return
    if state == "stock_add_wait_photo" and is_admin(uid):
        # ممکن است متن دیگر برسد؛ اگر عکس نیست، بدون عکس ثبت کنیم
        photo_file = None
        # اگر آخرین پیام شامل عکس بود، از مسیر handler عکس ثبت شده بود؛ در غیر این صورت بدون عکس
        # اینجا اگر کاربر «-» یا هر متن دیگری فرستاد، بدون عکس ذخیره می‌کنیم
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("INSERT INTO stock(plan_id, text_config, photo_file_id, created_at) VALUES (?,?,?,?)",
                        (data["pid"], data["text"], data.get("photo"), now_str()))
            con.commit()
        clear_state(uid)
        send_message(uid, "✅ به مخزن اضافه شد.", admin_menu()); return

    if state == "cp_percent" and is_admin(uid):
        n = digits(text)
        if not n:
            send_message(uid, "فقط درصد عددی:"); return
        set_state(uid, "cp_scope", {"percent": int(n)})
        send_message(uid, "کد برای همه پلن‌ها باشد؟\nبله=عدد 0 | یا آیدی پلن خاص را بفرست:", kb([[("انصراف","adm_coupons")]])); return
    if state == "cp_scope" and is_admin(uid):
        pid = int(digits(text) or "0")
        data["plan_id"] = None if pid == 0 else pid
        set_state(uid, "cp_expire_days", data)
        send_message(uid, "مدت اعتبار به روز (مثلا 10). 0 یعنی بدون انقضا:"); return
    if state == "cp_expire_days" and is_admin(uid):
        d = int(digits(text) or "0")
        exp = None
        if d > 0:
            exp = (datetime.utcnow() + timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S")
        data["expire_at"] = exp
        set_state(uid, "cp_max_uses", data)
        send_message(uid, "سقف تعداد استفاده (مثلا 100). 0 یعنی نامحدود:"); return
    if state == "cp_max_uses" and is_admin(uid):
        mu = int(digits(text) or "0")
        data["max_uses"] = mu if mu > 0 else None
        set_state(uid, "cp_code", data)
        send_message(uid, "نام/کد را بفرست (مثلا: OFF20):"); return
    if state == "cp_code" and is_admin(uid):
        code = text.strip().upper()
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("INSERT OR REPLACE INTO coupons(code, percent, plan_id, expire_at, max_uses, active) VALUES (?,?,?,?,?,1)",
                        (code, data["percent"], data["plan_id"], data["expire_at"], data["max_uses"]))
            con.commit()
        clear_state(uid)
        send_message(uid, "✅ کد ساخته شد.", admin_menu()); return

    if state == "adm_wallet_user" and is_admin(uid):
        target = int(digits(text) or "0")
        if not target:
            send_message(uid, "آیدی معتبر بفرست."); return
        set_state(uid, "adm_wallet_action", {"target": target})
        bal = get_wallet(target)
        send_message(uid, f"کاربر <code>{target}</code> | موجودی: {bal:,}\n"
                          f"افزایش یا کاهش؟ عدد مثبت/منفی را بفرست (مثلا 50000 یا -25000):"); return
    if state == "adm_wallet_action" and is_admin(uid):
        amt_str = text.strip().replace(",", "")
        m = re.match(r"^[-+]?\d+$", amt_str)
        if not m:
            send_message(uid, "فقط عدد مثبت/منفی:"); return
        amt = int(amt_str)
        target = data["target"]
        if amt >= 0:
            wallet_add(target, amt, f"شارژ دستی ادمین {uid}")
        else:
            if not wallet_sub(target, -amt, f"کسر دستی ادمین {uid}"):
                send_message(uid, "موجودی کافی برای کسر نیست."); return
        clear_state(uid)
        send_message(uid, "✅ انجام شد.", admin_menu()); return

    if state == "rc_ok_amount" and is_admin(uid):
        rid = data["rid"]
        amt = int(digits(text) or "0")
        if amt <= 0:
            send_message(uid, "عدد معتبر بفرست."); return
        receipt_set_status(rid, "approved")
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("SELECT user_id FROM receipts WHERE id=?", (rid,))
            r = cur.fetchone()
        if r:
            wallet_add(r["user_id"], amt, f"تأیید رسید #{rid}")
            send_message(r["user_id"], f"✅ شارژ {amt:,} تومان تایید شد و به کیف پول شما اضافه شد.")
        clear_state(uid)
        send_message(uid, "✅ شارژ واریز شد.", admin_menu()); return

    if state == "adm_users_wait" and is_admin(uid):
        q = text.strip()
        with _db_lock, db() as con:
            cur = con.cursor()
            if q.startswith("@"):
                cur.execute("SELECT * FROM users WHERE username=?", (q[1:],))
            else:
                cur.execute("SELECT * FROM users WHERE id=?", (int(digits(q) or "0"),))
            u = cur.fetchone()
        if not u:
            send_message(uid, "کاربری یافت نشد."); return
        with _db_lock, db() as con:
            cur = con.cursor()
            cur.execute("""SELECT COUNT(1) c, COALESCE(SUM(final_price),0) s FROM orders 
                           WHERE user_id=? AND delivered=1""", (u["id"],))
            r = cur.fetchone()
        lines = [
            f"👤 آیدی: <code>{u['id']}</code>",
            f"یوزرنیم: @{u['username']}" if u['username'] else "یوزرنیم: -",
            f"موجودی: {u['wallet']:,}",
            f"خریدها: {r['c']} | مجموع: {r['s']:,}"
        ]
        send_message(uid, "\n".join(lines), kb([[("بن/آنبن", f"ban_{u['id']}")],[("↩️ بازگشت","menu_admin")]])); return

    if state == "broadcast_wait_text" and is_admin(uid):
        txt = text
        threading.Thread(target=broadcast_all, args=(txt,)).start()
        clear_state(uid)
        send_message(uid, "✅ در صف ارسال قرار گرفت.", admin_menu()); return

    # اگر هیچ state فعالی نبود:
    show_home(uid)

def broadcast_all(text: str):
    # ارسال به همه کاربران ثبت‌شده
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT id FROM users")
        ids = [r["id"] for r in cur.fetchall()]
    for i, uid in enumerate(ids, 1):
        send_message(uid, text)
        if i % 25 == 0:
            time.sleep(1)

def notify_admins_new_receipt(rid: str):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT user_id,type,amount,image_file_id FROM receipts WHERE id=?", (rid,))
        r = cur.fetchone()
        cur.execute("SELECT user_id FROM admins")
        admins = [a["user_id"] for a in cur.fetchall()]
    cap = (f"#{rid} رسید 🧾\n"
           f"از: <code>{r['user_id']}</code>\n"
           f"نوع: {r['type']}\n"
           f"مبلغ: {r['amount']:,}\n"
           f"وضعیت: pending")
    k = kb([[("✅ تأیید", f"rc_ok_{rid}"), ("❌ رد", f"rc_no_{rid}")]])
    for a in admins:
        if r["image_file_id"]:
            send_photo(a, r["image_file_id"], cap, k)
        else:
            send_message(a, cap, k)

def notify_admins_ticket(uid: int, text: str):
    with _db_lock, db() as con:
        cur = con.cursor()
        cur.execute("SELECT user_id FROM admins")
        admins = [a["user_id"] for a in cur.fetchall()]
    for a in admins:
        send_message(a, f"📩 تیکت جدید از <code>{uid}</code>:\n\n{text}")

# =====================[ WEBHOOK ]====================

@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    upd = request.get_json(force=True, silent=True)
    if not upd:
        return "ok"
    # message
    if "message" in upd:
        m = upd["message"]
        handle_message(m)
    elif "callback_query" in upd:
        handle_callback(upd["callback_query"])
    return "ok"

@app.route("/")
def root():
    return "OK"

# =====================[ REMINDER THREAD ]====================
# نوتیف پایان اعتبار (هر 6 ساعت چک می‌کند)
def reminder_loop():
    while True:
        try:
            days = int(get_setting("expiry_reminder_days", "3") or "3")
            if days <= 0:
                time.sleep(21600); continue
            target_date = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")
            with _db_lock, db() as con:
                cur = con.cursor()
                cur.execute("""SELECT o.id, o.user_id, p.name, o.expire_at FROM orders o 
                               JOIN plans p ON p.id=o.plan_id
                               WHERE o.delivered=1 AND o.expire_at=?""", (target_date,))
                rows = cur.fetchall()
            for r in rows:
                send_message(r["user_id"], f"⏰ یادآوری: پلن «{r['name']}» شما {days} روز دیگر (در {r['expire_at']}) تمام می‌شود.\nبرای تمدید به «خرید پلن» بروید.", main_menu(r["user_id"]))
        except Exception:
            pass
        time.sleep(21600)  # هر 6 ساعت
threading.Thread(target=reminder_loop, daemon=True).start()

# =====================[ GUNICORN ENTRY ]====================
if __name__ == "__main__":
    # اجرای محلی
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
