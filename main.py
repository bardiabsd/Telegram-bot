# -*- coding: utf-8 -*-
import os
import json
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort
import telebot
from telebot import types

# -----------------------------
# تنظیمات اصلی (Koyeb-friendly)
# -----------------------------

# اگر متغیر محیطی نبود، از مقادیر کاربر استفاده می‌کنیم
BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
)
APP_URL = os.getenv(
    "APP_URL",
    "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"
)

# ادمین پیش‌فرض (در صورت نبود DB)
DEFAULT_ADMINS = {1743359080}

# کارت مقصد (ادمین در پنل می‌تواند تغییر دهد)
DEFAULT_CARD = "6037-9972-1234-5678"

# فایل دیتابیس سبک (JSON)
DB_PATH = "db.json"

# -----------------------------
# ابزارک‌های دیتابیس ساده
# -----------------------------

def _now_ts():
    return int(time.time())

def _load_db():
    if not os.path.exists(DB_PATH):
        return {
            "admins": list(DEFAULT_ADMINS),
            "card_number": DEFAULT_CARD,
            "users": {},        # user_id -> profile {username, wallet, buys, tickets, joined}
            "plans": {},        # plan_id -> {name, days, traffic, price, desc, stock: [items]}
            "coupons": {},      # code -> {percent, only_plan_id or None, expire_ts or None, max_uses or None, used:0}
            "receipts": {},     # receipt_id -> {...}
            "sales": [],        # list of sales records
            "texts": {          # قابل ویرایش توسط ادمین
                "welcome": "سلام! خوش اومدی 🌟\nاز منوی زیر انتخاب کن.",
                "kb_main_title": "منوی اصلی",
                "btn_buy": "🛒 خرید پلن",
                "btn_wallet": "🪙 کیف پول",
                "btn_tickets": "🎫 پشتیبانی",
                "btn_account": "👤 حساب کاربری",
                "btn_admin": "🛠 پنل ادمین",
                "btn_cancel": "❌ انصراف",
            },
            "toggles": {
                "buy": True,
                "wallet": True,
                "tickets": True,
                "account": True,
                "admin": True,
            }
        }
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_db(db):
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)

def get_user(db, uid, username=None):
    u = db["users"].get(str(uid))
    if not u:
        u = {
            "id": uid,
            "username": username or "",
            "wallet": 0,
            "buys": [],
            "tickets": [],
            "joined": _now_ts(),
            "state": {}  # state machine per user
        }
        db["users"][str(uid)] = u
    else:
        if username and u.get("username") != username:
            u["username"] = username
    return u

def set_state(uobj, **kw):
    st = uobj.get("state") or {}
    for k, v in kw.items():
        if v is None:
            st.pop(k, None)
        else:
            st[k] = v
    uobj["state"] = st

def clear_state(uobj):
    uobj["state"] = {}

def is_admin(db, uid):
    return uid in set(db.get("admins", []))

def next_id(prefix):
    return f"{prefix}_{int(time.time()*1000)}"

# -----------------------------
# تلگرام و وبهوک
# -----------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, parse_mode="HTML")
app = Flask(__name__)

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}"

@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        update = request.get_json()
        bot.process_new_updates([telebot.types.Update.de_json(update)])
        return "OK", 200
    else:
        abort(403)

# set webhook (تلاش اولیه + خطای 429 لاگ می‌شود)
def set_webhook_once():
    try:
        info = bot.get_webhook_info()
        if info and info.url == WEBHOOK_URL:
            print(f"{datetime.utcnow()} | INFO | Webhook already set: {WEBHOOK_URL}")
            return
    except Exception as e:
        print(f"{datetime.utcnow()} | WARN | get_webhook_info failed: {e}")
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"{datetime.utcnow()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print(f"{datetime.utcnow()} | ERROR | set_webhook failed: {e}")

# -----------------------------
# کیبوردها
# -----------------------------
def kb_main(db):
    t = db["texts"]
    tg = db["toggles"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    rows = []
    if tg.get("buy"): rows.append(types.KeyboardButton(t["btn_buy"]))
    if tg.get("wallet"): rows.append(types.KeyboardButton(t["btn_wallet"]))
    if tg.get("tickets"): rows.append(types.KeyboardButton(t["btn_tickets"]))
    if tg.get("account"): rows.append(types.KeyboardButton(t["btn_account"]))
    if tg.get("admin"): rows.append(types.KeyboardButton(t["btn_admin"]))
    kb.add(*rows)
    return kb

def kb_cancel(db):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton(db["texts"]["btn_cancel"]))
    return kb

def ik_cancel(db):
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton(db["texts"]["btn_cancel"], callback_data="cancel"))
    return ik

# -----------------------------
# منوی اصلی و استارت
# -----------------------------
@bot.message_handler(commands=["start"])
def cmd_start(m):
    db = _load_db()
    u = get_user(db, m.from_user.id, m.from_user.username)
    _save_db(db)
    bot.send_message(
        m.chat.id,
        db["texts"]["welcome"],
        reply_markup=kb_main(db)
    )

# -----------------------------
# خرید پلن (نمای پایه)
# -----------------------------
def human_price(p):
    return f"{p:,} تومان"

def plans_inline(db):
    ik = types.InlineKeyboardMarkup()
    for pid, p in db["plans"].items():
        stock = len(p.get("stock", []))
        title = f"{p['name']} • {human_price(p['price'])} • موجودی {stock}"
        ik.add(types.InlineKeyboardButton(title, callback_data=f"plan:{pid}"))
    if not db["plans"]:
        ik.add(types.InlineKeyboardButton("فعلاً پلنی موجود نیست", callback_data="noop"))
    ik.add(types.InlineKeyboardButton("انصراف", callback_data="cancel"))
    return ik

def show_plan_detail(db, chat_id, pid, uid):
    p = db["plans"].get(pid)
    if not p:
        bot.send_message(chat_id, "پلن نامعتبر است.", reply_markup=kb_main(db))
        return
    stock = len(p.get("stock", []))
    txt = (
        f"<b>{p['name']}</b>\n"
        f"مدت: {p['days']} روز\n"
        f"حجم: {p['traffic']}\n"
        f"قیمت: {human_price(p['price'])}\n"
        f"موجودی مخزن: {stock}\n\n"
        f"توضیحات: {p.get('desc','-')}"
    )
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("اعمال کد تخفیف", callback_data=f"buy:coupon:{pid}"),
        types.InlineKeyboardButton("کارت‌به‌کارت", callback_data=f"buy:bank:{pid}")
    )
    ik.add(types.InlineKeyboardButton("پرداخت با کیف پول", callback_data=f"buy:wallet:{pid}"))
    ik.add(types.InlineKeyboardButton("انصراف", callback_data="cancel"))
    bot.send_message(chat_id, txt, reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan:"))
def cb_plan(c):
    db = _load_db()
    uid = c.from_user.id
    show_plan_detail(db, c.message.chat.id, c.data.split(":",1)[1], uid)

@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(c):
    bot.answer_callback_query(c.id, "—")

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    clear_state(u)
    _save_db(db)
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
    bot.send_message(c.message.chat.id, "لغو شد ✅", reply_markup=kb_main(db))

# اعمال کد تخفیف
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:coupon:"))
def cb_buy_coupon(c):
    db = _load_db()
    uid = c.from_user.id
    pid = c.data.split(":")[-1]
    u = get_user(db, uid, c.from_user.username)
    set_state(u, flow="buy", step="coupon_code", plan_id=pid)
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "کد تخفیف را وارد کنید (یا «انصراف»):", reply_markup=kb_cancel(db))

# پرداخت کیف پول
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:wallet:"))
def cb_buy_wallet(c):
    db = _load_db()
    uid = c.from_user.id
    pid = c.data.split(":")[-1]
    u = get_user(db, uid, c.from_user.username)
    p = db["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن نامعتبر.")
        return
    # بررسی موجودی مخزن
    if not p.get("stock"):
        bot.answer_callback_query(c.id, "موجودی این پلن تمام است.")
        return
    price = p["price"]
    # اگر قبلاً کوپن روی state بوده، اعمال می‌کنیم
    coupon_code = u["state"].get("coupon_code")
    final = price
    if coupon_code and coupon_code in db["coupons"]:
        cp = db["coupons"][coupon_code]
        # بررسی محدودیت‌ها
        ok = True
        if cp.get("only_plan_id") and cp["only_plan_id"] != pid:
            ok = False
        if cp.get("expire_ts") and _now_ts() > cp["expire_ts"]:
            ok = False
        if cp.get("max_uses") and cp.get("used", 0) >= cp["max_uses"]:
            ok = False
        if ok:
            final = max(0, price - (price * int(cp["percent"]) // 100))
        else:
            coupon_code = None
    # پرداخت از کیف پول
    if u["wallet"] < final:
        diff = final - u["wallet"]
        msg = (
            f"موجودی کیف پول شما کافی نیست.\n"
            f"مبلغ نهایی: {human_price(final)}\n"
            f"موجودی فعلی: {human_price(u['wallet'])}\n"
            f"مابه‌التفاوت: {human_price(diff)}\n"
            "می‌خواهید همین مقدار را شارژ کنید؟"
        )
        ik = types.InlineKeyboardMarkup()
        ik.add(
            types.InlineKeyboardButton("شارژ همین مقدار", callback_data=f"wallet:charge_diff:{diff}:{pid}"),
            types.InlineKeyboardButton("انصراف", callback_data="cancel"),
        )
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, msg, reply_markup=ik)
        return

    # انجام خرید
    u["wallet"] -= final
    conf = p["stock"].pop(0)  # برداشتن یک کانفیگ
    sale = {
        "id": next_id("sale"),
        "uid": uid,
        "pid": pid,
        "price": price,
        "final": final,
        "coupon": coupon_code or "",
        "ts": _now_ts()
    }
    db["sales"].append(sale)
    u["buys"].append(sale["id"])
    # اعمال شمارنده‌ی کوپن
    if coupon_code and coupon_code in db["coupons"]:
        db["coupons"][coupon_code]["used"] = db["coupons"][coupon_code].get("used", 0) + 1
    _save_db(db)

    # ارسال کانفیگ (متن/عکس قابل پشتیبانی در نسخه‌های بعد)
    txt = f"خرید شما با موفقیت انجام شد ✅\n\n{conf}"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt, reply_markup=kb_main(db))

@bot.callback_query_handler(func=lambda c: c.data.startswith("wallet:charge_diff:"))
def cb_wallet_charge_diff(c):
    db = _load_db()
    uid = c.from_user.id
    parts = c.data.split(":")
    # wallet:charge_diff:<amount>:<pid>
    amount = int(parts[2])
    pid = parts[3]
    card = db.get("card_number", DEFAULT_CARD)
    u = get_user(db, uid, c.from_user.username)
    # قرار دادن state برای بارگذاری رسید
    set_state(u, flow="wallet", step="upload_receipt_diff", amount=amount, buy_after=pid)
    _save_db(db)

    msg = (
        "برای تکمیل خرید، لطفاً مابه‌التفاوت را کارت‌به‌کارت کنید:\n\n"
        f"💳 شماره کارت: <code>{card}</code>\n"
        "📝 سپس «رسید» را همین‌جا ارسال کنید.\n\n"
        "یا «انصراف» را بزنید."
    )
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, msg, reply_markup=kb_cancel(db))

# بانک (کارت به کارت مستقیم بدون کیف پول)
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:bank:"))
def cb_buy_bank(c):
    db = _load_db()
    uid = c.from_user.id
    pid = c.data.split(":")[-1]
    u = get_user(db, uid, c.from_user.username)
    card = db.get("card_number", DEFAULT_CARD)

    # اگر کوپن در state ثبت شده، بعد از رسید تایید اعمال می‌شود
    set_state(u, flow="bank", step="upload_receipt", plan_id=pid)
    _save_db(db)

    msg = (
        "برای خرید این پلن، مبلغ آن را کارت‌به‌کارت کنید:\n\n"
        f"💳 شماره کارت: <code>{card}</code>\n"
        "📝 سپس «رسید» را همین‌جا ارسال کنید.\n\n"
        "یا «انصراف» را بزنید."
    )
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, msg, reply_markup=kb_cancel(db))

# -----------------------------
# کیف پول (نمای پایه)
# -----------------------------
@bot.message_handler(func=lambda m: True)
def on_message(m):
    text = (m.text or "").strip()
    db = _load_db()
    u = get_user(db, m.from_user.id, m.from_user.username)
    st = u.get("state", {})
    isadm = is_admin(db, u["id"])

    # هندل مراحل ورودی آزاد (state-based)
    if text == db["texts"]["btn_cancel"] or text == "/cancel":
        clear_state(u)
        _save_db(db)
        bot.send_message(m.chat.id, "لغو شد ✅", reply_markup=kb_main(db))
        return

    # --- مراحل آزاد: ورود کد تخفیف
    if st.get("flow") == "buy" and st.get("step") == "coupon_code":
        code = text.replace(" ", "")
        pid = st.get("plan_id")
        u["state"]["coupon_code"] = code
        # بعد از ثبت کد، جزئیات پلن را دوباره نشان بده
        clear_state(u)
        _save_db(db)
        bot.send_message(m.chat.id, "کد تخفیف ثبت شد ✅")
        show_plan_detail(db, m.chat.id, pid, u["id"])
        return

    # --- مراحل آزاد: آپلود رسید (مابه‌التفاوت)
    if st.get("flow") == "wallet" and st.get("step") == "upload_receipt_diff":
        # کاربر باید عکس یا پیام رسید بده—ما هر نوع محتوا را می‌پذیریم و برای ادمین ثبت می‌کنیم
        rid = next_id("rcp")
        db["receipts"][rid] = {
            "id": rid,
            "uid": u["id"],
            "username": u.get("username", ""),
            "type": "charge_diff",
            "amount": st.get("amount", 0),
            "plan_id": st.get("buy_after"),
            "status": "pending",
            "note": "wallet_diff",
            "ts": _now_ts(),
            "message_id": m.message_id
        }
        clear_state(u)
        _save_db(db)
        bot.send_message(m.chat.id, "رسید شما ثبت شد؛ منتظر تأیید ادمین… ✅", reply_markup=kb_main(db))
        notify_admins_new_receipt(db, rid)
        return

    # --- مراحل آزاد: آپلود رسید خرید بانکی
    if st.get("flow") == "bank" and st.get("step") == "upload_receipt":
        rid = next_id("rcp")
        pid = st.get("plan_id")
        db["receipts"][rid] = {
            "id": rid,
            "uid": u["id"],
            "username": u.get("username", ""),
            "type": "buy_bank",
            "amount": None,  # ادمین وارد می‌کند
            "plan_id": pid,
            "status": "pending",
            "note": "buy_bank",
            "ts": _now_ts(),
            "message_id": m.message_id
        }
        clear_state(u)
        _save_db(db)
        bot.send_message(m.chat.id, "رسید شما ثبت شد؛ منتظر تأیید ادمین… ✅", reply_markup=kb_main(db))
        notify_admins_new_receipt(db, rid)
        return

    # --- مراحل آزاد: مراحل پنل ادمین
    if isadm:
        # افزودن ادمین با آی‌دی عددی
        if st.get("flow") == "admin_add" and st.get("step") == "ask_id":
            if not text.isdigit():
                bot.send_message(m.chat.id, "لطفاً آیدی عددی معتبر وارد کنید یا «انصراف».", reply_markup=kb_cancel(db))
                return
            new_id = int(text)
            admins = set(db.get("admins", []))
            admins.add(new_id)
            db["admins"] = list(admins)
            clear_state(u)
            _save_db(db)
            bot.send_message(m.chat.id, f"✅ ادمین با آیدی <code>{new_id}</code> اضافه شد.", reply_markup=kb_main(db))
            try:
                bot.send_message(new_id, "🎉 شما به عنوان ادمین اضافه شدید.")
            except:
                pass
            return

        # حذف ادمین
        if st.get("flow") == "admin_del" and st.get("step") == "ask_id":
            if not text.isdigit():
                bot.send_message(m.chat.id, "لطفاً آیدی عددی معتبر وارد کنید یا «انصراف».", reply_markup=kb_cancel(db))
                return
            del_id = int(text)
            admins = set(db.get("admins", []))
            if del_id in admins:
                admins.remove(del_id)
                db["admins"] = list(admins)
                clear_state(u)
                _save_db(db)
                bot.send_message(m.chat.id, f"🗑 ادمین <code>{del_id}</code> حذف شد.", reply_markup=kb_main(db))
                try:
                    bot.send_message(del_id, "⛔️ دسترسی ادمین شما لغو شد.")
                except:
                    pass
            else:
                bot.send_message(m.chat.id, "کاربری با این آیدی در لیست ادمین نیست.", reply_markup=kb_cancel(db))
            return

        # تغییر شماره کارت
        if st.get("flow") == "set_card" and st.get("step") == "ask_card":
            if len(text.replace("-", "").replace(" ", "")) < 16:
                bot.send_message(m.chat.id, "شماره کارت معتبر وارد کنید یا «انصراف».", reply_markup=kb_cancel(db))
                return
            db["card_number"] = text.strip()
            clear_state(u)
            _save_db(db)
            bot.send_message(m.chat.id, f"✅ شماره کارت ثبت شد:\n<code>{db['card_number']}</code>", reply_markup=kb_main(db))
            return

        # اعلان همگانی
        if st.get("flow") == "broadcast" and st.get("step") == "ask_text":
            msg = text
            clear_state(u)
            _save_db(db)
            sent, failed = 0, 0
            for k, usr in db["users"].items():
                try:
                    bot.send_message(usr["id"], msg)
                    sent += 1
                except:
                    failed += 1
            bot.send_message(m.chat.id, f"📣 ارسال شد.\nموفق: {sent}\nناموفق: {failed}", reply_markup=kb_main(db))
            return

        # ساخت کوپن: درصد
        if st.get("flow") == "coupon" and st.get("step") == "ask_percent":
            if not text.isdigit():
                bot.send_message(m.chat.id, "درصد را به‌صورت عدد وارد کنید یا «انصراف».", reply_markup=kb_cancel(db))
                return
            set_state(u, step="ask_plan_limit", coupon={"percent": int(text)})
            _save_db(db)
            bot.send_message(m.chat.id, "آیا کوپن محدود به پلن خاص باشد؟\n(آیدی پلن را بفرستید یا بنویسید «همه»)", reply_markup=kb_cancel(db))
            return

        # ساخت کوپن: محدودیت پلن
        if st.get("flow") == "coupon" and st.get("step") == "ask_plan_limit":
            cp = u["state"].get("coupon", {})
            plan_id = None
            if text != "همه":
                plan_id = text
            cp["only_plan_id"] = plan_id
            set_state(u, step="ask_expire", coupon=cp)
            _save_db(db)
            bot.send_message(m.chat.id, "تاریخ انقضا؟\nمثال: 2025-12-31 یا بنویس «بدون»", reply_markup=kb_cancel(db))
            return

        # ساخت کوپن: تاریخ
        if st.get("flow") == "coupon" and st.get("step") == "ask_expire":
            cp = u["state"].get("coupon", {})
            expire_ts = None
            if text != "بدون":
                try:
                    dt = datetime.strptime(text, "%Y-%m-%d")
                    expire_ts = int(dt.timestamp())
                except:
                    bot.send_message(m.chat.id, "فرمت تاریخ نامعتبر است. مثال: 2025-12-31", reply_markup=kb_cancel(db))
                    return
            cp["expire_ts"] = expire_ts
            set_state(u, step="ask_max_uses", coupon=cp)
            _save_db(db)
            bot.send_message(m.chat.id, "سقف تعداد استفاده؟ (عدد یا «بدون»)", reply_markup=kb_cancel(db))
            return

        # ساخت کوپن: سقف استفاده
        if st.get("flow") == "coupon" and st.get("step") == "ask_max_uses":
            cp = u["state"].get("coupon", {})
            max_uses = None
            if text != "بدون":
                if not text.isdigit():
                    bot.send_message(m.chat.id, "عدد معتبر وارد کنید یا «بدون».", reply_markup=kb_cancel(db))
                    return
                max_uses = int(text)
            cp["max_uses"] = max_uses
            set_state(u, step="ask_code", coupon=cp)
            _save_db(db)
            bot.send_message(m.chat.id, "نام/کد کوپن را بفرستید:", reply_markup=kb_cancel(db))
            return

        # ساخت کوپن: کد
        if st.get("flow") == "coupon" and st.get("step") == "ask_code":
            code = text.strip()
            if not code:
                bot.send_message(m.chat.id, "کد معتبر وارد کنید یا «انصراف».", reply_markup=kb_cancel(db))
                return
            cp = u["state"].get("coupon", {})
            cp["used"] = 0
            db["coupons"][code] = cp
            clear_state(u)
            _save_db(db)
            bot.send_message(m.chat.id, f"✅ کوپن «{code}» ساخته شد.", reply_markup=kb_main(db))
            return

        # آمار فروش پایه
        if st.get("flow") == "stats" and st.get("step") == "show":
            # هیچ ورودی لازم نیست؛ ورود متن یعنی بازگشت
            clear_state(u)
            _save_db(db)
            bot.send_message(m.chat.id, "بازگشت به منوی اصلی.", reply_markup=kb_main(db))
            return

    # -----------------------------
    # دکمه‌های منوی اصلی
    # -----------------------------
    t = db["texts"]
    if text == t["btn_buy"]:
        bot.send_message(m.chat.id, "لطفاً پلن را انتخاب کنید:", reply_markup=types.ReplyKeyboardRemove())
        bot.send_message(m.chat.id, "لیست پلن‌ها:", reply_markup=plans_inline(db))
        return

    if text == t["btn_wallet"]:
        # نمایش منوی کیف پول
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("شارژ کیف پول (ارسال رسید)", callback_data="wallet:charge"),
        )
        bot.send_message(m.chat.id, f"موجودی فعلی شما: {human_price(u['wallet'])}", reply_markup=kb)
        return

    if text == t["btn_tickets"]:
        # تیکت پایه
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("ایجاد تیکت جدید", callback_data="ticket:new"),
            types.InlineKeyboardButton("تیکت‌های من", callback_data="ticket:list"),
        )
        bot.send_message(m.chat.id, "پشتیبانی:", reply_markup=kb)
        return

    if text == t["btn_account"]:
        count = len(u["buys"])
        bot.send_message(
            m.chat.id,
            f"👤 آیدی: <code>{u['id']}</code>\n"
            f"یوزرنیم: @{u['username']}\n"
            f"تعداد کانفیگ‌های خریداری‌شده: {count}\n"
            f"موجودی کیف پول: {human_price(u['wallet'])}",
            reply_markup=kb_main(db)
        )
        return

    if text == t["btn_admin"] and isadm:
        show_admin_menu(db, m.chat.id)
        return

    # اگر به هیچ‌کدام نخورد و state آزاد هم نبود:
    bot.send_message(m.chat.id, "از دکمه‌ها استفاده کنید یا «انصراف/بازگشت».", reply_markup=kb_main(db))

# -----------------------------
# کیف پول: شارژ با رسید
# -----------------------------
@bot.callback_query_handler(func=lambda c: c.data == "wallet:charge")
def cb_wallet_charge(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="wallet", step="upload_receipt_wallet")
    _save_db(db)
    card = db.get("card_number", DEFAULT_CARD)
    msg = (
        "برای شارژ کیف پول، مبلغ مورد نظر را کارت‌به‌کارت کنید:\n\n"
        f"💳 شماره کارت: <code>{card}</code>\n"
        "📝 سپس «رسید» را همین‌جا ارسال کنید.\n\n"
        "یا «انصراف» را بزنید."
    )
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, msg, reply_markup=kb_cancel(db))

# پیام رسید کیف پول
@bot.message_handler(content_types=["photo", "document", "text"])
def on_any_message(m):
    # این هندلر پایین‌تر از on_message تعریف شده؛ فقط وقتی به آن نخورَد می‌آید
    db = _load_db()
    u = get_user(db, m.from_user.id, m.from_user.username)
    st = u.get("state", {})

    # رسید شارژ کیف پول
    if st.get("flow") == "wallet" and st.get("step") == "upload_receipt_wallet":
        rid = next_id("rcp")
        db["receipts"][rid] = {
            "id": rid,
            "uid": u["id"],
            "username": u.get("username", ""),
            "type": "wallet_charge",
            "amount": None,  # ادمین وارد می‌کند
            "plan_id": None,
            "status": "pending",
            "note": "wallet_charge",
            "ts": _now_ts(),
            "message_id": m.message_id
        }
        clear_state(u)
        _save_db(db)
        bot.send_message(m.chat.id, "رسید شما ثبت شد؛ منتظر تأیید ادمین… ✅", reply_markup=kb_main(db))
        notify_admins_new_receipt(db, rid)
        return

    # تیکت جدید: دریافت متن
    if st.get("flow") == "ticket" and st.get("step") == "ask_text":
        txt = (m.text or "").strip()
        if not txt:
            bot.send_message(m.chat.id, "لطفاً متن تیکت را بنویسید یا «انصراف».", reply_markup=kb_cancel(db))
            return
        tid = next_id("tkt")
        ticket = {
            "id": tid,
            "uid": u["id"],
            "subject": st.get("subject", "بدون موضوع"),
            "messages": [
                {"from": "user", "text": txt, "ts": _now_ts()}
            ],
            "status": "open",
            "ts": _now_ts()
        }
        u["tickets"].append(tid)
        # در DB در سطح root ذخیره کنیم
        db.setdefault("tickets", {})[tid] = ticket
        clear_state(u)
        _save_db(db)
        bot.send_message(m.chat.id, "تیکت ساخته شد ✅", reply_markup=kb_main(db))
        notify_admins_new_ticket(db, ticket)
        return

    # اگر اینجا رسید، یعنی state آزاد نبود؛ پاس بده به on_message که قبلاً هندل شده
    # (عملاً کاری لازم نیست بکنیم)
    return

# -----------------------------
# تیکت‌ها
# -----------------------------
@bot.callback_query_handler(func=lambda c: c.data == "ticket:new")
def cb_ticket_new(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="ticket", step="ask_subject")
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "موضوع تیکت را انتخاب کنید:", reply_markup=ticket_subjects())

def ticket_subjects():
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("مشکل خرید", callback_data="ticket:sub:buy"),
        types.InlineKeyboardButton("مشکل کانفیگ", callback_data="ticket:sub:config"),
    )
    ik.add(types.InlineKeyboardButton("انصراف", callback_data="cancel"))
    return ik

@bot.callback_query_handler(func=lambda c: c.data.startswith("ticket:sub:"))
def cb_ticket_sub(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    subject = c.data.split(":")[-1]
    set_state(u, flow="ticket", step="ask_text", subject=subject)
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "متن تیکت را بنویسید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data == "ticket:list")
def cb_ticket_list(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    tickets = [db.get("tickets", {}).get(tid) for tid in u.get("tickets", [])]
    tickets = [t for t in tickets if t]
    if not tickets:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "هیچ تیکتی ندارید.", reply_markup=kb_main(db))
        return
    msg = "تیکت‌های شما:\n\n"
    for t in tickets:
        msg += f"#{t['id']} | وضعیت: {t['status']} | موضوع: {t['subject']}\n"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, msg, reply_markup=kb_main(db))

# -----------------------------
# اعلانات برای ادمین‌ها
# -----------------------------
def notify_admins_new_receipt(db, rid):
    admins = set(db.get("admins", []))
    r = db["receipts"][rid]
    cap = (
        f"🧾 رسید جدید\n"
        f"نوع: {r['type']}\n"
        f"کاربر: @{r.get('username','') or '-'} ({r['uid']})\n"
        f"رسید: {rid}\n"
        f"وضعیت: {r['status']}"
    )
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("تأیید و ورود مبلغ", callback_data=f"adm:rcp:approve:{rid}"),
        types.InlineKeyboardButton("رد رسید", callback_data=f"adm:rcp:reject:{rid}"),
    )
    for aid in admins:
        try:
            bot.send_message(aid, cap, reply_markup=ik)
        except:
            pass

def notify_admins_new_ticket(db, ticket):
    admins = set(db.get("admins", []))
    cap = (
        f"🎫 تیکت جدید\n"
        f"کاربر: @{db['users'][str(ticket['uid'])].get('username','') or '-'} ({ticket['uid']})\n"
        f"#{ticket['id']} | موضوع: {ticket['subject']}"
    )
    for aid in admins:
        try:
            bot.send_message(aid, cap)
        except:
            pass

# -----------------------------
# پنل ادمین (پایه)
# -----------------------------
def show_admin_menu(db, chat_id):
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("👑 مدیریت ادمین‌ها", callback_data="adm:admins"),
        types.InlineKeyboardButton("💳 شماره کارت", callback_data="adm:card"),
    )
    ik.add(
        types.InlineKeyboardButton("🧾 رسیدهای در انتظار", callback_data="adm:receipts"),
        types.InlineKeyboardButton("🏷 ساخت کد تخفیف", callback_data="adm:coupon"),
    )
    ik.add(
        types.InlineKeyboardButton("📦 پلن‌ها/مخزن (نمای پایه)", callback_data="adm:plans"),
        types.InlineKeyboardButton("📣 اعلان همگانی", callback_data="adm:broadcast"),
    )
    ik.add(
        types.InlineKeyboardButton("📊 آمار فروش", callback_data="adm:stats"),
        types.InlineKeyboardButton("بازگشت", callback_data="cancel"),
    )
    bot.send_message(chat_id, "🛠 پنل ادمین:", reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data == "adm:admins")
def cb_adm_admins(c):
    db = _load_db()
    uid = c.from_user.id
    if not is_admin(db, uid): return
    admins = db.get("admins", [])
    txt = "ادمین‌ها:\n" + "\n".join([f"- <code>{a}</code>" for a in admins]) if admins else "ادمین ثبت نشده."
    ik = types.InlineKeyboardMarkup()
    ik.add(
        types.InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm:admins:add"),
        types.InlineKeyboardButton("🗑 حذف ادمین", callback_data="adm:admins:del"),
    )
    ik.add(types.InlineKeyboardButton("بازگشت", callback_data="cancel"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt, reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data == "adm:admins:add")
def cb_adm_admins_add(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    if not is_admin(db, u["id"]): return
    set_state(u, flow="admin_add", step="ask_id")
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "آیدی عددی ادمین جدید را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data == "adm:admins:del")
def cb_adm_admins_del(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    if not is_admin(db, u["id"]): return
    set_state(u, flow="admin_del", step="ask_id")
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "آیدی عددی ادمین مورد نظر برای حذف را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data == "adm:card")
def cb_adm_card(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    if not is_admin(db, u["id"]): return
    set_state(u, flow="set_card", step="ask_card")
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "شماره کارت جدید را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data == "adm:receipts")
def cb_adm_receipts(c):
    db = _load_db()
    if not is_admin(db, c.from_user.id): return
    pend = [r for r in db["receipts"].values() if r["status"] == "pending"]
    if not pend:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "رسید در انتظاری وجود ندارد.")
        return
    for r in pend:
        cap = (
            f"🧾 رسید در انتظار\n"
            f"#{r['id']} | نوع: {r['type']}\n"
            f"کاربر: @{r.get('username','') or '-'} ({r['uid']})\n"
            f"پیام: {r.get('message_id','-')}"
        )
        ik = types.InlineKeyboardMarkup()
        ik.add(
            types.InlineKeyboardButton("تأیید و ورود مبلغ", callback_data=f"adm:rcp:approve:{r['id']}"),
            types.InlineKeyboardButton("رد رسید", callback_data=f"adm:rcp:reject:{r['id']}"),
        )
        bot.send_message(c.message.chat.id, cap, reply_markup=ik)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:rcp:approve:"))
def cb_adm_rcp_approve(c):
    db = _load_db()
    if not is_admin(db, c.from_user.id): return
    rid = c.data.split(":")[-1]
    r = db["receipts"].get(rid)
    if not r:
        bot.answer_callback_query(c.id, "یافت نشد.")
        return
    # درخواست مبلغ
    r["status"] = "await_amount"
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"مبلغ نهایی برای رسید #{rid} را وارد کنید (به تومان):", reply_markup=kb_cancel(db))
    # ثبت state برای ادمینی که دارد وارد می‌کند
    u = get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="rcp_amount", step="ask_amount", rid=rid)
    _save_db(db)

@bot.message_handler(func=lambda m: True)
def on_message_admin_rcp_amount(m):
    # این هندلر پایین‌دستی است و روی همه پیام‌ها می‌آید؛ اما ما فقط اگر state مربوط باشد عمل می‌کنیم
    db = _load_db()
    u = get_user(db, m.from_user.id, m.from_user.username)
    st = u.get("state", {})
    if st.get("flow") == "rcp_amount" and st.get("step") == "ask_amount":
        rid = st.get("rid")
        if not rid or rid not in db["receipts"]:
            clear_state(u); _save_db(db)
            bot.send_message(m.chat.id, "رسید یافت نشد.", reply_markup=kb_main(db))
            return
        val = (m.text or "").strip().replace(",", "")
        if not val.isdigit():
            bot.send_message(m.chat.id, "لطفاً عدد معتبر وارد کنید یا «انصراف».", reply_markup=kb_cancel(db))
            return
        amount = int(val)
        r = db["receipts"][rid]
        r["amount"] = amount
        # اعمال اثر رسید
        if r["type"] == "wallet_charge":
            usr = get_user(db, r["uid"])
            usr["wallet"] += amount
            r["status"] = "approved"
            # اطلاع به کاربر
            try:
                bot.send_message(r["uid"], f"✅ رسید شما تأیید شد. کیف پول به میزان {human_price(amount)} شارژ شد.")
            except:
                pass

        elif r["type"] == "charge_diff":
            # فقط شارژ می‌کنیم، سپس ادمین باید خرید را دستی تکمیل کند یا ساده بگیریم: همان لحظه خرید تکمیل شود اگر plan_id موجود و stock>0
            usr = get_user(db, r["uid"])
            usr["wallet"] += amount
            r["status"] = "approved"
            # تلاش برای خرید خودکار
            pid = r.get("plan_id")
            if pid and pid in db["plans"] and db["plans"][pid].get("stock"):
                price = db["plans"][pid]["price"]
                if usr["wallet"] >= price:
                    usr["wallet"] -= price
                    conf = db["plans"][pid]["stock"].pop(0)
                    sale = {
                        "id": next_id("sale"),
                        "uid": usr["id"],
                        "pid": pid,
                        "price": price,
                        "final": price,
                        "coupon": "",
                        "ts": _now_ts()
                    }
                    db["sales"].append(sale)
                    usr["buys"].append(sale["id"])
                    try:
                        bot.send_message(usr["id"], f"✅ خرید شما تکمیل شد.\n{conf}")
                    except:
                        pass
        elif r["type"] == "buy_bank":
            # خرید از روی رسید بانک: نیاز به plan_id
            pid = r.get("plan_id")
            if not pid or pid not in db["plans"] or not db["plans"][pid].get("stock"):
                r["status"] = "approved"
                try:
                    bot.send_message(r["uid"], "✅ رسید شما تأیید شد. اما موجودی پلن کافی نبود؛ با پشتیبانی در تماس باشید.")
                except:
                    pass
            else:
                p = db["plans"][pid]
                price = p["price"]
                conf = p["stock"].pop(0)
                sale = {
                    "id": next_id("sale"),
                    "uid": r["uid"],
                    "pid": pid,
                    "price": price,
                    "final": price,
                    "coupon": "",
                    "ts": _now_ts()
                }
                db["sales"].append(sale)
                get_user(db, r["uid"])["buys"].append(sale["id"])
                r["status"] = "approved"
                try:
                    bot.send_message(r["uid"], f"✅ خرید شما تأیید شد و کانفیگ ارسال گردید.\n{conf}")
                except:
                    pass
        _save_db(db)
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, "✅ ثبت شد.", reply_markup=kb_main(db))
        return

# رد رسید
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:rcp:reject:"))
def cb_adm_rcp_reject(c):
    db = _load_db()
    if not is_admin(db, c.from_user.id): return
    rid = c.data.split(":")[-1]
    r = db["receipts"].get(rid)
    if not r:
        bot.answer_callback_query(c.id, "یافت نشد.")
        return
    r["status"] = "rejected"
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "رسید رد شد.")
    try:
        bot.send_message(r["uid"], "❌ رسید شما رد شد. در صورت ابهام با پشتیبانی در تماس باشید.")
    except:
        pass

# ساخت کوپن
@bot.callback_query_handler(func=lambda c: c.data == "adm:coupon")
def cb_adm_coupon(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    if not is_admin(db, u["id"]): return
    set_state(u, flow="coupon", step="ask_percent")
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "درصد تخفیف را (عدد ۰ تا ۱۰۰) بفرستید:", reply_markup=kb_cancel(db))

# اعلان همگانی
@bot.callback_query_handler(func=lambda c: c.data == "adm:broadcast")
def cb_adm_broadcast(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    if not is_admin(db, u["id"]): return
    set_state(u, flow="broadcast", step="ask_text")
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "متن اعلان همگانی را بفرستید:", reply_markup=kb_cancel(db))

# آمار فروش پایه
@bot.callback_query_handler(func=lambda c: c.data == "adm:stats")
def cb_adm_stats(c):
    db = _load_db()
    if not is_admin(db, c.from_user.id): return
    # محاسبه ساده
    total_count = len(db["sales"])
    total_sum = sum([s["final"] for s in db["sales"]])
    # Top buyers
    spend = {}
    for s in db["sales"]:
        spend[s["uid"]] = spend.get(s["uid"], 0) + s["final"]
    top = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:5]
    lines = [f"📊 آمار فروش",
             f"تعداد فروش: {total_count}",
             f"مجموع فروش: {human_price(total_sum)}",
             "Top Buyers:"]
    for uid, amt in top:
        un = db["users"].get(str(uid), {}).get("username", "")
        lines.append(f"- @{un or '-'} ({uid}): {human_price(amt)}")
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "\n".join(lines), reply_markup=kb_main(db))

# پلن‌ها/مخزن (نمای پایه - فهرست)
@bot.callback_query_handler(func=lambda c: c.data == "adm:plans")
def cb_adm_plans(c):
    db = _load_db()
    if not is_admin(db, c.from_user.id): return
    if not db["plans"]:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "فعلاً پلنی ثبت نشده.", reply_markup=kb_main(db))
        return
    msg = "📦 پلن‌ها:\n"
    for pid, p in db["plans"].items():
        msg += f"- {pid} | {p['name']} | قیمت {human_price(p['price'])} | موجودی {len(p.get('stock', []))}\n"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, msg, reply_markup=kb_main(db))

# -----------------------------
# هندل انتخاب پلن از منوی خرید
# -----------------------------
@bot.message_handler(func=lambda m: True)
def on_fallback(m):
    # این هندلر آخرین است و اگر قبلی‌ها return نکرده باشند می‌آید
    pass

# -----------------------------
# شروع اپ
# -----------------------------
if __name__ == "__main__":
    set_webhook_once()
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
