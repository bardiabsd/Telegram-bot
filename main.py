# -*- coding: utf-8 -*-
# main.py
# Telegram Shop Bot - Full Single-File, Button-Only UI
# Frameworks: pyTelegramBotAPI (telebot) + Flask (webhook)
# Gunicorn entry: main:app

import os
import json
import time
import re
from datetime import datetime, timedelta
from threading import Lock

from flask import Flask, request, abort
import telebot
from telebot import types

# -------------------- STATIC CONFIG (from your inputs) --------------------
BOT_TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
APP_URL   = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL  = f"{APP_URL}{WEBHOOK_PATH}"

# DEFAULT ADMIN
DEFAULT_ADMIN_ID = 1743359080

# -------------------- APP/TELEGRAM SETUP ---------------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=4)
server = Flask(__name__)
app = server  # for gunicorn main:app

# -------------------- DATABASE (JSON) ------------------------------------
DB_FILE = "db.json"
_db_lock = Lock()

def _now_ts():
    return int(time.time())

def load_db():
    with _db_lock:
        if not os.path.exists(DB_FILE):
            db = {
                "users": {},             # uid: {id, username, wallet, orders:[], tickets:[], banned:bool}
                "admins": [DEFAULT_ADMIN_ID],
                "plans": {},             # pid: {id, name, days, traffic_gb, price, desc, active:bool}
                "inventory": {},         # pid: [ {text, photo_id(optional)}, ... ]
                "orders": [],            # [{id, uid, pid, price, coupon_code, final, created_at, delivered, expiry}]
                "receipts": [],          # [{id, uid, kind:'purchase'|'topup', amount, status:'pending'|'approved'|'rejected', msg_id, note, created_at, processed_by}]
                "coupons": {},           # code: {code, percent, allowed_plan:'*'|pid, expire_ts, max_uses, used}
                "tickets": {},           # tid: {id, uid, subject, status:'open'|'closed', messages:[{role:'user'|'admin', text, ts}]}
                "settings": {
                    "texts": {
                        "home_title": "به ربات فروش خوش اومدی ✨",
                        "btn_buy": "🛒 خرید پلن",
                        "btn_wallet": "🪙 کیف پول",
                        "btn_tickets": "🎫 تیکت پشتیبانی",
                        "btn_account": "👤 حساب کاربری",
                        "btn_receipts": "🧾 رسیدها",
                        "btn_cancel": "❌ انصراف",
                        "wallet_charge": "شارژ کیف پول",
                        "wallet_tx_history": "تاریخچه تراکنش‌ها",
                        "btn_back": "⬅️ بازگشت",
                        "btn_admin": "🛠 پنل ادمین",
                        "btn_buynow": "خرید",
                        "btn_coupon": "کد تخفیف",
                        "btn_card2card": "💳 کارت‌به‌کارت",
                        "btn_walletpay": "🪙 پرداخت با کیف پول",
                        "btn_plans": "📦 لیست پلن‌ها",
                        "btn_my_orders": "سفارش‌های من",
                        "btn_new_ticket": "تیکت جدید",
                    },
                    "buttons_enabled": {  # feature toggles
                        "buy": True,
                        "wallet": True,
                        "tickets": True,
                        "account": True,
                        "receipts": True
                    },
                    "card_number": "6037-XXXX-XXXX-XXXX به نام شما",  # قابل ویرایش در پنل ادمین
                    "webhook_set_at": 0
                },
                "user_states": {}         # uid: {step, ...context...}
            }
            save_db(db)
            return db
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

def save_db(db):
    with _db_lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)

def get_user(db, uid, username=None):
    u = db["users"].get(str(uid))
    if not u:
        u = {
            "id": uid,
            "username": username or "",
            "wallet": 0,
            "orders": [],
            "tickets": [],
            "banned": False
        }
        db["users"][str(uid)] = u
        save_db(db)
    else:
        if username and u.get("username") != username:
            u["username"] = username
            save_db(db)
    return u

def is_admin(db, uid: int) -> bool:
    return int(uid) in db["admins"]

def set_state(db, uid, **kwargs):
    st = db["user_states"].get(str(uid), {})
    st.update(kwargs)
    db["user_states"][str(uid)] = st
    save_db(db)

def clear_state(db, uid):
    if str(uid) in db["user_states"]:
        del db["user_states"][str(uid)]
        save_db(db)

def get_state(db, uid):
    return db["user_states"].get(str(uid), {})

def plan_stock_count(db, pid):
    inv = db["inventory"].get(str(pid), [])
    return len(inv)

def next_id(prefix):
    # unique id by timestamp
    return f"{prefix}_{int(time.time()*1000)}"

# -------------------- KEYBOARDS ------------------------------------------
def kb_row(*btns):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(*btns)
    return kb

def home_kb(db, uid):
    t = db["settings"]["texts"]
    be = db["settings"]["buttons_enabled"]
    rows = []
    if be.get("buy"):     rows.append(t["btn_buy"])
    if be.get("wallet"):  rows.append(t["btn_wallet"])
    if be.get("tickets"): rows.append(t["btn_tickets"])
    if be.get("account"): rows.append(t["btn_account"])
    if be.get("receipts"): rows.append(t["btn_receipts"])
    # arrange in 2 per row
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    temp = []
    for b in rows:
        temp.append(types.KeyboardButton(b))
        if len(temp)==2:
            kb.row(*temp); temp=[]
    if temp: kb.row(*temp)
    if is_admin(load_db(), uid):
        kb.row(types.KeyboardButton(db["settings"]["texts"]["btn_admin"]))
    return kb

def back_kb(db):
    return kb_row(db["settings"]["texts"]["btn_back"], db["settings"]["texts"]["btn_cancel"])

def yesno_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("✅ بله", "❌ خیر")
    return kb

def admin_main_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📦 مدیریت پلن‌ها/مخزن", "🏷 کدهای تخفیف")
    kb.row("🪙 کیف پول کاربران", "🧾 رسیدها")
    kb.row("👥 مدیریت کاربران", "👑 مدیریت ادمین‌ها")
    kb.row("🧰 دکمه‌ها و متون", "📢 اعلان همگانی")
    kb.row("📊 آمار فروش")
    kb.row("⬅️ بازگشت به خانه")
    return kb

def plans_list_kb(db, include_back=True):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    for pid, p in db["plans"].items():
        title = f"{p['name']} ({plan_stock_count(db, pid)})"
        row.append(types.KeyboardButton(title))
        if len(row)==2:
            kb.row(*row); row=[]
    if row: kb.row(*row)
    kb.row("➕ افزودن پلن")
    if include_back:
        kb.row("⬅️ بازگشت")
    return kb

def buy_flow_kb(db, pid):
    t = db["settings"]["texts"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(t["btn_coupon"])
    kb.row(t["btn_card2card"], t["btn_walletpay"])
    kb.row(t["btn_cancel"])
    return kb

def wallet_kb(db):
    t = db["settings"]["texts"]
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(t["wallet_charge"], t["wallet_tx_history"])
    kb.row(db["settings"]["texts"]["btn_back"])
    return kb

def receipts_admin_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🕒 رسیدهای در انتظار", "✅ تأیید شده", "⛔ رد شده")
    kb.row("⬅️ بازگشت")
    return kb

def buttons_texts_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🔘 روشن/خاموش دکمه‌ها")
    kb.row("📝 ویرایش متون")
    kb.row("💳 شماره کارت")
    kb.row("⬅️ بازگشت")
    return kb

# -------------------- UTIL -----------------------------------------------
def fmt_money(x):
    try:
        x = int(x)
    except:
        return str(x)
    return f"{x:,} تومان".replace(",", "،")

def parse_int(msg_text):
    # accepts digits with optional spaces/commas
    s = re.sub(r"[^\d]", "", msg_text or "")
    return int(s) if s.isdigit() else None

def apply_coupon(db, pid, price, code):
    if not code: 
        return price, None, "کدی وارد نشده."
    c = db["coupons"].get(code.upper())
    if not c: 
        return price, None, "کد نامعتبر است."
    now = _now_ts()
    if c["expire_ts"] and now > c["expire_ts"]:
        return price, None, "کد منقضی شده."
    if c["max_uses"] and c["used"] >= c["max_uses"]:
        return price, None, "سقف استفاده از کد پر شده."
    allowed = c["allowed_plan"]
    if allowed not in ("*", str(pid)):
        return price, None, "این کد مخصوص پلن دیگری است."
    off = (price * int(c["percent"])) // 100
    final = max(price - off, 0)
    return final, c, f"تخفیف {c['percent']}٪ اعمال شد."

def deliver_config(db, uid, pid, chat_id):
    inv = db["inventory"].get(str(pid), [])
    if not inv:
        bot.send_message(chat_id, "❗ مخزن این پلن خالی است.")
        return False
    item = inv.pop(0)
    save_db(db)
    # send text + optional photo
    if item.get("photo_id"):
        bot.send_photo(chat_id, item["photo_id"], caption=item.get("text",""))
    else:
        bot.send_message(chat_id, item.get("text",""))
    return True

def calc_stats(db):
    total_orders = len(db["orders"])
    total_revenue = sum(o.get("final", o.get("price",0)) for o in db["orders"])
    buyers = {}
    for o in db["orders"]:
        uid = str(o["uid"])
        buyers.setdefault(uid, {"count":0, "sum":0})
        buyers[uid]["count"] += 1
        buyers[uid]["sum"] += int(o.get("final", o.get("price",0)))
    top = sorted(buyers.items(), key=lambda x: (-x[1]["sum"], -x[1]["count"]))[:10]
    top_list = []
    for uid, d in top:
        u = db["users"].get(uid, {})
        top_list.append({
            "uid": int(uid),
            "username": u.get("username",""),
            "count": d["count"],
            "sum": d["sum"]
        })
    return total_orders, total_revenue, top_list

# -------------------- WEBHOOK --------------------------------------------
def set_webhook_once():
    db = load_db()
    last = db["settings"].get("webhook_set_at", 0)
    now = _now_ts()
    # فقط هر چند دقیقه یک‌بار ست کنیم تا 429 نگیریم
    if now - last < 60:
        return
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        db["settings"]["webhook_set_at"] = now
        save_db(db)
        print(f"{datetime.utcnow()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print(f"{datetime.utcnow()} | ERROR | Failed to set webhook: {e}")

@server.route("/", methods=["GET"])
def index():
    return "OK", 200

@server.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    else:
        abort(403)

# -------------------- MESSAGE FLOW (BUTTON-ONLY) -------------------------
def send_home(uid, chat_id):
    db = load_db()
    t = db["settings"]["texts"]
    bot.send_message(chat_id, t["home_title"], reply_markup=home_kb(db, uid))
    clear_state(db, uid)

@bot.message_handler(content_types=['text'])
def on_text(m: types.Message):
    set_webhook_once()  # try to set webhook sparsely
    db = load_db()
    uid = m.from_user.id
    username = (m.from_user.username or "") if m.from_user else ""
    u = get_user(db, uid, username)

    if u.get("banned"):
        return

    text = (m.text or "").strip()

    # Global cancels/back
    if text in (db["settings"]["texts"]["btn_cancel"], "❌ انصراف"):
        clear_state(db, uid)
        send_home(uid, m.chat.id)
        return
    if text in ("⬅️ بازگشت", "⬅️ بازگشت به خانه", db["settings"]["texts"]["btn_back"]):
        clear_state(db, uid)
        send_home(uid, m.chat.id)
        return

    # ADMIN PANEL
    if text == db["settings"]["texts"]["btn_admin"] and is_admin(db, uid):
        bot.send_message(m.chat.id, "🛠 پنل ادمین", reply_markup=admin_main_kb())
        set_state(db, uid, step="admin_home")
        return

    st = get_state(db, uid)
    step = st.get("step")

    # ---------------- HOME BUTTONS ----------------
    t = db["settings"]["texts"]
    if text == t["btn_buy"]:
        # list plans with stock count
        if not db["plans"]:
            bot.send_message(m.chat.id, "هنوز پلنی ثبت نشده.")
            return
        bot.send_message(m.chat.id, "📦 لیست پلن‌ها (عدد داخل پرانتز = موجودی):", reply_markup=plans_list_kb(db))
        set_state(db, uid, step="choose_plan")
        return

    if text == t["btn_wallet"]:
        kb = wallet_kb(db)
        bot.send_message(m.chat.id, f"موجودی فعلی: {fmt_money(u['wallet'])}", reply_markup=kb)
        set_state(db, uid, step="wallet_menu")
        return

    if text == t["btn_tickets"]:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(t["btn_new_ticket"])
        kb.row(t["btn_back"])
        # list open tickets
        my_tickets = [db["tickets"][tid] for tid in u["tickets"]] if u["tickets"] else []
        if my_tickets:
            lines = ["📂 تیکت‌های شما:"]
            for tk in my_tickets[-10:]:
                lines.append(f"#{tk['id']} | {tk['subject']} | {('باز' if tk['status']=='open' else 'بسته')}")
            bot.send_message(m.chat.id, "\n".join(lines), reply_markup=kb)
        else:
            bot.send_message(m.chat.id, "هیچ تیکتی ندارید.", reply_markup=kb)
        set_state(db, uid, step="tickets_menu")
        return

    if text == t["btn_account"]:
        orders = [o for o in db["orders"] if o["uid"]==uid]
        lines = [f"آیدی عددی: {uid}",
                 f"یوزرنیم: @{u.get('username','')}" if u.get("username") else "یوزرنیم: -",
                 f"تعداد کانفیگ‌های خریداری‌شده: {len(orders)}"]
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row(t["btn_my_orders"])
        kb.row(t["btn_back"])
        bot.send_message(m.chat.id, "👤 حساب کاربری\n" + "\n".join(lines), reply_markup=kb)
        set_state(db, uid, step="account_menu")
        return

    if text == t["btn_receipts"]:
        # show user's receipts
        my = [r for r in db["receipts"] if r["uid"]==uid]
        if not my:
            bot.send_message(m.chat.id, "هیچ رسیدی ثبت نشده.")
        else:
            lines = ["🧾 رسیدهای شما:"]
            for r in my[-15:]:
                lines.append(f"#{r['id']} | نوع: {'خرید' if r['kind']=='purchase' else 'شارژ کیف پول'} | وضعیت: {r['status']} | مبلغ: {fmt_money(r.get('amount',0))}")
            bot.send_message(m.chat.id, "\n".join(lines))
        send_home(uid, m.chat.id)
        return

    # ---------------- FLOW: PLANS/BUY ----------------
    if step == "choose_plan":
        if text == "➕ افزودن پلن" and is_admin(db, uid):
            bot.send_message(m.chat.id, "نام پلن را وارد کنید:", reply_markup=back_kb(db))
            set_state(db, uid, step="add_plan_name")
            return
        # find clicked plan by title prefix
        chosen = None
        for pid, p in db["plans"].items():
            title = f"{p['name']} ({plan_stock_count(db, pid)})"
            if text == title:
                chosen = p
                break
        if not chosen:
            bot.send_message(m.chat.id, "پلن نامعتبر.")
            return

        pid = chosen["id"]
        stock = plan_stock_count(db, pid)
        msg = (f"🧾 مشخصات پلن:\n"
               f"نام: {chosen['name']}\n"
               f"مدت: {chosen['days']} روز\n"
               f"حجم: {chosen['traffic_gb']} گیگ\n"
               f"قیمت: {fmt_money(chosen['price'])}\n"
               f"توضیح: {chosen.get('desc','-')}\n"
               f"موجودی مخزن: {stock}")
        bot.send_message(m.chat.id, msg, reply_markup=buy_flow_kb(db, pid))
        set_state(db, uid, step="buy_menu", plan_id=pid, base_price=int(chosen['price']), coupon=None, final=int(chosen['price']))
        return

    if step == "buy_menu":
        if text == t["btn_coupon"]:
            bot.send_message(m.chat.id, "کد تخفیف را وارد کنید (یا «انصراف»):", reply_markup=back_kb(db))
            set_state(db, uid, step="enter_coupon")
            return
        if text == t["btn_card2card"]:
            card = db["settings"]["card_number"]
            final = get_state(db, uid).get("final")
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("📤 ارسال رسید خرید")
            kb.row(t["btn_cancel"])
            bot.send_message(m.chat.id,
                             f"💳 کارت‌به‌کارت\nمبلغ قابل پرداخت: {fmt_money(final)}\n"
                             f"شماره کارت:\n{card}\n\n"
                             f"بعد از واریز، روی «ارسال رسید خرید» بزنید و تصویر/پیام رسید را بفرستید.",
                             reply_markup=kb)
            set_state(db, uid, step="await_purchase_receipt")
            return
        if text == t["btn_walletpay"]:
            st = get_state(db, uid)
            need = st.get("final", st.get("base_price"))
            if u["wallet"] >= need:
                # charge and deliver
                u["wallet"] -= need
                order_id = next_id("ord")
                expiry = (datetime.utcnow() + timedelta(days= db["plans"][str(st["plan_id"])]["days"])).strftime("%Y-%m-%d")
                db["orders"].append({
                    "id": order_id, "uid": uid, "pid": st["plan_id"],
                    "price": st["base_price"], "final": need,
                    "coupon_code": (st.get("coupon") or {}).get("code"),
                    "created_at": _now_ts(), "delivered": False, "expiry": expiry
                })
                # deliver
                ok = deliver_config(db, uid, st["plan_id"], m.chat.id)
                if ok:
                    db["orders"][-1]["delivered"] = True
                save_db(db)
                bot.send_message(m.chat.id, f"✅ خرید انجام شد. موجودی جدید کیف پول: {fmt_money(u['wallet'])}")
                clear_state(db, uid)
                send_home(uid, m.chat.id)
            else:
                diff = need - u["wallet"]
                kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
                kb.row(f"🔼 شارژ {fmt_money(diff)}")
                kb.row(t["btn_cancel"])
                bot.send_message(m.chat.id, f"موجودی کافی نیست. مابه‌التفاوت: {fmt_money(diff)}", reply_markup=kb)
                set_state(db, uid, step="wallet_topup_diff", diff=diff)
            return

    if step == "enter_coupon":
        if text in (db["settings"]["texts"]["btn_cancel"], "❌ انصراف", "⬅️ بازگشت"):
            # back to buy menu
            st = get_state(db, uid)
            bot.send_message(m.chat.id, "به صفحه خرید برگشتید.", reply_markup=buy_flow_kb(db, st.get("plan_id")))
            set_state(db, uid, step="buy_menu")
            return
        st = get_state(db, uid)
        final, c, msg = apply_coupon(db, st["plan_id"], st["base_price"], text.strip())
        if c:
            bot.send_message(m.chat.id, f"✅ {msg}\nمبلغ نهایی: {fmt_money(final)}")
            set_state(db, uid, step="buy_menu", coupon=c, final=final)
        else:
            bot.send_message(m.chat.id, f"⚠️ {msg}")
            # stay in coupon entry

    if step == "wallet_topup_diff":
        if text.startswith("🔼 شارژ"):
            diff = get_state(db, uid).get("diff")
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("📤 ارسال رسید شارژ")
            kb.row(db["settings"]["texts"]["btn_cancel"])
            bot.send_message(m.chat.id, f"برای شارژ {fmt_money(diff)} واریز کنید و «ارسال رسید شارژ» را بزنید.", reply_markup=kb)
            set_state(db, uid, step="await_topup_receipt", expected=diff)
            return

    if step == "wallet_menu":
        if text == t["wallet_charge"]:
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("📤 ارسال رسید شارژ")
            kb.row(t["btn_cancel"])
            bot.send_message(m.chat.id, "مبلغ موردنظر را واریز کنید و سپس «ارسال رسید شارژ» را بزنید.", reply_markup=kb)
            set_state(db, uid, step="await_topup_receipt", expected=None)
            return
        if text == t["wallet_tx_history"]:
            txs = []
            for r in db["receipts"]:
                if r["uid"]==uid and r["kind"]=="topup" and r["status"]=="approved":
                    txs.append(r)
            if not txs:
                bot.send_message(m.chat.id, "تراکنشی یافت نشد.")
            else:
                lines = ["تاریخچه تراکنش‌های کیف پول:"]
                for r in txs[-20:]:
                    lines.append(f"#{r['id']} | مبلغ: {fmt_money(r['amount'])} | تاریخ: {datetime.fromtimestamp(r['created_at']).strftime('%Y-%m-%d %H:%M')}")
                bot.send_message(m.chat.id, "\n".join(lines))
            send_home(uid, m.chat.id)
            return

    if step == "tickets_menu":
        if text == t["btn_new_ticket"]:
            bot.send_message(m.chat.id, "موضوع تیکت را وارد کنید:", reply_markup=back_kb(db))
            set_state(db, uid, step="new_ticket_subject")
            return
        # open a ticket by id if user typed #id
        if re.match(r"^#\w+", text):
            tid = text[1:]
            tk = db["tickets"].get(tid)
            if not tk or tk["uid"]!=uid:
                bot.send_message(m.chat.id, "تیکت یافت نشد.")
            else:
                # show last messages
                msgs = []
                for msg in tk["messages"][-10:]:
                    who = "👤شما" if msg["role"]=="user" else "👑ادمین"
                    msgs.append(f"{who}: {msg['text']}")
                kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
                kb.row("✍️ ارسال پیام در همین تیکت")
                kb.row("🔒 بستن تیکت")
                kb.row(db["settings"]["texts"]["btn_back"])
                bot.send_message(m.chat.id, f"تیکت #{tid} | {tk['subject']} | وضعیت: {('باز' if tk['status']=='open' else 'بسته')}\n" + "\n".join(msgs), reply_markup=kb)
                set_state(db, uid, step="ticket_view", tid=tid)
            return

    if step == "new_ticket_subject":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            clear_state(db, uid); send_home(uid, m.chat.id); return
        subject = text
        tid = next_id("tkt")
        tk = {"id": tid, "uid": uid, "subject": subject, "status":"open", "messages":[]}
        db["tickets"][tid] = tk
        u["tickets"].append(tid)
        save_db(db)
        bot.send_message(m.chat.id, "متن پیام اولیه را بنویسید:", reply_markup=back_kb(db))
        set_state(db, uid, step="new_ticket_message", tid=tid)
        return

    if step == "new_ticket_message":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            clear_state(db, uid); send_home(uid, m.chat.id); return
        tid = get_state(db, uid)["tid"]
        tk = db["tickets"][tid]
        tk["messages"].append({"role":"user","text":text,"ts":_now_ts()})
        save_db(db)
        bot.send_message(m.chat.id, f"تیکت #{tid} ثبت شد. منتظر پاسخ ادمین باشید.")
        # notify admins
        for aid in db["admins"]:
            try:
                bot.send_message(aid, f"📩 تیکت جدید #{tid}\nاز: {uid} @{u.get('username','')}\nموضوع: {tk['subject']}\nمتن: {text}")
            except: pass
        clear_state(db, uid); send_home(uid, m.chat.id); return

    if step == "ticket_view":
        tid = get_state(db, uid)["tid"]
        tk = db["tickets"].get(tid)
        if not tk: 
            send_home(uid, m.chat.id); return
        if text == "✍️ ارسال پیام در همین تیکت":
            bot.send_message(m.chat.id, "پیام خود را بنویسید:", reply_markup=back_kb(db))
            set_state(db, uid, step="ticket_reply", tid=tid)
            return
        if text == "🔒 بستن تیکت":
            tk["status"]="closed"; save_db(db)
            bot.send_message(m.chat.id, "تیکت بسته شد.")
            clear_state(db, uid); send_home(uid, m.chat.id); return

    if step == "ticket_reply":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            clear_state(db, uid); send_home(uid, m.chat.id); return
        tid = get_state(db, uid)["tid"]
        tk = db["tickets"].get(tid); 
        if not tk: 
            send_home(uid, m.chat.id); return
        tk["messages"].append({"role":"user","text":text,"ts":_now_ts()})
        save_db(db)
        bot.send_message(m.chat.id, "پیام شما ارسال شد.")
        for aid in db["admins"]:
            try:
                bot.send_message(aid, f"🗨️ پیام جدید در تیکت #{tid} از {uid}:\n{text}")
            except: pass
        clear_state(db, uid); send_home(uid, m.chat.id); return

    # ---------------- ADMIN FLOWS ----------------
    if step == "admin_home":
        if text == "📦 مدیریت پلن‌ها/مخزن":
            bot.send_message(m.chat.id, "مدیریت پلن‌ها و مخزن:", reply_markup=plans_list_kb(db, include_back=True))
            set_state(db, uid, step="admin_plans")
            return
        if text == "🏷 کدهای تخفیف":
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("➕ ساخت کد تخفیف")
            kb.row("📄 لیست کدها")
            kb.row("⬅️ بازگشت")
            bot.send_message(m.chat.id, "مدیریت کدهای تخفیف:", reply_markup=kb)
            set_state(db, uid, step="admin_coupons")
            return
        if text == "🪙 کیف پول کاربران":
            bot.send_message(m.chat.id, "آیدی عددی کاربر را وارد کنید:", reply_markup=back_kb(db))
            set_state(db, uid, step="admin_wallet_user")
            return
        if text == "🧾 رسیدها":
            bot.send_message(m.chat.id, "مدیریت رسیدها:", reply_markup=receipts_admin_kb())
            set_state(db, uid, step="admin_receipts")
            return
        if text == "👥 مدیریت کاربران":
            bot.send_message(m.chat.id, "برای مشاهده پروفایل کاربر آیدی عددی یا @یوزرنیم را بفرستید:", reply_markup=back_kb(db))
            set_state(db, uid, step="admin_users")
            return
        if text == "👑 مدیریت ادمین‌ها":
            cur = ", ".join(str(a) for a in db["admins"])
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("➕ افزودن ادمین", "➖ حذف ادمین")
            kb.row("⬅️ بازگشت")
            bot.send_message(m.chat.id, f"لیست ادمین‌ها: {cur}", reply_markup=kb)
            set_state(db, uid, step="admin_admins")
            return
        if text == "🧰 دکمه‌ها و متون":
            bot.send_message(m.chat.id, "تنظیمات دکمه‌ها و متون:", reply_markup=buttons_texts_kb())
            set_state(db, uid, step="admin_btn_txt")
            return
        if text == "📢 اعلان همگانی":
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("✍️ نوشتن پیام و ارسال")
            kb.row("⬅️ بازگشت")
            bot.send_message(m.chat.id, "پیامی که می‌خواهید برای همه ارسال شود را بنویسید.", reply_markup=kb)
            set_state(db, uid, step="broadcast_menu")
            return
        if text == "📊 آمار فروش":
            total_orders, total_rev, top = calc_stats(db)
            lines = [f"📊 آمار فروش",
                     f"تعداد فروش: {total_orders}",
                     f"درآمد کل: {fmt_money(total_rev)}",
                     "",
                     "Top Buyers:"]
            if not top:
                lines.append("—")
            else:
                for i, ttt in enumerate(top, 1):
                    lines.append(f"{i}) {ttt['uid']} @{ttt['username']} | خرید: {ttt['count']} | مجموع: {fmt_money(ttt['sum'])}")
            bot.send_message(m.chat.id, "\n".join(lines))
            return

        if text == "⬅️ بازگشت به خانه":
            clear_state(db, uid); send_home(uid, m.chat.id); return

    # --- Admin: Plans & Inventory
    if step == "admin_plans":
        if text == "⬅️ بازگشت":
            bot.send_message(m.chat.id, "🛠 پنل ادمین", reply_markup=admin_main_kb())
            set_state(db, uid, step="admin_home")
            return
        if text == "➕ افزودن پلن":
            bot.send_message(m.chat.id, "نام پلن را وارد کنید:", reply_markup=back_kb(db))
            set_state(db, uid, step="add_plan_name")
            return
        # select plan by title
        chosen = None
        for pid, p in db["plans"].items():
            title = f"{p['name']} ({plan_stock_count(db, pid)})"
            if text == title:
                chosen = p; break
        if not chosen:
            bot.send_message(m.chat.id, "پلن نامعتبر.")
            return
        pid = chosen["id"]
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("📝 ویرایش مشخصات", "🗑 حذف پلن")
        kb.row("📦 مخزن این پلن")
        kb.row("⬅️ بازگشت")
        bot.send_message(m.chat.id, f"پلن «{chosen['name']}» انتخاب شد.", reply_markup=kb)
        set_state(db, uid, step="plan_menu", pid=pid)
        return

    if step == "add_plan_name":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb())
            set_state(db, uid, step="admin_home"); return
        name = text.strip()
        set_state(db, uid, step="add_plan_days", name=name)
        bot.send_message(m.chat.id, "مدت (روز) را وارد کنید:", reply_markup=back_kb(db))
        return

    if step == "add_plan_days":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_plans"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=plans_list_kb(db)); return
        days = parse_int(text)
        if days is None or days <= 0:
            bot.send_message(m.chat.id, "عدد معتبر وارد کنید.")
            return
        st = get_state(db, uid)
        set_state(db, uid, step="add_plan_traffic", name=st["name"], days=days)
        bot.send_message(m.chat.id, "حجم (گیگ) را وارد کنید:", reply_markup=back_kb(db))
        return

    if step == "add_plan_traffic":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_plans"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=plans_list_kb(db)); return
        tr = parse_int(text)
        if tr is None or tr <= 0:
            bot.send_message(m.chat.id, "عدد معتبر وارد کنید.")
            return
        st = get_state(db, uid)
        set_state(db, uid, step="add_plan_price", name=st["name"], days=st["days"], traffic=tr)
        bot.send_message(m.chat.id, "قیمت (تومان) را وارد کنید:", reply_markup=back_kb(db))
        return

    if step == "add_plan_price":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_plans"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=plans_list_kb(db)); return
        price = parse_int(text)
        if price is None or price < 0:
            bot.send_message(m.chat.id, "عدد معتبر وارد کنید.")
            return
        st = get_state(db, uid)
        pid = next_id("plan")
        db["plans"][pid] = {
            "id": pid, "name": st["name"], "days": st["days"],
            "traffic_gb": st["traffic"], "price": price, "desc":"-", "active": True
        }
        db["inventory"][pid] = []
        save_db(db)
        bot.send_message(m.chat.id, "پلن ایجاد شد.", reply_markup=plans_list_kb(db))
        set_state(db, uid, step="admin_plans")
        return

    if step == "plan_menu":
        pid = get_state(db, uid)["pid"]
        p = db["plans"].get(pid)
        if not p:
            bot.send_message(m.chat.id, "پلن یافت نشد."); set_state(db, uid, step="admin_plans"); return
        if text == "📝 ویرایش مشخصات":
            bot.send_message(m.chat.id, "توضیح جدید را وارد کنید (دلخواه، برای ردکردن بنویسید - ):", reply_markup=back_kb(db))
            set_state(db, uid, step="edit_plan_desc", pid=pid)
            return
        if text == "🗑 حذف پلن":
            del db["plans"][pid]; db["inventory"].pop(pid, None); save_db(db)
            bot.send_message(m.chat.id, "پلن حذف شد.", reply_markup=plans_list_kb(db))
            set_state(db, uid, step="admin_plans"); return
        if text == "📦 مخزن این پلن":
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("➕ افزودن کانفیگ", "🗂 لیست مخزن")
            kb.row("⬅️ بازگشت")
            bot.send_message(m.chat.id, "مخزن:", reply_markup=kb)
            set_state(db, uid, step="inv_menu", pid=pid)
            return
        if text == "⬅️ بازگشت":
            bot.send_message(m.chat.id, "بازگشت.", reply_markup=plans_list_kb(db))
            set_state(db, uid, step="admin_plans"); return

    if step == "edit_plan_desc":
        pid = get_state(db, uid)["pid"]
        if text in ("⬅️ بازگشت","❌ انصراف"): 
            set_state(db, uid, step="plan_menu", pid=pid); return
        if text.strip() != "-":
            db["plans"][pid]["desc"] = text.strip()
            save_db(db)
        bot.send_message(m.chat.id, "به‌روزرسانی شد.")
        set_state(db, uid, step="plan_menu", pid=pid)
        return

    if step == "inv_menu":
        pid = get_state(db, uid)["pid"]
        if text == "➕ افزودن کانفیگ":
            bot.send_message(m.chat.id, "متن کانفیگ را بفرستید (می‌توانید عکس هم بعداً اضافه کنید).", reply_markup=back_kb(db))
            set_state(db, uid, step="inv_add_text", pid=pid, temp={"text": None, "photo_id": None})
            return
        if text == "🗂 لیست مخزن":
            inv = db["inventory"].get(pid, [])
            if not inv:
                bot.send_message(m.chat.id, "مخزن خالی است.")
            else:
                bot.send_message(m.chat.id, f"تعداد آیتم‌ها: {len(inv)}")
            return
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="plan_menu", pid=pid)
            bot.send_message(m.chat.id, "بازگشت.", reply_markup=plans_list_kb(db))
            return

    # --- Admin: Coupons
    if step == "admin_coupons":
        if text == "➕ ساخت کد تخفیف":
            bot.send_message(m.chat.id, "درصد تخفیف را وارد کنید (مثلاً 10):", reply_markup=back_kb(db))
            set_state(db, uid, step="coupon_percent")
            return
        if text == "📄 لیست کدها":
            if not db["coupons"]:
                bot.send_message(m.chat.id, "کدی ثبت نشده.")
            else:
                lines = ["کدها:"]
                for code, c in db["coupons"].items():
                    exp = datetime.fromtimestamp(c["expire_ts"]).strftime("%Y-%m-%d") if c["expire_ts"] else "-"
                    lines.append(f"{code} | {c['percent']}% | پلن: {c['allowed_plan']} | تا: {exp} | استفاده: {c['used']}/{c['max_uses'] or '∞'}")
                bot.send_message(m.chat.id, "\n".join(lines))
            return
        if text == "⬅️ بازگشت":
            bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb())
            set_state(db, uid, step="admin_home"); return

    if step == "coupon_percent":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_coupons"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        val = parse_int(text)
        if val is None or not (0 <= val <= 100):
            bot.send_message(m.chat.id, "درصد معتبر (0 تا 100) وارد کنید.")
            return
        set_state(db, uid, step="coupon_plan", coupon={"percent": int(val)})
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("همه پلن‌ها")
        # also list plans
        for pid, p in db["plans"].items():
            kb.row(f"{p['name']}|{pid}")
        kb.row("⬅️ بازگشت")
        bot.send_message(m.chat.id, "محدودیت پلن: «همه پلن‌ها» یا یکی از پلن‌ها را انتخاب کنید.", reply_markup=kb)
        return

    if step == "coupon_plan":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_coupons"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        st = get_state(db, uid)
        cpn = st.get("coupon", {})
        if text == "همه پلن‌ها":
            cpn["allowed_plan"] = "*"
        else:
            # expected format: name|pid
            if "|" not in text:
                bot.send_message(m.chat.id, "یکی از گزینه‌ها را انتخاب کنید.")
                return
            pid = text.split("|",1)[1]
            if pid not in db["plans"]:
                bot.send_message(m.chat.id, "پلن نامعتبر.")
                return
            cpn["allowed_plan"] = pid
        set_state(db, uid, step="coupon_expire", coupon=cpn)
        bot.send_message(m.chat.id, "تاریخ انقضا را وارد کنید به فرم YYYY-MM-DD یا «-» برای بدون انقضا:", reply_markup=back_kb(db))
        return

    if step == "coupon_expire":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_coupons"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        st = get_state(db, uid)
        cpn = st.get("coupon", {})
        if text.strip() == "-":
            cpn["expire_ts"] = None
        else:
            try:
                d = datetime.strptime(text.strip(), "%Y-%m-%d")
                cpn["expire_ts"] = int(d.timestamp())
            except:
                bot.send_message(m.chat.id, "فرمت تاریخ نامعتبر است.")
                return
        set_state(db, uid, step="coupon_max", coupon=cpn)
        bot.send_message(m.chat.id, "حداکثر دفعات استفاده را وارد کنید (یا «-» برای نامحدود):", reply_markup=back_kb(db))
        return

    if step == "coupon_max":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_coupons"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        st = get_state(db, uid)
        cpn = st.get("coupon", {})
        if text.strip() == "-":
            cpn["max_uses"] = None
        else:
            val = parse_int(text)
            if val is None or val <= 0:
                bot.send_message(m.chat.id, "عدد معتبر وارد کنید یا «-».")
                return
            cpn["max_uses"] = val
        set_state(db, uid, step="coupon_code", coupon=cpn)
        bot.send_message(m.chat.id, "نام/کد تخفیف را وارد کنید (مثلاً OFF10):", reply_markup=back_kb(db))
        return

    if step == "coupon_code":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_coupons"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        code = text.strip().upper()
        if not re.match(r"^[A-Z0-9_\-]{2,}$", code):
            bot.send_message(m.chat.id, "کد نامعتبر است.")
            return
        st = get_state(db, uid)
        cpn = st.get("coupon", {})
        cpn.update({"code": code, "used": 0})
        db["coupons"][code] = cpn
        save_db(db)
        bot.send_message(m.chat.id, f"کد {code} ساخته شد.", reply_markup=admin_main_kb())
        set_state(db, uid, step="admin_home")
        return

    # --- Admin: Wallet users
    if step == "admin_wallet_user":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        # get user
        target = None
        if text.startswith("@"):
            uname = text[1:].lower()
            for usr in db["users"].values():
                if usr.get("username","").lower() == uname:
                    target = usr; break
        else:
            tid = parse_int(text)
            if tid and str(tid) in db["users"]:
                target = db["users"][str(tid)]
        if not target:
            bot.send_message(m.chat.id, "کاربر یافت نشد.")
            return
        set_state(db, uid, step="admin_wallet_action", target_id=target["id"])
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("➕ افزایش موجودی", "➖ کاهش موجودی")
        kb.row("⬅️ بازگشت")
        bot.send_message(m.chat.id, f"کاربر انتخاب شد: {target['id']} @{target.get('username','')}\nموجودی: {fmt_money(target['wallet'])}", reply_markup=kb)
        return

    if step == "admin_wallet_action":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        if text in ("➕ افزایش موجودی","➖ کاهش موجودی"):
            inc = (text.startswith("➕"))
            set_state(db, uid, step="admin_wallet_amount", inc=inc)
            bot.send_message(m.chat.id, "مبلغ را به تومان وارد کنید:", reply_markup=back_kb(db))
            return

    if step == "admin_wallet_amount":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        amount = parse_int(text)
        if amount is None or amount <= 0:
            bot.send_message(m.chat.id, "عدد معتبر وارد کنید.")
            return
        st = get_state(db, uid)
        target = db["users"].get(str(st["target_id"]))
        if not target:
            bot.send_message(m.chat.id, "کاربر یافت نشد."); return
        if st.get("inc"):
            target["wallet"] += amount
            note = f"شارژ دستی ادمین +{fmt_money(amount)}"
        else:
            target["wallet"] = max(0, target["wallet"] - amount)
            note = f"کسر دستی ادمین -{fmt_money(amount)}"
        save_db(db)
        bot.send_message(m.chat.id, f"انجام شد. موجودی جدید: {fmt_money(target['wallet'])}")
        try:
            bot.send_message(target["id"], f"🪙 {note}\nموجودی فعلی: {fmt_money(target['wallet'])}")
        except: pass
        set_state(db, uid, step="admin_home")
        bot.send_message(m.chat.id, "بازگشت به پنل.", reply_markup=admin_main_kb())
        return

    # --- Admin: Receipts
    if step == "admin_receipts":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        status_map = {"🕒 رسیدهای در انتظار":"pending", "✅ تأیید شده":"approved", "⛔ رد شده":"rejected"}
        if text not in status_map:
            bot.send_message(m.chat.id, "گزینه نامعتبر.")
            return
        stname = status_map[text]
        lst = [r for r in db["receipts"] if r["status"]==stname]
        if not lst:
            bot.send_message(m.chat.id, "موردی نیست.")
            return
        for r in lst[-20:]:
            bot.send_message(m.chat.id,
                             f"#{r['id']} | نوع: {'خرید' if r['kind']=='purchase' else 'شارژ کیف پول'} | کاربر: {r['uid']} @{db['users'].get(str(r['uid']),{}).get('username','')}\n"
                             f"مبلغ/انتظار: {fmt_money(r.get('amount') or r.get('expected') or 0)} | وضعیت: {r['status']}")
        bot.send_message(m.chat.id, "برای بررسی/تأیید/رد، آی‌دی رسید را به صورت #ID بفرستید.")
        set_state(db, uid, step="admin_receipt_pick")
        return

    if step == "admin_receipt_pick":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        if not text.startswith("#"):
            bot.send_message(m.chat.id, "فرمت صحیح #ID را بفرستید.")
            return
        rid = text[1:]
        rec = next((r for r in db["receipts"] if r["id"]==rid), None)
        if not rec:
            bot.send_message(m.chat.id, "رسید یافت نشد.")
            return
        set_state(db, uid, step="admin_receipt_action", rid=rid)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        if rec["kind"]=="topup" and rec["status"]=="pending":
            kb.row("✅ تأیید شارژ (وارد کردن مبلغ)")
        if rec["kind"]=="purchase" and rec["status"]=="pending":
            kb.row("✅ تأیید خرید و ارسال")
        if rec["status"]=="pending":
            kb.row("⛔ رد")
        kb.row("⬅️ بازگشت")
        bot.send_message(m.chat.id, "گزینه را انتخاب کنید:", reply_markup=kb)
        return

    if step == "admin_receipt_action":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        st = get_state(db, uid)
        rid = st["rid"]
        rec = next((r for r in db["receipts"] if r["id"]==rid), None)
        if not rec or rec["status"]!="pending":
            bot.send_message(m.chat.id, "این رسید دیگر در انتظار نیست.")
            return

        if text == "✅ تأیید شارژ (وارد کردن مبلغ)" and rec["kind"]=="topup":
            set_state(db, uid, step="admin_receipt_approve_topup", rid=rid)
            bot.send_message(m.chat.id, "مبلغ شارژ را وارد کنید:", reply_markup=back_kb(db))
            return

        if text == "✅ تأیید خرید و ارسال" and rec["kind"]=="purchase":
            # deliver config to user and mark approved
            uid2 = rec["uid"]
            plan_id = rec.get("plan_id")
            final = rec.get("expected")
            order_id = next_id("ord")
            expiry = (datetime.utcnow() + timedelta(days= db["plans"][str(plan_id)]["days"])).strftime("%Y-%m-%d")
            db["orders"].append({
                "id": order_id, "uid": uid2, "pid": plan_id,
                "price": rec.get("price", final), "final": final,
                "coupon_code": rec.get("coupon_code"),
                "created_at": _now_ts(), "delivered": False, "expiry": expiry
            })
            ok = deliver_config(db, uid2, plan_id, uid2)
            if ok:
                db["orders"][-1]["delivered"] = True
            rec["status"]="approved"; rec["processed_by"]=uid
            save_db(db)
            bot.send_message(m.chat.id, "✅ تأیید شد و کانفیگ ارسال گردید.")
            try:
                bot.send_message(uid2, "✅ خرید شما تأیید شد و کانفیگ ارسال شد.")
            except: pass
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb())
            return

        if text == "⛔ رد":
            rec["status"]="rejected"; rec["processed_by"]=uid; save_db(db)
            try:
                bot.send_message(rec["uid"], "⛔ رسید شما رد شد. در صورت نیاز با پشتیبانی تماس بگیرید.")
            except: pass
            bot.send_message(m.chat.id, "رد شد.")
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb())
            return

    if step == "admin_receipt_approve_topup":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        amount = parse_int(text)
        if amount is None or amount <= 0:
            bot.send_message(m.chat.id, "عدد معتبر وارد کنید.")
            return
        st = get_state(db, uid); rid = st["rid"]
        rec = next((r for r in db["receipts"] if r["id"]==rid), None)
        if not rec or rec["status"]!="pending":
            bot.send_message(m.chat.id, "این رسید دیگر در انتظار نیست.")
            return
        uid2 = rec["uid"]
        db["users"][str(uid2)]["wallet"] += amount
        rec["status"]="approved"; rec["amount"]=amount; rec["processed_by"]=uid
        save_db(db)
        bot.send_message(m.chat.id, "✅ شارژ کیف پول انجام شد.")
        try:
            bot.send_message(uid2, f"🪙 شارژ کیف پول شما تأیید شد: {fmt_money(amount)}\nموجودی فعلی: {fmt_money(db['users'][str(uid2)]['wallet'])}")
        except: pass
        set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return

    # --- Admin: Users
    if step == "admin_users":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        # search by id or @
        target = None
        if text.startswith("@"):
            uname = text[1:].lower()
            for usr in db["users"].values():
                if usr.get("username","").lower() == uname:
                    target = usr; break
        else:
            tid = parse_int(text)
            if tid and str(tid) in db["users"]:
                target = db["users"][str(tid)]
        if not target:
            bot.send_message(m.chat.id, "کاربر یافت نشد.")
            return
        orders = [o for o in db["orders"] if o["uid"]==target["id"]]
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.row("🚫 بن", "✅ آن‌بن")
        kb.row("⬅️ بازگشت")
        bot.send_message(m.chat.id,
                         f"پروفایل کاربر:\n"
                         f"ID: {target['id']}\n"
                         f"Username: @{target.get('username','')}\n"
                         f"موجودی: {fmt_money(target['wallet'])}\n"
                         f"تعداد خرید: {len(orders)}",
                         reply_markup=kb)
        set_state(db, uid, step="admin_user_action", target_id=target["id"])
        return

    if step == "admin_user_action":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        st = get_state(db, uid)
        target = db["users"].get(str(st["target_id"]))
        if not target:
            bot.send_message(m.chat.id, "کاربر یافت نشد."); return
        if text == "🚫 بن":
            target["banned"]=True; save_db(db); bot.send_message(m.chat.id, "کاربر بن شد."); return
        if text == "✅ آن‌بن":
            target["banned"]=False; save_db(db); bot.send_message(m.chat.id, "کاربر آن‌بن شد."); return

    # --- Admin: Admins
    if step == "admin_admins":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        if text == "➕ افزودن ادمین":
            bot.send_message(m.chat.id, "آیدی عددی کاربر را وارد کنید:", reply_markup=back_kb(db))
            set_state(db, uid, step="admin_add_admin"); return
        if text == "➖ حذف ادمین":
            bot.send_message(m.chat.id, "آیدی عددی ادمین را وارد کنید:", reply_markup=back_kb(db))
            set_state(db, uid, step="admin_del_admin"); return

    if step == "admin_add_admin":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_admins"); bot.send_message(m.chat.id, "لغو شد."); return
        tid = parse_int(text)
        if tid is None:
            bot.send_message(m.chat.id, "آیدی نامعتبر.")
            return
        if tid not in db["admins"]:
            db["admins"].append(tid); save_db(db)
        bot.send_message(m.chat.id, "ادمین افزوده شد.")
        set_state(db, uid, step="admin_admins")
        return

    if step == "admin_del_admin":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_admins"); bot.send_message(m.chat.id, "لغو شد."); return
        tid = parse_int(text)
        if tid is None:
            bot.send_message(m.chat.id, "آیدی نامعتبر.")
            return
        if tid in db["admins"]:
            if len(db["admins"])==1:
                bot.send_message(m.chat.id, "نمی‌توان آخرین ادمین را حذف کرد.")
            else:
                db["admins"].remove(tid); save_db(db); bot.send_message(m.chat.id, "ادمین حذف شد.")
        else:
            bot.send_message(m.chat.id, "در لیست ادمین‌ها نبود.")
        set_state(db, uid, step="admin_admins")
        return

    # --- Admin: Buttons & Texts
    if step == "admin_btn_txt":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        if text == "🔘 روشن/خاموش دکمه‌ها":
            be = db["settings"]["buttons_enabled"]
            lines = ["وضعیت فعلی:"]
            for k,v in be.items():
                lines.append(f"{k}: {'روشن' if v else 'خاموش'}")
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("toggle buy", "toggle wallet")
            kb.row("toggle tickets", "toggle account")
            kb.row("toggle receipts")
            kb.row("⬅️ بازگشت")
            bot.send_message(m.chat.id, "\n".join(lines)+"\nیکی از گزینه‌های toggle را انتخاب کنید.", reply_markup=kb)
            set_state(db, uid, step="admin_btn_toggle")
            return
        if text == "📝 ویرایش متون":
            # allow editing known keys
            keys = list(db["settings"]["texts"].keys())
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for k in keys:
                kb.row(k)
            kb.row("⬅️ بازگشت")
            bot.send_message(m.chat.id, "کلید متن موردنظر را انتخاب کنید:", reply_markup=kb)
            set_state(db, uid, step="admin_txt_pick")
            return
        if text == "💳 شماره کارت":
            bot.send_message(m.chat.id, f"شماره کارت فعلی:\n{db['settings']['card_number']}\n\nشماره کارت جدید را بفرستید:", reply_markup=back_kb(db))
            set_state(db, uid, step="admin_card_edit"); return

    if step == "admin_btn_toggle":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_btn_txt"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=buttons_texts_kb()); return
        if text.startswith("toggle "):
            key = text.split(" ",1)[1]
            if key in db["settings"]["buttons_enabled"]:
                db["settings"]["buttons_enabled"][key] = not db["settings"]["buttons_enabled"][key]
                save_db(db)
                bot.send_message(m.chat.id, f"{key} => {'روشن' if db['settings']['buttons_enabled'][key] else 'خاموش'}")
            else:
                bot.send_message(m.chat.id, "کلید نامعتبر.")
            return

    if step == "admin_txt_pick":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_btn_txt"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=buttons_texts_kb()); return
        key = text.strip()
        if key not in db["settings"]["texts"]:
            bot.send_message(m.chat.id, "کلید نامعتبر.")
            return
        set_state(db, uid, step="admin_txt_edit", txt_key=key)
        bot.send_message(m.chat.id, f"متن جدید برای «{key}» را بفرستید:", reply_markup=back_kb(db))
        return

    if step == "admin_txt_edit":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_btn_txt"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=buttons_texts_kb()); return
        key = get_state(db, uid)["txt_key"]
        db["settings"]["texts"][key] = text
        save_db(db)
        bot.send_message(m.chat.id, "به‌روزرسانی شد.", reply_markup=buttons_texts_kb())
        set_state(db, uid, step="admin_btn_txt")
        return

    if step == "admin_card_edit":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_btn_txt"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=buttons_texts_kb()); return
        db["settings"]["card_number"] = text.strip()
        save_db(db)
        bot.send_message(m.chat.id, "شماره کارت به‌روزرسانی شد.", reply_markup=buttons_texts_kb())
        set_state(db, uid, step="admin_btn_txt")
        return

    # --- Admin: Broadcast
    if step == "broadcast_menu":
        if text == "⬅️ بازگشت":
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "بازگشت.", reply_markup=admin_main_kb()); return
        if text == "✍️ نوشتن پیام و ارسال":
            bot.send_message(m.chat.id, "متن پیام همگانی را بفرستید:", reply_markup=back_kb(db))
            set_state(db, uid, step="broadcast_text"); return

    if step == "broadcast_text":
        if text in ("⬅️ بازگشت","❌ انصراف"):
            set_state(db, uid, step="admin_home"); bot.send_message(m.chat.id, "لغو شد.", reply_markup=admin_main_kb()); return
        sent = 0
        for uid2 in list(db["users"].keys()):
            try:
                bot.send_message(int(uid2), text)
                sent += 1
            except: pass
        bot.send_message(m.chat.id, f"ارسال شد به {sent} کاربر.", reply_markup=admin_main_kb())
        set_state(db, uid, step="admin_home")
        return

    # Fallback: show home (first-time or unknown text)
    send_home(uid, m.chat.id)

# -------------------- MEDIA HANDLERS (Receipts + Inventory Photos) -------
@bot.message_handler(content_types=['photo','document'])
def on_media(m: types.Message):
    db = load_db()
    uid = m.from_user.id
    st = get_state(db, uid)
    step = st.get("step")

    # USER: send receipt (purchase or topup)
    if step in ("await_purchase_receipt","await_topup_receipt"):
        rid = next_id("rcp")
        kind = "purchase" if step=="await_purchase_receipt" else "topup"
        data = {
            "id": rid, "uid": uid, "kind": kind, "status":"pending",
            "created_at": _now_ts(), "processed_by": None
        }
        if kind=="purchase":
            data["plan_id"] = st.get("plan_id")
            data["expected"] = st.get("final", st.get("base_price"))
            data["coupon_code"] = (st.get("coupon") or {}).get("code")
            data["price"] = st.get("base_price")
        else:
            data["expected"] = st.get("expected")

        # save media msg id for admins reference
        data["msg_id"] = m.message_id
        db["receipts"].append(data)
        save_db(db)

        bot.send_message(m.chat.id, "📨 رسید شما ثبت شد؛ منتظر تأیید ادمین…")
        # notify admins immediately
        for aid in db["admins"]:
            try:
                bot.send_message(aid, f"🧾 رسید جدید #{rid}\n"
                                      f"نوع: {('خرید کانفیگ' if kind=='purchase' else 'شارژ کیف پول')}\n"
                                      f"کاربر: {uid} @{db['users'].get(str(uid),{}).get('username','')}\n"
                                      f"مبلغ/انتظار: {fmt_money(data.get('expected',0))}\n"
                                      f"(برای بررسی، در پنل «🧾 رسیدها» وارد شوید)")
            except: pass
        clear_state(db, uid)
        send_home(uid, m.chat.id)
        return

    # ADMIN: add inventory photo (after text)
    if step == "inv_add_text":
        pid = st.get("pid")
        tmp = st.get("temp", {"text":None, "photo_id":None})
        # prioritize text via previous step; now if photo comes attach
        photo_id = None
        if m.content_type == "photo":
            photo_id = m.photo[-1].file_id
        elif m.content_type == "document" and m.document.mime_type.startswith("image/"):
            photo_id = m.document.file_id
        tmp["photo_id"] = photo_id
        if tmp.get("text") is None:
            # if text not received yet, ask for text
            bot.send_message(m.chat.id, "حالا متن کانفیگ را هم ارسال کنید:", reply_markup=back_kb(db))
            set_state(db, uid, step="inv_add_text", pid=pid, temp=tmp)
            return
        # finalize
        db["inventory"].setdefault(pid, []).append(tmp)
        save_db(db)
        bot.send_message(m.chat.id, "آیتم به مخزن اضافه شد.")
        set_state(db, uid, step="inv_menu", pid=pid)
        return

# Handler to capture plain text after "inv_add_text"
@bot.message_handler(func=lambda m: get_state(load_db(), m.from_user.id).get("step")=="inv_add_text", content_types=['text'])
def inv_add_text_only(m: types.Message):
    db = load_db()
    uid = m.from_user.id
    st = get_state(db, uid)
    pid = st.get("pid")
    tmp = st.get("temp", {"text":None, "photo_id":None})
    if m.text in ("⬅️ بازگشت","❌ انصراف"):
        set_state(db, uid, step="inv_menu", pid=pid)
        bot.send_message(m.chat.id, "لغو شد.", reply_markup=plans_list_kb(db))
        return
    tmp["text"] = m.text
    # if photo already sent earlier, save; else wait photo or finish
    db["inventory"].setdefault(pid, []).append(tmp)
    save_db(db)
    bot.send_message(m.chat.id, "آیتم (متن/عکس) به مخزن اضافه شد.")
    set_state(db, uid, step="inv_menu", pid=pid)

# -------------------- STARTUP (no slash, but greet on first message) -----
@bot.message_handler(commands=['start'])
def on_start(m: types.Message):
    send_home(m.from_user.id, m.chat.id)

# -------------------- GUNICORN ENTRY -------------------------------------
if __name__ == "__main__":
    set_webhook_once()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
