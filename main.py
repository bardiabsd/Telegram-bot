# -*- coding: utf-8 -*-
import os
import json
import time
import re
from datetime import datetime, timedelta

from flask import Flask, request, abort
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto
)

# ---------------------------
# تنظیمات اولیه
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo")
APP_URL   = os.getenv("APP_URL", "https://live-avivah-bardiabsd-cd8d676a.koyeb.app").rstrip("/")

# وبهوک: روی همین مسیر ست می‌کنیم (پترن توی Koyeb رو قبلا استفاده کرده بودیم)
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{APP_URL}{WEBHOOK_PATH}"

# ادمین پیش‌فرض (قابل مدیریت از داخل ربات)
DEFAULT_ADMIN_ID = 1743359080

# فایل پایدار‌سازی
DB_FILE = "db.json"

# ---------------------------
# کمک‌تابع‌های فایل دیتابیس
# ---------------------------
def _now_iso():
    return datetime.utcnow().isoformat()

def db_load():
    if not os.path.exists(DB_FILE):
        # مقداردهی اولیه
        data = {
            "admins": [DEFAULT_ADMIN_ID],
            "users": {},  # user_id -> {"username": "...", "wallet": 0, "stats": {...}}
            "plans": {},  # plan_id -> {...}
            "inventory": {},  # plan_id -> [ {text, image_url} , ... ]
            "coupons": {},  # code -> {percent, plan_id|None, uses, max_uses, expire_at}
            "receipts": {},  # receipt_id -> {...}
            "orders": {},    # order_id -> {...} (history)
            "tickets": {},   # ticket_id -> {...}
            "texts": {       # متن‌ها/برچسب‌ها (ادمین می‌تواند تغییر دهد)
                "welcome": (
                    "سلام! 👋\n"
                    "خوش اومدی به ربات فروش کانفیگ.\n"
                    "از منوی زیر یکی از گزینه‌ها رو انتخاب کن."
                ),
                "card_number": "6037-7777-7777-7777",  # توسط ادمین قابل ویرایش
                "cancel": "انصراف",
                "back": "بازگشت",
            },
            "toggles": {     # روشن/خاموش دکمه‌ها
                "buy": True,
                "wallet": True,
                "tickets": True,
                "my_account": True,
                "admin_panel": True
            },
            "states": {},    # user_id -> state dict
            "counters": {    # برای آیدی‌های خودکار
                "receipt": 1000,
                "order": 2000,
                "ticket": 3000,
                "plan": 4000
            },
            "logs": []
        }
        db_save(data)
        return data
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def db_save(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_event(kind, payload):
    data = db_load()
    data["logs"].append({"t": _now_iso(), "kind": kind, "data": payload})
    # برای جلوگیری از بزرگ شدن بی‌نهایت
    if len(data["logs"]) > 2000:
        data["logs"] = data["logs"][-1000:]
    db_save(data)

# ---------------------------
# مدیریت State (برای ورودی متنی)
# ---------------------------
def get_state(uid):
    data = db_load()
    return data["states"].get(str(uid), {})

def set_state(uid, **kwargs):
    data = db_load()
    st = data["states"].get(str(uid), {})
    st.update(kwargs)
    data["states"][str(uid)] = st
    db_save(data)

def clear_state(uid):
    data = db_load()
    if str(uid) in data["states"]:
        del data["states"][str(uid)]
        db_save(data)

def expecting(uid):
    """برمی‌گرداند در چه مرحله‌ای ورودی متنی انتظار داریم. ندارد => None"""
    st = get_state(uid)
    return st.get("await")  # کلید را await نمی‌گذاریم که کلمه رزرو نباشد! اما اینجا رشته است OK

# ---------------------------
# کمک‌تابع‌ها
# ---------------------------
def is_admin(user_id):
    data = db_load()
    return int(user_id) in data.get("admins", [])

def ensure_user(user):
    """ثبت اولیه کاربر در DB"""
    data = db_load()
    uid = str(user.id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "username": user.username or "",
            "wallet": 0,
            "stats": {"purchases": 0, "spent": 0},
            "joined_at": _now_iso()
        }
        db_save(data)
    else:
        # آپدیت یوزرنیم اگر عوض شد
        if (user.username or "") != data["users"][uid].get("username", ""):
            data["users"][uid]["username"] = user.username or ""
            db_save(data)

def fmt_money(x):
    try:
        n = int(x)
    except:
        return str(x)
    return f"{n:,}".replace(",", "،")

def next_id(counter_key):
    data = db_load()
    data["counters"][counter_key] += 1
    val = data["counters"][counter_key]
    db_save(data)
    return val

def plan_btn_title(p):
    inv_count = len(db_load()["inventory"].get(str(p["id"]), []))
    return f"{p['name']} | {fmt_money(p['price'])} تومان | موجودی: {inv_count}"

def coupon_valid_for(code, plan_id):
    data = db_load()
    c = data["coupons"].get(code)
    if not c:
        return False, "کد تخفیف معتبر نیست."
    # اعتبار زمانی
    if c.get("expire_at"):
        try:
            if datetime.utcnow() > datetime.fromisoformat(c["expire_at"]):
                return False, "کد منقضی شده است."
        except:
            pass
    # ظرفیت استفاده
    if c.get("max_uses") is not None and c.get("uses", 0) >= c["max_uses"]:
        return False, "سقف استفاده این کد تکمیل شده."
    # محدود به پلن خاص؟
    pid = c.get("plan_id")
    if pid and str(pid) != str(plan_id):
        return False, "این کد برای این پلن معتبر نیست."
    return True, ""

def apply_coupon_amount(price, code):
    data = db_load()
    c = data["coupons"].get(code)
    if not c:
        return price, 0
    percent = max(0, min(100, int(c.get("percent", 0))))
    discount = (price * percent) // 100
    return max(0, price - discount), discount

def inc_coupon_use(code):
    data = db_load()
    if code in data["coupons"]:
        data["coupons"][code]["uses"] = data["coupons"][code].get("uses", 0) + 1
        db_save(data)

# ---------------------------
# ساخت منوهای کاربر و ادمین
# ---------------------------
def main_menu(uid):
    data = db_load()
    tgl = data["toggles"]
    kb = InlineKeyboardMarkup(row_width=2)
    rows = []
    if tgl.get("buy", True):
        rows.append(InlineKeyboardButton("📦 خرید پلن", callback_data="buy"))
    if tgl.get("wallet", True):
        rows.append(InlineKeyboardButton("🪙 کیف پول", callback_data="wallet"))
    if tgl.get("tickets", True):
        rows.append(InlineKeyboardButton("🎫 تیکت پشتیبانی", callback_data="tickets"))
    if tgl.get("my_account", True):
        rows.append(InlineKeyboardButton("👤 حساب کاربری", callback_data="myacc"))
    if is_admin(uid) and tgl.get("admin_panel", True):
        rows.append(InlineKeyboardButton("🛠 پنل ادمین", callback_data="admin"))
    # چینش 2تایی
    kb.add(*rows)
    return kb

def back_cancel_kb():
    data = db_load()
    return InlineKeyboardMarkup().row(
        InlineKeyboardButton(f"⬅️ {data['texts']['back']}", callback_data="back"),
        InlineKeyboardButton(f"✖️ {data['texts']['cancel']}", callback_data="cancel")
    )

def wallet_menu():
    data = db_load()
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_charge"))
    kb.row(InlineKeyboardButton("📜 تاریخچه تراکنش‌ها", callback_data="wallet_tx"))
    kb.row(
        InlineKeyboardButton(f"✖️ {data['texts']['cancel']}", callback_data="cancel")
    )
    return kb

def buy_menu():
    data = db_load()
    kb = InlineKeyboardMarkup()
    # لیست پلن‌ها
    plans = list(data["plans"].values())
    plans.sort(key=lambda x: x["id"])
    for p in plans:
        inv = data["inventory"].get(str(p["id"]), [])
        if len(inv) == 0:
            # پلن بدون موجودی: غیرفعال
            title = plan_btn_title(p) + " (ناموجود)"
            kb.row(InlineKeyboardButton(title, callback_data="noop"))
        else:
            kb.row(InlineKeyboardButton(plan_btn_title(p), callback_data=f"buy_plan:{p['id']}"))
    kb.row(InlineKeyboardButton("🏷 اعمال کد تخفیف", callback_data="coupon_apply"))
    kb.row(InlineKeyboardButton("✖️ انصراف", callback_data="cancel"))
    return kb

def payment_menu(final_amount):
    data = db_load()
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(f"🪙 پرداخت از کیف پول ({fmt_money(final_amount)} تومان)", callback_data="pay_wallet"))
    kb.row(InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data="pay_card"))
    kb.row(InlineKeyboardButton(f"✖️ {data['texts']['cancel']}", callback_data="cancel"))
    return kb

def tickets_menu():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📝 ایجاد تیکت جدید", callback_data="tkt_new"))
    kb.row(InlineKeyboardButton("📂 تیکت‌های من", callback_data="tkt_my"))
    kb.row(InlineKeyboardButton("✖️ انصراف", callback_data="cancel"))
    return kb

def admin_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👑 مدیریت ادمین‌ها", callback_data="adm_admins"),
        InlineKeyboardButton("📦 مدیریت پلن‌ها/مخزن", callback_data="adm_plans"),
        InlineKeyboardButton("🏷 کدهای تخفیف", callback_data="adm_coupons"),
        InlineKeyboardButton("🪙 کیف پول (ادمین)", callback_data="adm_wallet"),
        InlineKeyboardButton("👥 کاربران", callback_data="adm_users"),
        InlineKeyboardButton("🧩 دکمه‌ها و متون", callback_data="adm_texts"),
        InlineKeyboardButton("📢 اعلان همگانی", callback_data="adm_broadcast"),
        InlineKeyboardButton("📊 آمار فروش", callback_data="adm_stats"),
        InlineKeyboardButton("🧾 رسیدها/سفارش‌ها", callback_data="adm_receipts")
    )
    kb.row(InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="back"))
    return kb

def admins_menu():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm_admin_add"))
    kb.row(InlineKeyboardButton("➖ حذف ادمین", callback_data="adm_admin_del"))
    kb.row(InlineKeyboardButton("📋 فهرست ادمین‌ها", callback_data="adm_admin_list"))
    kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="admin"))
    return kb

def plans_menu():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➕ افزودن پلن", callback_data="plan_add"))
    kb.row(InlineKeyboardButton("✏️ ویرایش پلن", callback_data="plan_edit"))
    kb.row(InlineKeyboardButton("🗑 حذف پلن", callback_data="plan_del"))
    kb.row(InlineKeyboardButton("📥 مدیریت مخزن پلن", callback_data="inv_manage"))
    kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="admin"))
    return kb

def coupons_menu():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➕ ساخت کد تخفیف", callback_data="coupon_new"))
    kb.row(InlineKeyboardButton("✏️ ویرایش کد", callback_data="coupon_edit"))
    kb.row(InlineKeyboardButton("🗑 حذف کد", callback_data="coupon_del"))
    kb.row(InlineKeyboardButton("📋 لیست کدها", callback_data="coupon_list"))
    kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="admin"))
    return kb

def wallet_admin_menu():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📥 رسیدهای شارژ در انتظار", callback_data="adm_wallet_inbox"))
    kb.row(InlineKeyboardButton("➕ شارژ دستی کاربر", callback_data="adm_wallet_add"))
    kb.row(InlineKeyboardButton("➖ کسر دستی کاربر", callback_data="adm_wallet_sub"))
    kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="admin"))
    return kb

def users_menu():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("🔎 جستجوی کاربر", callback_data="users_search"))
    kb.row(InlineKeyboardButton("📋 لیست کاربران", callback_data="users_list"))
    kb.row(InlineKeyboardButton("🚫 بن/آنبن کاربر", callback_data="users_ban"))
    kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="admin"))
    return kb

def texts_menu():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("✏️ ویرایش متن خوش‌آمدگویی", callback_data="txt_welcome"))
    kb.row(InlineKeyboardButton("✏️ ویرایش شماره کارت", callback_data="txt_card"))
    kb.row(InlineKeyboardButton("🟢/🔴 روشن/خاموش دکمه‌ها", callback_data="txt_toggles"))
    kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="admin"))
    return kb

def toggles_menu():
    data = db_load()
    t = data["toggles"]
    kb = InlineKeyboardMarkup(row_width=2)
    def badge(x): return "🟢" if t.get(x, True) else "🔴"
    kb.add(
        InlineKeyboardButton(f"{badge('buy')} خرید پلن", callback_data="tgl:buy"),
        InlineKeyboardButton(f"{badge('wallet')} کیف پول", callback_data="tgl:wallet"),
        InlineKeyboardButton(f"{badge('tickets')} تیکت‌ها", callback_data="tgl:tickets"),
        InlineKeyboardButton(f"{badge('my_account')} حساب کاربری", callback_data="tgl:my_account"),
        InlineKeyboardButton(f"{badge('admin_panel')} پنل ادمین", callback_data="tgl:admin_panel"),
    )
    kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="adm_texts"))
    return kb

# ---------------------------
# Bot و Flask
# ---------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, num_threads=1)
app = Flask(__name__)

def set_webhook_once():
    """ست کردن وبهوک با هندل ارور 429 (Too Many Requests)"""
    try:
        bot.remove_webhook()
    except Exception as e:
        pass
    time.sleep(0.3)
    for _ in range(3):
        try:
            bot.set_webhook(url=WEBHOOK_URL)
            print(f"{_now_iso()} | INFO | Webhook set to: {WEBHOOK_URL}")
            return
        except telebot.apihelper.ApiTelegramException as e:
            if "Too Many Requests" in str(e):
                time.sleep(1.2)
                continue
            else:
                print(f"{_now_iso()} | ERROR | Failed to set webhook: {e}")
                break
        except Exception as e:
            print(f"{_now_iso()} | ERROR | Failed to set webhook: {e}")
            break

set_webhook_once()

@app.route("/")
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

# ---------------------------
# استارت و منوی اصلی
# ---------------------------
@bot.message_handler(commands=["start"])
def cmd_start(m):
    ensure_user(m.from_user)
    clear_state(m.from_user.id)
    # پیام خوش‌آمد + منوی اصلی
    data = db_load()
    bot.send_message(
        m.chat.id,
        data["texts"]["welcome"],
        reply_markup=main_menu(m.from_user.id)
    )

# ---------------------------
# هندل کلیک‌های دکمه‌ای
# ---------------------------
@bot.callback_query_handler(func=lambda c: True)
def on_cb(c):
    uid = c.from_user.id
    ensure_user(c.from_user)
    data = db_load()
    cd = c.data or ""

    # ناوبری عمومی
    if cd == "back":
        clear_state(uid)
        bot.edit_message_text(
            data["texts"]["welcome"],
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=main_menu(uid)
        )
        return
    if cd == "cancel":
        clear_state(uid)
        bot.answer_callback_query(c.id, "لغو شد.")
        bot.edit_message_text(
            "لغو شد ✅",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=main_menu(uid)
        )
        return

    # منوهای کاربر
    if cd == "buy":
        clear_state(uid)
        bot.edit_message_text(
            "یکی از پلن‌ها را انتخاب کنید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=buy_menu()
        )
        return

    if cd.startswith("buy_plan:"):
        # انتخاب پلن
        pid = cd.split(":",1)[1]
        p = data["plans"].get(str(pid))
        if not p:
            bot.answer_callback_query(c.id, "پلن پیدا نشد.")
            return
        # اعمال کد تخفیف (اگر در state باشد)
        st = get_state(uid)
        code = st.get("coupon_code")
        price = int(p["price"])
        final_price = price
        discount = 0
        if code:
            ok, msg = coupon_valid_for(code, pid)
            if ok:
                final_price, discount = apply_coupon_amount(price, code)
            else:
                # کد نامعتبر؛ پاک می‌کنیم
                st.pop("coupon_code", None)
                set_state(uid, **st)
        # ذخیره سفارش در state تا پرداخت
        set_state(uid, flow="buy", plan_id=pid, final_amount=final_price)
        msg = f"پلن انتخابی: {p['name']}\n" \
              f"قیمت: {fmt_money(price)} تومان\n"
        if discount:
            msg += f"تخفیف: {fmt_money(discount)} تومان\n"
        msg += f"مبلغ نهایی: {fmt_money(final_price)} تومان\n\n" \
               "روش پرداخت را انتخاب کنید:"
        bot.edit_message_text(
            msg,
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=payment_menu(final_price)
        )
        return

    if cd == "coupon_apply":
        # درخواست کد تخفیف
        set_state(uid, flow="buy", await="coupon_code")
        bot.edit_message_text(
            "کد تخفیف را بفرستید (یا «انصراف»):",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "pay_wallet":
        st = get_state(uid)
        pid = st.get("plan_id")
        final_amount = int(st.get("final_amount", 0))
        inv = data["inventory"].get(str(pid), [])
        if not inv:
            bot.answer_callback_query(c.id, "موجودی این پلن خالی است.")
            return
        # چک موجودی کیف پول
        user = data["users"][str(uid)]
        if user["wallet"] >= final_amount:
            # پرداخت از کیف پول
            user["wallet"] -= final_amount
            data["users"][str(uid)] = user
            # ارسال کانفیگ
            cfg = inv.pop(0)
            data["inventory"][str(pid)] = inv
            # ثبت سفارش
            oid = next_id("order")
            data["orders"][str(oid)] = {
                "id": oid,
                "user_id": uid,
                "plan_id": int(pid),
                "amount": final_amount,
                "paid_via": "wallet",
                "at": _now_iso()
            }
            # آپدیت آمار
            data["users"][str(uid)]["stats"]["purchases"] += 1
            data["users"][str(uid)]["stats"]["spent"] += final_amount
            db_save(data)
            clear_state(uid)
            # ارسال کانفیگ (متن + تصویر در صورت وجود)
            txt = cfg.get("text", "—")
            img = cfg.get("image_url")
            if img:
                bot.send_photo(c.message.chat.id, img, caption=f"کانفیگ شما:\n{txt}")
            else:
                bot.send_message(c.message.chat.id, f"کانفیگ شما:\n{txt}")
            bot.edit_message_text(
                "پرداخت با موفقیت انجام شد ✅",
                chat_id=c.message.chat.id,
                message_id=c.message.message_id,
                reply_markup=main_menu(uid)
            )
        else:
            # موجودی ناکافی => نمایش مابه‌التفاوت + دکمه‌ی شارژ همین مقدار
            need = final_amount - user["wallet"]
            set_state(uid, flow="buy", await=None, need_topup=need)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(f"➕ شارژ {fmt_money(need)} تومان", callback_data="wallet_charge_need"))
            kb.row(InlineKeyboardButton("✖️ انصراف", callback_data="cancel"))
            bot.edit_message_text(
                f"موجودی کیف پول کافی نیست.\n"
                f"مبلغ موردنیاز: {fmt_money(need)} تومان",
                chat_id=c.message.chat.id,
                message_id=c.message.message_id,
                reply_markup=kb
            )
        return

    if cd == "wallet_charge_need":
        st = get_state(uid)
        need = int(st.get("need_topup", 0))
        data = db_load()
        card = data["texts"]["card_number"]
        # ثبت درخواست رسید
        rid = next_id("receipt")
        data = db_load()  # ری لود برای کانتر
        data["receipts"][str(rid)] = {
            "id": rid,
            "user_id": uid,
            "username": db_load()["users"][str(uid)]["username"],
            "kind": "wallet_topup",
            "target": "buy_continue",
            "amount_expected": need,
            "status": "pending",
            "created_at": _now_iso()
        }
        db_save(data)
        clear_state(uid)
        bot.edit_message_text(
            f"لطفاً مبلغ {fmt_money(need)} تومان را به کارت زیر واریز کنید و رسید را ارسال کنید:\n\n"
            f"💳 {card}\n\n"
            "پس از ارسال رسید، منتظر تأیید ادمین بمانید.",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "pay_card":
        # نمایش شماره کارت و درخواست رسید
        card = data["texts"]["card_number"]
        st = get_state(uid)
        pid = st.get("plan_id")
        final_amount = int(st.get("final_amount", 0))
        rid = next_id("receipt")
        data = db_load()
        data["receipts"][str(rid)] = {
            "id": rid,
            "user_id": uid,
            "username": data["users"][str(uid)]["username"],
            "kind": "plan_purchase",
            "plan_id": int(pid),
            "amount_expected": final_amount,
            "status": "pending",
            "created_at": _now_iso()
        }
        db_save(data)
        clear_state(uid)
        bot.edit_message_text(
            f"لطفاً مبلغ {fmt_money(final_amount)} تومان را به کارت زیر واریز کنید و رسید را ارسال کنید:\n\n"
            f"💳 {card}\n\n"
            "پس از ارسال رسید، منتظر تأیید ادمین بمانید.",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "wallet":
        clear_state(uid)
        u = data["users"][str(uid)]
        bot.edit_message_text(
            f"موجودی شما: {fmt_money(u['wallet'])} تومان",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=wallet_menu()
        )
        return

    if cd == "wallet_charge":
        # کاربر می‌خواهد شارژ کند => فقط رسید بخواهد (مبلغ آزاد)
        set_state(uid, flow="wallet", await="wallet_receipt_ask_amount")
        bot.edit_message_text(
            "مبلغ شارژ (تومان) را بفرستید:\n"
            "مثال: 150000",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "wallet_tx":
        # نمایش تاریخچه تراکنش‌ها از orders + receipts تایید شده
        uid_s = str(uid)
        orders = [o for o in db_load()["orders"].values() if str(o["user_id"]) == uid_s]
        receipts = [r for r in db_load()["receipts"].values()
                    if str(r["user_id"]) == uid_s and r.get("status") == "approved"]
        msg = "📜 تاریخچه:\n"
        if not orders and not receipts:
            msg += "موردی یافت نشد."
        else:
            for r in sorted(receipts, key=lambda x: x["id"], reverse=True)[:10]:
                msg += f"✅ شارژ کیف پول: +{fmt_money(r.get('amount_set', r.get('amount_expected', 0)))} | #{r['id']}\n"
            for o in sorted(orders, key=lambda x: x["id"], reverse=True)[:10]:
                msg += f"🧾 خرید پلن #{o['plan_id']}: -{fmt_money(o['amount'])} | {o['paid_via']}\n"
        bot.edit_message_text(
            msg,
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=wallet_menu()
        )
        return

    if cd == "tickets":
        clear_state(uid)
        bot.edit_message_text(
            "بخش تیکت پشتیبانی:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=tickets_menu()
        )
        return

    if cd == "tkt_new":
        set_state(uid, flow="ticket", await="ticket_subject")
        bot.edit_message_text(
            "موضوع تیکت را بفرستید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "tkt_my":
        # لیست تیکت‌های کاربر
        ts = [t for t in db_load()["tickets"].values() if str(t["user_id"]) == str(uid)]
        if not ts:
            txt = "شما هیچ تیکتی ندارید."
        else:
            txt = "تیکت‌های شما:\n"
            for t in sorted(ts, key=lambda x: x["id"], reverse=True)[:10]:
                status = t.get("status", "open")
                txt += f"#{t['id']} | {t['subject']} | {status}\n"
        bot.edit_message_text(
            txt,
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=tickets_menu()
        )
        return

    # پنل ادمین
    if cd == "admin":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "دسترسی ندارید.")
            return
        clear_state(uid)
        bot.edit_message_text(
            "پنل ادمین:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=admin_menu()
        )
        return

    if cd == "adm_admins":
        if not is_admin(uid):
            bot.answer_callback_query(c.id, "دسترسی ندارید.")
            return
        clear_state(uid)
        bot.edit_message_text(
            "مدیریت ادمین‌ها:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=admins_menu()
        )
        return

    if cd == "adm_admin_add":
        if not is_admin(uid):
            return
        set_state(uid, flow="adm_admins", await="admin_add_id")
        bot.edit_message_text(
            "آیدی عددی یا یوزرنیم (با @) ادمین جدید را بفرستید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "adm_admin_del":
        if not is_admin(uid):
            return
        set_state(uid, flow="adm_admins", await="admin_del_id")
        bot.edit_message_text(
            "آیدی عددی یا یوزرنیم (با @) ادمین را بفرستید تا حذف شود:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "adm_admin_list":
        if not is_admin(uid):
            return
        admins = db_load()["admins"]
        msg = "فهرست ادمین‌ها:\n" + "\n".join([f"- {a}" for a in admins]) if admins else "لیست خالی است."
        bot.edit_message_text(
            msg,
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=admins_menu()
        )
        return

    if cd == "adm_plans":
        if not is_admin(uid):
            return
        clear_state(uid)
        bot.edit_message_text(
            "مدیریت پلن‌ها و مخزن:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=plans_menu()
        )
        return

    if cd == "plan_add":
        if not is_admin(uid):
            return
        set_state(uid, flow="plans", await="plan_add_name")
        bot.edit_message_text(
            "نام پلن جدید را بفرستید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "plan_edit":
        if not is_admin(uid):
            return
        # نمایش لیست پلن‌ها جهت انتخاب
        data = db_load()
        plans = list(data["plans"].values())
        plans.sort(key=lambda x: x["id"])
        if not plans:
            bot.answer_callback_query(c.id, "هیچ پلنی وجود ندارد.")
            return
        kb = InlineKeyboardMarkup()
        for p in plans:
            kb.row(InlineKeyboardButton(f"✏️ {p['id']} - {p['name']}", callback_data=f"plan_edit_id:{p['id']}"))
        kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="adm_plans"))
        bot.edit_message_text(
            "پلن موردنظر برای ویرایش را انتخاب کنید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=kb
        )
        return

    if cd.startswith("plan_edit_id:"):
        if not is_admin(uid):
            return
        pid = cd.split(":",1)[1]
        set_state(uid, flow="plans", await="plan_edit_field", edit_plan_id=pid)
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("نام", callback_data="pef:name"))
        kb.row(InlineKeyboardButton("مدت (روز)", callback_data="pef:days"))
        kb.row(InlineKeyboardButton("حجم (GB)", callback_data="pef:gb"))
        kb.row(InlineKeyboardButton("قیمت (تومان)", callback_data="pef:price"))
        kb.row(InlineKeyboardButton("توضیح", callback_data="pef:desc"))
        kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="adm_plans"))
        bot.edit_message_text(
            f"ویرایش پلن #{pid} — یک فیلد را انتخاب کنید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=kb
        )
        return

    if cd.startswith("pef:"):
        if not is_admin(uid):
            return
        field = cd.split(":",1)[1]
        st = get_state(uid)
        if not st.get("edit_plan_id"):
            bot.answer_callback_query(c.id, "پلن انتخاب نشده.")
            return
        set_state(uid, await=f"plan_edit_input:{field}")
        bot.edit_message_text(
            f"مقدار جدید برای «{field}» را بفرستید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "plan_del":
        if not is_admin(uid):
            return
        # لیست پلن‌ها برای حذف
        plans = list(db_load()["plans"].values())
        plans.sort(key=lambda x: x["id"])
        if not plans:
            bot.answer_callback_query(c.id, "هیچ پلنی وجود ندارد.")
            return
        kb = InlineKeyboardMarkup()
        for p in plans:
            kb.row(InlineKeyboardButton(f"🗑 {p['id']} - {p['name']}", callback_data=f"plan_del_id:{p['id']}"))
        kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="adm_plans"))
        bot.edit_message_text(
            "پلن مورد نظر برای حذف را انتخاب کنید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=kb
        )
        return

    if cd.startswith("plan_del_id:"):
        if not is_admin(uid):
            return
        pid = cd.split(":",1)[1]
        data = db_load()
        data["plans"].pop(str(pid), None)
        data["inventory"].pop(str(pid), None)
        db_save(data)
        bot.answer_callback_query(c.id, "پلن حذف شد.")
        bot.edit_message_text(
            "مدیریت پلن‌ها و مخزن:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=plans_menu()
        )
        return

    if cd == "inv_manage":
        if not is_admin(uid):
            return
        # انتخاب پلن برای مدیریت مخزن
        data = db_load()
        plans = list(data["plans"].values())
        plans.sort(key=lambda x: x["id"])
        if not plans:
            bot.answer_callback_query(c.id, "هیچ پلنی وجود ندارد.")
            return
        kb = InlineKeyboardMarkup()
        for p in plans:
            kb.row(InlineKeyboardButton(f"📥 مخزن پلن {p['id']} - {p['name']}", callback_data=f"inv_plan:{p['id']}"))
        kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="adm_plans"))
        bot.edit_message_text(
            "پلن موردنظر برای مدیریت مخزن را انتخاب کنید:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=kb
        )
        return

    if cd.startswith("inv_plan:"):
        if not is_admin(uid):
            return
        pid = cd.split(":",1)[1]
        set_state(uid, flow="inventory", plan_id=pid)
        kb = InlineKeyboardMarkup()
        kb.row(InlineKeyboardButton("➕ افزودن کانفیگ", callback_data="inv_add"))
        kb.row(InlineKeyboardButton("🗑 حذف یک کانفیگ", callback_data="inv_pop"))
        kb.row(InlineKeyboardButton("📊 موجودی مخزن", callback_data="inv_list"))
        kb.row(InlineKeyboardButton("↩️ بازگشت", callback_data="adm_plans"))
        bot.edit_message_text(
            f"مدیریت مخزن پلن #{pid}:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=kb
        )
        return

    if cd == "inv_add":
        if not is_admin(uid):
            return
        set_state(uid, await="inv_add_text")
        bot.edit_message_text(
            "متن کانفیگ را بفرستید (بعداً می‌توانید عکس هم بفرستید؛ فعلاً متن اجباری است):",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return

    if cd == "inv_pop":
        if not is_admin(uid):
            return
        st = get_state(uid)
        pid = st.get("plan_id")
        data = db_load()
        inv = data["inventory"].get(str(pid), [])
        if not inv:
            bot.answer_callback_query(c.id, "مخزن خالی است.")
            return
        inv.pop(0)
        data["inventory"][str(pid)] = inv
        db_save(data)
        bot.answer_callback_query(c.id, "یک کانفیگ حذف شد.")
        return

    if cd == "inv_list":
        if not is_admin(uid):
            return
        st = get_state(uid)
        pid = st.get("plan_id")
        inv = db_load()["inventory"].get(str(pid), [])
        bot.answer_callback_query(c.id, f"تعداد موجودی: {len(inv)}")
        return

    if cd == "adm_coupons":
        if not is_admin(uid):
            return
        clear_state(uid)
        bot.edit_message_text(
            "مدیریت کدهای تخفیف:",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=coupons_menu()
        )
        return

    if cd == "coupon_new":
        if not is_admin(uid):
            return
        # مرحله‌ای: درصد → محدود به پلن؟ → تاریخ انقضا → سقف استفاده → کد
        set_state(uid, flow="coupon", await="coupon_percent", coupon={})
        bot.edit_message_text(
            "درصد تخفیف را وارد کنید (0 تا 100):",
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            reply_markup=back_cancel_kb()
        )
        return# ادامه main.py

# -------------------------------
# مدیریت دکمه‌ها و متون
# -------------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "manage_buttons")
def manage_buttons(msg):
    uid = msg.from_user.id
    text = msg.text
    if text == "🔙 انصراف":
        clear_state(uid)
        return bot.send_message(uid, "به منوی اصلی برگشتی.", reply_markup=admin_panel())

    buttons = get_buttons()
    if text in buttons:
        set_state(uid, "edit_button_text", editing=text)
        return bot.send_message(uid, f"متن فعلی دکمه «{text}» 👇\n\nحالا متن جدید رو بفرست:", reply_markup=cancel_markup())
    else:
        return bot.send_message(uid, "از دکمه‌ها استفاده کنید.", reply_markup=buttons_markup(buttons))


@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "edit_button_text")
def edit_button_text(msg):
    uid = msg.from_user.id
    st = get_state(uid)
    if not st or "editing" not in st:
        return bot.send_message(uid, "خطا! لطفاً دوباره تلاش کنید.")
    new_text = msg.text.strip()
    old_text = st["editing"]
    update_button(old_text, new_text)
    clear_state(uid)
    bot.send_message(uid, f"✅ دکمه «{old_text}» به «{new_text}» تغییر کرد.", reply_markup=admin_panel())

# -------------------------------
# مدیریت ادمین‌ها
# -------------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "manage_admins")
def manage_admins(msg):
    uid = msg.from_user.id
    text = msg.text
    if text == "➕ افزودن ادمین":
        set_state(uid, "add_admin")
        return bot.send_message(uid, "آیدی عددی یا یوزرنیم فرد رو وارد کن:", reply_markup=cancel_markup())
    elif text.startswith("❌ حذف "):
        tid = text.replace("❌ حذف ", "").strip()
        remove_admin(tid)
        bot.send_message(uid, f"ادمین {tid} حذف شد ❌")
        try:
            bot.send_message(int(tid), "⚠️ شما از لیست ادمین‌ها حذف شدید.")
        except:
            pass
    elif text == "🔙 بازگشت":
        clear_state(uid)
        return bot.send_message(uid, "بازگشتی به منوی اصلی.", reply_markup=admin_panel())
    else:
        bot.send_message(uid, "از دکمه‌ها استفاده کنید.", reply_markup=admin_manage_markup())


@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "add_admin")
def add_admin_handler(msg):
    uid = msg.from_user.id
    tid = msg.text.strip()
    if tid.startswith("@"):
        tid = tid[1:]
    if not tid.isdigit():
        try:
            user = bot.get_chat(tid)
            tid = str(user.id)
        except:
            return bot.send_message(uid, "❌ آیدی یا یوزرنیم نامعتبره.", reply_markup=cancel_markup())

    add_admin(tid)
    clear_state(uid)
    bot.send_message(uid, f"✅ کاربر {tid} ادمین شد.", reply_markup=admin_panel())
    try:
        bot.send_message(int(tid), "🎉 شما به عنوان ادمین ربات انتخاب شدید.")
    except:
        pass

# -------------------------------
# ساخت کد تخفیف
# -------------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "create_coupon")
def create_coupon(msg):
    uid = msg.from_user.id
    val = msg.text.strip()
    if not val.isdigit():
        return bot.send_message(uid, "❌ درصد تخفیف باید عدد باشه.", reply_markup=cancel_markup())
    set_state(uid, "create_coupon_plan", coupon={"percent": int(val)})
    bot.send_message(uid, "🔑 حالا کد تخفیف رو بفرست:", reply_markup=cancel_markup())


@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "create_coupon_plan")
def create_coupon_plan(msg):
    uid = msg.from_user.id
    st = get_state(uid)
    if not st or "coupon" not in st:
        return bot.send_message(uid, "خطا!")
    code = msg.text.strip()
    percent = st["coupon"]["percent"]
    save_coupon(code, percent)
    clear_state(uid)
    bot.send_message(uid, f"✅ کد تخفیف {code} با {percent}% ساخته شد.", reply_markup=admin_panel())

# -------------------------------
# اعلان همگانی
# -------------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "broadcast")
def broadcast(msg):
    uid = msg.from_user.id
    text = msg.text
    users = get_all_users()
    count = 0
    for u in users:
        try:
            bot.send_message(u, text)
            count += 1
        except:
            pass
    clear_state(uid)
    bot.send_message(uid, f"📢 اعلان برای {count} کاربر ارسال شد.", reply_markup=admin_panel())

# -------------------------------
# تیکت‌ها
# -------------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "new_ticket")
def new_ticket(msg):
    uid = msg.from_user.id
    text = msg.text
    tid = save_ticket(uid, text)
    clear_state(uid)
    bot.send_message(uid, "🎫 تیکت شما ثبت شد. پشتیبانی به زودی پاسخ میده.", reply_markup=main_menu())
    notify_admins(f"📩 تیکت جدید #{tid} از کاربر {uid}\n\n{text}")

# -------------------------------
# آمار فروش
# -------------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "stats")
def stats(msg):
    uid = msg.from_user.id
    total_sold, total_amount, top_buyers = get_sales_stats()
    txt = f"📊 آمار فروش:\n\n"
    txt += f"📦 تعداد کانفیگ‌های فروخته‌شده: {total_sold}\n"
    txt += f"💰 مجموع فروش: {total_amount:,} تومان\n\n"
    txt += "🏆 برترین خریداران:\n"
    for i, buyer in enumerate(top_buyers, start=1):
        txt += f"{i}. {buyer['username']} | {buyer['count']} کانفیگ | {buyer['spent']:,} تومان\n"
    clear_state(uid)
    bot.send_message(uid, txt, reply_markup=admin_panel())

# -------------------------------
# استارت
# -------------------------------
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    add_user(uid)
    bot.send_message(uid, "🌟 به ربات خوش اومدی! امیدوارم تجربه خوبی داشته باشی.", reply_markup=main_menu())

print("🤖 Bot is running...")
bot.infinity_polling()
