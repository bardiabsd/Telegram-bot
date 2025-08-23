# -*- coding: utf-8 -*-

import os
import re
import json
import time
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any

from flask import Flask, request, abort
import telebot
from telebot import types

# ========= ENV & WEBHOOK =========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
APP_URL = os.environ.get("APP_URL", "https://live-avivah-bardiabsd-cd8d676a.koyeb.app").strip()
# اگر خواستی توکن را هاردکد کنی (در محیط‌های تست):
# BOT_TOKEN = BOT_TOKEN or "PASTE_YOUR_BOT_TOKEN_HERE"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env not set.")

WEBHOOK_URL = f"{APP_URL}/webhook/{BOT_TOKEN}"

DEFAULT_ADMINS = {1743359080}  # آیدی عددی شما

DB_PATH = "data.db"

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=5)

# ========= DB UTILS =========
def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        purchases INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS admins(
        user_id INTEGER PRIMARY KEY
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        val TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS plans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        days INTEGER,
        traffic_gb INTEGER,
        price INTEGER,
        stock INTEGER DEFAULT 0
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS coupons(
        code TEXT PRIMARY KEY,
        percent INTEGER,          -- 5..90
        max_use INTEGER DEFAULT 0, -- 0 = نامحدود
        used INTEGER DEFAULT 0
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS receipts(
        id TEXT PRIMARY KEY,     -- hash
        user_id INTEGER,
        kind TEXT,               -- "wallet" | "card"
        amount INTEGER,
        status TEXT,             -- "pending" | "approved" | "rejected"
        created_at TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS tickets(
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        topic TEXT,              -- 'buy' | 'config' | 'finance' | 'tech' | 'other'
        body TEXT,
        status TEXT,             -- 'open' | 'closed'
        created_at TEXT
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS sales(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan_id INTEGER,
        price INTEGER,
        coupon_code TEXT,
        final_price INTEGER,
        created_at TEXT
    )""")

    # دکمه‌ها/متن‌های قابل ادیت
    defaults_texts = {
        "welcome": "سلام! خوش اومدی به ⭐️ GoldenVPN\nمن اینجام تا سریع و تمیز بهت سرویس بدم.\nاز منوی زیر انتخاب کن:",
        "menu_buy": "خرید پلن 🛒",
        "menu_wallet": "کیف پول 🌑",
        "menu_support": "تیکت پشتیبانی 🧾",
        "menu_profile": "حساب کاربری 👤",
        "wallet_title": "موجودی شما: {bal:,} تومان 💼",
        "wallet_buttons": "شارژ کیف پول (ارسال رسید) ➕|سوابق خرید 🧾|راهنما ℹ️",
        "card_number_msg": "🧾 روش کارت‌به‌کارت:\nلطفاً مبلغ را به کارت زیر واریز کنید و رسید را ارسال کنید.\n\nشماره کارت:\n{card}\n\nدکمه «انصراف ❌» برای بازگشت.",
        "no_plans": "فعلاً پلنی موجود نیست",
        "choose_plan": "لطفاً پلن موردنظر را انتخاب کنید: 🛍️",
        "plan_info": "✨ {title}\n⏳ مدت: {days} روز\n📶 ترافیک: {traffic} گیگ\n💵 قیمت: {price:,} تومان\n📦 موجودی مخزن: {stock}",
        "purchase_done": "✅ خرید شما با موفقیت انجام شد.",
        "ticket_choose": "موضوع تیکت را انتخاب کنید:",
        "ticket_enter": "لطفاً متن تیکت را با جزئیات بنویسید:",
        "ticket_ok": "✅ تیکت ساخته شد",
        "profile": "👤 آیدی: {id}\n✏️ یوزرنیم: @{username}\n🧾 تعداد خرید: {purchases}\n💰 موجودی: {bal:,} تومان",
        "admin_panel": "پنل ادمین 🛠️:",
    }

    for k, v in defaults_texts.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,val) VALUES(?,?)", (k, v))

    # کارت پیش‌فرض خالی
    cur.execute("INSERT OR IGNORE INTO settings(key,val) VALUES('card_number','—')")

    # ادمین‌های پیش‌فرض
    for a in DEFAULT_ADMINS:
        cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (a,))

    con.commit()
    con.close()

init_db()

# ========= HELPERS =========
def is_admin(user_id: int) -> bool:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    ok = cur.fetchone() is not None
    con.close()
    return ok

def get_setting(key: str, default: str = "") -> str:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT val FROM settings WHERE key=?", (key,))
    r = cur.fetchone()
    con.close()
    return r["val"] if r else default

def set_setting(key: str, val: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO settings(key,val) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET val=excluded.val", (key, val))
    con.commit()
    con.close()

def ensure_user(user: types.User):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(id,username,balance,purchases,created_at) VALUES(?,?,?,?,?)",
                (user.id, user.username or "", 0, 0, datetime.utcnow().isoformat()))
    if user.username and user.username != "":
        cur.execute("UPDATE users SET username=? WHERE id=?", (user.username, user.id))
    con.commit()
    con.close()

def n2int_safe(s: str) -> Optional[int]:
    # تبدیل اعداد فارسی/انگلیسی و حذف جداکننده‌ها
    persian = "۰۱۲۳۴۵۶۷۸۹"
    trans = str.maketrans("".join(persian), "0123456789")
    s = s.translate(trans)
    s = re.sub(r"[^\d]", "", s)
    if not s:
        return None
    try:
        return int(s)
    except:
        return None

def send_or_edit(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except:
        bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

# ========= KEYBOARDS =========
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton(get_setting("menu_buy","خرید پلن 🛒")))
    kb.add(types.KeyboardButton(get_setting("menu_wallet","کیف پول 🌑")))
    kb.add(types.KeyboardButton(get_setting("menu_support","تیکت پشتیبانی 🧾")))
    kb.add(types.KeyboardButton(get_setting("menu_profile","حساب کاربری 👤")))
    return kb

def wallet_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("شارژ کیف پول ➕"))
    kb.add(types.KeyboardButton("سوابق خرید 🧾"))
    kb.add(types.KeyboardButton("راهنما ℹ️"))
    kb.add(types.KeyboardButton("بازگشت ⤴️"))
    return kb

def support_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("مشکل خرید 🛒", "مشکل کانفیگ 🔌")
    kb.row("فنی/اتصال ⚙️", "مالی/پرداخت 🧾")
    kb.row("سایر موارد 💬", "انصراف ❌")
    kb.row("ایجاد تیکت جدید 🆕", "تیکت‌های من 📁")
    kb.row("بازگشت ⤴️")
    return kb

def back_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("بازگشت ⤴️"))
    return kb

def plan_actions():
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("کارت‌به‌کارت 💳", callback_data="pay_card"),
           types.InlineKeyboardButton("اعمال کد تخفیف 🎟️", callback_data="apply_coupon"))
    kb.row(types.InlineKeyboardButton("پرداخت از کیف پول 💼", callback_data="pay_wallet"))
    kb.row(types.InlineKeyboardButton("بازگشت ⤴️", callback_data="back_to_plans"),
           types.InlineKeyboardButton("انصراف ❌", callback_data="cancel_buy"))
    return kb

def admin_panel_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("مدیریت ادمین‌ها 👑", "شماره کارت 💳")
    kb.row("رسیدهای در انتظار 🧾", "شارژ کیف پول کاربر 💰")
    kb.row("اعلان همگانی 📣", "کوپن‌ها 🧧")
    kb.row("مدیریت پلن/مخزن 📦", "آمار فروش 📊")
    kb.row("ویرایش متن/دکمه‌ها ✏️", "بازگشت به منوی کاربر ⤴️")
    return kb

# ========= STATES (memory) =========
# state: dict(user_id -> {"name":..., ...})
STATE: Dict[int, Dict[str, Any]] = {}

def set_state(uid: int, **kwargs):
    STATE[uid] = kwargs

def get_state(uid: int) -> Dict[str, Any]:
    return STATE.get(uid, {})

def clear_state(uid: int):
    if uid in STATE:
        STATE.pop(uid, None)

# ========= WEBHOOK =========
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    return abort(403)

def set_webhook_once():
    try:
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        print("Webhook error:", e)

set_webhook_once()

# ========= HANDLERS =========
@bot.message_handler(commands=["start"])
def on_start(m: types.Message):
    ensure_user(m.from_user)
    text = get_setting("welcome")
    bot.send_message(m.chat.id, text, reply_markup=main_menu())

@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(m: types.Message):
    ensure_user(m.from_user)
    uid = m.from_user.id
    txt = m.text.strip()

    # بازگشت عمومی
    if txt == "بازگشت ⤴️":
        clear_state(uid)
        bot.send_message(uid, "منو:", reply_markup=main_menu())
        return

    st = get_state(uid)

    # ===== مسیرهای در حال انتظار (ورودی متنی آزاد) =====
    if st.get("await") == "wallet_charge_amount":
        amount = n2int_safe(txt)
        if not amount or amount <= 0:
            return bot.reply_to(m, "لطفاً عدد معتبر وارد کنید.")
        # ثبت رسید pending
        rid = f"{hex(int(time.time()*1000))[2:]}_{uid}"
        con = db(); cur = con.cursor()
        cur.execute("INSERT INTO receipts(id,user_id,kind,amount,status,created_at) VALUES(?,?,?,?,?,?)",
                    (rid, uid, "wallet", amount, "pending", datetime.utcnow().isoformat()))
        con.commit(); con.close()
        clear_state(uid)
        bot.send_message(uid, "📥 رسید شما ثبت شد؛ منتظر تأیید ادمین...", reply_markup=wallet_menu())

        # اطلاع به ادمین‌ها
        notify_admins(f"🧾 رسید جدید #{rid}\nاز: @{m.from_user.username or '-'} {uid}\nنوع: wallet\nمبلغ: {amount:,} تومان\nوضعیت: pending",
                      admin_actions_for_receipt(rid))
        return

    if st.get("await") == "broadcast_text" and is_admin(uid):
        send_broadcast(txt)
        clear_state(uid)
        return bot.reply_to(m, "✅ ارسال شد.")

    if st.get("await") == "admin_add_id" and is_admin(uid):
        nid = n2int_safe(txt)
        if not nid:
            return bot.reply_to(m, "آیدی عددی معتبر نیست.")
        con = db(); cur = con.cursor()
        cur.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (nid,))
        con.commit(); con.close()
        clear_state(uid)
        bot.reply_to(m, "🎉 شما به عنوان ادمین اضافه شدی.", reply_markup=admin_panel_kb())
        try:
            bot.send_message(nid, "🎉 شما به عنوان ادمین اضافه شدید.")
        except: pass
        return

    if st.get("await") == "admin_remove_id" and is_admin(uid):
        nid = n2int_safe(txt)
        if not nid:
            return bot.reply_to(m, "آیدی عددی معتبر نیست.")
        con = db(); cur = con.cursor()
        cur.execute("DELETE FROM admins WHERE user_id=?", (nid,))
        con.commit(); con.close()
        clear_state(uid)
        return bot.reply_to(m, "🗑️ ادمین حذف شد.", reply_markup=admin_panel_kb())

    if st.get("await") == "set_card" and is_admin(uid):
        set_setting("card_number", txt)
        clear_state(uid)
        return bot.reply_to(m, "✅ شماره کارت ذخیره شد.", reply_markup=admin_panel_kb())

    if st.get("await") == "charge_user_wallet_userid" and is_admin(uid):
        nid = n2int_safe(txt)
        if not nid:
            return bot.reply_to(m, "آیدی معتبر نیست.")
        set_state(uid, await="charge_user_wallet_amount", target=nid)
        return bot.reply_to(m, "مبلغ شارژ (تومان) را وارد کنید:")

    if st.get("await") == "charge_user_wallet_amount" and is_admin(uid):
        amount = n2int_safe(txt)
        if not amount or amount <= 0:
            return bot.reply_to(m, "عدد معتبر نیست.")
        target = st.get("target")
        con = db(); cur = con.cursor()
        cur.execute("UPDATE users SET balance = COALESCE(balance,0)+? WHERE id=?", (amount, target))
        con.commit(); con.close()
        clear_state(uid)
        try:
            bot.send_message(target, f"💰 کیف پول شما توسط ادمین به میزان {amount:,} تومان شارژ شد.")
        except: pass
        return bot.reply_to(m, "✅ شارژ شد.", reply_markup=admin_panel_kb())

    # افزودن پلن – مرحله‌ای
    if st.get("await") == "add_plan_title" and is_admin(uid):
        set_state(uid, await="add_plan_days", title=txt)
        return bot.reply_to(m, "مدت (روز)؟")
    if st.get("await") == "add_plan_days" and is_admin(uid):
        v = n2int_safe(txt)
        if not v or v <= 0: return bot.reply_to(m, "عدد معتبر نیست.")
        st["days"] = v; set_state(uid, await="add_plan_traffic", **st)
        return bot.reply_to(m, "ترافیک (گیگ)؟")
    if st.get("await") == "add_plan_traffic" and is_admin(uid):
        v = n2int_safe(txt)
        if not v or v <= 0: return bot.reply_to(m, "عدد معتبر نیست.")
        st["traffic"] = v; set_state(uid, await="add_plan_price", **st)
        return bot.reply_to(m, "قیمت (تومان)؟")
    if st.get("await") == "add_plan_price" and is_admin(uid):
        v = n2int_safe(txt)
        if not v or v <= 0: return bot.reply_to(m, "عدد معتبر نیست.")
        st["price"] = v; set_state(uid, await="add_plan_stock", **st)
        return bot.reply_to(m, "موجودی اولیه؟")
    if st.get("await") == "add_plan_stock" and is_admin(uid):
        v = n2int_safe(txt)
        if v is None or v < 0: return bot.reply_to(m, "عدد معتبر نیست.")
        con = db(); cur = con.cursor()
        cur.execute("INSERT INTO plans(title,days,traffic_gb,price,stock) VALUES(?,?,?,?,?)",
                    (st["title"], st["days"], st["traffic"], st["price"], v))
        con.commit(); con.close()
        clear_state(uid)
        return bot.reply_to(m, "✅ پلن اضافه شد.", reply_markup=admin_panel_kb())

    # کوپن درصدی
    if st.get("await") == "create_coupon_code" and is_admin(uid):
        code = txt.upper().strip()
        set_state(uid, await="create_coupon_percent", code=code)
        return bot.reply_to(m, "درصد تخفیف (مثلاً 10):")
    if st.get("await") == "create_coupon_percent" and is_admin(uid):
        p = n2int_safe(txt)
        if not p or p<=0 or p>=95:
            return bot.reply_to(m, "درصد 1..94 وارد کنید.")
        set_state(uid, await="create_coupon_maxuse", code=st["code"], percent=p)
        return bot.reply_to(m, "حداکثر دفعات استفاده؟ (0 = نامحدود)")
    if st.get("await") == "create_coupon_maxuse" and is_admin(uid):
        mu = n2int_safe(txt)
        if mu is None or mu<0: return bot.reply_to(m,"عدد معتبر نیست.")
        con = db(); cur = con.cursor()
        try:
            cur.execute("INSERT INTO coupons(code,percent,max_use,used) VALUES(?,?,?,0)", (st["code"], st["percent"], mu))
            con.commit()
            msg = f"✅ کوپن ساخته شد.\nکد: {st['code']} | درصد: {st['percent']}% | سقف استفاده: {mu or 'نامحدود'}"
        except sqlite3.IntegrityError:
            msg = "⚠️ این کد قبلاً وجود دارد."
        con.close(); clear_state(uid)
        return bot.reply_to(m, msg, reply_markup=admin_panel_kb())

    # ویرایش متن/دکمه‌ها
    if st.get("await") == "edit_text_key" and is_admin(uid):
        key = txt.strip()
        set_state(uid, await="edit_text_val", key=key)
        return bot.reply_to(m, "متن جدید را ارسال کنید:")
    if st.get("await") == "edit_text_val" and is_admin(uid):
        key = st["key"]
        set_setting(key, txt)
        clear_state(uid)
        return bot.reply_to(m, "✅ ذخیره شد.", reply_markup=admin_panel_kb())

    # ===== منوها =====

    # کیف پول
    if txt == get_setting("menu_wallet","کیف پول 🌑") or txt == "کیف پول 🌑":
        con = db(); cur = con.cursor()
        cur.execute("SELECT balance FROM users WHERE id=?", (uid,))
        bal = (cur.fetchone() or {"balance":0})["balance"]
        con.close()
        bot.send_message(uid, get_setting("wallet_title").format(bal=bal), reply_markup=wallet_menu())
        return

    if txt == "شارژ کیف پول ➕":
        set_state(uid, await="wallet_charge_amount")
        return bot.send_message(uid, "مبلغ شارژ (تومان) را وارد کنید:", reply_markup=back_menu())

    if txt == "سوابق خرید 🧾":
        con=db(); cur=con.cursor()
        cur.execute("""SELECT s.id, p.title, s.final_price, s.created_at
                       FROM sales s LEFT JOIN plans p ON p.id=s.plan_id
                       WHERE s.user_id=? ORDER BY s.id DESC LIMIT 10""",(uid,))
        rows = cur.fetchall(); con.close()
        if not rows:
            return bot.send_message(uid, "هنوز خریدی ندارید.", reply_markup=wallet_menu())
        lines = ["🧾 10 خرید آخر شما:"]
        for r in rows:
            when = r["created_at"][:16].replace("T"," ")
            lines.append(f"• {r['title'] or '—'} | {r['final_price']:,} تومان | {when}")
        bot.send_message(uid, "\n".join(lines))
        return

    if txt == "راهنما ℹ️":
        return bot.send_message(uid, "برای شارژ کیف پول مبلغ را وارد و رسید را ارسال کنید. پس از تأیید ادمین، موجودی‌تان افزایش می‌یابد.")

    # پشتیبانی
    if txt == get_setting("menu_support","تیکت پشتیبانی 🧾") or txt == "پشتیبانی":
        bot.send_message(uid, "پشتیبانی:", reply_markup=support_menu()); return

    if txt in ["ایجاد تیکت جدید 🆕","مشکل خرید 🛒","مشکل کانفیگ 🔌","فنی/اتصال ⚙️","مالی/پرداخت 🧾","سایر موارد 💬"]:
        topic_map = {
            "مشکل خرید 🛒":"buy","مشکل کانفیگ 🔌":"config","فنی/اتصال ⚙️":"tech",
            "مالی/پرداخت 🧾":"finance","سایر موارد 💬":"other"
        }
        topic = topic_map.get(txt,"other")
        set_state(uid, await="ticket_body", topic=topic)
        return bot.send_message(uid, get_setting("ticket_enter","لطفاً متن تیکت را با جزئیات بنویسید:"), reply_markup=back_menu())

    if st.get("await") == "ticket_body":
        tid = f"tkt_{int(time.time()*1000)}"
        con=db(); cur=con.cursor()
        cur.execute("INSERT INTO tickets(id,user_id,topic,body,status,created_at) VALUES(?,?,?,?,?,?)",
                    (tid, uid, st["topic"], txt, "open", datetime.utcnow().isoformat()))
        con.commit(); con.close()
        clear_state(uid)
        bot.send_message(uid, get_setting("ticket_ok","✅ تیکت ساخته شد"))
        notify_admins(f"📨 تیکت جدید: #{tid}\nاز: @{m.from_user.username or '-'} {uid}\nدسته: {st['topic']}\nمتن:\n{txt}")
        return

    if txt == "تیکت‌های من 📁":
        con=db(); cur=con.cursor()
        cur.execute("SELECT id,topic,status FROM tickets WHERE user_id=? ORDER BY created_at DESC LIMIT 10",(uid,))
        rows=cur.fetchall(); con.close()
        if not rows:
            return bot.send_message(uid,"هیچ تیکتی ندارید.", reply_markup=support_menu())
        lines=["تیکت‌های شما:"]
        for r in rows:
            lines.append(f"• #{r['id']} | {r['topic']} | وضعیت: {r['status']}")
        return bot.send_message(uid,"\n".join(lines), reply_markup=support_menu())

    if txt == "انصراف ❌":
        clear_state(uid)
        return bot.send_message(uid, "لغو شد.", reply_markup=main_menu())

    # حساب کاربری
    if txt == get_setting("menu_profile","حساب کاربری 👤") or txt == "حساب کاربری 👤":
        con=db(); cur=con.cursor()
        cur.execute("SELECT balance,purchases,username FROM users WHERE id=?",(uid,))
        r=cur.fetchone() or {"balance":0,"purchases":0,"username":m.from_user.username or "-"}
        con.close()
        bot.send_message(uid, get_setting("profile").format(
            id=uid, username=r["username"] or "-", purchases=r["purchases"], bal=r["balance"]
        ))
        return

    # خرید پلن
    if txt == get_setting("menu_buy","خرید پلن 🛒") or txt == "خرید پلن 🛒":
        list_plans(uid)
        return

    # پنل ادمین
    if txt == "پنل ادمین 🛠️" or (is_admin(uid) and txt == "Admin"):
        return show_admin(uid)

    if txt == "بازگشت به منوی کاربر ⤴️":
        return bot.send_message(uid, "منو:", reply_markup=main_menu())

    if is_admin(uid):
        # گزینه‌های پنل
        if txt == "مدیریت ادمین‌ها 👑":
            return show_admins(uid)
        if txt == "افزودن ادمین ➕":
            set_state(uid, await="admin_add_id")
            return bot.send_message(uid, "آیدی عددی ادمین برای افزودن را بفرستید:", reply_markup=back_menu())
        if txt == "حذف ادمین 🗑️":
            set_state(uid, await="admin_remove_id")
            return bot.send_message(uid, "آیدی عددی ادمین برای حذف را بفرستید:", reply_markup=back_menu())

        if txt == "شماره کارت 💳":
            set_state(uid, await="set_card")
            return bot.send_message(uid, "شماره کارت را ارسال کنید:", reply_markup=back_menu())

        if txt == "رسیدهای در انتظار 🧾":
            pending_receipts(uid); return

        if txt == "شارژ کیف پول کاربر 💰":
            set_state(uid, await="charge_user_wallet_userid")
            return bot.send_message(uid, "آیدی عددی کاربر را بفرستید:", reply_markup=back_menu())

        if txt == "اعلان همگانی 📣":
            set_state(uid, await="broadcast_text")
            return bot.send_message(uid, "متن اعلان را ارسال کنید:", reply_markup=back_menu())

        if txt == "کوپن‌ها 🧧":
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("ساخت کوپن جدید ➕", "فهرست کوپن‌ها 📋")
            kb.row("بازگشت ⤴️")
            return bot.send_message(uid, "کوپن‌ها:", reply_markup=kb)

        if txt == "ساخت کوپن جدید ➕":
            set_state(uid, await="create_coupon_code")
            return bot.send_message(uid, "کد کوپن را وارد کنید (حروف/عدد):", reply_markup=back_menu())

        if txt == "فهرست کوپن‌ها 📋":
            con=db(); cur=con.cursor()
            cur.execute("SELECT code,percent,max_use,used FROM coupons ORDER BY code")
            rows=cur.fetchall(); con.close()
            if not rows: return bot.send_message(uid,"کوپنی وجود ندارد.")
            lines=["کوپن‌ها:"]
            for r in rows:
                lim = r["max_use"] or 0
                lines.append(f"• {r['code']} | {r['percent']}% | استفاده: {r['used']}/{lim or '∞'}")
            return bot.send_message(uid,"\n".join(lines))

        if txt == "مدیریت پلن/مخزن 📦":
            kb=types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.row("افزودن پلن ➕","فهرست پلن‌ها 📋")
            kb.row("بازگشت ⤴️")
            return bot.send_message(uid, "پلن/مخزن:", reply_markup=kb)

        if txt == "افزودن پلن ➕":
            set_state(uid, await="add_plan_title")
            return bot.send_message(uid, "عنوان پلن؟", reply_markup=back_menu())

        if txt == "فهرست پلن‌ها 📋":
            con=db(); cur=con.cursor()
            cur.execute("SELECT id,title,days,traffic_gb,price,stock FROM plans ORDER BY id DESC")
            rows=cur.fetchall(); con.close()
            if not rows: return bot.send_message(uid,"پلنی نداریم.")
            lines=["پلن‌ها:"]
            for r in rows:
                lines.append(f"#{r['id']} | {r['title']} | {r['days']}روز | {r['traffic_gb']}GB | {r['price']:,}ت | موجودی:{r['stock']}")
            return bot.send_message(uid,"\n".join(lines))

        if txt == "آمار فروش 📊":
            return show_stats(uid)

        if txt == "ویرایش متن/دکمه‌ها ✏️":
            return edit_texts_intro(uid)

    # اگر هیچکدام نبود:
    bot.send_message(uid, "گزینه نامعتبر است.", reply_markup=main_menu())


# ====== INLINE CALLBACKS (خرید) ======
@bot.callback_query_handler(func=lambda c: c.data.startswith("plan_") or c.data in ["back_to_plans","cancel_buy","pay_wallet","pay_card","apply_coupon"])
def cb_plans(c: types.CallbackQuery):
    uid = c.from_user.id
    if c.data == "back_to_plans":
        list_plans(uid, msg=c.message); return
    if c.data == "cancel_buy":
        send_or_edit(c.message.chat.id, c.message.message_id, "لغو شد.")
        return
    state = get_state(uid)
    if c.data.startswith("plan_"):
        pid = int(c.data.split("_",1)[1])
        con=db(); cur=con.cursor()
        cur.execute("SELECT * FROM plans WHERE id=?", (pid,))
        p=cur.fetchone(); con.close()
        if not p: return bot.answer_callback_query(c.id,"پلن پیدا نشد.")
        set_state(uid, selected_plan=pid, coupon=None)
        text = get_setting("plan_info").format(title=p["title"], days=p["days"], traffic=p["traffic_gb"], price=p["price"], stock=p["stock"])
        send_or_edit(c.message.chat.id, c.message.message_id, text, reply_markup=plan_actions())
        return
    if c.data == "apply_coupon":
        set_state(uid, await="apply_coupon_code", **state)
        bot.answer_callback_query(c.id)
        bot.send_message(uid, "کد تخفیف را ارسال کنید:", reply_markup=back_menu())
        return
    if c.data == "pay_card":
        card = get_setting("card_number","—")
        send_or_edit(c.message.chat.id, c.message.message_id, get_setting("card_number_msg").format(card=card), reply_markup=None)
        return
    if c.data == "pay_wallet":
        purchase_with_wallet(uid, c.message)
        return

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await")=="apply_coupon_code")
def coupon_enter(m: types.Message):
    uid=m.from_user.id
    code=m.text.strip().upper()
    st=get_state(uid)
    con=db(); cur=con.cursor()
    cur.execute("SELECT code,percent,max_use,used FROM coupons WHERE code=?", (code,))
    r=cur.fetchone()
    if not r:
        bot.reply_to(m,"کوپن نامعتبر."); return
    if r["max_use"] and r["used"]>=r["max_use"]:
        bot.reply_to(m,"سقف استفاده از این کوپن پر شده."); return
    st["coupon"]=r["code"]; set_state(uid, **st)
    bot.reply_to(m, f"کوپن ثبت شد: {r['percent']}%")
    # آپدیت ویو پلن
    msg = m.reply_to_message or None
    if not msg:
        # تلاش برای نمایش مجدد جزئیات
        pid = st.get("selected_plan")
        if pid:
            con2=db(); cur2=con2.cursor(); cur2.execute("SELECT * FROM plans WHERE id=?", (pid,)); p=cur2.fetchone(); con2.close()
            if p:
                text = get_setting("plan_info").format(title=p["title"], days=p["days"], traffic=p["traffic_gb"], price=p["price"], stock=p["stock"])
                bot.send_message(uid, text, reply_markup=plan_actions())
    clear_state(uid)

def list_plans(uid: int, msg: Optional[types.Message]=None):
    con=db(); cur=con.cursor()
    cur.execute("SELECT id,title,days,traffic_gb,price,stock FROM plans WHERE stock>0 ORDER BY id DESC")
    rows=cur.fetchall(); con.close()
    if not rows:
        if msg: send_or_edit(msg.chat.id, msg.message_id, get_setting("no_plans"))
        else: bot.send_message(uid, get_setting("no_plans"))
        return
    kb = types.InlineKeyboardMarkup()
    for r in rows:
        kb.add(types.InlineKeyboardButton(f"{r['title']} | {r['days']}روز | {r['price']:,} تومان | 📦{r['stock']}", callback_data=f"plan_{r['id']}"))
    kb.add(types.InlineKeyboardButton("انصراف ❌", callback_data="cancel_buy"))
    text = get_setting("choose_plan")
    if msg: send_or_edit(msg.chat.id, msg.message_id, text, reply_markup=kb)
    else: bot.send_message(uid, text, reply_markup=kb)

def purchase_with_wallet(uid: int, msg: types.Message):
    st = get_state(uid)
    pid = st.get("selected_plan")
    if not pid:
        return bot.answer_callback_query(msg.id,"ابتدا پلن را انتخاب کنید.")
    con=db(); cur=con.cursor()
    cur.execute("SELECT * FROM plans WHERE id=?", (pid,))
    p=cur.fetchone()
    if not p: return bot.answer_callback_query(msg.id,"پلن یافت نشد.")
    cur.execute("SELECT balance,purchases FROM users WHERE id=?", (uid,))
    u=cur.fetchone() or {"balance":0,"purchases":0}
    price = p["price"]
    final = price
    coupon_code = st.get("coupon")
    if coupon_code:
        cur.execute("SELECT percent FROM coupons WHERE code=?", (coupon_code,))
        r=cur.fetchone()
        if r:
            final = max(0, price - (price * r["percent"] // 100))
            # افزایش شمارش استفاده
            cur.execute("UPDATE coupons SET used=used+1 WHERE code=?", (coupon_code,))
    if u["balance"] < final:
        con.close()
        return send_or_edit(msg.chat.id, msg.message_id, "❌ موجودی کیف پول شما کافی نیست.", reply_markup=None)
    # کسر موجودی + ثبت فروش + کاهش موجودی پلن
    cur.execute("UPDATE users SET balance=balance-?, purchases=purchases+1 WHERE id=?", (final, uid))
    cur.execute("UPDATE plans SET stock=stock-1 WHERE id=? AND stock>0", (pid,))
    cur.execute("INSERT INTO sales(user_id,plan_id,price,coupon_code,final_price,created_at) VALUES(?,?,?,?,?,?)",
                (uid, pid, price, coupon_code, final, datetime.utcnow().isoformat()))
    con.commit(); con.close()
    clear_state(uid)
    # ارسال کانفیگ (نمونه: همینجا متن موفقیت)
    send_or_edit(msg.chat.id, msg.message_id, get_setting("purchase_done"))
    # (اینجا می‌تونی ساخت/ارسال کانفیگ واقعی را اضافه کنی)

# ====== ADMIN RECEIPTS ======
def admin_actions_for_receipt(rid: str):
    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("تأیید ✅", callback_data=f"rc_ok_{rid}"),
           types.InlineKeyboardButton("رد ❌", callback_data=f"rc_no_{rid}"))
    kb.row(types.InlineKeyboardButton("مایه‌التفاوت ➕", callback_data=f"rc_diff_{rid}"))
    return kb

def notify_admins(text: str, kb: Optional[types.InlineKeyboardMarkup]=None):
    con=db(); cur=con.cursor()
    cur.execute("SELECT user_id FROM admins")
    admins=[r["user_id"] for r in cur.fetchall()]
    con.close()
    for a in admins:
        try: bot.send_message(a, text, reply_markup=kb)
        except: pass

def pending_receipts(admin_id: int):
    con=db(); cur=con.cursor()
    cur.execute("SELECT id,user_id,kind,amount,status FROM receipts WHERE status='pending' ORDER BY created_at")
    rows=cur.fetchall(); con.close()
    if not rows:
        bot.send_message(admin_id,"هیچ رسید در انتظاری نداریم."); return
    for r in rows:
        bot.send_message(admin_id, f"🧾 #{r['id']} | از {r['user_id']} | نوع: {r['kind']} | مبلغ: {r['amount']:,} | وضعیت: {r['status']}",
                         reply_markup=admin_actions_for_receipt(r["id"]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("rc_"))
def cb_receipt(c: types.CallbackQuery):
    if not is_admin(c.from_user.id):
        return bot.answer_callback_query(c.id,"دسترسی ندارید.")
    action, rid = c.data.split("_",2)[1:]
    con=db(); cur=con.cursor()
    cur.execute("SELECT id,user_id,amount,status FROM receipts WHERE id=?", (rid,))
    r=cur.fetchone()
    if not r:
        return bot.answer_callback_query(c.id, "یافت نشد.")
    uid=r["user_id"]
    if action=="ok":
        if r["status"]!="pending":
            return bot.answer_callback_query(c.id,"این رسید دیگر pending نیست.")
        cur.execute("UPDATE receipts SET status='approved' WHERE id=?", (rid,))
        cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (r["amount"], uid))
        con.commit(); con.close()
        bot.answer_callback_query(c.id,"تأیید شد.")
        try: bot.send_message(uid, f"✅ رسید شما تأیید شد. {r['amount']:,} تومان به کیف پولتان افزوده شد.")
        except: pass
    elif action=="no":
        cur.execute("UPDATE receipts SET status='rejected' WHERE id=?", (rid,))
        con.commit(); con.close()
        bot.answer_callback_query(c.id,"رد شد.")
        try: bot.send_message(uid, "❌ رسید شما رد شد. در صورت ابهام با پشتیبانی در تماس باشید.")
        except: pass
    elif action=="diff":
        con.close()
        set_state(c.from_user.id, await="diff_amount", rid=rid, target=uid)
        bot.answer_callback_query(c.id)
        bot.send_message(c.from_user.id, "مبلغ مایه‌التفاوت (تومان) را وارد کنید:", reply_markup=back_menu())

@bot.message_handler(func=lambda m: get_state(m.from_user.id).get("await")=="diff_amount")
def diff_amount_enter(m: types.Message):
    uid=m.from_user.id
    st=get_state(uid)
    val=n2int_safe(m.text)
    if not val or val<=0:
        return bot.reply_to(m,"عدد معتبر نیست.")
    target=st["target"]; rid=st["rid"]
    con=db(); cur=con.cursor()
    cur.execute("UPDATE users SET balance=balance+? WHERE id=?", (val, target))
    cur.execute("UPDATE receipts SET status='approved' WHERE id=?", (rid,))
    con.commit(); con.close()
    clear_state(uid)
    try: bot.send_message(target, f"✅ مابه‌التفاوت {val:,} تومان به کیف پول شما افزوده شد.")
    except: pass
    bot.reply_to(m,"✅ ثبت شد.", reply_markup=admin_panel_kb())

# ====== ADMIN PANEL ======
def show_admin(uid:int):
    txt = get_setting("admin_panel")
    bot.send_message(uid, txt, reply_markup=admin_panel_kb())

def show_admins(uid:int):
    con=db(); cur=con.cursor()
    cur.execute("SELECT user_id FROM admins ORDER BY user_id")
    rows=cur.fetchall(); con.close()
    if not rows:
        admins_text="(خالی)"
    else:
        admins_text = "👑 ادمین‌ها:\n" + "\n".join([f"• {r['user_id']}" for r in rows])
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("افزودن ادمین ➕","حذف ادمین 🗑️")
    kb.row("بازگشت ⤴️")
    bot.send_message(uid, admins_text, reply_markup=kb)

def send_broadcast(text: str):
    con=db(); cur=con.cursor()
    cur.execute("SELECT id FROM users")
    ids=[r["id"] for r in cur.fetchall()]
    con.close()
    ok=0
    for i in ids:
        try:
            bot.send_message(i, text, reply_markup=main_menu())
            ok+=1
        except: pass

def show_stats(uid:int):
    con=db(); cur=con.cursor()
    cur.execute("SELECT COUNT(*) c, COALESCE(SUM(final_price),0) s FROM sales")
    row=cur.fetchone()
    count=row["c"]; total=row["s"]
    cur.execute("""SELECT u.id,u.username,COUNT(s.id) cnt, COALESCE(SUM(s.final_price),0) sumv
                   FROM sales s JOIN users u ON u.id=s.user_id
                   GROUP BY u.id ORDER BY sumv DESC LIMIT 5""")
    top=cur.fetchall()
    con.close()
    lines = [f"📊 آمار فروش:\n• تعداد فروش/کانفیگ: {count}\n• فروش کل: {total:,} تومان",
             "\n🏆 برترین خریداران:"]
    if not top:
        lines.append("—")
    else:
        for i,r in enumerate(top,1):
            lines.append(f"{i}) {r['id']} @{r['username'] or '-'} | خرید: {r['cnt']} | مبلغ: {r['sumv']:,}ت")
    bot.send_message(uid, "\n".join(lines))

def edit_texts_intro(uid:int):
    lines = [
        "کلید متن/دکمه‌ای که می‌خواهی ویرایش کنی بفرست:",
        "welcome, menu_buy, menu_wallet, menu_support, menu_profile, wallet_title, wallet_buttons,",
        "card_number_msg, no_plans, choose_plan, plan_info, purchase_done,",
        "ticket_choose, ticket_enter, ticket_ok, profile, admin_panel"
    ]
    bot.send_message(uid, "\n".join(lines))
    set_state(uid, await="edit_text_key")

# ========= STARTUP =========
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
