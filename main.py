# main.py
# -*- coding: utf-8 -*-

import os
import time
import json
import uuid
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, abort
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto,
    ReplyKeyboardMarkup, KeyboardButton
)

# ----------------------------
#  تنظیمات پایه و وبهوک
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
APP_URL   = os.getenv("APP_URL", "").rstrip("/")  # مثل: https://your-domain.tld

if not BOT_TOKEN:
    raise RuntimeError("Config Var BOT_TOKEN تعریف نشده است.")
if not APP_URL:
    raise RuntimeError("Config Var APP_URL تعریف نشده است.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{APP_URL}{WEBHOOK_PATH}"

app = Flask(__name__)

# ----------------------------
#  لاگ
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("bot")

# ----------------------------
#  دیتابیس ساده (JSON)
# ----------------------------
DB_FILE = "db.json"

DEFAULT_TEXTS = {
    "menu_title": "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
    "btn_buy_plan": "📦 خرید پلن",
    "btn_wallet": "🪙 کیف پول",
    "btn_tickets": "🎫 تیکت پشتیبانی",
    "btn_account": "👤 حساب کاربری",
    "btn_cancel": "↩️ انصراف",

    "wallet_title": "🪙 کیف پول\n\nموجودی فعلی شما: <b>{balance}</b> تومان",
    "btn_wallet_charge": "➕ شارژ کیف پول",
    "btn_wallet_tx": "🧾 تاریخچه تراکنش‌ها",
    "wallet_send_receipt_prompt": "لطفاً رسید واریز را ارسال کنید.\nپس از ارسال، رسید شما برای ادمین ارسال می‌شود و در انتظار تأیید قرار می‌گیرد.",
    "wallet_receipt_registered": "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین…",

    "plans_title": "📦 لیست پلن‌ها:",
    "plan_out_of_stock": "ناموجود",
    "plan_details": "نام: {name}\nمدت: {days} روز\nحجم: {gb} گیگ\nقیمت: {price} تومان\n{desc}",
    "btn_card_to_card": "🏦 کارت‌به‌کارت",
    "btn_pay_with_wallet": "🪙 پرداخت با کیف پول",
    "enter_coupon": "اگر کد تخفیف دارید بفرستید؛ در غیر این صورت «انصراف» را بزنید.",
    "coupon_applied": "✅ کد تخفیف اعمال شد.\nمبلغ قبل: {before} تومان\nمبلغ بعد: {after} تومان",
    "coupon_invalid": "❌ کد تخفیف نامعتبر است.",
    "insufficient_wallet": "موجودی کیف پول کافی نیست.\nمبلغ مورد نیاز: <b>{need}</b> تومان\nمی‌خواهید همین مقدار شارژ شود؟",
    "btn_charge_exact_diff": "شارژ همین مقدار",
    "purchase_done": "✅ پلن خریداری شد و ارسال شد.",
    "card_to_card_info": "👈 لطفاً مبلغ <b>{amount}</b> تومان را به کارت زیر واریز کنید و رسید را ارسال کنید:\n\n<b>{card_number}</b>\n\nبعد از ارسال رسید، دکمه «ثبت رسید» را بزنید.",
    "btn_submit_receipt": "📤 ثبت رسید",
    "receipt_sent_for_purchase": "✅ رسید شما برای خرید پلن ثبت شد؛ منتظر تأیید ادمین…",

    "account_title": "👤 حساب کاربری",
    "account_info": "آیدی عددی: <code>{uid}</code>\nیوزرنیم: @{uname}\nتعداد کانفیگ‌های خریداری‌شده: {orders_count}",
    "my_orders_title": "🧾 سفارش‌های من",
    "order_item": "پلن: {plan_name} | تاریخ: {date}\nانقضا: {expire}",
    "btn_my_orders": "🧾 سفارش‌های من",

    "tickets_title": "🎫 تیکت پشتیبانی",
    "btn_ticket_new": "➕ تیکت جدید",
    "btn_ticket_list": "📂 تیکت‌های من",
    "ticket_enter_subject": "موضوع تیکت را انتخاب کنید:",
    "ticket_write_message": "لطفاً پیام خود را بنویسید:",
    "ticket_created": "✅ تیکت شما ثبت شد. پاسخ ادمین در همین گفتگو ارسال می‌شود.",

    # Admin area
    "btn_admin": "🛠 پنل ادمین",
    "admin_title": "🛠 پنل ادمین",
    "btn_admin_receipts": "📥 رسیدهای جدید",
    "btn_admin_plans": "📦 مدیریت پلن‌ها و مخزن",
    "btn_admin_coupons": "🏷 مدیریت کد تخفیف",
    "btn_admin_wallet": "🪙 کیف پول (ادمین)",
    "btn_admin_users": "👥 مدیریت کاربران",
    "btn_admin_broadcast": "📢 اعلان همگانی",
    "btn_admin_texts": "🧩 مدیریت دکمه‌ها و متون",
    "btn_admin_admins": "👑 مدیریت ادمین‌ها",
    "btn_admin_card_number": "💳 تنظیم شماره کارت",
    "admin_back_user": "🔁 نمایش نمای کاربر",
    "admin_saved": "✅ ذخیره شد.",
    "admin_enter_card_number": "شماره کارت جدید را ارسال کنید:",

    "receipt_inbox_header": "📥 رسیدهای در انتظار ({count} مورد)\n🔹 فقط رسیدهای رسیدگی‌نشده نمایش داده می‌شود.",
    "btn_next_unseen_receipt": "➡️ بعدی (رسید رسیدگی‌نشده)",
    "no_pending_receipts": "هیچ رسیدِ رسیدگی‌نشده‌ای نیست.",

    "receipt_card": "نوع: {kind}\nکاربر: @{uname} ({uid})\nمبلغ/توضیحات کاربر: {note}\nزمان: {ts}",
    "btn_receipt_approve": "✅ تأیید",
    "btn_receipt_reject": "❌ رد",
    "enter_reject_reason": "دلیل رد را بنویسید (کوتاه):",

    "notify_receipt_approved_wallet": "✅ شارژ کیف پول شما تأیید شد. مبلغ تأییدشده: {amount} تومان",
    "notify_receipt_approved_purchase": "✅ خرید شما تأیید شد و کانفیگ ارسال گردید.",
    "notify_receipt_rejected": "❌ رسید شما رد شد.\nعلت: {reason}",

    "plan_sent_caption": "✅ کانفیگ شما:\nپلن: {plan}\nانقضا: {expire}",

    "btn_back": "⬅️ بازگشت",
}

DEFAULT_BUTTONS_ACTIVE = {
    "buy_plan": True,
    "wallet": True,
    "tickets": True,
    "account": True,
    "admin": True,  # فقط برای ادمین نمایش داده می‌شود
}

DEFAULT_CARD_NUMBER = "6037-xxxx-xxxx-xxxx"  # ادمین می‌تواند از پنل تغییر دهد

def now_ts():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def load_db():
    if not os.path.exists(DB_FILE):
        init = {
            "admins": [1743359080],  # ادمین پیش‌فرض
            "users": {},             # {uid: {"wallet":0, "orders":[], "tickets":[], "state":{}}}
            "plans": {},             # {plan_id: {...}}
            "inventory": {},         # {plan_id: [{"text": "...", "image": None}, ...]}
            "coupons": {},           # {code: {...}}
            "receipts": {},          # {rid: {...}}
            "texts": DEFAULT_TEXTS,
            "buttons_active": DEFAULT_BUTTONS_ACTIVE,
            "card_number": DEFAULT_CARD_NUMBER,
            "broadcast_log": [],
        }
        save_db(init)
        return init
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

DB = load_db()

# --------------- کمک‌تابع‌ها ---------------
def is_admin(uid: int) -> bool:
    return int(uid) in DB.get("admins", [])

def ensure_user(uid: int, uname: str = ""):
    uid = str(uid)
    urec = DB["users"].get(uid)
    if not urec:
        DB["users"][uid] = {
            "uid": int(uid),
            "uname": uname or "",
            "wallet": 0,
            "orders": [],      # [{"plan_id","plan_name","date","expire"}]
            "tickets": [],     # [{"id","subject","messages":[{"from","text","ts"}],"open": True}]
            "state": {},       # حالت‌های جاری برای سناریو‌ها
            "seen_receipts": [], # برای ادمین‌ها: رسیدهایی که دیده/رسیدگی کرده
        }
        save_db(DB)
    else:
        if uname and urec.get("uname") != uname:
            DB["users"][uid]["uname"] = uname
            save_db(DB)

def user_state(uid: int) -> dict:
    ensure_user(uid)
    return DB["users"][str(uid)]["state"]

def clear_state(uid: int):
    DB["users"][str(uid)]["state"] = {}
    save_db(DB)

def fmt_price(n: int) -> str:
    return f"{n:,}"

# --------------- کیبوردها ---------------
def main_menu(uid: int):
    t = DB["texts"]
    ba = DB["buttons_active"]
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if ba.get("buy_plan"): kb.add(KeyboardButton(t["btn_buy_plan"]))
    if ba.get("wallet"):   kb.add(KeyboardButton(t["btn_wallet"]))
    if ba.get("tickets"):  kb.add(KeyboardButton(t["btn_tickets"]))
    if ba.get("account"):  kb.add(KeyboardButton(t["btn_account"]))
    if is_admin(uid) and ba.get("admin"):
        kb.add(KeyboardButton(t["btn_admin"]))
    return kb

def kb_cancel():
    t = DB["texts"]
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton(t["btn_cancel"]))
    return kb

# --------------- وبهوک ---------------
@app.route("/", methods=["GET"])
def health():
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

# ست وبهوک در استارت
def set_webhook_once():
    try:
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        log.info(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        log.exception("Failed to set webhook: %s", e)

set_webhook_once()

# --------------- هندلرهای دکمه‌ای (بدون /) ---------------
def send_home(chat_id, uid, uname):
    ensure_user(uid, uname)
    t = DB["texts"]
    bot.send_message(
        chat_id,
        t["menu_title"],
        reply_markup=main_menu(uid)
    )

@bot.message_handler(commands=["start"])
def cmd_start(m):
    send_home(m.chat.id, m.from_user.id, m.from_user.username or "")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(m):
    uid = m.from_user.id
    uname = m.from_user.username or ""
    ensure_user(uid, uname)
    text = (m.text or "").strip()
    t = DB["texts"]

    # دکمه‌های اصلی
    if text == t["btn_buy_plan"]:
        show_plans(m.chat.id, uid)
        return

    if text == t["btn_wallet"]:
        show_wallet(m.chat.id, uid)
        return

    if text == t["btn_tickets"]:
        show_tickets(m.chat.id, uid)
        return

    if text == t["btn_account"]:
        show_account(m.chat.id, uid)
        return

    if text == t["btn_admin"]:
        if is_admin(uid):
            show_admin(m.chat.id, uid)
        else:
            bot.reply_to(m, "شما ادمین نیستید.")
        return

    if text == t["btn_cancel"]:
        clear_state(uid)
        send_home(m.chat.id, uid, uname)
        return

    # حالت‌ها
    st = user_state(uid)

    # ورود کد تخفیف
    if st.get("await_coupon_for_plan"):
        code = text.upper().strip()
        plan_id = st["await_coupon_for_plan"]["plan_id"]
        plan = DB["plans"].get(plan_id)
        if not plan:
            clear_state(uid)
            bot.reply_to(m, "پلن یافت نشد.")
            return

        # کد تخفیف
        coupon = DB["coupons"].get(code)
        if coupon and coupon.get("active", True):
            # اگر محدود به پلن
            allowed = (coupon.get("plan_id") in [None, "", plan_id]) or (coupon.get("plan_id") is None)
            if allowed:
                percent = int(coupon.get("percent", 0))
                before = int(plan["price"])
                after = before - (before * percent // 100)
                st["await_coupon_for_plan"]["coupon"] = {"code": code, "percent": percent, "after": after, "before": before}
                save_db(DB)
                bot.reply_to(m, t["coupon_applied"].format(before=fmt_price(before), after=fmt_price(after)))
            else:
                bot.reply_to(m, t["coupon_invalid"])
        else:
            if text != t["btn_cancel"]:
                bot.reply_to(m, t["coupon_invalid"])
        # نمایش روش‌های پرداخت
        send_payment_options(m.chat.id, uid, plan_id)
        return

    # پیامِ وارد کردن شماره کارت جدید توسط ادمین
    if st.get("await_admin_card_number"):
        DB["card_number"] = text.replace(" ", "")
        save_db(DB)
        clear_state(uid)
        bot.reply_to(m, DB["texts"]["admin_saved"])
        show_admin(m.chat.id, uid)
        return

    # رد رسید - گرفتن دلیل
    if st.get("await_reject_reason"):
        rid = st["await_reject_reason"]["rid"]
        reason = text.strip()
        clear_state(uid)
        admin_reject_receipt(uid, rid, reason, chat_id=m.chat.id)
        return

    # ایجاد تیکت
    if st.get("await_ticket_message"):
        subj = st["await_ticket_message"]["subject"]
        ticket_create(uid, subj, text)
        clear_state(uid)
        bot.reply_to(m, DB["texts"]["ticket_created"], reply_markup=main_menu(uid))
        return

    # حالت خاص دیگری نبود:
    # اگر چیزی نا مشخص بود، برگرد به منو
    send_home(m.chat.id, uid, uname)

# --------------- خرید پلن ---------------
def show_plans(chat_id, uid):
    t = DB["texts"]
    kb = InlineKeyboardMarkup()
    any_plan = False
    for pid, p in DB["plans"].items():
        stock = len(DB["inventory"].get(pid, []))
        name = p["name"]
        label = f"{name} ({'ناموجود' if stock==0 else f'موجودی:{stock}'})"
        if stock == 0:
            # غیرفعال شدن خودکار (فقط نمایش)
            label += " ❌"
            btn = InlineKeyboardButton(label, callback_data=f"noop")
        else:
            btn = InlineKeyboardButton(label, callback_data=f"plan:{pid}")
        kb.add(btn)
        any_plan = True

    if not any_plan:
        bot.send_message(chat_id, "هیچ پلنی ثبت نشده است.", reply_markup=main_menu(uid))
        return

    bot.send_message(chat_id, t["plans_title"], reply_markup=kb)

def plan_details_text(p):
    t = DB["texts"]
    return t["plan_details"].format(
        name=p["name"],
        days=p["days"],
        gb=p["gb"],
        price=fmt_price(p["price"]),
        desc=p.get("desc","")
    )

def send_plan_detail(chat_id, uid, plan_id):
    p = DB["plans"].get(plan_id)
    if not p:
        bot.send_message(chat_id, "پلن یافت نشد.", reply_markup=main_menu(uid))
        return

    stock = len(DB["inventory"].get(plan_id, []))
    if stock == 0:
        bot.send_message(chat_id, "این پلن ناموجود است.", reply_markup=main_menu(uid))
        return

    txt = plan_details_text(p)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔖 وارد کردن کد تخفیف", callback_data=f"coupon:{plan_id}"))
    kb.add(
        InlineKeyboardButton(DB["texts"]["btn_card_to_card"], callback_data=f"pay:card:{plan_id}"),
        InlineKeyboardButton(DB["texts"]["btn_pay_with_wallet"], callback_data=f"pay:wallet:{plan_id}")
    )
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="back:plans"))
    bot.send_message(chat_id, txt, reply_markup=kb)

def send_payment_options(chat_id, uid, plan_id):
    p = DB["plans"].get(plan_id)
    if not p:
        bot.send_message(chat_id, "پلن یافت نشد.", reply_markup=main_menu(uid))
        return
    txt = "روش پرداخت را انتخاب کنید:"
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton(DB["texts"]["btn_card_to_card"], callback_data=f"pay:card:{plan_id}"),
        InlineKeyboardButton(DB["texts"]["btn_pay_with_wallet"], callback_data=f"pay:wallet:{plan_id}")
    )
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data=f"plan:{plan_id}"))
    bot.send_message(chat_id, txt, reply_markup=kb)

def apply_coupon_if_any(uid, plan_id, price):
    st = user_state(uid)
    info = st.get("await_coupon_for_plan")
    if info and info.get("plan_id") == plan_id and info.get("coupon"):
        return max(int(info["coupon"]["after"]), 0)
    return int(price)

def wallet_pay_flow(chat_id, uid, plan_id):
    p = DB["plans"].get(plan_id)
    if not p:
        bot.send_message(chat_id, "پلن یافت نشد.", reply_markup=main_menu(uid))
        return
    final = apply_coupon_if_any(uid, plan_id, p["price"])
    bal = DB["users"][str(uid)]["wallet"]

    if bal >= final:
        # پرداخت
        DB["users"][str(uid)]["wallet"] = bal - final
        # ارسال کانفیگ
        ok = send_config_from_inventory(uid, chat_id, plan_id, p["name"], p["days"])
        if ok:
            bot.send_message(chat_id, DB["texts"]["purchase_done"], reply_markup=main_menu(uid))
            # پاک کردن حالت کد تخفیف
            clear_state(uid)
            save_db(DB)
        else:
            bot.send_message(chat_id, "موجودی پلن تمام شد.", reply_markup=main_menu(uid))
        return
    else:
        need = final - bal
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(DB["texts"]["btn_charge_exact_diff"], callback_data=f"wallet:charge:{need}:{plan_id}"))
        kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data=f"plan:{plan_id}"))
        bot.send_message(chat_id, DB["texts"]["insufficient_wallet"].format(need=fmt_price(need)), reply_markup=kb)

def card_to_card_flow(chat_id, uid, plan_id):
    p = DB["plans"].get(plan_id)
    if not p:
        bot.send_message(chat_id, "پلن یافت نشد.", reply_markup=main_menu(uid))
        return
    final = apply_coupon_if_any(uid, plan_id, p["price"])
    txt = DB["texts"]["card_to_card_info"].format(amount=fmt_price(final), card_number=DB["card_number"])
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(DB["texts"]["btn_submit_receipt"], callback_data=f"purchase:receipt:{plan_id}:{final}"))
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data=f"plan:{plan_id}"))
    bot.send_message(chat_id, txt, reply_markup=kb)

def send_config_from_inventory(uid, chat_id, plan_id, plan_name, days):
    inv = DB["inventory"].get(plan_id, [])
    if not inv:
        return False
    item = inv.pop(0)
    save_db(DB)

    expire = (datetime.utcnow() + timedelta(days=int(days))).strftime("%Y-%m-%d")
    # ارسال متن + تصویر (اگر داشت)
    caption = DB["texts"]["plan_sent_caption"].format(plan=plan_name, expire=expire)
    if item.get("image"):
        try:
            bot.send_photo(chat_id, item["image"], caption=caption)
        except:
            bot.send_message(chat_id, caption)
            bot.send_message(chat_id, item.get("text",""))
    else:
        bot.send_message(chat_id, caption)
        if item.get("text"):
            bot.send_message(chat_id, item["text"])

    # ثبت سفارش
    DB["users"][str(uid)]["orders"].append({
        "plan_id": plan_id,
        "plan_name": plan_name,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "expire": expire
    })
    save_db(DB)
    return True

# --------------- کیف پول ---------------
def show_wallet(chat_id, uid):
    bal = DB["users"][str(uid)]["wallet"]
    txt = DB["texts"]["wallet_title"].format(balance=fmt_price(bal))
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(DB["texts"]["btn_wallet_charge"], callback_data="wallet:charge"))
    kb.add(InlineKeyboardButton(DB["texts"]["btn_wallet_tx"], callback_data="wallet:tx"))
    bot.send_message(chat_id, txt, reply_markup=kb)

def ask_wallet_charge(chat_id, uid):
    st = user_state(uid)
    st["await_receipt"] = {"kind": "wallet_charge"}
    save_db(DB)
    bot.send_message(chat_id, DB["texts"]["wallet_send_receipt_prompt"], reply_markup=kb_cancel())

# --------------- حساب کاربری ---------------
def show_account(chat_id, uid):
    u = DB["users"][str(uid)]
    txt = DB["texts"]["account_info"].format(
        uid=uid,
        uname=u.get("uname") or "-",
        orders_count=len(u.get("orders",[]))
    )
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(DB["texts"]["btn_my_orders"], callback_data="acct:orders"))
    bot.send_message(chat_id, txt, reply_markup=kb)

def show_my_orders(chat_id, uid):
    orders = DB["users"][str(uid)].get("orders", [])
    if not orders:
        bot.send_message(chat_id, "شما سفارشی ثبت نکرده‌اید.")
        return
    lines = [DB["texts"]["my_orders_title"], ""]
    for o in orders[-20:][::-1]:
        lines.append(DB["texts"]["order_item"].format(
            plan_name=o["plan_name"], date=o["date"], expire=o["expire"]
        ))
    bot.send_message(chat_id, "\n".join(lines))

# --------------- تیکت ---------------
def show_tickets(chat_id, uid):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(DB["texts"]["btn_ticket_new"], callback_data="ticket:new"))
    kb.add(InlineKeyboardButton(DB["texts"]["btn_ticket_list"], callback_data="ticket:list"))
    bot.send_message(chat_id, DB["texts"]["tickets_title"], reply_markup=kb)

def ticket_create(uid, subject, message):
    tlist = DB["users"][str(uid)]["tickets"]
    tid = str(uuid.uuid4())[:8]
    tlist.append({
        "id": tid,
        "subject": subject,
        "messages": [{"from":"user", "text": message, "ts": now_ts()}],
        "open": True
    })
    save_db(DB)
    # اطلاع به ادمین‌ها
    for aid in DB["admins"]:
        try:
            bot.send_message(aid, f"🎫 تیکت جدید از @{DB['users'][str(uid)]['uname']} ({uid})\nموضوع: {subject}")
        except:
            pass

# --------------- رسیدها ---------------
def create_receipt(uid, kind, note="", file_id=None, related=None):
    rid = str(uuid.uuid4())[:12]
    DB["receipts"][rid] = {
        "rid": rid,
        "uid": uid,
        "uname": DB["users"][str(uid)]["uname"],
        "kind": kind,  # wallet_charge | purchase
        "note": note,
        "file_id": file_id,  # photo/document file_id
        "related": related or {}, # مثلا: {"plan_id":..., "amount":...}
        "status": "pending",
        "ts": now_ts(),
        "seen_by": [],  # ادمین‌هایی که دیدن
        "handled_by": None,
        "reject_reason": ""
    }
    save_db(DB)
    notify_admins_new_receipt(rid)
    return rid

def notify_admins_new_receipt(rid):
    R = DB["receipts"][rid]
    txt = f"📥 رسید جدید\nنوع: {R['kind']}\nکاربر: @{R['uname']} ({R['uid']})\nزمان: {R['ts']}"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("بازکردن", callback_data=f"receipt:open:{rid}"))
    for aid in DB["admins"]:
        try:
            bot.send_message(aid, txt, reply_markup=kb)
        except:
            pass

def admin_open_next_unseen(uid, chat_id):
    # رسیدهای پندینگ که handled ندارند و در seen_by این uid نیست
    for rid, R in DB["receipts"].items():
        if R["status"] == "pending" and (R.get("handled_by") in [None, ""]) and (uid not in R.get("seen_by", [])):
            # مارک دیده شده
            R.setdefault("seen_by", []).append(uid)
            save_db(DB)
            show_receipt_card(chat_id, rid, admin_view=True)
            return
    bot.send_message(chat_id, DB["texts"]["no_pending_receipts"])

def show_receipt_card(chat_id, rid, admin_view=False):
    R = DB["receipts"].get(rid)
    if not R:
        bot.send_message(chat_id, "رسید یافت نشد.")
        return
    txt = DB["texts"]["receipt_card"].format(
        kind=("شارژ کیف پول" if R["kind"]=="wallet_charge" else "خرید کانفیگ"),
        uname=R["uname"] or "-",
        uid=R["uid"],
        note=R.get("note","-"),
        ts=R["ts"]
    )
    if admin_view:
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton(DB["texts"]["btn_receipt_approve"], callback_data=f"receipt:approve:{rid}"),
            InlineKeyboardButton(DB["texts"]["btn_receipt_reject"], callback_data=f"receipt:reject:{rid}")
        )
        bot.send_message(chat_id, txt, reply_markup=kb)
    else:
        bot.send_message(chat_id, txt)

def admin_approve_receipt(uid_admin, rid, chat_id=None):
    R = DB["receipts"].get(rid)
    if not R or R["status"] != "pending":
        if chat_id: bot.send_message(chat_id, "این رسید در وضعیت مناسب نیست.")
        return
    R["status"] = "approved"
    R["handled_by"] = uid_admin
    save_db(DB)

    uid = R["uid"]
    if R["kind"] == "wallet_charge":
        amount = int(R["related"].get("amount", 0))
        DB["users"][str(uid)]["wallet"] += amount
        save_db(DB)
        # اطلاع به کاربر
        bot.send_message(uid, DB["texts"]["notify_receipt_approved_wallet"].format(amount=fmt_price(amount)))
    else:
        # خرید کانفیگ
        plan_id = R["related"]["plan_id"]
        p = DB["plans"].get(plan_id)
        if p:
            ok = send_config_from_inventory(uid, uid, plan_id, p["name"], p["days"])
            if ok:
                bot.send_message(uid, DB["texts"]["notify_receipt_approved_purchase"])
        # else: اگر نبود، کاری نمی‌کنیم

    if chat_id:
        bot.send_message(chat_id, DB["texts"]["admin_saved"])

def admin_reject_receipt(uid_admin, rid, reason, chat_id=None):
    R = DB["receipts"].get(rid)
    if not R or R["status"] != "pending":
        if chat_id: bot.send_message(chat_id, "این رسید در وضعیت مناسب نیست.")
        return
    R["status"] = "rejected"
    R["handled_by"] = uid_admin
    R["reject_reason"] = reason or "-"
    save_db(DB)
    bot.send_message(R["uid"], DB["texts"]["notify_receipt_rejected"].format(reason=reason or "-"))
    if chat_id:
        bot.send_message(chat_id, DB["texts"]["admin_saved"])

# --------------- کال‌بک‌ها ---------------
@bot.callback_query_handler(func=lambda c: True)
def on_cb(c):
    uid = c.from_user.id
    uname = c.from_user.username or ""
    ensure_user(uid, uname)
    data = c.data or ""

    try:
        if data == "noop":
            bot.answer_callback_query(c.id, "—")
            return

        if data == "back:plans":
            bot.answer_callback_query(c.id)
            show_plans(c.message.chat.id, uid)
            return

        if data.startswith("plan:"):
            _, pid = data.split(":", 1)
            bot.answer_callback_query(c.id)
            send_plan_detail(c.message.chat.id, uid, pid)
            return

        if data.startswith("coupon:"):
            _, pid = data.split(":")
            st = user_state(uid)
            st["await_coupon_for_plan"] = {"plan_id": pid}
            save_db(DB)
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id, DB["texts"]["enter_coupon"], reply_markup=kb_cancel())
            return

        if data.startswith("pay:wallet:"):
            _, _, pid = data.split(":")
            bot.answer_callback_query(c.id)
            wallet_pay_flow(c.message.chat.id, uid, pid)
            return

        if data.startswith("pay:card:"):
            _, _, pid = data.split(":")
            bot.answer_callback_query(c.id)
            card_to_card_flow(c.message.chat.id, uid, pid)
            return

        if data.startswith("wallet:charge:"):
            parts = data.split(":")
            # wallet:charge  یا wallet:charge:<diff>:<plan_id>
            if len(parts) == 2:
                bot.answer_callback_query(c.id)
                ask_wallet_charge(c.message.chat.id, uid)
            else:
                _, _, need, plan_id = parts
                need = int(need)
                st = user_state(uid)
                st["await_receipt"] = {"kind":"wallet_charge", "force_amount": need, "for_plan": plan_id}
                save_db(DB)
                bot.answer_callback_query(c.id)
                bot.send_message(c.message.chat.id, DB["texts"]["wallet_send_receipt_prompt"], reply_markup=kb_cancel())
            return

        if data == "wallet:tx":
            bot.answer_callback_query(c.id)
            # نمایش ساده (از لاگ رسیدها)
            lines = ["🧾 تراکنش‌های اخیر:"]
            items = []
            for rid, R in DB["receipts"].items():
                if R["uid"] == uid and R["status"] == "approved":
                    if R["kind"] == "wallet_charge":
                        items.append(f"➕ شارژ کیف پول: +{fmt_price(int(R['related'].get('amount',0)))} | {R['ts']}")
                    elif R["kind"] == "purchase":
                        plan_id = R["related"].get("plan_id","-")
                        items.append(f"🛍 خرید: پلن {DB['plans'].get(plan_id,{}).get('name','?')} | {R['ts']}")
            if not items:
                lines.append("موردی ثبت نشده.")
            else:
                lines += items[-20:][::-1]
            bot.send_message(c.message.chat.id, "\n".join(lines))
            return

        if data.startswith("purchase:receipt:"):
            _, _, pid, final = data.split(":")
            final = int(final)
            st = user_state(uid)
            st["await_receipt"] = {"kind": "purchase", "plan_id": pid, "expected": final, "coupon": st.get("await_coupon_for_plan",{}).get("coupon")}
            save_db(DB)
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id, "لطفاً رسید پرداخت را ارسال کنید.", reply_markup=kb_cancel())
            return

        # حساب کاربری
        if data == "acct:orders":
            bot.answer_callback_query(c.id)
            show_my_orders(c.message.chat.id, uid)
            return

        # ادمین
        if data == "admin:home":
            bot.answer_callback_query(c.id)
            show_admin(c.message.chat.id, uid)
            return

        if data == "admin:receipts":
            bot.answer_callback_query(c.id)
            count = sum(1 for r in DB["receipts"].values() if r["status"]=="pending")
            txt = DB["texts"]["receipt_inbox_header"].format(count=count)
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(DB["texts"]["btn_next_unseen_receipt"], callback_data="admin:next_receipt"))
            bot.send_message(c.message.chat.id, txt, reply_markup=kb)
            return

        if data == "admin:next_receipt":
            bot.answer_callback_query(c.id)
            admin_open_next_unseen(uid, c.message.chat.id)
            return

        if data.startswith("receipt:open:"):
            _, _, rid = data.split(":")
            # مارک دیده‌شده
            R = DB["receipts"].get(rid)
            if R and uid not in R.get("seen_by", []):
                R.setdefault("seen_by", []).append(uid)
                save_db(DB)
            bot.answer_callback_query(c.id)
            show_receipt_card(c.message.chat.id, rid, admin_view=True)
            return

        if data.startswith("receipt:approve:"):
            _, _, rid = data.split(":")
            bot.answer_callback_query(c.id)
            admin_approve_receipt(uid, rid, chat_id=c.message.chat.id)
            return

        if data.startswith("receipt:reject:"):
            _, _, rid = data.split(":")
            st = user_state(uid)
            st["await_reject_reason"] = {"rid": rid}
            save_db(DB)
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id, DB["texts"]["enter_reject_reason"], reply_markup=kb_cancel())
            return

        if data == "admin:plans":
            bot.answer_callback_query(c.id)
            admin_show_plans(c.message.chat.id, uid)
            return

        if data == "admin:coupons":
            bot.answer_callback_query(c.id)
            admin_show_coupons(c.message.chat.id, uid)
            return

        if data == "admin:wallet":
            bot.answer_callback_query(c.id)
            admin_wallet_menu(c.message.chat.id, uid)
            return

        if data == "admin:users":
            bot.answer_callback_query(c.id)
            admin_users_menu(c.message.chat.id, uid)
            return

        if data == "admin:broadcast":
            bot.answer_callback_query(c.id)
            admin_broadcast_menu(c.message.chat.id, uid)
            return

        if data == "admin:texts":
            bot.answer_callback_query(c.id)
            admin_texts_menu(c.message.chat.id, uid)
            return

        if data == "admin:admins":
            bot.answer_callback_query(c.id)
            admin_admins_menu(c.message.chat.id, uid)
            return

        if data == "admin:cardnumber":
            bot.answer_callback_query(c.id)
            st = user_state(uid)
            st["await_admin_card_number"] = True
            save_db(DB)
            bot.send_message(c.message.chat.id, DB["texts"]["admin_enter_card_number"], reply_markup=kb_cancel())
            return

        if data == "admin:toggle_buttons":
            bot.answer_callback_query(c.id)
            admin_toggle_buttons_menu(c.message.chat.id, uid)
            return

        if data.startswith("togglebtn:"):
            _, key = data.split(":")
            cur = DB["buttons_active"].get(key, True)
            DB["buttons_active"][key] = not cur
            save_db(DB)
            bot.answer_callback_query(c.id, "ذخیره شد.")
            admin_toggle_buttons_menu(c.message.chat.id, uid)
            return

        # مدیریت ادمین‌ها
        if data.startswith("adm:add:"):
            _, _, id_str = data.split(":")
            try:
                aid = int(id_str)
            except:
                bot.answer_callback_query(c.id, "آیدی نامعتبر.")
                return
            if aid not in DB["admins"]:
                DB["admins"].append(aid)
                save_db(DB)
            bot.answer_callback_query(c.id, "افزوده شد.")
            admin_admins_menu(c.message.chat.id, uid)
            return

        if data.startswith("adm:del:"):
            _, _, id_str = data.split(":")
            try:
                aid = int(id_str)
            except:
                bot.answer_callback_query(c.id, "آیدی نامعتبر.")
                return
            if aid in DB["admins"] and aid != uid:  # خودش را نتواند حذف کند
                DB["admins"].remove(aid)
                save_db(DB)
            bot.answer_callback_query(c.id, "حذف شد.")
            admin_admins_menu(c.message.chat.id, uid)
            return

    except Exception as e:
        log.exception("Callback error: %s", e)
        bot.answer_callback_query(c.id, "خطا رخ داد.")

# --------------- تصاویر/فایل‌ها (برای رسید) ---------------
@bot.message_handler(content_types=["photo","document"])
def on_media(m):
    uid = m.from_user.id
    uname = m.from_user.username or ""
    ensure_user(uid, uname)
    st = user_state(uid)

    if st.get("await_receipt"):
        kind = st["await_receipt"]["kind"]  # wallet_charge | purchase
        file_id = None
        if m.content_type == "photo":
            file_id = m.photo[-1].file_id
        elif m.content_type == "document":
            file_id = m.document.file_id

        note = ""
        related = {}

        if kind == "wallet_charge":
            amount = st["await_receipt"].get("force_amount")
            if not amount:
                # اگر مبلغ اجباری نبود، از کاربر می‌خوایم یه توضیح کوچیک بده با عدد
                amount = 0
            related = {"amount": int(amount or 0)}
            create_receipt(uid, "wallet_charge", note=note, file_id=file_id, related=related)
            bot.reply_to(m, DB["texts"]["wallet_receipt_registered"], reply_markup=main_menu(uid))
            clear_state(uid)
            return

        else:
            # خرید پلن
            pid = st["await_receipt"]["plan_id"]
            final = st["await_receipt"]["expected"]
            coupon = st["await_receipt"].get("coupon")
            related = {"plan_id": pid, "amount": int(final), "coupon": coupon}
            create_receipt(uid, "purchase", note=note, file_id=file_id, related=related)
            bot.reply_to(m, DB["texts"]["receipt_sent_for_purchase"], reply_markup=main_menu(uid))
            clear_state(uid)
            return

    # اگر رسید نبود، برگرد به منو
    send_home(m.chat.id, uid, uname)

# --------------- پنل ادمین‌ها ---------------
def show_admin(chat_id, uid):
    if not is_admin(uid):
        bot.send_message(chat_id, "شما ادمین نیستید.")
        return
    t = DB["texts"]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(t["btn_admin_receipts"], callback_data="admin:receipts"))
    kb.add(InlineKeyboardButton(t["btn_admin_plans"], callback_data="admin:plans"))
    kb.add(InlineKeyboardButton(t["btn_admin_coupons"], callback_data="admin:coupons"))
    kb.add(InlineKeyboardButton(t["btn_admin_wallet"], callback_data="admin:wallet"))
    kb.add(InlineKeyboardButton(t["btn_admin_users"], callback_data="admin:users"))
    kb.add(InlineKeyboardButton(t["btn_admin_broadcast"], callback_data="admin:broadcast"))
    kb.add(InlineKeyboardButton(t["btn_admin_texts"], callback_data="admin:texts"))
    kb.add(InlineKeyboardButton(t["btn_admin_admins"], callback_data="admin:admins"))
    kb.add(InlineKeyboardButton(t["btn_admin_card_number"], callback_data="admin:cardnumber"))
    kb.add(InlineKeyboardButton("⚙️ فعال/غیرفعال کردن دکمه‌ها", callback_data="admin:toggle_buttons"))
    kb.add(InlineKeyboardButton(DB["texts"]["admin_back_user"], callback_data="admin:home"))
    bot.send_message(chat_id, DB["texts"]["admin_title"], reply_markup=kb)

def admin_toggle_buttons_menu(chat_id, uid):
    ba = DB["buttons_active"]
    labels = {
        "buy_plan": "📦 خرید پلن",
        "wallet": "🪙 کیف پول",
        "tickets": "🎫 تیکت پشتیبانی",
        "account": "👤 حساب کاربری",
        "admin": "🛠 پنل ادمین",
    }
    kb = InlineKeyboardMarkup()
    for key, lbl in labels.items():
        st = "✅" if ba.get(key, True) else "❌"
        kb.add(InlineKeyboardButton(f"{st} {lbl}", callback_data=f"togglebtn:{key}"))
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "دکمه‌ها:", reply_markup=kb)

def admin_admins_menu(chat_id, uid):
    lines = ["👑 مدیریت ادمین‌ها:", ""]
    for a in DB["admins"]:
        lines.append(f"- <code>{a}</code> {'(شما)' if a==uid else ''}")
    kb = InlineKeyboardMarkup()
    # برای اضافه‌کردن/حذف‌کردن، ادمین باید آیدی را به‌صورت متن بفرستد؟ اینجا برای راحتی 2 نمونه نمایشی می‌ذاریم:
    lines.append("\nبرای افزودن/حذف: آیدی را به‌صورت زیر با این باتن‌ها بساز:\n")
    lines.append("افزودن: adm:add:<ID>\nحذف: adm:del:<ID>\n(فعلاً سریع‌ترین راه دکمه‌ای با CallbackData است)")
    # برای کمک سریع: دکمه‌های نمونه (تو می‌تونی بعداً تغییر بدی)
    sample_add = uid  # نمونه
    kb.add(InlineKeyboardButton("➕ افزودن نمونه", callback_data=f"adm:add:{sample_add}"))
    if len(DB["admins"]) > 1:
        for a in DB["admins"]:
            if a != uid:
                kb.add(InlineKeyboardButton(f"➖ حذف {a}", callback_data=f"adm:del:{a}"))
                break
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)

# --- مدیریت پلن‌ها و مخزن (حداقلیِ کامل) ---
def admin_show_plans(chat_id, uid):
    lines = ["📦 مدیریت پلن‌ها و مخزن:"]
    if not DB["plans"]:
        lines.append("هیچ پلنی ثبت نشده است.")
    else:
        for pid, p in DB["plans"].items():
            stock = len(DB["inventory"].get(pid, []))
            lines.append(f"• {p['name']} | قیمت: {fmt_price(p['price'])} | روز: {p['days']} | حجم: {p['gb']} | موجودی مخزن: {stock}")
    lines.append("\nبرای افزودن سریع پلن نمونه استفاده کن:")
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ افزودن پلن نمونه", callback_data="planadmin:addsample"))
    # مدیریت مخزن سریع برای اولین پلن
    if DB["plans"]:
        first_pid = list(DB["plans"].keys())[0]
        kb.add(InlineKeyboardButton("➕ افزودن کانفیگ نمونه به اولین پلن", callback_data=f"inv:addsample:{first_pid}"))
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["planadmin:addsample"])
def add_sample_plan_cb(c):
    pid = str(uuid.uuid4())[:8]
    DB["plans"][pid] = {
        "id": pid,
        "name": "پلن پایه",
        "days": 30,
        "gb": 100,
        "price": 150000,
        "desc": "پلن نمونه جهت تست."
    }
    DB["inventory"][pid] = []
    save_db(DB)
    bot.answer_callback_query(c.id, "پلن نمونه افزوده شد.")
    admin_show_plans(c.message.chat.id, c.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("inv:addsample:"))
def add_sample_inv_cb(c):
    _, _, pid = c.data.split(":")
    if pid not in DB["plans"]:
        bot.answer_callback_query(c.id, "پلن یافت نشد.")
        return
    DB["inventory"].setdefault(pid, []).append({
        "text": "این یک کانفیگ نمونه است.\nvmess://example...",
        "image": None
    })
    save_db(DB)
    bot.answer_callback_query(c.id, "کانفیگ نمونه افزوده شد.")
    admin_show_plans(c.message.chat.id, c.from_user.id)

# --- مدیریت کد تخفیف (حداقلیِ کامل) ---
def admin_show_coupons(chat_id, uid):
    lines = ["🏷 مدیریت کد تخفیف:"]
    if not DB["coupons"]:
        lines.append("هیچ کدی ثبت نشده است.")
    else:
        for code, cc in DB["coupons"].items():
            st = "فعال" if cc.get("active", True) else "غیرفعال"
            target = cc.get("plan_id") or "همه پلن‌ها"
            lines.append(f"• {code} | {cc['percent']}٪ | هدف: {target} | {st}")
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ ساخت کد نمونه", callback_data="coupon:addsample"))
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "coupon:addsample")
def coupon_add_sample(c):
    DB["coupons"]["OFF10"] = {
        "code": "OFF10",
        "percent": 10,
        "plan_id": None,  # None یعنی همه پلن‌ها
        "active": True,
        "limit": 100,
        "used": 0,
        "expire": None
    }
    save_db(DB)
    bot.answer_callback_query(c.id, "کد تخفیف نمونه ساخته شد.")
    admin_show_coupons(c.message.chat.id, c.from_user.id)

# --- کیف پول ادمین ---
def admin_wallet_menu(chat_id, uid):
    lines = ["🪙 کیف پول (ادمین)", "— تأیید/رد رسیدها از بخش رسیدها انجام می‌شود.", "— همچنین می‌توانی شارژ/کسر دستی انجام دهی."]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ شارژ دستی نمونه کاربر", callback_data="aw:add:sample"))
    kb.add(InlineKeyboardButton("➖ کسر دستی نمونه کاربر", callback_data="aw:sub:sample"))
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["aw:add:sample","aw:sub:sample"])
def admin_wallet_ops(c):
    # نمونه: روی خود ادمین اعمال می‌کنیم
    uid = c.from_user.id
    if c.data == "aw:add:sample":
        DB["users"][str(uid)]["wallet"] += 50000
        save_db(DB)
        bot.answer_callback_query(c.id, "۵۰هزار تومان شارژ شد.")
    else:
        DB["users"][str(uid)]["wallet"] = max(0, DB["users"][str(uid)]["wallet"] - 20000)
        save_db(DB)
        bot.answer_callback_query(c.id, "۲۰هزار تومان کسر شد.")
    admin_wallet_menu(c.message.chat.id, uid)

# --- کاربران ---
def admin_users_menu(chat_id, uid):
    lines = ["👥 مدیریت کاربران", f"تعداد کاربران: {len(DB['users'])}"]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)

# --- اعلان همگانی (ساده) ---
def admin_broadcast_menu(chat_id, uid):
    lines = [
        "📢 اعلان همگانی (نسخه ساده)",
        "برای ارسال پیام همگانی، همینجا پیام را فوروارد/تایپ و به من ریپلای کن با کلمه ‘ارسال’—(در نسخه حاضر برای سادگی غیرفعاله)."
    ]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)

# --- متون و دکمه‌ها ---
def admin_texts_menu(chat_id, uid):
    lines = ["🧩 مدیریت دکمه‌ها و متون",
             "در این نسخه، برخی کلیدواژه‌ها از پیش تعریف شده‌اند. برای ویرایش، می‌تونی مستقیم از JSON (DB) هم تغییر بدی.",
             "— در آپدیت بعدی می‌تونیم برای هر کلید یک فرم ادیت هم دکمه‌ای کنیم."]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(DB["texts"]["btn_back"], callback_data="admin:home"))
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb)

# --------------- پردازش رسید مستقیم برای خرید (ثبت رسید) ---------------
@bot.callback_query_handler(func=lambda c: c.data == "submit:purchase:receipt")
def submit_purchase_receipt(c):
    uid = c.from_user.id
    st = user_state(uid)
    if not st.get("await_receipt") or st["await_receipt"].get("kind") != "purchase":
        bot.answer_callback_query(c.id, "فعلاً سناریوی خرید فعال نیست.")
        return
    bot.answer_callback_query(c.id, "لطفاً تصویر/فایل رسید را ارسال کنید.")

# --------------- ادمین: رسیدها (گزارش) ---------------
@bot.message_handler(commands=["_debug_dump_db"])
def _debug(m):
    if not is_admin(m.from_user.id):
        return
    bot.reply_to(m, f"<code>{json.dumps(DB, ensure_ascii=False)[:3500]}</code>")

# --------------- ورودی‌های دیگر ---------------
@bot.message_handler(func=lambda m: True, content_types=["sticker","voice","video","audio","location","contact"])
def on_misc(m):
    # اگر در سناریوی رسید هست، باید فایل/عکس بفرستد
    uid = m.from_user.id
    uname = m.from_user.username or ""
    ensure_user(uid, uname)
    st = user_state(uid)
    if st.get("await_receipt"):
        bot.reply_to(m, "لطفاً تصویر یا فایل رسید را ارسال کنید.")
        return
    send_home(m.chat.id, uid, uname)

# --------------- نمایش پلن/کوپن و … به صورت lazy-notify انقضا (ساده) ---------------
def lazy_expiry_pinger(uid):
    """به شکل ساده: هر بار یوزر پیام می‌دهد، اگر سفارشی 3 روز مانده بود یادآور بده."""
    today = datetime.utcnow().date()
    for o in DB["users"][str(uid)].get("orders", []):
        try:
            exp = datetime.strptime(o["expire"], "%Y-%m-%d").date()
            if 0 <= (exp - today).days <= 3:
                bot.send_message(uid, f"⏰ یادآور: پلن «{o['plan_name']}» تا {o['expire']} معتبر است. برای تمدید اقدام کنید.")
        except:
            pass

# --------------- رویداد ورودی برای همه پیام‌های متنی جهت پینگ انقضا ---------------
@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text_second_pass(m):
    # این هندلر دوم به خاطر تقدم/تأخر اجرا نمیشه
    # پس فقط به‌عنوان یادگاری نگه می‌داریم اگر لازم شد بعداً سوییچ کنیم.
    pass

# --------------- اجرا در گونی‌کورْن ---------------
if __name__ == "__main__":
    # برای تست لوکال: می‌تونی از polling استفاده کنی (یادت باشه وبهوک رو حذف کنی)
    # bot.remove_webhook()
    # bot.infinity_polling()
    app.run(host="0.0.0.0", port=8000)
