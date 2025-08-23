# main.py
# -*- coding: utf-8 -*-

import os
import json
import time
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from flask import Flask, request, abort
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

# -----------------------------
# Config & Constants
# -----------------------------
# توکن بات: از env بخوان؛ اگر نبود، از توکن داده‌شده استفاده می‌شود
BOT_TOKEN = os.getenv("BOT_TOKEN", "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo").strip()
APP_URL = os.getenv("APP_URL", "https://live-avivah-bardiabsd-cd8d676a.koyeb.app").rstrip("/")
WEBHOOK_URL = f"{APP_URL}/webhook/{BOT_TOKEN}"

# Admin default
DEFAULT_ADMIN_ID = 1743359080  # آیدی عددی شما

DATA_FILE = "data.json"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True)
app = Flask(__name__)

# -----------------------------
# Persistence Helpers
# -----------------------------
def _now_ts():
    return int(time.time())

def load_db():
    if not os.path.exists(DATA_FILE):
        db = {
            "admins": [DEFAULT_ADMIN_ID],
            "users": {},               # user_id -> {username, first_name, joined_at, wallet, stats, ...}
            "plans": {},               # plan_id -> {...}
            "inventory": {},           # plan_id -> [items] (each item: {id, type: text/photo/file, content, caption, added_by})
            "orders": [],              # [{user_id, plan_id, price, coupon_code, ts, expires_at}]
            "wallets": {},             # user_id -> balance (int)
            "receipts": {},            # receipt_id -> {user_id, kind, status, amount?, message?, media?, ts}
            "tickets": {},             # ticket_id -> {user_id, status, messages:[{from, text, ts}], subject}
            "coupons": {},             # code -> {percent, plan_limit (None or plan_id), max_use, used, expires_at_ts}
            "buttons": {               # ALL labels centralized. Admin can modify via UI
                "home_title": "منوی اصلی",
                "btn_buy": "🛒 خرید پلن",
                "btn_wallet": "🪙 کیف پول",
                "btn_tickets": "🎫 تیکت پشتیبانی",
                "btn_orders": "🧾 سفارش‌های من",
                "btn_account": "👤 حساب کاربری",
                "btn_cancel": "انصراف",
                "btn_back": "↩️ بازگشت",
                "btn_admin": "🛠 پنل ادمین",
                "btn_broadcast": "📢 اعلان همگانی",
                "btn_admins": "👑 مدیریت ادمین‌ها",
                "btn_plans": "📦 مدیریت پلن‌ها",
                "btn_inventory": "📦 مخزن هر پلن",
                "btn_coupons": "🏷 کد تخفیف",
                "btn_wallet_admin": "🪙 کیف پول (ادمین)",
                "btn_receipts": "🧾 رسیدها",
                "btn_users": "👥 مدیریت کاربران",
                "btn_stats": "📊 آمار فروش",
                "btn_texts": "🧩 مدیریت دکمه‌ها و متون",
                "btn_toggle": "🔘 روشن/خاموش دکمه‌ها",
                "btn_set_card": "💳 تنظیم شماره کارت",
                "btn_set_welcome": "✨ تنظیم خوش‌آمدگویی",
                "btn_add_plan": "➕ افزودن پلن",
                "btn_edit_plan": "✏️ ویرایش پلن",
                "btn_del_plan": "🗑 حذف پلن",
                "btn_add_to_wallet": "➕ شارژ کیف پول",
                "btn_buy_with_wallet": "💳 پرداخت با کیف پول",
                "btn_buy_with_card": "🏦 کارت‌به‌کارت",
                "btn_enter_coupon": "🏷 وارد کردن کد تخفیف",
                "btn_clear_coupon": "❌ حذف کد تخفیف",
                "btn_my_tickets": "📂 تیکت‌های من",
                "btn_new_ticket": "📝 ایجاد تیکت",
                "btn_inventory_manage": "📦 مدیریت مخزن پلن",
                "btn_inventory_add": "➕ افزودن کانفیگ",
                "btn_inventory_list": "📄 لیست کانفیگ‌ها",
                "btn_inventory_back": "⬅️ برگشت به پلن‌ها",
            },
            "visibility": {            # فعال/غیرفعال بودن دکمه‌های منوی کاربر
                "buy": True,
                "wallet": True,
                "tickets": True,
                "orders": True,
                "account": True
            },
            "settings": {
                "card_number": "6037-xxxxxxxx-xxxx",   # شماره کارت پیش‌فرض
                "welcome_message": "سلام! خوش اومدی 👋\nاز منوی زیر انتخاب کن.",
                "expire_days": 30                      # برای محاسبه پایان اعتبار پلن
            },
            "states": {}               # user_id -> {mode, payload, ...}
        }
        save_db(db)
        return db
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

db = load_db()

def is_admin(uid: int) -> bool:
    return uid in db.get("admins", [])

def set_state(uid: int, mode: str = None, payload: dict = None):
    s = db["states"].get(str(uid), {})
    if mode is None:
        # clear
        if str(uid) in db["states"]:
            del db["states"][str(uid)]
    else:
        s["mode"] = mode
        s["payload"] = payload or {}
        db["states"][str(uid)] = s
    save_db(db)

def get_state(uid: int):
    return db["states"].get(str(uid), None)

def clear_state(uid: int):
    if str(uid) in db["states"]:
        del db["states"][str(uid)]
        save_db(db)

def get_user_or_create(message):
    u = message.from_user
    uid = u.id
    user = db["users"].get(str(uid))
    if not user:
        user = {
            "id": uid,
            "username": (u.username or "")[:64],
            "first_name": (u.first_name or "")[:128],
            "joined_at": _now_ts(),
            "wallet": 0,
            "orders_count": 0,
        }
        db["users"][str(uid)] = user
        save_db(db)
    else:
        # update username/first name
        changed = False
        if user.get("username") != (u.username or ""):
            user["username"] = (u.username or "")
            changed = True
        if user.get("first_name") != (u.first_name or ""):
            user["first_name"] = (u.first_name or "")
            changed = True
        if changed:
            save_db(db)
    return user

# -----------------------------
# Keyboards
# -----------------------------
def kb_home(uid):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    v = db["visibility"]
    b = db["buttons"]
    row = []
    if v.get("buy"): row.append(types.KeyboardButton(b["btn_buy"]))
    if v.get("wallet"): row.append(types.KeyboardButton(b["btn_wallet"]))
    if row: k.row(*row)
    row = []
    if v.get("tickets"): row.append(types.KeyboardButton(b["btn_tickets"]))
    if v.get("orders"): row.append(types.KeyboardButton(b["btn_orders"]))
    if row: k.row(*row)
    k.row(types.KeyboardButton(b["btn_account"]))
    if is_admin(uid):
        k.row(types.KeyboardButton(b["btn_admin"]))
    return k

def kb_cancel_back():
    b = db["buttons"]
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    k.add(types.KeyboardButton(b["btn_cancel"]), types.KeyboardButton(b["btn_back"]))
    return k

def kb_admin():
    b = db["buttons"]
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton(b["btn_plans"]), types.KeyboardButton(b["btn_inventory"]))
    k.row(types.KeyboardButton(b["btn_coupons"]), types.KeyboardButton(b["btn_wallet_admin"]))
    k.row(types.KeyboardButton(b["btn_receipts"]), types.KeyboardButton(b["btn_users"]))
    k.row(types.KeyboardButton(b["btn_texts"]), types.KeyboardButton(b["btn_toggle"]))
    k.row(types.KeyboardButton(b["btn_set_card"]), types.KeyboardButton(b["btn_set_welcome"]))
    k.row(types.KeyboardButton(b["btn_broadcast"]), types.KeyboardButton(b["btn_stats"]))
    k.row(types.KeyboardButton(db["buttons"]["btn_back"]))
    return k

def kb_plans_for_user(uid, include_back=True):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    b = db["buttons"]
    # Show plans with stock
    row = []
    for pid, p in db["plans"].items():
        stock = len(db["inventory"].get(pid, []))
        label = f"{p['name']} ({stock} موجود)"
        row.append(types.KeyboardButton(label))
        if len(row) == 2:
            k.row(*row); row=[]
    if row: k.row(*row)
    k.row(types.KeyboardButton(b["btn_back"]))
    return k

def kb_buy_actions():
    b = db["buttons"]
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    k.add(types.KeyboardButton(b["btn_buy_with_wallet"]),
          types.KeyboardButton(b["btn_buy_with_card"]))
    k.add(types.KeyboardButton(b["btn_enter_coupon"]))
    k.add(types.KeyboardButton(b["btn_clear_coupon"]),
          types.KeyboardButton(b["btn_cancel"]))
    return k

def kb_wallet_user():
    b = db["buttons"]
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    k.add(types.KeyboardButton(b["btn_add_to_wallet"]), types.KeyboardButton(b["btn_back"]))
    return k

def kb_inventory_admin():
    b = db["buttons"]
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    k.add(types.KeyboardButton(b["btn_inventory_add"]), types.KeyboardButton(b["btn_inventory_list"]))
    k.add(types.KeyboardButton(b["btn_inventory_back"]))
    return k

# -----------------------------
# Helpers (plans/inventory/orders/wallet/etc)
# -----------------------------
def list_plans():
    # returns [(id, name, price, days, size, desc, stock)]
    out = []
    for pid, p in db["plans"].items():
        stock = len(db["inventory"].get(pid, []))
        out.append((pid, p["name"], p["price"], p["days"], p["size"], p.get("desc",""), stock))
    # sort by name
    out.sort(key=lambda x: x[1])
    return out

def find_plan_by_label(label: str):
    # expects "<name> (X موجود)"
    name = label.split(" (")[0].strip()
    for pid, p in db["plans"].items():
        if p["name"] == name:
            return pid, p
    return None, None

def calculate_price_with_coupon(base_price: int, coupon: dict):
    if not coupon: return base_price, 0
    percent = int(coupon.get("percent", 0))
    discount = (base_price * percent) // 100
    final = max(0, base_price - discount)
    return final, discount

def give_inventory_item(plan_id: str):
    items = db["inventory"].get(plan_id, [])
    if not items:
        return None
    # FIFO
    item = items.pop(0)
    db["inventory"][plan_id] = items
    save_db(db)
    return item

def record_order(user_id, plan_id, price, coupon_code=None):
    p = db["plans"][plan_id]
    expire_days = int(db["settings"].get("expire_days", 30))
    expires_at = _now_ts() + expire_days * 24 * 3600
    order = {
        "id": str(uuid4()),
        "user_id": user_id,
        "plan_id": plan_id,
        "price": price,
        "coupon_code": coupon_code,
        "ts": _now_ts(),
        "expires_at": expires_at
    }
    db["orders"].append(order)
    # inc user stats
    db["users"][str(user_id)]["orders_count"] = db["users"][str(user_id)].get("orders_count",0) + 1
    save_db(db)
    return order

def format_money(v: int):
    s = f"{v:,}".replace(",", "٬")
    return f"{s} تومان"

def username_link(uid):
    u = db["users"].get(str(uid), {})
    uname = u.get("username") or ""
    if uname:
        return f"@{uname} ({uid})"
    return str(uid)

def send_config_to_user(user_id, item):
    # item: {type: text/photo/file, content, caption?}
    if item["type"] == "text":
        bot.send_message(user_id, item["content"])
    elif item["type"] == "photo":
        bot.send_photo(user_id, item["content"], caption=item.get("caption") or "")
    elif item["type"] == "file":
        bot.send_document(user_id, item["content"], caption=item.get("caption") or "")
    else:
        bot.send_message(user_id, "کانفیگ آماده ارسال بود ولی نوع ناشناخته بود.")

# -----------------------------
# Webhook (Flask)
# -----------------------------
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
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
        logging.info(f"Webhook set to: {WEBHOOK_URL}")
    except ApiTelegramException as e:
        logging.error(f"Failed to set webhook: {e}")

# -----------------------------
# Entry Buttons / Home
# -----------------------------
def show_home(uid):
    b = db["buttons"]
    bot.send_message(uid, db["settings"]["welcome_message"], reply_markup=kb_home(uid))

@bot.message_handler(content_types=['text'])
def on_text(message: types.Message):
    uid = message.from_user.id
    txt = (message.text or "").strip()
    get_user_or_create(message)

    # Global cancel/back
    if txt == db["buttons"]["btn_cancel"]:
        clear_state(uid); show_home(uid); return
    if txt == db["buttons"]["btn_back"]:
        clear_state(uid); show_home(uid); return

    # Admin panel button
    if txt == db["buttons"]["btn_admin"]:
        if is_admin(uid):
            bot.send_message(uid, "🛠 به پنل ادمین خوش آمدید:", reply_markup=kb_admin())
            clear_state(uid)
            return
        else:
            bot.send_message(uid, "شما ادمین نیستید.", reply_markup=kb_home(uid))
            return

    # Route by state first (to حل مشکل «از دکمه‌ها…»)
    st = get_state(uid)
    if st and st.get("mode"):
        if handle_stateful_text(uid, message, st):
            return

    # No state → handle menu
    b = db["buttons"]

    # Home entries
    if txt == b["btn_buy"]:
        show_plans_for_user(uid); return
    if txt == b["btn_wallet"]:
        show_wallet(uid); return
    if txt == b["btn_tickets"]:
        show_ticket_menu(uid); return
    if txt == b["btn_orders"]:
        show_my_orders(uid); return
    if txt == b["btn_account"]:
        show_account(uid); return

    # Admin entries
    if is_admin(uid):
        if txt == b["btn_broadcast"]:
            bot.send_message(uid, "متن اعلام همگانی را بفرستید:", reply_markup=kb_cancel_back())
            set_state(uid, "await_broadcast_text")
            return
        if txt == b["btn_admins"]:
            manage_admins_menu(uid); return
        if txt == b["btn_plans"]:
            manage_plans_menu(uid); return
        if txt == b["btn_inventory"]:
            choose_plan_for_inventory(uid); return
        if txt == b["btn_coupons"]:
            coupons_menu(uid); return
        if txt == b["btn_wallet_admin"]:
            wallet_admin_menu(uid); return
        if txt == b["btn_receipts"]:
            list_pending_receipts(uid); return
        if txt == b["btn_users"]:
            users_menu(uid); return
        if txt == b["btn_texts"]:
            edit_texts_menu(uid); return
        if txt == b["btn_toggle"]:
            toggle_visibility_menu(uid); return
        if txt == b["btn_set_card"]:
            bot.send_message(uid, "شماره کارت جدید را ارسال کنید:", reply_markup=kb_cancel_back())
            set_state(uid, "await_card_number")
            return
        if txt == b["btn_set_welcome"]:
            bot.send_message(uid, "متن خوش‌آمدگویی جدید را ارسال کنید:", reply_markup=kb_cancel_back())
            set_state(uid, "await_welcome_text")
            return

    # Maybe plan selected?
    pid, p = find_plan_by_label(txt)
    if p:
        # show plan details & buy actions
        show_plan_detail(uid, pid)
        return

    # Fallback
    bot.send_message(uid, "از دکمه‌ها استفاده کنید یا «انصراف/بازگشت».", reply_markup=kb_home(uid))

@bot.message_handler(content_types=['photo', 'document'])
def on_media(message: types.Message):
    uid = message.from_user.id
    get_user_or_create(message)
    st = get_state(uid)
    if st and st.get("mode"):
        if handle_stateful_media(uid, message, st):
            return
    bot.send_message(uid, "از دکمه‌ها استفاده کنید یا «انصراف/بازگشت».", reply_markup=kb_home(uid))

# -----------------------------
# Stateful Handlers
# -----------------------------
def handle_stateful_text(uid: int, message: types.Message, st: dict) -> bool:
    txt = (message.text or "").strip()
    mode = st["mode"]
    payload = st.get("payload", {})

    # --- Broadcast ---
    if mode == "await_broadcast_text":
        # send to all users
        clear_state(uid)
        send_broadcast(uid, txt)
        return True

    # --- Admins manage ---
    if mode == "await_admin_id_to_add":
        if txt.isdigit():
            aid = int(txt)
            if aid in db["admins"]:
                bot.send_message(uid, "این آیدی قبلا ادمین است.", reply_markup=kb_admin())
            else:
                db["admins"].append(aid)
                save_db(db)
                bot.send_message(uid, f"ادمین {aid} افزوده شد.", reply_markup=kb_admin())
            clear_state(uid)
        else:
            bot.send_message(uid, "آیدی عددی معتبر وارد کنید.", reply_markup=kb_cancel_back())
        return True

    if mode == "await_admin_id_to_remove":
        if txt.isdigit():
            aid = int(txt)
            if aid == DEFAULT_ADMIN_ID and len(db["admins"]) == 1:
                bot.send_message(uid, "نمی‌توانید آخرین ادمین را حذف کنید.", reply_markup=kb_admin())
            elif aid in db["admins"]:
                db["admins"] = [x for x in db["admins"] if x != aid]
                save_db(db)
                bot.send_message(uid, f"ادمین {aid} حذف شد.", reply_markup=kb_admin())
            else:
                bot.send_message(uid, "این آیدی در لیست ادمین‌ها نیست.", reply_markup=kb_admin())
            clear_state(uid)
        else:
            bot.send_message(uid, "آیدی عددی معتبر وارد کنید.", reply_markup=kb_cancel_back())
        return True

    # --- Set Card Number ---
    if mode == "await_card_number":
        db["settings"]["card_number"] = txt
        save_db(db)
        bot.send_message(uid, f"شماره کارت به‌روزرسانی شد:\n<code>{txt}</code>", reply_markup=kb_admin())
        clear_state(uid)
        return True

    # --- Set Welcome Text ---
    if mode == "await_welcome_text":
        db["settings"]["welcome_message"] = txt
        save_db(db)
        bot.send_message(uid, "متن خوش‌آمدگویی به‌روزرسانی شد.", reply_markup=kb_admin())
        clear_state(uid)
        return True

    # --- Plans manage ---
    if mode == "await_new_plan_name":
        payload["name"] = txt
        set_state(uid, "await_new_plan_price", payload)
        bot.send_message(uid, "قیمت (تومان) را وارد کنید:", reply_markup=kb_cancel_back())
        return True

    if mode == "await_new_plan_price":
        if txt.isdigit():
            payload["price"] = int(txt)
            set_state(uid, "await_new_plan_days", payload)
            bot.send_message(uid, "مدت (روز) را وارد کنید:", reply_markup=kb_cancel_back())
        else:
            bot.send_message(uid, "قیمت باید عدد باشد.", reply_markup=kb_cancel_back())
        return True

    if mode == "await_new_plan_days":
        if txt.isdigit():
            payload["days"] = int(txt)
            set_state(uid, "await_new_plan_size", payload)
            bot.send_message(uid, "حجم پلن (مثلاً 100GB) را وارد کنید:", reply_markup=kb_cancel_back())
        else:
            bot.send_message(uid, "مدت باید عدد باشد.", reply_markup=kb_cancel_back())
        return True

    if mode == "await_new_plan_size":
        payload["size"] = txt
        set_state(uid, "await_new_plan_desc", payload)
        bot.send_message(uid, "توضیحات پلن (اختیاری):", reply_markup=kb_cancel_back())
        return True

    if mode == "await_new_plan_desc":
        payload["desc"] = txt
        # save
        pid = str(uuid4())
        db["plans"][pid] = {
            "id": pid,
            "name": payload["name"],
            "price": payload["price"],
            "days": payload["days"],
            "size": payload["size"],
            "desc": payload.get("desc","")
        }
        db["inventory"][pid] = []
        save_db(db)
        bot.send_message(uid, "پلن افزوده شد.", reply_markup=kb_admin())
        clear_state(uid)
        return True

    if mode == "await_edit_plan_pick":
        # expects selection by plan label
        pid, p = find_plan_by_label(txt)
        if not p:
            bot.send_message(uid, "پلن معتبر انتخاب کنید.", reply_markup=kb_plans_for_user(uid))
            return True
        payload["plan_id"] = pid
        set_state(uid, "await_edit_plan_field", payload)
        bot.send_message(uid, "کدام را ویرایش کنیم؟\nنام | قیمت | روز | حجم | توضیح", reply_markup=kb_cancel_back())
        return True

    if mode == "await_edit_plan_field":
        field_map = {"نام":"name", "قیمت":"price", "روز":"days", "حجم":"size", "توضیح":"desc"}
        fkey = field_map.get(txt)
        if not fkey:
            bot.send_message(uid, "یکی از موارد: نام/قیمت/روز/حجم/توضیح", reply_markup=kb_cancel_back())
            return True
        payload["field"] = fkey
        set_state(uid, "await_edit_plan_value", payload)
        bot.send_message(uid, "مقدار جدید را بفرستید:", reply_markup=kb_cancel_back())
        return True

    if mode == "await_edit_plan_value":
        pid = payload["plan_id"]
        fkey = payload["field"]
        if fkey in ("price","days"):
            if not txt.isdigit():
                bot.send_message(uid, "باید عدد باشد.", reply_markup=kb_cancel_back())
                return True
            val = int(txt)
        else:
            val = txt
        db["plans"][pid][fkey] = val
        save_db(db)
        bot.send_message(uid, "به‌روزرسانی شد.", reply_markup=kb_admin()); clear_state(uid)
        return True

    if mode == "await_delete_plan_pick":
        pid, p = find_plan_by_label(txt)
        if not p:
            bot.send_message(uid, "پلن معتبر انتخاب کنید.", reply_markup=kb_plans_for_user(uid))
            return True
        # delete
        db["plans"].pop(pid, None)
        db["inventory"].pop(pid, None)
        save_db(db)
        bot.send_message(uid, "پلن حذف شد.", reply_markup=kb_admin()); clear_state(uid)
        return True

    # --- Inventory add expects text (but media handled separately) ---
    if mode == "await_inventory_pick_plan":
        pid, p = find_plan_by_label(txt)
        if not p:
            bot.send_message(uid, "پلن معتبر انتخاب کنید.", reply_markup=kb_plans_for_user(uid))
            return True
        payload["plan_id"] = pid
        set_state(uid, "await_inventory_add_item", payload)
        bot.send_message(uid, "کانفیگ را ارسال کنید (متن/عکس/فایل).", reply_markup=kb_cancel_back())
        return True

    if mode == "await_inventory_add_item":
        # text config
        pid = payload["plan_id"]
        itm = {
            "id": str(uuid4()),
            "type": "text",
            "content": txt,
            "caption": "",
            "added_by": uid,
            "ts": _now_ts(),
        }
        db["inventory"].setdefault(pid, []).append(itm)
        save_db(db)
        bot.send_message(uid, "✅ کانفیگ متنی به مخزن اضافه شد.", reply_markup=kb_inventory_admin())
        clear_state(uid)
        return True

    # --- Coupons flow (مرحله‌ای) ---
    if mode == "await_coupon_percent":
        if not txt.isdigit() or not (0 < int(txt) <= 100):
            bot.send_message(uid, "درصد معتبر (1 تا 100) وارد کنید.", reply_markup=kb_cancel_back())
            return True
        payload["percent"] = int(txt)
        set_state(uid, "await_coupon_plan_limit", payload)
        bot.send_message(uid, "محدود به پلن خاص؟ اگر بله، نام پلن را انتخاب/ارسال کن؛ اگر نه بفرست: «همه»", reply_markup=kb_plans_for_user(uid))
        return True

    if mode == "await_coupon_plan_limit":
        if txt == "همه":
            payload["plan_limit"] = None
        else:
            pid, p = find_plan_by_label(txt)
            if not p:
                # may be plain plan name
                pid = None
                for k, v in db["plans"].items():
                    if v["name"] == txt:
                        pid = k; break
                if pid is None:
                    bot.send_message(uid, "پلن معتبر یا «همه».", reply_markup=kb_plans_for_user(uid))
                    return True
            payload["plan_limit"] = pid
        set_state(uid, "await_coupon_expire_days", payload)
        bot.send_message(uid, "تا چند روز اعتبار داشته باشد؟ (عدد)", reply_markup=kb_cancel_back())
        return True

    if mode == "await_coupon_expire_days":
        if not txt.isdigit():
            bot.send_message(uid, "عدد معتبر بفرستید.", reply_markup=kb_cancel_back())
            return True
        days = int(txt)
        payload["expire_days"] = days
        set_state(uid, "await_coupon_cap", payload)
        bot.send_message(uid, "سقف تعداد استفاده؟ (عدد؛ مثلا 50)", reply_markup=kb_cancel_back())
        return True

    if mode == "await_coupon_cap":
        if not txt.isdigit():
            bot.send_message(uid, "عدد معتبر بفرستید.", reply_markup=kb_cancel_back()); return True
        payload["max_use"] = int(txt)
        set_state(uid, "await_coupon_code", payload)
        bot.send_message(uid, "کد تخفیف (نام/کد) را بفرست:", reply_markup=kb_cancel_back())
        return True

    if mode == "await_coupon_code":
        code = txt.upper().strip()
        if code in db["coupons"]:
            bot.send_message(uid, "این کد وجود دارد. کد دیگری ارسال کنید.", reply_markup=kb_cancel_back()); return True
        expires_at = _now_ts() + payload["expire_days"]*24*3600
        db["coupons"][code] = {
            "percent": payload["percent"],
            "plan_limit": payload["plan_limit"],
            "max_use": payload["max_use"],
            "used": 0,
            "expires_at_ts": expires_at
        }
        save_db(db)
        bot.send_message(uid, f"کد ساخته شد: <code>{code}</code>", reply_markup=kb_admin()); clear_state(uid)
        return True

    # --- Wallet admin: charge user ---
    if mode == "await_wallet_admin_userid":
        if not txt.isdigit():
            bot.send_message(uid, "آیدی عددی کاربر را بفرست.", reply_markup=kb_cancel_back()); return True
        payload["target_uid"] = int(txt)
        set_state(uid, "await_wallet_admin_amount", payload)
        bot.send_message(uid, "مبلغ شارژ (تومان) را ارسال کنید:", reply_markup=kb_cancel_back())
        return True

    if mode == "await_wallet_admin_amount":
        if not txt.isdigit():
            bot.send_message(uid, "عدد معتبر بفرست.", reply_markup=kb_cancel_back()); return True
        amount = int(txt)
        tid = payload["target_uid"]
        db["wallets"][str(tid)] = db["wallets"].get(str(tid), 0) + amount
        save_db(db)
        bot.send_message(uid, f"✅ {format_money(amount)} به کیف پول {tid} افزوده شد.", reply_markup=kb_admin())
        try:
            bot.send_message(tid, f"🪙 کیف پول شما {format_money(amount)} شارژ شد.")
        except:
            pass
        clear_state(uid)
        return True

    # --- Receipts admin confirm amount ---
    if mode == "await_receipt_amount":
        if not txt.isdigit():
            bot.send_message(uid, "عدد معتبر بفرست.", reply_markup=kb_cancel_back()); return True
        amount = int(txt)
        rid = payload["receipt_id"]
        R = db["receipts"].get(rid)
        if not R or R["status"] != "pending":
            bot.send_message(uid, "رسید معتبر نیست.", reply_markup=kb_admin()); clear_state(uid); return True
        R["amount"] = amount
        # if kind=wallet → add balance
        tgt = R["user_id"]
        if R["kind"] == "wallet":
            db["wallets"][str(tgt)] = db["wallets"].get(str(tgt), 0) + amount
            R["status"] = "approved"
            save_db(db)
            bot.send_message(uid, f"✅ رسید تایید شد و {format_money(amount)} به کیف پول {tgt} اضافه شد.", reply_markup=kb_admin())
            try:
                bot.send_message(tgt, f"✅ رسید شما تایید شد و {format_money(amount)} به کیف پولتان افزوده شد.")
            except: pass
            clear_state(uid); return True
        # if kind=purchase → complete purchase (need plan_id and expected)
        if R["kind"] == "purchase":
            plan_id = R["plan_id"]
            final_expected = R.get("expected", amount)  # fallback
            item = give_inventory_item(plan_id)
            if not item:
                bot.send_message(uid, "موجودی مخزن این پلن تمام شده.", reply_markup=kb_admin())
                clear_state(uid); return True
            record_order(tgt, plan_id, final_expected, coupon_code=R.get("coupon"))
            R["status"] = "approved"
            save_db(db)
            # send item to user
            send_config_to_user(tgt, item)
            try:
                bot.send_message(tgt, f"✅ خرید شما تایید شد. مبلغ دریافتی: {format_money(amount)}")
            except: pass
            bot.send_message(uid, "خرید تکمیل و کانفیگ ارسال شد.", reply_markup=kb_admin())
            clear_state(uid); return True
        return True

    # --- User flows: buy / wallet / ticket ---
    if mode == "await_coupon_input":
        code = txt.upper()
        C = db["coupons"].get(code)
        if not C:
            bot.send_message(uid, "کد نامعتبر است.", reply_markup=kb_buy_actions()); return True
        # validate
        pid = payload["plan_id"]
        if C["expires_at_ts"] < _now_ts():
            bot.send_message(uid, "کد منقضی شده است.", reply_markup=kb_buy_actions()); return True
        if C["max_use"] <= C["used"]:
            bot.send_message(uid, "سقف استفاده از این کد پر شده.", reply_markup=kb_buy_actions()); return True
        if C["plan_limit"] and C["plan_limit"] != pid:
            bot.send_message(uid, "این کد برای این پلن معتبر نیست.", reply_markup=kb_buy_actions()); return True
        payload["coupon_code"] = code
        set_state(uid, "buy_menu_for_plan", payload)  # بازگشت به منوی خرید
        show_plan_detail(uid, pid, coupon_code=code)
        return True

    if mode == "await_ticket_subject":
        payload["subject"] = txt
        set_state(uid, "await_ticket_text", payload)
        bot.send_message(uid, "متن پیام تیکت را بنویسید:", reply_markup=kb_cancel_back())
        return True

    if mode == "await_ticket_text":
        # create ticket
        tid = str(uuid4())
        db["tickets"][tid] = {
            "id": tid,
            "user_id": uid,
            "status": "open",
            "subject": payload["subject"],
            "messages": [
                {"from":"user","text":txt,"ts":_now_ts()}
            ]
        }
        save_db(db)
        bot.send_message(uid, f"🎫 تیکت ایجاد شد: {tid}", reply_markup=kb_home(uid))
        # notify admins
        for aid in db["admins"]:
            try:
                bot.send_message(aid, f"🎫 تیکت جدید از {username_link(uid)}\nموضوع: {payload['subject']}")
            except:
                pass
        clear_state(uid)
        return True

    if mode == "await_search_user":
        # search by id or username (without @)
        res = []
        if txt.isdigit():
            u = db["users"].get(txt)
            if u: res.append(u)
        else:
            key = txt.lower().lstrip("@")
            for u in db["users"].values():
                if (u.get("username") or "").lower() == key:
                    res.append(u)
        if not res:
            bot.send_message(uid, "چیزی یافت نشد.", reply_markup=kb_admin()); clear_state(uid); return True
        # show result(s)
        for u in res[:30]:
            bot.send_message(uid, format_user_profile(u))
        clear_state(uid)
        return True

    # default → not handled
    return False

def handle_stateful_media(uid: int, message: types.Message, st: dict) -> bool:
    mode = st["mode"]; payload = st.get("payload", {})
    # Inventory add item with media
    if mode == "await_inventory_add_item":
        pid = payload["plan_id"]
        if message.photo:
            fid = message.photo[-1].file_id
            cap = (message.caption or "")
            itm = {"id": str(uuid4()), "type": "photo", "content": fid, "caption": cap, "added_by": uid, "ts": _now_ts()}
            db["inventory"].setdefault(pid, []).append(itm)
            save_db(db)
            bot.send_message(uid, "✅ عکس به مخزن اضافه شد.", reply_markup=kb_inventory_admin())
            clear_state(uid)
            return True
        if message.document:
            fid = message.document.file_id
            cap = (message.caption or "")
            itm = {"id": str(uuid4()), "type": "file", "content": fid, "caption": cap, "added_by": uid, "ts": _now_ts()}
            db["inventory"].setdefault(pid, []).append(itm)
            save_db(db)
            bot.send_message(uid, "✅ فایل به مخزن اضافه شد.", reply_markup=kb_inventory_admin())
            clear_state(uid)
            return True
        # otherwise ignore
        bot.send_message(uid, "نوع محتوا پشتیبانی نمی‌شود.", reply_markup=kb_inventory_admin())
        return True

    # no other media states
    return False

# -----------------------------
# User Menus / Flows
# -----------------------------
def show_plans_for_user(uid):
    plans = list_plans()
    if not plans:
        bot.send_message(uid, "فعلاً پلنی موجود نیست.", reply_markup=kb_home(uid)); return
    bot.send_message(uid, "لطفاً پلن مورد نظر را انتخاب کنید:", reply_markup=kb_plans_for_user(uid))

def show_plan_detail(uid, plan_id, coupon_code=None):
    p = db["plans"][plan_id]
    stock = len(db["inventory"].get(plan_id, []))
    base = int(p["price"])
    coupon = db["coupons"].get(coupon_code) if coupon_code else None
    final, disc = calculate_price_with_coupon(base, coupon)
    txt = (
        f"نام: <b>{p['name']}</b>\n"
        f"مدت: {p['days']} روز\n"
        f"حجم: {p['size']}\n"
        f"قیمت: {format_money(base)}\n"
        + (f"تخفیف: {disc}% → مبلغ: {format_money(final)}\n" if coupon else "")
        + f"موجودی مخزن: {stock}\n"
        f"{p.get('desc','')}"
    )
    bot.send_message(uid, txt, reply_markup=kb_buy_actions())
    set_state(uid, "buy_menu_for_plan", {"plan_id": plan_id, "coupon_code": coupon_code})

@bot.message_handler(func=lambda m: get_state(m.from_user.id) and get_state(m.from_user.id).get("mode")=="buy_menu_for_plan")
def on_buy_menu(message: types.Message):
    uid = message.from_user.id
    txt = message.text.strip()
    st = get_state(uid)
    plan_id = st["payload"]["plan_id"]
    coupon_code = st["payload"].get("coupon_code")
    b = db["buttons"]

    if txt == b["btn_enter_coupon"]:
        set_state(uid, "await_coupon_input", {"plan_id": plan_id})
        bot.send_message(uid, "کد تخفیف را ارسال کنید:", reply_markup=kb_buy_actions())
        return
    if txt == b["btn_clear_coupon"]:
        set_state(uid, "buy_menu_for_plan", {"plan_id": plan_id})
        show_plan_detail(uid, plan_id, coupon_code=None)
        return
    if txt == b["btn_buy_with_wallet"]:
        # wallet pay flow
        base = db["plans"][plan_id]["price"]
        coupon = db["coupons"].get(coupon_code) if coupon_code else None
        final, _ = calculate_price_with_coupon(base, coupon)
        bal = db["wallets"].get(str(uid), 0)
        if bal >= final:
            db["wallets"][str(uid)] = bal - final
            item = give_inventory_item(plan_id)
            if not item:
                bot.send_message(uid, "متاسفانه موجودی مخزن تمام شده.", reply_markup=kb_home(uid)); clear_state(uid); return
            record_order(uid, plan_id, final, coupon_code=coupon_code)
            # mark coupon used
            if coupon_code:
                db["coupons"][coupon_code]["used"] += 1
                save_db(db)
            send_config_to_user(uid, item)
            bot.send_message(uid, "✅ خرید با کیف پول انجام شد و کانفیگ ارسال گردید.", reply_markup=kb_home(uid))
            clear_state(uid); return
        else:
            diff = final - bal
            # پیشنهاد شارژ مابه‌التفاوت
            card = db["settings"]["card_number"]
            msg = (
                f"موجودی کیف پول شما کافی نیست.\n"
                f"مبلغ موردنیاز: {format_money(final)}\n"
                f"موجودی فعلی: {format_money(bal)}\n"
                f"مابه‌التفاوت: <b>{format_money(diff)}</b>\n\n"
                f"برای شارژ مابه‌التفاوت، مبلغ را به کارت زیر واریز کنید و رسید را ارسال نمایید:\n"
                f"<code>{card}</code>"
            )
            bot.send_message(uid, msg, reply_markup=kb_cancel_back())
            # ثبت رسید در انتظار پس از ارسال
            set_state(uid, "await_wallet_diff_receipt", {"plan_id": plan_id, "expected": diff, "coupon": coupon_code})
            return
    if txt == b["btn_buy_with_card"]:
        # card to card pay flow
        base = db["plans"][plan_id]["price"]
        coupon = db["coupons"].get(coupon_code) if coupon_code else None
        final, _ = calculate_price_with_coupon(base, coupon)
        card = db["settings"]["card_number"]
        msg = (
            "لطفاً مبلغ زیر را کارت‌به‌کارت کنید و رسید را همینجا ارسال کنید:\n"
            f"مبلغ: <b>{format_money(final)}</b>\n"
            f"شماره کارت: <code>{card}</code>\n\n"
            "پس از ارسال رسید، ادمین بررسی می‌کند و در صورت تایید، کانفیگ ارسال می‌شود."
        )
        bot.send_message(uid, msg, reply_markup=kb_cancel_back())
        set_state(uid, "await_purchase_receipt", {"plan_id": plan_id, "expected": final, "coupon": coupon_code})
        return

    bot.send_message(uid, "از دکمه‌ها استفاده کنید یا «انصراف/بازگشت».", reply_markup=kb_buy_actions())

def show_wallet(uid):
    bal = db["wallets"].get(str(uid), 0)
    msg = f"موجودی کیف پول شما: <b>{format_money(bal)}</b>"
    bot.send_message(uid, msg, reply_markup=kb_wallet_user())

@bot.message_handler(func=lambda m: m.text and m.text.strip()==db["buttons"]["btn_add_to_wallet"])
def wallet_add_flow(message: types.Message):
    uid = message.from_user.id
    card = db["settings"]["card_number"]
    msg = (
        "برای شارژ کیف پول:\n"
        "1) مبلغ دلخواه را به شماره کارت زیر واریز کنید.\n"
        f"   <code>{card}</code>\n"
        "2) رسید پرداخت (عکس/متن/فایل) را همینجا ارسال کنید.\n"
        "3) پس از تایید ادمین، مبلغ به کیف پول شما افزوده می‌شود."
    )
    bot.send_message(uid, msg, reply_markup=kb_cancel_back())
    set_state(uid, "await_wallet_receipt", {})

def show_ticket_menu(uid):
    b = db["buttons"]
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton(b["btn_new_ticket"]), types.KeyboardButton(b["btn_my_tickets"]))
    k.row(types.KeyboardButton(b["btn_back"]))
    bot.send_message(uid, "بخش پشتیبانی:", reply_markup=k)

@bot.message_handler(func=lambda m: m.text and m.text.strip()==db["buttons"]["btn_new_ticket"])
def new_ticket_subject(message: types.Message):
    uid = message.from_user.id
    bot.send_message(uid, "موضوع تیکت را بفرستید:", reply_markup=kb_cancel_back())
    set_state(uid, "await_ticket_subject", {})

@bot.message_handler(func=lambda m: m.text and m.text.strip()==db["buttons"]["btn_my_tickets"])
def my_tickets(message: types.Message):
    uid = message.from_user.id
    items = [t for t in db["tickets"].values() if t["user_id"]==uid]
    if not items:
        bot.send_message(uid, "هیچ تیکتی ندارید.", reply_markup=kb_home(uid)); return
    for t in items[-10:]:
        bot.send_message(uid, f"#{t['id']}\nوضعیت: {t['status']}\nموضوع: {t['subject']}\nپیام‌ها: {len(t['messages'])}")
    bot.send_message(uid, "برای پاسخ به تیکت، زیر همین پیام بنویسید: #ID متن", reply_markup=kb_home(uid))

def show_my_orders(uid):
    items = [o for o in db["orders"] if o["user_id"]==uid]
    if not items:
        bot.send_message(uid, "سفارشی ثبت نشده.", reply_markup=kb_home(uid)); return
    lines = []
    for o in items[-10:][::-1]:
        p = db["plans"].get(o["plan_id"], {"name":"(حذف‌شده)"})
        dt = datetime.fromtimestamp(o["ts"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• {p['name']} - {format_money(o['price'])} - {dt}")
    bot.send_message(uid, "سفارش‌های اخیر:\n" + "\n".join(lines), reply_markup=kb_home(uid))

def show_account(uid):
    u = db["users"].get(str(uid), {})
    msg = (
        f"ID عددی: <code>{uid}</code>\n"
        f"یوزرنیم: @{u.get('username') or '-'}\n"
        f"تعداد کانفیگ‌های خریداری‌شده: {u.get('orders_count',0)}"
    )
    bot.send_message(uid, msg, reply_markup=kb_home(uid))

# -----------------------------
# Receipts (user sends) & Admin Inbox
# -----------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id) and get_state(m.from_user.id).get("mode") in ("await_wallet_receipt","await_wallet_diff_receipt","await_purchase_receipt"), content_types=['text','photo','document'])
def on_receipt_upload(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    mode = st["mode"]; payload = st.get("payload", {})
    rid = str(uuid4())
    rec = {
        "id": rid,
        "user_id": uid,
        "status": "pending",
        "ts": _now_ts()
    }
    if mode == "await_wallet_receipt":
        rec["kind"] = "wallet"
    elif mode == "await_wallet_diff_receipt":
        rec["kind"] = "purchase"
        rec["plan_id"] = payload["plan_id"]
        rec["expected"] = payload["expected"]
        if payload.get("coupon"): rec["coupon"] = payload["coupon"]
    elif mode == "await_purchase_receipt":
        rec["kind"] = "purchase"
        rec["plan_id"] = payload["plan_id"]
        rec["expected"] = payload["expected"]
        if payload.get("coupon"): rec["coupon"] = payload["coupon"]

    if message.photo:
        rec["media"] = {"type":"photo","file_id": message.photo[-1].file_id, "caption": message.caption or ""}
    elif message.document:
        rec["media"] = {"type":"file","file_id": message.document.file_id, "caption": message.caption or ""}
    else:
        rec["message"] = message.text

    db["receipts"][rid] = rec
    save_db(db)
    bot.send_message(uid, "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین…", reply_markup=kb_home(uid))
    clear_state(uid)

    # notify admins
    for aid in db["admins"]:
        try:
            bot.send_message(aid, f"🧾 رسید جدید از {username_link(uid)}\nنوع: {rec['kind']}\nReceipt ID: <code>{rid}</code>")
        except:
            pass

def list_pending_receipts(uid):
    items = [r for r in db["receipts"].values() if r["status"]=="pending"]
    if not items:
        bot.send_message(uid, "رسید در انتظاری وجود ندارد.", reply_markup=kb_admin()); return
    items.sort(key=lambda x: x["ts"])
    for r in items[:20]:
        s = f"#{r['id']} | از: {username_link(r['user_id'])} | نوع: {r['kind']}"
        if "expected" in r: s += f" | مبلغ مورد انتظار: {format_money(r['expected'])}"
        bot.send_message(uid, s)
    bot.send_message(uid, "برای تأیید یک رسید، بنویسید:\napprove <ReceiptID>\nبرای رد: reject <ReceiptID>", reply_markup=kb_admin())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and (m.text.startswith("approve ") or m.text.startswith("reject ")))
def approve_reject_receipt(message: types.Message):
    uid = message.from_user.id
    parts = message.text.strip().split()
    if len(parts) != 2:
        bot.send_message(uid, "فرمت درست نیست.", reply_markup=kb_admin()); return
    cmd, rid = parts
    R = db["receipts"].get(rid)
    if not R or R["status"] != "pending":
        bot.send_message(uid, "رسید معتبر نیست.", reply_markup=kb_admin()); return
    if cmd == "reject":
        R["status"] = "rejected"; save_db(db)
        bot.send_message(uid, "رسید رد شد.", reply_markup=kb_admin())
        try:
            bot.send_message(R["user_id"], "❌ رسید شما رد شد. در صورت ابهام با پشتیبانی در تماس باشید.")
        except: pass
        return
    # approve → ask amount if not wallet? always ask amount to be safe
    set_state(uid, "await_receipt_amount", {"receipt_id": rid})
    bot.send_message(uid, "مبلغ تاییدی (تومان) را وارد کنید:", reply_markup=kb_cancel_back())

# -----------------------------
# Admin Menus
# -----------------------------
def manage_admins_menu(uid):
    L = "\n".join([f"• {a}" for a in db["admins"]]) or "-"
    bot.send_message(uid, f"👑 ادمین‌ها:\n{L}\n\nبرای افزودن، بنویسید: addadmin\nبرای حذف، بنویسید: deladmin", reply_markup=kb_admin())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip() in ("addadmin","deladmin"))
def on_admin_add_del(message: types.Message):
    uid = message.from_user.id
    cmd = message.text.strip()
    if cmd == "addadmin":
        bot.send_message(uid, "آیدی عددی ادمین جدید را بفرست.", reply_markup=kb_cancel_back())
        set_state(uid, "await_admin_id_to_add", {})
    else:
        bot.send_message(uid, "آیدی عددی ادمینی که باید حذف شود را بفرست.", reply_markup=kb_cancel_back())
        set_state(uid, "await_admin_id_to_remove", {})

def manage_plans_menu(uid):
    b = db["buttons"]
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton(b["btn_add_plan"]), types.KeyboardButton(b["btn_edit_plan"]))
    k.row(types.KeyboardButton(b["btn_del_plan"]), types.KeyboardButton(b["btn_back"]))
    bot.send_message(uid, "مدیریت پلن‌ها:", reply_markup=k)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()==db["buttons"]["btn_add_plan"])
def on_add_plan(message: types.Message):
    uid = message.from_user.id
    set_state(uid, "await_new_plan_name", {})
    bot.send_message(uid, "نام پلن را بفرست:", reply_markup=kb_cancel_back())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()==db["buttons"]["btn_edit_plan"])
def on_edit_plan(message: types.Message):
    uid = message.from_user.id
    set_state(uid, "await_edit_plan_pick", {})
    bot.send_message(uid, "پلن را انتخاب کنید:", reply_markup=kb_plans_for_user(uid))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()==db["buttons"]["btn_del_plan"])
def on_del_plan(message: types.Message):
    uid = message.from_user.id
    set_state(uid, "await_delete_plan_pick", {})
    bot.send_message(uid, "پلن را انتخاب کنید برای حذف:", reply_markup=kb_plans_for_user(uid))

def choose_plan_for_inventory(uid):
    set_state(uid, "await_inventory_pick_plan", {})
    bot.send_message(uid, "پلن مورد نظر برای مدیریت مخزن را انتخاب کنید:", reply_markup=kb_plans_for_user(uid))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()==db["buttons"]["btn_inventory_add"])
def inv_add_btn(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    if not st or st.get("mode") != "await_inventory_pick_plan":
        bot.send_message(uid, "ابتدا پلن را انتخاب کنید.", reply_markup=kb_plans_for_user(uid)); return
    # next step already set in stateful flow
    bot.send_message(uid, "کانفیگ را ارسال کنید (متن/عکس/فایل).", reply_markup=kb_cancel_back())
    set_state(uid, "await_inventory_add_item", st.get("payload",{}))

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()==db["buttons"]["btn_inventory_list"])
def inv_list_btn(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    if not st or st.get("mode") != "await_inventory_pick_plan":
        bot.send_message(uid, "ابتدا پلن را انتخاب کنید.", reply_markup=kb_plans_for_user(uid)); return
    pid = st["payload"].get("plan_id")
    items = db["inventory"].get(pid, [])
    if not items:
        bot.send_message(uid, "مخزن خالی است.", reply_markup=kb_inventory_admin()); return
    bot.send_message(uid, f"تعداد آیتم‌های مخزن: {len(items)}", reply_markup=kb_inventory_admin())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()==db["buttons"]["btn_inventory_back"])
def inv_back_btn(message: types.Message):
    uid = message.from_user.id
    clear_state(uid)
    manage_plans_menu(uid)

def coupons_menu(uid):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton("➕ ساخت کد تخفیف"), types.KeyboardButton("📜 لیست کدها"))
    k.row(types.KeyboardButton(db["buttons"]["btn_back"]))
    bot.send_message(uid, "مدیریت کدهای تخفیف:", reply_markup=k)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()=="➕ ساخت کد تخفیف")
def coupon_create(message: types.Message):
    uid = message.from_user.id
    bot.send_message(uid, "درصد تخفیف (1 تا 100):", reply_markup=kb_cancel_back())
    set_state(uid, "await_coupon_percent", {})

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()=="📜 لیست کدها")
def coupon_list(message: types.Message):
    uid = message.from_user.id
    if not db["coupons"]:
        bot.send_message(uid, "کدی وجود ندارد.", reply_markup=kb_admin()); return
    lines=[]
    for code, c in db["coupons"].items():
        plim = "-"
        if c["plan_limit"]:
            plim = db["plans"].get(c["plan_limit"],{}).get("name","(حذف‌شده)")
        exp = datetime.fromtimestamp(c["expires_at_ts"]).strftime("%Y-%m-%d")
        lines.append(f"<b>{code}</b> | {c['percent']}% | پلن: {plim} | استفاده: {c['used']}/{c['max_use']} | انقضا: {exp}")
    bot.send_message(uid, "\n".join(lines), reply_markup=kb_admin())

def wallet_admin_menu(uid):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton("➕ شارژ کاربر"), types.KeyboardButton(db["buttons"]["btn_back"]))
    bot.send_message(uid, "بخش کیف پول (ادمین):", reply_markup=k)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()=="➕ شارژ کاربر")
def wallet_admin_charge_user(message: types.Message):
    uid = message.from_user.id
    bot.send_message(uid, "آیدی عددی کاربر را بفرست.", reply_markup=kb_cancel_back())
    set_state(uid, "await_wallet_admin_userid", {})

def users_menu(uid):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(types.KeyboardButton("🔎 جستجو"), types.KeyboardButton("📋 لیست کاربران"))
    k.row(types.KeyboardButton(db["buttons"]["btn_back"]))
    bot.send_message(uid, "مدیریت کاربران:", reply_markup=k)

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()=="🔎 جستجو")
def users_search(message: types.Message):
    uid = message.from_user.id
    bot.send_message(uid, "یوزرنیم (بدون @) یا آیدی عددی را ارسال کنید:", reply_markup=kb_cancel_back())
    set_state(uid, "await_search_user", {})

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()=="📋 لیست کاربران")
def users_list(message: types.Message):
    uid = message.from_user.id
    users = list(db["users"].values())
    users.sort(key=lambda x: x.get("joined_at",0), reverse=True)
    if not users:
        bot.send_message(uid, "کاربری وجود ندارد.", reply_markup=kb_admin()); return
    chunk = users[:30]
    for u in chunk:
        bot.send_message(uid, format_user_profile(u))
    bot.send_message(uid, f"نمایش {len(chunk)} کاربر (از {len(users)}).", reply_markup=kb_admin())

def edit_texts_menu(uid):
    # مرحله‌ای: لیست همه برچسب‌های متنی/دکمه‌ای را به صورت دکمه نمایش بده
    keys = list(db["buttons"].keys())
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row=[]
    for key in keys:
        label = f"✏️ {key}"
        row.append(types.KeyboardButton(label))
        if len(row)==2: k.row(*row); row=[]
    if row: k.row(*row)
    k.row(types.KeyboardButton(db["buttons"]["btn_back"]))
    bot.send_message(uid, "برای ویرایش، یکی از موارد را انتخاب کنید:", reply_markup=k)
    set_state(uid, "await_pick_button_key", {})

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id) and get_state(m.from_user.id).get("mode")=="await_pick_button_key")
def on_pick_button_key(message: types.Message):
    uid = message.from_user.id
    txt = message.text.strip()
    if not txt.startswith("✏️ "):
        bot.send_message(uid, "از لیست انتخاب کنید.", reply_markup=kb_cancel_back()); return
    key = txt.replace("✏️ ","",1)
    if key not in db["buttons"]:
        bot.send_message(uid, "کلید معتبر نیست.", reply_markup=kb_cancel_back()); return
    set_state(uid, "await_new_button_value", {"key":key})
    bot.send_message(uid, f"متن جدید برای <code>{key}</code> را بفرست:", reply_markup=kb_cancel_back())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id) and get_state(m.from_user.id).get("mode")=="await_new_button_value")
def on_new_button_value(message: types.Message):
    uid = message.from_user.id
    st = get_state(uid)
    key = st["payload"]["key"]
    db["buttons"][key] = (message.text or "").strip()
    save_db(db)
    bot.send_message(uid, "به‌روزرسانی شد.", reply_markup=kb_admin()); clear_state(uid)

def toggle_visibility_menu(uid):
    v = db["visibility"]
    txt = (
        "وضعیت دکمه‌ها:\n"
        f"خرید: {emoji_onoff(v.get('buy'))} | کیف پول: {emoji_onoff(v.get('wallet'))}\n"
        f"تیکت: {emoji_onoff(v.get('tickets'))} | سفارش‌ها: {emoji_onoff(v.get('orders'))}\n"
        "برای تغییر بنویسید: toggle buy/wallet/tickets/orders"
    )
    bot.send_message(uid, txt, reply_markup=kb_admin())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip().startswith("toggle "))
def on_toggle(message: types.Message):
    uid = message.from_user.id
    key = message.text.strip().split(" ",1)[-1]
    if key not in ("buy","wallet","tickets","orders"):
        bot.send_message(uid, "کلید معتبر: buy/wallet/tickets/orders", reply_markup=kb_admin()); return
    db["visibility"][key] = not db["visibility"].get(key, True)
    save_db(db)
    toggle_visibility_menu(uid)

def emoji_onoff(b):
    return "🟢" if b else "⚪️"

def send_broadcast(uid, text):
    users = list(db["users"].keys())
    ok = 0; fails = 0
    for sid in users:
        try:
            bot.send_message(int(sid), text)
            ok += 1
        except:
            fails += 1
    bot.send_message(uid, f"📢 ارسال شد.\nموفق: {ok} | ناموفق: {fails}", reply_markup=kb_admin())

def format_user_profile(u):
    j = datetime.fromtimestamp(u.get("joined_at", _now_ts())).strftime("%Y-%m-%d")
    return (
        f"ID: <code>{u['id']}</code>\n"
        f"Username: @{u.get('username') or '-'}\n"
        f"نام: {u.get('first_name','-')}\n"
        f"عضویت: {j}\n"
        f"سفارش‌ها: {u.get('orders_count',0)}\n"
        f"موجودی کیف پول: {format_money(db['wallets'].get(str(u['id']),0))}"
    )

# -----------------------------
# Sales Stats
# -----------------------------
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text and m.text.strip()==db["buttons"]["btn_stats"])
def show_stats(message: types.Message):
    uid = message.from_user.id
    orders = db["orders"]
    if not orders:
        bot.send_message(uid, "هنوز سفارشی ثبت نشده.", reply_markup=kb_admin()); return
    total_amount = sum(o["price"] for o in orders)
    total_count = len(orders)
    # by plan
    by_plan = {}
    for o in orders:
        pid = o["plan_id"]
        by_plan[pid] = by_plan.get(pid, 0) + 1
    lines_plan = []
    for pid, cnt in sorted(by_plan.items(), key=lambda x: x[1], reverse=True):
        name = db["plans"].get(pid, {"name":"(حذف‌شده)"}).get("name")
        lines_plan.append(f"• {name}: {cnt} فروش")
    # top buyers
    by_user = {}
    for o in orders:
        by_user[o["user_id"]] = by_user.get(o["user_id"], 0) + o["price"]
    top_buyers = sorted(by_user.items(), key=lambda x: x[1], reverse=True)[:5]
    lines_users = []
    for uid2, amount in top_buyers:
        lines_users.append(f"• {username_link(uid2)} → {format_money(amount)}")
    msg = (
        "📊 آمار فروش:\n"
        f"تعداد کل فروش: <b>{total_count}</b>\n"
        f"مبلغ کل: <b>{format_money(total_amount)}</b>\n\n"
        "فروش به تفکیک پلن:\n" + ("\n".join(lines_plan) if lines_plan else "-") + "\n\n"
        "Top Buyers:\n" + ("\n".join(lines_users) if lines_users else "-")
    )
    bot.send_message(uid, msg, reply_markup=kb_admin())

# -----------------------------
# Start / Home route (no slash)
# -----------------------------
@bot.message_handler(func=lambda m: True, commands=['start'])
def _ignore_start(m):  # نباشد ولی اگر کسی زد نریزد
    show_home(m.from_user.id)

@bot.message_handler(func=lambda m: m.text and m.text.strip()==db["buttons"]["btn_back"])
def _back_to_home(m):
    show_home(m.from_user.id)

# -----------------------------
# Boot
# -----------------------------
def boot_message():
    try:
        # به ادمین‌ها پیام بوت
        for aid in db["admins"]:
            try:
                bot.send_message(aid, "✅ ربات بالا آمد.", reply_markup=kb_admin())
            except:
                pass
    except:
        pass

# -----------------------------
# Flask/Gunicorn hooks
# -----------------------------
set_webhook_once()
boot_message()

# -----------------------------
# Run (for local, not used on Koyeb)
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
