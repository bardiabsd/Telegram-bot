# -*- coding: utf-8 -*-
# main.py
# Telegram Bot – Plans/WALLET/Receipts/Tickets/Admin Panel – Fully button-based (no slash commands)
# Framework: pyTelegramBotAPI + Flask webhook
# Compatible with Gunicorn: expects `app` in module global.
# Author: (You)
# NOTE: Persian comments kept concise; no problematic Farsi in identifiers.

import os
import json
import time
import uuid
import math
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, abort

import telebot
from telebot import types

# ------------------- Config (env first, then defaults) -------------------
DEFAULT_TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
DEFAULT_APP_URL = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"
BOT_TOKEN = os.getenv("BOT_TOKEN", DEFAULT_TOKEN).strip()
APP_URL = os.getenv("APP_URL", DEFAULT_APP_URL).strip().rstrip("/")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}"

ADMIN_DEFAULT = 1743359080  # آیدی عددی شما

DB_FILE = "db.json"
LOCK = threading.RLock()

# ------------------- Flask & Bot -------------------
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)

# -------- Helpers: db read/write --------
def now_ts():
    return int(time.time())

def jdt(ts=None):
    # نمایش ساده تاریخ/زمان
    if ts is None:
        ts = now_ts()
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

def read_db():
    with LOCK:
        if not os.path.exists(DB_FILE):
            data = {
                "admins": [ADMIN_DEFAULT],
                "buttons": {
                    "enabled": {
                        "buy": True, "wallet": True, "tickets": True,
                        "account": True, "admin": True
                    },
                    "labels": {
                        "menu_buy": "🛒 خرید پلن",
                        "menu_wallet": "🪙 کیف پول",
                        "menu_tickets": "🎫 تیکت پشتیبانی",
                        "menu_account": "👤 حساب کاربری",
                        "menu_admin": "🛠 پنل ادمین",
                        "cancel": "❌ انصراف",
                        "back": "🔙 بازگشت",
                        "pay_wallet": "پرداخت با کیف پول",
                        "pay_card": "کارت‌به‌کارت",
                        "coupon": "🏷 کد تخفیف",
                        "wallet_charge": "➕ شارژ کیف پول",
                        "wallet_history": "📜 تاریخچه",
                        "wallet_shortfall_charge": "شارژ مابه‌التفاوت",
                        "ticket_new": "➕ تیکت جدید",
                        "ticket_my": "📂 تیکت‌های من",
                        "plans_add": "➕ افزودن پلن",
                        "plans_manage": "📦 مدیریت پلن‌ها و مخزن",
                        "coupons": "🏷 مدیریت کد تخفیف",
                        "admins": "👑 مدیریت ادمین‌ها",
                        "buttons_texts": "🧩 دکمه‌ها و متون",
                        "receipts_inbox": "🧾 رسیدها",
                        "wallet_admin": "🪙 کیف پول (ادمین)",
                        "users_admin": "👥 مدیریت کاربران",
                        "broadcast": "📢 اعلان همگانی",
                        "stats": "📊 آمار فروش",
                        "admin_back": "⬅️ بازگشت به پنل ادمین",
                    }
                },
                "cards": {  # شماره کارت برای کارت‌به‌کارت
                    "number": "6037-XXXX-XXXX-XXXX",
                    "holder": "نام صاحب کارت"
                },
                "plans": {},  # plan_id -> {name, days, traffic_gb, price, desc, inventory:[inv_id], active:True}
                "inventory": {},  # inv_id -> {plan_id, text, photo_id(optional)}
                "users": {},  # uid -> {wallet:int_rial, purchases:[{...}], tx:[{...}], username, state:{}}
                "receipts": {},  # rid -> {user_id, kind, amount, plan_id, status, note, photo_id, created_at, reviewed_by}
                "coupons": {},  # code -> {percent, plan_id(or None), max_uses, used, expires_at(ts or None)}
                "tickets": {},  # tid -> {user_id, subject, messages:[{from,user/admin,id,text,ts}], status}
                "orders": [],   # list of {user_id, plan_id, price_paid, coupon_code, ts}
                "settings": {
                    "webhook_set": False,
                    "last_broadcast": None
                }
            }
            write_db(data)
        else:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
    return data

def write_db(data):
    with LOCK:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(uid):
    db = read_db()
    u = db["users"].get(str(uid))
    if not u:
        u = {
            "wallet": 0,
            "purchases": [],
            "tx": [],
            "username": "",
            "state": {}
        }
        db["users"][str(uid)] = u
        write_db(db)
    return u

def set_user(uid, udata):
    db = read_db()
    db["users"][str(uid)] = udata
    write_db(db)

def get_state(uid):
    return get_user(uid).get("state", {})

def set_state(uid, **kwargs):
    u = get_user(uid)
    st = u.get("state", {})
    st.update(kwargs)
    u["state"] = st
    set_user(uid, u)

def clear_state(uid):
    u = get_user(uid)
    u["state"] = {}
    set_user(uid, u)

def is_admin(uid):
    db = read_db()
    return int(uid) in db["admins"]

def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "دسترسی نامعتبر.")
            return
        return func(message, *args, **kwargs)
    return wrapper

def money(num):
    try:
        n = int(num)
    except:
        return str(num)
    return f"{n:,}"

# ---------- Webhook setup ----------
def set_webhook_once():
    db = read_db()
    already = db["settings"].get("webhook_set")
    try:
        bot.delete_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        db["settings"]["webhook_set"] = True
        write_db(db)
        print(f"{jdt()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except telebot.apihelper.ApiTelegramException as e:
        # 429 Too Many Requests را لاگ می‌کنیم ولی نمی‌میریم
        print(f"{jdt()} | ERROR | Failed to set webhook: {e}")
    except Exception as e:
        print(f"{jdt()} | ERROR | Webhook exception: {e}")

# ---------- Keyboards ----------
def main_menu(uid):
    db = read_db()
    en = db["buttons"]["enabled"]
    lb = db["buttons"]["labels"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    if en.get("buy", True): row.append(lb["menu_buy"])
    if en.get("wallet", True): row.append(lb["menu_wallet"])
    if row: kb.add(*row)

    row = []
    if en.get("tickets", True): row.append(lb["menu_tickets"])
    if en.get("account", True): row.append(lb["menu_account"])
    if row: kb.add(*row)

    if is_admin(uid) and en.get("admin", True):
        kb.add(lb["menu_admin"])
    return kb

def cancel_kb():
    db = read_db()
    lb = db["buttons"]["labels"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(lb["cancel"], lb["back"])
    return kb

def back_kb():
    db = read_db()
    lb = db["buttons"]["labels"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(lb["back"])
    return kb

# ---------------- Messages helpers ----------------
def notify_admins(text, reply_markup=None):
    db = read_db()
    for aid in db["admins"]:
        try:
            bot.send_message(aid, text, reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception:
            pass

# ---------------- Plan & Inventory ----------------
def plan_stock_count(plan_id):
    db = read_db()
    p = db["plans"].get(plan_id)
    if not p: return 0
    inv_ids = p.get("inventory", [])
    cnt = 0
    for iid in inv_ids:
        if iid in db["inventory"]:
            cnt += 1
    return cnt

def pick_inventory_item(plan_id):
    db = read_db()
    p = db["plans"].get(plan_id)
    if not p: return None
    inv_ids = p.get("inventory", [])
    for iid in inv_ids:
        if iid in db["inventory"]:
            return iid
    return None

def consume_inventory_item(inv_id):
    db = read_db()
    inv = db["inventory"].pop(inv_id, None)
    if not inv:
        return
    plan_id = inv["plan_id"]
    p = db["plans"].get(plan_id)
    if p and inv_id in p.get("inventory", []):
        p["inventory"].remove(inv_id)
        db["plans"][plan_id] = p
    write_db(db)

# ---------------- Coupons ----------------
def validate_coupon(code, plan_id):
    db = read_db()
    c = db["coupons"].get(code.upper())
    if not c: return (False, "کد تخفیف نامعتبر است.", None)
    # تاریخ انقضا
    exp = c.get("expires_at")
    if exp and now_ts() > int(exp):
        return (False, "مدت اعتبار این کد تمام شده است.", None)
    # سقف استفاده
    mx = c.get("max_uses")
    used = c.get("used", 0)
    if mx is not None and used >= int(mx):
        return (False, "سقف استفاده از این کد پر شده است.", None)
    # محدودیت پلن
    p_lim = c.get("plan_id")
    if p_lim and p_lim != plan_id:
        return (False, "این کد برای این پلن معتبر نیست.", None)
    return (True, "", c)

def apply_coupon(price, percent):
    try:
        price = int(price)
        percent = int(percent)
    except:
        return price
    disc = math.floor(price * percent / 100.0)
    return max(0, price - disc)

def consume_coupon(code):
    db = read_db()
    c = db["coupons"].get(code.upper())
    if not c: return
    c["used"] = int(c.get("used", 0)) + 1
    db["coupons"][code.upper()] = c
    write_db(db)

# ---------------- Tickets ----------------
def create_ticket(uid, subject, first_message=None):
    db = read_db()
    tid = str(uuid.uuid4())
    db["tickets"][tid] = {
        "user_id": uid,
        "subject": subject,
        "messages": [],
        "status": "open",
        "created_at": now_ts()
    }
    if first_message:
        db["tickets"][tid]["messages"].append({
            "from": "user",
            "text": first_message,
            "ts": now_ts()
        })
    write_db(db)
    return tid

# ---------------- Receipts ----------------
def create_receipt(user_id, kind, amount=None, plan_id=None, note=None, photo_id=None):
    db = read_db()
    rid = str(uuid.uuid4())
    db["receipts"][rid] = {
        "user_id": user_id,
        "kind": kind,  # wallet/purchase
        "amount": int(amount) if (amount is not None and str(amount).isdigit()) else None,
        "plan_id": plan_id,
        "status": "pending",
        "note": note,
        "photo_id": photo_id,
        "created_at": now_ts(),
        "reviewed_by": None
    }
    write_db(db)
    return rid

def approve_wallet_receipt(rid, admin_id, amount_value):
    db = read_db()
    rc = db["receipts"].get(rid)
    if not rc or rc["status"] != "pending":
        return (False, "رسید نامعتبر است.")
    uid = rc["user_id"]
    try:
        amount = int(str(amount_value).replace(",", "").strip())
    except:
        return (False, "مبلغ نامعتبر.")
    u = db["users"].get(str(uid))
    if not u:
        return (False, "کاربر پیدا نشد.")
    u["wallet"] = int(u.get("wallet", 0)) + amount
    u["tx"].append({"type": "charge", "amount": amount, "ts": now_ts(), "by": admin_id})
    db["users"][str(uid)] = u
    rc["status"] = "approved"
    rc["reviewed_by"] = admin_id
    rc["amount"] = amount
    db["receipts"][rid] = rc
    write_db(db)
    try:
        bot.send_message(uid, f"✅ شارژ کیف پول شما تأیید شد.\nمبلغ: <b>{money(amount)}</b> تومان")
    except:
        pass
    return (True, "انجام شد.")

def approve_purchase_receipt(rid, admin_id):
    db = read_db()
    rc = db["receipts"].get(rid)
    if not rc or rc["status"] != "pending" or rc.get("kind") != "purchase":
        return (False, "رسید نامعتبر است.")
    uid = rc["user_id"]
    plan_id = rc.get("plan_id")
    inv_id = pick_inventory_item(plan_id)
    if not inv_id:
        return (False, "موجودی این پلن تمام شده.")
    inv = db["inventory"][inv_id]
    # ارسال کانفیگ
    try:
        txt = inv.get("text", "")
        pid = inv.get("photo_id")
        if pid:
            bot.send_photo(uid, pid, caption=txt or "کانفیگ")
        else:
            bot.send_message(uid, txt or "کانفیگ")
    except:
        pass
    # کسر از مخزن + ثبت خرید
    consume_inventory_item(inv_id)
    # ذخیره خرید در پروفایل
    u = db["users"].get(str(uid), {})
    p = db["plans"].get(plan_id, {})
    u.setdefault("purchases", []).append({
        "plan_id": plan_id,
        "ts": now_ts(),
        "price": p.get("price", 0)
    })
    db["users"][str(uid)] = u
    db["orders"].append({
        "user_id": uid,
        "plan_id": plan_id,
        "price_paid": p.get("price", 0),
        "coupon_code": None,
        "ts": now_ts()
    })
    # آپدیت رسید
    rc["status"] = "approved"
    rc["reviewed_by"] = admin_id
    db["receipts"][rid] = rc
    write_db(db)
    try:
        bot.send_message(uid, "✅ خرید شما تأیید شد و کانفیگ ارسال گردید.")
    except:
        pass
    return (True, "انجام شد.")

def reject_receipt(rid, admin_id, reason=""):
    db = read_db()
    rc = db["receipts"].get(rid)
    if not rc or rc["status"] != "pending":
        return (False, "رسید نامعتبر است.")
    rc["status"] = "rejected"
    rc["reviewed_by"] = admin_id
    db["receipts"][rid] = rc
    write_db(db)
    try:
        uid = rc["user_id"]
        bot.send_message(uid, f"❌ رسید شما رد شد. {('علت: ' + reason) if reason else ''}\nدر صورت نیاز با پشتیبانی در تماس باشید.")
    except:
        pass
    return (True, "رد شد.")

# ---------------- Admin UI helpers ----------------
def admin_panel_kb():
    db = read_db()
    lb = db["buttons"]["labels"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    kb.add(lb["plans_manage"], lb["plans_add"])
    kb.add(lb["receipts_inbox"], lb["wallet_admin"])
    kb.add(lb["coupons"], lb["users_admin"])
    kb.add(lb["admins"], lb["buttons_texts"])
    kb.add(lb["broadcast"], lb["stats"])
    kb.add(db["buttons"]["labels"]["back"])
    return kb

# ---------------- User flows ----------------

def show_main_menu(uid, chat_id=None, text="از منوی زیر انتخاب کنید:"):
    kb = main_menu(uid)
    if chat_id is None:
        chat_id = uid
    bot.send_message(chat_id, text, reply_markup=k b)

# ---------- Start & basic ----------
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

# ---------- set webhook on startup ----------
with app.app_context():
    set_webhook_once()

# ======================================================================
# Telegram Handlers
# ======================================================================

# چون همه‌چیز دکمه‌ای‌ست، پیام آزاد را بسته به state مصرف می‌کنیم.
@bot.message_handler(content_types=['text', 'photo', 'document'])
def all_messages(message: types.Message):
    uid = message.from_user.id
    txt = (message.text or "").strip()
    u = get_user(uid)
    # ذخیره یوزرنیم
    if message.from_user.username:
        u["username"] = message.from_user.username
        set_user(uid, u)

    db = read_db()
    lb = db["buttons"]["labels"]
    en = db["buttons"]["enabled"]

    st = get_state(uid)

    # --- Cancel / Back ---
    if txt == lb["cancel"]:
        clear_state(uid)
        bot.send_message(uid, "انصراف انجام شد.", reply_markup=main_menu(uid))
        return
    if txt == lb["back"]:
        clear_state(uid)
        bot.send_message(uid, "بازگشت به منو.", reply_markup=main_menu(uid))
        return

    # ================= Main Menu Buttons =================
    if txt == lb["menu_buy"] and en.get("buy", True):
        # listing plans (with stock)
        if not db["plans"]:
            bot.send_message(uid, "هنوز پلنی ثبت نشده.", reply_markup=main_menu(uid))
            return
        kb = types.InlineKeyboardMarkup()
        for pid, p in db["plans"].items():
            if not p.get("active", True):
                continue
            stock = plan_stock_count(pid)
            title = f"{p['name']} | {money(p['price'])} تومان | موجودی: {stock}"
            btn = types.InlineKeyboardButton(title, callback_data=f"plan:{pid}")
            kb.add(btn)
        bot.send_message(uid, "پلن‌ها:", reply_markup=kb)
        clear_state(uid)
        return

    if txt == lb["menu_wallet"] and en.get("wallet", True):
        bal = int(get_user(uid).get("wallet", 0))
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(lb["wallet_charge"], lb["wallet_history"])
        kb.add(lb["back"])
        bot.send_message(uid, f"موجودی کیف پول شما: <b>{money(bal)}</b> تومان", reply_markup=kb)
        set_state(uid, mode="wallet_menu")
        return

    if txt == lb["menu_tickets"] and en.get("tickets", True):
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(lb["ticket_new"], lb["ticket_my"])
        kb.add(lb["back"])
        bot.send_message(uid, "پشتیبانی:", reply_markup=kb)
        set_state(uid, mode="tickets_menu")
        return

    if txt == lb["menu_account"] and en.get("account", True):
        u = get_user(uid)
        purchases = u.get("purchases", [])
        msg = f"آیدی عددی: <code>{uid}</code>\n" \
              f"یوزرنیم: @{u.get('username') or '-'}\n" \
              f"تعداد کانفیگ‌های خریداری شده: <b>{len(purchases)}</b>\n\n"
        if purchases:
            msg += "سفارش‌های من:\n"
            for i, o in enumerate(reversed(purchases[-10:]), 1):
                p = db["plans"].get(o["plan_id"], {})
                msg += f"{i}. {p.get('name','?')} | {jdt(o['ts'])} | {money(o.get('price',0))} تومان\n"
        bot.send_message(uid, msg, reply_markup=main_menu(uid))
        clear_state(uid)
        return

    if txt == lb["menu_admin"] and is_admin(uid) and en.get("admin", True):
        bot.send_message(uid, "🛠 پنل ادمین", reply_markup=admin_panel_kb())
        set_state(uid, mode="admin")
        return

    # ================== Wallet submenu ==================
    if st.get("mode") == "wallet_menu":
        if txt == lb["wallet_history"]:
            tx = get_user(uid).get("tx", [])
            if not tx:
                bot.send_message(uid, "تاریخچه‌ای نیست.", reply_markup=back_kb())
            else:
                lines = []
                for t in reversed(tx[-15:]):
                    if t["type"] == "charge":
                        lines.append(f"شارژ +{money(t['amount'])} | {jdt(t['ts'])}")
                    elif t["type"] == "pay":
                        lines.append(f"خرید -{money(t['amount'])} | {jdt(t['ts'])}")
                bot.send_message(uid, "تاریخچه:\n" + "\n".join(lines), reply_markup=back_kb())
            return
        if txt == lb["wallet_charge"]:
            # کاربر رسید را بفرستد → رسید در حالت wallet ثبت می‌شود
            bot.send_message(uid, "لطفاً رسید پرداخت را (عکس یا متن) ارسال کنید.\n"
                                  "در صورت تمایل، مبلغ هم بنویسید.\n"
                                  "پس از ارسال، منتظر تأیید ادمین بمانید.", reply_markup=cancel_kb())
            set_state(uid, mode="wallet_receipt_wait")
            return

    if st.get("mode") == "wallet_receipt_wait":
        # کاربر هرچی فرستاد، رسید ثبت می‌شود
        photo_id = None
        note = None
        if message.photo:
            photo_id = message.photo[-1].file_id
        if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
            photo_id = message.document.file_id
        if message.caption:
            note = message.caption.strip()
        elif message.text:
            note = message.text.strip()
        rid = create_receipt(uid, kind="wallet", amount=None, plan_id=None, note=note, photo_id=photo_id)
        clear_state(uid)
        bot.send_message(uid, "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین…", reply_markup=main_menu(uid))
        # اطلاع به ادمین‌ها
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ تأیید (ورود مبلغ)", callback_data=f"rcw_ok:{rid}"))
        kb.add(types.InlineKeyboardButton("❌ رد", callback_data=f"rc_rej:{rid}"))
        preview = f"🧾 رسید شارژ کیف پول\n" \
                  f"کاربر: {uid} @{get_user(uid).get('username') or '-'}\n" \
                  f"متن: {note or '-'}\n" \
                  f"زمان: {jdt()}"
        notify_admins(preview, reply_markup=kb)
        return

    # ================== Tickets submenu ==================
    if st.get("mode") == "tickets_menu":
        if txt == lb["ticket_new"]:
            bot.send_message(uid, "موضوع تیکت را وارد کنید:", reply_markup=cancel_kb())
            set_state(uid, mode="ticket_subject")
            return
        if txt == lb["ticket_my"]:
            db = read_db()
            my = [ (tid, t) for tid, t in db["tickets"].items() if t["user_id"] == uid ]
            if not my:
                bot.send_message(uid, "هیچ تیکتی ندارید.", reply_markup=back_kb())
                return
            kb = types.InlineKeyboardMarkup()
            for tid, t in sorted(my, key=lambda x: x[1]["created_at"], reverse=True)[:15]:
                kb.add(types.InlineKeyboardButton(f"{t['subject']} | {t['status']} | {jdt(t['created_at'])}",
                                                  callback_data=f"ticket_view:{tid}"))
            bot.send_message(uid, "تیکت‌های شما:", reply_markup=kb)
            return

    if st.get("mode") == "ticket_subject":
        subject = txt
        set_state(uid, mode="ticket_body", subject=subject)
        bot.send_message(uid, "متن پیام تیکت را بنویسید:", reply_markup=cancel_kb())
        return

    if st.get("mode") == "ticket_body":
        subject = st.get("subject", "بدون موضوع")
        body = txt if txt else "(بدون متن)"
        tid = create_ticket(uid, subject, body)
        clear_state(uid)
        bot.send_message(uid, f"تیکت شما ثبت شد. کد: <code>{tid}</code>", reply_markup=main_menu(uid))
        # اطلاع ادمین
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✉️ پاسخ", callback_data=f"t_reply:{tid}"))
        notify_admins(f"🎫 تیکت جدید\nکاربر: {uid} @{get_user(uid).get('username') or '-'}\n"
                      f"موضوع: {subject}\nمتن: {body}\nزمان: {jdt()}", reply_markup=kb)
        return

    # ================== Admin mode ==================
    if st.get("mode") == "admin" and is_admin(uid):
        # دکمه‌های پنل ادمین
        if txt == db["buttons"]["labels"]["plans_add"]:
            bot.send_message(uid, "نام پلن را وارد کنید:", reply_markup=cancel_kb())
            set_state(uid, mode="admin_add_plan", step="name")
            return
        if txt == db["buttons"]["labels"]["plans_manage"]:
            # لیست پلن‌ها + مدیریت مخزن
            if not db["plans"]:
                bot.send_message(uid, "پلنی وجود ندارد.", reply_markup=admin_panel_kb())
                return
            kb = types.InlineKeyboardMarkup()
            for pid, p in db["plans"].items():
                stock = plan_stock_count(pid)
                kb.add(types.InlineKeyboardButton(f"{p['name']} | موجودی: {stock}", callback_data=f"plan_mng:{pid}"))
            bot.send_message(uid, "مدیریت پلن‌ها:", reply_markup=kb)
            return
        if txt == db["buttons"]["labels"]["receipts_inbox"]:
            # اینباکس رسیدهای pending
            pend = [(rid, r) for rid, r in db["receipts"].items() if r["status"] == "pending"]
            if not pend:
                bot.send_message(uid, "رسید در انتظار نداریم.", reply_markup=admin_panel_kb())
                return
            kb = types.InlineKeyboardMarkup()
            for rid, r in sorted(pend, key=lambda x: x[1]["created_at"], reverse=True)[:15]:
                title = f"{'شارژ' if r['kind']=='wallet' else 'خرید'} | {r['user_id']} | {jdt(r['created_at'])}"
                kb.add(types.InlineKeyboardButton(title, callback_data=f"rc_view:{rid}"))
            bot.send_message(uid, "رسیدهای در انتظار:", reply_markup=kb)
            return
        if txt == db["buttons"]["labels"]["wallet_admin"]:
            bot.send_message(uid, "آیدی عددی کاربر را بفرستید:", reply_markup=cancel_kb())
            set_state(uid, mode="admin_wallet", step="uid")
            return
        if txt == db["buttons"]["labels"]["coupons"]:
            # مدیریت کد تخفیف: ساخت/لیست
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("➕ ساخت کد جدید", callback_data="coupon_new"))
            if db["coupons"]:
                kb.add(types.InlineKeyboardButton("📜 لیست کدها", callback_data="coupon_list"))
            bot.send_message(uid, "مدیریت کد تخفیف:", reply_markup=kb)
            return
        if txt == db["buttons"]["labels"]["users_admin"]:
            bot.send_message(uid, "برای جستجوی کاربر، آیدی عددی یا یوزرنیم را وارد کنید (مثال: 123456 یا @user):", reply_markup=cancel_kb())
            set_state(uid, mode="admin_user_search")
            return
        if txt == db["buttons"]["labels"]["admins"]:
            # مدیریت ادمین‌ها
            kb = types.InlineKeyboardMarkup()
            for aid in db["admins"]:
                kb.add(types.InlineKeyboardButton(f"❌ حذف {aid}", callback_data=f"adm_del:{aid}"))
            kb.add(types.InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm_add"))
            bot.send_message(uid, "👑 لیست ادمین‌ها:", reply_markup=kb)
            return
        if txt == db["buttons"]["labels"]["buttons_texts"]:
            # روشن/خاموش و ویرایش نام دکمه‌ها
            kb = types.InlineKeyboardMarkup()
            for key, val in db["buttons"]["enabled"].items():
                stx = "✅" if val else "🚫"
                kb.add(types.InlineKeyboardButton(f"{stx} {key}", callback_data=f"btn_tgl:{key}"))
            kb.add(types.InlineKeyboardButton("✏️ ویرایش متن یک دکمه", callback_data="btn_edit"))
            bot.send_message(uid, "🧩 مدیریت دکمه‌ها و متون:", reply_markup=kb)
            return
        if txt == db["buttons"]["labels"]["broadcast"]:
            bot.send_message(uid, "متن اعلان همگانی را ارسال کنید:", reply_markup=cancel_kb())
            set_state(uid, mode="admin_broadcast")
            return
        if txt == db["buttons"]["labels"]["stats"]:
            # آمار فروش
            orders = db["orders"]
            total_count = len(orders)
            total_amount = sum(int(o.get("price_paid", 0)) for o in orders)
            # خریداران برتر
            agg = {}
            for o in orders:
                uid2 = o["user_id"]
                agg.setdefault(uid2, {"amount": 0, "count": 0, "plans": {}})
                agg[uid2]["amount"] += int(o.get("price_paid", 0))
                agg[uid2]["count"] += 1
                pl = o["plan_id"]
                agg[uid2]["plans"][pl] = agg[uid2]["plans"].get(pl, 0) + 1
            tops = sorted(agg.items(), key=lambda x: x[1]["amount"], reverse=True)[:10]
            msg = f"📊 آمار فروش\nتعداد فروش: <b>{total_count}</b>\nمجموع فروش: <b>{money(total_amount)}</b> تومان\n\n"
            if tops:
                msg += "Top Buyers:\n"
                for i, (u_id, datax) in enumerate(tops, 1):
                    best_plan = None
                    if datax["plans"]:
                        best_plan = max(datax["plans"].items(), key=lambda x: x[1])[0]
                    msg += f"{i}. {u_id} | تعداد: {datax['count']} | مجموع: {money(datax['amount'])} | بیشترین پلن: {db['plans'].get(best_plan,{}).get('name','-')}\n"
            else:
                msg += "فعلاً خریدی ثبت نشده."
            bot.send_message(uid, msg, reply_markup=admin_panel_kb())
            return

    # -------- Admin add plan wizard --------
    if st.get("mode") == "admin_add_plan":
        step = st.get("step")
        if step == "name":
            set_state(uid, mode="admin_add_plan", step="days", name=txt)
            bot.send_message(uid, "مدت (روز) را وارد کنید:", reply_markup=cancel_kb())
            return
        if step == "days":
            if not txt.isdigit():
                bot.send_message(uid, "فقط عدد وارد کنید.", reply_markup=cancel_kb())
                return
            set_state(uid, mode="admin_add_plan", step="traffic", days=int(txt))
            bot.send_message(uid, "حجم (GB) را وارد کنید:", reply_markup=cancel_kb())
            return
        if step == "traffic":
            if not txt.isdigit():
                bot.send_message(uid, "فقط عدد وارد کنید.", reply_markup=cancel_kb())
                return
            set_state(uid, mode="admin_add_plan", step="price", traffic=int(txt))
            bot.send_message(uid, "قیمت (تومان) را وارد کنید:", reply_markup=cancel_kb())
            return
        if step == "price":
            val = str(txt).replace(",", "").strip()
            if not val.isdigit():
                bot.send_message(uid, "قیمت عددی وارد کنید.", reply_markup=cancel_kb())
                return
            set_state(uid, mode="admin_add_plan", step="desc", price=int(val))
            bot.send_message(uid, "توضیحات پلن را بفرستید:", reply_markup=cancel_kb())
            return
        if step == "desc":
            db = read_db()
            pid = str(uuid.uuid4())
            name = st["name"]
            days = st["days"]
            traffic = st["traffic"]
            price = st["price"]
            desc = txt
            db["plans"][pid] = {
                "name": name,
                "days": days,
                "traffic_gb": traffic,
                "price": price,
                "desc": desc,
                "inventory": [],
                "active": True
            }
            write_db(db)
            clear_state(uid)
            bot.send_message(uid, f"پلن «{name}» اضافه شد.", reply_markup=admin_panel_kb())
            return

    # -------- Admin manage wallet --------
    if st.get("mode") == "admin_wallet":
        step = st.get("step")
        if step == "uid":
            rec_uid = txt.lstrip("@")
            if rec_uid.isdigit():
                set_state(uid, mode="admin_wallet", step="action", target_uid=int(rec_uid))
                kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
                kb.add("➕ شارژ", "➖ کسر")
                kb.add(lb["back"])
                bot.send_message(uid, "عملیات را انتخاب کنید:", reply_markup=kb)
                return
            else:
                bot.send_message(uid, "آیدی عددی نامعتبر.", reply_markup=cancel_kb())
                return
        if step == "action":
            if txt not in ["➕ شارژ", "➖ کسر"]:
                bot.send_message(uid, "از دکمه‌ها استفاده کنید.", reply_markup=cancel_kb())
                return
            set_state(uid, mode="admin_wallet", step="amount", action=txt)
            bot.send_message(uid, "مبلغ را وارد کنید (فقط عدد):", reply_markup=cancel_kb())
            return
        if step == "amount":
            val = str(txt).replace(",", "").strip()
            if not val.isdigit():
                bot.send_message(uid, "مبلغ نامعتبر.", reply_markup=cancel_kb())
                return
            amount = int(val)
            db = read_db()
            tuid = st["target_uid"]
            u2 = db["users"].get(str(tuid))
            if not u2:
                bot.send_message(uid, "کاربر یافت نشد.", reply_markup=admin_panel_kb())
                clear_state(uid)
                return
            if st["action"] == "➕ شارژ":
                u2["wallet"] = int(u2.get("wallet", 0)) + amount
                u2.setdefault("tx", []).append({"type": "charge", "amount": amount, "ts": now_ts(), "by": uid})
                db["users"][str(tuid)] = u2
                write_db(db)
                bot.send_message(uid, "انجام شد.", reply_markup=admin_panel_kb())
                try:
                    bot.send_message(tuid, f"حساب شما توسط ادمین شارژ شد: +{money(amount)} تومان")
                except:
                    pass
            else:
                u2["wallet"] = max(0, int(u2.get("wallet", 0)) - amount)
                u2.setdefault("tx", []).append({"type": "pay", "amount": amount, "ts": now_ts(), "by": uid})
                db["users"][str(tuid)] = u2
                write_db(db)
                bot.send_message(uid, "کسر شد.", reply_markup=admin_panel_kb())
                try:
                    bot.send_message(tuid, f"از حساب شما توسط ادمین کسر شد: -{money(amount)} تومان")
                except:
                    pass
            clear_state(uid)
            return

    # -------- Admin user search --------
    if st.get("mode") == "admin_user_search" and is_admin(uid):
        db = read_db()
        key = txt.strip()
        found = None
        if key.startswith("@"):
            key = key[1:]
        # جستجو
        for k, v in db["users"].items():
            if key.isdigit() and int(k) == int(key):
                found = (int(k), v)
                break
            if v.get("username") and v["username"].lower() == key.lower():
                found = (int(k), v)
                break
        if not found:
            bot.send_message(uid, "کاربر پیدا نشد.", reply_markup=admin_panel_kb())
            clear_state(uid)
            return
        tuid, v = found
        purchases = v.get("purchases", [])
        msg = f"👤 کاربر: <b>{tuid}</b>\nیوزرنیم: @{v.get('username') or '-'}\n" \
              f"کیف پول: {money(v.get('wallet',0))}\n" \
              f"تعداد خرید: {len(purchases)}\n"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💼 شارژ/کسر کیف پول", callback_data=f"usr_wallet:{tuid}"))
        bot.send_message(uid, msg, reply_markup=kb)
        clear_state(uid)
        return

    # -------- Buttons edit (text) flow --------
    if st.get("mode") == "btn_edit_key" and is_admin(uid):
        key = txt.strip()
        db = read_db()
        if key not in db["buttons"]["labels"]:
            bot.send_message(uid, "کلید یافت نشد.", reply_markup=admin_panel_kb())
            clear_state(uid)
            return
        set_state(uid, mode="btn_edit_val", key=key)
        bot.send_message(uid, f"متن جدید برای {key} را ارسال کنید:", reply_markup=cancel_kb())
        return

    if st.get("mode") == "btn_edit_val" and is_admin(uid):
        new_value = txt
        db = read_db()
        key = st["key"]
        db["buttons"]["labels"][key] = new_value
        write_db(db)
        bot.send_message(uid, "بروزرسانی شد.", reply_markup=admin_panel_kb())
        clear_state(uid)
        return

    # -------- Coupon creation wizard --------
    if st.get("mode") == "coupon_new":
        step = st.get("step")
        if step == "percent":
            val = str(txt).replace("%", "").strip()
            if not val.isdigit() or not (1 <= int(val) <= 100):
                bot.send_message(uid, "درصد بین 1 تا 100 وارد کنید.", reply_markup=cancel_kb())
                return
            set_state(uid, mode="coupon_new", step="plan", percent=int(val))
            # انتخاب پلن یا همه
            db = read_db()
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("همه پلن‌ها", callback_data="coupon_plan:ALL"))
            for pid, p in db["plans"].items():
                kb.add(types.InlineKeyboardButton(p["name"], callback_data=f"coupon_plan:{pid}"))
            bot.send_message(uid, "محدودیت پلن را انتخاب کنید:", reply_markup=kb)
            return
        if step == "max_uses":
            val = str(txt).strip()
            if val.lower() in ["نامحدود", "infinite", "none"]:
                set_state(uid, mode="coupon_new", step="expires", max_uses=None)
                bot.send_message(uid, "تاریخ انقضا را وارد کنید (YYYY-MM-DD) یا «ندارد»:", reply_markup=cancel_kb())
                return
            if not val.isdigit():
                bot.send_message(uid, "عدد یا «ندارد/نامحدود» وارد کنید.", reply_markup=cancel_kb())
                return
            set_state(uid, mode="coupon_new", step="expires", max_uses=int(val))
            bot.send_message(uid, "تاریخ انقضا را وارد کنید (YYYY-MM-DD) یا «ندارد»:", reply_markup=cancel_kb())
            return
        if step == "expires":
            val = txt.strip()
            exp_ts = None
            if val not in ["ندارد", "none", "بدون"]:
                try:
                    dt = datetime.strptime(val, "%Y-%m-%d")
                    exp_ts = int(dt.timestamp())
                except:
                    bot.send_message(uid, "فرمت تاریخ نامعتبر.", reply_markup=cancel_kb())
                    return
            set_state(uid, mode="coupon_new", step="code", expires=exp_ts)
            bot.send_message(uid, "نام/کد کد تخفیف را وارد کنید (حروف/عدد بدون فاصله):", reply_markup=cancel_kb())
            return
        if step == "code":
            code = txt.strip().upper().replace(" ", "")
            if not code:
                bot.send_message(uid, "کد نامعتبر.", reply_markup=cancel_kb())
                return
            db = read_db()
            if code in db["coupons"]:
                bot.send_message(uid, "این کد وجود دارد.", reply_markup=cancel_kb())
                return
            percent = st["percent"]
            plan_sel = st.get("plan_id")  # ممکن است None باشد (همه)
            mx = st.get("max_uses")
            exp = st.get("expires")
            db["coupons"][code] = {
                "percent": percent,
                "plan_id": plan_sel,
                "max_uses": mx,
                "used": 0,
                "expires_at": exp
            }
            write_db(db)
            clear_state(uid)
            bot.send_message(uid, f"کد {code} با درصد {percent}% ساخته شد.", reply_markup=admin_panel_kb())
            return

    # -------- Purchase flow state handling --------
    if st.get("mode") == "buy_plan":
        # انتظار وارد کردن کد تخفیف یا انتخاب روش پرداخت
        pass  # handled via callback buttons; free text here نادیده

    # -------- Fallback ----------
    # اگر هیچ‌کدوم نخورد و state خاصی نبود:
    if not st:
        # نمایش منوی اصلی
        bot.send_message(uid, "سلام! از منوی زیر استفاده کنید.", reply_markup=main_menu(uid))
    else:
        # در حالت‌های ناهمخوان:
        bot.send_message(uid, "از دکمه‌ها استفاده کنید یا «انصراف/بازگشت».", reply_markup=cancel_kb())


# ======================================================================
# Callback handlers
# ======================================================================

@bot.callback_query_handler(func=lambda c: True)
def callbacks(c: types.CallbackQuery):
    uid = c.from_user.id
    db = read_db()
    lb = db["buttons"]["labels"]

    def answer(t=None):
        try:
            bot.answer_callback_query(c.id, t, show_alert=False)
        except:
            pass

    data = c.data or ""

    # ---------- Plans: show details ----------
    if data.startswith("plan:"):
        pid = data.split(":", 1)[1]
        p = db["plans"].get(pid)
        if not p:
            answer("پلن یافت نشد.")
            return
        stock = plan_stock_count(pid)
        msg = f"<b>{p['name']}</b>\nقیمت: {money(p['price'])} تومان\nمدت: {p['days']} روز | حجم: {p['traffic_gb']}GB\n" \
              f"موجودی مخزن: {stock}\n\n{p['desc']}"
        kb = types.InlineKeyboardMarkup()
        if stock > 0:
            kb.add(types.InlineKeyboardButton(lb["coupon"], callback_data=f"coupon_enter:{pid}"))
            kb.add(types.InlineKeyboardButton(lb["pay_wallet"], callback_data=f"pay_wallet:{pid}"))
            kb.add(types.InlineKeyboardButton(lb["pay_card"], callback_data=f"pay_card:{pid}"))
        bot.edit_message_text(msg, c.message.chat.id, c.message.message_id, reply_markup=kb)
        set_state(uid, mode="buy_plan", plan_id=pid, coupon=None)
        return

    # ---------- Coupon enter ----------
    if data.startswith("coupon_enter:"):
        pid = data.split(":", 1)[1]
        set_state(uid, mode="buy_plan", plan_id=pid, step="coupon_wait")
        bot.send_message(uid, "کد تخفیف را وارد کنید:", reply_markup=cancel_kb())
        return

    # ---------- Pay with wallet ----------
    if data.startswith("pay_wallet:"):
        pid = data.split(":", 1)[1]
        p = db["plans"].get(pid)
        if not p:
            answer("پلن یافت نشد.")
            return
        st = get_state(uid)
        coupon_code = st.get("coupon")
        price = p["price"]
        if coupon_code:
            ok, err, cpn = validate_coupon(coupon_code, pid)
            if ok:
                price = apply_coupon(price, cpn["percent"])
            else:
                # حذف کوپن نامعتبر
                set_state(uid, coupon=None)
        bal = get_user(uid).get("wallet", 0)
        if bal >= price:
            # کسر و ارسال کانفیگ
            u = get_user(uid)
            u["wallet"] = bal - price
            u.setdefault("tx", []).append({"type": "pay", "amount": price, "ts": now_ts()})
            set_user(uid, u)
            inv_id = pick_inventory_item(pid)
            if not inv_id:
                bot.send_message(uid, "موجودی این پلن تمام شده.", reply_markup=main_menu(uid))
                return
            inv = db["inventory"][inv_id]
            # ارسال
            try:
                if inv.get("photo_id"):
                    bot.send_photo(uid, inv["photo_id"], caption=inv.get("text") or "کانفیگ")
                else:
                    bot.send_message(uid, inv.get("text") or "کانفیگ")
            except:
                pass
            consume_inventory_item(inv_id)
            # ثبت سفارش + مصرف کوپن
            order = {"user_id": uid, "plan_id": pid, "price_paid": price, "coupon_code": coupon_code, "ts": now_ts()}
            db = read_db()
            db["orders"].append(order)
            if coupon_code:
                consume_coupon(coupon_code)
            # ذخیره در پروفایل
            u = get_user(uid)
            u["purchases"].append({"plan_id": pid, "ts": now_ts(), "price": price})
            set_user(uid, u)
            write_db(db)
            clear_state(uid)
            bot.send_message(uid, "✅ خرید با کیف پول انجام شد و کانفیگ ارسال شد.", reply_markup=main_menu(uid))
        else:
            shortfall = price - bal
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add(db["buttons"]["labels"]["wallet_shortfall_charge"], lb["cancel"])
            set_state(uid, mode="wallet_shortfall", amount=shortfall, plan_id=pid, coupon=coupon_code)
            bot.send_message(uid, f"موجودی کافی نیست. مابه‌التفاوت: <b>{money(shortfall)}</b> تومان\n"
                                  "برای ادامه، رسید پرداخت مابه‌التفاوت را بفرستید.", reply_markup=kb)
        return

    # ---------- Pay card-to-card ----------
    if data.startswith("pay_card:"):
        pid = data.split(":", 1)[1]
        p = db["plans"].get(pid)
        if not p:
            answer("پلن یافت نشد.")
            return
        st = get_state(uid)
        coupon_code = st.get("coupon")
        price = p["price"]
        if coupon_code:
            ok, err, cpn = validate_coupon(coupon_code, pid)
            if ok:
                price = apply_coupon(price, cpn["percent"])
        card = db["cards"]
        bot.send_message(uid,
                         f"اطلاعات کارت برای کارت‌به‌کارت:\n"
                         f"<b>{card.get('number','-')}</b>\n"
                         f"به نام: {card.get('holder','-')}\n\n"
                         "پس از واریز، رسید (عکس یا متن) را همینجا ارسال کنید.",
                         reply_markup=cancel_kb())
        set_state(uid, mode="card_receipt_wait", plan_id=pid, expected=price, coupon=coupon_code)
        return

    # ---------- Admin: plan manage ----------
    if data.startswith("plan_mng:") and is_admin(uid):
        pid = data.split(":", 1)[1]
        p = db["plans"].get(pid)
        if not p:
            answer("پلن یافت نشد.")
            return
        stock = plan_stock_count(pid)
        msg = f"پلن: <b>{p['name']}</b>\nقیمت: {money(p['price'])}\nموجودی: {stock}\n"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ افزودن کانفیگ به مخزن", callback_data=f"inv_add:{pid}"))
        kb.add(types.InlineKeyboardButton("📦 لیست مخزن", callback_data=f"inv_list:{pid}"))
        sw = "غیرفعال" if p.get("active", True) else "فعال"
        kb.add(types.InlineKeyboardButton(f"🔁 {sw} کردن پلن", callback_data=f"plan_toggle:{pid}"))
        kb.add(types.InlineKeyboardButton("🗑 حذف پلن", callback_data=f"plan_del:{pid}"))
        try:
            bot.edit_message_text(msg, c.message.chat.id, c.message.message_id, reply_markup=kb)
        except:
            bot.send_message(uid, msg, reply_markup=kb)
        return

    if data.startswith("inv_add:") and is_admin(uid):
        pid = data.split(":", 1)[1]
        set_state(uid, mode="inv_add", plan_id=pid, step="text")
        bot.send_message(uid, "متن/کانفیگ را ارسال کنید (می‌توانید بعداً عکس هم بفرستید).", reply_markup=cancel_kb())
        return

    if data.startswith("inv_list:") and is_admin(uid):
        pid = data.split(":", 1)[1]
        invs = [ (iid, v) for iid, v in db["inventory"].items() if v["plan_id"] == pid ]
        if not invs:
            bot.send_message(uid, "برای این پلن کانفیگی در مخزن نیست.", reply_markup=admin_panel_kb())
            return
        kb = types.InlineKeyboardMarkup()
        for iid, v in invs[:20]:
            title = (v.get("text") or "متن")[:30]
            kb.add(types.InlineKeyboardButton(f"🗑 حذف | {title}", callback_data=f"inv_del:{iid}"))
        bot.send_message(uid, "مخزن:", reply_markup=kb)
        return

    if data.startswith("inv_del:") and is_admin(uid):
        iid = data.split(":", 1)[1]
        inv = db["inventory"].get(iid)
        if not inv:
            answer("یافت نشد.")
            return
        consume_inventory_item(iid)  # حذف از inventory و حذف لینک از plan.inventory
        bot.send_message(uid, "حذف شد.", reply_markup=admin_panel_kb())
        return

    if data.startswith("plan_toggle:") and is_admin(uid):
        pid = data.split(":", 1)[1]
        p = db["plans"].get(pid)
        if not p:
            answer("پلن یافت نشد.")
            return
        p["active"] = not p.get("active", True)
        db["plans"][pid] = p
        write_db(db)
        answer("بروزرسانی شد.")
        return

    if data.startswith("plan_del:") and is_admin(uid):
        pid = data.split(":", 1)[1]
        p = db["plans"].pop(pid, None)
        if p:
            # حذف inventory های مربوط
            for iid in list(db["inventory"].keys()):
                if db["inventory"][iid]["plan_id"] == pid:
                    db["inventory"].pop(iid, None)
            write_db(db)
        answer("پلن حذف شد.")
        return

    # ---------- Admin: receipts ----------
    if data.startswith("rc_view:") and is_admin(uid):
        rid = data.split(":", 1)[1]
        r = db["receipts"].get(rid)
        if not r:
            answer("یافت نشد.")
            return
        msg = f"🧾 رسید\nنوع: {'شارژ کیف پول' if r['kind']=='wallet' else 'خرید'}\n" \
              f"کاربر: {r['user_id']} @{db['users'].get(str(r['user_id']),{}).get('username','-')}\n" \
              f"وضعیت: {r['status']}\n" \
              f"زمان: {jdt(r['created_at'])}\n" \
              f"پلن: {db['plans'].get(r.get('plan_id'),{}).get('name','-')}\n" \
              f"مبلغ: {money(r.get('amount') or 0)}\n" \
              f"توضیح: {r.get('note') or '-'}"
        kb = types.InlineKeyboardMarkup()
        if r["kind"] == "wallet":
            kb.add(types.InlineKeyboardButton("✅ تأیید (ورود مبلغ)", callback_data=f"rcw_ok:{rid}"))
        else:
            kb.add(types.InlineKeyboardButton("✅ تأیید خرید", callback_data=f"rcp_ok:{rid}"))
        kb.add(types.InlineKeyboardButton("❌ رد", callback_data=f"rc_rej:{rid}"))
        if r.get("photo_id"):
            try:
                bot.send_photo(uid, r["photo_id"], caption=msg, reply_markup=kb)
            except:
                bot.send_message(uid, msg, reply_markup=kb)
        else:
            bot.send_message(uid, msg, reply_markup=kb)
        return

    if data.startswith("rcw_ok:") and is_admin(uid):
        rid = data.split(":", 1)[1]
        # درخواست ورود مبلغ
        set_state(uid, mode="rc_wallet_amount", rid=rid)
        bot.send_message(uid, "مبلغ تأیید شارژ را وارد کنید (فقط عدد):", reply_markup=cancel_kb())
        return

    if data.startswith("rcp_ok:") and is_admin(uid):
        rid = data.split(":", 1)[1]
        ok, msg = approve_purchase_receipt(rid, uid)
        answer(msg)
        return

    if data.startswith("rc_rej:") and is_admin(uid):
        rid = data.split(":", 1)[1]
        set_state(uid, mode="rc_reject_reason", rid=rid)
        bot.send_message(uid, "علت رد را وارد کنید (اختیاری؛ می‌توانید خالی بفرستید):", reply_markup=cancel_kb())
        return

    # ---------- Admin: admins manage ----------
    if data.startswith("adm_del:") and is_admin(uid):
        aid = int(data.split(":", 1)[1])
        if aid == ADMIN_DEFAULT:
            answer("نمی‌توان ادمین پیش‌فرض را حذف کرد.")
            return
        db["admins"] = [a for a in db["admins"] if int(a) != aid]
        write_db(db)
        answer("حذف شد.")
        return

    if data == "adm_add" and is_admin(uid):
        set_state(uid, mode="adm_add", step="uid")
        bot.send_message(uid, "آیدی عددی ادمین جدید را وارد کنید:", reply_markup=cancel_kb())
        return

    # ---------- Admin: buttons toggle/edit ----------
    if data.startswith("btn_tgl:") and is_admin(uid):
        key = data.split(":", 1)[1]
        if key in db["buttons"]["enabled"]:
            db["buttons"]["enabled"][key] = not db["buttons"]["enabled"][key]
            write_db(db)
            answer("ذخیره شد.")
        else:
            answer("کلید نامعتبر.")
        return

    if data == "btn_edit" and is_admin(uid):
        set_state(uid, mode="btn_edit_key")
        bot.send_message(uid, "نام کلید (labels) را بفرستید. مثال: menu_buy یا cancel ...", reply_markup=cancel_kb())
        return

    # ---------- Coupon manage ----------
    if data == "coupon_new" and is_admin(uid):
        set_state(uid, mode="coupon_new", step="percent")
        bot.send_message(uid, "درصد تخفیف (1..100):", reply_markup=cancel_kb())
        return

    if data == "coupon_list" and is_admin(uid):
        if not db["coupons"]:
            bot.send_message(uid, "کدی وجود ندارد.", reply_markup=admin_panel_kb())
            return
        kb = types.InlineKeyboardMarkup()
        for code, cpn in db["coupons"].items():
            stx = "فعال" if (not cpn.get("expires_at") or now_ts() <= cpn["expires_at"]) else "منقضی"
            kb.add(types.InlineKeyboardButton(f"{code} | {cpn['percent']}% | {stx} | used:{cpn.get('used',0)}",
                                              callback_data=f"coupon_view:{code}"))
        bot.send_message(uid, "لیست کدها:", reply_markup=kb)
        return

    if data.startswith("coupon_view:") and is_admin(uid):
        code = data.split(":", 1)[1]
        cpn = db["coupons"].get(code)
        if not cpn:
            answer("یافت نشد.")
            return
        msg = f"کد: <b>{code}</b>\nدرصد: {cpn['percent']}%\n" \
              f"پلن: {db['plans'].get(cpn.get('plan_id'),{}).get('name','همه')}\n" \
              f"سقف استفاده: {cpn.get('max_uses','بدون')}\n" \
              f"استفاده‌شده: {cpn.get('used',0)}\n" \
              f"انقضا: {jdt(cpn['expires_at']) if cpn.get('expires_at') else 'ندارد'}"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🗑 حذف کد", callback_data=f"coupon_del:{code}"))
        bot.send_message(uid, msg, reply_markup=kb)
        return

    if data.startswith("coupon_del:") and is_admin(uid):
        code = data.split(":", 1)[1]
        if code in db["coupons"]:
            db["coupons"].pop(code, None)
            write_db(db)
            answer("حذف شد.")
        else:
            answer("یافت نشد.")
        return

    if data.startswith("coupon_plan:") and is_admin(uid):
        sel = data.split(":", 1)[1]
        if sel == "ALL":
            set_state(uid, mode="coupon_new", step="max_uses", plan_id=None)
        else:
            set_state(uid, mode="coupon_new", step="max_uses", plan_id=sel)
        bot.send_message(uid, "سقف تعداد استفاده (عدد یا «نامحدود»):", reply_markup=cancel_kb())
        return

    # ---------- Tickets admin reply ----------
    if data.startswith("t_reply:") and is_admin(uid):
        tid = data.split(":", 1)[1]
        if tid not in db["tickets"]:
            answer("یافت نشد.")
            return
        set_state(uid, mode="ticket_admin_reply", tid=tid)
        bot.send_message(uid, "متن پاسخ را بنویسید:", reply_markup=cancel_kb())
        return

    # ---------- Coupon apply text flow will set in message handler ----------
    # ---------- Admin user wallet shortcut ----------
    if data.startswith("usr_wallet:") and is_admin(uid):
        tuid = int(data.split(":", 1)[1])
        set_state(uid, mode="admin_wallet", step="action", target_uid=tuid)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("➕ شارژ", "➖ کسر")
        kb.add(lb["back"])
        bot.send_message(uid, "عملیات را انتخاب کنید:", reply_markup=kb)
        return

    answer()  # default silent ack


# ======================================================================
# Additional typed states (amount inputs, coupon, inventory add, receipts reject, etc.)
# ======================================================================

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("mode") in ["rc_wallet_amount",
                                                                              "rc_reject_reason",
                                                                              "ticket_admin_reply",
                                                                              "inv_add",
                                                                              "wallet_shortfall",
                                                                              "buy_plan",
                                                                              "admin_broadcast",
                                                                              "adm_add"])
def admin_extra_inputs(message: types.Message):
    uid = message.from_user.id
    txt = (message.text or "").strip()
    st = get_state(uid)
    db = read_db()
    lb = db["buttons"]["labels"]

    # -------- Approve wallet receipt amount --------
    if st.get("mode") == "rc_wallet_amount" and is_admin(uid):
        rid = st.get("rid")
        ok, msg = approve_wallet_receipt(rid, uid, txt)
        clear_state(uid)
        bot.send_message(uid, msg, reply_markup=admin_panel_kb())
        return

    # -------- Reject receipt reason --------
    if st.get("mode") == "rc_reject_reason" and is_admin(uid):
        rid = st.get("rid")
        ok, msg = reject_receipt(rid, uid, txt)
        clear_state(uid)
        bot.send_message(uid, msg, reply_markup=admin_panel_kb())
        return

    # -------- Ticket admin reply --------
    if st.get("mode") == "ticket_admin_reply" and is_admin(uid):
        tid = st.get("tid")
        t = db["tickets"].get(tid)
        if not t:
            clear_state(uid)
            bot.send_message(uid, "تیکت یافت نشد.", reply_markup=admin_panel_kb())
            return
        t["messages"].append({"from": "admin", "text": txt, "ts": now_ts()})
        db["tickets"][tid] = t
        write_db(db)
        clear_state(uid)
        # notify user
        try:
            bot.send_message(t["user_id"], f"📩 پاسخ به تیکت «{t['subject']}»:\n{txt}")
        except:
            pass
        bot.send_message(uid, "ارسال شد.", reply_markup=admin_panel_kb())
        return

    # -------- Inventory add wizard --------
    if st.get("mode") == "inv_add" and is_admin(uid):
        step = st.get("step")
        if step == "text":
            set_state(uid, mode="inv_add", step="photo", text=txt)
            bot.send_message(uid, "در صورت نیاز تصویر/اسکرین کانفیگ را بفرستید یا «بازگشت» برای رد کردن.", reply_markup=cancel_kb())
            return
        if step == "photo":
            # اگر اینجا متن داد و عکس نداد، همون را ثبت کنیم
            pid = st.get("plan_id")
            inv_id = str(uuid.uuid4())
            photo_id = None
            if message.photo:
                photo_id = message.photo[-1].file_id
            db["inventory"][inv_id] = {"plan_id": pid, "text": st.get("text"), "photo_id": photo_id}
            db["plans"][pid]["inventory"].append(inv_id)
            write_db(db)
            clear_state(uid)
            bot.send_message(uid, "به مخزن اضافه شد.", reply_markup=admin_panel_kb())
            return

    # -------- Wallet shortfall receipt (user) --------
    if st.get("mode") == "wallet_shortfall":
        shortfall = st.get("amount")
        plan_id = st.get("plan_id")
        coupon_code = st.get("coupon")
        photo_id = None
        note = None
        if message.photo:
            photo_id = message.photo[-1].file_id
        if message.caption:
            note = message.caption.strip()
        elif message.text:
            note = message.text.strip()
        rid = create_receipt(uid, kind="wallet", amount=shortfall, plan_id=None, note=note, photo_id=photo_id)
        clear_state(uid)
        bot.send_message(uid, "✅ رسید مابه‌التفاوت ثبت شد؛ منتظر تأیید ادمین…", reply_markup=main_menu(uid))
        # اطلاع به ادمین‌ها
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ تأیید (ورود مبلغ)", callback_data=f"rcw_ok:{rid}"))
        kb.add(types.InlineKeyboardButton("❌ رد", callback_data=f"rc_rej:{rid}"))
        notify_admins(f"🧾 رسید مابه‌التفاوت برای خرید پلن\nکاربر: {uid}\nمبلغ پیشنهادی: {money(shortfall)}",
                      reply_markup=kb)
        # ذخیره state خرید بعد از تأیید (کاربر لازم نیست کاری کند)
        # این سناریو را ساده نگه می‌داریم: پس از شارژ دستی، کاربر مجدد با کیف پول می‌خرد.

    # -------- Buy plan coupon code (free text) --------
    if st.get("mode") == "buy_plan" and st.get("step") == "coupon_wait":
        pid = st.get("plan_id")
        code = txt.strip().upper()
        ok, err, cpn = validate_coupon(code, pid)
        if not ok:
            bot.send_message(uid, err, reply_markup=cancel_kb())
            return
        set_state(uid, mode="buy_plan", plan_id=pid, coupon=code)
        bot.send_message(uid, "✅ کد تخفیف اعمال شد. مجدداً روش پرداخت را انتخاب کنید.", reply_markup=back_kb())
        return

    # -------- Admin broadcast --------
    if st.get("mode") == "admin_broadcast" and is_admin(uid):
        text_to_send = txt
        db = read_db()
        count = 0
        for k in list(db["users"].keys()):
            try:
                bot.send_message(int(k), text_to_send)
                count += 1
            except:
                pass
        db["settings"]["last_broadcast"] = now_ts()
        write_db(db)
        bot.send_message(uid, f"ارسال شد به {count} کاربر.", reply_markup=admin_panel_kb())
        clear_state(uid)
        return

    # -------- Admin add new admin --------
    if st.get("mode") == "adm_add" and st.get("step") == "uid" and is_admin(uid):
        if not txt.isdigit():
            bot.send_message(uid, "آیدی عددی صحیح نیست.", reply_markup=cancel_kb())
            return
        new_id = int(txt)
        db = read_db()
        if new_id in db["admins"]:
            bot.send_message(uid, "این کاربر قبلاً ادمین است.", reply_markup=admin_panel_kb())
            clear_state(uid)
            return
        db["admins"].append(new_id)
        write_db(db)
        bot.send_message(uid, "ادمین اضافه شد.", reply_markup=admin_panel_kb())
        clear_state(uid)
        return


# ======================================================================
# Photo/doc handlers specifically for card receipt waiting
# ======================================================================

@bot.message_handler(content_types=['photo', 'document'], func=lambda m: get_state(m.from_user.id).get("mode") == "card_receipt_wait")
def card_receipt_handler(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    pid = st.get("plan_id")
    expected = st.get("expected")
    coupon = st.get("coupon")
    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        photo_id = message.document.file_id
    note = message.caption or None
    rid = create_receipt(uid, kind="purchase", amount=expected, plan_id=pid, note=note, photo_id=photo_id)
    clear_state(uid)
    bot.send_message(uid, "✅ رسید خرید ثبت شد؛ منتظر تأیید ادمین…", reply_markup=main_menu(uid))
    # اطلاع ادمین
    db = read_db()
    p = db["plans"].get(pid, {})
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ تأیید خرید", callback_data=f"rcp_ok:{rid}"))
    kb.add(types.InlineKeyboardButton("❌ رد", callback_data=f"rc_rej:{rid}"))
    notify_admins(f"🧾 رسید خرید پلن\nکاربر: {uid} @{get_user(uid).get('username') or '-'}\n"
                  f"پلن: {p.get('name','-')}\n"
                  f"مبلغ: {money(expected)}\n"
                  f"زمان: {jdt()}", reply_markup=kb)

# اگر کاربر به‌جای عکس، متن فرستاد در card_receipt_wait:
@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("mode") == "card_receipt_wait", content_types=['text'])
def card_receipt_text(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    pid = st.get("plan_id")
    expected = st.get("expected")
    note = message.text.strip()
    rid = create_receipt(uid, kind="purchase", amount=expected, plan_id=pid, note=note)
    clear_state(uid)
    bot.send_message(uid, "✅ رسید خرید ثبت شد؛ منتظر تأیید ادمین…", reply_markup=main_menu(uid))
    # اطلاع ادمین
    db = read_db()
    p = db["plans"].get(pid, {})
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ تأیید خرید", callback_data=f"rcp_ok:{rid}"))
    kb.add(types.InlineKeyboardButton("❌ رد", callback_data=f"rc_rej:{rid}"))
    notify_admins(f"🧾 رسید خرید پلن\nکاربر: {uid} @{get_user(uid).get('username') or '-'}\n"
                  f"پلن: {p.get('name','-')}\n"
                  f"مبلغ: {money(expected)}\n"
                  f"زمان: {jdt()}", reply_markup=kb)

# ======================================================================
# Run (gunicorn will import `app`)
# ======================================================================

# هیچ run محلی اینجا نمی‌گذاریم تا فقط با gunicorn اجرا شود.
# Procfile شما باید چیزی شبیه این باشد:
# web: gunicorn main:app --workers 2 --bind 0.0.0.0:$PORT
