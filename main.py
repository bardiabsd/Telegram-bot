# main.py
# -*- coding: utf-8 -*-

import os
import json
import time
import re
import threading
from datetime import datetime, timedelta
from uuid import uuid4

from flask import Flask, request, abort
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InputMediaPhoto
)
from telebot.apihelper import ApiTelegramException

# -----------------------------
# تنظیمات حساس (قابل override با ENV)
# -----------------------------
DEFAULT_BOT_TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
DEFAULT_APP_URL   = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"
DEFAULT_ADMIN_ID  = "1743359080"  # عددی

BOT_TOKEN = os.getenv("BOT_TOKEN", DEFAULT_BOT_TOKEN).strip()
APP_URL   = os.getenv("APP_URL", DEFAULT_APP_URL).strip()
ADMIN_ID1 = int(os.getenv("ADMIN_ID", DEFAULT_ADMIN_ID))

WEBHOOK_URL = f"{APP_URL}/webhook/{BOT_TOKEN}"

# اگر دوست داری پورت/هاست رو کاستوم کنی
PORT = int(os.getenv("PORT", "8000"))

# -----------------------------
# Bot & Flask
# -----------------------------
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True)
app = Flask(__name__)

DB_PATH = "data.json"
db_lock = threading.Lock()

# -----------------------------
# Utilities
# -----------------------------
def now_ts() -> int:
    return int(time.time())

def to_int_safe(s: str, default: int = 0) -> int:
    if s is None:
        return default
    # تبدیل اعداد فارسی/عربی به لاتین
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    s2 = str(s).strip().translate(trans)
    s2 = re.sub(r"[^\d]", "", s2)
    if s2 == "":
        return default
    try:
        return int(s2)
    except:
        return default

def to_float_safe(s: str, default: float = 0.0) -> float:
    if s is None:
        return default
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    s2 = str(s).strip().translate(trans)
    s2 = s2.replace(",", "").replace(" ", "")
    try:
        return float(s2)
    except:
        return default

def money_fmt(v: int) -> str:
    return f"{v:,}".replace(",", "،")

def days_from_now(days: int) -> int:
    return int((datetime.utcnow() + timedelta(days=days)).timestamp())

def is_admin(uid: int) -> bool:
    return uid in db()["admins"]

def ensure_user(uid: int, username: str = None):
    D = db()
    U = D["users"].get(str(uid))
    if not U:
        D["users"][str(uid)] = {
            "wallet": 0,
            "purchases": [],      # order_ids
            "tickets": {},        # ticket_id -> {messages: [..], status}
            "receipts": [],       # receipt_ids
            "state": {},          # fsm
            "username": username or ""
        }
        save_db(D)
    else:
        if username and U.get("username") != username:
            U["username"] = username
            save_db(D)

def get_user(uid: int) -> dict:
    return db()["users"].get(str(uid), {})

def set_state(uid: int, **kwargs):
    D = db()
    st = D["users"].setdefault(str(uid), {}).setdefault("state", {})
    st.update(kwargs)
    save_db(D)

def get_state(uid: int) -> dict:
    return db()["users"].get(str(uid), {}).get("state", {})

def clear_state(uid: int, *keys):
    D = db()
    st = D["users"].get(str(uid), {}).get("state", {})
    if not keys:
        st.clear()
    else:
        for k in keys:
            st.pop(k, None)
    save_db(D)

def db() -> dict:
    with db_lock:
        if not os.path.exists(DB_PATH):
            init = {
                "admins": [ADMIN_ID1],
                "settings": {
                    "card_number": "6037-XXXX-XXXX-XXXX",
                    "texts": {
                        # متن‌ها قابل‌ویرایش از پنل ادمین
                        "welcome": "سلام! خوش اومدی 👋\nاز منوی زیر یکی رو انتخاب کن.",
                        "plans_title": "📦 پلن‌ها",
                        "wallet_title": "🪙 کیف پول",
                        "tickets_title": "🎫 تیکت پشتیبانی",
                        "profile_title": "👤 حساب کاربری",
                        "orders_title": "🧾 سفارش‌های من",
                        "enter_amount": "مبلغ را وارد کنید (تومان):",
                        "invalid_amount": "مقدار نامعتبر است. فقط عدد وارد کنید.",
                        "receipt_hint": "لطفاً رسید را ارسال کنید (عکس/متن).",
                        "receipt_saved": "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین باشید.",
                        "admin_panel": "🛠 پنل ادمین",
                        "not_admin": "⛔ شما ادمین نیستید.",
                        "coupon_invalid": "کد تخفیف نامعتبر یا منقضی است.",
                        "coupon_applied": "✅ کد تخفیف اعمال شد.",
                        "canceled": "❌ عملیات لغو شد.",
                    },
                    "buttons": {
                        "show_plans": True,
                        "show_wallet": True,
                        "show_tickets": True,
                        "show_orders": True,
                        "show_profile": True
                    }
                },
                "plans": {},      # plan_id -> {..., inventory:[{text, photo}]}
                "coupons": {},    # code -> {percent, limit, ...}
                "receipts": {},   # receipt_id -> {...}
                "orders": {},     # order_id -> {...}
                "broadcasts": []  # history
            }
            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(init, f, ensure_ascii=False, indent=2)
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

def save_db(data: dict):
    with db_lock:
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def main_menu(uid: int) -> ReplyKeyboardMarkup:
    S = db()["settings"]
    btns = S["buttons"]
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    if btns.get("show_plans", True):
        row.append(KeyboardButton("📦 خرید پلن"))
    if btns.get("show_wallet", True):
        row.append(KeyboardButton("🪙 کیف پول"))
    kb.add(*row) if row else None
    row2 = []
    if btns.get("show_tickets", True):
        row2.append(KeyboardButton("🎫 تیکت پشتیبانی"))
    if btns.get("show_orders", True):
        row2.append(KeyboardButton("🧾 سفارش‌های من"))
    if row2:
        kb.add(*row2)
    if btns.get("show_profile", True):
        kb.add(KeyboardButton("👤 حساب کاربری"))
    if is_admin(uid):
        kb.add(KeyboardButton("🛠 پنل ادمین"))
    return kb

def yes_no_kb(cancel_text="انصراف"):
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("✅ تایید", callback_data="yes"),
           InlineKeyboardButton("❌ " + cancel_text, callback_data="no"))
    return kb

def cancel_kb(txt="انصراف", data="cancel"):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"❌ {txt}", callback_data=data))
    return kb

def admin_menu_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans"))
    kb.add(InlineKeyboardButton("🏷 کدهای تخفیف", callback_data="admin_coupons"))
    kb.add(InlineKeyboardButton("🧾 رسیدها (اینباکس)", callback_data="admin_receipts"))
    kb.add(InlineKeyboardButton("🪙 کیف پول (ادمین)", callback_data="admin_wallet"))
    kb.add(InlineKeyboardButton("👥 کاربران", callback_data="admin_users"))
    kb.add(InlineKeyboardButton("📢 اعلان همگانی", callback_data="admin_broadcast"))
    kb.add(InlineKeyboardButton("📊 آمار فروش", callback_data="admin_stats"))
    kb.add(InlineKeyboardButton("👑 مدیریت ادمین‌ها", callback_data="admin_admins"))
    kb.add(InlineKeyboardButton("⚙️ تنظیمات (دکمه/متن/کارت)", callback_data="admin_settings"))
    return kb

def back_to_admin_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔙 بازگشت به پنل ادمین", callback_data="admin_home"))
    return kb

def plans_kb():
    D = db()
    kb = InlineKeyboardMarkup()
    has_any = False
    for pid, p in D["plans"].items():
        title = p.get("title", "بدون‌نام")
        inv = len(p.get("inventory", []))
        active = p.get("active", True)
        label = f"{'🟢' if (active and inv>0) else '🔴'} {title} ({inv} موجود)"
        cb = f"plan_{pid}" if active and inv>0 else f"plan_x_{pid}"
        kb.add(InlineKeyboardButton(label, callback_data=cb))
        has_any = True
    if not has_any:
        kb.add(InlineKeyboardButton("— فعلا پلنی موجود نیست —", callback_data="noop"))
    kb.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow"))
    return kb

def plan_detail_kb(pid: str, has_coupon: bool):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data=f"buy_card_{pid}"))
    kb.add(InlineKeyboardButton("🪙 خرید با کیف پول", callback_data=f"buy_wallet_{pid}"))
    kb.add(InlineKeyboardButton(("❌ حذف کد تخفیف" if has_coupon else "🏷 افزودن کدتخفیف"),
                                callback_data=(f"rm_coupon_{pid}" if has_coupon else f"add_coupon_{pid}")))
    kb.add(InlineKeyboardButton("🔙 انتخاب پلن دیگر", callback_data="back_plans"))
    kb.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow"))
    return kb

def wallet_menu_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_topup"))
    kb.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow"))
    return kb

def delta_topup_kb(amount: int):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"➕ شارژ همین مقدار ({money_fmt(amount)} تومان)", callback_data=f"wallet_topup_delta_{amount}"))
    kb.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel_flow"))
    return kb

def receipt_inbox_kb():
    D = db()
    kb = InlineKeyboardMarkup()
    pending = [(rid, r) for rid, r in D["receipts"].items() if r.get("status") == "pending"]
    pending.sort(key=lambda x: x[1].get("created", 0))
    if not pending:
        kb.add(InlineKeyboardButton("— رسید در انتظار نداریم —", callback_data="noop"))
    else:
        for rid, r in pending[:50]:
            u = r.get("user_id")
            kind = "کانفیگ" if r.get("kind") == "purchase" else "شارژ"
            kb.add(InlineKeyboardButton(f"{rid[:6]}… | {kind} | {u}", callback_data=f"receipt_{rid}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home"))
    return kb

def admins_kb():
    D = db()
    kb = InlineKeyboardMarkup()
    for a in D["admins"]:
        kb.add(InlineKeyboardButton(f"👑 {a}", callback_data=f"admin_rm_{a}"))
    kb.add(InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add_admin"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home"))
    return kb

def settings_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🧷 شماره کارت", callback_data="set_card"))
    kb.add(InlineKeyboardButton("🔘 دکمه‌ها (روشن/خاموش)", callback_data="toggle_buttons"))
    kb.add(InlineKeyboardButton("✏️ ویرایش متن‌ها", callback_data="edit_texts"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home"))
    return kb

def toggle_buttons_kb():
    S = db()["settings"]["buttons"]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"{'🟢' if S.get('show_plans',True) else '🔴'} پلن‌ها", callback_data="tbtn_show_plans"))
    kb.add(InlineKeyboardButton(f"{'🟢' if S.get('show_wallet',True) else '🔴'} کیف پول", callback_data="tbtn_show_wallet"))
    kb.add(InlineKeyboardButton(f"{'🟢' if S.get('show_tickets',True) else '🔴'} تیکت‌ها", callback_data="tbtn_show_tickets"))
    kb.add(InlineKeyboardButton(f"{'🟢' if S.get('show_orders',True) else '🔴'} سفارش‌ها", callback_data="tbtn_show_orders"))
    kb.add(InlineKeyboardButton(f"{'🟢' if S.get('show_profile',True) else '🔴'} پروفایل", callback_data="tbtn_show_profile"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_settings"))
    return kb

def coupons_kb():
    D = db()
    kb = InlineKeyboardMarkup()
    items = []
    for code, c in D["coupons"].items():
        active = c.get("active", True)
        used = c.get("uses", 0)
        mx   = c.get("max_uses", 0)
        label = f"{'🟢' if active else '🔴'} {code} | {c.get('percent',0)}% | {used}/{mx or '∞'}"
        items.append((label, f"coupon_{code}"))
    items.sort()
    if not items:
        kb.add(InlineKeyboardButton("— کدی موجود نیست —", callback_data="noop"))
    else:
        for lab, cb in items[:50]:
            kb.add(InlineKeyboardButton(lab, callback_data=cb))
    kb.add(InlineKeyboardButton("➕ ساخت کدتخفیف", callback_data="coupon_create"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home"))
    return kb

def plans_admin_kb():
    D = db()
    kb = InlineKeyboardMarkup()
    if not D["plans"]:
        kb.add(InlineKeyboardButton("— پلنی موجود نیست —", callback_data="noop"))
    else:
        for pid, p in D["plans"].items():
            inv = len(p.get("inventory", []))
            active = p.get("active", True)
            title = p.get("title","بدون‌نام")
            kb.add(InlineKeyboardButton(f"{'🟢' if (active and inv>0) else '🔴'} {title} ({inv})", callback_data=f"aplan_{pid}"))
    kb.add(InlineKeyboardButton("➕ افزودن پلن", callback_data="aplan_add"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home"))
    return kb

def plan_admin_detail_kb(pid: str):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✏️ ویرایش مشخصات", callback_data=f"aplan_edit_{pid}"))
    kb.add(InlineKeyboardButton("📥 مدیریت مخزن", callback_data=f"aplan_inv_{pid}"))
    kb.add(InlineKeyboardButton("🔁 فعال/غیرفعال", callback_data=f"aplan_toggle_{pid}"))
    kb.add(InlineKeyboardButton("🗑 حذف پلن", callback_data=f"aplan_del_{pid}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_plans"))
    return kb

def plan_inventory_kb(pid: str):
    D = db()
    p = D["plans"].get(pid, {})
    inv = p.get("inventory", [])
    kb = InlineKeyboardMarkup()
    if not inv:
        kb.add(InlineKeyboardButton("— موجودی ندارد —", callback_data="noop"))
    else:
        for idx in range(len(inv)):
            kb.add(InlineKeyboardButton(f"🗑 حذف مورد #{idx+1}", callback_data=f"inv_del_{pid}_{idx}"))
    kb.add(InlineKeyboardButton("➕ افزودن کانفیگ", callback_data=f"inv_add_{pid}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data=f"aplan_{pid}"))
    return kb

# -----------------------------
# Startup: Set webhook (with simple retry)
# -----------------------------
def set_webhook_once():
    try:
        bot.delete_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"{datetime.utcnow().isoformat()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except ApiTelegramException as e:
        print(f"{datetime.utcnow().isoformat()} | ERROR | Failed to set webhook: {e}")
        # تلاش دوباره کوتاه
        time.sleep(2)
        try:
            bot.set_webhook(url=WEBHOOK_URL)
        except Exception as e2:
            print(f"{datetime.utcnow().isoformat()} | ERROR | Second try failed: {e2}")

# -----------------------------
# Webhook routes
# -----------------------------
@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def legacy_webhook():
    # فقط برای ناسازگاری؛ 404 نمی‌دهیم که لاگ تمیز باشد
    return "OK", 200

@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def tg_webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

# -----------------------------
# Command / start
# -----------------------------
@bot.message_handler(commands=["start"])
def cmd_start(m):
    uid = m.from_user.id
    uname = (m.from_user.username or "") if m.from_user else ""
    ensure_user(uid, uname)
    txt = db()["settings"]["texts"]["welcome"]
    bot.send_message(uid, txt, reply_markup=main_menu(uid))

# -----------------------------
# Main menu text handlers
# -----------------------------
@bot.message_handler(func=lambda m: m.text == "📦 خرید پلن")
def h_plans(m):
    uid = m.from_user.id
    ensure_user(uid, m.from_user.username or "")
    D = db()
    bot.send_message(uid, D["settings"]["texts"]["plans_title"], reply_markup=ReplyKeyboardRemove())
    bot.send_message(uid, "یکی از پلن‌ها را انتخاب کن:", reply_markup=plans_kb())
    clear_state(uid)

@bot.message_handler(func=lambda m: m.text == "🪙 کیف پول")
def h_wallet(m):
    uid = m.from_user.id
    U = get_user(uid)
    bal = U.get("wallet", 0)
    bot.send_message(uid, f"موجودی فعلی: <b>{money_fmt(bal)}</b> تومان", reply_markup=ReplyKeyboardRemove())
    bot.send_message(uid, "چه کاری انجام بدهم؟", reply_markup=wallet_menu_kb())
    clear_state(uid)

@bot.message_handler(func=lambda m: m.text == "🎫 تیکت پشتیبانی")
def h_tickets(m):
    uid = m.from_user.id
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ تیکت جدید", callback_data="t_new"))
    # لیست تیکت‌های باز و بسته
    U = get_user(uid)
    opened = []
    closed = []
    for tid, t in U.get("tickets", {}).items():
        (opened if t.get("status") == "open" else closed).append((tid, t))
    if opened:
        for tid, _ in opened[:10]:
            kb.add(InlineKeyboardButton(f"🟢 تیکت #{tid[:6]}", callback_data=f"t_view_{tid}"))
    if closed:
        for tid, _ in closed[:10]:
            kb.add(InlineKeyboardButton(f"⚪️ تیکت بسته #{tid[:6]}", callback_data=f"t_view_{tid}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_home"))
    bot.send_message(uid, db()["settings"]["texts"]["tickets_title"], reply_markup=ReplyKeyboardRemove())
    bot.send_message(uid, "مدیریت تیکت‌ها:", reply_markup=kb)
    clear_state(uid)

@bot.message_handler(func=lambda m: m.text == "🧾 سفارش‌های من")
def h_orders(m):
    uid = m.from_user.id
    D = db()
    U = get_user(uid)
    orders = U.get("purchases", [])
    if not orders:
        bot.send_message(uid, "فعلاً سفارشی نداری.", reply_markup=ReplyKeyboardRemove())
    else:
        for oid in orders[-10:]:
            o = D["orders"].get(oid, {})
            p = D["plans"].get(o.get("plan_id",""), {})
            bot.send_message(uid,
                f"سفارش #{oid[:6]}\nپلن: {p.get('title','?')}\n"
                f"مبلغ: {money_fmt(o.get('price_final',0))} تومان\n"
                f"وضعیت: {'تحویل‌شده' if o.get('delivered') else 'در انتظار'}")
    bot.send_message(uid, "منوی اصلی:", reply_markup=main_menu(uid))
    clear_state(uid)

@bot.message_handler(func=lambda m: m.text == "👤 حساب کاربری")
def h_profile(m):
    uid = m.from_user.id
    U = get_user(uid)
    count = len(U.get("purchases", []))
    uname = U.get("username","") or (m.from_user.username or "")
    bot.send_message(uid, f"آیدی عددی: <code>{uid}</code>\n"
                          f"یوزرنیم: @{uname}\n"
                          f"تعداد کانفیگ‌های خریداری‌شده: <b>{count}</b>",
                     reply_markup=ReplyKeyboardRemove())
    bot.send_message(uid, "منوی اصلی:", reply_markup=main_menu(uid))
    clear_state(uid)

@bot.message_handler(func=lambda m: m.text == "🛠 پنل ادمین")
def h_admin(m):
    uid = m.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, db()["settings"]["texts"]["not_admin"])
        return
    bot.send_message(uid, db()["settings"]["texts"]["admin_panel"], reply_markup=ReplyKeyboardRemove())
    bot.send_message(uid, "یک مورد را انتخاب کنید:", reply_markup=admin_menu_kb())
    clear_state(uid)

# -----------------------------
# Callbacks (User flows)
# -----------------------------
@bot.callback_query_handler(func=lambda c: c.data == "back_home")
def cb_back_home(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "منوی اصلی:", reply_markup=main_menu(c.from_user.id))
    clear_state(c.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data == "cancel_flow")
def cb_cancel_flow(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, db()["settings"]["texts"]["canceled"], reply_markup=main_menu(c.from_user.id))
    clear_state(c.from_user.id)

# == Plans list / detail ==
@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_"))
def cb_plan_select(c):
    bot.answer_callback_query(c.id)
    parts = c.data.split("_", 2)
    if parts[1] == "x":
        bot.send_message(c.message.chat.id, "این پلن فعلاً قابل خرید نیست (ناموجود/غیرفعال).")
        return
    pid = parts[1]
    D = db()
    p = D["plans"].get(pid)
    if not p:
        bot.send_message(c.message.chat.id, "پلن پیدا نشد.")
        return
    price = p.get("price", 0)
    desc = p.get("desc","")
    days = p.get("days", 0)
    vol  = p.get("volume", "")
    st = get_state(c.from_user.id)
    has_coupon = bool(st.get("coupon") and st.get("coupon").get("plan_ok") == pid)
    bot.send_message(c.message.chat.id,
        f"نام پلن: {p.get('title','')}\n"
        f"قیمت: {money_fmt(price)} تومان\n"
        f"مدت/حجم: {days} روز / {vol}\n"
        f"توضیح: {desc}",
        reply_markup=plan_detail_kb(pid, has_coupon))

    # ذخیره‌ی «پلن انتخاب‌شده»
    set_state(c.from_user.id, selected_plan=pid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("add_coupon_"))
def cb_add_coupon(c):
    bot.answer_callback_query(c.id)
    st = get_state(c.from_user.id)
    pid = (c.data.split("_", 2)[2])
    set_state(c.from_user.id, awaiting="enter_coupon", coupon={"plan_try": pid})
    bot.send_message(c.message.chat.id, "کد تخفیف را وارد کنید:", reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("rm_coupon_"))
def cb_rm_coupon(c):
    bot.answer_callback_query(c.id)
    pid = c.data.split("_", 2)[2]
    st = get_state(c.from_user.id)
    if st.get("coupon") and st["coupon"].get("plan_ok") == pid:
        st.pop("coupon", None)
        set_state(c.from_user.id, **st)
        bot.send_message(c.message.chat.id, "کدتخفیف حذف شد.", reply_markup=plan_detail_kb(pid, False))
    else:
        bot.send_message(c.message.chat.id, "کدتخفیفی روی این پلن فعال نبود.")

# == Buy card-to-card ==
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_card_"))
def cb_buy_card(c):
    bot.answer_callback_query(c.id)
    pid = c.data.split("_", 2)[2]
    D = db()
    p = D["plans"].get(pid)
    if not p:
        bot.send_message(c.message.chat.id, "پلن پیدا نشد.")
        return
    price = p.get("price", 0)
    st = get_state(c.from_user.id)

    # اعمال کدتخفیف اگر معتبر
    final = price
    if st.get("coupon") and st["coupon"].get("plan_ok") == pid:
        pr = st["coupon"]["percent"]
        final = max(0, price - (price*pr)//100)

    card = D["settings"]["card_number"]
    bot.send_message(c.message.chat.id,
        f"برای پرداخت کارت‌به‌کارت:\n"
        f"شماره کارت: <code>{card}</code>\n"
        f"مبلغ: <b>{money_fmt(final)}</b> تومان\n\n"
        f"پس از واریز، رسید را ارسال کنید.",
        reply_markup=cancel_kb())

    # تعیین انتظار رسید خرید
    st["awaiting"] = "await_receipt"
    st["await_receipt"] = {"kind": "purchase", "plan_id": pid, "expected": final, "coupon": st.get("coupon")}
    set_state(c.from_user.id, **st)

# == Buy with wallet ==
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_wallet_"))
def cb_buy_wallet(c):
    bot.answer_callback_query(c.id)
    pid = c.data.split("_", 2)[2]
    D = db()
    U = get_user(c.from_user.id)
    p = D["plans"].get(pid)
    if not p:
        bot.send_message(c.message.chat.id, "پلن پیدا نشد.")
        return
    price = p.get("price", 0)
    st = get_state(c.from_user.id)

    final = price
    if st.get("coupon") and st["coupon"].get("plan_ok") == pid:
        pr = st["coupon"]["percent"]
        final = max(0, price - (price*pr)//100)

    bal = U.get("wallet", 0)
    if bal >= final:
        # پرداخت و تحویل
        U["wallet"] = bal - final
        OID = str(uuid4())
        D["orders"][OID] = {
            "user_id": c.from_user.id,
            "plan_id": pid,
            "price_final": final,
            "coupon_code": st.get("coupon", {}).get("code"),
            "delivered": False,
            "created": now_ts()
        }
        U["purchases"].append(OID)
        save_db(D)

        deliver_plan_config(c.from_user.id, OID)
        clear_state(c.from_user.id)
        bot.send_message(c.message.chat.id, "✅ پرداخت از کیف پول انجام شد.\nکانفیگ ارسال شد.", reply_markup=main_menu(c.from_user.id))
    else:
        diff = final - bal
        bot.send_message(c.message.chat.id,
                         "موجودی کیف پول کافی نیست.",
                         reply_markup=delta_topup_kb(diff))
        # ذخیره سبد خرید برای ادامه بعد از شارژ
        set_state(c.from_user.id, awaiting="buy_after_topup", buy_after={"plan_id": pid, "final": final})

# == Wallet topup ==
@bot.callback_query_handler(func=lambda c: c.data == "wallet_topup")
def cb_wallet_topup(c):
    bot.answer_callback_query(c.id)
    D = db()
    card = D["settings"]["card_number"]
    bot.send_message(c.message.chat.id,
        f"برای شارژ کیف پول:\n"
        f"شماره کارت: <code>{card}</code>\n"
        f"لطفاً مبلغ موردنظر را وارد کنید (تومان).",
        reply_markup=cancel_kb())
    set_state(c.from_user.id, awaiting="enter_topup_amount")

@bot.callback_query_handler(func=lambda c: c.data.startswith("wallet_topup_delta_"))
def cb_wallet_topup_delta(c):
    bot.answer_callback_query(c.id)
    amt = to_int_safe(c.data.split("_")[-1], 0)
    if amt <= 0:
        bot.send_message(c.message.chat.id, "مبلغ نامعتبر است.")
        return
    D = db()
    card = D["settings"]["card_number"]
    bot.send_message(c.message.chat.id,
        f"برای شارژ همین مقدار:\n"
        f"شماره کارت: <code>{card}</code>\n"
        f"مبلغ: <b>{money_fmt(amt)}</b> تومان\n\n"
        f"پس از واریز، رسید را ارسال کنید.",
        reply_markup=cancel_kb())
    set_state(c.from_user.id, awaiting="await_receipt", await_receipt={"kind":"wallet","expected": amt})

# -----------------------------
# Message handler for states
# -----------------------------
@bot.message_handler(content_types=['text','photo','document'])
def h_stateful(m):
    uid = m.from_user.id
    ensure_user(uid, m.from_user.username or "")
    st = get_state(uid)
    aw = st.get("awaiting")

    # ورود کد تخفیف
    if aw == "enter_coupon":
        code = (m.text or "").strip()
        if not code:
            bot.reply_to(m, "کد خالی است.")
            return
        D = db()
        c = D["coupons"].get(code.upper())
        pid_try = st.get("coupon", {}).get("plan_try")
        if not c or not c.get("active", True):
            bot.reply_to(m, D["settings"]["texts"]["coupon_invalid"])
            return
        # بررسی محدودیت پلن و انقضا/تعداد
        if c.get("expire") and now_ts() > c["expire"]:
            bot.reply_to(m, D["settings"]["texts"]["coupon_invalid"])
            return
        if c.get("max_uses", 0) and c.get("uses",0) >= c["max_uses"]:
            bot.reply_to(m, D["settings"]["texts"]["coupon_invalid"])
            return
        plan_limit = c.get("plan_limit", "all")
        if plan_limit != "all" and plan_limit != pid_try:
            bot.reply_to(m, "این کدتخفیف مخصوص پلن دیگری است.")
            return
        # OK
        st["coupon"] = {"code": code.upper(), "percent": c["percent"], "plan_ok": pid_try}
        set_state(uid, **st)
        bot.reply_to(m, D["settings"]["texts"]["coupon_applied"])
        bot.send_message(uid, "به جزئیات پلن برگردیم:", reply_markup=plan_detail_kb(pid_try, True))
        return

    # ورود مبلغ شارژ کیف پول
    if aw == "enter_topup_amount":
        amt = to_int_safe(m.text, -1)
        if amt <= 0:
            bot.reply_to(m, db()["settings"]["texts"]["invalid_amount"])
            return
        D = db()
        card = D["settings"]["card_number"]
        bot.send_message(uid,
            f"شماره کارت: <code>{card}</code>\n"
            f"مبلغ: <b>{money_fmt(amt)}</b> تومان\n"
            f"پس از واریز، رسید را ارسال کنید.",
            reply_markup=cancel_kb())
        set_state(uid, awaiting="await_receipt", await_receipt={"kind":"wallet","expected": amt})
        return

    # انتظار رسید (عکس/متن/فایل)
    if aw == "await_receipt":
        R_ID = str(uuid4())
        D = db()
        ar = st.get("await_receipt", {})
        kind = ar.get("kind")
        expected = int(ar.get("expected", 0))
        plan_id = ar.get("plan_id")
        coupon = ar.get("coupon")
        # ذخیره پیام رسید (آیدی پیام)
        mid = m.message_id
        # می‌تونیم عکس/متن رو هم نگه داریم
        payload = {"type": None, "file_id": None, "caption": None, "text": None}
        if m.photo:
            payload["type"] = "photo"
            payload["file_id"] = m.photo[-1].file_id
            payload["caption"] = (m.caption or "")
        elif m.document:
            payload["type"] = "doc"
            payload["file_id"] = m.document.file_id
            payload["caption"] = (m.caption or "")
        else:
            payload["type"] = "text"
            payload["text"] = (m.text or "")

        D["receipts"][R_ID] = {
            "user_id": uid,
            "kind": kind,
            "expected": expected,
            "plan_id": plan_id,
            "coupon": coupon,
            "status": "pending",
            "created": now_ts(),
            "updated": now_ts(),
            "origin_msg_id": mid,
            "payload": payload
        }
        D["users"][str(uid)]["receipts"].append(R_ID)
        save_db(D)
        clear_state(uid)
        bot.reply_to(m, db()["settings"]["texts"]["receipt_saved"], reply_markup=main_menu(uid))

        # ارسال به اینباکس ادمین‌ها (Realtime)
        for adm in D["admins"]:
            try:
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("✅ تایید", callback_data=f"rc_ok_{R_ID}"))
                kb.add(InlineKeyboardButton("❌ رد", callback_data=f"rc_no_{R_ID}"))
                kind_t = "خرید کانفیگ" if kind == "purchase" else "شارژ کیف پول"
                bot.send_message(int(adm),
                    f"🧾 رسید جدید\n"
                    f"نوع: {kind_t}\n"
                    f"کاربر: {uid}\n"
                    f"مبلغ/انتظار: {money_fmt(expected)}",
                    reply_markup=kb)
                # اگر عکس داشت، پیش‌نمایش
                if payload["type"] == "photo" and payload["file_id"]:
                    bot.send_photo(int(adm), payload["file_id"], caption=f"رسید #{R_ID[:6]}")
            except Exception:
                pass
        return

    # پاسخ به تیکت جدید/متن چندکلمه‌ای
    if aw == "create_ticket":
        text = (m.text or "").strip()
        if not text:
            bot.reply_to(m, "لطفاً متن تیکت را وارد کنید.")
            return
        D = db()
        TID = str(uuid4())
        D["users"][str(uid)]["tickets"][TID] = {
            "status": "open",
            "messages": [{"from":"user","text":text,"time":now_ts()}],
            "created": now_ts()
        }
        save_db(D)
        clear_state(uid)
        bot.reply_to(m, f"تیکت #{TID[:6]} ساخته شد.", reply_markup=main_menu(uid))
        # ارسال به ادمین‌ها
        for adm in D["admins"]:
            try:
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("✉️ پاسخ", callback_data=f"t_reply_{uid}_{TID}"))
                bot.send_message(int(adm), f"🎫 تیکت جدید از {uid}\nمتن: {text}", reply_markup=kb)
            except Exception:
                pass
        return

    # پاسخ ادمین به تیکت
    if aw == "admin_reply_ticket":
        D = db()
        tgt_uid = st.get("reply_uid")
        tid = st.get("reply_tid")
        text = (m.text or "").strip()
        if not (tgt_uid and tid and text):
            bot.reply_to(m, "پاسخ نامعتبر.")
            return
        U = D["users"].get(str(tgt_uid), {})
        if tid not in U.get("tickets", {}):
            bot.reply_to(m, "تیکت پیدا نشد.")
            return
        U["tickets"][tid]["messages"].append({"from":"admin","text":text,"time":now_ts()})
        save_db(D)
        clear_state(uid)
        bot.reply_to(m, "✅ پاسخ ارسال شد.", reply_markup=back_to_admin_kb())
        try:
            bot.send_message(int(tgt_uid), f"✉️ پاسخ ادمین به تیکت #{tid[:6]}:\n{text}")
        except Exception:
            pass
        return

    # درخواست‌های جاری دیگر هندل نشده => نادیده + منو
    # اگر چیزی در جریان نیست، سطح عمومی:
    if m.text and m.text.startswith("/"):
        return
    # اگر در هیچ انتظاری نبود، رفتار عمومی:
    # (عمداً چیزی نمی‌فرستیم تا اسپم نشه)

# -----------------------------
# Admin Callbacks
# -----------------------------
@bot.callback_query_handler(func=lambda c: c.data == "admin_home")
def cb_admin_home(c):
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "ادمین نیستید.")
        return
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    bot.send_message(c.message.chat.id, "🛠 پنل ادمین:", reply_markup=admin_menu_kb())
    clear_state(c.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data == "admin_plans")
def cb_admin_plans(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "📦 مدیریت پلن‌ها:", reply_markup=plans_admin_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("aplan_"))
def cb_admin_plan_detail(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    parts = c.data.split("_", 2)
    action = parts[1]
    pid = parts[2] if len(parts)>2 else None
    D = db()

    if action == "add":
        # شروع ویزارد افزودن پلن
        set_state(c.from_user.id, awaiting="aplan_title")
        bot.send_message(c.message.chat.id, "عنوان پلن را وارد کنید:", reply_markup=cancel_kb())
        return

    if not pid or pid not in D["plans"]:
        bot.send_message(c.message.chat.id, "پلن پیدا نشد.")
        return

    p = D["plans"][pid]
    inv = len(p.get("inventory", []))
    bot.send_message(c.message.chat.id,
        f"پلن: {p.get('title','')}\n"
        f"قیمت: {money_fmt(p.get('price',0))}\n"
        f"مدت/حجم: {p.get('days',0)} روز / {p.get('volume','')}\n"
        f"موجودی: {inv}\n"
        f"وضعیت: {'🟢 فعال' if p.get('active',True) else '🔴 غیرفعال'}",
        reply_markup=plan_admin_detail_kb(pid))

@bot.callback_query_handler(func=lambda c: c.data.startswith("aplan_edit_"))
def cb_aplan_edit(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    pid = c.data.split("_",2)[2]
    set_state(c.from_user.id, awaiting="aplan_edit_menu", edit_pid=pid)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("عنوان", callback_data="edit_title"))
    kb.add(InlineKeyboardButton("قیمت", callback_data="edit_price"))
    kb.add(InlineKeyboardButton("مدت (روز)", callback_data="edit_days"))
    kb.add(InlineKeyboardButton("حجم", callback_data="edit_volume"))
    kb.add(InlineKeyboardButton("توضیح", callback_data="edit_desc"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data=f"aplan_{pid}"))
    bot.send_message(c.message.chat.id, "کدام مورد را ویرایش کنیم؟", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("aplan_inv_"))
def cb_aplan_inv(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    pid = c.data.split("_",2)[2]
    bot.send_message(c.message.chat.id, "📥 مدیریت مخزن:", reply_markup=plan_inventory_kb(pid))

@bot.callback_query_handler(func=lambda c: c.data.startswith("inv_add_"))
def cb_inv_add(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    pid = c.data.split("_",2)[2]
    set_state(c.from_user.id, awaiting="inv_add_item", inv_pid=pid)
    bot.send_message(c.message.chat.id, "متن/عکس کانفیگ را بفرستید.", reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("inv_del_"))
def cb_inv_del(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    _, _, pid, idx = c.data.split("_",3)
    D = db()
    L = D["plans"].get(pid,{}).get("inventory",[])
    i = to_int_safe(idx, -1)
    if 0 <= i < len(L):
        L.pop(i)
        save_db(D)
        bot.send_message(c.message.chat.id, "حذف شد.", reply_markup=plan_inventory_kb(pid))
    else:
        bot.send_message(c.message.chat.id, "اندیس نامعتبر.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("aplan_toggle_"))
def cb_aplan_toggle(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    pid = c.data.split("_",2)[2]
    D = db()
    if pid in D["plans"]:
        D["plans"][pid]["active"] = not D["plans"][pid].get("active", True)
        save_db(D)
        bot.send_message(c.message.chat.id, "وضعیت تغییر کرد.", reply_markup=plan_admin_detail_kb(pid))

@bot.callback_query_handler(func=lambda c: c.data.startswith("aplan_del_"))
def cb_aplan_del(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    pid = c.data.split("_",2)[2]
    D = db()
    if pid in D["plans"]:
        D["plans"].pop(pid)
        save_db(D)
        bot.send_message(c.message.chat.id, "پلن حذف شد.", reply_markup=plans_admin_kb())

# == Admin receipts inbox ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_receipts")
def cb_admin_receipts(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "🧾 رسیدهای در انتظار:", reply_markup=receipt_inbox_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("receipt_"))
def cb_receipt_detail(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    rid = c.data.split("_",1)[1]
    D = db()
    r = D["receipts"].get(rid)
    if not r:
        bot.send_message(c.message.chat.id, "رسید پیدا نشد.")
        return
    kind_t = "خرید کانفیگ" if r.get("kind") == "purchase" else "شارژ کیف پول"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ تایید", callback_data=f"rc_ok_{rid}"))
    kb.add(InlineKeyboardButton("❌ رد", callback_data=f"rc_no_{rid}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_receipts"))
    bot.send_message(c.message.chat.id,
        f"رسید #{rid[:6]}\n"
        f"نوع: {kind_t}\n"
        f"کاربر: {r.get('user_id')}\n"
        f"مبلغ: {money_fmt(r.get('expected',0))}\n"
        f"وضعیت: {r.get('status')}",
        reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rc_ok_") or c.data.startswith("rc_no_"))
def cb_receipt_action(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    D = db()
    ok = c.data.startswith("rc_ok_")
    rid = c.data.split("_",2)[2]
    r = D["receipts"].get(rid)
    if not r or r.get("status") != "pending":
        bot.send_message(c.message.chat.id, "رسید معتبر نیست.")
        return
    r["updated"] = now_ts()
    r["status"]  = "approved" if ok else "rejected"
    save_db(D)
    uid = r.get("user_id")
    if ok:
        if r.get("kind") == "wallet":
            # افزایش موجودی
            U = get_user(uid)
            U["wallet"] = U.get("wallet",0) + int(r.get("expected",0))
            D["users"][str(uid)] = U
            save_db(D)
            bot.send_message(c.message.chat.id, "✅ شارژ کیف پول انجام شد.", reply_markup=receipt_inbox_kb())
            try:
                bot.send_message(uid, "✅ رسید شما تایید شد و کیف پول شارژ شد.", reply_markup=main_menu(uid))
            except Exception:
                pass
        else:
            # خرید کانفیگ: تحویل و کسر موجودی
            # ساخت سفارش
            OID = str(uuid4())
            D["orders"][OID] = {
                "user_id": uid,
                "plan_id": r.get("plan_id"),
                "price_final": int(r.get("expected",0)),
                "coupon_code": (r.get("coupon") or {}).get("code"),
                "delivered": False,
                "created": now_ts()
            }
            D["users"][str(uid)]["purchases"].append(OID)
            save_db(D)
            deliver_plan_config(uid, OID)
            bot.send_message(c.message.chat.id, "✅ خرید تایید و کانفیگ ارسال شد.", reply_markup=receipt_inbox_kb())
            try:
                bot.send_message(uid, "✅ رسید شما تایید شد؛ کانفیگ ارسال شد.", reply_markup=main_menu(uid))
            except Exception:
                pass
    else:
        bot.send_message(c.message.chat.id, "❌ رسید رد شد.", reply_markup=receipt_inbox_kb())
        try:
            bot.send_message(uid, "❌ رسید شما رد شد. در صورت مشکل با پشتیبانی در تماس باشید.", reply_markup=main_menu(uid))
        except Exception:
            pass

# == Admin wallet (manual) ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_wallet")
def cb_admin_wallet(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    set_state(c.from_user.id, awaiting="admin_wallet_user")
    bot.send_message(c.message.chat.id, "آیدی عددی کاربر را بفرستید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "admin_wallet_user", content_types=['text'])
def h_admin_wallet_user(m):
    uid = m.from_user.id
    tgt = to_int_safe(m.text, 0)
    if tgt <= 0:
        bot.reply_to(m, "آیدی نامعتبر.")
        return
    ensure_user(tgt)
    set_state(uid, awaiting="admin_wallet_amount", admin_wallet_uid=tgt)
    bot.reply_to(m, "مبلغ مثبت برای شارژ، منفی برای کسر (تومان) را وارد کنید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "admin_wallet_amount", content_types=['text'])
def h_admin_wallet_amount(m):
    uid = m.from_user.id
    st = get_state(uid)
    tgt = st.get("admin_wallet_uid")
    val = to_int_safe(m.text, 0)
    D = db()
    U = get_user(tgt)
    U["wallet"] = max(0, U.get("wallet",0) + val)
    D["users"][str(tgt)] = U
    save_db(D)
    clear_state(uid, "awaiting", "admin_wallet_uid")
    bot.reply_to(m, f"انجام شد. موجودی جدید کاربر {tgt}: {money_fmt(U['wallet'])} تومان", reply_markup=back_to_admin_kb())

# == Admin users ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_users")
def cb_admin_users(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    set_state(c.from_user.id, awaiting="user_search")
    bot.send_message(c.message.chat.id, "آیدی عددی یا یوزرنیم (بدون @) را بفرستید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "user_search", content_types=['text'])
def h_user_search(m):
    uid = m.from_user.id
    query = (m.text or "").strip().lstrip("@")
    D = db()
    found_id = None
    if query.isdigit():
        if query in D["users"]:
            found_id = int(query)
    else:
        for k, U in D["users"].items():
            if U.get("username","").lower() == query.lower():
                found_id = int(k)
                break
    if not found_id:
        bot.reply_to(m, "کاربر پیدا نشد.")
        return
    U = D["users"][str(found_id)]
    total_spent = 0
    for oid in U.get("purchases", []):
        o = D["orders"].get(oid, {})
        total_spent += int(o.get("price_final", 0))
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🪙 تغییر موجودی", callback_data=f"admw_{found_id}"))
    kb.add(InlineKeyboardButton("🚫 بن کاربر", callback_data=f"ban_{found_id}"))
    kb.add(InlineKeyboardButton("♻️ آن‌بن کاربر", callback_data=f"unban_{found_id}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home"))
    bot.reply_to(m,
        f"پروفایل کاربر:\n"
        f"آیدی: {found_id}\n"
        f"یوزرنیم: @{U.get('username','')}\n"
        f"تعداد خرید: {len(U.get('purchases',[]))}\n"
        f"مجموع هزینه: {money_fmt(total_spent)} تومان\n"
        f"موجودی: {money_fmt(U.get('wallet',0))} تومان",
        reply_markup=kb)
    clear_state(uid)

# == Admin broadcast ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
def cb_broadcast(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    set_state(c.from_user.id, awaiting="broadcast_text")
    bot.send_message(c.message.chat.id, "متن اعلان همگانی را بفرستید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "broadcast_text", content_types=['text'])
def h_broadcast_text(m):
    uid = m.from_user.id
    text = (m.text or "").strip()
    if not text:
        bot.reply_to(m, "متن خالی است.")
        return
    D = db()
    cnt = 0
    for k in list(D["users"].keys()):
        try:
            bot.send_message(int(k), text)
            cnt += 1
        except Exception:
            pass
    D["broadcasts"].append({"text": text, "sent": cnt, "time": now_ts()})
    save_db(D)
    clear_state(uid)
    bot.reply_to(m, f"ارسال شد برای {cnt} کاربر.", reply_markup=back_to_admin_kb())

# == Admin coupons ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_coupons")
def cb_admin_coupons(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "🏷 مدیریت کدتخفیف:", reply_markup=coupons_kb())

@bot.callback_query_handler(func=lambda c: c.data == "coupon_create")
def cb_coupon_create(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    set_state(c.from_user.id, awaiting="create_coupon_percent", coupon={})
    bot.send_message(c.message.chat.id, "درصد تخفیف را وارد کنید (مثلاً 10):", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "create_coupon_percent", content_types=['text'])
def h_coupon_percent(m):
    uid = m.from_user.id
    val = to_int_safe(m.text, -1)
    if val <= 0 or val > 100:
        bot.reply_to(m, "عدد بین 1 تا 100 وارد کنید.")
        return
    st = get_state(uid)
    st["coupon"] = {"percent": int(val)}
    set_state(uid, awaiting="create_coupon_plan", coupon=st["coupon"])
    # انتخاب پلن خاص یا همه
    D = db()
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("همه پلن‌ها", callback_data="cc_plan_all"))
    for pid, p in D["plans"].items():
        kb.add(InlineKeyboardButton(p.get("title","بدون‌نام"), callback_data=f"cc_plan_{pid}"))
    bot.reply_to(m, "کد برای کدام پلن باشد؟", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cc_plan_"))
def cb_coupon_plan_pick(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    plan_id = c.data.split("_",2)[2]
    st = get_state(c.from_user.id)
    coup = st.get("coupon", {})
    coup["plan_limit"] = ("all" if plan_id == "all" else plan_id)
    set_state(c.from_user.id, awaiting="create_coupon_expire", coupon=coup)
    bot.send_message(c.message.chat.id, "اعتبار تا چند روز؟ (۰ = بدون انقضا)", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "create_coupon_expire", content_types=['text'])
def h_coupon_expire(m):
    uid = m.from_user.id
    days = to_int_safe(m.text, -1)
    if days < 0 or days > 3650:
        bot.reply_to(m, "عدد بین 0 تا 3650 وارد کنید.")
        return
    st = get_state(uid)
    coup = st.get("coupon", {})
    coup["expire"] = (days_from_now(days) if days>0 else 0)
    set_state(uid, awaiting="create_coupon_max", coupon=coup)
    bot.reply_to(m, "حداکثر تعداد استفاده؟ (۰ = نامحدود)", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "create_coupon_max", content_types=['text'])
def h_coupon_max(m):
    uid = m.from_user.id
    mx = to_int_safe(m.text, -1)
    if mx < 0:
        bot.reply_to(m, "عدد 0 یا بزرگتر وارد کنید.")
        return
    st = get_state(uid)
    coup = st.get("coupon", {})
    coup["max_uses"] = mx
    set_state(uid, awaiting="create_coupon_code", coupon=coup)
    bot.reply_to(m, "کد را وارد کنید (حروف/عدد).", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "create_coupon_code", content_types=['text'])
def h_coupon_code(m):
    uid = m.from_user.id
    code = (m.text or "").strip().upper()
    if not re.match(r"^[A-Z0-9_-]{3,32}$", code):
        bot.reply_to(m, "کد باید 3 تا 32 کاراکتر و فقط A-Z/0-9/_/- باشد.")
        return
    D = db()
    if code in D["coupons"]:
        bot.reply_to(m, "این کد موجود است.")
        return
    st = get_state(uid)
    coup = st.get("coupon", {})
    D["coupons"][code] = {
        "percent": coup.get("percent", 0),
        "plan_limit": coup.get("plan_limit","all"),
        "expire": coup.get("expire",0),
        "max_uses": coup.get("max_uses",0),
        "uses": 0,
        "active": True
    }
    save_db(D)
    clear_state(uid)
    bot.reply_to(m, "کدتخفیف ساخته شد.", reply_markup=back_to_admin_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("coupon_"))
def cb_coupon_view(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    code = c.data.split("_",1)[1]
    D = db()
    cp = D["coupons"].get(code)
    if not cp:
        bot.send_message(c.message.chat.id, "کد پیدا نشد.")
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔁 فعال/غیرفعال", callback_data=f"cc_t_{code}"))
    kb.add(InlineKeyboardButton("🗑 حذف", callback_data=f"cc_d_{code}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_coupons"))
    bot.send_message(c.message.chat.id,
        f"{code}\n"
        f"{cp.get('percent',0)}% | محدود: {cp.get('plan_limit','all')}\n"
        f"انقضا: {('ندارد' if not cp.get('expire') else datetime.utcfromtimestamp(cp['expire']).strftime('%Y-%m-%d'))}\n"
        f"استفاده: {cp.get('uses',0)}/{cp.get('max_uses',0) or '∞'}\n"
        f"وضعیت: {'🟢' if cp.get('active',True) else '🔴'}",
        reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cc_t_") or c.data.startswith("cc_d_"))
def cb_coupon_toggle_delete(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    D = db()
    is_toggle = c.data.startswith("cc_t_")
    code = c.data.split("_",2)[2]
    if code not in D["coupons"]:
        bot.send_message(c.message.chat.id, "کد پیدا نشد.")
        return
    if is_toggle:
        D["coupons"][code]["active"] = not D["coupons"][code].get("active", True)
        save_db(D)
        bot.send_message(c.message.chat.id, "وضعیت تغییر کرد.", reply_markup=coupons_kb())
    else:
        D["coupons"].pop(code)
        save_db(D)
        bot.send_message(c.message.chat.id, "حذف شد.", reply_markup=coupons_kb())

# == Admin settings ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_settings")
def cb_admin_settings(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    D = db()
    bot.send_message(c.message.chat.id,
                     f"شماره کارت فعلی: <code>{D['settings']['card_number']}</code>",
                     reply_markup=settings_kb())

@bot.callback_query_handler(func=lambda c: c.data == "set_card")
def cb_set_card(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    set_state(c.from_user.id, awaiting="set_card_number")
    bot.send_message(c.message.chat.id, "شماره کارت جدید را وارد کنید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "set_card_number", content_types=['text'])
def h_set_card_number(m):
    uid = m.from_user.id
    card = (m.text or "").strip()
    if len(card) < 8:
        bot.reply_to(m, "شماره کارت نامعتبر.")
        return
    D = db()
    D["settings"]["card_number"] = card
    save_db(D)
    clear_state(uid)
    bot.reply_to(m, "شماره کارت بروزرسانی شد.", reply_markup=back_to_admin_kb())

@bot.callback_query_handler(func=lambda c: c.data == "toggle_buttons")
def cb_toggle_buttons(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "روشن/خاموش کردن دکمه‌ها:", reply_markup=toggle_buttons_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("tbtn_"))
def cb_toggle_a_button(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    key = c.data.replace("tbtn_","")
    D = db()
    b = D["settings"]["buttons"].get(key, True)
    D["settings"]["buttons"][key] = not b
    save_db(D)
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=toggle_buttons_kb())

@bot.callback_query_handler(func=lambda c: c.data == "edit_texts")
def cb_edit_texts(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    S = db()["settings"]["texts"]
    kb = InlineKeyboardMarkup()
    for k in list(S.keys()):
        kb.add(InlineKeyboardButton(k, callback_data=f"et_{k}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="admin_settings"))
    bot.send_message(c.message.chat.id, "کدام متن را ویرایش کنیم؟", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("et_"))
def cb_edit_one_text(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    key = c.data.split("_",1)[1]
    set_state(c.from_user.id, awaiting="edit_text_value", edit_text_key=key)
    bot.send_message(c.message.chat.id, f"متن جدید برای «{key}» را بفرستید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "edit_text_value", content_types=['text'])
def h_edit_text_value(m):
    uid = m.from_user.id
    st = get_state(uid)
    key = st.get("edit_text_key")
    if not key:
        bot.reply_to(m, "کلید نامعتبر.")
        return
    D = db()
    D["settings"]["texts"][key] = (m.text or "")
    save_db(D)
    clear_state(uid)
    bot.reply_to(m, "بروزرسانی شد.", reply_markup=back_to_admin_kb())

# == Admin: admins ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_admins")
def cb_admin_admins(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "👑 مدیریت ادمین‌ها:", reply_markup=admins_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_rm_"))
def cb_admin_rm(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    aid = to_int_safe(c.data.split("_",2)[2], 0)
    D = db()
    if aid in D["admins"] and len(D["admins"]) > 1:
        D["admins"].remove(aid)
        save_db(D)
        bot.send_message(c.message.chat.id, "ادمین حذف شد.", reply_markup=admins_kb())
    else:
        bot.send_message(c.message.chat.id, "امکان حذف نیست (حداقل یک ادمین باید بماند).", reply_markup=admins_kb())

@bot.callback_query_handler(func=lambda c: c.data == "admin_add_admin")
def cb_admin_add_admin(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    set_state(c.from_user.id, awaiting="enter_admin_id")
    bot.send_message(c.message.chat.id, "آیدی عددی ادمین جدید را وارد کنید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "enter_admin_id", content_types=['text'])
def h_enter_admin_id(m):
    uid = m.from_user.id
    aid = to_int_safe(m.text, 0)
    if aid <= 0:
        bot.reply_to(m, "آیدی نامعتبر.")
        return
    D = db()
    if aid not in D["admins"]:
        D["admins"].append(aid)
        save_db(D)
    clear_state(uid)
    bot.reply_to(m, "ادمین افزوده شد.", reply_markup=admins_kb())

# == Tickets ==
@bot.callback_query_handler(func=lambda c: c.data == "t_new")
def cb_t_new(c):
    bot.answer_callback_query(c.id)
    set_state(c.from_user.id, awaiting="create_ticket")
    bot.send_message(c.message.chat.id, "موضوع/متن تیکت را بنویسید:", reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("t_view_"))
def cb_t_view(c):
    bot.answer_callback_query(c.id)
    tid = c.data.split("_",2)[2]
    U = get_user(c.from_user.id)
    t = U.get("tickets", {}).get(tid)
    if not t:
        bot.send_message(c.message.chat.id, "تیکت پیدا نشد.")
        return
    msgs = t.get("messages", [])
    out = [f"تیکت #{tid[:6]} ({'باز' if t.get('status')=='open' else 'بسته'})"]
    for msg in msgs[-10:]:
        who = "👤 شما" if msg.get("from")=="user" else "👑 ادمین"
        out.append(f"{who}: {msg.get('text','')}")
    kb = InlineKeyboardMarkup()
    if t.get("status") == "open":
        kb.add(InlineKeyboardButton("✉️ پاسخ", callback_data=f"t_reply_{c.from_user.id}_{tid}"))
        kb.add(InlineKeyboardButton("🗂 بستن تیکت", callback_data=f"t_close_{c.from_user.id}_{tid}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_home"))
    bot.send_message(c.message.chat.id, "\n".join(out), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("t_reply_"))
def cb_t_reply(c):
    bot.answer_callback_query(c.id)
    parts = c.data.split("_",2)[2].split("_")
    tgt_uid = int(parts[0])
    tid = parts[1]
    # اگر ادمین می‌زند، می‌رود به حالت پاسخ ادمین
    if is_admin(c.from_user.id):
        set_state(c.from_user.id, awaiting="admin_reply_ticket", reply_uid=tgt_uid, reply_tid=tid)
        bot.send_message(c.message.chat.id, "پاسخ خود را بنویسید:", reply_markup=cancel_kb())
    else:
        # کاربر پاسخ می‌دهد در همان هندلر create_ticket هم پوشش داده شد؟ نه، برای کاربر هم لازم:
        set_state(c.from_user.id, awaiting="user_reply_ticket", reply_tid=tid)
        bot.send_message(c.message.chat.id, "پاسخ خود را بنویسید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "user_reply_ticket", content_types=['text'])
def h_user_reply_ticket(m):
    uid = m.from_user.id
    st = get_state(uid)
    tid = st.get("reply_tid")
    text = (m.text or "").strip()
    if not tid or not text:
        bot.reply_to(m, "نامعتبر.")
        return
    D = db()
    U = D["users"].get(str(uid), {})
    if tid not in U.get("tickets", {}):
        bot.reply_to(m, "تیکت پیدا نشد.")
        return
    U["tickets"][tid]["messages"].append({"from":"user","text":text,"time":now_ts()})
    save_db(D)
    clear_state(uid)
    bot.reply_to(m, "پاسخ ثبت شد.", reply_markup=main_menu(uid))
    # اطلاع ادمین‌ها
    for adm in D["admins"]:
        try:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("✉️ پاسخ", callback_data=f"t_reply_{uid}_{tid}"))
            bot.send_message(int(adm), f"پاسخ جدید از کاربر {uid} در تیکت #{tid[:6]}:\n{text}", reply_markup=kb)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("t_close_"))
def cb_t_close(c):
    bot.answer_callback_query(c.id)
    parts = c.data.split("_",2)[2].split("_")
    tgt_uid = int(parts[0])
    tid = parts[1]
    D = db()
    U = D["users"].get(str(tgt_uid), {})
    if tid in U.get("tickets", {}):
        U["tickets"][tid]["status"] = "closed"
        save_db(D)
    bot.send_message(c.message.chat.id, "تیکت بسته شد.")

# == Admin stats ==
@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def cb_admin_stats(c):
    if not is_admin(c.from_user.id):
        return
    bot.answer_callback_query(c.id)
    D = db()
    orders = list(D["orders"].values())
    total_count = len(orders)
    total_sum = sum(int(o.get("price_final",0)) for o in orders)
    # Top buyers
    spend = {}
    for oid, o in D["orders"].items():
        u = o.get("user_id")
        spend[u] = spend.get(u, 0) + int(o.get("price_final",0))
    top = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = [
        "📊 آمار فروش",
        f"تعداد کانفیگ فروخته‌شده: {total_count}",
        f"فروش کل: {money_fmt(total_sum)} تومان",
        "— برترین خریداران —"
    ]
    for i,(u, s) in enumerate(top,1):
        lines.append(f"{i}) {u} — {money_fmt(s)} تومان")
    bot.send_message(c.message.chat.id, "\n".join(lines), reply_markup=back_to_admin_kb())

# -----------------------------
# Plan Delivery
# -----------------------------
def deliver_plan_config(uid: int, order_id: str):
    D = db()
    o = D["orders"].get(order_id, {})
    pid = o.get("plan_id")
    p = D["plans"].get(pid, {})
    inv = p.get("inventory", [])
    if not inv:
        bot.send_message(uid, "⚠️ موجودی این پلن به پایان رسیده؛ با پشتیبانی تماس بگیرید.")
        return
    item = inv.pop(0)  # FIFO
    save_db(D)
    # ارسال متن + تصویر (اگر هست)
    text = item.get("text","")
    photo_id = item.get("photo")
    if photo_id:
        try:
            bot.send_photo(uid, photo_id, caption=text or "کانفیگ")
        except Exception:
            # اگر ارسال عکس خطا داد، متنی بفرستیم
            bot.send_message(uid, text or "کانفیگ")
    else:
        bot.send_message(uid, text or "کانفیگ")
    # به‌روزرسانی سفارش
    D = db()
    D["orders"][order_id]["delivered"] = True
    D["orders"][order_id]["delivered_at"] = now_ts()
    save_db(D)

# -----------------------------
# Admin Plan Wizard (title, price, days, volume, desc)
# -----------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "aplan_title", content_types=['text'])
def h_aplan_title(m):
    uid = m.from_user.id
    title = (m.text or "").strip()
    if not title:
        bot.reply_to(m, "عنوان خالی است.")
        return
    set_state(uid, awaiting="aplan_price", aplan={"title": title})
    bot.reply_to(m, "قیمت (تومان) را وارد کنید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "aplan_price", content_types=['text'])
def h_aplan_price(m):
    uid = m.from_user.id
    price = to_int_safe(m.text, -1)
    if price <= 0:
        bot.reply_to(m, "قیمت نامعتبر.")
        return
    st = get_state(uid)
    st["aplan"]["price"] = price
    set_state(uid, **st, awaiting="aplan_days")
    bot.reply_to(m, "مدت (روز) را وارد کنید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "aplan_days", content_types=['text'])
def h_aplan_days(m):
    uid = m.from_user.id
    days = to_int_safe(m.text, -1)
    if days < 0 or days > 3650:
        bot.reply_to(m, "روز نامعتبر.")
        return
    st = get_state(uid)
    st["aplan"]["days"] = days
    set_state(uid, **st, awaiting="aplan_volume")
    bot.reply_to(m, "حجم/ترافیک (مثلاً 100GB) را بنویسید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "aplan_volume", content_types=['text'])
def h_aplan_volume(m):
    uid = m.from_user.id
    volume = (m.text or "").strip()
    if not volume:
        bot.reply_to(m, "حجم نامعتبر.")
        return
    st = get_state(uid)
    st["aplan"]["volume"] = volume
    set_state(uid, **st, awaiting="aplan_desc")
    bot.reply_to(m, "توضیح پلن را بنویسید:", reply_markup=cancel_kb())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "aplan_desc", content_types=['text'])
def h_aplan_desc(m):
    uid = m.from_user.id
    desc = (m.text or "").strip()
    st = get_state(uid)
    plan = st.get("aplan", {})
    plan["desc"] = desc
    # ذخیره نهایی
    D = db()
    pid = str(uuid4())
    D["plans"][pid] = {
        "title": plan.get("title",""),
        "price": plan.get("price",0),
        "days": plan.get("days",0),
        "volume": plan.get("volume",""),
        "desc": plan.get("desc",""),
        "inventory": [],
        "active": True
    }
    save_db(D)
    clear_state(uid)
    bot.reply_to(m, "پلن افزوده شد.", reply_markup=plans_admin_kb())

# == Admin: Append inventory item ==
@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting") == "inv_add_item", content_types=['text','photo'])
def h_inv_add_item(m):
    uid = m.from_user.id
    st = get_state(uid)
    pid = st.get("inv_pid")
    if not pid:
        bot.reply_to(m, "شناسه پلن نامعتبر.")
        return
    D = db()
    P = D["plans"].get(pid)
    if not P:
        bot.reply_to(m, "پلن پیدا نشد.")
        return
    item = {"text":"", "photo":None}
    if m.photo:
        item["photo"] = m.photo[-1].file_id
        item["text"] = (m.caption or "")
    else:
        item["text"] = (m.text or "")
    P["inventory"].append(item)
    save_db(D)
    clear_state(uid, "awaiting", "inv_pid")
    bot.reply_to(m, "مخزن به‌روزرسانی شد.", reply_markup=plan_inventory_kb(pid))

# -----------------------------
# Apply coupon during plan re-entry (validate increments)
# -----------------------------
def consume_coupon_if_any(code: str):
    D = db()
    if not code:
        return
    c = D["coupons"].get(code)
    if not c:
        return
    c["uses"] = c.get("uses",0) + 1
    save_db(D)

# -----------------------------
# Webhook bootstrap
# -----------------------------
def create_app():
    set_webhook_once()
    return app

# برای gunicorn: main:app
app = create_app()
