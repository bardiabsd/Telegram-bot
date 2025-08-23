# -*- coding: utf-8 -*-
import os
import json
import time
from datetime import datetime
from flask import Flask, request, abort
import telebot
from telebot import types

# ==============================
# تنظیمات عمومی (Koyeb-friendly)
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "REPLACE_ME_WITH_YOUR_TOKEN")
APP_URL   = os.getenv("APP_URL",   "https://YOUR-APP.koyeb.app")

DEFAULT_ADMINS = {1743359080}   # آیدی عددی شما
DEFAULT_CARD   = "6037-9972-1234-5678"
DB_PATH        = "db.json"
USER_PAGE_SIZE = 20  # تعداد کاربران در هر صفحه لیست

# -----------------------------
# لود/سیو دیتابیس سبک
# -----------------------------
def _now_ts(): return int(time.time())

def _load_db():
    if not os.path.exists(DB_PATH):
        return {
            "admins": list(DEFAULT_ADMINS),
            "card_number": DEFAULT_CARD,
            "users": {},   # str(uid) -> {...}
            "plans": {},   # pid -> {..., stock:[...]}
            "tickets": {}, # tid -> {...}
            "coupons": {}, # code -> {...}
            "receipts": {},# rid -> {...}
            "sales": [],   # [{id,uid,pid,price,final,coupon,ts}]
            "texts": {
                "welcome": (
                    "سلام! خوش اومدی به <b>GoldenVPN</b> 🌟\n\n"
                    "از منوی زیر انتخاب کن:\n"
                    "🛒 خرید پلن | 🪙 کیف پول | 🎫 پشتیبانی | 👤 حساب کاربری"
                ),
                "kb_main_title": "منوی اصلی",
                "btn_buy": "🛒 خرید پلن",
                "btn_wallet": "🪙 کیف پول",
                "btn_tickets": "🎫 پشتیبانی",
                "btn_account": "👤 حساب کاربری",
                "btn_admin": "🛠 پنل ادمین",
                "btn_back_user": "↩️ بازگشت به منوی کاربر",
                "btn_cancel": "❌ انصراف",
            },
            "toggles": {
                "buy": True, "wallet": True, "tickets": True, "account": True
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
            "state": {},
            "view": "user"  # user/admin_panel
        }
        db["users"][str(uid)] = u
    else:
        if username and u.get("username") != username:
            u["username"] = username
    return u

def is_admin(db, uid): return uid in set(db.get("admins", []))

def set_state(uobj, **kw):
    st = uobj.get("state") or {}
    for k, v in kw.items():
        if v is None: st.pop(k, None)
        else: st[k] = v
    uobj["state"] = st

def clear_state(uobj): uobj["state"] = {}

def next_id(prefix): return f"{prefix}_{int(time.time()*1000)}"

def human_price(p): return f"{int(p):,} تومان"

# -----------------------------
# تلگرام و وبهوک
# -----------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, parse_mode="HTML")
app = Flask(__name__)

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{APP_URL}{WEBHOOK_PATH}"

@app.route("/", methods=["GET"])
def root(): return "OK", 200

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        update = request.get_json()
        bot.process_new_updates([telebot.types.Update.de_json(update)])
        return "OK", 200
    abort(403)

def set_webhook_once():
    try:
        info = bot.get_webhook_info()
        if info and info.url == WEBHOOK_URL:
            print("Webhook already set")
            return
    except Exception as e:
        print("get_webhook_info err:", e)
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        print("Webhook set:", WEBHOOK_URL)
    except Exception as e:
        print("set_webhook err:", e)

# -----------------------------
# کیبوردها
# -----------------------------
def kb_main(db, isadm=False, view="user"):
    t, tg = db["texts"], db["toggles"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    rows = []
    if tg.get("buy"):     rows.append(types.KeyboardButton(t["btn_buy"]))
    if tg.get("wallet"):  rows.append(types.KeyboardButton(t["btn_wallet"]))
    if tg.get("tickets"): rows.append(types.KeyboardButton(t["btn_tickets"]))
    if tg.get("account"): rows.append(types.KeyboardButton(t["btn_account"]))
    if isadm:
        if view == "user":
            rows.append(types.KeyboardButton(t["btn_admin"]))
        else:
            rows.append(types.KeyboardButton(t["btn_back_user"]))
    kb.add(*rows)
    return kb

def kb_cancel(db):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton(db["texts"]["btn_cancel"]))
    return kb

def ik_back_cancel(db):
    ik = types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("↩️ بازگشت", callback_data="back"),
           types.InlineKeyboardButton(db["texts"]["btn_cancel"], callback_data="cancel"))
    return ik

# -----------------------------
# استارت
# -----------------------------
@bot.message_handler(commands=["start"])
def cmd_start(m):
    db = _load_db()
    u = get_user(db, m.from_user.id, m.from_user.username)
    clear_state(u); u["view"] = "user"; _save_db(db)
    bot.send_message(m.chat.id, db["texts"]["welcome"], reply_markup=kb_main(db, is_admin(db, u["id"]), "user"))

# =============================
# ساختار پنل ادمین
# =============================
def admin_panel_kb():
    ik = types.InlineKeyboardMarkup()
    ik.row(
        types.InlineKeyboardButton("👑 مدیریت ادمین‌ها", callback_data="adm:admins"),
        types.InlineKeyboardButton("💳 شماره کارت", callback_data="adm:card"),
    )
    ik.row(
        types.InlineKeyboardButton("🧾 رسیدهای در انتظار", callback_data="adm:receipts"),
        types.InlineKeyboardButton("🧮 شارژ کیف پولِ کاربر", callback_data="adm:credit"),
    )
    ik.row(
        types.InlineKeyboardButton("🏷 کوپن‌ها", callback_data="adm:coupons"),
        types.InlineKeyboardButton("📣 اعلان همگانی", callback_data="adm:broadcast"),
    )
    ik.row(
        types.InlineKeyboardButton("📦 مدیریت پلن/مخزن", callback_data="adm:plans"),
        types.InlineKeyboardButton("👥 کاربران", callback_data="adm:users"),
    )
    ik.row(
        types.InlineKeyboardButton("📊 آمار فروش", callback_data="adm:stats"),
        types.InlineKeyboardButton("🎫 مدیریت تیکت‌ها", callback_data="adm:tickets"),
    )
    ik.add(types.InlineKeyboardButton("↩️ بازگشت به منوی کاربر", callback_data="adm:back_user"))
    return ik

def show_admin_panel(chat_id):
    bot.send_message(chat_id, "🛠 <b>پنل ادمین</b>:", reply_markup=admin_panel_kb())

@bot.callback_query_handler(func=lambda c: c.data=="adm:back_user")
def cb_adm_back_user(c):
    db = _load_db()
    u = get_user(db, c.from_user.id, c.from_user.username)
    u["view"]="user"; clear_state(u); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "به منوی کاربر برگشتید.", reply_markup=kb_main(db, is_admin(db, u["id"]), "user"))

# =============================
# خرید پلن برای کاربر
# =============================
def _calc_final_with_coupon(db, pid, coupon_code):
    """محاسبه مبلغ نهایی با کوپن (در صورت معتبر بودن)"""
    p = db["plans"].get(pid) or {}
    price = p.get("price", 0)
    final = price
    valid = False
    if coupon_code and coupon_code in db.get("coupons", {}):
        cp = db["coupons"][coupon_code]
        cond = True
        if cp.get("only_plan_id") and cp["only_plan_id"] != pid: cond = False
        if cp.get("expire_ts") and _now_ts() > cp["expire_ts"]: cond = False
        if cp.get("max_uses") and cp.get("used", 0) >= cp["max_uses"]: cond = False
        if cond:
            valid = True
            final = max(0, price - (price * int(cp.get("percent", 0)) // 100))
    return price, final, valid

def plans_inline(db):
    ik = types.InlineKeyboardMarkup()
    if not db["plans"]:
        ik.add(types.InlineKeyboardButton("فعلاً پلنی موجود نیست", callback_data="noop"))
        ik.add(types.InlineKeyboardButton("انصراف", callback_data="cancel"))
        return ik
    for pid, p in db["plans"].items():
        stock = len(p.get("stock", []))
        title = f"{p['name']} | ⏳{p['days']}روز | 📦{stock} | 💵{human_price(p['price'])}"
        ik.add(types.InlineKeyboardButton(title, callback_data=f"plan:{pid}"))
    ik.add(types.InlineKeyboardButton("انصراف", callback_data="cancel"))
    return ik

def show_plan_detail(db, chat_id, pid, uid):
    p = db["plans"].get(pid)
    if not p:
        bot.send_message(chat_id, "پلن نامعتبر است.")
        return
    stock = len(p.get("stock", []))
    u = get_user(db, uid)
    code = (u.get("state", {}) or {}).get("coupon_code")
    price, final, ok = _calc_final_with_coupon(db, pid, code)

    price_line = f"💵 قیمت: <b>{human_price(price)}</b>"
    if ok and final != price:
        price_line += f" ➜ <b>{human_price(final)}</b> با کد «{code}» ✅"

    txt = (
        f"✨ <b>{p['name']}</b>\n"
        f"⏳ مدت: <b>{p['days']}</b> روز\n"
        f"📶 ترافیک: <b>{p['traffic']}</b>\n"
        f"{price_line}\n"
        f"📦 موجودی مخزن: <b>{stock}</b>\n\n"
        f"ℹ️ {p.get('desc','-')}"
    )
    ik = types.InlineKeyboardMarkup()
    ik.row(
        types.InlineKeyboardButton("🎟 اعمال کد تخفیف", callback_data=f"buy:coupon:{pid}"),
        types.InlineKeyboardButton("🏦 کارت‌به‌کارت", callback_data=f"buy:bank:{pid}")
    )
    ik.add(types.InlineKeyboardButton("💼 پرداخت از کیف پول", callback_data=f"buy:wallet:{pid}"))
    ik.add(types.InlineKeyboardButton("↩️ بازگشت", callback_data="back"),
           types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    bot.send_message(chat_id, txt, reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan:"))
def cb_plan_open(c):
    db = _load_db()
    show_plan_detail(db, c.message.chat.id, c.data.split(":")[1], c.from_user.id)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data=="back")
def cb_back(c):
    db = _load_db()
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "فهرست پلن‌ها:", reply_markup=plans_inline(db))

# کوپن
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:coupon:"))
def cb_coupon(c):
    db=_load_db()
    u=get_user(db, c.from_user.id, c.from_user.username)
    pid=c.data.split(":")[-1]
    set_state(u, flow="buy", step="coupon_code", plan_id=pid); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "کد تخفیف را ارسال کنید (یا «انصراف»).", reply_markup=kb_cancel(db))

# پرداخت از کیف‌پول
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:wallet:"))
def cb_buy_wallet(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    pid=c.data.split(":")[-1]; p=db["plans"].get(pid)
    if not p: bot.answer_callback_query(c.id,"پلن نامعتبر"); return
    if not p.get("stock"):
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "😕 موجودی این پلن تموم شده!\n"
            "🔔 به‌زودی موجودی جدید اضافه می‌کنیم. لطفاً بعداً سر بزنید یا پلن دیگری را امتحان کنید.")
        return
    price=p["price"]
    coupon_code=u["state"].get("coupon_code")
    price, final, ok = _calc_final_with_coupon(db, pid, coupon_code)
    if not ok: coupon_code = None

    if u["wallet"]<final:
        diff=final-u["wallet"]
        ik=types.InlineKeyboardMarkup()
        ik.add(types.InlineKeyboardButton("شارژ همین مقدار", callback_data=f"wallet:charge_diff:{diff}:{pid}"))
        ik.add(types.InlineKeyboardButton("انصراف", callback_data="cancel"))
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            f"موجودی کافی نیست.\nمبلغ نهایی: {human_price(final)}\n"
            f"موجودی فعلی: {human_price(u['wallet'])}\n"
            f"مابه‌التفاوت: {human_price(diff)}",
            reply_markup=ik)
        return
    # خرید
    u["wallet"]-=final
    conf=p["stock"].pop(0)
    sale={"id":next_id("sale"),"uid":u["id"],"pid":pid,"price":price,"final":final,"coupon":coupon_code or "", "ts":_now_ts()}
    db["sales"].append(sale); u["buys"].append(sale["id"])
    if coupon_code and coupon_code in db["coupons"]:
        db["coupons"][coupon_code]["used"]=db["coupons"][coupon_code].get("used",0)+1
    _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"✅ خرید شما با موفقیت انجام شد.\n\n{conf}", reply_markup=kb_main(db, is_admin(db,u['id']), u.get("view","user")))

# کارت‌به‌کارت
@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:bank:"))
def cb_buy_bank(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    pid=c.data.split(":")[-1]
    p = db["plans"].get(pid)
    if not p:
        bot.answer_callback_query(c.id, "پلن نامعتبر"); return
    if not p.get("stock"):
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "😕 موجودی این پلن تموم شده!\n"
            "🔔 به‌زودی موجودی جدید اضافه می‌کنیم. لطفاً بعداً سر بزنید یا پلن دیگری را امتحان کنید.")
        return
    set_state(u, flow="bank", step="upload_receipt", plan_id=pid); _save_db(db)
    card=db.get("card_number", DEFAULT_CARD)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id,
        f"برای خرید، مبلغ را به کارت زیر واریز کنید و رسید را ارسال نمایید:\n\n"
        f"💳 <code>{card}</code>\n"
        f"📝 سپس عکس/فایل رسید را بفرستید.\n\n"
        f"یا «انصراف».", reply_markup=kb_cancel(db))

# شارژ اختلاف
@bot.callback_query_handler(func=lambda c: c.data.startswith("wallet:charge_diff:"))
def cb_charge_diff(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    _,_,amount,pid=c.data.split(":")
    amount=int(amount)
    set_state(u, flow="wallet", step="upload_receipt_diff", amount=amount, buy_after=pid); _save_db(db)
    card=db.get("card_number", DEFAULT_CARD)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id,
        f"مبلغ {human_price(amount)} را کارت‌به‌کارت کنید و رسید را ارسال نمایید:\n\n"
        f"💳 <code>{card}</code>\n📝 سپس عکس/فایل رسید را بفرستید.\n\nیا «انصراف».",
        reply_markup=kb_cancel(db))

# =============================
# کیف پول (شیک‌تر)
# =============================
def wallet_menu(db, u):
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ شارژ کیف پول (ارسال رسید)", callback_data="wallet:charge"))
    kb.add(types.InlineKeyboardButton("🧾 سوابق خرید", callback_data="wallet:history"))
    kb.add(types.InlineKeyboardButton("ℹ️ راهنما", callback_data="wallet:help"))
    return kb

@bot.callback_query_handler(func=lambda c: c.data=="wallet:help")
def cb_wallet_help(c):
    db=_load_db()
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id,
        "✅ شارژ کیف پول با ارسال رسید کارت‌به‌کارت انجام می‌شود.\n"
        "پس از تأیید ادمین، موجودی‌تان افزایش می‌یابد و می‌توانید سریع خرید کنید.")

@bot.callback_query_handler(func=lambda c: c.data=="wallet:history")
def cb_wallet_history(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    my_sales=[s for s in db["sales"] if s["uid"]==u["id"]]
    if not my_sales:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "هنوز خریدی ندارید.")
        return
    my_sales=sorted(my_sales, key=lambda x:x["ts"], reverse=True)[:10]
    lines=["🧾 ۱۰ خرید آخر شما:"]
    for s in my_sales:
        p=db["plans"].get(s["pid"], {"name":"نامشخص"})
        dt=datetime.fromtimestamp(s["ts"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• {p['name']} | {human_price(s['final'])} | {dt}")
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "\n".join(lines))

@bot.callback_query_handler(func=lambda c: c.data=="wallet:charge")
def cb_wallet_charge(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="wallet", step="upload_receipt_wallet"); _save_db(db)
    card=db.get("card_number", DEFAULT_CARD)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id,
        f"برای شارژ، مبلغ دلخواه را کارت‌به‌کارت کنید و رسید را ارسال نمایید:\n\n"
        f"💳 <code>{card}</code>\n"
        f"📝 سپس عکس/فایل رسید را بفرستید.\n\n"
        f"یا «انصراف».",
        reply_markup=kb_cancel(db))

# =============================
# تیکت‌ها (دوطرفه + بستن + لاگ)
# =============================
def ticket_subjects_kb():
    ik=types.InlineKeyboardMarkup()
    ik.row(
        types.InlineKeyboardButton("🛒 مشکل خرید", callback_data="ticket:sub:buy"),
        types.InlineKeyboardButton("🔌 مشکل کانفیگ", callback_data="ticket:sub:config"),
    )
    ik.row(
        types.InlineKeyboardButton("💳 مالی/پرداخت", callback_data="ticket:sub:payment"),
        types.InlineKeyboardButton("⚙️ فنی/اتصال", callback_data="ticket:sub:tech"),
    )
    ik.row(
        types.InlineKeyboardButton("💬 سایر موارد", callback_data="ticket:sub:other"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"),
    )
    return ik

def ticket_view_kb(tid, role="user"):
    ik = types.InlineKeyboardMarkup()
    if role=="admin":
        ik.add(types.InlineKeyboardButton("✍️ پاسخ", callback_data=f"adm:tickets:reply:{tid}"),
               types.InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"adm:tickets:close:{tid}"))
    else:
        ik.add(types.InlineKeyboardButton("✍️ ارسال پیام", callback_data=f"ticket:reply:{tid}"),
               types.InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"ticket:close:{tid}"))
    return ik

def render_ticket(db, t):
    dt=datetime.fromtimestamp(t["ts"]).strftime("%Y-%m-%d %H:%M")
    lines=[f"🎫 <b>تیکت #{t['id']}</b>\nموضوع: <b>{t['subject']}</b>\nوضعیت: <b>{t['status']}</b>\nایجاد: {dt}", "—"]
    for msg in t.get("messages", [])[-10:]:
        who = "ادمین" if msg["from"]=="admin" else "کاربر"
        dts=datetime.fromtimestamp(msg["ts"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"{who}: {msg['text']}  ({dts})")
    return "\n".join(lines)

@bot.callback_query_handler(func=lambda c: c.data=="ticket:new")
def cb_ticket_new(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="ticket", step="ask_subject"); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "موضوع تیکت را انتخاب کنید:", reply_markup=ticket_subjects_kb())

@bot.callback_query_handler(func=lambda c: c.data=="ticket:list")
def cb_ticket_list(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    tickets=[db.get("tickets",{}).get(tid) for tid in u.get("tickets",[])]
    tickets=[t for t in tickets if t]
    bot.answer_callback_query(c.id)
    if not tickets:
        bot.send_message(c.message.chat.id, "هیچ تیکتی ندارید.")
        return
    ik=types.InlineKeyboardMarkup()
    for t in tickets[-10:]:
        ik.add(types.InlineKeyboardButton(f"#{t['id']} | {t['subject']} | {t['status']}", callback_data=f"ticket:open:{t['id']}"))
    bot.send_message(c.message.chat.id, "📂 تیکت‌های شما:", reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ticket:open:"))
def cb_ticket_open_user(c):
    db=_load_db()
    tid=c.data.split(":")[-1]
    t=db["tickets"].get(tid)
    bot.answer_callback_query(c.id)
    if not t: bot.send_message(c.message.chat.id,"یافت نشد."); return
    bot.send_message(c.message.chat.id, render_ticket(db,t), reply_markup=ticket_view_kb(tid,"user"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("ticket:reply:"))
def cb_ticket_reply_user(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    tid=c.data.split(":")[-1]
    if tid not in db["tickets"]: bot.answer_callback_query(c.id,"یافت نشد"); return
    set_state(u, flow="ticket_reply_user", step="ask_text", tid=tid); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "پیام خود را بنویسید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data.startswith("ticket:close:"))
def cb_ticket_close_user(c):
    db=_load_db()
    tid=c.data.split(":")[-1]
    t=db["tickets"].get(tid)
    bot.answer_callback_query(c.id)
    if not t: bot.send_message(c.message.chat.id,"یافت نشد."); return
    if t["status"]=="closed":
        bot.send_message(c.message.chat.id,"این تیکت قبلاً بسته شده."); return
    t["status"]="closed"; t["closed_ts"]=_now_ts(); t["closed_by"]="user"
    _save_db(db)
    # لاگ به ادمین‌ها
    _send_ticket_log(db, t, closer="user")
    bot.send_message(c.message.chat.id, f"تیکت #{t['id']} بسته شد ✅")

def notify_admins_ticket(db, t):
    cap=(f"🎫 تیکت جدید\n"
         f"#{t['id']} | از @{db['users'][str(t['uid'])].get('username','') or '-'} ({t['uid']})\n"
         f"موضوع: {t['subject']}")
    for aid in set(db.get("admins", [])):
        try: bot.send_message(aid, cap)
        except: pass

def _send_ticket_log(db, t, closer=""):
    # خلاصه کامل برای لاگ
    user = db["users"].get(str(t["uid"]), {})
    user_un = user.get("username","")
    admin_resps = [m for m in t.get("messages",[]) if m["from"]=="admin"]
    admin_last = admin_resps[-1]["admin_id"] if admin_resps else "-"
    admin_username = "-"
    if isinstance(admin_last, int):
        au = db["users"].get(str(admin_last))
        if au: admin_username = au.get("username","-")
    lines = [
        f"📁 لاگ تیکت #{t['id']}",
        f"موضوع: {t['subject']}",
        f"کاربر: @{user_un or '-'} ({t['uid']})",
        f"آخرین ادمین پاسخ‌دهنده: @{admin_username} ({admin_last})",
        f"وضعیت نهایی: {t.get('status','')}",
        f"زمان بستن: {datetime.fromtimestamp(t.get('closed_ts', _now_ts())).strftime('%Y-%m-%d %H:%M')}",
        "— پیام‌ها —"
    ]
    for m in t.get("messages",[]):
        who="ادمین" if m["from"]=="admin" else "کاربر"
        dts=datetime.fromtimestamp(m["ts"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"{who}: {m['text']}  ({dts})")
    text="\n".join(lines)
    # ارسال برای همه ادمین‌ها و خود کاربر
    for aid in set(db.get("admins", [])):
        try: bot.send_message(aid, text)
        except: pass
    try: bot.send_message(t["uid"], text)
    except: pass

# =============================
# نوتی به ادمین‌ها (رسید)
# =============================
def notify_admins_receipt(db, rid):
    r=db["receipts"][rid]
    cap=(f"🧾 <b>رسید جدید</b>\n"
         f"نوع: <b>{r['type']}</b>\n"
         f"کاربر: @{r.get('username','') or '-'} ({r['uid']})\n"
         f"شماره رسید: <code>{rid}</code>\n"
         f"وضعیت: <b>{r['status']}</b>")
    # برای خرید بانکی فقط تایید/رد (بدون ورود مبلغ)
    ik=types.InlineKeyboardMarkup()
    if r["type"]=="buy_bank":
        ik.add(
            types.InlineKeyboardButton("✅ تایید خرید", callback_data=f"adm:rcp:approve_bank:{rid}"),
            types.InlineKeyboardButton("❌ رد رسید", callback_data=f"adm:rcp:reject:{rid}"),
        )
    else:
        ik.add(
            types.InlineKeyboardButton("✅ تأیید و ورود مبلغ", callback_data=f"adm:rcp:approve:{rid}"),
            types.InlineKeyboardButton("❌ رد رسید", callback_data=f"adm:rcp:reject:{rid}"),
        )
    for aid in set(db.get("admins", [])):
        try:
            if r.get("message_id"):
                bot.copy_message(aid, r["uid"], r["message_id"], caption=cap, reply_markup=ik)
            else:
                bot.send_message(aid, cap, reply_markup=ik)
        except: pass

# =============================
# پنل ادمین: گزینه‌ها
# =============================
@bot.callback_query_handler(func=lambda c: c.data=="adm:admins")
def cb_adm_admins(c):
    db=_load_db()
    if not is_admin(db, c.from_user.id): return
    admins=db.get("admins",[])
    txt="👑 ادمین‌ها:\n" + ("\n".join([f"• <code>{a}</code>" for a in admins]) or "-")
    ik=types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm:admins:add"),
           types.InlineKeyboardButton("🗑 حذف ادمین", callback_data="adm:admins:del"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt, reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data=="adm:admins:add")
def cb_adm_add(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="admin_add", step="ask_id"); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "آیدی عددی ادمین جدید را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data=="adm:admins:del")
def cb_adm_del(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="admin_del", step="ask_id"); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "آیدی عددی ادمین برای حذف را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data=="adm:card")
def cb_adm_card(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="set_card", step="ask_card"); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "شماره کارت جدید را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data=="adm:broadcast")
def cb_broadcast(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="broadcast", step="ask_text"); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "متن اعلان همگانی را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data=="adm:credit")
def cb_adm_credit(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="credit", step="ask_user"); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "آیدی عددی کاربر یا @یوزرنیم را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data=="adm:receipts")
def cb_adm_receipts(c):
    db=_load_db()
    if not is_admin(db, c.from_user.id): return
    pend=[r for r in db["receipts"].values() if r["status"]=="pending"]
    bot.answer_callback_query(c.id)
    if not pend:
        bot.send_message(c.message.chat.id, "رسید در انتظاری وجود ندارد.")
        return
    for r in pend:
        rid=r["id"]
        try:
            cap=(f"🧾 رسید در انتظار\n"
                 f"نوع: <b>{r['type']}</b>\n"
                 f"کاربر: @{r.get('username','') or '-'} ({r['uid']})\n"
                 f"#{rid}")
            if r["type"]=="buy_bank":
                ik=types.InlineKeyboardMarkup()
                ik.add(types.InlineKeyboardButton("✅ تایید خرید", callback_data=f"adm:rcp:approve_bank:{rid}"),
                       types.InlineKeyboardButton("❌ رد رسید", callback_data=f"adm:rcp:reject:{rid}"))
            else:
                ik=types.InlineKeyboardMarkup()
                ik.add(types.InlineKeyboardButton("✅ تأیید و ورود مبلغ", callback_data=f"adm:rcp:approve:{rid}"),
                       types.InlineKeyboardButton("❌ رد رسید", callback_data=f"adm:rcp:reject:{rid}"))
            if r.get("message_id"): bot.copy_message(c.message.chat.id, r["uid"], r["message_id"], caption=cap, reply_markup=ik)
            else: bot.send_message(c.message.chat.id, cap, reply_markup=ik)
        except: pass

# تایید رسید بانکی بدون ورود مبلغ
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:rcp:approve_bank:"))
def cb_rcp_approve_bank(c):
    db=_load_db()
    rid=c.data.split(":")[-1]
    r=db["receipts"].get(rid)
    if not r: bot.answer_callback_query(c.id,"یافت نشد"); return
    pid=r.get("plan_id")
    ok=False
    if pid and pid in db["plans"] and db["plans"][pid].get("stock"):
        p=db["plans"][pid]; price=p["price"]; conf=p["stock"].pop(0)
        sale={"id":next_id("sale"),"uid":r["uid"],"pid":pid,"price":price,"final":price,"coupon":"","ts":_now_ts()}
        db["sales"].append(sale); get_user(db, r["uid"])["buys"].append(sale["id"])
        r["status"]="approved"; ok=True
        try: bot.send_message(r["uid"], f"✅ خرید شما تایید شد و کانفیگ ارسال شد:\n{conf}")
        except: pass
    else:
        # موجودی نیست: فقط تایید و اعلام می‌کنیم به‌محض شارژ ارسال می‌شود
        r["status"]="approved_no_stock"
        try:
            bot.send_message(r["uid"], "✅ رسید تایید شد؛ اما موجودی این پلن فعلاً صفره. به‌محض شارژِ مخزن کانفیگ شما ارسال می‌شود. 🙏")
        except: pass
    _save_db(db)
    bot.answer_callback_query(c.id, "ثبت شد")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:rcp:approve:"))
def cb_rcp_approve(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    rid=c.data.split(":")[-1]
    r=db["receipts"].get(rid)
    if not r: bot.answer_callback_query(c.id,"یافت نشد"); return
    r["status"]="await_amount"; _save_db(db)
    set_state(u, flow="rcp_amount", step="ask_amount", rid=rid); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"مبلغ نهایی رسید #{rid} را وارد کنید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:rcp:reject:"))
def cb_rcp_reject(c):
    db=_load_db()
    rid=c.data.split(":")[-1]
    r=db["receipts"].get(rid)
    if not r: bot.answer_callback_query(c.id,"یافت نشد"); return
    r["status"]="rejected"; _save_db(db)
    bot.answer_callback_query(c.id); bot.send_message(c.message.chat.id,"رسید رد شد.")
    try: bot.send_message(r["uid"], "❌ رسید شما رد شد. در صورت ابهام با پشتیبانی در تماس باشید.")
    except: pass

@bot.callback_query_handler(func=lambda c: c.data=="adm:coupons")
def cb_coupons(c):
    db=_load_db()
    if not is_admin(db, c.from_user.id): return
    ik=types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("➕ ساخت کوپن جدید", callback_data="adm:coupon:new"))
    if db["coupons"]:
        for code, cp in list(db["coupons"].items())[:10]:
            title=f"{code} | %{cp['percent']} | استفاده‌شده: {cp.get('used',0)}/{cp.get('max_uses','∞')}"
            ik.add(types.InlineKeyboardButton(title, callback_data=f"adm:coupon:view:{code}"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "🏷 لیست کوپن‌ها (حداکثر ۱۰ مورد):", reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data=="adm:coupon:new")
def cb_coupon_new(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="coupon", step="ask_percent", coupon={}); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "درصد تخفیف (۰-۱۰۰) را وارد کنید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:coupon:view:"))
def cb_coupon_view(c):
    db=_load_db()
    code=c.data.split(":")[-1]
    cp=db["coupons"].get(code)
    bot.answer_callback_query(c.id)
    if not cp: bot.send_message(c.message.chat.id,"یافت نشد."); return
    exp=cp.get("expire_ts"); exp_txt= datetime.fromtimestamp(exp).strftime("%Y-%m-%d") if exp else "بدون"
    ik=types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("🗑 حذف کوپن", callback_data=f"adm:coupon:del:{code}"))
    bot.send_message(c.message.chat.id,
        f"کد: <code>{code}</code>\n"
        f"درصد: %{cp['percent']}\n"
        f"پلن محدود: {cp.get('only_plan_id') or 'همه'}\n"
        f"انقضا: {exp_txt}\n"
        f"سقف استفاده: {cp.get('max_uses','بدون')}\n"
        f"تعداد استفاده: {cp.get('used',0)}",
        reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:coupon:del:"))
def cb_coupon_del(c):
    db=_load_db()
    code=c.data.split(":")[-1]
    db["coupons"].pop(code, None); _save_db(db)
    bot.answer_callback_query(c.id, "حذف شد")
    bot.send_message(c.message.chat.id, "کوپن حذف شد.")

# آمار فروش + ریست
@bot.callback_query_handler(func=lambda c: c.data=="adm:stats")
def cb_stats(c):
    db=_load_db()
    if not is_admin(db, c.from_user.id): return
    total_count=len(db["sales"])
    total_sum=sum(s["final"] for s in db["sales"])
    # برترین خریداران
    spend={}
    for s in db["sales"]:
        spend[s["uid"]]=spend.get(s["uid"],0)+s["final"]
    top=sorted(spend.items(), key=lambda x:x[1], reverse=True)[:10]
    lines=[
        "📊 <b>آمار فروش</b>",
        f"• تعداد فروش: <b>{total_count}</b>",
        f"• مجموع فروش: <b>{human_price(total_sum)}</b>",
        "👑 <b>برترین خریداران</b> (۱۰ نفر):"
    ]
    for uid,amt in top:
        un=db["users"].get(str(uid),{}).get("username","")
        lines.append(f"  - @{un or '-'} ({uid}) : {human_price(amt)}")
    ik=types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("🧹 صفر کردن آمار", callback_data="adm:stats:reset:ask"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "\n".join(lines), reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data=="adm:stats:reset:ask")
def cb_stats_reset_ask(c):
    db=_load_db()
    if not is_admin(db, c.from_user.id): return
    ik=types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("❗️ بله، صفر کن", callback_data="adm:stats:reset:yes"),
           types.InlineKeyboardButton("انصراف", callback_data="cancel"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "آیا مطمئنید کل آمار فروش صفر شود؟", reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data=="adm:stats:reset:yes")
def cb_stats_reset_yes(c):
    db=_load_db()
    if not is_admin(db, c.from_user.id): return
    db["sales"]=[]; _save_db(db)
    bot.answer_callback_query(c.id, "ریست شد")
    bot.send_message(c.message.chat.id, "✅ آمار فروش از نو صفر شد.")

# مدیریت پلن/مخزن
@bot.callback_query_handler(func=lambda c: c.data=="adm:plans")
def cb_plans(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    if not is_admin(db, u["id"]): return
    ik=types.InlineKeyboardMarkup()
    ik.add(types.InlineKeyboardButton("➕ ساخت پلن جدید", callback_data="adm:plans:new"))
    if db["plans"]:
        for pid, p in db["plans"].items():
            ik.add(types.InlineKeyboardButton(f"{p['name']} | موجودی {len(p.get('stock', []))}", callback_data=f"adm:plans:open:{pid}"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "📦 مدیریت پلن‌ها:", reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data=="adm:plans:new")
def cb_plans_new(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="plan_new", step="ask_name", plan={}); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "نام پلن را بفرستید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:plans:open:"))
def cb_plans_open(c):
    db=_load_db()
    pid=c.data.split(":")[-1]
    p=db["plans"].get(pid)
    if not p: bot.answer_callback_query(c.id,"یافت نشد"); return
    stock=len(p.get("stock",[]))
    txt=(f"<b>{p['name']}</b>\n⏳ {p['days']} روز | 📶 {p['traffic']} | 💵 {human_price(p['price'])}\n"
         f"📦 موجودی مخزن: <b>{stock}</b>\nℹ️ {p.get('desc','-')}")
    ik=types.InlineKeyboardMarkup()
    ik.row(
        types.InlineKeyboardButton("➕ افزودن آیتم به مخزن", callback_data=f"adm:stock:add:{pid}"),
        types.InlineKeyboardButton("🗑 پاک‌سازی مخزن", callback_data=f"adm:stock:clear:{pid}")
    )
    ik.add(types.InlineKeyboardButton("✏️ ویرایش قیمت", callback_data=f"adm:plan:price:{pid}"))
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, txt, reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:stock:add:"))
def cb_stock_add(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    pid=c.data.split(":")[-1]
    set_state(u, flow="stock_add", step="ask_item", pid=pid); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "متن کانفیگ/آیتم را بفرستید (هر پیام = یک آیتم):", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:stock:clear:"))
def cb_stock_clear(c):
    db=_load_db()
    pid=c.data.split(":")[-1]
    if pid in db["plans"]:
        db["plans"][pid]["stock"]=[]; _save_db(db)
    bot.answer_callback_query(c.id, "پاک شد")
    bot.send_message(c.message.chat.id, "مخزن این پلن خالی شد.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:plan:price:"))
def cb_plan_price(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    pid=c.data.split(":")[-1]
    set_state(u, flow="plan_edit_price", step="ask_price", pid=pid); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "قیمت جدید (تومان) را وارد کنید:", reply_markup=kb_cancel(db))

# =============================
# مدیریت کاربران (لیست + جستجو)
# =============================
def _render_users_page(db, start=0, q=None):
    users = list(db["users"].values())
    if q:
        ql = q.lower()
        users = [u for u in users if str(u["id"]).startswith(ql) or (u.get("username","").lower().find(ql) >= 0)]
    total = len(users)
    users = sorted(users, key=lambda x: x.get("joined",0))
    page = users[start:start+USER_PAGE_SIZE]
    lines=[f"👥 کاربران (نمایش {start+1}-{min(start+USER_PAGE_SIZE,total)} از {total})"]
    for u in page:
        lines.append(f"• ({u['id']}) @{u.get('username','-')} | کیف پول: {human_price(u['wallet'])} | خریدها: {len(u.get('buys',[]))}")
    ik=types.InlineKeyboardMarkup()
    prev_start = max(0, start-USER_PAGE_SIZE)
    next_start = start+USER_PAGE_SIZE if (start+USER_PAGE_SIZE)<total else None
    if prev_start < start:
        ik.add(types.InlineKeyboardButton("« قبلی", callback_data=f"adm:users:list:{prev_start}:{q or ''}"))
    if next_start is not None:
        ik.add(types.InlineKeyboardButton("بعدی »", callback_data=f"adm:users:list:{next_start}:{q or ''}"))
    ik.add(types.InlineKeyboardButton("🔎 جستجو", callback_data="adm:users:search"),
           types.InlineKeyboardButton("🔄 همه", callback_data="adm:users"))
    return "\n".join(lines), ik

@bot.callback_query_handler(func=lambda c: c.data=="adm:users")
def cb_users_home(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    if not is_admin(db, u["id"]): return
    bot.answer_callback_query(c.id)
    text, ik = _render_users_page(db, start=0, q=None)
    bot.send_message(c.message.chat.id, text, reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:users:list:"))
def cb_users_page(c):
    db=_load_db()
    _,_,_,start,q = c.data.split(":", 4)
    start=int(start or 0); q=q or None
    bot.answer_callback_query(c.id)
    text, ik = _render_users_page(db, start=start, q=q)
    bot.send_message(c.message.chat.id, text, reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data=="adm:users:search")
def cb_users_search(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    set_state(u, flow="users_search", step="ask_q"); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "عبارت جستجو (@یوزرنیم یا آیدی) را بفرستید:", reply_markup=kb_cancel(db))

# =============================
# مدیریت تیکت‌ها برای ادمین
# =============================
@bot.callback_query_handler(func=lambda c: c.data=="adm:tickets")
def cb_adm_tickets(c):
    db=_load_db()
    if not is_admin(db, c.from_user.id): return
    open_ts=[t for t in db["tickets"].values() if t.get("status")=="open"]
    bot.answer_callback_query(c.id)
    if not open_ts:
        bot.send_message(c.message.chat.id, "هیچ تیکت بازی وجود ندارد.")
        return
    ik=types.InlineKeyboardMarkup()
    for t in open_ts[-20:]:
        u=db["users"].get(str(t["uid"]),{})
        ik.add(types.InlineKeyboardButton(f"#{t['id']} | @{u.get('username','-')} | {t['subject']}", callback_data=f"adm:tickets:open:{t['id']}"))
    bot.send_message(c.message.chat.id, "تیکت‌های باز:", reply_markup=ik)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:tickets:open:"))
def cb_adm_ticket_open(c):
    db=_load_db()
    tid=c.data.split(":")[-1]
    t=db["tickets"].get(tid)
    bot.answer_callback_query(c.id)
    if not t: bot.send_message(c.message.chat.id,"یافت نشد."); return
    bot.send_message(c.message.chat.id, render_ticket(db,t), reply_markup=ticket_view_kb(tid,"admin"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:tickets:reply:"))
def cb_adm_ticket_reply(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    tid=c.data.split(":")[-1]
    if tid not in db["tickets"]: bot.answer_callback_query(c.id,"یافت نشد"); return
    set_state(u, flow="ticket_reply_admin", step="ask_text", tid=tid); _save_db(db)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "پاسخ خود را بنویسید:", reply_markup=kb_cancel(db))

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:tickets:close:"))
def cb_adm_ticket_close(c):
    db=_load_db(); u=get_user(db, c.from_user.id, c.from_user.username)
    tid=c.data.split(":")[-1]
    t=db["tickets"].get(tid)
    bot.answer_callback_query(c.id)
    if not t: bot.send_message(c.message.chat.id,"یافت نشد."); return
    if t["status"]=="closed":
        bot.send_message(c.message.chat.id,"این تیکت قبلاً بسته شده."); return
    t["status"]="closed"; t["closed_ts"]=_now_ts(); t["closed_by"]="admin"
    _save_db(db)
    _send_ticket_log(db, t, closer="admin")
    bot.send_message(c.message.chat.id, f"تیکت #{t['id']} بسته شد ✅")

# =============================
# روتر «پیام‌ها»: اولویت با state
# =============================
@bot.message_handler(content_types=["text","photo","document"])
def router(m):
    db=_load_db()
    u=get_user(db, m.from_user.id, m.from_user.username)
    st=u.get("state",{})
    text=(m.text or "").strip()
    isadm=is_admin(db, u["id"])

    # ======= کنترل انصراف
    if text == db["texts"]["btn_cancel"] or text=="/cancel":
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, "لغو شد ✅", reply_markup=kb_main(db, isadm, u.get("view","user")))
        return

    # ======= مراحل state آزاد (اولویت بالا)

    # جستجوی کاربران
    if isadm and st.get("flow")=="users_search" and st.get("step")=="ask_q":
        q=text
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, "نتایج جستجو:")
        t, ik = _render_users_page(db, start=0, q=q)
        bot.send_message(m.chat.id, t, reply_markup=ik)
        return

    # کوپن: ورودی کد
    if st.get("flow")=="buy" and st.get("step")=="coupon_code":
        code=text.replace(" ","")
        pid = u["state"].get("plan_id")
        # اعتبارسنجی
        _, _, ok = _calc_final_with_coupon(db, pid, code)
        if not ok:
            bot.send_message(m.chat.id, "❌ کد تخفیف نامعتبر/منقضی است یا برای این پلن نیست. دوباره تلاش کنید یا «انصراف».", reply_markup=kb_cancel(db))
            return
        u["state"]["coupon_code"]=code; _save_db(db)
        bot.send_message(m.chat.id, "کد تخفیف معتبر ✅")
        show_plan_detail(db, m.chat.id, pid, u["id"])
        clear_state(u); _save_db(db)
        return

    # آپلود رسید برای کیف پول
    if st.get("flow")=="wallet" and st.get("step")=="upload_receipt_wallet":
        rid=next_id("rcp")
        db["receipts"][rid]={
            "id":rid,"uid":u["id"],"username":u.get("username",""),
            "type":"wallet_charge","amount":None,"plan_id":None,
            "status":"pending","note":"wallet_charge","ts":_now_ts(),
            "message_id": m.message_id if (m.photo or m.document or m.text) else None
        }
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id,"رسید شما ثبت شد؛ منتظر تأیید ادمین… ✅", reply_markup=kb_main(db,isadm,u.get("view","user")))
        notify_admins_receipt(db, rid)
        return

    # آپلود رسید برای اختلاف خرید
    if st.get("flow")=="wallet" and st.get("step")=="upload_receipt_diff":
        rid=next_id("rcp")
        db["receipts"][rid]={
            "id":rid,"uid":u["id"],"username":u.get("username",""),
            "type":"charge_diff","amount":st.get("amount",0),"plan_id":st.get("buy_after"),
            "status":"pending","note":"wallet_diff","ts":_now_ts(),
            "message_id": m.message_id if (m.photo or m.document or m.text) else None
        }
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id,"رسید شما ثبت شد؛ منتظر تأیید ادمین… ✅", reply_markup=kb_main(db,isadm,u.get("view","user")))
        notify_admins_receipt(db, rid)
        return

    # آپلود رسید برای خرید بانکی
    if st.get("flow")=="bank" and st.get("step")=="upload_receipt":
        rid=next_id("rcp")
        db["receipts"][rid]={
            "id":rid,"uid":u["id"],"username":u.get("username",""),
            "type":"buy_bank","amount":None,"plan_id":st.get("plan_id"),
            "status":"pending","note":"buy_bank","ts":_now_ts(),
            "message_id": m.message_id if (m.photo or m.document or m.text) else None
        }
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id,"رسید شما ثبت شد؛ منتظر تأیید ادمین… ✅", reply_markup=kb_main(db,isadm,u.get("view","user")))
        notify_admins_receipt(db, rid)
        return

    # تیکت: دریافت متن اولیه
    if st.get("flow")=="ticket" and st.get("step")=="ask_text":
        txt=(m.text or "").strip()
        if not txt:
            bot.send_message(m.chat.id,"لطفاً متن تیکت را بنویسید یا «انصراف».", reply_markup=kb_cancel(db)); return
        tid=next_id("tkt")
        t={
            "id":tid, "uid":u["id"], "subject":st.get("subject","بدون موضوع"),
            "messages":[{"from":"user","text":txt,"ts":_now_ts()}],
            "status":"open","ts":_now_ts()
        }
        u["tickets"].append(tid); db["tickets"][tid]=t
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id,"تیکت ساخته شد ✅", reply_markup=kb_main(db,isadm,u.get("view","user")))
        notify_admins_ticket(db, t)
        return

    # تیکت: پاسخ کاربر
    if st.get("flow")=="ticket_reply_user" and st.get("step")=="ask_text":
        tid=st.get("tid"); t=db["tickets"].get(tid)
        if not t:
            clear_state(u); _save_db(db)
            bot.send_message(m.chat.id, "تیکت یافت نشد.", reply_markup=kb_main(db,isadm,u.get("view","user"))); return
        msg=(m.text or "").strip()
        if not msg:
            bot.send_message(m.chat.id,"پیام خالی است. تایپ کنید یا «انصراف».", reply_markup=kb_cancel(db)); return
        t["messages"].append({"from":"user","text":msg,"ts":_now_ts()})
        _save_db(db)
        clear_state(u); _save_db(db)
        # اطلاع به ادمین‌ها
        for aid in set(db.get("admins", [])):
            try: bot.send_message(aid, f"پیام جدید در تیکت #{tid} از کاربر {u['id']}:\n{msg}")
            except: pass
        bot.send_message(m.chat.id, "پیام شما ارسال شد ✅")
        return

    # تیکت: پاسخ ادمین
    if isadm and st.get("flow")=="ticket_reply_admin" and st.get("step")=="ask_text":
        tid=st.get("tid"); t=db["tickets"].get(tid)
        if not t:
            clear_state(u); _save_db(db)
            bot.send_message(m.chat.id, "تیکت یافت نشد.", reply_markup=kb_main(db,True,u.get("view","user"))); return
        msg=(m.text or "").strip()
        if not msg:
            bot.send_message(m.chat.id,"پیام خالی است. تایپ کنید یا «انصراف».", reply_markup=kb_cancel(db)); return
        t["messages"].append({"from":"admin","text":msg,"ts":_now_ts(),"admin_id":u["id"]})
        _save_db(db)
        clear_state(u); _save_db(db)
        # ارسال برای کاربر
        try: bot.send_message(t["uid"], f"پاسخ ادمین در تیکت #{tid}:\n{msg}")
        except: pass
        bot.send_message(m.chat.id, "پاسخ ارسال شد ✅")
        return

    # ادمین: افزودن/حذف ادمین
    if isadm and st.get("flow")=="admin_add" and st.get("step")=="ask_id":
        if not text.isdigit():
            bot.send_message(m.chat.id,"آیدی عددی معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
        aid=int(text); admins=set(db.get("admins",[])); admins.add(aid); db["admins"]=list(admins)
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, f"✅ ادمین <code>{aid}</code> اضافه شد.", reply_markup=kb_main(db,True,u.get("view","user")))
        try: bot.send_message(aid,"🎉 شما به عنوان ادمین اضافه شدید.")
        except: pass
        return

    if isadm and st.get("flow")=="admin_del" and st.get("step")=="ask_id":
        if not text.isdigit():
            bot.send_message(m.chat.id,"آیدی عددی معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
        aid=int(text); admins=set(db.get("admins",[]))
        if aid in admins:
            admins.remove(aid); db["admins"]=list(admins); _save_db(db)
            try: bot.send_message(aid,"⛔️ دسترسی ادمین شما لغو شد.")
            except: pass
            bot.send_message(m.chat.id, f"🗑 ادمین <code>{aid}</code> حذف شد.", reply_markup=kb_main(db,True,u.get("view","user")))
        else:
            bot.send_message(m.chat.id,"این آیدی جزو ادمین‌ها نیست.", reply_markup=kb_cancel(db))
        clear_state(u); _save_db(db)
        return

    # ادمین: تغییر کارت
    if isadm and st.get("flow")=="set_card" and st.get("step")=="ask_card":
        if len(text.replace("-","").replace(" ",""))<16:
            bot.send_message(m.chat.id,"شماره کارت معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
        db["card_number"]=text.strip(); clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, f"✅ ثبت شد:\n<code>{db['card_number']}</code>", reply_markup=kb_main(db,True,u.get("view","user")))
        return

    # ادمین: اعلان
    if isadm and st.get("flow")=="broadcast" and st.get("step")=="ask_text":
        msg=text; clear_state(u); _save_db(db)
        sent=failed=0
        for _,usr in db["users"].items():
            try: bot.send_message(usr["id"], msg); sent+=1
            except: failed+=1
        bot.send_message(m.chat.id, f"📣 ارسال شد.\nموفق: {sent}\nناموفق: {failed}", reply_markup=kb_main(db,True,u.get("view","user")))
        return

    # ادمین: تأیید رسید → ورود مبلغ (غیر از buy_bank)
    if isadm and st.get("flow")=="rcp_amount" and st.get("step")=="ask_amount":
        rid=st.get("rid")
        if not rid or rid not in db["receipts"]:
            clear_state(u); _save_db(db); bot.send_message(m.chat.id,"رسید یافت نشد.", reply_markup=kb_main(db,True,u.get("view","user"))); return
        val=text.replace(",","")
        if not val.isdigit():
            bot.send_message(m.chat.id,"عدد معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
        amount=int(val); r=db["receipts"][rid]; r["amount"]=amount
        # اعمال
        if r["type"]=="wallet_charge":
            usr=get_user(db, r["uid"]); usr["wallet"]+=amount; r["status"]="approved"
            try: bot.send_message(r["uid"], f"✅ کیف پول شما {human_price(amount)} شارژ شد.")
            except: pass
        elif r["type"]=="charge_diff":
            usr=get_user(db, r["uid"]); usr["wallet"]+=amount; r["status"]="approved"
            try: bot.send_message(r["uid"], f"✅ مابه‌التفاوت {human_price(amount)} شارژ شد.")
            except: pass
        _save_db(db); clear_state(u); _save_db(db)
        bot.send_message(m.chat.id,"✅ ثبت شد.", reply_markup=kb_main(db,True,u.get("view","user")))
        return

    # ادمین: ساخت کوپن مراحل
    if isadm and st.get("flow")=="coupon" and st.get("step")=="ask_percent":
        if not text.isdigit(): bot.send_message(m.chat.id,"درصد به صورت عدد وارد شود.", reply_markup=kb_cancel(db)); return
        p=int(text)
        if p<0 or p>100: bot.send_message(m.chat.id,"درصد بین 0 تا 100.", reply_markup=kb_cancel(db)); return
        set_state(u, step="ask_plan", coupon={"percent": p}); _save_db(db)
        bot.send_message(m.chat.id,"آیا کوپن محدود به پلن است؟ آیدی پلن را بفرستید یا «همه».", reply_markup=kb_cancel(db)); return

    if isadm and st.get("flow")=="coupon" and st.get("step")=="ask_plan":
        cp=u["state"]["coupon"]; cp["only_plan_id"]= None if text=="همه" else text
        set_state(u, step="ask_expire", coupon=cp); _save_db(db)
        bot.send_message(m.chat.id,"تاریخ انقضا (YYYY-MM-DD) یا «بدون».", reply_markup=kb_cancel(db)); return

    if isadm and st.get("flow")=="coupon" and st.get("step")=="ask_expire":
        cp=u["state"]["coupon"]; expire_ts=None
        if text!="بدون":
            try: expire_ts=int(datetime.strptime(text,"%Y-%m-%d").timestamp())
            except: bot.send_message(m.chat.id,"فرمت تاریخ نادرست است.", reply_markup=kb_cancel(db)); return
        cp["expire_ts"]=expire_ts; set_state(u, step="ask_max_uses", coupon=cp); _save_db(db)
        bot.send_message(m.chat.id,"سقف استفاده (عدد) یا «بدون».", reply_markup=kb_cancel(db)); return

    if isadm and st.get("flow")=="coupon" and st.get("step")=="ask_max_uses":
        cp=u["state"]["coupon"]; max_uses=None
        if text!="بدون":
            if not text.isdigit(): bot.send_message(m.chat.id,"عدد معتبر یا «بدون».", reply_markup=kb_cancel(db)); return
            max_uses=int(text)
        cp["max_uses"]=max_uses; set_state(u, step="ask_code", coupon=cp); _save_db(db)
        bot.send_message(m.chat.id,"کد/نام کوپن را بفرستید:", reply_markup=kb_cancel(db)); return

    if isadm and st.get("flow")=="coupon" and st.get("step")=="ask_code":
        code=text.strip()
        if not code: bot.send_message(m.chat.id,"کد معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
        cp=u["state"]["coupon"]; cp["used"]=0; db["coupons"][code]=cp
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, f"✅ کوپن «{code}» ساخته شد.", reply_markup=kb_main(db,True,u.get("view","user"))); return

    # ادمین: شارژ کیف پول کاربر
    if isadm and st.get("flow")=="credit" and st.get("step")=="ask_user":
        target=None
        if text.startswith("@"):
            for usr in db["users"].values():
                if usr.get("username","").lower()==text[1:].lower(): target=usr; break
        elif text.isdigit():
            target=db["users"].get(text)
        if not target:
            bot.send_message(m.chat.id,"کاربر یافت نشد. آیدی عددی یا @یوزرنیم را بفرستید.", reply_markup=kb_cancel(db)); return
        set_state(u, step="ask_amount", target_id=target["id"]); _save_db(db)
        bot.send_message(m.chat.id, f"مبلغ شارژ برای کاربر {target['id']} را وارد کنید:", reply_markup=kb_cancel(db)); return

    if isadm and st.get("flow")=="credit" and st.get("step")=="ask_amount":
        val=text.replace(",","")
        if not val.isdigit(): bot.send_message(m.chat.id,"عدد معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
        amount=int(val)
        tu=get_user(db, st.get("target_id"))
        tu["wallet"]+=amount; clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, f"✅ کیف پول کاربر {tu['id']} به میزان {human_price(amount)} شارژ شد.", reply_markup=kb_main(db,True,u.get("view","user")))
        try: bot.send_message(tu["id"], f"💰 کیف پول شما توسط ادمین به میزان {human_price(amount)} شارژ شد.")
        except: pass
        return

    # ادمین: ساخت پلن مراحل
    if isadm and st.get("flow")=="plan_new":
        plan=u["state"]["plan"]
        if st.get("step")=="ask_name":
            plan["name"]=text; set_state(u, step="ask_days", plan=plan); _save_db(db)
            bot.send_message(m.chat.id,"مدت پلن (روز) را وارد کنید:", reply_markup=kb_cancel(db)); return
        if st.get("step")=="ask_days":
            if not text.isdigit(): bot.send_message(m.chat.id,"عدد معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
            plan["days"]=int(text); set_state(u, step="ask_traffic", plan=plan); _save_db(db)
            bot.send_message(m.chat.id,"حجم/ترافیک (مثلاً 100GB):", reply_markup=kb_cancel(db)); return
        if st.get("step")=="ask_traffic":
            plan["traffic"]=text; set_state(u, step="ask_price", plan=plan); _save_db(db)
            bot.send_message(m.chat.id,"قیمت (تومان) را وارد کنید:", reply_markup=kb_cancel(db)); return
        if st.get("step")=="ask_price":
            if not text.replace(",","").isdigit(): bot.send_message(m.chat.id,"عدد معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
            plan["price"]=int(text.replace(",","")); set_state(u, step="ask_desc", plan=plan); _save_db(db)
            bot.send_message(m.chat.id,"توضیحات پلن:", reply_markup=kb_cancel(db)); return
        if st.get("step")=="ask_desc":
            plan["desc"]=text; plan["stock"]=[]; pid=next_id("plan")
            db["plans"][pid]=plan; _save_db(db); clear_state(u); _save_db(db)
            bot.send_message(m.chat.id, f"✅ پلن «{plan['name']}» ساخته شد.", reply_markup=kb_main(db,True,u.get("view","user"))); return

    # ادمین: افزودن آیتم مخزن
    if isadm and st.get("flow")=="stock_add" and st.get("step")=="ask_item":
        pid=st.get("pid")
        if pid in db["plans"]:
            db["plans"][pid].setdefault("stock",[]).append(text or "—")
            _save_db(db)
            bot.send_message(m.chat.id,"✅ آیتم به مخزن اضافه شد. برای افزودن بیشتر پیام جدید بفرستید یا «انصراف».")
        return

    # ادمین: ویرایش قیمت
    if isadm and st.get("flow")=="plan_edit_price" and st.get("step")=="ask_price":
        pid=st.get("pid")
        if not text.replace(",","").isdigit(): bot.send_message(m.chat.id,"عدد معتبر وارد کنید.", reply_markup=kb_cancel(db)); return
        if pid in db["plans"]:
            db["plans"][pid]["price"]=int(text.replace(",","")); _save_db(db)
        clear_state(u); _save_db(db)
        bot.send_message(m.chat.id,"✅ قیمت بروز شد.", reply_markup=kb_main(db,True,u.get("view","user"))); return

    # ======= اگر state نبود: دکمه‌های منو
    if text == db["texts"]["btn_admin"] and isadm:
        u["view"]="admin_panel"; _save_db(db)
        show_admin_panel(m.chat.id); return

    if text == db["texts"]["btn_back_user"] and isadm:
        u["view"]="user"; clear_state(u); _save_db(db)
        bot.send_message(m.chat.id, "به منوی کاربر برگشتید.", reply_markup=kb_main(db,True,"user")); return

    # منوی کاربر
    t=db["texts"]
    if text == t["btn_buy"]:
        bot.send_message(m.chat.id, "🛍 لطفاً پلن موردنظر را انتخاب کنید:", reply_markup=types.ReplyKeyboardRemove())
        bot.send_message(m.chat.id, "فهرست پلن‌ها:", reply_markup=plans_inline(db)); return

    if text == t["btn_wallet"]:
        bot.send_message(m.chat.id, f"💼 موجودی شما: <b>{human_price(u['wallet'])}</b>", reply_markup=wallet_menu(db,u)); return

    if text == t["btn_tickets"]:
        ik=types.InlineKeyboardMarkup()
        ik.add(types.InlineKeyboardButton("🆕 ایجاد تیکت جدید", callback_data="ticket:new"))
        ik.add(types.InlineKeyboardButton("📂 تیکت‌های من", callback_data="ticket:list"))
        bot.send_message(m.chat.id, "پشتیبانی:", reply_markup=ik); return

    if text == t["btn_account"]:
        cnt=len(u["buys"])
        bot.send_message(m.chat.id,
            f"👤 آیدی: <code>{u['id']}</code>\n"
            f"🧷 یوزرنیم: @{u.get('username','')}\n"
            f"🧾 تعداد خرید: {cnt}\n"
            f"💰 موجودی: {human_price(u['wallet'])}",
            reply_markup=kb_main(db,isadm,u.get("view","user")))
        return

    # پیام ناشناخته:
    bot.send_message(m.chat.id, "از دکمه‌ها استفاده کنید یا «انصراف».", reply_markup=kb_main(db,isadm,u.get("view","user")))

# -----------------------------
# شروع اپ
# -----------------------------
if __name__ == "__main__":
    set_webhook_once()
    port=int(os.getenv("PORT","8000"))
    app.run(host="0.0.0.0", port=port)
