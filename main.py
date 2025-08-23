# main.py
# -*- coding: utf-8 -*-
import os, json, time, re, threading
from datetime import datetime, timedelta
from uuid import uuid4

from flask import Flask, request, abort
import telebot
from telebot import types

# ----------------------------
# تنظیمات پایه
# ----------------------------
APP_URL = os.getenv("APP_URL", "").rstrip("/")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN env var is required")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}" if APP_URL else None

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, disable_web_page_preview=True)

DATA_FILE = "data.json"
LOCK = threading.Lock()

# ادمین پیش‌فرض
DEFAULT_ADMINS = ["1743359080"]  # می‌تونی بعداً از توی بات اضافه/حذف کنی

# ----------------------------
# ابزار ذخیره‌سازی (JSON)
# ----------------------------
def now_ts():
    return int(time.time())

def _load():
    if not os.path.exists(DATA_FILE):
        base = {
            "admins": DEFAULT_ADMINS[:],
            "users": {},               # uid -> {wallet:int, tickets:[...], purchases:[purchase_id], username:str}
            "plans": {},               # plan_id -> {name, days, traffic_gb, price, desc, enabled:bool}
            "inventory": {},           # plan_id -> [ {id, text, photo_id} ]
            "coupons": {},             # code -> {percent:int, plan_id or "all", max_uses:int, used:int, active:bool}
            "receipts": {},            # rid -> {uid, type:"wallet"|"purchase", plan_id?, amount, status, admin_id?, created_at}
            "purchases": {},           # pid -> {uid, plan_id, price, coupon?, delivered_cfg_id?, created_at}
            "tickets": {},             # tid -> {uid, subject, status, msgs:[{from, text, ts}]}
            "buttons": {               # روشن/خاموش کردن بخش‌ها
                "shop": True, "wallet": True, "tickets": True, "my_configs": True, "help": True
            },
            "texts": {                 # متون قابل ویرایش
                "welcome": "سلام! خوش اومدی 🌟 از منوی زیر یکی رو انتخاب کن.",
                "help": "📘 آموزش قدم‌به‌قدم:\n\n"
                        "🛍 خرید پلن: از «خرید پلن» → پلن رو انتخاب کن → کوپن اختیاری → پرداخت.\n"
                        "🪙 کیف پول: موجودی رو ببین، شارژ کن یا باهاش خرید کن.\n"
                        "🎫 تیکت: اگر سوال/مشکلی داشتی، از اینجا تیکت بساز.\n"
                        "🗂 کانفیگ‌های من: همه خریدهای قبلیت.\n",
                "card_number": "****-****-****-****",  # توسط ادمین قابل ویرایش
            },
            "wallet_logs": [],         # [{uid, admin_id, delta, old, new, reason, ts}]
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(base, f, ensure_ascii=False, indent=2)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(db):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def db_read():
    with LOCK:
        return _load()

def db_write(mutator):
    with LOCK:
        db = _load()
        mutator(db)
        _save(db)

# ----------------------------
# ابزارها
# ----------------------------
def is_admin(uid: int) -> bool:
    db = db_read()
    return str(uid) in db["admins"]

def get_username(u: telebot.types.User) -> str:
    return (u.username or "").strip()

def ensure_user(uid: int, username: str):
    def mut(db):
        users = db["users"]
        uid_s = str(uid)
        if uid_s not in users:
            users[uid_s] = {"wallet": 0, "tickets": [], "purchases": [], "username": username}
        else:
            users[uid_s]["username"] = username
    db_write(mut)

def fmt_toman(n: int) -> str:
    s = f"{n:,}".replace(",", "،")
    return f"{s} تومان"

def parse_amount(txt: str):
    # اعداد با کاما/فاصله/فارسی → فقط رقم
    digits = re.sub(r"[^\d]", "", txt)
    return int(digits) if digits else None

def make_kb(rows):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for row in rows:
        kb.row(*[types.KeyboardButton(x) for x in row])
    return kb

def admin_kb():
    rows = [
        ["📦 مدیریت پلن‌ها/مخزن", "🏷 مدیریت کد تخفیف"],
        ["🧾 رسیدها", "🪙 کیف پول کاربران"],
        ["👥 مدیریت ادمین‌ها", "🧩 دکمه‌ها و متون"],
        ["📊 آمار فروش"],
        ["🔙 بازگشت"],
    ]
    return make_kb(rows)

def user_main_kb():
    db = db_read()
    rows = []
    if db["buttons"].get("shop", True): rows.append(["🛍 خرید پلن"])
    if db["buttons"].get("wallet", True): rows.append(["🪙 کیف پول"])
    if db["buttons"].get("tickets", True): rows.append(["🎫 پشتیبانی"])
    if db["buttons"].get("my_configs", True): rows.append(["🗂 کانفیگ‌های من"])
    if db["buttons"].get("help", True): rows.append(["📘 آموزش ربات"])
    if is_admin_cache.get("on", False):
        rows.append(["👑 ورود پنل ادمین"])
    return make_kb(rows)

# کش کوچک برای جلوگیری از ساخت اضافه دکمه «ورود ادمین»
is_admin_cache = {"on": True}

# ----------------------------
# مدیریت استیت‌ها
# ----------------------------
STATE_FILE = "state.json"

def get_state(uid: int):
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
    return st.get(str(uid), {})

def set_state(uid: int, **kwargs):
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
    cur = st.get(str(uid), {})
    if kwargs is None:
        cur = {}
    else:
        # پاک‌کردن کلیدهای None
        for k, v in list(kwargs.items()):
            if v is None and k in cur:
                del cur[k]
            elif v is not None:
                cur[k] = v
    st[str(uid)] = cur
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

def clear_state(uid: int):
    set_state(uid, reset=True)
    # پاک کامل:
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
    st[str(uid)] = {}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

# ----------------------------
# UI ابتدایی
# ----------------------------
def send_welcome(chat_id, is_admin_user=False):
    db = db_read()
    kb = user_main_kb()
    bot.send_message(chat_id, db["texts"]["welcome"], reply_markup=kb)
    if is_admin_user:
        bot.send_message(chat_id, "برای ورود به پنل ادمین، «👑 ورود پنل ادمین» را بزن.", reply_markup=kb)

# ----------------------------
# وبهوک
# ----------------------------
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

# ----------------------------
# راه‌اندازی وبهوک یک‌بار
# ----------------------------
def set_webhook_once():
    if not WEBHOOK_URL:
        print("APP_URL is not set; webhook not configured")
        return
    try:
        bot.delete_webhook()
    except Exception:
        pass
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"{datetime.utcnow()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print(f"{datetime.utcnow()} | ERROR | Failed to set webhook: {e}")

# ----------------------------
# هندل پیام‌ها
# ----------------------------
@bot.message_handler(func=lambda m: True, content_types=["text", "photo", "document"])
def all_msgs(m: types.Message):
    uid = m.from_user.id
    ensure_user(uid, get_username(m.from_user))
    st = get_state(uid)
    txt = (m.text or "").strip()
    admin = is_admin(uid)

    # گرفتن عکس به عنوان رسید در حالت‌های انتظار
    if m.content_type in ("photo", "document"):
        if st.get("await_receipt"):
            handle_user_receipt(m, st)
            return
        # پیام فایل در تیکت:
        if st.get("ticket_mode") in ("new_body", "reply_body"):
            # فایل را به متن تبدیل نمی‌کنیم؛ یک placeholder می‌گذاریم
            file_note = "🖼 فایل/عکس پیوست شد."
            m.text = file_note
            # ادامه مثل متن
        else:
            # خارج از حالت‌های مربوطه، نادیده گرفته می‌شود
            pass

    # دکمه‌های اصلی
    if txt in ("شروع", "بازگشت", "🔙 بازگشت", "/start"):
        clear_state(uid)
        send_welcome(uid, is_admin_user=admin)
        return

    if txt == "👑 ورود پنل ادمین":
        if admin:
            clear_state(uid)
            bot.send_message(uid, "خوش آمدی به پنل ادمین 👑", reply_markup=admin_kb())
        else:
            bot.send_message(uid, "شما ادمین نیستید.")
        return

    # کاربر
    if txt == "🛍 خرید پلن":
        show_plans(uid)
        return

    if txt == "🪙 کیف پول":
        show_wallet(uid)
        return

    if txt == "🎫 پشتیبانی":
        show_ticket_menu(uid)
        return

    if txt == "🗂 کانفیگ‌های من":
        show_my_configs(uid)
        return

    if txt == "📘 آموزش ربات":
        show_help(uid)
        return

    # ادمین
    if admin:
        if txt == "📦 مدیریت پلن‌ها/مخزن":
            admin_plans_menu(uid)
            return
        if txt == "🏷 مدیریت کد تخفیف":
            admin_coupon_menu(uid)
            return
        if txt == "🧾 رسیدها":
            admin_receipts_menu(uid)
            return
        if txt == "🪙 کیف پول کاربران":
            admin_wallet_menu(uid)
            return
        if txt == "👥 مدیریت ادمین‌ها":
            admin_admins_menu(uid)
            return
        if txt == "🧩 دکمه‌ها و متون":
            admin_texts_buttons_menu(uid)
            return
        if txt == "📊 آمار فروش":
            admin_stats(uid)
            return

    # پردازش حالت‌ها (state machine)
    if st:
        handle_stateful(uid, m, st)
        return

    # اگر هیچ‌کدوم نبود:
    bot.send_message(uid, "از منوی زیر انتخاب کن:", reply_markup=(admin_kb() if admin else user_main_kb()))

# ----------------------------
# فروشگاه / پلن‌ها
# ----------------------------
def show_plans(uid: int):
    db = db_read()
    rows = []
    for pid, p in db["plans"].items():
        if p.get("enabled", True):
            inv_count = len(db["inventory"].get(pid, []))
            label = f"{p['name']} — {fmt_toman(p['price'])} — موجودی: {inv_count}"
            rows.append([label, f"🔎 جزئیات «{p['name']}»"])
    rows.append(["🔙 بازگشت"])
    bot.send_message(uid, "🛍 لیست پلن‌ها:", reply_markup=make_kb(rows))

@bot.message_handler(func=lambda m: m.text and m.text.startswith("🔎 جزئیات «"))
def plan_details(m: types.Message):
    uid = m.from_user.id
    db = db_read()
    name = m.text.replace("🔎 جزئیات «", "").rstrip("»")
    pid = None
    for k, v in db["plans"].items():
        if v["name"] == name:
            pid = k
            p = v
            break
    if not pid:
        bot.send_message(uid, "پلن پیدا نشد.")
        return
    inv_count = len(db["inventory"].get(pid, []))
    desc = p.get("desc", "")
    msg = (f"📦 {p['name']}\n"
           f"⏳ مدت: {p['days']} روز\n"
           f"📶 حجم: {p['traffic_gb']} گیگ\n"
           f"💵 قیمت: {fmt_toman(p['price'])}\n"
           f"📦 موجودی مخزن: {inv_count}\n\n"
           f"{desc}")
    rows = [["🎟 اعمال/حذف کد تخفیف"], ["💳 کارت‌به‌کارت", "💼 پرداخت با کیف پول"], ["🔙 بازگشت"]]
    set_state(uid, flow="buy_plan", plan_id=pid, coupon=None)
    bot.send_message(uid, msg, reply_markup=make_kb(rows))

@bot.message_handler(func=lambda m: m.text == "🎟 اعمال/حذف کد تخفیف")
def coupon_apply_menu(m: types.Message):
    uid = m.from_user.id
    st = get_state(uid)
    if st.get("flow") != "buy_plan":
        bot.send_message(uid, "ابتدا یک پلن انتخاب کن.")
        return
    c = st.get("coupon")
    if c:
        rows = [["❌ حذف کد تخفیف"], ["🔙 بازگشت"]]
        bot.send_message(uid, f"کد فعلی: {c} — برای حذف بزن:", reply_markup=make_kb(rows))
        set_state(uid, coupon_mode="remove")
    else:
        rows = [["🔙 بازگشت"]]
        bot.send_message(uid, "کد تخفیف رو بفرست:", reply_markup=make_kb(rows))
        set_state(uid, coupon_mode="enter")

@bot.message_handler(func=lambda m: m.text == "❌ حذف کد تخفیف")
def coupon_remove(m: types.Message):
    uid = m.from_user.id
    st = get_state(uid)
    if st.get("coupon_mode") == "remove":
        set_state(uid, coupon=None, coupon_mode=None)
        bot.send_message(uid, "کد تخفیف حذف شد ✅")
        show_payment_options(uid)
    else:
        bot.send_message(uid, "ابتدا وارد بخش کد تخفیف شو.")

def show_payment_options(uid: int):
    db = db_read()
    st = get_state(uid)
    pid = st.get("plan_id")
    if not pid:
        bot.send_message(uid, "پلن نامعتبر.")
        return
    p = db["plans"][pid]
    price = p["price"]
    coupon_code = st.get("coupon")
    discount = 0
    if coupon_code and coupon_code in db["coupons"]:
        c = db["coupons"][coupon_code]
        if c["active"] and (c["plan_id"] in ("all", pid)) and (c["used"] < c["max_uses"]):
            discount = (price * c["percent"]) // 100
    final = max(price - discount, 0)
    wallet = db["users"][str(uid)]["wallet"]
    msg = f"💵 مبلغ نهایی: {fmt_toman(final)}\n"
    if coupon_code:
        msg += f"🎟 کد: {coupon_code} — تخفیف: {fmt_toman(discount)}\n"
    rows = [["💳 کارت‌به‌کارت"]]
    if wallet >= final and final > 0:
        rows[0].append("💼 پرداخت با کیف پول")
    elif final > wallet:
        diff = final - wallet
        rows.append([f"➕ شارژ همین مقدار ({fmt_toman(diff)})"])
    rows.append(["🔙 بازگشت"])
    bot.send_message(uid, msg, reply_markup=make_kb(rows))

@bot.message_handler(func=lambda m: m.text == "💳 کارت‌به‌کارت")
def pay_card_to_card(m: types.Message):
    uid = m.from_user.id
    db = db_read()
    st = get_state(uid)
    if st.get("flow") != "buy_plan":
        bot.send_message(uid, "ابتدا پلن انتخاب کن.")
        return
    pid = st["plan_id"]
    p = db["plans"][pid]
    # مبلغ نهایی
    coupon_code = st.get("coupon")
    discount = 0
    if coupon_code and coupon_code in db["coupons"]:
        c = db["coupons"][coupon_code]
        if c["active"] and (c["plan_id"] in ("all", pid)) and (c["used"] < c["max_uses"]):
            discount = (p["price"] * c["percent"]) // 100
    final = max(p["price"] - discount, 0)

    card_no = db["texts"]["card_number"]
    bot.send_message(uid, f"👈 مبلغ قابل پرداخت: {fmt_toman(final)}\n"
                          f"🪪 شماره کارت:\n`{card_no}`\n\n"
                          f"لطفاً رسید را ارسال کنید و نوع پرداخت را انتخاب کنید.",
                     parse_mode="Markdown", reply_markup=make_kb([["📷 ارسال رسید خرید"], ["🔙 بازگشت"]]))
    set_state(uid, await_receipt={"kind": "purchase", "plan_id": pid, "expected": final, "coupon": st.get("coupon")})

@bot.message_handler(func=lambda m: m.text == "💼 پرداخت با کیف پول")
def pay_with_wallet(m: types.Message):
    uid = m.from_user.id
    db = db_read()
    st = get_state(uid)
    if st.get("flow") != "buy_plan":
        bot.send_message(uid, "ابتدا پلن انتخاب کن.")
        return
    pid = st["plan_id"]
    p = db["plans"][pid]
    # محاسبه نهایی
    coupon_code = st.get("coupon")
    discount = 0
    if coupon_code and coupon_code in db["coupons"]:
        c = db["coupons"][coupon_code]
        if c["active"] and (c["plan_id"] in ("all", pid)) and (c["used"] < c["max_uses"]):
            discount = (p["price"] * c["percent"]) // 100
    final = max(p["price"] - discount, 0)

    user = db["users"][str(uid)]
    if user["wallet"] < final:
        bot.send_message(uid, "موجودی کافی نیست. از گزینه شارژ استفاده کن.")
        show_payment_options(uid)
        return

    # کم‌کردن و تحویل کانفیگ
    cfg_id, cfg_txt, cfg_photo = pop_inventory(pid)
    if not cfg_id:
        bot.send_message(uid, "موجودی این پلن تمام شده. لطفاً بعداً تلاش کن.")
        return

    def mut(dbm):
        dbm["users"][str(uid)]["wallet"] -= final
        # خرید
        pid_buy = str(uuid4())
        dbm["purchases"][pid_buy] = {"uid": str(uid), "plan_id": pid, "price": final,
                                     "coupon": coupon_code, "delivered_cfg_id": cfg_id, "created_at": now_ts()}
        dbm["users"][str(uid)]["purchases"].append(pid_buy)
        # کوپن مصرف شد؟
        if coupon_code and coupon_code in dbm["coupons"]:
            dbm["coupons"][coupon_code]["used"] += 1
    db_write(mut)

    # تحویل
    deliver_config(uid, cfg_txt, cfg_photo, p['name'])

def pop_inventory(plan_id: str):
    db = db_read()
    arr = db["inventory"].get(plan_id, [])
    if not arr:
        return None, None, None
    cfg = arr.pop(0)
    def mut(dbm):
        dbm["inventory"].setdefault(plan_id, [])
        dbm["inventory"][plan_id] = arr
    db_write(mut)
    return cfg["id"], cfg.get("text"), cfg.get("photo_id")

def deliver_config(uid: int, cfg_txt: str, cfg_photo: str, plan_name: str):
    if cfg_photo:
        bot.send_photo(uid, cfg_photo, caption=f"✅ کانفیگ پلن «{plan_name}»", reply_markup=user_main_kb())
    if cfg_txt:
        bot.send_message(uid, f"✅ کانفیگ پلن «{plan_name}»:\n\n{cfg_txt}", reply_markup=user_main_kb())
    bot.send_message(uid, "خرید با موفقیت انجام شد 🎉")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("➕ شارژ همین مقدار"))
def charge_diff(m: types.Message):
    uid = m.from_user.id
    st = get_state(uid)
    if st.get("flow") != "buy_plan":
        bot.send_message(uid, "ابتدا پلن انتخاب کن.")
        return
    bot.send_message(uid, "لطفاً رسید شارژ مابه‌التفاوت را ارسال کن:", reply_markup=make_kb([["📷 ارسال رسید شارژ"], ["🔙 بازگشت"]]))
    set_state(uid, await_receipt={"kind": "wallet_diff"})

@bot.message_handler(func=lambda m: m.text in ("📷 ارسال رسید خرید", "📷 ارسال رسید شارژ"))
def ask_receipt(m: types.Message):
    uid = m.from_user.id
    st = get_state(uid)
    if not st.get("await_receipt"):
        # اگر از منو نیومده باشه
        bot.send_message(uid, "ابتدا گزینه پرداخت را انتخاب کن.")
        return
    bot.send_message(uid, "✅ حالا عکس/فایل رسید را همینجا بفرست.\n"
                          "پس از ارسال، رسید برای ادمین‌ها جهت بررسی ارسال می‌شود.\n"
                          "تا تأیید نهایی صبر کن 🙏")

def handle_user_receipt(m: types.Message, st: dict):
    uid = m.from_user.id
    mode = st["await_receipt"]
    kind = mode["kind"]
    db = db_read()
    if m.content_type not in ("photo", "document"):
        bot.send_message(uid, "لطفاً عکس/فایل رسید را ارسال کنید.")
        return
    # ساخت رکورد رسید
    rid = str(uuid4())
    amt = None
    if kind == "purchase":
        amt = mode.get("expected")
    elif kind == "wallet_diff":
        # کاربر مبلغ را تعیین نکرده؛ ادمین هنگام تأیید وارد می‌کند
        pass
    rec = {"uid": str(uid), "type": "purchase" if kind == "purchase" else "wallet",
           "plan_id": mode.get("plan_id"), "amount": amt, "status": "pending",
           "admin_id": None, "created_at": now_ts(), "coupon": mode.get("coupon")}
    def mut(dbm):
        dbm["receipts"][rid] = rec
    db_write(mut)

    # اطلاع به ادمین‌ها
    notify_admins_new_receipt(rid, uid, kind)

    bot.send_message(uid, "📨 رسید شما ثبت شد؛ منتظر تأیید ادمین…")
    clear_state(uid)

def notify_admins_new_receipt(rid: str, user_id: int, kind: str):
    db = db_read()
    u = db["users"][str(user_id)]
    for aid in db["admins"]:
        try:
            bot.send_message(int(aid),
                             f"🆕 رسید جدید #{rid[:8]}\n"
                             f"👤 @{u.get('username','') or '—'} | {user_id}\n"
                             f"نوع: {'خرید کانفیگ' if kind=='purchase' else 'شارژ کیف پول'}\n"
                             f"وضعیت: در انتظار")
        except Exception:
            pass

# ----------------------------
# کیف پول کاربر
# ----------------------------
def show_wallet(uid: int):
    db = db_read()
    bal = db["users"][str(uid)]["wallet"]
    rows = [["➕ شارژ کیف پول", "🔙 بازگشت"]]
    bot.send_message(uid, f"🪙 موجودی فعلی: {fmt_toman(bal)}", reply_markup=make_kb(rows))
    set_state(uid, wallet_menu=True)

@bot.message_handler(func=lambda m: m.text == "➕ شارژ کیف پول")
def wallet_charge(m: types.Message):
    uid = m.from_user.id
    db = db_read()
    card_no = db["texts"]["card_number"]
    bot.send_message(uid, f"برای شارژ کیف پول:\n"
                          f"🪪 شماره کارت:\n`{card_no}`\n\n"
                          f"لطفاً رسید را ارسال کنید.", parse_mode="Markdown",
                     reply_markup=make_kb([["📷 ارسال رسید شارژ"], ["🔙 بازگشت"]]))
    set_state(uid, await_receipt={"kind": "wallet"})

# ----------------------------
# تیکت سیستم
# ----------------------------
def show_ticket_menu(uid: int):
    rows = [["🆕 تیکت جدید", "📂 تیکت‌های من"], ["🔙 بازگشت"]]
    bot.send_message(uid, "🎫 پشتیبانی:", reply_markup=make_kb(rows))

@bot.message_handler(func=lambda m: m.text == "🆕 تیکت جدید")
def ticket_new(m: types.Message):
    uid = m.from_user.id
    bot.send_message(uid, "موضوع تیکت رو بنویس:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, ticket_mode="new_subject")

@bot.message_handler(func=lambda m: m.text == "📂 تیکت‌های من")
def ticket_list(m: types.Message):
    uid = m.from_user.id
    db = db_read()
    my = []
    for tid, t in db["tickets"].items():
        if t["uid"] == str(uid):
            my.append((tid, t))
    if not my:
        bot.send_message(uid, "هنوز تیکتی نداری.")
        return
    rows = []
    for tid, t in sorted(my, key=lambda x: x[1]["created_at"], reverse=True)[:20]:
        rows.append([f"📄 {t['subject']} — {t['status']} — #{tid[:6]}"])
    rows.append(["🔙 بازگشت"])
    bot.send_message(uid, "🗂 لیست تیکت‌ها:", reply_markup=make_kb(rows))
    set_state(uid, ticket_mode="list")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("📄 "))
def ticket_open(m: types.Message):
    uid = m.from_user.id
    db = db_read()
    seg = m.text
    tid_hash = seg.split("#")[-1]
    target = None
    for tid in db["tickets"]:
        if tid.startswith(tid_hash):
            target = tid
            break
    if not target:
        bot.send_message(uid, "تیکت پیدا نشد.")
        return
    t = db["tickets"][target]
    if t["uid"] != str(uid) and not is_admin(uid):
        bot.send_message(uid, "دسترسی نداری.")
        return
    txt = f"🎫 {t['subject']} — {t['status']}\n\n"
    for msg in t["msgs"][-10:]:
        who = "👤کاربر" if msg["from"] == "user" else "👑ادمین"
        txt += f"{who}: {msg['text']}\n"
    rows = [["✍️ پاسخ", "🔙 بازگشت"]]
    bot.send_message(uid, txt, reply_markup=make_kb(rows))
    set_state(uid, ticket_mode="open", ticket_id=target)

@bot.message_handler(func=lambda m: m.text == "✍️ پاسخ")
def ticket_reply(m: types.Message):
    uid = m.from_user.id
    st = get_state(uid)
    if st.get("ticket_mode") != "open":
        bot.send_message(uid, "ابتدا یک تیکت باز کن.")
        return
    bot.send_message(uid, "متن پاسخ رو بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, ticket_mode="reply_body")

def ticket_add(uid: int, text: str, author: str, tid: str):
    def mut(dbm):
        dbm["tickets"][tid]["msgs"].append({"from": author, "text": text, "ts": now_ts()})
        # اگر ادمین پاسخ داد و وضعیت باز بود، باز می‌ماند. اگر کاربر پاسخ داد و بسته بود، باز شود:
        if author == "user" and dbm["tickets"][tid]["status"] == "closed":
            dbm["tickets"][tid]["status"] = "open"
    db_write(mut)

# ----------------------------
# ادمین: منوها
# ----------------------------
def admin_plans_menu(uid: int):
    db = db_read()
    rows = [["➕ افزودن پلن", "📋 لیست پلن‌ها"], ["📦 مخزن پلن", "🔙 بازگشت"]]
    bot.send_message(uid, "📦 مدیریت پلن‌ها/مخزن:", reply_markup=make_kb(rows))

def admin_coupon_menu(uid: int):
    rows = [["➕ ساخت کوپن", "📃 لیست کوپن‌ها"], ["🔙 بازگشت"]]
    bot.send_message(uid, "🏷 مدیریت کد تخفیف:", reply_markup=make_kb(rows))

def admin_receipts_menu(uid: int):
    db = db_read()
    pend = [r for r in db["receipts"].values() if r["status"] == "pending"]
    rows = [["📥 رسیدهای در انتظار" + (f" ({len(pend)})" if pend else "")], ["📜 همه رسیدها"], ["🔙 بازگشت"]]
    bot.send_message(uid, "🧾 رسیدها:", reply_markup=make_kb(rows))

def admin_wallet_menu(uid: int):
    rows = [["➕ افزایش موجودی", "➖ کسر موجودی"], ["📒 لاگ موجودی"], ["🔙 بازگشت"]]
    bot.send_message(uid, "🪙 کیف پول کاربران:", reply_markup=make_kb(rows))

def admin_admins_menu(uid: int):
    rows = [["➕ افزودن ادمین", "🗑 حذف ادمین"], ["📃 لیست ادمین‌ها"], ["🔙 بازگشت"]]
    bot.send_message(uid, "👥 مدیریت ادمین‌ها:", reply_markup=make_kb(rows))

def admin_texts_buttons_menu(uid: int):
    rows = [["📝 ویرایش متن‌ها", "🔘 مدیریت دکمه‌ها"], ["💳 تنظیم شماره کارت"], ["🔙 بازگشت"]]
    bot.send_message(uid, "🧩 دکمه‌ها و متون:", reply_markup=make_kb(rows))

def admin_stats(uid: int):
    db = db_read()
    # فروش کل
    total_income = sum(p["price"] for p in db["purchases"].values())
    # تعداد کانفیگ فروخته‌شده
    total_items = len(db["purchases"])
    # خریداران برتر
    sums = {}
    counts = {}
    for pid, p in db["purchases"].items():
        u = p["uid"]
        sums[u] = sums.get(u, 0) + p["price"]
        counts[u] = counts.get(u, 0) + 1
    top = sorted(sums.items(), key=lambda x: x[1], reverse=True)[:10]
    txt = f"📊 آمار فروش:\n\n"
    txt += f"🧾 تعداد فروش: {total_items}\n"
    txt += f"💰 درآمد کل: {fmt_toman(total_income)}\n\n"
    txt += "🏆 Top Buyers:\n"
    for u, amt in top:
        uname = db["users"].get(u, {}).get("username") or "—"
        txt += f"• @{uname} ({u}) — {counts[u]} خرید — {fmt_toman(amt)}\n"
    bot.send_message(uid, txt, reply_markup=admin_kb())

# ----------------------------
# ادمین: عملیات
# ----------------------------
@bot.message_handler(func=lambda m: m.text == "📋 لیست پلن‌ها")
def admin_list_plans(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    if not db["plans"]:
        bot.send_message(uid, "هیچ پلنی ثبت نشده.")
        return
    rows = []
    for pid, p in db["plans"].items():
        inv = len(db["inventory"].get(pid, []))
        en = "✅" if p.get("enabled", True) else "⛔"
        rows.append([f"{en} {p['name']} — {fmt_toman(p['price'])} — موجودی {inv}",
                     f"✏️ ویرایش «{p['name']}»", f"{'🔴' if en=='✅' else '🟢'} روشن/خاموش «{p['name']}»"])
    rows.append(["🔙 بازگشت"])
    bot.send_message(uid, "📋 پلن‌ها:", reply_markup=make_kb(rows))

@bot.message_handler(func=lambda m: m.text == "➕ افزودن پلن")
def admin_add_plan(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    bot.send_message(uid, "نام پلن را بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, add_plan_step="name")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("✏️ ویرایش «"))
def admin_edit_plan_start(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    name = m.text.replace("✏️ ویرایش «", "").rstrip("»")
    db = db_read()
    pid = next((k for k, v in db["plans"].items() if v["name"] == name), None)
    if not pid:
        bot.send_message(uid, "پلن پیدا نشد.")
        return
    bot.send_message(uid, "کدام مورد را ویرایش کنم؟", reply_markup=make_kb([
        ["✏️ نام", "✏️ قیمت"], ["✏️ مدت (روز)", "✏️ حجم (GB)"], ["✏️ توضیحات"], ["🔙 بازگشت"]
    ]))
    set_state(uid, edit_plan_id=pid, edit_plan_step="menu")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("🟢 روشن/خاموش «") or m.text.startswith("🔴 روشن/خاموش «"))
def admin_toggle_plan(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    name = m.text.split("«",1)[1].rstrip("»")
    def mut(dbm):
        pid = next((k for k, v in dbm["plans"].items() if v["name"] == name), None)
        if pid:
            dbm["plans"][pid]["enabled"] = not dbm["plans"][pid].get("enabled", True)
    db_write(mut)
    bot.send_message(uid, "انجام شد ✅")
    admin_list_plans(m)

@bot.message_handler(func=lambda m: m.text == "📦 مخزن پلن")
def admin_inventory_menu(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    if not db["plans"]:
        bot.send_message(uid, "اول پلن بساز.")
        return
    rows = []
    for pid, p in db["plans"].items():
        inv = len(db["inventory"].get(pid, []))
        rows.append([f"📦 مخزن «{p['name']}» ({inv})"])
    rows.append(["🔙 بازگشت"])
    bot.send_message(uid, "کدام مخزن؟", reply_markup=make_kb(rows))
    set_state(uid, inv_step="pick")

@bot.message_handler(func=lambda m: m.text and m.text.startswith("📦 مخزن «"))
def admin_inventory_manage(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    name = m.text.replace("📦 مخزن «", "").split("»")[0]
    db = db_read()
    pid = next((k for k, v in db["plans"].items() if v["name"] == name), None)
    if not pid:
        bot.send_message(uid, "پلن پیدا نشد.")
        return
    rows = [["➕ افزودن کانفیگ متنی", "🖼 افزودن کانفیگ تصویری"], ["📄 لیست مخزن"], ["🔙 بازگشت"]]
    bot.send_message(uid, f"مدیریت مخزن «{name}»:", reply_markup=make_kb(rows))
    set_state(uid, inv_step="menu", inv_plan_id=pid)

@bot.message_handler(func=lambda m: m.text == "📄 لیست مخزن")
def admin_inventory_list(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    st = get_state(uid)
    pid = st.get("inv_plan_id")
    if not pid:
        bot.send_message(uid, "ابتدا یک مخزن انتخاب کن.")
        return
    db = db_read()
    arr = db["inventory"].get(pid, [])
    if not arr:
        bot.send_message(uid, "مخزن خالی است.")
        return
    msg = "آیتم‌ها:\n"
    for it in arr[:20]:
        msg += f"• {it['id']}\n"
    bot.send_message(uid, msg)

@bot.message_handler(func=lambda m: m.text == "➕ افزودن کانفیگ متنی")
def admin_inventory_add_text(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    st = get_state(uid)
    if not st.get("inv_plan_id"):
        bot.send_message(uid, "ابتدا مخزن را انتخاب کن.")
        return
    bot.send_message(uid, "متن کانفیگ را بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, inv_step="add_text")

@bot.message_handler(func=lambda m: m.text == "🖼 افزودن کانفیگ تصویری")
def admin_inventory_add_photo(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    st = get_state(uid)
    if not st.get("inv_plan_id"):
        bot.send_message(uid, "ابتدا مخزن را انتخاب کن.")
        return
    bot.send_message(uid, "عکس کانفیگ را بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, inv_step="add_photo")

# کوپن‌ها
@bot.message_handler(func=lambda m: m.text == "➕ ساخت کوپن")
def admin_coupon_create(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    bot.send_message(uid, "درصد تخفیف را وارد کن (مثلاً 20):", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, coupon_flow="create", coupon_step="percent")

@bot.message_handler(func=lambda m: m.text == "📃 لیست کوپن‌ها")
def admin_coupon_list(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    if not db["coupons"]:
        bot.send_message(uid, "کوپنی وجود ندارد.")
        return
    msg = "🏷 کوپن‌ها:\n"
    for code, c in db["coupons"].items():
        msg += (f"• {code} — {c['percent']}% — "
                f"{'همه پلن‌ها' if c['plan_id']=='all' else f'پلن {c["plan_id"]}'} — "
                f"استفاده: {c['used']}/{c['max_uses']} — {'فعال' if c['active'] else 'غیرفعال'}\n")
    bot.send_message(uid, msg)

# رسیدها
@bot.message_handler(func=lambda m: m.text == "📥 رسیدهای در انتظار")
def admin_receipts_pending(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    pend = [(rid, r) for rid, r in db["receipts"].items() if r["status"] == "pending"]
    if not pend:
        bot.send_message(uid, "رسید در انتظاری نداریم.")
        return
    rows = []
    for rid, r in pend[:20]:
        user = db["users"].get(r["uid"], {})
        label = f"#{rid[:6]} — {(user.get('username') and '@'+user['username']) or r['uid']} — {r['type']}"
        rows.append([label])
    rows.append(["🔙 بازگشت"])
    bot.send_message(uid, "در انتظار:", reply_markup=make_kb(rows))
    set_state(uid, receipt_mode="pick")

@bot.message_handler(func=lambda m: m.text == "📜 همه رسیدها")
def admin_receipts_all(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    if not db["receipts"]:
        bot.send_message(uid, "رسیدی نداریم.")
        return
    rows = []
    for rid, r in list(db["receipts"].items())[-20:]:
        user = db["users"].get(r["uid"], {})
        label = f"#{rid[:6]} — {(user.get('username') and '@'+user['username']) or r['uid']} — {r['type']} — {r['status']}"
        rows.append([label])
    rows.append(["🔙 بازگشت"])
    bot.send_message(uid, "همه رسیدها:", reply_markup=make_kb(rows))
    set_state(uid, receipt_mode="pick")

# کیف پول ادمین
@bot.message_handler(func=lambda m: m.text == "➕ افزایش موجودی")
def admin_wallet_inc(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    bot.send_message(uid, "آیدی عددی کاربر را بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, wallet_op="inc_user")

@bot.message_handler(func=lambda m: m.text == "➖ کسر موجودی")
def admin_wallet_dec(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    bot.send_message(uid, "آیدی عددی کاربر را بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, wallet_op="dec_user")

@bot.message_handler(func=lambda m: m.text == "📒 لاگ موجودی")
def admin_wallet_log(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    logs = db["wallet_logs"][-20:]
    if not logs:
        bot.send_message(uid, "لاگی وجود ندارد.")
        return
    msg = "📒 لاگ تغییرات موجودی:\n"
    for lg in logs[::-1]:
        uname = db["users"].get(lg["uid"], {}).get("username", "—")
        aname = db["users"].get(lg["admin_id"], {}).get("username", "—")
        msg += (f"• @{uname}({lg['uid']}) — تغییر: {fmt_toman(lg['delta'])} | "
                f"قبل: {fmt_toman(lg['old'])} → بعد: {fmt_toman(lg['new'])}\n"
                f"  توسط: @{aname}({lg['admin_id']}) — {datetime.fromtimestamp(lg['ts']).strftime('%Y-%m-%d %H:%M')}\n")
    bot.send_message(uid, msg)

# مدیریت ادمین‌ها
@bot.message_handler(func=lambda m: m.text == "➕ افزودن ادمین")
def admin_add_admin(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    bot.send_message(uid, "آیدی عددی کاربر را بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, admin_op="add")

@bot.message_handler(func=lambda m: m.text == "🗑 حذف ادمین")
def admin_del_admin(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    bot.send_message(uid, "آیدی عددی کاربر را بفرست:", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, admin_op="del")

@bot.message_handler(func=lambda m: m.text == "📃 لیست ادمین‌ها")
def admin_list_admins(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    if not db["admins"]:
        bot.send_message(uid, "ادمینی وجود ندارد.")
        return
    msg = "👑 ادمین‌ها:\n" + "\n".join(f"• {aid}" for aid in db["admins"])
    bot.send_message(uid, msg)

# متن‌ها و دکمه‌ها
@bot.message_handler(func=lambda m: m.text == "📝 ویرایش متن‌ها")
def admin_edit_texts(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    rows = [["متن خوشامد", "متن آموزش"], ["🔙 بازگشت"]]
    bot.send_message(uid, "کدام متن؟", reply_markup=make_kb(rows))
    set_state(uid, edit_text_step="menu")

@bot.message_handler(func=lambda m: m.text == "🔘 مدیریت دکمه‌ها")
def admin_toggle_buttons(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    db = db_read()
    b = db["buttons"]
    rows = [[f"{'🟢' if b.get('shop', True) else '🔴'} خرید پلن",
             f"{'🟢' if b.get('wallet', True) else '🔴'} کیف پول"],
            [f"{'🟢' if b.get('tickets', True) else '🔴'} تیکت",
             f"{'🟢' if b.get('my_configs', True) else '🔴'} کانفیگ‌های من"],
            [f"{'🟢' if b.get('help', True) else '🔴'} آموزش"],
            ["🔙 بازگشت"]]
    bot.send_message(uid, "روشن/خاموش کن:", reply_markup=make_kb(rows))
    set_state(uid, toggle_buttons=True)

@bot.message_handler(func=lambda m: m.text == "💳 تنظیم شماره کارت")
def admin_set_card_number(m: types.Message):
    uid = m.from_user.id
    if not is_admin(uid): return
    bot.send_message(uid, "شماره کارت را وارد کن (با یا بی‌خط تیره):", reply_markup=make_kb([["🔙 بازگشت"]]))
    set_state(uid, set_card=True)

# ----------------------------
# «کانفیگ‌های من» و «آموزش»
# ----------------------------
def show_my_configs(uid: int):
    db = db_read()
    pur_ids = db["users"][str(uid)]["purchases"]
    if not pur_ids:
        bot.send_message(uid, "هنوز خریدی نداری.")
        return
    msg = "🗂 کانفیگ‌های من:\n"
    for pid in pur_ids[-20:][::-1]:
        p = db["purchases"][pid]
        plan = db["plans"].get(p["plan_id"], {}).get("name", p["plan_id"])
        msg += f"• {plan} — {fmt_toman(p['price'])} — {datetime.fromtimestamp(p['created_at']).strftime('%Y-%m-%d')}\n"
    bot.send_message(uid, msg)

def show_help(uid: int):
    db = db_read()
    bot.send_message(uid, db["texts"]["help"], parse_mode=None)

# ----------------------------
# هندل استیت‌های متنی
# ----------------------------
def handle_stateful(uid: int, m: types.Message, st: dict):
    txt = (m.text or "").strip()
    admin = is_admin(uid)

    # تیکت
    if st.get("ticket_mode") == "new_subject":
        subj = txt
        tid = str(uuid4())
        def mut(dbm):
            dbm["tickets"][tid] = {"uid": str(uid), "subject": subj, "status": "open",
                                   "msgs": [], "created_at": now_ts()}
            dbm["users"][str(uid)]["tickets"].append(tid)
        db_write(mut)
        bot.send_message(uid, "متن تیکت رو بنویس:", reply_markup=make_kb([["🔙 بازگشت"]]))
        set_state(uid, ticket_mode="new_body", ticket_id=tid)
        return
    if st.get("ticket_mode") == "new_body":
        tid = st.get("ticket_id")
        ticket_add(uid, txt, "user", tid)
        bot.send_message(uid, "ارسال شد ✅")
        clear_state(uid)
        return
    if st.get("ticket_mode") == "reply_body":
        tid = st.get("ticket_id")
        ticket_add(uid, txt, ("admin" if admin else "user"), tid)
        bot.send_message(uid, "ارسال شد ✅")
        clear_state(uid)
        return

    # افزودن پلن مرحله‌ای
    if st.get("add_plan_step") == "name":
        set_state(uid, add_plan_step="price", new_plan={"name": txt})
        bot.send_message(uid, "قیمت (تومان) را وارد کن:", reply_markup=make_kb([["🔙 بازگشت"]]))
        return
    if st.get("add_plan_step") == "price":
        amt = parse_amount(txt)
        if amt is None:
            bot.send_message(uid, "عدد نامعتبر. دوباره بفرست.")
            return
        np = st["new_plan"]; np["price"] = amt
        set_state(uid, add_plan_step="days", new_plan=np)
        bot.send_message(uid, "مدت (روز) را وارد کن:")
        return
    if st.get("add_plan_step") == "days":
        d = parse_amount(txt)
        if d is None:
            bot.send_message(uid, "عدد نامعتبر.")
            return
        np = st["new_plan"]; np["days"] = d
        set_state(uid, add_plan_step="traffic", new_plan=np)
        bot.send_message(uid, "حجم (GB) را وارد کن:")
        return
    if st.get("add_plan_step") == "traffic":
        g = parse_amount(txt)
        if g is None:
            bot.send_message(uid, "عدد نامعتبر.")
            return
        np = st["new_plan"]; np["traffic_gb"] = g
        set_state(uid, add_plan_step="desc", new_plan=np)
        bot.send_message(uid, "توضیحات پلن را بفرست:")
        return
    if st.get("add_plan_step") == "desc":
        np = st["new_plan"]; np["desc"] = txt; np["enabled"] = True
        pid = str(uuid4())
        def mut(dbm):
            dbm["plans"][pid] = np
            dbm["inventory"].setdefault(pid, [])
        db_write(mut)
        bot.send_message(uid, "پلن اضافه شد ✅", reply_markup=admin_kb())
        clear_state(uid)
        return

    # ویرایش پلن
    if st.get("edit_plan_step") == "menu":
        if txt == "✏️ نام":
            set_state(uid, edit_plan_step="name")
            bot.send_message(uid, "نام جدید:")
            return
        if txt == "✏️ قیمت":
            set_state(uid, edit_plan_step="price")
            bot.send_message(uid, "قیمت جدید (تومان):")
            return
        if txt == "✏️ مدت (روز)":
            set_state(uid, edit_plan_step="days")
            bot.send_message(uid, "مدت جدید (روز):")
            return
        if txt == "✏️ حجم (GB)":
            set_state(uid, edit_plan_step="traffic")
            bot.send_message(uid, "حجم جدید (GB):")
            return
        if txt == "✏️ توضیحات":
            set_state(uid, edit_plan_step="desc")
            bot.send_message(uid, "توضیحات جدید:")
            return
    if st.get("edit_plan_step") in ("name", "price", "days", "traffic", "desc"):
        pid = st.get("edit_plan_id")
        key = st["edit_plan_step"]
        val = txt
        if key in ("price", "days", "traffic"):
            nv = parse_amount(txt)
            if nv is None:
                bot.send_message(uid, "عدد نامعتبر.")
                return
            val = nv
        def mut(dbm):
            if key == "name": dbm["plans"][pid]["name"] = val
            if key == "price": dbm["plans"][pid]["price"] = val
            if key == "days": dbm["plans"][pid]["days"] = val
            if key == "traffic": dbm["plans"][pid]["traffic_gb"] = val
            if key == "desc": dbm["plans"][pid]["desc"] = val
        db_write(mut)
        bot.send_message(uid, "به‌روزرسانی شد ✅")
        clear_state(uid)
        return

    # مخزن: افزودن متن/تصویر
    if st.get("inv_step") == "add_text":
        pid = st.get("inv_plan_id")
        cfg_id = str(uuid4())
        def mut(dbm):
            dbm["inventory"].setdefault(pid, [])
            dbm["inventory"][pid].append({"id": cfg_id, "text": txt, "photo_id": None})
        db_write(mut)
        bot.send_message(uid, "افزوده شد ✅")
        clear_state(uid)
        return
    if st.get("inv_step") == "add_photo":
        if m.content_type != "photo":
            bot.send_message(uid, "لطفاً عکس بفرست.")
            return
        pid = st.get("inv_plan_id")
        ph = m.photo[-1].file_id
        cfg_id = str(uuid4())
        def mut(dbm):
            dbm["inventory"].setdefault(pid, [])
            dbm["inventory"][pid].append({"id": cfg_id, "text": None, "photo_id": ph})
        db_write(mut)
        bot.send_message(uid, "افزوده شد ✅")
        clear_state(uid)
        return

    # ساخت کوپن مرحله‌ای
    if st.get("coupon_flow") == "create" and st.get("coupon_step") == "percent":
        val = parse_amount(txt)
        if not val or val <= 0 or val >= 100:
            bot.send_message(uid, "درصد نامعتبر (1..99).")
            return
        set_state(uid, coupon_step="plan", coupon={"percent": int(val)})
        bot.send_message(uid, "آی‌دی پلن هدف را بفرست یا بنویس all برای همه پلن‌ها:")
        return
    if st.get("coupon_flow") == "create" and st.get("coupon_step") == "plan":
        plan_id_or_all = txt.strip()
        set_state(uid, coupon_step="max", coupon={**st["coupon"], "plan_id": plan_id_or_all})
        bot.send_message(uid, "سقف تعداد استفاده (مثلاً 10):")
        return
    if st.get("coupon_flow") == "create" and st.get("coupon_step") == "max":
        mx = parse_amount(txt)
        if not mx or mx < 1:
            bot.send_message(uid, "عدد نامعتبر.")
            return
        set_state(uid, coupon_step="code", coupon={**st["coupon"], "max_uses": int(mx)})
        bot.send_message(uid, "کد کوپن را بفرست (حروف/اعداد):")
        return
    if st.get("coupon_flow") == "create" and st.get("coupon_step") == "code":
        code = txt.strip()
        def mut(dbm):
            dbm["coupons"][code] = {"percent": st["coupon"]["percent"], "plan_id": st["coupon"]["plan_id"],
                                    "max_uses": st["coupon"]["max_uses"], "used": 0, "active": True}
        db_write(mut)
        bot.send_message(uid, "کوپن ساخته شد ✅", reply_markup=admin_kb())
        clear_state(uid)
        return

    # انتخاب رسید
    if st.get("receipt_mode") == "pick" and txt.startswith("#"):
        hashid = txt.split("—")[0].strip().lstrip("#")
        db = db_read()
        rid = next((k for k in db["receipts"].keys() if k.startswith(hashid)), None)
        if not rid:
            bot.send_message(uid, "رسید پیدا نشد.")
            return
        r = db["receipts"][rid]
        uname = db["users"].get(r["uid"], {}).get("username", "—")
        msg = (f"#{rid[:8]} — @{uname}({r['uid']})\n"
               f"نوع: {r['type']}\n"
               f"وضعیت: {r['status']}\n"
               f"مبلغ: {fmt_toman(r['amount']) if r.get('amount') else '—'}")
        rows = [["✅ تأیید", "❌ رد"], ["🔙 بازگشت"]]
        bot.send_message(uid, msg, reply_markup=make_kb(rows))
        set_state(uid, receipt_mode="act", receipt_id=rid)
        return
    if st.get("receipt_mode") == "act":
        rid = st.get("receipt_id")
        if txt == "✅ تأیید":
            # اگر نوع wallet و مبلغ ندارد، از ادمین مبلغ بگیر
            db = db_read()
            r = db["receipts"][rid]
            if r["type"] == "wallet" and not r.get("amount"):
                bot.send_message(uid, "مبلغ شارژ را وارد کن:", reply_markup=make_kb([["🔙 بازگشت"]]))
                set_state(uid, receipt_mode="enter_amount", receipt_id=rid)
                return
            approve_receipt(uid, rid, r.get("amount"))
            clear_state(uid)
            return
        if txt == "❌ رد":
            reject_receipt(uid, rid)
            clear_state(uid)
            return

    if st.get("receipt_mode") == "enter_amount":
        rid = st.get("receipt_id")
        amt = parse_amount(txt)
        if not amt:
            bot.send_message(uid, "مبلغ نامعتبر.")
            return
        approve_receipt(uid, rid, amt)
        clear_state(uid)
        return

    # ویرایش متن‌ها
    if st.get("edit_text_step") == "menu":
        if txt == "متن خوشامد":
            set_state(uid, edit_text_step="welcome")
            bot.send_message(uid, "متن جدید خوشامد را بفرست:")
            return
        if txt == "متن آموزش":
            set_state(uid, edit_text_step="help")
            bot.send_message(uid, "متن جدید آموزش را بفرست:")
            return
    if st.get("edit_text_step") in ("welcome", "help"):
        key = st["edit_text_step"]
        def mut(dbm):
            dbm["texts"][key] = txt
        db_write(mut)
        bot.send_message(uid, "ذخیره شد ✅")
        clear_state(uid)
        return

    # مدیریت دکمه‌ها
    if st.get("toggle_buttons"):
        label = txt.split(" ")[-1]
        map_key = {
            "پلن": "shop", "پول": "wallet", "تیکت": "tickets", "کانفیگ‌های": "my_configs", "آموزش": "help"
        }
        # یک‌کم انعطاف:
        for k, v in map_key.items():
            if k in txt:
                def mut(dbm):
                    dbm["buttons"][v] = not dbm["buttons"].get(v, True)
                db_write(mut)
                bot.send_message(uid, "به‌روزرسانی شد ✅")
                clear_state(uid)
                return

    # شماره کارت
    if st.get("set_card"):
        num = re.sub(r"[^\d-]", "", txt)
        def mut(dbm):
            dbm["texts"]["card_number"] = num
        db_write(mut)
        bot.send_message(uid, "شماره کارت ذخیره شد ✅")
        clear_state(uid)
        return

    # کیف پول ادمین: انتخاب کاربر/مبلغ
    if st.get("wallet_op") in ("inc_user", "dec_user") and not st.get("wallet_uid"):
        target = re.sub(r"[^\d]", "", txt)
        if not target:
            bot.send_message(uid, "آیدی نامعتبر.")
            return
        set_state(uid, wallet_uid=target)
        bot.send_message(uid, "مبلغ را وارد کن:")
        return
    if st.get("wallet_op") in ("inc_user", "dec_user") and st.get("wallet_uid"):
        amt = parse_amount(txt)
        if not amt or amt <= 0:
            bot.send_message(uid, "مبلغ نامعتبر.")
            return
        do_wallet_change(admin_id=uid, target_uid=st["wallet_uid"], delta=(amt if st["wallet_op"]=="inc_user" else -amt),
                         reason=("شارژ دستی" if st["wallet_op"]=="inc_user" else "کسر دستی"))
        bot.send_message(uid, "انجام شد ✅")
        clear_state(uid)
        return

    # کد تخفیف برای خرید
    if st.get("coupon_mode") == "enter":
        code = txt.strip()
        db = db_read()
        pid = st.get("plan_id")
        if code in db["coupons"]:
            c = db["coupons"][code]
            if c["active"] and (c["plan_id"] in ("all", pid)) and (c["used"] < c["max_uses"]):
                set_state(uid, coupon=code, coupon_mode=None)
                bot.send_message(uid, "کوپن اعمال شد ✅")
                show_payment_options(uid)
                return
        bot.send_message(uid, "کد نامعتبر یا منقضی شده.")
        return

    # اگر هیچ کدوم:
    bot.send_message(uid, "دستور نامعتبر. از منو استفاده کن.")

# ----------------------------
# رسید: تأیید/رد
# ----------------------------
def approve_receipt(admin_id: int, rid: str, amount: int):
    db = db_read()
    r = db["receipts"][rid]
    uid = int(r["uid"])

    if r["type"] == "wallet":
        do_wallet_change(admin_id=admin_id, target_uid=uid, delta=amount, reason=f"تأیید رسید #{rid[:6]}")
        msg_user = f"✅ رسید شارژ شما تأیید شد. مبلغ شارژ: {fmt_toman(amount)}\nتوسط ادمین: {admin_id}"
        bot.send_message(uid, msg_user)
    else:
        # خرید کانفیگ
        pid = r.get("plan_id")
        cfg_id, cfg_txt, cfg_photo = pop_inventory(pid)
        if not cfg_id:
            bot.send_message(admin_id, "مخزن خالی است؛ امکان تأیید نیست.")
            return
        # خرید و تحویل
        def mut(dbm):
            pid_buy = str(uuid4())
            price = r["amount"] or 0
            dbm["purchases"][pid_buy] = {"uid": str(uid), "plan_id": pid, "price": price,
                                         "coupon": r.get("coupon"), "delivered_cfg_id": cfg_id,
                                         "created_at": now_ts()}
            dbm["users"][str(uid)]["purchases"].append(pid_buy)
            # کوپن مصرف شد
            cp = r.get("coupon")
            if cp and cp in dbm["coupons"]:
                dbm["coupons"][cp]["used"] += 1
        db_write(mut)
        plan_name = db["plans"].get(pid, {}).get("name", pid)
        deliver_config(uid, cfg_txt, cfg_photo, plan_name)
        bot.send_message(uid, f"✅ رسید خرید شما تأیید شد. توسط ادمین: {admin_id}")

    # وضعیت رسید
    def mut2(dbm):
        dbm["receipts"][rid]["status"] = "approved"
        dbm["receipts"][rid]["admin_id"] = str(admin_id)
        if r["type"] == "wallet" and not dbm["receipts"][rid].get("amount"):
            dbm["receipts"][rid]["amount"] = amount
    db_write(mut2)

def reject_receipt(admin_id: int, rid: str):
    db = db_read()
    r = db["receipts"][rid]
    uid = int(r["uid"])
    def mut(dbm):
        dbm["receipts"][rid]["status"] = "rejected"
        dbm["receipts"][rid]["admin_id"] = str(admin_id)
    db_write(mut)
    bot.send_message(uid, f"❌ رسید شما رد شد. توسط ادمین: {admin_id}\nدر صورت ابهام، تیکت ثبت کنید.")

# ----------------------------
# تغییر موجودی با لاگ
# ----------------------------
def do_wallet_change(admin_id: int, target_uid, delta: int, reason: str):
    target_uid = str(target_uid)
    def mut(dbm):
        old = dbm["users"].setdefault(target_uid, {"wallet": 0, "tickets": [], "purchases": [], "username": ""})["wallet"]
        new = max(old + delta, 0)
        dbm["users"][target_uid]["wallet"] = new
        dbm["wallet_logs"].append({"uid": target_uid, "admin_id": str(admin_id),
                                   "delta": delta, "old": old, "new": new,
                                   "reason": reason, "ts": now_ts()})
    db_write(mut)

# ----------------------------
# خرید با کوپن: نمایش دوباره گزینه‌ها بعد از اعمال
# ----------------------------
@bot.message_handler(func=lambda m: m.text == "🔙 بازگشت")
def on_back(m: types.Message):
    uid = m.from_user.id
    admin = is_admin(uid)
    clear_state(uid)
    send_welcome(uid, is_admin_user=admin)

# ----------------------------
# راه‌اندازی
# ----------------------------
if __name__ == "__main__":
    # فقط یکبار وبهوک ست می‌کنیم
    try:
        set_webhook_once()
    except Exception as e:
        print("Error setting webhook:", e)

    # اپ WSGI برای گانیکورن
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
