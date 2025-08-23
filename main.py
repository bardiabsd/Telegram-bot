# -*- coding: utf-8 -*-
import os
import json
import re
import time
from datetime import datetime
from flask import Flask, request, abort
import telebot
from telebot.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardRemove)

# -----------------------------
# تنظیمات اصلی (env اولویت دارد)
# -----------------------------
DEFAULT_BOT_TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
DEFAULT_APP_URL   = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"
ADMIN_DEFAULT_ID  = 1743359080  # ادمین اولیه (شما)

BOT_TOKEN = os.getenv("BOT_TOKEN", DEFAULT_BOT_TOKEN).strip()
APP_URL  = os.getenv("APP_URL", DEFAULT_APP_URL).rstrip("/")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{APP_URL}{WEBHOOK_PATH}"

DB_PATH = "database.json"

# -----------------------------
# ابزارها و کمکی‌ها
# -----------------------------
def now_ts():
    return int(time.time())

def pretty_datetime(ts=None):
    if ts is None:
        ts = now_ts()
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def normalize_digits(s: str) -> str:
    """ارقام فارسی/عربی را به لاتین تبدیل و جداکننده‌ها را حذف می‌کند"""
    if s is None: return ""
    persian = "۰۱۲۳۴۵۶۷۸۹"
    arabic  = "٠١٢٣٤٥٦٧٨٩"
    res = []
    for ch in str(s):
        if ch in persian:
            res.append(str(persian.index(ch)))
        elif ch in arabic:
            res.append(str(arabic.index(ch)))
        elif ch in " ,_":
            # حذف جداکننده‌های رایج
            continue
        else:
            res.append(ch)
    return "".join(res)

def to_int_amount(s: str):
    s = normalize_digits(s)
    if not re.fullmatch(r"\d{1,12}", s or ""):
        return None
    try:
        return int(s)
    except:
        return None

# -----------------------------
# دیتابیس ساده JSON (atomic)
# -----------------------------
INIT_DB = {
    "admins": [ADMIN_DEFAULT_ID],
    "users": {},  # uid -> {balance, buys:[{plan_id, price, ts}], tickets:{tid:{msgs:[...], open:bool}}, configs:[{plan_id, text, ts}]}
    "plans": {},  # plan_id -> {title, price}
    "coupons": {},  # code -> {percent, usage_left, plan_id('all'|pid), created_ts}
    "settings": {
        "card_number": "6214 **** **** ****",
        "texts": {
            "home_title": "👋 خوش اومدی!",
            "wallet_title": "💳 کیف پول شما",
            "shop_title": "🛍️ فروشگاه",
            "support_title": "🎫 پشتیبانی",
            "cancel": "انصراف",
            "enter_amount": "مبلغ را وارد کنید (تومان):",
            "invalid_amount": "❌ مبلغ نامعتبر است. فقط عدد وارد کنید.",
            "send_receipt": "🧾 لطفاً رسید واریز را ارسال کنید یا «انصراف» را بزنید.",
            "card_to_card": "🔻 کارت به کارت:\n\n{card}\n\nپس از واریز، رسید را ارسال کنید.",
            "coupon_applied": "✅ کد تخفیف اعمال شد. مبلغ جدید: {amount} تومان",
            "coupon_invalid": "❌ کد تخفیف نامعتبر یا به سقف استفاده رسیده است.",
            "coupon_removed": "🗑️ کد تخفیف حذف شد.",
            "no_plans": "فعلاً پلنی ثبت نشده.",
            "your_configs": "🧾 کانفیگ‌های خریداری‌شده شما:",
            "no_configs": "هنوز چیزی نخریدی.",
            "teach_title": "📚 آموزش استفاده از ربات",
            "teach_body": (
                "مرحله‌به‌مرحله:\n"
                "1) از منوی «🛍️ فروشگاه» پلن رو ببین ✅\n"
                "2) «💳 کیف پول» رو شارژ کن ✅\n"
                "3) «خرید» رو بزن، اگر کد تخفیف داری استفاده کن 🎟️\n"
                "4) بعد از خرید، کانفیگت تو «🧾 کانفیگ‌های من» میاد ✨\n"
                "5) سوال داشتی از «🎫 پشتیبانی» تیکت ثبت کن 🙋‍♂️"
            ),
        }
    },
    "receipts": [],  # {id, uid, amount, photo_id(optional), status:pending|approved|rejected, by_admin, ts}
    "balance_logs": [],  # {id, uid, by_admin, change, before, after, reason, ts}
    "sales": []  # {uid, plan_id, price, ts}
}

def load_db():
    if not os.path.exists(DB_PATH):
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(INIT_DB, f, ensure_ascii=False, indent=2)
        return json.loads(json.dumps(INIT_DB))
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)

# state در حافظه (نه دیسک)
STATE = {}  # uid -> {"awaiting": str|None, "...": any}

def get_state(uid): return STATE.get(str(uid), {})
def set_state(uid, **kwargs):
    sid = str(uid)
    cur = STATE.get(sid, {})
    cur.update(kwargs)
    STATE[sid] = cur
def clear_state(uid):
    STATE.pop(str(uid), None)

def is_admin(db, uid):
    return int(uid) in db.get("admins", [])

def ensure_user(db, uid, username=None):
    u = db["users"].get(str(uid))
    if not u:
        u = {"balance": 0, "buys": [], "tickets": {}, "configs": []}
        db["users"][str(uid)] = u
    if username:
        u["username"] = username
    return u

def next_id(items):
    return (max([x.get("id", 0) for x in items], default=0) + 1) if items else 1

# -----------------------------
# ربات و وب‌سرور
# -----------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=4, skip_pending=True)
app = Flask(__name__)

# -------------- کیبوردها ---------------
def kb_main(db, uid):
    m = ReplyKeyboardMarkup(resize_keyboard=True)
    m.row(KeyboardButton("🛍️ فروشگاه"), KeyboardButton("💳 کیف پول"))
    m.row(KeyboardButton("🧾 کانفیگ‌های من"), KeyboardButton("🎫 پشتیبانی"))
    m.row(KeyboardButton("📚 آموزش"))
    if is_admin(db, uid):
        m.row(KeyboardButton("🛠 پنل ادمین"))
    return m

def kb_cancel(db):
    t = db["settings"]["texts"]["cancel"]
    m = ReplyKeyboardMarkup(resize_keyboard=True)
    m.row(KeyboardButton(t))
    return m

def ikb_wallet(db, has_pending=False):
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_topup"))
    m.add(InlineKeyboardButton("🎟️ وارد کردن کد تخفیف", callback_data="wallet_coupon"))
    m.add(InlineKeyboardButton("❌ حذف کد تخفیف", callback_data="wallet_coupon_remove"))
    m.add(InlineKeyboardButton("↩️ انصراف", callback_data="cancel"))
    return m

def ikb_topup_methods(db):
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("💳 کارت به کارت", callback_data="topup_card"))
    m.add(InlineKeyboardButton("↩️ انصراف", callback_data="cancel"))
    return m

def ikb_support_user():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("➕ تیکت جدید", callback_data="ticket_new"))
    m.add(InlineKeyboardButton("📂 تیکت‌های من", callback_data="ticket_my"))
    m.add(InlineKeyboardButton("↩️ انصراف", callback_data="cancel"))
    return m

def ikb_support_admin():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("📥 تیکت‌های باز کاربران", callback_data="adm_tickets_open"))
    m.add(InlineKeyboardButton("📚 راهنما/آموزش", callback_data="teach"))
    m.add(InlineKeyboardButton("↩️ انصراف", callback_data="cancel"))
    return m

def ikb_admin_panel():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("👥 مدیریت کاربران", callback_data="adm_users"))
    m.add(InlineKeyboardButton("🧾 رسیدهای واریز", callback_data="adm_receipts"))
    m.add(InlineKeyboardButton("🎟️ کدهای تخفیف", callback_data="adm_coupons"))
    m.add(InlineKeyboardButton("🧮 آمار فروش", callback_data="adm_stats"))
    m.add(InlineKeyboardButton("💼 لاگ موجودی", callback_data="adm_balance_logs"))
    m.add(InlineKeyboardButton("🗂 مدیریت پلن‌ها", callback_data="adm_plans"))
    m.add(InlineKeyboardButton("💳 تنظیم شماره کارت", callback_data="adm_card"))
    m.add(InlineKeyboardButton("🛡 مدیریت ادمین‌ها", callback_data="adm_admins"))
    m.add(InlineKeyboardButton("↩️ انصراف", callback_data="cancel"))
    return m

# -----------------------------
# متون پویا
# -----------------------------
def txt(db, key):
    return db["settings"]["texts"].get(key, "")

# -----------------------------
# هندلر شروع (فقط دکمه‌ای)
# -----------------------------
def send_home(uid):
    db = load_db()
    u = ensure_user(db, uid)
    save_db(db)
    bot.send_message(uid, f"{txt(db,'home_title')}\n\nاز منوی زیر انتخاب کن 👇",
                     reply_markup=kb_main(db, uid))

# -----------------------------
# والِت
# -----------------------------
def wallet_view(uid):
    db = load_db()
    u = ensure_user(db, uid)
    save_db(db)
    bot.send_message(uid, f"{txt(db,'wallet_title')}\n\nموجودی فعلی: {u['balance']:,} تومان",
                     reply_markup=kb_main(db, uid))
    bot.send_message(uid, "یک گزینه را انتخاب کن:",
                     reply_markup=None, reply_markup_inline=None)
    bot.send_message(uid, " ", reply_markup=ikb_wallet(db))

# -----------------------------
# تیکت سیستم
# -----------------------------
def user_open_tickets(db, uid):
    tickets = ensure_user(db, uid).get("tickets", {})
    return {tid: t for tid, t in tickets.items() if t.get("open", True)}

def show_user_tickets(uid):
    db = load_db()
    tickets = ensure_user(db, uid).get("tickets", {})
    if not tickets:
        bot.send_message(uid, "هنوز تیکتی نداری.", reply_markup=kb_main(db, uid))
        return
    lines = []
    for tid, t in sorted(tickets.items(), key=lambda x:x[0], reverse=True):
        status = "باز" if t.get("open", True) else "بسته"
        last = t.get("msgs", [])[-1]["text"] if t.get("msgs") else "-"
        lines.append(f"#{tid} — {status}\nآخرین پیام: {last[:60]}")
    bot.send_message(uid, "📂 تیکت‌های شما:\n\n" + "\n\n".join(lines))

def create_ticket(uid):
    db = load_db()
    u = ensure_user(db, uid)
    tickets = u.setdefault("tickets", {})
    tid = next_id([{"id": int(k)} for k in tickets.keys()])
    tickets[str(tid)] = {"id": tid, "open": True, "msgs": []}
    save_db(db)
    set_state(uid, awaiting="ticket_message", ticket_id=tid)
    bot.send_message(uid, "✍️ متن پیام اولیه تیکت را بنویس:",
                     reply_markup=kb_cancel(db))

def append_ticket_message(uid, text):
    db = load_db()
    st = get_state(uid)
    tid = str(st.get("ticket_id"))
    t = ensure_user(db, uid)["tickets"].get(tid)
    if not t:
        bot.send_message(uid, "تیکت معتبر نیست.", reply_markup=kb_main(db, uid))
        clear_state(uid); return
    t["msgs"].append({"from":"user", "text": text, "ts": now_ts()})
    save_db(db)
    # اطلاع به ادمین‌ها
    for aid in db["admins"]:
        try:
            bot.send_message(aid, f"🎫 پیام جدید در تیکت #{tid} از کاربر {uid}:\n\n{text}")
        except: pass
    bot.send_message(uid, "✅ پیام ثبت شد. می‌تونی پیام بعدی هم بفرستی یا با «انصراف» خارج شی.")

def admin_open_tickets_list(uid):
    db = load_db()
    lines = []
    for suid, u in db["users"].items():
        for tid, t in u.get("tickets", {}).items():
            if t.get("open", True):
                last = t.get("msgs", [])[-1]["text"] if t.get("msgs") else "-"
                lines.append(f"#{tid} — از کاربر {suid}\nآخرین پیام: {last[:60]}")
    if not lines:
        bot.send_message(uid, "هیچ تیکت بازی وجود ندارد.")
    else:
        bot.send_message(uid, "📥 تیکت‌های باز:\n\n" + "\n\n".join(lines))

# -----------------------------
# کوپن
# -----------------------------
def validate_coupon(db, code, plan_id, want_consume=False):
    c = db["coupons"].get(code.upper())
    if not c: return (False, "notfound")
    if c["usage_left"] <= 0: return (False, "usedup")
    if c["plan_id"] != "all" and c["plan_id"] != plan_id:
        return (False, "plan_mismatch")
    if want_consume:
        c["usage_left"] -= 1
        save_db(db)
    return (True, c)

# -----------------------------
# رسیدها و شارژ کیف پول
# -----------------------------
def submit_receipt(uid, amount, photo_id=None):
    db = load_db()
    rid = next_id(db["receipts"])
    db["receipts"].append({
        "id": rid, "uid": uid, "amount": amount,
        "photo_id": photo_id, "status": "pending",
        "by_admin": None, "ts": now_ts()
    })
    save_db(db)
    # اطلاع به همه ادمین‌ها
    for aid in db["admins"]:
        try:
            bot.send_message(aid,
                f"🧾 رسید جدید #{rid}\n"
                f"کاربر: {uid}\nمبلغ: {amount:,} تومان\nوضعیت: در انتظار بررسی")
        except: pass
    bot.send_message(uid, "✅ رسید ثبت شد و در انتظار بررسی ادمین‌هاست.")

def admin_list_receipts(uid, only_pending=True):
    db = load_db()
    items = [r for r in db["receipts"] if (r["status"]=="pending" if only_pending else True)]
    if not items:
        bot.send_message(uid, "موردی یافت نشد.")
        return
    for r in sorted(items, key=lambda x:x["id"], reverse=True)[:30]:
        st = "در انتظار" if r["status"]=="pending" else ("تأیید" if r["status"]=="approved" else "رد")
        by = f" — توسط ادمین {r['by_admin']}" if r.get("by_admin") else ""
        cap = (f"🧾 رسید #{r['id']}\nکاربر: {r['uid']}\nمبلغ: {r['amount']:,} تومان\n"
               f"وضعیت: {st}{by}\nتاریخ: {pretty_datetime(r['ts'])}")
        m = InlineKeyboardMarkup()
        if r["status"]=="pending":
            m.add(InlineKeyboardButton("✅ تأیید", callback_data=f"rcpt_ok_{r['id']}"))
            m.add(InlineKeyboardButton("❌ رد", callback_data=f"rcpt_no_{r['id']}"))
        else:
            m.add(InlineKeyboardButton("ℹ️ جزئیات", callback_data=f"rcpt_info_{r['id']}"))
        try:
            if r.get("photo_id"):
                bot.send_photo(uid, r["photo_id"], caption=cap, reply_markup=m)
            else:
                bot.send_message(uid, cap, reply_markup=m)
        except: pass

def apply_receipt(uid_admin, rid, approve: bool, amount_override=None):
    db = load_db()
    rec = next((x for x in db["receipts"] if x["id"]==rid), None)
    if not rec or rec["status"]!="pending":
        bot.send_message(uid_admin, "این رسید قابل بررسی نیست.")
        return
    rec["status"] = "approved" if approve else "rejected"
    rec["by_admin"] = uid_admin
    save_db(db)
    if approve:
        # مبلغ نهایی
        amount = amount_override if (amount_override is not None) else rec["amount"]
        user = ensure_user(db, rec["uid"])
        before = user["balance"]
        after  = before + amount
        user["balance"] = after
        save_db(db)
        # لاگ
        db["balance_logs"].append({
            "id": next_id(db["balance_logs"]),
            "uid": rec["uid"], "by_admin": uid_admin,
            "change": amount, "before": before, "after": after,
            "reason": f"تأیید رسید #{rid}",
            "ts": now_ts()
        })
        save_db(db)
        bot.send_message(rec["uid"],
            f"✅ رسید #{rid} توسط ادمین {uid_admin} تأیید شد.\n"
            f"{amount:,} تومان به موجودی‌ات اضافه شد.")
        bot.send_message(uid_admin, "✅ اعمال شد.")
    else:
        bot.send_message(rec["uid"], f"❌ رسید #{rid} توسط ادمین {uid_admin} رد شد.")
        bot.send_message(uid_admin, "⛔️ رد شد.")

# -----------------------------
# آمار فروش
# -----------------------------
def stats_view(uid):
    db = load_db()
    total_configs = len(db["sales"])
    total_amount  = sum(s["price"] for s in db["sales"])
    # برترین خریداران
    spend = {}
    count = {}
    for s in db["sales"]:
        spend[s["uid"]] = spend.get(s["uid"], 0) + s["price"]
        count[s["uid"]] = count.get(s["uid"], 0) + 1
    tops = sorted(spend.items(), key=lambda x:x[1], reverse=True)[:10]
    lines = [f"📈 آمار فروش",
             f"تعداد فروش (کانفیگ): {total_configs}",
             f"مبلغ کل: {total_amount:,} تومان",
             "",
             "🏆 برترین خریداران:"]
    if not tops:
        lines.append("هنوز فروشی ثبت نشده.")
    else:
        i = 1
        for uid2, amt in tops:
            lines.append(f"{i}) کاربر {uid2} — خرید: {count[uid2]} — مجموع: {amt:,} تومان")
            i += 1
    bot.send_message(uid, "\n".join(lines))

# -----------------------------
# مدیریت پلن‌ها (ساده)
# -----------------------------
def admin_list_plans(uid):
    db = load_db()
    if not db["plans"]:
        bot.send_message(uid, "هیچ پلنی ثبت نشده.")
        return
    lines = []
    for pid, p in db["plans"].items():
        lines.append(f"• {p['title']} — {p['price']:,} تومان — ID: {pid}")
    bot.send_message(uid, "📦 پلن‌ها:\n\n" + "\n".join(lines))

# -----------------------------
# کانفیگ‌های من
# -----------------------------
def user_configs_view(uid):
    db = load_db()
    u = ensure_user(db, uid)
    configs = u.get("configs", [])
    if not configs:
        bot.send_message(uid, txt(db, "no_configs"))
        return
    lines = [txt(db, "your_configs")]
    for c in sorted(configs, key=lambda x:x["ts"], reverse=True):
        plan_part = "همه پلن‌ها" if c["plan_id"]=="all" else f"پلن {c['plan_id']}"
        lines.append(f"— {plan_part} | {pretty_datetime(c['ts'])}\n{c['text']}")
    bot.send_message(uid, "\n\n".join(lines))

# -----------------------------
# خرید (دموی ساده؛ فقط کسر موجودی و ثبت کانفیگ)
# -----------------------------
def shop_view(uid):
    db = load_db()
    if not db["plans"]:
        bot.send_message(uid, txt(db, "no_plans"))
        return
    # لیست پلن‌ها با دکمه خرید
    for pid, p in db["plans"].items():
        m = InlineKeyboardMarkup()
        m.add(InlineKeyboardButton("خرید", callback_data=f"buy_{pid}"))
        bot.send_message(uid, f"📦 {p['title']}\n💰 {p['price']:,} تومان", reply_markup=m)

def try_buy(uid, pid):
    db = load_db()
    p = db["plans"].get(pid)
    if not p:
        bot.send_message(uid, "پلن یافت نشد.")
        return
    u = ensure_user(db, uid)
    price = p["price"]
    # اگر state کوپن فعال است اعمال کن (فقط نمایش/کسر واقعی همینجا)
    st = get_state(uid)
    applied = st.get("coupon_applied")
    if applied and applied.get("plan_id") in ("all", pid):
        pc = int(applied["percent"])
        price = max(0, price * (100 - pc) // 100)
    if u["balance"] < price:
        bot.send_message(uid, f"❌ موجودی کافی نیست. نیاز: {price:,} تومان")
        return
    before = u["balance"]
    u["balance"] -= price
    u["buys"].append({"plan_id": pid, "price": price, "ts": now_ts()})
    # به عنوان نمونه، یک متن کانفیگ تحویل بده
    u["configs"].append({"plan_id": pid, "text": f"CONFIG-{pid}-{now_ts()}", "ts": now_ts()})
    db["sales"].append({"uid": uid, "plan_id": pid, "price": price, "ts": now_ts()})
    save_db(db)
    # لاگ
    db["balance_logs"].append({
        "id": next_id(db["balance_logs"]),
        "uid": uid, "by_admin": None,
        "change": -price, "before": before, "after": u["balance"],
        "reason": f"خرید پلن {pid}",
        "ts": now_ts()
    })
    save_db(db)
    bot.send_message(uid, f"✅ خرید موفق! کانفیگ به «🧾 کانفیگ‌های من» اضافه شد.\n"
                          f"مبلغ: {price:,} تومان")

# -----------------------------
# مدیریت ادمین‌ها
# -----------------------------
def admins_view(uid):
    db = load_db()
    admins = db["admins"]
    lines = ["🛡 ادمین‌ها:"]
    for a in admins:
        lines.append(f"• {a}")
    bot.send_message(uid, "\n".join(lines))

# -----------------------------
# مدیریت کاربران/موجودی +/-
# -----------------------------
def admin_user_info(uid, target_uid):
    db = load_db()
    u = db["users"].get(str(target_uid))
    if not u:
        bot.send_message(uid, "کاربر یافت نشد.")
        return
    buys = len(u.get("buys", []))
    un = u.get("username", "-")
    bot.send_message(uid, (f"👤 کاربر {target_uid}\n"
                           f"یوزرنیم: @{un}\n"
                           f"موجودی: {u['balance']:,} تومان\n"
                           f"تعداد خرید: {buys}"))

# -----------------------------
# پیام‌های متنی کاربر (رویداد اصلی)
# -----------------------------
@bot.message_handler(content_types=["text", "photo"])
def on_message(m):
    uid = m.from_user.id
    username = (m.from_user.username or "")[:32]
    db = load_db()
    ensure_user(db, uid, username=username)
    save_db(db)

    # چک دکمه «انصراف»
    if m.content_type == "text":
        if m.text.strip() == txt(db, "cancel"):
            clear_state(uid)
            bot.send_message(uid, "لغو شد ✅", reply_markup=kb_main(db, uid))
            return

    st = get_state(uid)
    aw = st.get("awaiting")

    # --- حالت‌های انتظار (state) ---
    if aw == "topup_amount":
        if m.content_type != "text":
            bot.send_message(uid, txt(db,"invalid_amount")); return
        amount = to_int_amount(m.text)
        if amount is None or amount <= 0:
            bot.send_message(uid, txt(db,"invalid_amount")); return
        set_state(uid, awaiting="topup_receipt", amount=amount)
        bot.send_message(uid, txt(db,"send_receipt"), reply_markup=kb_cancel(db))
        return

    if aw == "topup_receipt":
        amount = st.get("amount")
        photo_id = None
        if m.content_type == "photo":
            photo_id = m.photo[-1].file_id
        elif m.content_type == "text" and m.text.strip() == txt(db,"cancel"):
            clear_state(uid)
            bot.send_message(uid, "لغو شد.", reply_markup=kb_main(db, uid)); return
        submit_receipt(uid, amount, photo_id)
        clear_state(uid)
        bot.send_message(uid, "برگشت به منو.", reply_markup=kb_main(db, uid))
        return

    if aw == "coupon_enter":
        if m.content_type != "text":
            bot.send_message(uid, "یک کد متنی بفرست."); return
        code = m.text.strip().upper()
        # اینجا فقط حالت «ذخیره در state» انجام می‌دیم، مصرف واقعی هنگام خرید
        c = db["coupons"].get(code)
        if not c or c["usage_left"] <= 0:
            bot.send_message(uid, txt(db,"coupon_invalid")); clear_state(uid); return
        set_state(uid, coupon_applied={"code": code, "percent": c["percent"], "plan_id": c["plan_id"]})
        bot.send_message(uid, txt(db,"coupon_applied").format(amount="—"), reply_markup=kb_main(db, uid))
        clear_state(uid)
        return

    if aw == "ticket_message":
        if m.content_type != "text":
            bot.send_message(uid, "لطفاً متن تیکت را تایپ کن."); return
        append_ticket_message(uid, m.text)
        return

    # -----------------------
    # ادمین – حالت‌ها
    # -----------------------
    if aw == "adm_add_balance":
        target = st.get("target_uid")
        if m.content_type != "text":
            bot.send_message(uid, txt(db,"invalid_amount")); return
        amt = to_int_amount(m.text)
        if not amt:
            bot.send_message(uid, txt(db,"invalid_amount")); return
        user = ensure_user(db, target)
        before = user["balance"]; after = before + amt
        user["balance"] = after
        save_db(db)
        db["balance_logs"].append({
            "id": next_id(db["balance_logs"]),
            "uid": target, "by_admin": uid,
            "change": amt, "before": before, "after": after,
            "reason": "افزایش دستی موجودی", "ts": now_ts()
        }); save_db(db)
        clear_state(uid)
        bot.send_message(uid, f"✅ موجودی کاربر {target} {amt:,} افزایش یافت. موجودی فعلی: {after:,}")
        return

    if aw == "adm_sub_balance":
        target = st.get("target_uid")
        if m.content_type != "text":
            bot.send_message(uid, txt(db,"invalid_amount")); return
        amt = to_int_amount(m.text)
        if not amt:
            bot.send_message(uid, txt(db,"invalid_amount")); return
        user = ensure_user(db, target)
        before = user["balance"]; after = max(0, before - amt)
        user["balance"] = after
        save_db(db)
        db["balance_logs"].append({
            "id": next_id(db["balance_logs"]),
            "uid": target, "by_admin": uid,
            "change": -amt, "before": before, "after": after,
            "reason": "کاهش دستی موجودی", "ts": now_ts()
        }); save_db(db)
        clear_state(uid)
        bot.send_message(uid, f"✅ {amt:,} تومان از موجودی کاربر {target} کسر شد. موجودی فعلی: {after:,}")
        return

    if aw == "adm_find_user":
        # ورودی می‌تواند آیدی یا @یوزرنیم باشد
        if m.content_type != "text":
            bot.send_message(uid, "متن بفرست."); return
        q = m.text.strip().lstrip("@")
        found_uid = None
        if re.fullmatch(r"\d{4,12}", normalize_digits(q)):
            found_uid = int(normalize_digits(q))
        else:
            # جستجوی یوزرنیم
            for suid, u in db["users"].items():
                if u.get("username","").lower() == q.lower():
                    found_uid = int(suid); break
        if not found_uid or str(found_uid) not in db["users"]:
            bot.send_message(uid, "❌ کاربر یافت نشد."); return
        admin_user_info(uid, found_uid)
        # دکمه‌های مدیریت موجودی
        mkb = InlineKeyboardMarkup()
        mkb.add(InlineKeyboardButton("➕ افزایش موجودی", callback_data=f"adm_addb_{found_uid}"))
        mkb.add(InlineKeyboardButton("➖ کسر موجودی", callback_data=f"adm_subb_{found_uid}"))
        bot.send_message(uid, "یک گزینه را انتخاب کنید:", reply_markup=mkb)
        clear_state(uid)
        return

    if aw == "adm_card_set":
        if m.content_type != "text":
            bot.send_message(uid, "شماره کارت را متنی بفرست."); return
        db["settings"]["card_number"] = m.text.strip()
        save_db(db)
        clear_state(uid)
        bot.send_message(uid, "✅ شماره کارت ذخیره شد.")
        return

    if aw == "adm_coupon_new_percent":
        if m.content_type != "text":
            bot.send_message(uid, "درصد تخفیف را وارد کن (مثلاً 10)."); return
        p = to_int_amount(m.text)
        if p is None or not (1 <= p <= 99):
            bot.send_message(uid, "❌ درصد نامعتبر (1 تا 99)."); return
        set_state(uid, awaiting="adm_coupon_new_usage", coupon_new={"percent": p})
        bot.send_message(uid, "تعداد مجاز استفاده را وارد کن:", reply_markup=kb_cancel(db))
        return

    if aw == "adm_coupon_new_usage":
        cdata = st.get("coupon_new", {})
        if m.content_type != "text":
            bot.send_message(uid, "عدد تعداد را وارد کن."); return
        n = to_int_amount(m.text)
        if n is None or n <= 0:
            bot.send_message(uid, "❌ نامعتبر."); return
        cdata["usage_left"] = n
        set_state(uid, awaiting="adm_coupon_new_plan", coupon_new=cdata)
        bot.send_message(uid, "ID پلن خاص را بفرست یا بنویس «all» برای همه پلن‌ها:",
                         reply_markup=kb_cancel(db)); return

    if aw == "adm_coupon_new_plan":
        cdata = st.get("coupon_new", {})
        if m.content_type != "text":
            bot.send_message(uid, "متن بفرست."); return
        pid = m.text.strip()
        if pid.lower() != "all":
            # اگر پلن وجود نداشت هم اجازه می‌دهیم؛ مسئولیت با ادمین
            pass
        # ساخت کد
        code = f"C{int(time.time())}"  # ساده و یکتا
        db["coupons"][code] = {
            "percent": cdata["percent"],
            "usage_left": cdata["usage_left"],
            "plan_id": ("all" if pid.lower()=="all" else pid),
            "created_ts": now_ts()
        }
        save_db(db)
        clear_state(uid)
        bot.send_message(uid, f"✅ کوپن ساخته شد:\nکد: {code}\nدرصد: {cdata['percent']}%\n"
                              f"تعداد: {cdata['usage_left']}\nپلن: {('همه' if pid.lower()=='all' else pid)}")
        return

    # -----------------------
    # بدون state: دکمه‌های منو
    # -----------------------
    if m.content_type == "text":
        t = m.text.strip()
        if t in ("شروع", "منو", "بازگشت") or t == "/start":
            send_home(uid); return

        if t == "💳 کیف پول":
            wallet_view(uid); return

        if t == "🛍️ فروشگاه":
            shop_view(uid); return

        if t == "🎫 پشتیبانی":
            if is_admin(db, uid):
                bot.send_message(uid, txt(db,"support_title"), reply_markup=kb_main(db, uid))
                bot.send_message(uid, "یک گزینه را انتخاب کن:", reply_markup=ikb_support_admin())
            else:
                bot.send_message(uid, txt(db,"support_title"), reply_markup=kb_main(db, uid))
                bot.send_message(uid, "یک گزینه را انتخاب کن:", reply_markup=ikb_support_user())
            return

        if t == "🧾 کانفیگ‌های من":
            user_configs_view(uid); return

        if t == "📚 آموزش":
            bot.send_message(uid, f"{txt(db,'teach_title')}\n\n{txt(db,'teach_body')}",
                             reply_markup=kb_main(db, uid)); return

        if t == "🛠 پنل ادمین":
            if not is_admin(db, uid):
                bot.send_message(uid, "دسترسی ندارید."); return
            bot.send_message(uid, "پنل ادمین:", reply_markup=kb_main(db, uid))
            bot.send_message(uid, "یک گزینه را انتخاب کن:", reply_markup=ikb_admin_panel())
            return

    # عکس بدون state: اگر ادمین نبود یعنی در جریان رسید نیستیم
    if m.content_type == "photo" and st.get("awaiting") != "topup_receipt":
        bot.send_message(uid, "برای ثبت رسید، اول مبلغ شارژ را وارد کن.")
        return

# -----------------------------
# کال‌بک‌ها (دکمه‌های اینلاین)
# -----------------------------
@bot.callback_query_handler(func=lambda c: True)
def on_callback(c):
    uid = c.from_user.id
    db = load_db()
    data = c.data

    if data == "cancel":
        clear_state(uid)
        bot.answer_callback_query(c.id, "لغو شد")
        bot.edit_message_reply_markup(uid, c.message.message_id, reply_markup=None)
        return

    # کیف پول
    if data == "wallet_topup":
        set_state(uid, awaiting="topup_amount")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, txt(db,"enter_amount"), reply_markup=kb_cancel(db))
        return

    if data == "wallet_coupon":
        set_state(uid, awaiting="coupon_enter")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "کد تخفیف را وارد کنید:", reply_markup=kb_cancel(db))
        return

    if data == "wallet_coupon_remove":
        st = get_state(uid)
        if "coupon_applied" in st:
            st.pop("coupon_applied", None)
            STATE[str(uid)] = st
            bot.answer_callback_query(c.id, "حذف شد.")
            bot.send_message(uid, txt(db,"coupon_removed"))
        else:
            bot.answer_callback_query(c.id, "کدی اعمال نشده.")
        return

    if data == "topup_card":
        card = db["settings"]["card_number"]
        bot.answer_callback_query(c.id)
        bot.send_message(uid, txt(db,"card_to_card").format(card=card), reply_markup=kb_cancel(db))
        return

    # پشتیبانی
    if data == "ticket_new":
        bot.answer_callback_query(c.id)
        create_ticket(uid); return

    if data == "ticket_my":
        bot.answer_callback_query(c.id)
        show_user_tickets(uid); return

    if data == "adm_tickets_open":
        if not is_admin(db, uid):
            bot.answer_callback_query(c.id, "دسترسی ندارید."); return
        bot.answer_callback_query(c.id)
        admin_open_tickets_list(uid); return

    if data == "teach":
        bot.answer_callback_query(c.id)
        bot.send_message(uid, f"{txt(db,'teach_title')}\n\n{txt(db,'teach_body')}")
        return

    # خرید
    if data.startswith("buy_"):
        pid = data.split("_",1)[1]
        bot.answer_callback_query(c.id)
        try_buy(uid, pid); return

    # پنل ادمین
    if data == "adm_users":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        set_state(uid, awaiting="adm_find_user")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "آیدی عددی یا یوزرنیم (بدون @) را بفرست:", reply_markup=kb_cancel(db))
        return

    if data == "adm_receipts":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        admin_list_receipts(uid, only_pending=True); return

    if data == "adm_coupons":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        # لیست + ساخت
        if not db["coupons"]:
            bot.send_message(uid, "🎟️ کوپنی وجود ندارد.")
        else:
            lines = []
            for code, cpn in db["coupons"].items():
                plan_part = "همه پلن‌ها" if cpn["plan_id"]=="all" else f"پلن {cpn['plan_id']}"
                lines.append(f"• {code} — {cpn['percent']}% — باقی‌مانده: {cpn['usage_left']} — {plan_part}")
            bot.send_message(uid, "🎟️ کوپن‌ها:\n\n" + "\n".join(lines))
        mkb = InlineKeyboardMarkup()
        mkb.add(InlineKeyboardButton("➕ ساخت کوپن جدید", callback_data="adm_coupon_new"))
        bot.send_message(uid, "گزینه‌ای انتخاب کن:", reply_markup=mkb)
        return

    if data == "adm_coupon_new":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        set_state(uid, awaiting="adm_coupon_new_percent", coupon_new={})
        bot.send_message(uid, "درصد تخفیف را وارد کن (1 تا 99):", reply_markup=kb_cancel(db))
        return

    if data == "adm_stats":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        stats_view(uid); return

    if data == "adm_balance_logs":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        logs = sorted(db["balance_logs"], key=lambda x:x["id"], reverse=True)[:30]
        if not logs:
            bot.send_message(uid, "📄 لاگی وجود ندارد."); return
        lines = ["💼 لاگ موجودی (30 مورد آخر):"]
        for l in logs:
            by = f"@{db['users'].get(str(l['uid']),{}).get('username','-')}"
            admin_by = l["by_admin"] if l["by_admin"] is not None else "سیستم"
            lines.append(
                f"#{l['id']} — کاربر {l['uid']} ({by})\n"
                f"تغییر: {l['change']:+,} — قبل: {l['before']:,} — بعد: {l['after']:,}\n"
                f"علت: {l['reason']} — ادمین: {admin_by} — {pretty_datetime(l['ts'])}"
            )
        bot.send_message(uid, "\n\n".join(lines)); return

    if data == "adm_plans":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        admin_list_plans(uid)
        return

    if data == "adm_card":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        bot.send_message(uid, f"شماره کارت فعلی:\n{db['settings']['card_number']}")
        set_state(uid, awaiting="adm_card_set")
        bot.send_message(uid, "شماره کارت جدید را بفرست:", reply_markup=kb_cancel(db))
        return

    if data == "adm_admins":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        bot.answer_callback_query(c.id)
        admins_view(uid)
        # امکانات اضافه/حذف ساده بر اساس آیدی
        mkb = InlineKeyboardMarkup()
        mkb.add(InlineKeyboardButton("➕ افزودن ادمین با آیدی", callback_data="adm_admin_add"))
        mkb.add(InlineKeyboardButton("➖ حذف ادمین با آیدی", callback_data="adm_admin_del"))
        bot.send_message(uid, "یک گزینه را انتخاب کن:", reply_markup=mkb)
        return

    if data == "adm_admin_add":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        set_state(uid, awaiting="adm_admin_add_id")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "آیدی عددی کاربر را بفرست:", reply_markup=kb_cancel(db))
        return

    if data == "adm_admin_del":
        if not is_admin(db, uid): bot.answer_callback_query(c.id); return
        set_state(uid, awaiting="adm_admin_del_id")
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "آیدی عددی ادمین را بفرست:", reply_markup=kb_cancel(db))
        return

    # مدیریت موجودی کاربر (از کال‌بک)
    if data.startswith("adm_addb_"):
        target = int(data.split("_")[2])
        set_state(uid, awaiting="adm_add_balance", target_uid=target)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "مبلغ افزایش را وارد کن:", reply_markup=kb_cancel(db))
        return

    if data.startswith("adm_subb_"):
        target = int(data.split("_")[2])
        set_state(uid, awaiting="adm_sub_balance", target_uid=target)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "مبلغ کسر را وارد کن:", reply_markup=kb_cancel(db))
        return

    # رسیدها
    if data.startswith("rcpt_ok_"):
        rid = int(data.split("_")[2])
        set_state(uid, awaiting="rcpt_ok_amount", receipt_id=rid)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "مبلغ نهایی شارژ را وارد کن (اگر می‌خوای تغییر بدی؛ در غیر اینصورت همان مبلغ رسید اعمال می‌شود):",
                         reply_markup=kb_cancel(db))
        return

    if data.startswith("rcpt_no_"):
        rid = int(data.split("_")[2])
        bot.answer_callback_query(c.id)
        apply_receipt(uid, rid, approve=False)
        return

    if data.startswith("rcpt_info_"):
        rid = int(data.split("_")[2])
        bot.answer_callback_query(c.id)
        db = load_db()
        r = next((x for x in db["receipts"] if x["id"]==rid), None)
        if not r:
            bot.send_message(uid, "پیدا نشد.")
            return
        st = "در انتظار" if r["status"]=="pending" else ("تأیید" if r["status"]=="approved" else "رد")
        by = f" — توسط ادمین {r['by_admin']}" if r.get("by_admin") else ""
        bot.send_message(uid, f"🧾 رسید #{r['id']}\nکاربر: {r['uid']}\nمبلغ: {r['amount']:,}\n"
                              f"وضعیت: {st}{by}\nتاریخ: {pretty_datetime(r['ts'])}")
        return

# رسید: گرفتن مبلغ نهایی در state
@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="rcpt_ok_amount", content_types=["text"])
def rcpt_ok_amount_handler(m):
    uid = m.from_user.id
    st = get_state(uid)
    rid = st.get("receipt_id")
    val = m.text.strip()
    if val == txt(load_db(),"cancel"):
        clear_state(uid); bot.send_message(uid, "لغو شد."); return
    amt = to_int_amount(val)
    if amt is None or amt <= 0:
        bot.send_message(uid, "❌ مبلغ نامعتبر."); return
    apply_receipt(uid, rid, approve=True, amount_override=amt)
    clear_state(uid)

# افزودن/حذف ادمین با state
@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="adm_admin_add_id", content_types=["text"])
def adm_add_admin_id(m):
    uid = m.from_user.id
    db = load_db()
    if not is_admin(db, uid): return
    val = to_int_amount(m.text)
    if val is None:
        bot.send_message(uid, "❌ آیدی عددی نامعتبر."); return
    if val in db["admins"]:
        bot.send_message(uid, "قبلاً ادمین بوده."); clear_state(uid); return
    db["admins"].append(val)
    save_db(db)
    clear_state(uid)
    bot.send_message(uid, f"✅ {val} به ادمین‌ها اضافه شد.")

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("awaiting")=="adm_admin_del_id", content_types=["text"])
def adm_del_admin_id(m):
    uid = m.from_user.id
    db = load_db()
    if not is_admin(db, uid): return
    val = to_int_amount(m.text)
    if val is None:
        bot.send_message(uid, "❌ آیدی عددی نامعتبر."); return
    if val not in db["admins"]:
        bot.send_message(uid, "ادمین نیست."); clear_state(uid); return
    if val == ADMIN_DEFAULT_ID and len(db["admins"])==1:
        bot.send_message(uid, "نمی‌تونی تنها ادمین را حذف کنی."); clear_state(uid); return
    db["admins"] = [x for x in db["admins"] if x != val]
    save_db(db)
    clear_state(uid)
    bot.send_message(uid, f"✅ {val} از ادمین‌ها حذف شد.")

# -----------------------------
# وبهوک
# -----------------------------
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

def set_webhook_once():
    try:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print(f"Failed to set webhook: {e}")

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_update = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_update)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

# -----------------------------
# بوت شدن
# -----------------------------
if __name__ == "__main__":
    set_webhook_once()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
