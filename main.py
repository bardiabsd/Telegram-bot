# main.py
# -*- coding: utf-8 -*-
import os, json, time, re, threading, datetime
from datetime import datetime, timedelta
from flask import Flask, request, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

# ----------------- ثابت‌ها و تنظیمات پایه -----------------
BOT_TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
APP_URL   = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{APP_URL}{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", "8000"))

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=4)
app = Flask(__name__)

DB_FILE = "db.json"
LOCK = threading.Lock()

# ----------------- ابزار ذخیره‌سازی -----------------
def load_db():
    if not os.path.exists(DB_FILE):
        fresh = {
            "admins": [1743359080],  # ادمین پیش‌فرض
            "settings": {
                "card_number": "---- ---- ---- ----",
                "texts": {},   # متن‌های قابل ویرایش
                "buttons": {   # وضعیت نمایش دکمه‌ها
                    "buy": True,
                    "wallet": True,
                    "tickets": True,
                    "my_account": True,
                    "admin": True,
                }
            },
            "users": {},           # uid -> {wallet:0, history:[], tickets:[{...}]}
            "plans": {},           # plan_id -> {title, days, size, price, desc, repo:[{text, photo_id}], stock:int}
            "coupons": {},         # code -> {percent, for_plan: None|plan_id, expire_at, max_use, used}
            "receipts": {},        # receipt_id -> {by, kind: purchase|wallet, status: pending|approved|rejected, amount, plan_id?, created_at, note}
            "state": {},           # uid -> {awaiting:..., ctx:{...}}
            "sales": []            # [{uid, plan_id, amount, at}]
        }
        save_db(fresh)
        return fresh
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with LOCK:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)

DB = load_db()

def is_admin(uid:int) -> bool:
    return uid in DB["admins"]

def get_user(uid:int):
    if str(uid) not in DB["users"]:
        DB["users"][str(uid)] = {"wallet":0, "history":[], "tickets": []}
        save_db(DB)
    return DB["users"][str(uid)]

def set_state(uid, awaiting=None, ctx=None, clear=False, **extra):
    st = DB["state"].get(str(uid), {})
    if clear:
        st = {}
    if awaiting is not None:
        st["awaiting"] = awaiting
    if ctx is not None:
        base = st.get("ctx", {})
        base.update(ctx)
        st["ctx"] = base
    if extra:
        base = st.get("ctx", {})
        base.update(extra)
        st["ctx"] = base
    DB["state"][str(uid)] = st
    save_db(DB)

def pop_state(uid):
    st = DB["state"].pop(str(uid), None)
    save_db(DB)
    return st or {}

def get_state(uid):
    return DB["state"].get(str(uid), {})

# ----------------- ابزار فرمتی/کمکی -----------------
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
LATIN_DIGITS   = "0123456789"
P2L = str.maketrans("".join(PERSIAN_DIGITS), "".join(LATIN_DIGITS))

def normalize_number(text: str) -> str:
    if text is None: return ""
    t = str(text).strip()
    # تبدیل ارقام فارسی، حذف فاصله/کاما
    t = t.translate(P2L)
    t = re.sub(r"[ ,_]", "", t)
    # فقط عدد و اعشار (درصورت نیاز)
    m = re.match(r"^(\d+)(\.\d+)?$", t)
    if not m:
        return ""
    return t

def fmt_currency(n: int) -> str:
    s = f"{int(n):,}".replace(",", "،")
    return s + " تومان"

def now_iso():
    return datetime.utcnow().isoformat()

# ----------------- کیبوردها -----------------
def kb_main(uid):
    m = InlineKeyboardMarkup()
    btns = DB["settings"]["buttons"]
    if btns.get("buy", True):     m.add(InlineKeyboardButton("🛍 خرید پلن", callback_data="buy"))
    if btns.get("wallet", True):  m.add(InlineKeyboardButton("🪙 کیف پول", callback_data="wallet"))
    if btns.get("tickets", True): m.add(InlineKeyboardButton("🎫 تیکت پشتیبانی", callback_data="tickets"))
    if btns.get("my_account", True): m.add(InlineKeyboardButton("👤 حساب کاربری", callback_data="account"))
    if btns.get("admin", True) and is_admin(uid):
        m.add(InlineKeyboardButton("🛠 پنل ادمین", callback_data="admin"))
    return m

def kb_back_home():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🏠 منو اصلی", callback_data="home"))
    return m

def kb_cancel_only():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return m

# ----------------- متن‌های قابل تغییر -----------------
def T(key, default):
    return DB["settings"]["texts"].get(key, default)

# ----------------- بخش کاربر: شروع -----------------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    get_user(uid)  # ایجاد پروفایل
    bot.send_message(
        uid,
        T("welcome", "سلام! به ربات فروش خوش اومدی 👋\nاز منوی زیر انتخاب کن:"),
        reply_markup=kb_main(uid)
    )

@bot.callback_query_handler(func=lambda c: c.data == "home")
def cb_home(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    bot.edit_message_text(T("home", "منو اصلی:"), uid, c.message.message_id, reply_markup=kb_main(uid))

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id, "لغو شد")
    set_state(uid, clear=True)
    bot.edit_message_text("لغو شد ✅", uid, c.message.message_id, reply_markup=kb_main(uid))

# ----------------- خرید پلن -----------------
def kb_plan_list():
    m = InlineKeyboardMarkup()
    # فقط پلن‌هایی که دکمه‌شان فعال و موجودی > 0 است
    for pid, p in DB["plans"].items():
        stock = p.get("stock", len(p.get("repo", [])))
        title = p["title"]
        label = f"{title} ({stock} موجود)"
        disabled = stock <= 0
        if disabled:
            continue
        m.add(InlineKeyboardButton(label, callback_data=f"plan_{pid}"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="home"))
    return m

@bot.callback_query_handler(func=lambda c: c.data == "buy")
def cb_buy(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not DB["plans"]:
        bot.edit_message_text("هیچ پلنی تعریف نشده.", uid, c.message.message_id, reply_markup=kb_back_home())
        return
    bot.edit_message_text("لیست پلن‌ها:", uid, c.message.message_id, reply_markup=kb_plan_list())

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_"))
def cb_plan_detail(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    pid = c.data.split("_",1)[1]
    p = DB["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن نامعتبر")
        return
    price = p["price"]
    desc = p.get("desc","")
    days = p.get("days")
    size = p.get("size")
    stock = p.get("stock", len(p.get("repo", [])))
    txt = f"📦 {p['title']}\n⏱ مدت: {days} روز\n📶 حجم: {size}\n💰 قیمت: {fmt_currency(price)}\n📦 موجودی: {stock}\n\n{desc}"
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🎟 اعمال کد تخفیف", callback_data=f"coupon_{pid}"))
    m.add(InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data=f"pay_cc_{pid}"))
    m.add(InlineKeyboardButton("🪙 خرید با کیف پول", callback_data=f"pay_w_{pid}"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="buy"))
    bot.edit_message_text(txt, uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("coupon_"))
def cb_coupon(c):
    uid = c.from_user.id
    pid = c.data.split("_",1)[1]
    bot.answer_callback_query(c.id)
    p = DB["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن نامعتبر")
        return
    set_state(uid, awaiting="coupon_enter", ctx={"plan_id": pid})
    bot.send_message(uid, "کد تخفیف را ارسال کنید:", reply_markup=kb_cancel_only())

def apply_coupon(pid, code):
    c = DB["coupons"].get(code)
    if not c: return (False, "کد نامعتبر")
    # انقضا/تعداد/پلن
    if c.get("expire_at") and datetime.fromisoformat(c["expire_at"]) < datetime.utcnow():
        return (False, "این کد منقضی شده.")
    if c.get("max_use") is not None and c.get("used",0) >= c["max_use"]:
        return (False, "سقف استفاده از این کد پر شده.")
    allowed = (c.get("for_plan") in (None, pid))
    if not allowed: return (False, "این کد برای این پلن معتبر نیست.")
    return (True, c["percent"])

def consume_coupon(code):
    if code in DB["coupons"]:
        DB["coupons"][code]["used"] = DB["coupons"][code].get("used",0) + 1
        save_db(DB)

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="coupon_enter")
def msg_coupon(m):
    uid = m.from_user.id
    st = get_state(uid)
    pid = st.get("ctx",{}).get("plan_id")
    p = DB["plans"].get(pid)
    if not p:
        set_state(uid, clear=True)
        bot.reply_to(m, "پلن پیدا نشد.")
        return
    code = m.text.strip()
    ok, data = apply_coupon(pid, code)
    if not ok:
        bot.reply_to(m, data, reply_markup=kb_cancel_only())
        return
    percent = int(data)
    price = p["price"]
    off = (price * percent)//100
    final = price - off
    set_state(uid, awaiting=None, ctx={"coupon_code": code, "final_price": final})
    bot.reply_to(m, f"✅ کد اعمال شد: {percent}%\nمبلغ نهایی: {fmt_currency(final)}", reply_markup=kb_back_home())

@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_cc_"))
def cb_pay_cc(c):
    uid = c.from_user.id
    pid = c.data.split("_", 2)[2]
    bot.answer_callback_query(c.id)
    p = DB["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن نامعتبر")
        return
    # محاسبه مبلغ نهایی (اگر کوپن ذخیره داریم)
    st = get_state(uid)
    final = st.get("ctx",{}).get("final_price", p["price"])
    set_state(uid, awaiting="receipt_purchase", ctx={"purchase_plan": pid, "expected_amount": final})
    card = DB["settings"]["card_number"]
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    bot.edit_message_text(
        f"💳 کارت‌به‌کارت\n\nشماره کارت: {card}\nمبلغ: {fmt_currency(final)}\n\nپس از واریز، رسید را به‌صورت عکس/متن ارسال کنید.",
        uid, c.message.message_id, reply_markup=m
    )

@bot.message_handler(content_types=["text", "photo"])
def msg_router(m):
    uid = m.from_user.id
    st = get_state(uid)
    aw = st.get("awaiting")
    # رسید خرید/شارژ
    if aw in ("receipt_purchase","receipt_wallet"):
        handle_receipt_message(m, kind=("purchase" if aw=="receipt_purchase" else "wallet"))
        return
    # ورودی‌های چندمرحله‌ای ادمین/…:
    handle_flow_inputs(m)

def handle_receipt_message(m, kind):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    expected = st.get("expected_amount")
    rid = f"r{int(time.time()*1000)}"
    DB["receipts"][rid] = {
        "by": uid,
        "kind": kind,
        "status": "pending",
        "amount": expected,
        "plan_id": st.get("purchase_plan"),
        "created_at": now_iso(),
        "note": (m.caption if m.caption else (m.text if m.content_type=="text" else "")),
    }
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین…")
    # اطلاع به ادمین‌ها
    push_to_admins_receipt_inbox(rid)

def push_to_admins_receipt_inbox(rid):
    r = DB["receipts"][rid]
    uid = r["by"]
    u = get_user(uid)
    txt = (
        f"🧾 رسید جدید ({'خرید کانفیگ' if r['kind']=='purchase' else 'شارژ کیف پول'})\n"
        f"کاربر: @{get_username(uid)} (ID: {uid})\n"
        f"تعداد خریدهای قبلی: {len(u['history'])}\n"
        f"مبلغ: {fmt_currency(r.get('amount',0))}\n"
        f"کد رسید: {rid}"
    )
    m = InlineKeyboardMarkup()
    if r["kind"]=="purchase":
        m.add(InlineKeyboardButton("✅ تأیید و ارسال کانفیگ", callback_data=f"rc_ok_{rid}"))
    else:
        m.add(InlineKeyboardButton("✅ تأیید شارژ کیف پول", callback_data=f"rc_ok_{rid}"))
    m.add(InlineKeyboardButton("❌ رد رسید", callback_data=f"rc_no_{rid}"))
    for ad in DB["admins"]:
        try: bot.send_message(ad, txt, reply_markup=m)
        except: pass

def get_username(uid):
    # تلاش برای بازیابی username از آخرین آپدیت‌ها (ساده)
    try:
        # اگر قبلاً در state ذخیره شده باشد
        return DB["users"][str(uid)].get("username","")
    except:
        return ""

@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_w_"))
def cb_pay_wallet(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    pid = c.data.split("_",2)[2]
    p = DB["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن نامعتبر")
        return
    st = get_state(uid)
    final = st.get("ctx",{}).get("final_price", p["price"])
    wallet = get_user(uid)["wallet"]
    if wallet >= final:
        # پرداخت مستقیم
        get_user(uid)["wallet"] -= final
        save_db(DB)
        deliver_config(uid, pid)
        DB["sales"].append({"uid": uid, "plan_id": pid, "amount": final, "at": now_iso()})
        save_db(DB)
        consume_coupon(st.get("ctx",{}).get("coupon_code"))
        set_state(uid, clear=True)
        bot.edit_message_text("پرداخت با کیف پول انجام شد ✅\nکانفیگ ارسال شد.", uid, c.message.message_id, reply_markup=kb_back_home())
    else:
        diff = final - wallet
        m = InlineKeyboardMarkup()
        m.add(InlineKeyboardButton(f"شارژ همین مقدار ({fmt_currency(diff)})", callback_data=f"charge_diff_{pid}_{diff}"))
        m.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
        bot.edit_message_text(
            f"موجودی کیف پول شما کافی نیست.\n"
            f"موجودی: {fmt_currency(wallet)}\n"
            f"مبلغ نهایی: {fmt_currency(final)}\n"
            f"مابه‌التفاوت: {fmt_currency(diff)}",
            uid, c.message.message_id, reply_markup=m
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("charge_diff_"))
def cb_charge_diff(c):
    uid = c.from_user.id
    _, pid, diff = c.data.split("_", 2)
    diff = int(diff)
    bot.answer_callback_query(c.id)
    set_state(uid, awaiting="receipt_wallet", ctx={"expected_amount": diff, "purchase_plan": pid})
    bot.edit_message_text(
        f"برای تکمیل خرید، مبلغ {fmt_currency(diff)} را کارت‌به‌کارت کنید و رسید را ارسال کنید.",
        uid, c.message.message_id, reply_markup=kb_cancel_only()
    )

def deliver_config(uid, pid):
    p = DB["plans"][pid]
    # برداشت از مخزن
    repo = p.get("repo", [])
    if not repo:
        bot.send_message(uid, "⚠️ مخزن این پلن خالی است؛ لطفاً به پشتیبانی اطلاع دهید.")
        return
    item = repo.pop(0)
    p["stock"] = p.get("stock", len(repo))
    save_db(DB)
    # ارسال
    text = item.get("text","")
    photo = item.get("photo_id")
    if photo:
        bot.send_photo(uid, photo, caption=text or " ")
    else:
        bot.send_message(uid, text or " ")
    # ثبت در تاریخچه
    u = get_user(uid)
    u["history"].append({"pid": pid, "at": now_iso(), "title": p["title"]})
    save_db(DB)
    # نوتی پایان اعتبار (۳ روز مانده)
    days = p.get("days",0)
    if days:
        expire_at = datetime.utcnow() + timedelta(days=days)
        # اینجا می‌تونید تسک زمان‌بندی‌شدهٔ واقعی اضافه کنید؛ ما فعلاً فقط ذخیره می‌کنیم
        u["last_expire_at"] = expire_at.isoformat()
        save_db(DB)

# ----------------- کیف پول کاربر -----------------
@bot.callback_query_handler(func=lambda c: c.data=="wallet")
def cb_wallet(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    bal = get_user(uid)["wallet"]
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ شارژ کیف پول (ارسال رسید)", callback_data="wallet_charge"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="home"))
    bot.edit_message_text(f"موجودی فعلی: {fmt_currency(bal)}", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data=="wallet_charge")
def cb_wallet_charge(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    set_state(uid, awaiting="receipt_wallet", ctx={"expected_amount": None})
    card = DB["settings"]["card_number"]
    bot.edit_message_text(
        f"برای شارژ کیف پول، مبلغ موردنظر را کارت‌به‌کارت کنید و رسید را ارسال کنید.\nشماره کارت: {card}",
        uid, c.message.message_id, reply_markup=kb_cancel_only()
    )

# ----------------- تیکت پشتیبانی -----------------
@bot.callback_query_handler(func=lambda c: c.data=="tickets")
def cb_tickets(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🆕 ایجاد تیکت جدید", callback_data="tk_new"))
    m.add(InlineKeyboardButton("📂 تیکت‌های من", callback_data="tk_list"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="home"))
    bot.edit_message_text("پشتیبانی:", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data=="tk_new")
def cb_tk_new(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    set_state(uid, awaiting="ticket_subject")
    bot.edit_message_text("موضوع تیکت را بنویسید:", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="ticket_subject")
def msg_tk_subject(m):
    uid = m.from_user.id
    sub = m.text.strip()
    set_state(uid, awaiting="ticket_body", ctx={"ticket_subject": sub})
    bot.reply_to(m, "متن تیکت را بفرستید (می‌توانید چندین کلمه و جمله بنویسید):", reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="ticket_body")
def msg_tk_body(m):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    sub = st.get("ticket_subject","(بدون موضوع)")
    body = m.text if m.text else (m.caption or "")
    tik = {"id": f"t{int(time.time()*1000)}", "subject": sub, "body": body, "status": "open", "created_at": now_iso(), "replies":[]}
    get_user(uid)["tickets"].append(tik)
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, f"تیکت ثبت شد ✅\nکد تیکت: {tik['id']}")

@bot.callback_query_handler(func=lambda c: c.data=="tk_list")
def cb_tk_list(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    ts = get_user(uid)["tickets"]
    if not ts:
        bot.edit_message_text("تیکتی ندارید.", uid, c.message.message_id, reply_markup=kb_back_home())
        return
    lines = []
    for t in ts[-10:][::-1]:
        lines.append(f"#{t['id']} | {t['subject']} | وضعیت: {t['status']}")
    bot.edit_message_text("\n".join(lines), uid, c.message.message_id, reply_markup=kb_back_home())

# ----------------- حساب کاربری -----------------
@bot.callback_query_handler(func=lambda c: c.data=="account")
def cb_account(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    u = get_user(uid)
    cnt = len(u["history"])
    bot.edit_message_text(
        f"👤 آیدی: {uid}\n"
        f"📛 یوزرنیم: @{get_username(uid)}\n"
        f"🧾 تعداد کانفیگ‌های خریداری‌شده: {cnt}",
        uid, c.message.message_id,
        reply_markup=kb_back_home()
    )

# ----------------- ادمین -----------------
def kb_admin():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("👥 مدیریت ادمین‌ها", callback_data="ad_admins"))
    m.add(InlineKeyboardButton("📦 پلن‌ها و مخزن", callback_data="ad_plans"))
    m.add(InlineKeyboardButton("🎟 کد تخفیف", callback_data="ad_coupons"))
    m.add(InlineKeyboardButton("🪙 کیف پول (تأیید رسید/شارژ دستی)", callback_data="ad_wallet"))
    m.add(InlineKeyboardButton("🧾 رسیدها", callback_data="ad_receipts"))
    m.add(InlineKeyboardButton("🧰 متن‌ها و دکمه‌ها", callback_data="ad_texts"))
    m.add(InlineKeyboardButton("📢 اعلان همگانی", callback_data="ad_broadcast"))
    m.add(InlineKeyboardButton("📊 آمار فروش", callback_data="ad_stats"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="home"))
    return m

@bot.callback_query_handler(func=lambda c: c.data=="admin")
def cb_admin(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "دسترسی ادمین ندارید.")
        return
    bot.edit_message_text("🛠 پنل ادمین:", uid, c.message.message_id, reply_markup=kb_admin())

# ---- مدیریت ادمین‌ها ----
@bot.callback_query_handler(func=lambda c: c.data=="ad_admins")
def cb_ad_admins(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    lst = ", ".join([str(x) for x in DB["admins"]])
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ افزودن ادمین", callback_data="ad_admin_add"))
    m.add(InlineKeyboardButton("➖ حذف ادمین", callback_data="ad_admin_del"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="admin"))
    bot.edit_message_text(f"ادمین‌ها: {lst}", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data=="ad_admin_add")
def cb_ad_admin_add(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    set_state(uid, awaiting="add_admin_id")
    bot.edit_message_text("آیدی عددی کاربر را بفرستید:", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="add_admin_id")
def msg_ad_admin_add_id(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    val = normalize_number(m.text)
    if not val:
        bot.reply_to(m, "ورودی نامعتبر. فقط عدد بفرستید.")
        return
    nid = int(float(val))
    if nid not in DB["admins"]:
        DB["admins"].append(nid)
        save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, f"✅ {nid} ادمین شد.", reply_markup=kb_back_home())

@bot.callback_query_handler(func=lambda c: c.data=="ad_admin_del")
def cb_ad_admin_del(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    set_state(uid, awaiting="del_admin_id")
    bot.edit_message_text("آیدی عددی ادمین برای حذف:", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="del_admin_id")
def msg_ad_admin_del_id(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    val = normalize_number(m.text)
    if not val: bot.reply_to(m, "نامعتبر"); return
    nid = int(float(val))
    if nid in DB["admins"]:
        DB["admins"].remove(nid)
        save_db(DB)
        bot.reply_to(m, f"✅ {nid} از ادمین‌ها حذف شد.")
    else:
        bot.reply_to(m, "پیدا نشد.")
    set_state(uid, clear=True)

# ---- پلن‌ها و مخزن ----
def kb_ad_plans():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ افزودن پلن", callback_data="pl_add"))
    m.add(InlineKeyboardButton("📝 ویرایش/حذف پلن", callback_data="pl_edit"))
    m.add(InlineKeyboardButton("📥 مدیریت مخزن", callback_data="pl_repo"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="admin"))
    return m

@bot.callback_query_handler(func=lambda c: c.data=="ad_plans")
def cb_ad_plans(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    bot.edit_message_text("مدیریت پلن‌ها:", uid, c.message.message_id, reply_markup=kb_ad_plans())

@bot.callback_query_handler(func=lambda c: c.data=="pl_add")
def cb_pl_add(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    set_state(uid, awaiting="pl_add_title", ctx={"tmp":{}})
    bot.edit_message_text("نام پلن:", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="pl_add_title")
def msg_pl_add_title(m):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    st.setdefault("tmp",{})["title"] = m.text.strip()
    set_state(uid, awaiting="pl_add_days", ctx=st)
    bot.reply_to(m, "مدت (روز):")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="pl_add_days")
def msg_pl_add_days(m):
    uid = m.from_user.id
    val = normalize_number(m.text)
    if not val: bot.reply_to(m, "فقط عدد."); return
    st = get_state(uid).get("ctx",{})
    st["tmp"]["days"] = int(float(val))
    set_state(uid, awaiting="pl_add_size", ctx=st)
    bot.reply_to(m, "حجم (مثلاً 100GB):")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="pl_add_size")
def msg_pl_add_size(m):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    st["tmp"]["size"] = m.text.strip()
    set_state(uid, awaiting="pl_add_price", ctx=st)
    bot.reply_to(m, "قیمت (تومان):")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="pl_add_price")
def msg_pl_add_price(m):
    uid = m.from_user.id
    val = normalize_number(m.text)
    if not val: bot.reply_to(m, "عدد نامعتبر."); return
    st = get_state(uid).get("ctx",{})
    st["tmp"]["price"] = int(float(val))
    set_state(uid, awaiting="pl_add_desc", ctx=st)
    bot.reply_to(m, "توضیحات:")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="pl_add_desc")
def msg_pl_add_desc(m):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    tmp = st["tmp"]
    tmp["desc"] = m.text.strip()
    pid = f"p{int(time.time()*1000)}"
    DB["plans"][pid] = {
        "title": tmp["title"], "days": tmp["days"], "size": tmp["size"], "price": tmp["price"],
        "desc": tmp["desc"], "repo": [], "stock": 0
    }
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, f"✅ پلن ایجاد شد: {tmp['title']} (ID: {pid})", reply_markup=kb_back_home())

@bot.callback_query_handler(func=lambda c: c.data=="pl_repo")
def cb_pl_repo(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    if not DB["plans"]:
        bot.edit_message_text("پلنی وجود ندارد.", uid, c.message.message_id, reply_markup=kb_back_home())
        return
    m = InlineKeyboardMarkup()
    for pid, p in DB["plans"].items():
        m.add(InlineKeyboardButton(f"{p['title']} (repo:{len(p['repo'])})", callback_data=f"repo_{pid}"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="ad_plans"))
    bot.edit_message_text("یک پلن برای مدیریت مخزن انتخاب کنید:", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("repo_"))
def cb_repo_plan(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    pid = c.data.split("_",1)[1]
    p = DB["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن نامعتبر"); return
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ افزودن کانفیگ به مخزن", callback_data=f"repo_add_{pid}"))
    m.add(InlineKeyboardButton("🗑 حذف یکی از ابتدای صف", callback_data=f"repo_pop_{pid}"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="pl_repo"))
    bot.edit_message_text(f"مدیریت مخزن: {p['title']} (موجودی:{len(p['repo'])})", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("repo_add_"))
def cb_repo_add(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    pid = c.data.split("_",2)[2]
    set_state(uid, awaiting="repo_add", ctx={"pid":pid})
    bot.edit_message_text("متن کانفیگ را بفرستید (می‌توانید عکس با کپشن هم بفرستید):", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="repo_add", content_types=["text","photo"])
def msg_repo_add(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    st = get_state(uid).get("ctx",{})
    pid = st.get("pid")
    p = DB["plans"].get(pid)
    if not p:
        set_state(uid, clear=True); bot.reply_to(m,"پلن نامعتبر"); return
    item = {}
    if m.content_type=="photo":
        item["photo_id"] = m.photo[-1].file_id
        item["text"] = m.caption or ""
    else:
        item["text"] = m.text
    p["repo"].append(item)
    p["stock"] = len(p["repo"])
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, f"✅ یک مورد به مخزن {p['title']} اضافه شد. موجودی: {p['stock']}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("repo_pop_"))
def cb_repo_pop(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    pid = c.data.split("_",2)[2]
    p = DB["plans"].get(pid)
    if not p: return
    if p["repo"]:
        p["repo"].pop(0)
        p["stock"] = len(p["repo"])
        save_db(DB)
        bot.edit_message_text(f"اولین مورد حذف شد. موجودی جدید: {p['stock']}", uid, c.message.message_id, reply_markup=kb_back_home())
    else:
        bot.edit_message_text("مخزن خالی است.", uid, c.message.message_id, reply_markup=kb_back_home())

# ---- کد تخفیف ----
@bot.callback_query_handler(func=lambda c: c.data=="ad_coupons")
def cb_ad_coupons(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ ساخت کد جدید (مرحله‌ای)", callback_data="cp_new"))
    if DB["coupons"]:
        m.add(InlineKeyboardButton("🗂 لیست کدها", callback_data="cp_list"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="admin"))
    bot.edit_message_text("مدیریت کد تخفیف:", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data=="cp_new")
def cb_cp_new(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    set_state(uid, awaiting="cp_percent", ctx={"coupon":{}})
    bot.edit_message_text("درصد تخفیف را بفرستید (مثلاً 20):", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="cp_percent")
def msg_cp_percent(m):
    uid = m.from_user.id
    val = normalize_number(m.text)
    if not val: bot.reply_to(m, "درصد نامعتبر."); return
    st = get_state(uid).get("ctx",{})
    st["coupon"]["percent"] = int(float(val))
    set_state(uid, awaiting="cp_plan_scope", ctx=st)
    bot.reply_to(m, "برای همه پلن‌ها؟ (بله/خیر)\nاگر «خیر»، آیدی پلن را بعداً می‌گیریم.")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="cp_plan_scope")
def msg_cp_plan_scope(m):
    uid = m.from_user.id
    text = (m.text or "").strip()
    st = get_state(uid).get("ctx",{})
    if text in ["بله","بلی","آره","yes","Yes","YES"]:
        st["coupon"]["for_plan"] = None
        set_state(uid, awaiting="cp_expire", ctx=st)
        bot.reply_to(m, "تاریخ انقضا را به‌صورت YYYY-MM-DD یا «ندارد» بفرستید:")
    else:
        set_state(uid, awaiting="cp_plan_id", ctx=st)
        bot.reply_to(m, "آیدی پلن هدف را بفرستید:")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="cp_plan_id")
def msg_cp_plan_id(m):
    uid = m.from_user.id
    pid = (m.text or "").strip()
    if pid not in DB["plans"]:
        bot.reply_to(m, "پلن نامعتبر. آیدی دقیق پلن را بفرستید.")
        return
    st = get_state(uid).get("ctx",{})
    st["coupon"]["for_plan"] = pid
    set_state(uid, awaiting="cp_expire", ctx=st)
    bot.reply_to(m, "تاریخ انقضا را به‌صورت YYYY-MM-DD یا «ندارد» بفرستید:")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="cp_expire")
def msg_cp_expire(m):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    t = (m.text or "").strip()
    if t in ["ندارد","none","None","-","بدون"]:
        st["coupon"]["expire_at"] = None
    else:
        try:
            dt = datetime.strptime(t, "%Y-%m-%d")
            st["coupon"]["expire_at"] = dt.isoformat()
        except:
            bot.reply_to(m, "فرمت تاریخ اشتباه است. مثلاً 2025-12-31"); return
    set_state(uid, awaiting="cp_max_use", ctx=st)
    bot.reply_to(m, "سقف تعداد استفاده (مثلاً 100) یا «نامحدود»:")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="cp_max_use")
def msg_cp_max_use(m):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    t = (m.text or "").strip()
    if t in ["نامحدود","نامحدود.","بی‌نهایت","none","None","-"]:
        st["coupon"]["max_use"] = None
    else:
        val = normalize_number(t)
        if not val: bot.reply_to(m, "عدد نامعتبر."); return
        st["coupon"]["max_use"] = int(float(val))
    set_state(uid, awaiting="cp_name", ctx=st)
    bot.reply_to(m, "نام/کد دلخواه برای این کد تخفیف:")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="cp_name")
def msg_cp_name(m):
    uid = m.from_user.id
    st = get_state(uid).get("ctx",{})
    code = (m.text or "").strip()
    if not code: bot.reply_to(m, "کد نامعتبر."); return
    c = st["coupon"]
    DB["coupons"][code] = {
        "percent": c["percent"],
        "for_plan": c["for_plan"],
        "expire_at": c["expire_at"],
        "max_use": c["max_use"],
        "used": 0
    }
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, f"✅ کد ساخته شد: {code}")

@bot.callback_query_handler(func=lambda c: c.data=="cp_list")
def cb_cp_list(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    lines = []
    for code, cc in DB["coupons"].items():
        for_plan = cc["for_plan"] or "همه"
        exp = cc["expire_at"] or "ندارد"
        used = cc.get("used",0)
        mx   = cc.get("max_use","نامحدود")
        lines.append(f"{code} → {cc['percent']}% | پلن: {for_plan} | انقضا: {exp} | استفاده: {used}/{mx}")
    bot.edit_message_text("\n".join(lines) if lines else "هیچ کدی نیست.", uid, c.message.message_id, reply_markup=kb_back_home())

# ---- کیف پول ادمین / رسیدها ----
@bot.callback_query_handler(func=lambda c: c.data=="ad_wallet")
def cb_ad_wallet(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("📥 رسیدهای در انتظار", callback_data="rc_pending"))
    m.add(InlineKeyboardButton("💰 شارژ/کسر دستی کیف پول", callback_data="wl_manual"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="admin"))
    bot.edit_message_text("کیف پول ادمین:", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data=="rc_pending")
def cb_rc_pending(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    pend = [ (rid,r) for rid,r in DB["receipts"].items() if r["status"]=="pending" ]
    if not pend:
        bot.edit_message_text("هیچ رسید در انتظاری نیست.", uid, c.message.message_id, reply_markup=kb_back_home())
        return
    for rid, r in pend[:15]:
        txt = f"🧾 {rid} | {('خرید' if r['kind']=='purchase' else 'شارژ')} | {fmt_currency(r.get('amount',0))} | کاربر: {r['by']}"
        m = InlineKeyboardMarkup()
        if r["kind"]=="purchase":
            m.add(InlineKeyboardButton("✅ تأیید و ارسال کانفیگ", callback_data=f"rc_ok_{rid}"))
        else:
            m.add(InlineKeyboardButton("✅ تأیید شارژ کیف پول", callback_data=f"rc_ok_{rid}"))
        m.add(InlineKeyboardButton("❌ رد رسید", callback_data=f"rc_no_{rid}"))
        try: bot.send_message(uid, txt, reply_markup=m)
        except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("rc_ok_"))
def cb_rc_ok(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    rid = c.data.split("_",2)[2]
    r = DB["receipts"].get(rid)
    if not r or r["status"]!="pending":
        bot.answer_callback_query(c.id, "یافت نشد/رسیدگی شده.")
        return
    if r["kind"]=="wallet":
        # از ادمین مبلغ واقعی را بگیریم (اگر در رسید نبود)
        amt = r.get("amount")
        set_state(uid, awaiting="wallet_charge_amount_confirm", ctx={"rid": rid, "default": amt})
        bot.edit_message_text(f"مبلغ شارژ را وارد کنید (پیشنهاد: {fmt_currency(amt or 0)}):", uid, c.message.message_id)
    else:
        # خرید: ارسال کانفیگ و ثبت فروش
        pid = r.get("plan_id")
        to_uid = r["by"]
        amt = r.get("amount", DB["plans"].get(pid,{}).get("price",0))
        deliver_config(to_uid, pid)
        DB["sales"].append({"uid": to_uid, "plan_id": pid, "amount": amt, "at": now_iso()})
        r["status"]="approved"
        save_db(DB)
        try: bot.send_message(to_uid, "خرید شما تأیید شد و کانفیگ ارسال شد ✅")
        except: pass
        bot.edit_message_text("✅ انجام شد.", uid, c.message.message_id)

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="wallet_charge_amount_confirm")
def msg_wallet_charge_amount_confirm(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    st = get_state(uid).get("ctx",{})
    rid = st.get("rid")
    r = DB["receipts"].get(rid)
    if not r: bot.reply_to(m,"رسید نامعتبر"); set_state(uid, clear=True); return
    val = normalize_number(m.text)
    if not val: bot.reply_to(m,"عدد نامعتبر"); return
    amt = int(float(val))
    to_uid = r["by"]
    u = get_user(to_uid)
    u["wallet"] += amt
    r["status"]="approved"
    save_db(DB)
    set_state(uid, clear=True)
    try: bot.send_message(to_uid, f"شارژ کیف پول شما تأیید شد: +{fmt_currency(amt)} ✅")
    except: pass
    bot.reply_to(m, "✅ اعمال شد.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("rc_no_"))
def cb_rc_no(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    rid = c.data.split("_",2)[2]
    r = DB["receipts"].get(rid)
    if not r or r["status"]!="pending":
        bot.answer_callback_query(c.id, "یافت نشد/رسیدگی شده.")
        return
    r["status"]="rejected"
    save_db(DB)
    try: bot.send_message(r["by"], "رسید شما رد شد. برای پیگیری با پشتیبانی در تماس باشید.")
    except: pass
    bot.edit_message_text("رد شد.", uid, c.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data=="wl_manual")
def cb_wl_manual(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    set_state(uid, awaiting="wl_manual_target")
    bot.edit_message_text("آیدی عددی کاربر:", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="wl_manual_target")
def msg_wl_manual_target(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    val = normalize_number(m.text)
    if not val: bot.reply_to(m, "نامعتبر"); return
    nid = int(float(val))
    set_state(uid, awaiting="wl_manual_amount", ctx={"target_uid": nid})
    bot.reply_to(m, "مبلغ مثبت برای شارژ، منفی برای کسر. مثال: 200000 یا -50000")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="wl_manual_amount")
def msg_wl_manual_amount(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    t = (m.text or "").strip().replace("٬","").replace("،","").replace(",","")
    t = t.translate(P2L)
    if not re.match(r"^-?\d+$", t):
        bot.reply_to(m, "عدد نامعتبر (می‌تواند منفی باشد)."); return
    amt = int(t)
    st = get_state(uid).get("ctx",{})
    target = int(st.get("target_uid"))
    u = get_user(target)
    u["wallet"] += amt
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, f"✅ اعمال شد. موجودی جدید کاربر {target}: {fmt_currency(u['wallet'])}")

# ---- رسیدها (نمایش کلی) ----
@bot.callback_query_handler(func=lambda c: c.data=="ad_receipts")
def cb_ad_receipts(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    pend = [rid for rid,r in DB["receipts"].items() if r["status"]=="pending"]
    bot.edit_message_text(f"رسیدهای در انتظار: {len(pend)}\nبرای رسیدهای جدید، پیام جداگانه دریافت می‌کنید.", uid, c.message.message_id, reply_markup=kb_back_home())

# ---- متن‌ها و دکمه‌ها ----
@bot.callback_query_handler(func=lambda c: c.data=="ad_texts")
def cb_ad_texts(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("📝 ویرایش متن‌ها", callback_data="tx_edit"))
    m.add(InlineKeyboardButton("🎛 روشن/خاموش کردن دکمه‌ها", callback_data="tx_buttons"))
    m.add(InlineKeyboardButton("💳 ویرایش شماره کارت", callback_data="tx_card"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="admin"))
    bot.edit_message_text("تنظیمات نمایش:", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data=="tx_edit")
def cb_tx_edit(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    keys = ["welcome","home"]
    m = InlineKeyboardMarkup()
    for k in keys:
        m.add(InlineKeyboardButton(f"ویرایش: {k}", callback_data=f"tx_key_{k}"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="ad_texts"))
    bot.edit_message_text("یک متن را انتخاب کنید:", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tx_key_"))
def cb_tx_key(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    key = c.data.split("_",2)[2]
    set_state(uid, awaiting="tx_edit_value", ctx={"key": key})
    bot.edit_message_text(f"متن جدید برای «{key}» را ارسال کنید:", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="tx_edit_value")
def msg_tx_edit_value(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    st = get_state(uid).get("ctx",{})
    key = st.get("key")
    DB["settings"]["texts"][key] = m.text
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, "✅ ذخیره شد.", reply_markup=kb_back_home())

@bot.callback_query_handler(func=lambda c: c.data=="tx_buttons")
def cb_tx_buttons(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    btns = DB["settings"]["buttons"]
    m = InlineKeyboardMarkup()
    for k, v in btns.items():
        sign = "🟢" if v else "⚪️"
        m.add(InlineKeyboardButton(f"{sign} {k}", callback_data=f"btn_toggle_{k}"))
    m.add(InlineKeyboardButton("🔙 برگشت", callback_data="ad_texts"))
    bot.edit_message_text("وضعیت دکمه‌ها:", uid, c.message.message_id, reply_markup=m)

@bot.callback_query_handler(func=lambda c: c.data.startswith("btn_toggle_"))
def cb_btn_toggle(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    key = c.data.split("_",2)[2]
    cur = DB["settings"]["buttons"].get(key, True)
    DB["settings"]["buttons"][key] = not cur
    save_db(DB)
    cb_tx_buttons(c)

@bot.callback_query_handler(func=lambda c: c.data=="tx_card")
def cb_tx_card(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    set_state(uid, awaiting="set_card")
    bot.edit_message_text("شماره کارت جدید را بفرستید (۴*۴ یا بدون فاصله):", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="set_card")
def msg_set_card(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    t = re.sub(r"\D","", m.text or "")
    if len(t) not in (16,19):  # 19 در صورت داشتن کاراکترهای خاص
        bot.reply_to(m,"شماره کارت نامعتبر."); return
    # فرمت 4-4-4-4
    t = re.sub(r"\D","", t)
    fmt = " ".join([t[i:i+4] for i in range(0, len(t), 4)])
    DB["settings"]["card_number"] = fmt
    save_db(DB)
    set_state(uid, clear=True)
    bot.reply_to(m, f"✅ ثبت شد: {fmt}")

# ---- اعلان همگانی ----
@bot.callback_query_handler(func=lambda c: c.data=="ad_broadcast")
def cb_broadcast(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    set_state(uid, awaiting="bc_text")
    bot.edit_message_text("متن پیام همگانی را ارسال کنید:", uid, c.message.message_id, reply_markup=kb_cancel_only())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="bc_text")
def msg_broadcast(m):
    uid = m.from_user.id
    if not is_admin(uid): return
    text = m.text if m.text else (m.caption or "")
    cnt = 0
    for uid_str in list(DB["users"].keys()):
        try: bot.send_message(int(uid_str), text); cnt += 1
        except: pass
    set_state(uid, clear=True)
    bot.reply_to(m, f"✅ برای {cnt} نفر ارسال شد.")

# ---- آمار فروش ----
@bot.callback_query_handler(func=lambda c: c.data=="ad_stats")
def cb_stats(c):
    uid = c.from_user.id
    bot.answer_callback_query(c.id)
    if not is_admin(uid): return
    sales = DB["sales"]
    total_amount = sum(s["amount"] for s in sales)
    total_count  = len(sales)
    # top buyers
    agg = {}
    for s in sales:
        u = s["uid"]; agg[u] = agg.get(u,0)+s["amount"]
    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = [
        f"📊 آمار فروش",
        f"کل فروش (تعداد کانفیگ): {total_count}",
        f"کل فروش (تومان): {fmt_currency(total_amount)}",
        "",
        "Top Buyers:"
    ]
    for uid2, amt in top:
        cnt_u = len([s for s in sales if s["uid"]==uid2])
        lines.append(f"- {uid2}: {cnt_u} خرید | {fmt_currency(amt)}")
    bot.edit_message_text("\n".join(lines), uid, c.message.message_id, reply_markup=kb_back_home())

# ----------------- هندلر ورودی‌های عمومی (fallback) -----------------
def handle_flow_inputs(m):
    # اگر state تعریف نشده بود یا دستور ناشناس بود، نمایش منو
    if m.text and m.text.startswith("/"):
        return
    # آپدیت username برای نمایش‌های بعدی
    try:
        if m.from_user.username:
            get_user(m.from_user.id)["username"] = m.from_user.username
            save_db(DB)
    except:
        pass
    if not get_state(m.from_user.id).get("awaiting"):
        bot.reply_to(m, "از منوی دکمه‌ای استفاده کنید:", reply_markup=kb_main(m.from_user.id))

# ----------------- وب‌هوک و WSGI -----------------
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

def set_webhook_once():
    try:
        bot.delete_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print("Failed to set webhook:", e)

# --------- اپ WSGI برای گونیicorn ---------
def app_factory():
    return app

app = app_factory()

# ست وب‌هوک حین استارت
t = threading.Thread(target=set_webhook_once, daemon=True)
t.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
