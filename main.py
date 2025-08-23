# -*- coding: utf-8 -*-
import os, json, time, uuid, re, threading
from datetime import datetime, timedelta
from flask import Flask, request, abort
import telebot
from telebot import types

# ---------------------------
# Config
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo")
APP_URL = os.getenv("APP_URL", "https://live-avivah-bardiabsd-cd8d676a.koyeb.app")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}"

DEFAULT_ADMIN_ID = 1743359080  # ادمین پیش‌فرض

DATA_PATH = os.getenv("DATA_PATH", "data.json")
BACKUP_EVERY_SEC = 60

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, num_threads=1)

# ---------------------------
# Tiny JSON Store
# ---------------------------
DEFAULT_STORE = {
    "admins": [DEFAULT_ADMIN_ID],
    "users": {},
    "wallets": {},   # uid -> int (rial)
    "receipts": {},  # rid -> {...}
    "tickets": {},   # tid -> {...}
    "plans": {},     # pid -> {"name","days","gb","price","desc","active":True}
    "stock": {},     # pid -> [ {id, text, photo_id, delivered_to:[uid,...]} ]
    "coupons": {},   # code -> {"percent","plan_id"(opt),"expires"(ts or None),"max_uses", "used":0, "active":True}
    "orders": [],    # [{uid, pid, price, final, coupon_code, at}]
    "states": {},    # uid -> {...}
    "ui": {          # متن‌ها و دکمه‌ها (قابل ویرایش از پنل ادمین)
        "main_user_title": "سلام! 👋 خوش اومدی\nاز منوی زیر انتخاب کن:",
        "btn_plans": "🛍 خرید پلن",
        "btn_wallet": "🪙 کیف پول",
        "btn_tickets": "🎫 تیکت پشتیبانی",
        "btn_myorders": "🧾 سفارش‌های من",
        "btn_cancel": "❌ انصراف",

        "main_admin_title": "پنل مدیریت 👑\nاز گزینه‌های زیر استفاده کن:",
        "btn_admin_plans": "📦 پلن‌ها و مخزن",
        "btn_admin_receipts": "🧾 رسیدها (در انتظار)",
        "btn_admin_wallets": "🪙 کیف پول (ادمین)",
        "btn_admin_coupons": "🏷 کد تخفیف",
        "btn_admin_texts": "🧩 دکمه‌ها و متن‌ها",
        "btn_admin_users": "👥 کاربران",
        "btn_admin_broadcast": "📢 اعلان همگانی",
        "btn_admin_stats": "📊 آمار فروش",
        "btn_admins_manage": "👑 مدیریت ادمین‌ها",
        "btn_back": "⬅️ برگشت",
        "card_number": "****-****-****-****",  # قابل ویرایش در پنل ادمین
    }
}

lock = threading.Lock()

def load_db():
    if not os.path.exists(DATA_PATH):
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_STORE, f, ensure_ascii=False, indent=2)
        return DEFAULT_STORE.copy()
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except:
            data = DEFAULT_STORE.copy()
    # تکمیل کلیدهای جاافتاده
    for k, v in DEFAULT_STORE.items():
        if k not in data:
            data[k] = v
    # ادمین پیشفرض را اگر نباشد اضافه کن
    if DEFAULT_ADMIN_ID not in data["admins"]:
        data["admins"].append(DEFAULT_ADMIN_ID)
    return data

DB = load_db()

def save_db():
    with lock:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(DB, f, ensure_ascii=False, indent=2)

def auto_backup_loop():
    while True:
        time.sleep(BACKUP_EVERY_SEC)
        save_db()

threading.Thread(target=auto_backup_loop, daemon=True).start()

# ---------------------------
# Helpers
# ---------------------------
def is_admin(uid:int)->bool:
    return int(uid) in DB["admins"]

def now_ts():
    return int(time.time())

def fmt_toman(rial:int)->str:
    # تمیز و کوتاه
    if rial is None: return "0"
    s = f"{rial:,}".replace(",", "،")
    return f"{s} تومان"

def get_state(uid):
    return DB["states"].get(str(uid), {})

def set_state(uid, **kwargs):
    s = get_state(uid)
    s.update(kwargs)
    DB["states"][str(uid)] = s
    save_db()

def clear_state(uid):
    if str(uid) in DB["states"]:
        del DB["states"][str(uid)]
        save_db()

def kb_inline(rows):
    m = types.InlineKeyboardMarkup()
    for row in rows:
        btns = [types.InlineKeyboardButton(text=t, callback_data=d) for (t, d) in row]
        m.row(*btns)
    return m

def kb_reply(rows):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for row in rows:
        m.row(*[types.KeyboardButton(t) for t in row])
    return m

def user_wallet(uid):
    return int(DB["wallets"].get(str(uid), 0))

def add_wallet(uid, amount):
    DB["wallets"][str(uid)] = user_wallet(uid) + int(amount)
    save_db()

def dec_wallet(uid, amount):
    DB["wallets"][str(uid)] = max(0, user_wallet(uid) - int(amount))
    save_db()

def add_order(uid, pid, price, final, coupon_code=None):
    DB["orders"].append({
        "uid": uid,
        "pid": pid,
        "price": price,
        "final": final,
        "coupon_code": coupon_code,
        "at": now_ts()
    })
    save_db()

def admin_ids():
    return [int(x) for x in DB["admins"]]

def get_plan(pid):
    return DB["plans"].get(str(pid))

def plan_in_stock(pid):
    lst = DB["stock"].get(str(pid), [])
    # فقط آیتم‌هایی که هنوز تحویل نشده‌اند
    remain = [x for x in lst if "delivered_to" not in x or not x["delivered_to"]]
    return len(remain)

def pick_one_from_stock(pid, to_uid):
    pid = str(pid)
    items = DB["stock"].get(pid, [])
    for it in items:
        delivered = it.get("delivered_to", [])
        if not delivered:
            it.setdefault("delivered_to", []).append(int(to_uid))
            save_db()
            return it
    return None

def apply_coupon(code, pid, price):
    """برمی‌گرداند: (final_price, err or None, code_used or None)"""
    if not code: 
        return price, None, None
    c = DB["coupons"].get(code.upper())
    if not c or not c.get("active", True):
        return price, "کد تخفیف نامعتبره ❌", None
    if c.get("expires") and now_ts() > int(c["expires"]):
        return price, "این کد منقضی شده ❌", None
    if c.get("max_uses") is not None and int(c.get("used", 0)) >= int(c["max_uses"]):
        return price, "سقف استفاده از این کد پر شده ❌", None
    limit_pid = c.get("plan_id")
    if limit_pid and str(limit_pid) != str(pid):
        return price, "این کد برای این پلن معتبر نیست ❌", None
    percent = int(c["percent"])
    discount = (price * percent) // 100
    final = max(0, price - discount)
    return final, None, code.upper()

def coupon_used(code):
    if not code: return
    c = DB["coupons"].get(code)
    if not c: return
    c["used"] = int(c.get("used", 0)) + 1
    save_db()

def ensure_user(uid, username):
    u = DB["users"].get(str(uid))
    if not u:
        DB["users"][str(uid)] = {"username": username, "created_at": now_ts(), "orders": 0}
    else:
        DB["users"][str(uid)]["username"] = username
    save_db()

# ---------------------------
# UI Builders
# ---------------------------
def main_user_menu(uid):
    ui = DB["ui"]
    rows = [
        (ui["btn_plans"], ui["btn_wallet"], ui["btn_tickets"]),
        (ui["btn_myorders"],)
    ]
    if is_admin(uid):
        rows.append(("پنل ادمین 👑",))
    return kb_reply(rows)

def main_admin_kb():
    ui = DB["ui"]
    rows = [
        (ui["btn_admin_plans"], ui["btn_admin_receipts"], ui["btn_admin_wallets"]),
        (ui["btn_admin_coupons"], ui["btn_admin_texts"], ui["btn_admin_users"]),
        (ui["btn_admin_broadcast"], ui["btn_admin_stats"], ui["btn_admins_manage"]),
        (ui["btn_back"],)
    ]
    return kb_reply(rows)

def plans_inline_kb():
    rows = []
    for pid, p in DB["plans"].items():
        if not p.get("active", True):
            continue
        stock_n = plan_in_stock(pid)
        title = f'{p["name"]} | موجودی: {stock_n}'
        rows.append([(title, f"plan:{pid}")])
    if not rows:
        rows = [[("فعلاً پلنی موجود نیست 😕", "noop")]]
    rows.append([("⬅️ برگشت", "back:home")])
    return kb_inline(rows)

def plan_buy_kb(pid):
    ui = DB["ui"]
    rows = [
        [("🧾 کارت‌به‌کارت", f"buy:card:{pid}"), ("🪙 پرداخت با کیف پول", f"buy:wallet:{pid}")],
        [("🎟 اعمال/حذف کد تخفیف", f"coupon:{pid}")],
        [(ui["btn_cancel"], f"cancel:pid:{pid}")]
    ]
    return kb_inline(rows)

def wallet_inline_kb(uid):
    rows = [
        [("➕ شارژ کیف پول", "wallet:charge")],
        [("📜 تاریخچه تراکنش‌ها", "wallet:history")],
        [("⬅️ برگشت", "back:home")]
    ]
    return kb_inline(rows)

def admin_receipts_inline_kb():
    # رسیدهای در انتظارِ رسیدگی
    waiting = [r for r in DB["receipts"].values() if r.get("status")=="pending"]
    rows = []
    for r in sorted(waiting, key=lambda x: x["created_at"], reverse=True):
        tag = "خرید کانفیگ" if r["purpose"]=="buy" else "شارژ کیف پول"
        title = f'{tag} · از @{r.get("username","-")} · #{r["id"][-5:]}'
        rows.append([(title, f"rcp:{r['id']}")])
    if not rows:
        rows = [[("فعلاً رسیدی در انتظار نیست ✅", "noop")]]
    rows.append([("⬅️ برگشت", "back:admin")])
    return kb_inline(rows)

def admin_plans_inline_kb():
    rows = [
        [("➕ افزودن پلن", "admplan:add"), ("🛠 مدیریت مخزن", "admplan:stock")],
    ]
    # لیست پلن‌ها
    for pid, p in DB["plans"].items():
        on = "✅" if p.get("active", True) else "⛔️"
        title = f'{on} {p["name"]} · {p["gb"]}GB/{p["days"]}روز · {fmt_toman(p["price"])} · موجودی: {plan_in_stock(pid)}'
        rows.append([(title, f"admplan:edit:{pid}")])
    rows.append([("⬅️ برگشت", "back:admin")])
    return kb_inline(rows)

def admin_coupons_kb():
    rows = [
        [("➕ ساخت کد تخفیف", "coupon:create")],
    ]
    for code, c in DB["coupons"].items():
        on = "✅" if c.get("active", True) else "⛔️"
        lim = f'پلن:{c["plan_id"]}' if c.get("plan_id") else "همه پلن‌ها"
        exp = ("—" if not c.get("expires") else datetime.fromtimestamp(int(c["expires"])).strftime("%Y-%m-%d"))
        used = f'{c.get("used",0)}/{c.get("max_uses","∞")}'
        title = f'{on} {code} · {c["percent"]}% · {lim} · انقضا:{exp} · استفاده:{used}'
        rows.append([(title, f"coupon:edit:{code}")])
    rows.append([("⬅️ برگشت", "back:admin")])
    return kb_inline(rows)

def admin_users_kb(page=0, per=8):
    uids = list(DB["users"].keys())
    start = page*per
    chunk = uids[start:start+per]
    rows = []
    for uid in chunk:
        u = DB["users"][uid]
        w = user_wallet(uid)
        title = f'@{u.get("username","-")} · ID:{uid} · کیف:{fmt_toman(w)} · خرید:{u.get("orders",0)}'
        rows.append([(title, f"user:view:{uid}")])
    nav = []
    if start>0: nav.append(("⬅️ قبلی", f"user:page:{page-1}"))
    if start+per < len(uids): nav.append(("بعدی ➡️", f"user:page:{page+1}"))
    if nav: rows.append(nav)
    rows.append([("⬅️ برگشت", "back:admin")])
    return kb_inline(rows)

def admin_wallet_kb(uid):
    return kb_inline([
        [("➕ شارژ دستی", f"aw:add:{uid}"), ("➖ کسر دستی", f"aw:sub:{uid}")],
        [("⬅️ برگشت", "back:admin_users")]
    ])

def admin_texts_kb():
    ui = DB["ui"]
    rows = [
        [("📝 ویرایش متن/دکمه‌ها", "ui:edit")],
        [("💳 ویرایش شماره کارت", "ui:card")],
        [("⬅️ برگشت", "back:admin")]
    ]
    return kb_inline(rows)

# ---------------------------
# Flask endpoints
# ---------------------------
@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    else:
        abort(403)

# ---------------------------
# Webhook setup (safe, with spam-guard)
# ---------------------------
_webhook_set_once = False
def set_webhook_once():
    global _webhook_set_once
    if _webhook_set_once: 
        return
    try:
        bot.delete_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print("Failed to set webhook:", e)
    _webhook_set_once = True

with app.app_context():
    set_webhook_once()

# ---------------------------
# Command: /start
# ---------------------------
@bot.message_handler(commands=['start'])
def start_cmd(m: types.Message):
    ensure_user(m.from_user.id, m.from_user.username)
    clear_state(m.from_user.id)
    ui = DB["ui"]
    text = ui["main_user_title"]
    bot.send_message(
        m.chat.id,
        text,
        reply_markup=main_user_menu(m.from_user.id)
    )

# ---------------------------
# Reply Keyboard Handlers (User & Admin)
# ---------------------------
@bot.message_handler(func=lambda msg: True, content_types=['text', 'photo', 'document'])
def all_messages(m: types.Message):
    ensure_user(m.from_user.id, m.from_user.username)
    txt = (m.text or "").strip()

    # اول بررسی وضعیت جریان‌ها (FSM)
    st = get_state(m.from_user.id)
    if st:
        return handle_state_message(m, st)

    ui = DB["ui"]

    # پنل ادمین
    if is_admin(m.from_user.id):
        if txt == "پنل ادمین 👑":
            bot.send_message(m.chat.id, ui["main_admin_title"], reply_markup=main_admin_kb())
            return
        # دکمه برگشت در پنل ادمین
        if txt == ui["btn_back"]:
            bot.send_message(m.chat.id, ui["main_user_title"], reply_markup=main_user_menu(m.from_user.id))
            return

    # دکمه‌های پنل کاربر
    if txt == ui["btn_plans"]:
        bot.send_message(m.chat.id, "لیست پلن‌ها 👇", reply_markup=main_user_menu(m.from_user.id))
        bot.send_message(m.chat.id, "یک پلن انتخاب کن:", reply_markup=types.ReplyKeyboardRemove(), reply_to_message_id=m.message_id)
        bot.send_message(m.chat.id, " ", reply_markup=plans_inline_kb())
        return

    if txt == ui["btn_wallet"]:
        w = user_wallet(m.from_user.id)
        bot.send_message(m.chat.id,
                         f"کیف پول شما: {fmt_toman(w)} 🪙\nاز گزینه‌های زیر یکی رو انتخاب کن:",
                         reply_markup=wallet_inline_kb(m.from_user.id))
        return

    if txt == ui["btn_tickets"]:
        show_ticket_topics(m)
        return

    if txt == ui["btn_myorders"]:
        show_my_orders(m)
        return

    # اگر هیچ‌کدام نبود → منو
    bot.send_message(m.chat.id, ui["main_user_title"], reply_markup=main_user_menu(m.from_user.id))

# ---------------------------
# State handler (FSM)
# ---------------------------
def handle_state_message(m: types.Message, st: dict):
    uid = m.from_user.id

    # آپلود رسید (کاربر)
    if st.get("await_state") == "send_receipt":
        rid = str(uuid.uuid4())
        is_photo = (m.content_type == "photo")
        is_doc = (m.content_type == "document")
        caption = (m.caption or m.text or "").strip()
        if not (is_photo or is_doc or caption):
            bot.reply_to(m, "لطفاً تصویر/فایل یا متن رسید رو بفرست 🙏")
            return
        file_id = None
        if is_photo:
            file_id = m.photo[-1].file_id
        elif is_doc:
            file_id = m.document.file_id

        DB["receipts"][rid] = {
            "id": rid,
            "uid": uid,
            "username": m.from_user.username,
            "purpose": st.get("receipt_purpose", "wallet"),  # buy | wallet
            "plan_id": st.get("plan_id"),
            "created_at": now_ts(),
            "file_id": file_id,
            "text": caption,
            "status": "pending",
        }
        save_db()
        clear_state(uid)
        bot.reply_to(m, "رسیدت ثبت شد ✅\nمنتظر تایید ادمین باش 🙏")
        # به ادمین‌ها خبر بده
        for a in admin_ids():
            try:
                bot.send_message(a, f"🧾 رسید جدید ثبت شد!\nاز: @{m.from_user.username or '-'}\nنوع: {'خرید کانفیگ' if st.get('receipt_purpose')=='buy' else 'شارژ کیف پول'}\nشناسه: #{rid[-5:]}")
            except: pass
        return

    # ساخت کد تخفیف (مرحله‌ای)
    if st.get("await_state") == "coupon_percent":
        val = (m.text or "").strip()
        if not val.isdigit() or not (0 < int(val) <= 100):
            bot.reply_to(m, "عدد بین 1 تا 100 بده ✋")
            return
        set_state(uid, await_state="coupon_plan", coupon={"percent": int(val)})
        bot.reply_to(m, "کد برای همه پلن‌ها باشه یا یک پلن خاص؟\n- همه → عدد 0\n- یا آی‌دی پلن موردنظر رو بفرست")
        return

    if st.get("await_state") == "coupon_plan":
        val = (m.text or "").strip()
        coupon = st.get("coupon", {})
        plan_id = None
        if val.isdigit() and int(val) != 0:
            if str(val) not in DB["plans"]:
                bot.reply_to(m, "آی‌دی پلن نامعتبره ❌\nلیست پلن‌ها رو از بخش مدیریت پلن ببین.")
                return
            plan_id = str(int(val))
        coupon["plan_id"] = plan_id
        set_state(uid, await_state="coupon_exp", coupon=coupon)
        bot.reply_to(m, "تاریخ انقضا (اختیاری):\nبه‌صورت YYYY-MM-DD یا عدد 0 برای بدون انقضا.")
        return

    if st.get("await_state") == "coupon_exp":
        val = (m.text or "").strip()
        coupon = st.get("coupon", {})
        exp_ts = None
        if val != "0":
            try:
                dt = datetime.strptime(val, "%Y-%m-%d")
                exp_ts = int(datetime(dt.year, dt.month, dt.day).timestamp())
            except:
                bot.reply_to(m, "فرمت تاریخ نامعتبره. مثال: 2025-12-31 یا 0")
                return
        coupon["expires"] = exp_ts
        set_state(uid, await_state="coupon_limit", coupon=coupon)
        bot.reply_to(m, "سقف تعداد استفاده: (مثلاً 50)\nیا 0 برای نامحدود.")
        return

    if st.get("await_state") == "coupon_limit":
        val = (m.text or "").strip()
        if not val.isdigit() or int(val) < 0:
            bot.reply_to(m, "باید عدد صفر یا مثبت بدی.")
            return
        coupon = st.get("coupon", {})
        coupon["max_uses"] = None if int(val)==0 else int(val)
        set_state(uid, await_state="coupon_name", coupon=coupon)
        bot.reply_to(m, "نام/کد برای تخفیف رو بفرست (فقط حروف/اعداد، بدون فاصله).")
        return

    if st.get("await_state") == "coupon_name":
        code = (m.text or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9_]+", code):
            bot.reply_to(m, "فقط حروف لاتین بزرگ، عدد یا _ مجازه.")
            return
        if code in DB["coupons"]:
            bot.reply_to(m, "این کد از قبل وجود داره ❌")
            return
        coupon = st.get("coupon", {})
        DB["coupons"][code] = {
            "percent": coupon.get("percent", 5),
            "plan_id": coupon.get("plan_id"),
            "expires": coupon.get("expires"),
            "max_uses": coupon.get("max_uses"),
            "used": 0,
            "active": True
        }
        save_db()
        clear_state(uid)
        bot.reply_to(m, f"کد {code} ساخته شد ✅")
        return

    # ویرایش شماره کارت
    if st.get("await_state") == "ui_card":
        card = (m.text or "").strip()
        DB["ui"]["card_number"] = card
        save_db()
        clear_state(uid)
        bot.reply_to(m, "شماره کارت به‌روزرسانی شد ✅")
        return

    # ویرایش متن/دکمه (کلید)
    if st.get("await_state") == "ui_key":
        key = st.get("ui_key")
        val = (m.text or "").strip()
        DB["ui"][key] = val
        save_db()
        clear_state(uid)
        bot.reply_to(m, "به‌روزرسانی شد ✅")
        return

    # افزودن پلن
    if st.get("await_state") == "plan_name":
        name = (m.text or "").strip()
        set_state(uid, await_state="plan_days", new_plan={"name": name})
        bot.reply_to(m, "مدت (روز): یک عدد مثل 30")
        return

    if st.get("await_state") == "plan_days":
        if not (m.text or "").isdigit():
            bot.reply_to(m, "باید عدد بدی.")
            return
        pl = st.get("new_plan", {})
        pl["days"] = int(m.text)
        set_state(uid, await_state="plan_gb", new_plan=pl)
        bot.reply_to(m, "حجم (GB): مثل 100")
        return

    if st.get("await_state") == "plan_gb":
        if not (m.text or "").isdigit():
            bot.reply_to(m, "باید عدد بدی.")
            return
        pl = st.get("new_plan", {})
        pl["gb"] = int(m.text)
        set_state(uid, await_state="plan_price", new_plan=pl)
        bot.reply_to(m, "قیمت (تومان): فقط عدد")
        return

    if st.get("await_state") == "plan_price":
        if not (m.text or "").isdigit():
            bot.reply_to(m, "قیمت باید عدد باشه.")
            return
        pl = st.get("new_plan", {})
        pl["price"] = int(m.text)
        set_state(uid, await_state="plan_desc", new_plan=pl)
        bot.reply_to(m, "توضیح کوتاه پلن:")
        return

    if st.get("await_state") == "plan_desc":
        pl = st.get("new_plan", {})
        pl["desc"] = (m.text or "").strip()
        pid = str(int(time.time()))
        DB["plans"][pid] = {
            "name": pl["name"], "days": pl["days"], "gb": pl["gb"],
            "price": pl["price"], "desc": pl["desc"], "active": True
        }
        DB["stock"].setdefault(pid, [])
        save_db()
        clear_state(uid)
        bot.reply_to(m, f"پلن «{pl['name']}» اضافه شد ✅", reply_markup=main_admin_kb())
        return

    # افزودن به مخزن
    if st.get("await_state") == "stock_plan":
        val = (m.text or "").strip()
        if val not in DB["plans"]:
            bot.reply_to(m, "آی‌دی پلن نامعتبره.")
            return
        set_state(uid, await_state="stock_mode", sel_pid=val)
        bot.reply_to(m, "مدیا/متن کانفیگ رو بفرست (عکس یا متن). برای پایان، کلمه «تمام» رو بفرست.")
        return

    if st.get("await_state") == "stock_mode":
        if (m.text or "").strip() == "تمام":
            clear_state(uid)
            bot.reply_to(m, "افزودن به مخزن تموم شد ✅")
            return
        pid = st.get("sel_pid")
        entry = {"id": str(uuid.uuid4()), "text": None, "photo_id": None, "delivered_to": []}
        if m.content_type == "photo":
            entry["photo_id"] = m.photo[-1].file_id
            entry["text"] = (m.caption or "").strip() or None
        elif m.content_type == "text":
            entry["text"] = (m.text or "").strip()
        else:
            bot.reply_to(m, "فقط عکس یا متن مجازه.")
            return
        DB["stock"].setdefault(pid, []).append(entry)
        save_db()
        bot.reply_to(m, f"یک مورد به مخزن پلن #{pid} اضافه شد ✅ (برای پایان: «تمام»)")
        return

    # پاسخ به تیکت
    if st.get("await_state") == "ticket_msg":
        tid = st.get("ticket_id")
        tk = DB["tickets"].get(tid)
        if not tk:
            clear_state(uid)
            bot.reply_to(m, "تیکت پیدا نشد ❌")
            return
        msg = (m.text or m.caption or "").strip()
        # ثبت پیام
        tk["messages"].append({
            "from_admin": is_admin(uid),
            "uid": uid,
            "text": msg,
            "at": now_ts()
        })
        save_db()
        clear_state(uid)
        bot.reply_to(m, "پیامت ثبت شد ✅")
        # اطلاع به طرف مقابل
        other_uid = tk["uid"] if is_admin(uid) else admin_ids()[0]
        try:
            bot.send_message(other_uid, f"🟡 پیام جدید در تیکت #{tid[-5:]}:\n\n{msg}")
        except: pass
        return

    # شارژ/کسر دستی کیف پول (ادمین)
    if st.get("await_state") == "aw_amount":
        target = st.get("aw_target")
        mode = st.get("aw_mode")
        val = (m.text or "").replace(",", "").replace(" ", "")
        if not val.isdigit():
            bot.reply_to(m, "لطفاً عدد صحیح وارد کن (فقط رقم).")
            return
        amt = int(val)
        if mode == "add":
            add_wallet(target, amt)
            bot.reply_to(m, f"به کیف پول کاربر {fmt_toman(amt)} اضافه شد ✅")
        else:
            dec_wallet(target, amt)
            bot.reply_to(m, f"{fmt_toman(amt)} از کیف پول کاربر کسر شد ✅")
        clear_state(uid)
        return

    # مبلغ تأیید رسید (ادمین، نوع شارژ)
    if st.get("await_state") == "rcp_amount":
        rid = st.get("rcp_id")
        r = DB["receipts"].get(rid)
        if not r or r.get("status") != "pending":
            clear_state(uid)
            bot.reply_to(m, "این رسید قابل پردازش نیست ❌")
            return
        val = (m.text or "").replace(",", "").replace(" ", "")
        if not val.isdigit():
            bot.reply_to(m, "عدد صحیح وارد کن.")
            return
        amt = int(val)
        uid2 = r["uid"]
        if r["purpose"] == "wallet":
            add_wallet(uid2, amt)
            r["status"] = "approved"
            r["approved_at"] = now_ts()
            r["amount"] = amt
            save_db()
            bot.reply_to(m, "شارژ کیف پول تایید شد ✅")
            try:
                bot.send_message(uid2, f"✅ شارژ کیف پولت تایید شد و {fmt_toman(amt)} اضافه شد.")
            except: pass
        else:
            # خرید کانفیگ → ارسال کانفیگ از مخزن
            pid = r.get("plan_id")
            it = pick_one_from_stock(pid, uid2)
            if not it:
                r["status"] = "failed"
                save_db()
                bot.reply_to(m, "مخزن خالیه! اول مخزن رو شارژ کن ❌")
                try: bot.send_message(uid2, "متاسفیم 🙏 فعلاً موجودی این پلن تموم شده. به‌زودی شارژ می‌کنیم.")
                except: pass
                return
            # ارسال
            send_config_to_user(uid2, pid, it)
            r["status"] = "approved"
            r["approved_at"] = now_ts()
            r["amount"] = amt
            save_db()
            bot.reply_to(m, "خرید تایید شد و کانفیگ ارسال شد ✅")
            try:
                bot.send_message(uid2, "✅ سفارشت تایید شد و کانفیگ برات ارسال شد.")
            except: pass
        clear_state(uid)
        return

    # اگر هیچ حالت فعالی نبود:
    bot.reply_to(m, "یک لحظه! گزینه‌ای که انتخاب کردی رو پیدا نکردم. از منوی ربات استفاده کن 🙏")

# ---------------------------
# Callbacks (Inline)
# ---------------------------
@bot.callback_query_handler(func=lambda c: True)
def cb(c: types.CallbackQuery):
    uid = c.from_user.id
    ensure_user(uid, c.from_user.username or "")
    data = c.data or "noop"

    if data == "noop":
        bot.answer_callback_query(c.id)
        return

    if data == "back:home":
        bot.answer_callback_query(c.id)
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
        bot.send_message(c.message.chat.id, DB["ui"]["main_user_title"], reply_markup=main_user_menu(uid))
        return

    # لیست پلن‌ها / جزئیات
    if data.startswith("plan:"):
        pid = data.split(":")[1]
        p = get_plan(pid)
        bot.answer_callback_query(c.id)
        if not p or not p.get("active", True):
            bot.edit_message_text("این پلن در دسترس نیست ❌", c.message.chat.id, c.message.message_id)
            return
        st = plan_in_stock(pid)
        text = f'''🛍 {p["name"]}
⏳ مدت: {p["days"]} روز
📦 حجم: {p["gb"]} GB
💵 قیمت: {fmt_toman(p["price"])}
ℹ️ توضیح: {p["desc"]}

موجودی مخزن: {st} عدد'''
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=plan_buy_kb(pid))
        return

    # خرید: کارت‌به‌کارت / کیف پول
    if data.startswith("buy:"):
        _, method, pid = data.split(":")
        p = get_plan(pid)
        bot.answer_callback_query(c.id)
        if not p or not p.get("active", True):
            bot.send_message(c.message.chat.id, "این پلن در دسترس نیست ❌")
            return
        # قیمت + کد تخفیف موجود در state
        st = get_state(uid)
        coupon_code = st.get("coupon_code")
        final, err, used = apply_coupon(coupon_code, pid, p["price"])
        if err:
            final, used = p["price"], None
        if method == "card":
            card = DB["ui"]["card_number"]
            set_state(uid, await_state="send_receipt", receipt_purpose="buy", plan_id=pid)
            msg = f'''پرداخت کارت‌به‌کارت 🧾

💳 شماره کارت:
{card}

💰 مبلغ نهایی: {fmt_toman(final)}
لطفاً بعد از پرداخت، عکس/فایل یا متن رسید رو همینجا ارسال کن.
'''
            bot.send_message(c.message.chat.id, msg)
        else:
            # کیف پول
            w = user_wallet(uid)
            if w >= final:
                dec_wallet(uid, final)
                it = pick_one_from_stock(pid, uid)
                if not it:
                    bot.send_message(c.message.chat.id, "متاسفم 🙏 فعلاً موجودی این پلن تموم شده.")
                    add_wallet(uid, final)  # برگشت پول
                    return
                send_config_to_user(uid, pid, it)
                add_order(uid, pid, p["price"], final, used)
                coupon_used(used)
                DB["users"][str(uid)]["orders"] = DB["users"][str(uid)].get("orders", 0)+1
                save_db()
                bot.send_message(c.message.chat.id, "✅ خرید از کیف پول انجام شد و کانفیگ ارسال شد.")
            else:
                diff = final - w
                set_state(uid, await_state="send_receipt", receipt_purpose="wallet", plan_id=None)
                msg = f'''موجودی کیف پول کافی نیست ❗️
مبلغ موجودی: {fmt_toman(w)}
مبلغ نهایی خرید: {fmt_toman(final)}
مابه‌التفاوت: {fmt_toman(diff)}

برای شارژ همین مقدار، پرداخت کارت‌به‌کارت انجام بده و رسید رو ارسال کن 🙏
💳 کارت: {DB["ui"]["card_number"]}
'''
                bot.send_message(c.message.chat.id, msg)
        return

    # کد تخفیف
    if data.startswith("coupon:"):
        pid = data.split(":")[1]
        st = get_state(uid)
        cur = st.get("coupon_code")
        if cur:
            clear_state(uid)
            bot.answer_callback_query(c.id, "کد تخفیف حذف شد ✅", show_alert=False)
        else:
            set_state(uid, await_state="enter_coupon", plan_for_coupon=pid)
            bot.answer_callback_query(c.id, "کد تخفیف رو به‌صورت متن بفرست ✍️", show_alert=True)
        return

    # کیف پول
    if data == "wallet:charge":
        set_state(uid, await_state="send_receipt", receipt_purpose="wallet", plan_id=None)
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
                         f"برای شارژ کیف پول، مبلغ دلخواه رو کارت‌به‌کارت کن و رسید رو ارسال کن 🙏\n💳 کارت: {DB['ui']['card_number']}")
        return
    if data == "wallet:history":
        bot.answer_callback_query(c.id)
        show_wallet_history(uid, c.message)
        return

    # ادمین: رسیدها
    if data == "admplan:add":
        bot.answer_callback_query(c.id)
        set_state(uid, await_state="plan_name")
        bot.send_message(c.message.chat.id, "نام پلن رو بفرست:")
        return
    if data == "admplan:stock":
        bot.answer_callback_query(c.id)
        msg = "آی‌دی پلن موردنظر برای افزودن به مخزن رو بفرست (از لیست پلن‌ها نگاه کن):"
        set_state(uid, await_state="stock_plan")
        bot.send_message(c.message.chat.id, msg)
        return
    if data.startswith("admplan:edit:"):
        bot.answer_callback_query(c.id)
        pid = data.split(":")[2]
        p = get_plan(pid)
        if not p:
            bot.send_message(c.message.chat.id, "پلن پیدا نشد.")
            return
        on = "⛔️ غیرفعال کن" if p.get("active", True) else "✅ فعال کن"
        kb = kb_inline([
            [("✏️ نام", f"pe:name:{pid}"), ("⏳ روز", f"pe:days:{pid}"), ("📦 GB", f"pe:gb:{pid}")],
            [("💵 قیمت", f"pe:price:{pid}"), ("ℹ️ توضیح", f"pe:desc:{pid}")],
            [(on, f"pe:toggle:{pid}"), ("🗑 حذف", f"pe:del:{pid}")],
            [("⬅️ برگشت", "adm:plans")]
        ])
        txt = f'ویرایش پلن:\n{p["name"]} · {p["gb"]}GB/{p["days"]}روز · {fmt_toman(p["price"])}\n{p["desc"]}\nموجودی مخزن: {plan_in_stock(pid)}'
        bot.send_message(c.message.chat.id, txt, reply_markup=kb)
        return
    if data == "adm:plans":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "مدیریت پلن‌ها و مخزن:", reply_markup=admin_plans_inline_kb())
        return

    if data.startswith("pe:"):
        bot.answer_callback_query(c.id)
        _, fld, pid = data.split(":")
        p = get_plan(pid)
        if not p:
            bot.send_message(c.message.chat.id, "پلن پیدا نشد.")
            return
        if fld == "toggle":
            p["active"] = not p.get("active", True)
            save_db()
            bot.send_message(c.message.chat.id, f'وضعیت پلن تغییر کرد: {"فعال" if p["active"] else "غیرفعال"} ✅')
            return
        if fld == "del":
            DB["plans"].pop(str(pid), None)
            DB["stock"].pop(str(pid), None)
            save_db()
            bot.send_message(c.message.chat.id, "پلن حذف شد ✅")
            return
        # تغییر فیلد عدد/متن
        set_state(uid, await_state=f"pe_{fld}", edit_pid=pid)
        labels = {
            "name": "نام جدید پلن رو بفرست:",
            "days": "مدت (روز) جدید:",
            "gb": "حجم (GB) جدید:",
            "price": "قیمت (تومان) جدید:",
            "desc": "توضیح جدید:"
        }
        bot.send_message(c.message.chat.id, labels.get(fld, "مقدار جدید رو بفرست:"))
        return

    # رسیدها (لیست)
    if data == "admin:receipts":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "رسیدهای در انتظار:", reply_markup=admin_receipts_inline_kb())
        return
    if data.startswith("rcp:"):
        bot.answer_callback_query(c.id)
        rid = data.split(":")[1]
        r = DB["receipts"].get(rid)
        if not r:
            bot.send_message(c.message.chat.id, "رسید پیدا نشد.")
            return
        kb = kb_inline([
            [("✅ تایید", f"rcp_ok:{rid}"), ("❌ رد", f"rcp_no:{rid}")],
            [("⬅️ برگشت", "admin:receipts")]
        ])
        text = f'''🧾 رسید #{rid[-5:]}
از: @{r.get("username","-")} (ID:{r["uid"]})
نوع: {'خرید کانفیگ' if r['purpose']=='buy' else 'شارژ کیف پول'}
وضعیت: {r["status"]}

متن/توضیح:
{r.get("text","—")}
'''
        if r.get("file_id"):
            try:
                bot.send_photo(c.message.chat.id, r["file_id"], caption=text, reply_markup=kb)
            except:
                bot.send_message(c.message.chat.id, text, reply_markup=kb)
        else:
            bot.send_message(c.message.chat.id, text, reply_markup=kb)
        return

    if data.startswith("rcp_ok:"):
        bot.answer_callback_query(c.id)
        rid = data.split(":")[1]
        r = DB["receipts"].get(rid)
        if not r or r.get("status")!="pending":
            bot.send_message(c.message.chat.id, "این رسید قابل تایید نیست.")
            return
        # درخواست مبلغ
        set_state(uid, await_state="rcp_amount", rcp_id=rid)
        bot.send_message(c.message.chat.id, "مبلغ تایید (تومان) رو وارد کن (فقط عدد):")
        return

    if data.startswith("rcp_no:"):
        bot.answer_callback_query(c.id)
        rid = data.split(":")[1]
        r = DB["receipts"].get(rid)
        if not r:
            bot.send_message(c.message.chat.id, "رسید پیدا نشد.")
            return
        r["status"] = "rejected"
        r["rejected_at"] = now_ts()
        save_db()
        bot.send_message(c.message.chat.id, "رسید رد شد ❌")
        try:
            bot.send_message(r["uid"], "رسید شما رد شد ❌ در صورت نیاز با پشتیبانی در ارتباط باشید.")
        except: pass
        return

    # کیف پول (ادمین از پروفایل کاربر)
    if data.startswith("aw:"):
        bot.answer_callback_query(c.id)
        _, mode, uid2 = data.split(":")
        set_state(uid, await_state="aw_amount", aw_target=int(uid2), aw_mode=mode)
        bot.send_message(c.message.chat.id, f"مبلغ رو وارد کن (فقط رقم). حالت: {'افزایش' if mode=='add' else 'کاهش'}")
        return

    # مدیریت ادمین‌ها
    if data == "admins:manage":
        bot.answer_callback_query(c.id)
        rows = [[(f"➕ افزودن ادمین", "admadd")]]
        for a in admin_ids():
            rows.append([(f"👑 {a}", f"admdel:{a}")])
        rows.append([("⬅️ برگشت", "back:admin")])
        bot.send_message(c.message.chat.id, "مدیریت ادمین‌ها:", reply_markup=kb_inline(rows))
        return
    if data == "admadd":
        bot.answer_callback_query(c.id)
        set_state(uid, await_state="adm_add")
        bot.send_message(c.message.chat.id, "آیدی عددی ادمین جدید رو بفرست:")
        return
    if data.startswith("admdel:"):
        bot.answer_callback_query(c.id)
        aid = int(data.split(":")[1])
        if aid == DEFAULT_ADMIN_ID:
            bot.send_message(c.message.chat.id, "ادمین پیش‌فرض قابل حذف نیست.")
            return
        if aid in DB["admins"]:
            DB["admins"].remove(aid)
            save_db()
            bot.send_message(c.message.chat.id, "حذف شد ✅")
        return

    # مدیریت متن‌ها و دکمه‌ها
    if data == "ui:edit":
        bot.answer_callback_query(c.id)
        rows = []
        for k in ["main_user_title","btn_plans","btn_wallet","btn_tickets","btn_myorders",
                  "main_admin_title","btn_admin_plans","btn_admin_receipts","btn_admin_wallets",
                  "btn_admin_coupons","btn_admin_texts","btn_admin_users","btn_admin_broadcast",
                  "btn_admin_stats","btn_admins_manage","btn_back","btn_cancel"]:
            rows.append([(k, f"uikey:{k}")])
        rows.append([("⬅️ برگشت", "back:admin")])
        bot.send_message(c.message.chat.id, "کدوم مورد رو میخوای ویرایش کنی؟", reply_markup=kb_inline(rows))
        return
    if data == "ui:card":
        bot.answer_callback_query(c.id)
        set_state(uid, await_state="ui_card")
        bot.send_message(c.message.chat.id, "شماره کارت جدید رو بفرست (با خط فاصله یا بدون).")
        return
    if data.startswith("uikey:"):
        bot.answer_callback_query(c.id)
        key = data.split(":")[1]
        set_state(uid, await_state="ui_key", ui_key=key)
        bot.send_message(c.message.chat.id, f"مقدار جدید برای {key} رو بفرست:")
        return

    # کوپن‌ها
    if data == "coupon:create":
        bot.answer_callback_query(c.id)
        set_state(uid, await_state="coupon_percent")
        bot.send_message(c.message.chat.id, "درصد تخفیف (1 تا 100):")
        return
    if data.startswith("coupon:edit:"):
        bot.answer_callback_query(c.id)
        code = data.split(":")[2]
        cpn = DB["coupons"].get(code)
        if not cpn:
            bot.send_message(c.message.chat.id, "کد پیدا نشد.")
            return
        on = "⛔️ غیرفعال کن" if cpn.get("active", True) else "✅ فعال کن"
        kb = kb_inline([
            [("درصد", f"ce:percent:{code}"), ("پلن", f"ce:plan:{code}"), ("انقضا", f"ce:exp:{code}")],
            [("سقف استفاده", f"ce:max:{code}"), (on, f"ce:toggle:{code}")],
            [("🗑 حذف", f"ce:del:{code}")],
            [("⬅️ برگشت", "admin:coupons")]
        ])
        bot.send_message(c.message.chat.id, f"ویرایش کد {code}:", reply_markup=kb)
        return
    if data == "admin:coupons":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "مدیریت کدهای تخفیف:", reply_markup=admin_coupons_kb())
        return

    if data.startswith("ce:"):
        bot.answer_callback_query(c.id)
        _, fld, code = data.split(":")
        cpn = DB["coupons"].get(code)
        if not cpn:
            bot.send_message(c.message.chat.id, "کد پیدا نشد.")
            return
        if fld == "toggle":
            cpn["active"] = not cpn.get("active", True)
            save_db()
            bot.send_message(c.message.chat.id, f'وضعیت کد تغییر کرد: {"فعال" if cpn["active"] else "غیرفعال"}')
            return
        if fld == "del":
            DB["coupons"].pop(code, None)
            save_db()
            bot.send_message(c.message.chat.id, "کد حذف شد ✅")
            return
        # تغییر مرحله‌ای
        map_label = {
            "percent": "درصد جدید (1 تا 100):",
            "plan": "آی‌دی پلن (یا 0 برای همه پلن‌ها):",
            "exp": "تاریخ انقضا YYYY-MM-DD یا 0:",
            "max": "سقف استفاده (0 = نامحدود):"
        }
        set_state(uid, await_state=f"ce_{fld}", edit_code=code)
        bot.send_message(c.message.chat.id, map_label[fld])
        return

    # کاربران
    if data == "admin:users":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "لیست کاربران:", reply_markup=admin_users_kb(0))
        return
    if data.startswith("user:page:"):
        bot.answer_callback_query(c.id)
        page = int(data.split(":")[2])
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=admin_users_kb(page))
        return
    if data.startswith("user:view:"):
        bot.answer_callback_query(c.id)
        uid2 = data.split(":")[2]
        u = DB["users"].get(uid2)
        if not u:
            bot.send_message(c.message.chat.id, "کاربر پیدا نشد.")
            return
        txt = f'''👤 کاربر
یوزرنیم: @{u.get("username","-")}
آیدی: {uid2}
تعداد خرید: {u.get("orders",0)}
موجودی کیف پول: {fmt_toman(user_wallet(uid2))}
'''
        bot.send_message(c.message.chat.id, txt, reply_markup=admin_wallet_kb(uid2))
        return

    # اعلان همگانی
    if data == "admin:broadcast":
        bot.answer_callback_query(c.id)
        set_state(uid, await_state="broadcast_text")
        bot.send_message(c.message.chat.id, "متن اعلان همگانی رو بفرست:")
        return

    # آمار فروش
    if data == "admin:stats":
        bot.answer_callback_query(c.id)
        send_sales_stats(c.message.chat.id)
        return

    # رسیدها در انتظار (میانبر)
    if data == "admin:receipts":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "رسیدهای در انتظار:", reply_markup=admin_receipts_inline_kb())
        return

    # برگشت به پنل ادمین
    if data == "back:admin":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, DB["ui"]["main_admin_title"], reply_markup=main_admin_kb())
        return

    # کیف پول - برگشت به مدیریت کاربران
    if data == "back:admin_users":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "لیست کاربران:", reply_markup=admin_users_kb(0))
        return

# ---------------------------
# Extra handlers for FSM not covered in callback
# ---------------------------
@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await_state") in {
    "enter_coupon","adm_add","pe_name","pe_days","pe_gb","pe_price","pe_desc",
    "ce_percent","ce_plan","ce_exp","ce_max",
    "broadcast_text"
})
def fsm_text_steps(m: types.Message):
    st = get_state(m.from_user.id)
    uid = m.from_user.id
    state = st.get("await_state")

    if state == "enter_coupon":
        code = (m.text or "").strip().upper()
        set_state(uid, coupon_code=code)
        bot.reply_to(m, "کد ثبت شد ✅ دوباره روی «خرید» بزن.")
        clear_state(uid)  # فقط ذخیره‌ی coupon_code
        return

    if state == "adm_add":
        val = (m.text or "").strip()
        if not val.isdigit():
            bot.reply_to(m, "فقط آیدی عددی بفرست.")
            return
        aid = int(val)
        if aid not in DB["admins"]:
            DB["admins"].append(aid)
            save_db()
            bot.reply_to(m, "ادمین اضافه شد ✅")
        else:
            bot.reply_to(m, "این آیدی قبلاً ادمین بوده.")
        clear_state(uid)
        return

    # ویرایش فیلد پلن
    if state.startswith("pe_"):
        fld = state.split("_",1)[1]
        pid = st.get("edit_pid")
        p = get_plan(pid)
        if not p:
            clear_state(uid); bot.reply_to(m, "پلن پیدا نشد."); return
        val = (m.text or "").strip()
        if fld in ("days","gb","price"):
            if not val.isdigit():
                bot.reply_to(m, "باید عدد بدی.")
                return
            p[fld] = int(val)
        else:
            p[fld] = val
        save_db()
        clear_state(uid)
        bot.reply_to(m, "به‌روزرسانی شد ✅")
        return

    # ویرایش کد تخفیف
    if state.startswith("ce_"):
        fld = state.split("_",1)[1]
        code = st.get("edit_code")
        cpn = DB["coupons"].get(code)
        if not cpn:
            clear_state(uid); bot.reply_to(m, "کد پیدا نشد."); return
        val = (m.text or "").strip()
        if fld == "percent":
            if not val.isdigit() or not (1 <= int(val) <= 100):
                bot.reply_to(m, "باید عدد 1..100 بدی.")
                return
            cpn["percent"] = int(val)
        elif fld == "plan":
            if val == "0":
                cpn["plan_id"] = None
            else:
                if val not in DB["plans"]:
                    bot.reply_to(m, "آی‌دی پلن نامعتبر.")
                    return
                cpn["plan_id"] = val
        elif fld == "exp":
            if val == "0":
                cpn["expires"] = None
            else:
                try:
                    dt = datetime.strptime(val, "%Y-%m-%d")
                    cpn["expires"] = int(datetime(dt.year, dt.month, dt.day).timestamp())
                except:
                    bot.reply_to(m, "فرمت تاریخ نادرست.")
                    return
        elif fld == "max":
            if not val.isdigit() or int(val) < 0:
                bot.reply_to(m, "باید عدد صفر یا مثبت بدی.")
                return
            cpn["max_uses"] = None if int(val)==0 else int(val)
        save_db()
        clear_state(uid)
        bot.reply_to(m, "به‌روزرسانی شد ✅")
        return

    # اعلان همگانی
    if state == "broadcast_text":
        text = (m.text or "").strip()
        sent = 0
        for uid2 in list(DB["users"].keys()):
            try:
                bot.send_message(int(uid2), f"📢 اعلان:\n\n{text}")
                sent += 1
                time.sleep(0.03)
            except:
                pass
        clear_state(uid)
        bot.reply_to(m, f"ارسال شد ✅ ({sent} کاربر)")
        return

# ---------------------------
# Features
# ---------------------------
def show_my_orders(m: types.Message):
    orders = [o for o in DB["orders"] if int(o["uid"]) == m.from_user.id]
    if not orders:
        bot.send_message(m.chat.id, "هنوز سفارشی ثبت نکردی 🙂")
        return
    lines = []
    for o in sorted(orders, key=lambda x: x["at"], reverse=True)[:15]:
        p = get_plan(o["pid"]) or {}
        tm = datetime.fromtimestamp(o["at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f'🧾 {p.get("name","پلن")} · {fmt_toman(o.get("final",o.get("price",0)))} · {tm}')
    bot.send_message(m.chat.id, "\n".join(lines))

def show_ticket_topics(m: types.Message):
    rows = [
        [("🛍 خرید/مشکل خرید", "t:new:buy"), ("🔧 مشکل فنی", "t:new:tech")],
        [("💳 مالی/پرداخت", "t:new:pay"), ("💬 سایر", "t:new:other")],
        [("🎟 تیکت‌های من", "t:list")]
    ]
    bot.send_message(m.chat.id, "موضوع تیکت رو انتخاب کن:", reply_markup=kb_inline(rows))

@bot.callback_query_handler(func=lambda c: c.data.startswith("t:"))
def ticket_cb(c: types.CallbackQuery):
    uid = c.from_user.id
    data = c.data
    if data == "t:list":
        my = [t for t in DB["tickets"].values() if t["uid"]==uid]
        if not my:
            bot.answer_callback_query(c.id, "تیکتی نداری.", show_alert=True); return
        rows = []
        for t in sorted(my, key=lambda x: x["created_at"], reverse=True)[:10]:
            rows.append([(f'#{t["id"][-5:]} · {t["topic"]}', f"t:view:{t['id']}")])
        rows.append([("⬅️ برگشت", "back:home")])
        bot.edit_message_text("تیکت‌های شما:", c.message.chat.id, c.message.message_id, reply_markup=kb_inline(rows))
        return
    if data.startswith("t:new:"):
        topic = data.split(":")[2]
        tid = str(uuid.uuid4())
        DB["tickets"][tid] = {
            "id": tid,
            "uid": uid,
            "topic": topic,
            "created_at": now_ts(),
            "open": True,
            "messages": []
        }
        save_db()
        set_state(uid, await_state="ticket_msg", ticket_id=tid)
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, f"تیکت #{tid[-5:]} ساخته شد ✅\nپیامت رو بنویس:")
        # خبر به ادمین
        for a in admin_ids():
            try: bot.send_message(a, f"🎫 تیکت جدید از @{c.from_user.username or '-'} · #{tid[-5:]} · موضوع: {topic}")
            except: pass
        return
    if data.startswith("t:view:"):
        tid = data.split(":")[2]
        tk = DB["tickets"].get(tid)
        if not tk or tk["uid"]!=uid:
            bot.answer_callback_query(c.id, "تیکت پیدا نشد.", show_alert=True); return
        txt = ticket_render(tk)
        kb = kb_inline([
            [("✍️ پاسخ", f"t:reply:{tid}"), ("🔒 بستن", f"t:close:{tid}")],
            [("⬅️ برگشت", "t:list")]
        ])
        bot.edit_message_text(txt, c.message.chat.id, c.message.message_id, reply_markup=kb)
        return
    if data.startswith("t:reply:"):
        tid = data.split(":")[2]
        set_state(uid, await_state="ticket_msg", ticket_id=tid)
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "متن پاسخت رو بفرست:")
        return
    if data.startswith("t:close:"):
        tid = data.split(":")[2]
        tk = DB["tickets"].get(tid)
        if tk and tk["uid"]==uid:
            tk["open"] = False
            save_db()
            bot.answer_callback_query(c.id, "تیکت بسته شد.")
            bot.send_message(c.message.chat.id, "🔒 تیکت بسته شد.")
        else:
            bot.answer_callback_query(c.id, "تیکت پیدا نشد.", show_alert=True)
        return

# ادمین هم بتونه پاسخ بده
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and (m.reply_to_message and "#TICKET:" in (m.reply_to_message.text or "")))
def admin_reply_ticket(m: types.Message):
    # ادمین روی پیام تیکت ریپلای کند: متن شامل #TICKET:<id>
    mt = m.reply_to_message.text
    m2 = re.search(r"#TICKET:([0-9a-f\-]+)", mt or "")
    if not m2:
        return
    tid = m2.group(1)
    tk = DB["tickets"].get(tid)
    if not tk:
        bot.reply_to(m, "تیکت پیدا نشد.")
        return
    msg = (m.text or m.caption or "").strip()
    tk["messages"].append({"from_admin": True, "uid": m.from_user.id, "text": msg, "at": now_ts()})
    save_db()
    bot.reply_to(m, "پاسخ ارسال شد ✅")
    try:
        bot.send_message(tk["uid"], f"🟢 پاسخ ادمین به تیکت #{tid[-5:]}:\n\n{msg}")
    except: pass

def ticket_render(tk):
    head = f'#TICKET:{tk["id"]}\n🎫 تیکت #{tk["id"][-5:]} · موضوع: {tk["topic"]} · وضعیت: {"باز" if tk["open"] else "بسته"}'
    lines = []
    for msg in tk["messages"]:
        who = "ادمین" if msg["from_admin"] else "شما"
        tm = datetime.fromtimestamp(msg["at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f'[{tm}] {who}: {msg["text"]}')
    return head + ("\n\n" + "\n".join(lines) if lines else "\n\n— هنوز پیامی ثبت نشده —")

def show_wallet_history(uid, msg):
    # در این نسخه برای سادگی، تاریخچه جدا ثبت نکردیم؛ از orders و receipts استفاده‌ی نمایشی می‌کنیم
    rec = [r for r in DB["receipts"].values() if r["uid"]==uid]
    if not rec:
        bot.send_message(msg.chat.id, "تاریخچه‌ای ثبت نشده.")
        return
    lines = []
    for r in sorted(rec, key=lambda x: x["created_at"], reverse=True)[:15]:
        tm = datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f'#{r["id"][-5:]} · {r["purpose"]} · {r["status"]} · {tm}')
    bot.send_message(msg.chat.id, "\n".join(lines))

def send_config_to_user(uid, pid, item):
    p = get_plan(pid) or {}
    exp = datetime.now() + timedelta(days=int(p.get("days", 30)))
    exp_str = exp.strftime("%Y-%m-%d")
    msg = f'''🎉 ممنون از خریدت!

🛍 پلن: {p.get("name","—")}
⏳ مدت: {p.get("days","—")} روز
📦 حجم: {p.get("gb","—")} GB
⏰ تاریخ انقضا: {exp_str}

———
'''
    try:
        if item.get("photo_id"):
            bot.send_photo(uid, item["photo_id"], caption=msg + (item.get("text") or ""))
        else:
            bot.send_message(uid, msg + (item.get("text") or ""))
    except: pass

# آمار فروش
def send_sales_stats(chat_id):
    total_orders = len(DB["orders"])
    total_income = sum([int(o.get("final", o.get("price", 0))) for o in DB["orders"]])
    # Top Buyers
    spent = {}
    count_orders = {}
    for o in DB["orders"]:
        u = int(o["uid"])
        spent[u] = spent.get(u, 0) + int(o.get("final", o.get("price", 0)))
        count_orders[u] = count_orders.get(u, 0) + 1
    top = sorted(spent.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = [
        f"📊 آمار فروش",
        f"تعداد فروش: {total_orders}",
        f"درآمد کل: {fmt_toman(total_income)}",
        "———",
        "Top Buyers:"
    ]
    for i,(u, s) in enumerate(top, start=1):
        uname = DB["users"].get(str(u), {}).get("username","-")
        lines.append(f"{i}) @{uname} · {count_orders.get(u,0)} خرید · {fmt_toman(s)}")
    bot.send_message(chat_id, "\n".join(lines))

# ---------------------------
# Admin shortcuts via reply keyboard text
# ---------------------------
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text in [
    DEFAULT_STORE["ui"]["btn_admin_plans"],
    DEFAULT_STORE["ui"]["btn_admin_receipts"],
    DEFAULT_STORE["ui"]["btn_admin_wallets"],
    DEFAULT_STORE["ui"]["btn_admin_coupons"],
    DEFAULT_STORE["ui"]["btn_admin_texts"],
    DEFAULT_STORE["ui"]["btn_admin_users"],
    DEFAULT_STORE["ui"]["btn_admin_broadcast"],
    DEFAULT_STORE["ui"]["btn_admin_stats"],
    DEFAULT_STORE["ui"]["btn_admins_manage"],
])
def admin_buttons_router(m: types.Message):
    t = m.text
    if t == DB["ui"]["btn_admin_plans"]:
        bot.send_message(m.chat.id, "مدیریت پلن‌ها و مخزن:", reply_markup=admin_plans_inline_kb()); return
    if t == DB["ui"]["btn_admin_receipts"]:
        bot.send_message(m.chat.id, "رسیدهای در انتظار:", reply_markup=admin_receipts_inline_kb()); return
    if t == DB["ui"]["btn_admin_wallets"]:
        bot.send_message(m.chat.id, "برای مدیریت کیف پول کاربران به «👥 کاربران» برو و روی کاربر کلیک کن."); return
    if t == DB["ui"]["btn_admin_coupons"]:
        bot.send_message(m.chat.id, "مدیریت کدهای تخفیف:", reply_markup=admin_coupons_kb()); return
    if t == DB["ui"]["btn_admin_texts"]:
        bot.send_message(m.chat.id, "مدیریت دکمه‌ها و متن‌ها:", reply_markup=admin_texts_kb()); return
    if t == DB["ui"]["btn_admin_users"]:
        bot.send_message(m.chat.id, "لیست کاربران:", reply_markup=admin_users_kb(0)); return
    if t == DB["ui"]["btn_admin_broadcast"]:
        set_state(m.from_user.id, await_state="broadcast_text")
        bot.send_message(m.chat.id, "متن اعلان همگانی رو بفرست:"); return
    if t == DB["ui"]["btn_admin_stats"]:
        send_sales_stats(m.chat.id); return
    if t == DB["ui"]["btn_admins_manage"]:
        rows = [[("➕ افزودن ادمین", "admadd")]]
        for a in admin_ids():
            rows.append([(f"👑 {a}", f"admdel:{a}")])
        rows.append([("⬅️ برگشت", "back:admin")])
        bot.send_message(m.chat.id, "مدیریت ادمین‌ها:", reply_markup=kb_inline(rows)); return

# ---------------------------
# Run (WSGI entry)
# ---------------------------
# لازم برای gunicorn: app
# bot را با webhook می‌گیریم، نیازی به polling نیست.
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
