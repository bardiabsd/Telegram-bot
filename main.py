# -*- coding: utf-8 -*-
import os, json, time, threading, re, uuid, datetime
from flask import Flask, request, abort
import telebot
from telebot import types

# ===================== CONFIG =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "YOUR_TOKEN_HERE"
APP_URL   = os.environ.get("APP_URL")   or "https://your-app.koyeb.app"
PORT      = int(os.environ.get("PORT", "8000"))

if not BOT_TOKEN or "YOUR_TOKEN_HERE" in BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in environment variables!")

WEBHOOK_URL = f"{APP_URL}/webhook/{BOT_TOKEN}"

# Default Admin(s)
DEFAULT_ADMINS = [1743359080]  # <- شما

DB_FILE = "db.json"

# ===================== BOT/APP =====================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ===================== DB HELPERS =====================
def now_ts():
    return int(time.time())

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def load_db():
    if not os.path.exists(DB_FILE):
        db = {
            "admins": DEFAULT_ADMINS[:],
            "users": {},             # uid -> {wallet:int, username:str,...}
            "states": {},            # uid -> {step:str, payload:{}}
            "plans": {},             # plan_id -> {..., stock:[{text,img}]}
            "orders": [],            # [{uid, plan_id, price, delivered:[], at}]
            "receipts": [],          # [{id, uid, kind, amount, status, admin_id, at, note, plan_id}]
            "coupons": {},           # code -> {percent, max_uses, used, allowed_plans, expires}
            "ui": {                  # dynamic texts/buttons and toggles
                "buttons": {
                    "shop": "🛍 خرید پلن",
                    "wallet": "🪙 کیف پول",
                    "tickets": "🎫 تیکت پشتیبانی",
                    "my_configs": "📦 کانفیگ‌های من",
                    "help": "📘 آموزش ربات",
                    "admin": "🛠 پنل ادمین"
                },
                "texts": {
                    "welcome": "سلام! خوش اومدی 👋\nاز منوی زیر یکی رو انتخاب کن:",
                    "card_number": "💳 شماره کارت:\n<b>6221-xxxx-xxxx-xxxx</b>\nرسید کارت‌به‌کارت رو همینجا ارسال کن.\n\n⬅️ برای انصراف روی «انصراف» بزن.",
                    "wallet_rules": "برای شارژ کیف پول رسید رو بفرست و نوع اقدام رو انتخاب کن.",
                    "tutorial": (
                        "📘 آموزش ربات قدم‌به‌قدم\n\n"
                        "🛍 <b>خرید پلن</b>:\n- پلن رو انتخاب کن\n- اگه کد تخفیف داری، اعمال کن\n- روش پرداخت: «کیف پول» یا «کارت‌به‌کارت»\n"
                        "🪙 <b>کیف پول</b>:\n- شارژ یا خرید از موجودی\n- تاریخچه تراکنش‌ها رو می‌تونی ببینی\n"
                        "🎫 <b>تیکت پشتیبانی</b>:\n- تیکت جدید بساز و پیام بده\n- پاسخ ادمین داخل همون ترد میاد\n"
                        "📦 <b>کانفیگ‌های من</b>:\n- همه کانفیگ‌های تحویل‌شده اینجاست\n"
                        "ℹ️ مشکلی داشتی از تیکت کمک بگیر 🌟"
                    )
                },
                "toggles": { # enable/disable top-level buttons
                    "shop": True, "wallet": True, "tickets": True, "my_configs": True, "help": True, "admin": True
                }
            },
            "wallet_logs": [],   # [{id, uid, delta, before, after, admin_id, reason, at}]
            "admin_chat": [],    # [{id, admin_id, username, text, at}]
        }
        save_db(db)
        return db
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

db_lock = threading.Lock()
def db_read():
    with db_lock:
        return load_db()

def db_write(newdb):
    with db_lock:
        save_db(newdb)

# ===================== STATE HELPERS =====================
def get_user(uid):
    db = db_read()
    u = db["users"].get(str(uid))
    return u

def ensure_user(message):
    uid = message.from_user.id
    uname = message.from_user.username or ""
    db = db_read()
    if str(uid) not in db["users"]:
        db["users"][str(uid)] = {"wallet": 0, "username": uname, "created_at": now_str()}
    else:
        db["users"][str(uid)]["username"] = uname
    db_write(db)

def is_admin(uid):
    db = db_read()
    return uid in db["admins"]

def get_state(uid):
    db = db_read()
    return db["states"].get(str(uid), {})

def set_state(uid, step=None, **payload):
    db = db_read()
    cur = db["states"].get(str(uid), {})
    if step is not None:
        cur["step"] = step
    if payload:
        cur.update(payload)
    db["states"][str(uid)] = cur
    db_write(db)

def clear_state(uid):
    db = db_read()
    if str(uid) in db["states"]:
        db["states"].pop(str(uid))
        db_write(db)

# ===================== KEYBOARDS =====================
def main_menu(uid):
    d = db_read()
    tgl = d["ui"]["toggles"]; btn = d["ui"]["buttons"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    if tgl.get("shop"):        row.append(types.KeyboardButton(btn["shop"]))
    if tgl.get("wallet"):      row.append(types.KeyboardButton(btn["wallet"]))
    if row: kb.row(*row)
    row = []
    if tgl.get("tickets"):     row.append(types.KeyboardButton(btn["tickets"]))
    if tgl.get("my_configs"):  row.append(types.KeyboardButton(btn["my_configs"]))
    if row: kb.row(*row)
    row = []
    if tgl.get("help"):        row.append(types.KeyboardButton(btn["help"]))
    if is_admin(uid) and tgl.get("admin"): row.append(types.KeyboardButton(btn["admin"]))
    if row: kb.row(*row)
    return kb

def back_cancel_row():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel"))
    return kb

def bool_btn(val): return "✅ روشن" if val else "❌ خاموش"

# ===================== WEBHOOK =====================
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return ""
    abort(403)

@app.route("/", methods=["GET"])
def index():
    return "OK", 200

def set_webhook_once():
    try:
        bot.delete_webhook()
        time.sleep(0.3)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"{now_str()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print(f"{now_str()} | ERROR | Failed to set webhook: {e}")

# ===================== UTIL =====================
def price_after_coupon(plan_price, coupon):
    if not coupon: return plan_price
    try:
        percent = int(coupon.get("percent", 0))
    except:
        percent = 0
    percent = max(0, min(90, percent))
    off = (plan_price * percent) // 100
    return max(0, plan_price - off)

def admin_broadcast(text):
    d = db_read()
    for aid in d["admins"]:
        try: bot.send_message(aid, text)
        except: pass

def find_plan(plan_id):
    d = db_read()
    return d["plans"].get(plan_id)

def push_wallet_log(uid, delta, before, after, admin_id, reason):
    d = db_read()
    d["wallet_logs"].append({
        "id": str(uuid.uuid4()),
        "uid": uid, "delta": int(delta), "before": int(before), "after": int(after),
        "admin_id": admin_id, "reason": reason, "at": now_str()
    })
    db_write(d)

def plan_inline_list():
    d = db_read()
    kb = types.InlineKeyboardMarkup()
    if not d["plans"]:
        kb.add(types.InlineKeyboardButton("فعلاً پلنی ثبت نشده ❗️", callback_data="noop"))
        kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel"))
        return kb
    for pid, p in d["plans"].items():
        stock = len(p.get("stock", []))
        title = f"{p.get('name', 'بدون‌نام')} ({stock})"
        kb.add(types.InlineKeyboardButton(title, callback_data=f"plan_{pid}"))
    kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel"))
    return kb

# ===================== START / MENU =====================
@bot.message_handler(commands=["start"])
def on_start(message):
    ensure_user(message)
    d = db_read()
    uid = message.from_user.id
    bot.send_message(uid, d["ui"]["texts"]["welcome"], reply_markup=main_menu(uid))

@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(message):
    ensure_user(message)
    uid = message.from_user.id
    txt = (message.text or "").strip()
    d = db_read()
    btn = d["ui"]["buttons"]

    st = get_state(uid)
    step = st.get("step")

    # ====== active steps (ticket, coupon, etc.)
    if step:
        return step_router(message, step, st)

    # ====== main menu
    if txt == btn["shop"]:
        return show_plans(uid)
    if txt == btn["wallet"]:
        return wallet_menu(uid)
    if txt == btn["tickets"]:
        return tickets_menu(uid)
    if txt == btn["my_configs"]:
        return my_configs(uid)
    if txt == btn["help"]:
        return bot.send_message(uid, d["ui"]["texts"]["tutorial"], reply_markup=main_menu(uid))
    if txt == btn["admin"] and is_admin(uid):
        return admin_menu(uid)

    # fallback
    return bot.send_message(uid, "از منوی زیر انتخاب کن ⬇️", reply_markup=main_menu(uid))

# ===================== SHOP / PLANS =====================
def show_plans(uid):
    d = db_read()
    kb = types.InlineKeyboardMarkup()
    for pid, p in d["plans"].items():
        stock = len(p.get("stock", []))
        title = f"{p.get('name','بی‌نام')} • {p.get('duration','?')}روز • {p.get('volume','?')}GB • {p.get('price',0)} تومان • موجودی:{stock}"
        disabled = (stock == 0)
        data = f"buy_{pid}" if not disabled else "noop"
        kb.add(types.InlineKeyboardButton(("❌ " if disabled else "🛒 ")+title, callback_data=data))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "🛍 پلن‌ها:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_") or c.data=="cancel" or c.data.startswith("noop"))
def cb_shop(c):
    uid = c.from_user.id
    if c.data == "cancel":
        clear_state(uid)
        bot.answer_callback_query(c.id, "لغو شد")
        return bot.edit_message_text("لغو شد ✅", c.message.chat.id, c.message.message_id, reply_markup=None)
    if c.data.startswith("noop"):
        return bot.answer_callback_query(c.id, "در دسترس نیست")
    if c.data.startswith("buy_"):
        pid = c.data.split("_",1)[1]
        d = db_read()
        p = d["plans"].get(pid)
        if not p:
            bot.answer_callback_query(c.id, "پلن یافت نشد")
            return
        price = int(p.get("price",0))
        set_state(uid, step="buy_plan", plan_id=pid, coupon_code=None)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🎟 اعمال کد تخفیف", callback_data="apply_coupon"))
        kb.add(types.InlineKeyboardButton("❌ حذف کد تخفیف", callback_data="remove_coupon"))
        kb.add(types.InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data="pay_cc"))
        kb.add(types.InlineKeyboardButton("🪙 پرداخت با کیف پول", callback_data="pay_wallet"))
        kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel"))
        text = (
            f"نام پلن: <b>{p.get('name')}</b>\n"
            f"مدت: {p.get('duration','?')} روز | حجم: {p.get('volume','?')}GB\n"
            f"قیمت: <b>{price}</b> تومان\n"
            "می‌تونی کد تخفیف بزنی یا روش پرداخت رو انتخاب کنی."
        )
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)
        bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data in ["apply_coupon","remove_coupon","pay_cc","pay_wallet"])
def cb_buy_flow(c):
    uid = c.from_user.id
    st = get_state(uid)
    if st.get("step") != "buy_plan":
        return bot.answer_callback_query(c.id, "سشن خرید معتبر نیست")

    d = db_read()
    pid = st.get("plan_id")
    p = d["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن یافت نشد")
        return

    if c.data == "apply_coupon":
        set_state(uid, step="enter_coupon", plan_id=pid)
        bot.answer_callback_query(c.id)
        return bot.send_message(uid, "کد تخفیف رو ارسال کن:", reply_markup=back_cancel_row())

    if c.data == "remove_coupon":
        set_state(uid, step="buy_plan", plan_id=pid, coupon_code=None)
        bot.answer_callback_query(c.id, "کد تخفیف حذف شد")
        # رفرش کارت
        refresh_buy_card(uid, c.message)
        return

    if c.data == "pay_cc":
        # کارت‌به‌کارت
        set_state(uid, step="await_receipt", kind="purchase", plan_id=pid)
        bot.answer_callback_query(c.id)
        text = db_read()["ui"]["texts"]["card_number"]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel_receipt"))
        return bot.send_message(uid, text, reply_markup=kb)

    if c.data == "pay_wallet":
        # پرداخت کیف پول
        final = current_final_price(uid, p)
        u = get_user(uid)
        if u["wallet"] < final:
            diff = final - u["wallet"]
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(f"🔼 شارژ همین مقدار ({diff})", callback_data=f"wallet_topup_{diff}"))
            kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel"))
            bot.answer_callback_query(c.id)
            return bot.send_message(uid, f"موجودی کافی نیست. مابه‌التفاوت: <b>{diff}</b> تومان", reply_markup=kb)
        # کسر و ارسال
        do_wallet_purchase(uid, p, final, approver="کیف پول")
        bot.answer_callback_query(c.id)

def refresh_buy_card(uid, msg):
    d = db_read()
    st = get_state(uid)
    pid = st.get("plan_id")
    p = d["plans"].get(pid)
    base = int(p.get("price",0))
    coupon_code = st.get("coupon_code")
    coupon_obj = d["coupons"].get((coupon_code or "").upper())
    final = price_after_coupon(base, coupon_obj)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎟 اعمال کد تخفیف", callback_data="apply_coupon"))
    kb.add(types.InlineKeyboardButton("❌ حذف کد تخفیف", callback_data="remove_coupon"))
    kb.add(types.InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data="pay_cc"))
    kb.add(types.InlineKeyboardButton("🪙 پرداخت با کیف پول", callback_data="pay_wallet"))
    kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel"))
    text = (
        f"نام پلن: <b>{p.get('name')}</b>\n"
        f"مدت: {p.get('duration','?')} روز | حجم: {p.get('volume','?')}GB\n"
        f"قیمت پایه: {base} تومان\n"
        f"کد تخفیف: <b>{coupon_code or '—'}</b>\n"
        f"مبلغ نهایی: <b>{final}</b> تومان"
    )
    try:
        bot.edit_message_text(text, msg.chat.id, msg.message_id, reply_markup=kb)
    except:
        bot.send_message(uid, text, reply_markup=kb)

def current_final_price(uid, plan):
    d = db_read()
    st = get_state(uid)
    base = int(plan.get("price",0))
    code = (st.get("coupon_code") or "").upper()
    cp = d["coupons"].get(code)
    if not cp: return base
    # محدودیت‌ها
    if cp.get("expires") and now_ts() > int(cp["expires"]):
        return base
    if cp.get("max_uses", 0) and int(cp.get("used",0)) >= int(cp["max_uses"]):
        return base
    allowed = cp.get("allowed_plans")
    if allowed and plan.get("id") not in allowed:
        return base
    return price_after_coupon(base, cp)

def do_wallet_purchase(uid, plan, final, approver=""):
    d = db_read()
    u = d["users"].get(str(uid))
    before = u["wallet"]
    u["wallet"] -= final
    after = u["wallet"]
    push_wallet_log(uid, -final, before, after, 0, f"خرید پلن {plan.get('name')}")
    # ارسال کانفیگ
    cfg = pop_plan_stock(plan["id"])
    order = {
        "id": str(uuid.uuid4()), "uid": uid, "plan_id": plan["id"],
        "price": final, "delivered": cfg and [cfg] or [],
        "at": now_str()
    }
    d["orders"].append(order)
    db_write(d)
    send_config_to_user(uid, plan, cfg)
    clear_state(uid)
    bot.send_message(uid, f"✅ خرید از کیف پول با موفقیت انجام شد. مبلغ کسر شده: <b>{final}</b> تومان")

def pop_plan_stock(plan_id):
    d = db_read()
    p = d["plans"].get(plan_id)
    if not p: return None
    st = p.get("stock", [])
    if not st: return None
    item = st.pop(0)
    db_write(d)
    return item

def send_config_to_user(uid, plan, cfg):
    if not cfg:
        bot.send_message(uid, "❗️متأسفانه موجودی این پلن صفر شد. لطفاً به پشتیبانی پیام بدهید.")
        admin_broadcast(f"⚠️ موجودی پلن {plan.get('name')} تمام شد.")
        return
    text = cfg.get("text")
    img  = cfg.get("img")
    cap = f"🚀 کانفیگ پلن <b>{plan.get('name')}</b>\nاعتبار: {plan.get('duration','?')} روز"
    try:
        if img:
            bot.send_photo(uid, img, caption=(text or cap))
        else:
            bot.send_message(uid, (text or cap))
    except:
        bot.send_message(uid, (text or cap))

# ===================== COUPONS =====================
def apply_coupon_code(uid, code, plan_id):
    d = db_read()
    code_u = (code or "").upper()
    cp = d["coupons"].get(code_u)
    if not cp:
        return (False, "کد تخفیف نامعتبره.")
    # تاریخ انقضا
    if cp.get("expires") and now_ts() > int(cp["expires"]):
        return (False, "مهلت استفاده از این کد گذشته.")
    # محدودیت استفاده
    if cp.get("max_uses",0) and int(cp.get("used",0)) >= int(cp["max_uses"]):
        return (False, "تعداد دفعات مجاز استفاده از این کد به پایان رسیده.")
    # محدودیت پلن
    allowed = cp.get("allowed_plans")
    if allowed and plan_id not in allowed:
        return (False, "این کد برای این پلن معتبر نیست.")
    # OK
    st = get_state(uid)
    set_state(uid, step="buy_plan", plan_id=plan_id, coupon_code=code_u)
    return (True, "کد تخفیف با موفقیت اعمال شد ✅")

def increase_coupon_used(code):
    d = db_read()
    if code and code in d["coupons"]:
        d["coupons"][code]["used"] = int(d["coupons"][code].get("used",0)) + 1
        db_write(d)

# ===================== WALLET / RECEIPTS =====================
def wallet_menu(uid):
    u = get_user(uid)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_charge"))
    kb.add(types.InlineKeyboardButton("🧾 تاریخچه تراکنش‌ها", callback_data="wallet_history"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, f"🪙 موجودی فعلی: <b>{u['wallet']}</b> تومان", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["wallet_charge","wallet_history","cancel_receipt"])
def cb_wallet(c):
    uid = c.from_user.id
    if c.data=="wallet_charge":
        set_state(uid, step="await_receipt", kind="wallet")
        bot.answer_callback_query(c.id)
        text = db_read()["ui"]["texts"]["card_number"] + "\n\nنوع اقدام: شارژ کیف پول"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ انصراف", callback_data="cancel"))
        bot.send_message(uid, text, reply_markup=kb)
    elif c.data=="wallet_history":
        show_wallet_history(uid)
        bot.answer_callback_query(c.id)
    elif c.data=="cancel_receipt":
        clear_state(uid)
        bot.answer_callback_query(c.id, "لغو شد")
        try: bot.edit_message_text("لغو شد ✅", c.message.chat.id, c.message.message_id)
        except: pass

def show_wallet_history(uid):
    d = db_read()
    logs = [x for x in d["wallet_logs"] if x["uid"]==uid]
    if not logs:
        return bot.send_message(uid, "هنوز تراکنشی ثبت نشده.")
    lines=[]
    for x in sorted(logs, key=lambda z:z["at"], reverse=True)[:20]:
        sign = "➕" if x["delta"]>0 else "➖"
        who = f" (by admin {x.get('admin_id')})" if x.get("admin_id") else ""
        lines.append(f"{x['at']} | {sign}{abs(x['delta'])} | پس از تغییر: {x['after']}{who}\n— {x.get('reason','')}")
    bot.send_message(uid, "🧾 آخرین تراکنش‌ها:\n\n" + "\n\n".join(lines))

# کاربر رسید می‌فرستد
@bot.message_handler(content_types=["photo","document"], func=lambda m: True)
def on_receipt(message):
    st = get_state(message.from_user.id)
    if st.get("step") != "await_receipt": return
    uid = message.from_user.id
    d = db_read()
    kind = st.get("kind")  # "purchase" | "wallet"
    plan_id = st.get("plan_id")
    amount = st.get("expected")  # اختیاری
    file_id = None

    if message.content_type == "photo":
        file_id = message.photo[-1].file_id
    elif message.content_type == "document":
        file_id = message.document.file_id

    rec = {
        "id": str(uuid.uuid4()),
        "uid": uid,
        "kind": kind,
        "amount": amount or 0,
        "status": "pending",
        "file_id": file_id,
        "plan_id": plan_id,
        "admin_id": None,
        "note": "",
        "at": now_str()
    }
    d["receipts"].append(rec)
    db_write(d)
    clear_state(uid)

    bot.reply_to(message, "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین…")
    # به همه ادمین‌ها بفرست
    text = f"🧾 رسید جدید\nنوع: {('خرید کانفیگ' if kind=='purchase' else 'شارژ کیف پول')}\nکاربر: <code>{uid}</code>\nزمان: {rec['at']}\nID: {rec['id']}"
    for aid in d["admins"]:
        try:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅ تأیید", callback_data=f"rc_ok_{rec['id']}"),
                types.InlineKeyboardButton("❌ رد", callback_data=f"rc_no_{rec['id']}")
            )
            if file_id:
                bot.send_photo(aid, file_id, caption=text, reply_markup=kb)
            else:
                bot.send_message(aid, text, reply_markup=kb)
        except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("rc_ok_") or c.data.startswith("rc_no_"))
def cb_receipt_admin(c):
    uid = c.from_user.id
    if not is_admin(uid):
        return bot.answer_callback_query(c.id,"ادمین نیستی")
    d = db_read()
    rid = c.data.split("_",2)[2]
    rec = next((x for x in d["receipts"] if x["id"]==rid), None)
    if not rec:
        return bot.answer_callback_query(c.id, "رسید یافت نشد")
    if rec["status"]!="pending":
        return bot.answer_callback_query(c.id, "این رسید بررسی شده")

    rec["admin_id"] = uid
    if c.data.startswith("rc_ok_"):
        rec["status"]="approved"
        # اگر خرید کانفیگ: ارسال کانفیگ
        if rec["kind"]=="purchase":
            plan = d["plans"].get(rec["plan_id"])
            if plan:
                cfg = pop_plan_stock(plan["id"])
                order = {
                    "id": str(uuid.uuid4()), "uid": rec["uid"], "plan_id": plan["id"],
                    "price": int(plan.get("price",0)), "delivered": cfg and [cfg] or [], "at": now_str()
                }
                d["orders"].append(order)
                db_write(d)
                send_config_to_user(rec["uid"], plan, cfg)
        else:
            # شارژ کیف پول: از ادمین مقدار می‌گیریم
            set_state(uid, step="enter_wallet_amount_for_receipt", receipt_id=rid)
            db_write(d)
            bot.answer_callback_query(c.id, "مبلغ شارژ رو بفرست (فقط عدد)")
            return bot.send_message(uid, f"💰 مبلغ شارژ برای رسید {rid}؟", reply_markup=back_cancel_row())
        db_write(d)
        bot.answer_callback_query(c.id, "تأیید شد")
        bot.edit_message_caption(caption=c.message.caption+"\n\n✔️ تأیید شد", chat_id=c.message.chat.id, message_id=c.message.message_id) if c.message.caption else None
        try:
            admin_tag = f"@{get_user(uid).get('username','')}" if get_user(uid) else f"{uid}"
            bot.send_message(rec["uid"], f"✅ رسید شما توسط {admin_tag} تأیید شد.")
        except: pass

    else:
        rec["status"]="rejected"
        db_write(d)
        bot.answer_callback_query(c.id, "رد شد")
        if c.message.caption:
            try: bot.edit_message_caption(caption=c.message.caption+"\n\n❌ رد شد", chat_id=c.message.chat.id, message_id=c.message.message_id)
            except: pass
        try:
            admin_tag = f"@{get_user(uid).get('username','')}" if get_user(uid) else f"{uid}"
            bot.send_message(rec["uid"], f"❌ رسید شما توسط {admin_tag} رد شد. اگر فکر می‌کنید اشتباهه، از تیکت کمک بگیرید.")
        except: pass

# مبلغ شارژ کیف پول برای تأیید رسید
def handle_amount_for_receipt(message, st):
    admin_id = message.from_user.id
    val = re.sub(r"[^\d]", "", message.text or "")
    if not val:
        return bot.send_message(admin_id, "مبلغ نامعتبره. فقط عدد بفرست.", reply_markup=back_cancel_row())
    amount = int(val)
    d = db_read()
    rid = st.get("receipt_id")
    rec = next((x for x in d["receipts"] if x["id"]==rid), None)
    if not rec:
        clear_state(admin_id)
        return bot.send_message(admin_id, "رسید پیدا نشد.")
    u = d["users"].get(str(rec["uid"]))
    before = u["wallet"]; u["wallet"] += amount; after = u["wallet"]
    push_wallet_log(rec["uid"], amount, before, after, admin_id, f"شارژ توسط تأیید رسید {rid}")
    db_write(d)
    clear_state(admin_id)
    admin_tag = f"@{get_user(admin_id).get('username','')}" if get_user(admin_id) else f"{admin_id}"
    bot.send_message(admin_id, f"✅ {amount} تومان به کیف پول کاربر {rec['uid']} افزوده شد.")
    try:
        bot.send_message(rec["uid"], f"💰 کیف پولت {amount} تومان شارژ شد (توسط {admin_tag}).")
    except: pass

# ===================== TICKETS =====================
def tickets_menu(uid):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🆕 ایجاد تیکت", callback_data="tk_new"))
    kb.add(types.InlineKeyboardButton("📂 تیکت‌های من", callback_data="tk_list"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "🎫 تیکت پشتیبانی:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["tk_new","tk_list"])
def cb_tickets(c):
    uid = c.from_user.id
    if c.data=="tk_new":
        set_state(uid, step="ticket_new_subject")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "موضوع تیکت رو بنویس:", reply_markup=back_cancel_row())
    elif c.data=="tk_list":
        show_my_tickets(uid)
        bot.answer_callback_query(c.id)

def show_my_tickets(uid):
    d = db_read()
    my = [t for t in d.get("tickets",[]) if t["uid"]==uid]
    if not my:
        return bot.send_message(uid, "هنوز تیکتی نداری.")
    kb = types.InlineKeyboardMarkup()
    for t in sorted(my, key=lambda x:x["at"], reverse=True)[:20]:
        kb.add(types.InlineKeyboardButton(f"{'🟢' if t['status']=='open' else '⚪️'} {t['subject']}", callback_data=f"tk_view_{t['id']}"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "📂 تیکت‌ها:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tk_view_"))
def cb_ticket_view(c):
    uid = c.from_user.id
    d = db_read()
    tid = c.data.split("_",2)[2]
    t = next((x for x in d.get("tickets",[]) if x["id"]==tid), None)
    if not t: return bot.answer_callback_query(c.id, "تیکت یافت نشد")
    if t["uid"]!=uid and not is_admin(uid): 
        return bot.answer_callback_query(c.id,"اجازه دسترسی نداری")
    kb = types.InlineKeyboardMarkup()
    if t["status"]=="open":
        kb.add(types.InlineKeyboardButton("✍️ پاسخ در همین تیکت", callback_data=f"tk_reply_{tid}"))
        if is_admin(uid):
            kb.add(types.InlineKeyboardButton("🔒 بستن", callback_data=f"tk_close_{tid}"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    msgs = "\n".join([f"👤 {m['by']} | {m['at']}\n{m['text']}" for m in t.get("messages",[])])
    bot.answer_callback_query(c.id)
    bot.send_message(uid, f"موضوع: <b>{t['subject']}</b>\nوضعیت: {t['status']}\n\n{msgs or '—'}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tk_reply_") or c.data.startswith("tk_close_"))
def cb_ticket_action(c):
    uid = c.from_user.id
    d = db_read()
    action, tid = c.data.split("_",1)[0], c.data.split("_",2)[2]
    t = next((x for x in d.get("tickets",[]) if x["id"]==tid), None)
    if not t:
        return bot.answer_callback_query(c.id,"تیکت یافت نشد")
    if action=="tk_reply":
        set_state(uid, step="ticket_reply", ticket_id=tid)
        bot.answer_callback_query(c.id)
        return bot.send_message(uid, "متن پاسخ رو بفرست:", reply_markup=back_cancel_row())
    if action=="tk_close":
        if not is_admin(uid): return bot.answer_callback_query(c.id,"ادمین نیستی")
        t["status"]="closed"; db_write(d)
        bot.answer_callback_query(c.id, "بسته شد")
        try:
            bot.send_message(t["uid"], f"🔒 تیکت «{t['subject']}» توسط ادمین بسته شد.")
        except: pass

def add_ticket(uid, subject, text):
    d = db_read()
    if "tickets" not in d: d["tickets"]=[]
    t = {
        "id": str(uuid.uuid4()), "uid": uid, "subject": subject.strip()[:100],
        "status": "open", "messages": [{"by":"user","text":text.strip(), "at": now_str()}],
        "at": now_str()
    }
    d["tickets"].append(t); db_write(d)
    # اطلاع به ادمین‌ها
    for aid in d["admins"]:
        try:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("مشاهده", callback_data=f"tk_view_{t['id']}"))
            bot.send_message(aid, f"🎫 تیکت جدید از {uid}\nموضوع: {t['subject']}", reply_markup=kb)
        except: pass

def add_ticket_reply(uid, tid, text, by="user"):
    d = db_read()
    t = next((x for x in d.get("tickets",[]) if x["id"]==tid), None)
    if not t: return False
    t["messages"].append({"by": by, "text": text.strip(), "at": now_str()})
    db_write(d)
    # نوتیف
    if by=="admin":
        try: bot.send_message(t["uid"], f"📩 پاسخ جدید به تیکت «{t['subject']}»:\n{text}")
        except: pass
    return True

# ===================== MY CONFIGS =====================
def my_configs(uid):
    d = db_read()
    my = [o for o in d["orders"] if o["uid"]==uid]
    if not my:
        return bot.send_message(uid, "📦 هنوز کانفیگی دریافت نکردی.")
    lines=[]
    for o in sorted(my, key=lambda z:z["at"], reverse=True)[:20]:
        p = d["plans"].get(o["plan_id"], {})
        lines.append(f"• {p.get('name','(پلن ناموجود)')} | {o['price']} تومان | {o['at']}")
    bot.send_message(uid, "📦 کانفیگ‌های من:\n\n"+"\n".join(lines))

# ===================== ADMIN PANEL =====================
def admin_menu(uid):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("👤 مدیریت ادمین‌ها", callback_data="adm_admins"))
    kb.add(types.InlineKeyboardButton("📦 مدیریت پلن‌ها/مخزن", callback_data="adm_plans"))
    kb.add(types.InlineKeyboardButton("🏷 کد تخفیف", callback_data="adm_coupon"))
    kb.add(types.InlineKeyboardButton("🪙 کیف پول (تأیید رسید/دستی)", callback_data="adm_wallet"))
    kb.add(types.InlineKeyboardButton("📢 اعلان همگانی", callback_data="adm_broadcast"))
    kb.add(types.InlineKeyboardButton("🧾 رسیدهای جدید", callback_data="adm_receipts"))
    kb.add(types.InlineKeyboardButton("🧮 آمار فروش", callback_data="adm_stats"))
    kb.add(types.InlineKeyboardButton("🗂 لاگ موجودی", callback_data="adm_wallet_logs"))
    kb.add(types.InlineKeyboardButton("💬 چت ادمین‌ها", callback_data="adm_chat"))
    kb.add(types.InlineKeyboardButton("🔧 دکمه‌ها و متون", callback_data="adm_ui"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "🛠 پنل ادمین:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_"))
def cb_admin(c):
    uid = c.from_user.id
    if not is_admin(uid): return bot.answer_callback_query(c.id,"ادمین نیستی")
    key = c.data
    bot.answer_callback_query(c.id)
    if key=="adm_admins":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm_admins_add"))
        kb.add(types.InlineKeyboardButton("➖ حذف ادمین", callback_data="adm_admins_del"))
        kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
        bot.send_message(uid, "مدیریت ادمین‌ها:", reply_markup=kb)
    elif key=="adm_plans":
        show_admin_plans(uid)
    elif key=="adm_coupon":
        coupon_menu(uid)
    elif key=="adm_wallet":
        wallet_admin_menu(uid)
    elif key=="adm_broadcast":
        set_state(uid, step="broadcast_text")
        bot.send_message(uid, "متن اعلان همگانی رو بفرست:", reply_markup=back_cancel_row())
    elif key=="adm_receipts":
        list_pending_receipts(uid)
    elif key=="adm_stats":
        show_stats(uid)
    elif key=="adm_wallet_logs":
        show_wallet_logs(uid)
    elif key=="adm_chat":
        set_state(uid, step="admin_chat")
        bot.send_message(uid, "پیامت رو برای چت ادمین‌ها بفرست:", reply_markup=back_cancel_row())
    elif key=="adm_ui":
        ui_menu(uid)

# --- Admins add/del
@bot.callback_query_handler(func=lambda c: c.data in ["adm_admins_add","adm_admins_del"])
def cb_admins_manage(c):
    uid=c.from_user.id
    if not is_admin(uid): return
    if c.data=="adm_admins_add":
        set_state(uid, step="admin_add_id")
        bot.send_message(uid, "آیدی عددی کاربر جدید رو بفرست:", reply_markup=back_cancel_row())
    else:
        set_state(uid, step="admin_del_id")
        bot.send_message(uid, "آیدی عددی ادمین رو برای حذف بفرست:", reply_markup=back_cancel_row())

def show_admin_plans(uid):
    d = db_read()
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن پلن", callback_data="pl_add"))
    for pid, p in d["plans"].items():
        kb.add(types.InlineKeyboardButton(f"✏️ {p.get('name')} ({len(p.get('stock',[]))})", callback_data=f"pl_edit_{pid}"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "📦 مدیریت پلن‌ها:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data=="pl_add" or c.data.startswith("pl_edit_"))
def cb_plans(c):
    uid=c.from_user.id
    if not is_admin(uid): return
    if c.data=="pl_add":
        set_state(uid, step="pl_name", plan={"id": str(uuid.uuid4())})
        return bot.send_message(uid, "نام پلن:", reply_markup=back_cancel_row())
    else:
        pid=c.data.split("_",2)[2]
        d=db_read(); p=d["plans"].get(pid)
        if not p: return bot.answer_callback_query(c.id,"پلن یافت نشد")
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✏️ ویرایش قیمت/مدت/حجم/توضیح", callback_data=f"pl_edit_fields_{pid}"))
        kb.add(types.InlineKeyboardButton("📥 افزودن به مخزن", callback_data=f"pl_stock_add_{pid}"))
        kb.add(types.InlineKeyboardButton("🗑 حذف پلن", callback_data=f"pl_del_{pid}"))
        kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
        bot.send_message(uid, f"پلن: {p.get('name')} | موجودی: {len(p.get('stock',[]))}", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("pl_edit_fields_") or c.data.startswith("pl_stock_add_") or c.data.startswith("pl_del_"))
def cb_plan_edit(c):
    uid=c.from_user.id
    if not is_admin(uid): return
    d=db_read()
    pid=c.data.split("_",3)[3]
    p=d["plans"].get(pid)
    if not p: return bot.answer_callback_query(c.id,"پلن یافت نشد")
    if c.data.startswith("pl_edit_fields_"):
        set_state(uid, step="pl_edit_fields", edit_plan_id=pid)
        bot.answer_callback_query(c.id)
        return bot.send_message(uid, "قیمت/مدت/حجم/توضیح را به شکل زیر بفرست:\nقیمت|مدت‌روز|حجمGB|توضیح\nمثال: 150000|30|100|پلن ماهانه 100گیگ", reply_markup=back_cancel_row())
    elif c.data.startswith("pl_stock_add_"):
        set_state(uid, step="pl_stock_add", edit_plan_id=pid)
        bot.answer_callback_query(c.id)
        return bot.send_message(uid, "متن کانفیگ (و در صورت وجود تصویر، بعداً هم می‌تونی بفرستی). فعلاً متن را بفرست:", reply_markup=back_cancel_row())
    elif c.data.startswith("pl_del_"):
        del d["plans"][pid]; db_write(d)
        bot.answer_callback_query(c.id, "حذف شد")
        return bot.send_message(uid, "پلن حذف شد.")

# --- Coupons
def coupon_menu(uid):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ ساخت کد تخفیف", callback_data="cp_new"))
    kb.add(types.InlineKeyboardButton("📃 لیست کدها", callback_data="cp_list"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "🏷 مدیریت کد تخفیف:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["cp_new","cp_list"])
def cb_coupon(c):
    uid=c.from_user.id
    if not is_admin(uid): return
    if c.data=="cp_new":
        # مراحل ساخت
        set_state(uid, step="cp_percent", coupon={"percent":None,"max_uses":0,"allowed_plans":None,"expires":None})
        bot.send_message(uid, "درصد تخفیف؟ (فقط عدد 0..90)", reply_markup=back_cancel_row())
    else:
        d=db_read()
        if not d["coupons"]:
            return bot.send_message(uid, "فعلاً کدی نیست.")
        lines=[]
        for code,cp in d["coupons"].items():
            lines.append(f"{code}: {cp['percent']}% | استفاده: {cp.get('used',0)}/{cp.get('max_uses',0) or '∞'} | وضعیت: {'منقضی' if cp.get('expires') and now_ts()>int(cp['expires']) else 'فعال'}")
        bot.send_message(uid, "کدها:\n"+"\n".join(lines))

# --- Wallet (Admin manual)
def wallet_admin_menu(uid):
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ شارژ دستی", callback_data="wa_add"))
    kb.add(types.InlineKeyboardButton("➖ کسر دستی", callback_data="wa_sub"))
    kb.add(types.InlineKeyboardButton("🧾 رسیدهای در انتظار", callback_data="adm_receipts"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "🪙 مدیریت کیف پول:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["wa_add","wa_sub"])
def cb_wallet_admin(c):
    uid=c.from_user.id
    if not is_admin(uid): return
    action = "add" if c.data=="wa_add" else "sub"
    set_state(uid, step=f"wa_{action}_uid")
    bot.answer_callback_query(c.id)
    bot.send_message(uid, "آیدی عددی کاربر؟", reply_markup=back_cancel_row())

def list_pending_receipts(uid):
    d=db_read()
    pend=[r for r in d["receipts"] if r["status"]=="pending"]
    if not pend:
        return bot.send_message(uid,"رسید در انتظار نداریم.")
    for r in pend[:20]:
        kb=types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("✅ تأیید", callback_data=f"rc_ok_{r['id']}"),
            types.InlineKeyboardButton("❌ رد", callback_data=f"rc_no_{r['id']}")
        )
        text=f"🧾 رسید در انتظار\nنوع: {('خرید کانفیگ' if r['kind']=='purchase' else 'شارژ کیف پول')}\nکاربر: <code>{r['uid']}</code>\nID: {r['id']}\nزمان: {r['at']}"
        try:
            if r.get("file_id"): bot.send_photo(uid, r["file_id"], caption=text, reply_markup=kb)
            else: bot.send_message(uid, text, reply_markup=kb)
        except: pass

# --- Stats
def show_stats(uid):
    d=db_read()
    total_orders=len(d["orders"])
    total_amount=sum([int(o.get("price",0)) for o in d["orders"]])
    # Top buyers
    agg={}
    for o in d["orders"]:
        u=o["uid"]; agg.setdefault(u,{"count":0,"amount":0}); agg[u]["count"]+=1; agg[u]["amount"]+=int(o.get("price",0))
    top=sorted(agg.items(), key=lambda x:x[1]["amount"], reverse=True)[:10]
    lines=[f"فروش کل: {total_orders} کانفیگ | {total_amount} تومان"]
    lines.append("👑 خریداران برتر:")
    for uid2,info in top:
        lines.append(f"• {uid2} | {info['count']} خرید | {info['amount']} تومان")
    bot.send_message(uid, "📊 آمار فروش:\n\n"+"\n".join(lines))

def show_wallet_logs(uid):
    d=db_read()
    if not d["wallet_logs"]:
        return bot.send_message(uid,"لاگی وجود ندارد.")
    lines=[]
    for x in sorted(d["wallet_logs"], key=lambda z:z["at"], reverse=True)[:25]:
        user = d["users"].get(str(x["uid"]),{})
        admin = d["users"].get(str(x.get("admin_id")),{})
        lines.append(
            f"🪪 کاربر: @{user.get('username','')} ({x['uid']})\n"
            f"👤 ادمین: @{admin.get('username','')} ({x.get('admin_id')})\n"
            f"⏱ {x['at']}\n"
            f"💵 تغییر: {x['delta']} | قبل: {x['before']} | بعد: {x['after']}\n"
            f"📝 دلیل: {x.get('reason','-')}\n"
            "—————————————"
        )
    bot.send_message(uid, "📒 لاگ موجودی:\n\n"+"\n".join(lines))

# --- Admin Chat
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id).get("step")=="admin_chat", content_types=["text"])
def on_admin_chat(message):
    d=db_read()
    entry={"id":str(uuid.uuid4()),"admin_id":message.from_user.id,"username":message.from_user.username or "", "text":message.text, "at":now_str()}
    d["admin_chat"].append(entry); db_write(d)
    for aid in d["admins"]:
        try:
            if aid!=message.from_user.id:
                bot.send_message(aid, f"💬 پیام ادمین @{entry['username'] or entry['admin_id']}:\n{entry['text']}")
        except: pass

# --- UI Editor
def ui_menu(uid):
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎛 روشن/خاموش دکمه‌ها", callback_data="ui_toggle"))
    kb.add(types.InlineKeyboardButton("✏️ ویرایش عناوین دکمه‌ها", callback_data="ui_btns"))
    kb.add(types.InlineKeyboardButton("📝 ویرایش متون ثابت", callback_data="ui_texts"))
    kb.add(types.InlineKeyboardButton("💳 ویرایش شماره کارت", callback_data="ui_card"))
    kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
    bot.send_message(uid, "🔧 دکمه‌ها و متون:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["ui_toggle","ui_btns","ui_texts","ui_card"])
def cb_ui(c):
    uid=c.from_user.id
    if not is_admin(uid): return
    d=db_read()
    if c.data=="ui_toggle":
        kb=types.InlineKeyboardMarkup()
        for k,v in d["ui"]["toggles"].items():
            kb.add(types.InlineKeyboardButton(f"{k} : {bool_btn(v)}", callback_data=f"ui_t_{k}"))
        kb.add(types.InlineKeyboardButton("⬅️ برگشت", callback_data="cancel"))
        bot.send_message(uid, "روشن/خاموش:", reply_markup=kb)
    elif c.data=="ui_btns":
        set_state(uid, step="ui_btn_key")
        bot.send_message(uid, "کلید دکمه (shop/wallet/tickets/my_configs/help/admin) رو بفرست:", reply_markup=back_cancel_row())
    elif c.data=="ui_texts":
        set_state(uid, step="ui_txt_key")
        bot.send_message(uid, "کلید متن (welcome/card_number/wallet_rules/tutorial) رو بفرست:", reply_markup=back_cancel_row())
    elif c.data=="ui_card":
        set_state(uid, step="ui_card_edit")
        bot.send_message(uid, "شماره کارت جدید رو بفرست (متن کامل پیام).", reply_markup=back_cancel_row())

@bot.callback_query_handler(func=lambda c: c.data.startswith("ui_t_"))
def cb_ui_toggle(c):
    uid=c.from_user.id
    k=c.data.split("_",2)[2]
    d=db_read()
    cur=d["ui"]["toggles"].get(k)
    if cur is None: return bot.answer_callback_query(c.id,"نامعتبر")
    d["ui"]["toggles"][k]=not cur; db_write(d)
    bot.answer_callback_query(c.id,"اوکی")
    return ui_menu(uid)

# ===================== STEP ROUTER =====================
def step_router(message, step, st):
    uid=message.from_user.id
    txt=(message.text or "").strip()

    # --- Admin add/del
    if step=="admin_add_id":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"آیدی نامعتبره", reply_markup=back_cancel_row())
        d=db_read(); ad=int(val)
        if ad not in d["admins"]:
            d["admins"].append(ad); db_write(d)
        clear_state(uid)
        return bot.send_message(uid,"✅ اضافه شد.")
    if step=="admin_del_id":
        val=re.sub(r"[^\d]","",txt)
        d=db_read(); ad=int(val or 0)
        if ad in d["admins"]:
            d["admins"].remove(ad); db_write(d)
            bot.send_message(uid,"✅ حذف شد.")
        else:
            bot.send_message(uid,"پیدا نشد.")
        clear_state(uid); return

    # --- Plan creation
    if step=="pl_name":
        p=st.get("plan",{}); p["name"]=txt; set_state(uid, step="pl_price", plan=p)
        return bot.send_message(uid,"قیمت (تومان):", reply_markup=back_cancel_row())
    if step=="pl_price":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"عدد نامعتبره.", reply_markup=back_cancel_row())
        p=st.get("plan",{}); p["price"]=int(val); set_state(uid, step="pl_duration", plan=p)
        return bot.send_message(uid,"مدت (روز):", reply_markup=back_cancel_row())
    if step=="pl_duration":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"عدد نامعتبره.", reply_markup=back_cancel_row())
        p=st.get("plan",{}); p["duration"]=int(val); set_state(uid, step="pl_volume", plan=p)
        return bot.send_message(uid,"حجم (GB):", reply_markup=back_cancel_row())
    if step=="pl_volume":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"عدد نامعتبره.", reply_markup=back_cancel_row())
        p=st.get("plan",{}); p["volume"]=int(val); set_state(uid, step="pl_desc", plan=p)
        return bot.send_message(uid,"توضیح کوتاه:", reply_markup=back_cancel_row())
    if step=="pl_desc":
        p=st.get("plan",{}); p["desc"]=txt; p.setdefault("stock",[]); p["id"]=p.get("id") or str(uuid.uuid4())
        d=db_read(); d["plans"][p["id"]]=p; db_write(d); clear_state(uid)
        return bot.send_message(uid,"✅ پلن ثبت شد.")

    if step=="pl_edit_fields":
        # قیمت|مدت|حجم|توضیح
        parts=txt.split("|")
        if len(parts)<4: return bot.send_message(uid,"فرمت اشتباهه.", reply_markup=back_cancel_row())
        price = re.sub(r"[^\d]","",parts[0])
        dur   = re.sub(r"[^\d]","",parts[1])
        vol   = re.sub(r"[^\d]","",parts[2])
        desc  = parts[3].strip()
        if not price or not dur or not vol:
            return bot.send_message(uid,"اعداد نامعتبر.", reply_markup=back_cancel_row())
        d=db_read(); p=d["plans"].get(st["edit_plan_id"])
        if not p: return bot.send_message(uid,"پلن یافت نشد.")
        p["price"]=int(price); p["duration"]=int(dur); p["volume"]=int(vol); p["desc"]=desc; db_write(d); clear_state(uid)
        return bot.send_message(uid,"✅ ویرایش شد.")
    if step=="pl_stock_add":
        d=db_read(); p=d["plans"].get(st["edit_plan_id"])
        if not p: return bot.send_message(uid,"پلن یافت نشد.")
        # متن کانفیگ
        cfg={"text": txt, "img": None}
        p.setdefault("stock",[]).append(cfg); db_write(d); clear_state(uid)
        return bot.send_message(uid,"✅ یک کانفیگ به مخزن افزوده شد.")

    # --- Coupon creation wizard
    if step=="cp_percent":
        val=re.sub(r"[^\d]","",txt)
        if not val or not (0<=int(val)<=90): return bot.send_message(uid,"درصد نامعتبره (0..90).", reply_markup=back_cancel_row())
        cp=st.get("coupon",{}); cp["percent"]=int(val)
        set_state(uid, step="cp_max", coupon=cp)
        return bot.send_message(uid,"حداکثر دفعات استفاده؟ (0 = نامحدود)", reply_markup=back_cancel_row())
    if step=="cp_max":
        val=re.sub(r"[^\d]","",txt)
        cp=st.get("coupon",{}); cp["max_uses"]=int(val or 0); cp["used"]=0
        set_state(uid, step="cp_plans", coupon=cp)
        return bot.send_message(uid,"کد برای همه پلن‌ها باشه یا فقط برخی؟\n"
                                    "برای همه: بنویس <b>all</b>\n"
                                    "برای برخی: آیدی پلن‌ها رو با کاما بفرست: id1,id2", reply_markup=back_cancel_row())
    if step=="cp_plans":
        cp=st.get("coupon",{})
        if txt.lower()=="all":
            cp["allowed_plans"]=None
        else:
            ids=[x.strip() for x in txt.split(",") if x.strip()]
            cp["allowed_plans"]=ids or None
        set_state(uid, step="cp_exp", coupon=cp)
        return bot.send_message(uid,"تاریخ انقضا (timestamp ثانیه) یا 0 برای بدون انقضا:", reply_markup=back_cancel_row())
    if step=="cp_exp":
        val=re.sub(r"[^\d]","",txt)
        cp=st.get("coupon",{}); exp=int(val or 0); cp["expires"]= (exp if exp>0 else None)
        set_state(uid, step="cp_code", coupon=cp)
        return bot.send_message(uid,"نام/کد دلخواه:", reply_markup=back_cancel_row())
    if step=="cp_code":
        code=txt.strip().upper()
        d=db_read()
        if code in d["coupons"]: return bot.send_message(uid,"این کد وجود داره. یکی دیگه بده.", reply_markup=back_cancel_row())
        cp=st.get("coupon",{})
        d["coupons"][code]=cp; db_write(d); clear_state(uid)
        return bot.send_message(uid,f"✅ کد {code} ساخته شد.")

    # --- Buy flow extras
    if step=="enter_coupon":
        d=db_read(); plan_id=st.get("plan_id"); ok,msg = apply_coupon_code(uid, txt, plan_id)
        bot.send_message(uid, msg)
        # رفرش کارت خرید
        msg_ref = None
        return
    if step=="await_receipt":
        # (کالای رسید با handler photo/document مدیریت میشه)
        return bot.send_message(uid, "برای ثبت رسید عکس/فایل آن را بفرست.", reply_markup=back_cancel_row())

    # --- Admin receipts (amount)
    if step=="enter_wallet_amount_for_receipt":
        return handle_amount_for_receipt(message, st)

    # --- Wallet admin manual
    if step=="wa_add_uid":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"آیدی نامعتبر.", reply_markup=back_cancel_row())
        set_state(uid, step="wa_add_amount", target_uid=int(val))
        return bot.send_message(uid,"مبلغ (فقط عدد):", reply_markup=back_cancel_row())
    if step=="wa_add_amount":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"عدد نامعتبر.", reply_markup=back_cancel_row())
        target=st.get("target_uid")
        d=db_read(); u=d["users"].setdefault(str(target), {"wallet":0, "username":""})
        before=u["wallet"]; u["wallet"]+=int(val); after=u["wallet"]
        push_wallet_log(target, int(val), before, after, uid, "شارژ دستی")
        db_write(d); clear_state(uid)
        return bot.send_message(uid, f"✅ شارژ شد. موجودی جدید کاربر {target}: {after}")

    if step=="wa_sub_uid":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"آیدی نامعتبر.", reply_markup=back_cancel_row())
        set_state(uid, step="wa_sub_amount", target_uid=int(val))
        return bot.send_message(uid,"مبلغ کسر (فقط عدد):", reply_markup=back_cancel_row())
    if step=="wa_sub_amount":
        val=re.sub(r"[^\d]","",txt)
        if not val: return bot.send_message(uid,"عدد نامعتبر.", reply_markup=back_cancel_row())
        target=st.get("target_uid")
        d=db_read(); u=d["users"].setdefault(str(target), {"wallet":0, "username":""})
        amount=int(val)
        before=u["wallet"]; u["wallet"]=max(0, u["wallet"]-amount); after=u["wallet"]
        push_wallet_log(target, -amount, before, after, uid, "کسر دستی")
        db_write(d); clear_state(uid)
        return bot.send_message(uid, f"✅ کسر شد. موجودی جدید کاربر {target}: {after}")

    # --- Broadcast
    if step=="broadcast_text":
        d=db_read()
        cnt=0
        for k in d["users"].keys():
            try: bot.send_message(int(k), f"📢 {txt}"); cnt+=1
            except: pass
        clear_state(uid)
        return bot.send_message(uid, f"ارسال شد برای {cnt} نفر.")

    # --- Ticket create / reply
    if step=="ticket_new_subject":
        set_state(uid, step="ticket_new_text", ticket_subject=txt)
        return bot.send_message(uid, "متن پیام رو بنویس:", reply_markup=back_cancel_row())
    if step=="ticket_new_text":
        add_ticket(uid, st.get("ticket_subject","(بدون موضوع)"), txt)
        clear_state(uid)
        return bot.send_message(uid, "✅ تیکت ثبت شد.")
    if step=="ticket_reply":
        if add_ticket_reply(uid, st.get("ticket_id"), txt, by=("admin" if is_admin(uid) else "user")):
            clear_state(uid); return bot.send_message(uid,"✅ ارسال شد.")
        return bot.send_message(uid,"تیکت پیدا نشد.", reply_markup=back_cancel_row())

    # --- UI edits
    if step=="ui_btn_key":
        valid={"shop","wallet","tickets","my_configs","help","admin"}
        if txt not in valid: return bot.send_message(uid,"کلید نامعتبر.", reply_markup=back_cancel_row())
        set_state(uid, step="ui_btn_val", ui_key=txt)
        return bot.send_message(uid, "عنوان جدید دکمه:", reply_markup=back_cancel_row())
    if step=="ui_btn_val":
        d=db_read(); key=st.get("ui_key"); d["ui"]["buttons"][key]=txt; db_write(d); clear_state(uid)
        return bot.send_message(uid,"✅ تغییر کرد.")

    if step=="ui_txt_key":
        valid={"welcome","card_number","wallet_rules","tutorial"}
        if txt not in valid: return bot.send_message(uid,"کلید نامعتبر.", reply_markup=back_cancel_row())
        set_state(uid, step="ui_txt_val", ui_key=txt)
        return bot.send_message(uid, "متن جدید:", reply_markup=back_cancel_row())
    if step=="ui_txt_val":
        d=db_read(); key=st.get("ui_key"); d["ui"]["texts"][key]=txt; db_write(d); clear_state(uid)
        return bot.send_message(uid,"✅ متن تغییر کرد.")
    if step=="ui_card_edit":
        d=db_read(); d["ui"]["texts"]["card_number"]=txt; db_write(d); clear_state(uid)
        return bot.send_message(uid,"✅ شماره کارت/متن کارت‌به‌کارت به‌روزرسانی شد.")

    # default
    return bot.send_message(uid, "ورودی معتبر نیست. از منو استفاده کن.", reply_markup=main_menu(uid))

# ===================== CALLBACK: COUPON ENTER / WALLET TOPUP =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("wallet_topup_"))
def cb_wallet_topup(c):
    uid=c.from_user.id
    diff=int(c.data.split("_",2)[2])
    set_state(uid, step="await_receipt", kind="wallet")
    bot.answer_callback_query(c.id)
    text = db_read()["ui"]["texts"]["card_number"] + f"\n\nمبلغ پیشنهادی: <b>{diff}</b> تومان"
    bot.send_message(uid, text, reply_markup=back_cancel_row())

# ===================== RUN =====================
if __name__ == "__main__":
    set_webhook_once()
    app.run(host="0.0.0.0", port=PORT)
