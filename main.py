# -*- coding: utf-8 -*-
import os, json, time, threading, uuid, traceback
from datetime import datetime, timedelta
from flask import Flask, request, abort
import telebot
from telebot import types

# -------------------- ثابت‌ها و پیکربندی --------------------
TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
APP_URL = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"  # بدون اسلش پایانی
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}"
ADMIN_DEFAULT_ID = 1743359080  # ادمین پیش‌فرض طبق گفته شما

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

# -------------------- مسیر فایل‌های داده --------------------
FILES = {
    "users": "users.json",
    "plans": "plans.json",
    "stock": "stock.json",
    "coupons": "coupons.json",
    "receipts": "receipts.json",
    "tickets": "tickets.json",
    "settings": "settings.json",
    "logs": "logs.json"
}

# -------------------- ابزار ذخیره‌سازی --------------------
def load(name, default):
    path = FILES[name]
    if not os.path.exists(path):
        save(name, default)
        return json.loads(json.dumps(default))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))

def save(name, data):
    with open(FILES[name], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_iso():
    return datetime.utcnow().isoformat()

# -------------------- دیتای اولیه --------------------
USERS = load("users", {})  # user_id: {..., "wallet": int, "history": [], "state": {...}}
PLANS = load("plans", {})  # plan_id: {id, name, days, volume, price, desc, enabled}
STOCK = load("stock", {})  # plan_id: [ {id, text, photo_id} ... ]
COUPONS = load("coupons", {})  # code: {percent, plan_id or None, max_use, used, expire_ts}
RECEIPTS = load("receipts", {})  # receipt_id: {...}
TICKETS = load("tickets", {})  # ticket_id: {...}
SETTINGS = load("settings", {
    "admins": [ADMIN_DEFAULT_ID],
    "features": {
        "buy": True, "wallet": True, "tickets": True, "account": True, "broadcast": True,
        "manage_admins": True, "manage_plans": True, "manage_stock": True, "manage_coupons": True,
        "manage_ui": True, "users": True, "receipts": True
    },
    "ui": {
        "menu_title": "به ربات فروش خوش آمدید ✨",
        "btn_buy": "🛒 خرید پلن",
        "btn_wallet": "🪙 کیف پول",
        "btn_tickets": "🎫 تیکت پشتیبانی",
        "btn_account": "👤 حساب کاربری",
        "btn_admin": "🛠 پنل ادمین",
        "btn_back": "🔙 بازگشت",
        "btn_cancel": "❌ انصراف",
        "btn_charge_wallet": "➕ شارژ کیف پول",
        "btn_wallet_history": "🧾 تاریخچه",
        "btn_plans": "📦 لیست پلن‌ها",
        "wallet_title": "کیف پول شما:",
        "cardpay_title": "🔹 کارت‌به‌کارت",
        "card_number_text": "شماره کارت فروشگاه:",
        "ask_receipt": "لطفاً رسید پرداخت را ارسال کنید.",
        "receipt_registered": "✅ رسید شما ثبت شد؛ منتظر تأیید ادمین باشید.",
        "receipt_rejected": "❌ رسید شما رد شد. در صورت ابهام با پشتیبانی تماس بگیرید.",
        "receipt_approved": "✅ رسید شما تأیید شد.",
        "ask_coupon": "کد تخفیف را وارد کنید یا «انصراف» را بزنید.",
        "invalid_coupon": "❌ کد تخفیف نامعتبر است.",
        "coupon_applied": "✅ کد تخفیف اعمال شد.",
        "choose_plan": "لطفاً یکی از پلن‌ها را انتخاب کنید:",
        "plan_empty": "این پلن موجودی ندارد.",
        "pay_with_wallet": "پرداخت با کیف پول",
        "pay_with_card": "کارت‌به‌کارت",
        "remove_coupon": "حذف کد تخفیف",
        "final_amount": "مبلغ نهایی:",
        "wallet_not_enough": "موجودی کیف پول کافی نیست.",
        "need_amount": "مابه‌التفاوت موردنیاز:",
        "btn_pay_diff": "🔌 شارژ همین مقدار",
        "card_number": "6037-9911-1111-1111",  # قابل تغییر از پنل ادمین
        "ticket_intro": "برای ایجاد تیکت یک موضوع انتخاب کنید:",
        "ticket_mine": "🗂 تیکت‌های من",
        "ticket_new": "🆕 تیکت جدید",
        "ticket_subjects": ["مشکل فنی", "سوال درباره پلن", "مالی و پرداخت", "سایر"],
        "ticket_saved": "✅ تیکت ایجاد شد. منتظر پاسخ ادمین باشید.",
        "broadcast_ask": "متن اعلان همگانی را بفرستید:",
        "broadcast_done": "✅ ارسال شد.",
        "admins_title": "مدیریت ادمین‌ها",
        "plans_title": "مدیریت پلن‌ها",
        "stock_title": "مدیریت مخزن/کانفیگ",
        "coupons_title": "مدیریت کد تخفیف",
        "ui_title": "مدیریت دکمه‌ها و متون",
        "users_title": "مدیریت کاربران",
        "receipts_title": "رسیدها",
        "admin_only": "فقط برای ادمین‌هاست.",
        "plan_added": "✅ پلن افزوده شد.",
        "plan_edited": "✅ پلن ویرایش شد.",
        "coupon_added": "✅ کد تخفیف ساخته شد.",
        "coupon_deleted": "🗑 کد حذف شد.",
        "stock_added": "✅ کانفیگ به مخزن افزوده شد.",
        "stock_empty": "❌ مخزن این پلن خالی است.",
        "sent_config": "✅ کانفیگ برای شما ارسال شد.",
        "account_overview": "👤 حساب کاربری شما:",
        "btn_admins": "👑 ادمین‌ها",
        "btn_manage_plans": "📦 پلن‌ها",
        "btn_manage_stock": "📥 مخزن",
        "btn_manage_coupons": "🏷 کد تخفیف",
        "btn_manage_ui": "🧩 دکمه‌ها و متون",
        "btn_manage_users": "👥 کاربران",
        "btn_broadcast": "📢 اعلان همگانی",
        "btn_receipts": "🧾 رسیدها",
        "btn_features": "🔌 روشن/خاموش دکمه‌ها",
        "btn_cardpay": "💳 کارت‌به‌کارت",
        "btn_delete_coupon": "🗑 حذف کد",
    }
})

LOGS = load("logs", [])

# -------------------- هِلپرهای UI --------------------
def kb(rows):
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for r in rows:
        m.add(*[types.KeyboardButton(x) for x in r])
    return m

def ikb(buttons):
    m = types.InlineKeyboardMarkup()
    for row in buttons:
        m.row(*[types.InlineKeyboardButton(text=t, callback_data=d) for (t, d) in row])
    return m

def is_admin(uid):
    return int(uid) in SETTINGS["admins"]

def user(uid):
    uid = str(uid)
    if uid not in USERS:
        USERS[uid] = {
            "id": int(uid),
            "username": None,
            "wallet": 0,
            "history": [],
            "state": {},
            "tickets": []
        }
        save("users", USERS)
    return USERS[uid]

def fmt_toman(x):
    try:
        x = int(x)
    except:
        return str(x)
    return f"{x:,} تومان"

def plan_available(plan_id):
    arr = STOCK.get(str(plan_id), [])
    return len(arr)

def get_final_amount(price, coupon_code, plan_id):
    if not coupon_code:
        return price, 0
    c = COUPONS.get(coupon_code.upper())
    if not c:
        return price, 0
    # اعتبار: تاریخ، ظرفیت، محدودیت پلن
    if c.get("expire_ts") and time.time() > c["expire_ts"]:
        return price, 0
    if c.get("max_use") and c.get("used", 0) >= c["max_use"]:
        return price, 0
    if c.get("plan_id") and str(c["plan_id"]) != str(plan_id):
        return price, 0
    percent = min(100, max(0, int(c.get("percent", 0))))
    off = (price * percent) // 100
    return max(0, price - off), off

# -------------------- منوها --------------------
def main_menu(uid):
    U = user(uid)
    ui = SETTINGS["ui"]
    rows = []
    if SETTINGS["features"].get("buy"): rows.append([ui["btn_buy"]])
    if SETTINGS["features"].get("wallet"): rows.append([ui["btn_wallet"]])
    if SETTINGS["features"].get("tickets"): rows.append([ui["btn_tickets"]])
    if SETTINGS["features"].get("account"): rows.append([ui["btn_account"]])
    if is_admin(uid): rows.append([ui["btn_admin"]])
    return kb(rows)

def wallet_menu():
    ui = SETTINGS["ui"]
    return kb([[ui["btn_charge_wallet"], ui["btn_wallet_history"]],[ui["btn_back"]]])

def admin_menu():
    ui = SETTINGS["ui"]
    rows = [
        [ui["btn_admins"], ui["btn_manage_plans"]],
        [ui["btn_manage_stock"], ui["btn_manage_coupons"]],
        [ui["btn_manage_ui"], ui["btn_features"]],
        [ui["btn_manage_users"], ui["btn_receipts"]],
        [ui["btn_broadcast"], ui["btn_back"]],
    ]
    return kb(rows)

# -------------------- شروع و منوی اصلی --------------------
@bot.message_handler(commands=['start'])
def start_cmd(m):
    U = user(m.from_user.id)
    U["username"] = m.from_user.username
    save("users", USERS)
    bot.send_message(m.chat.id, SETTINGS["ui"]["menu_title"], reply_markup=main_menu(m.from_user.id))

@bot.message_handler(func=lambda m: True, content_types=['text'])
def on_text(m):
    t = m.text.strip()
    uid = m.from_user.id
    U = user(uid)
    ui = SETTINGS["ui"]

    # هندل «بازگشت/انصراف»
    if t == ui["btn_back"] or t == ui["btn_cancel"]:
        U["state"] = {}
        save("users", USERS)
        bot.send_message(m.chat.id, "منوی اصلی:", reply_markup=main_menu(uid))
        return

    # منوی کاربر
    if t == ui["btn_buy"]:
        # لیست پلن‌ها
        if not PLANS:
            bot.send_message(m.chat.id, "هنوز پلنی ثبت نشده.", reply_markup=main_menu(uid))
            return
        msg = [ui["choose_plan"]]
        markup = types.InlineKeyboardMarkup()
        for pid, p in PLANS.items():
            if not p.get("enabled", True): 
                continue
            cnt = plan_available(pid)
            title = f"{p['name']} | {fmt_toman(p['price'])} | موجودی: {cnt}"
            cb = f"plan:{pid}"
            markup.add(types.InlineKeyboardButton(title, callback_data=cb))
        bot.send_message(m.chat.id, "\n".join(msg), reply_markup=markup)
        return

    if t == ui["btn_wallet"]:
        bal = U["wallet"]
        msg = f"{ui['wallet_title']} <b>{fmt_toman(bal)}</b>"
        bot.send_message(m.chat.id, msg, reply_markup=wallet_menu())
        return

    if t == ui["btn_charge_wallet"]:
        # شروع جریان شارژ کیف پول
        st = U["state"] = {"mode": "charge_wallet"}
        save("users", USERS)
        card = SETTINGS["ui"]["card_number"]
        text = f"{ui['cardpay_title']}\n{ui['card_number_text']} <code>{card}</code>\n\n{ui['ask_receipt']}"
        bot.send_message(m.chat.id, text, reply_markup=kb([[ui["btn_cancel"]]]))
        return

    if t == ui["btn_wallet_history"]:
        hist = U.get("history", [])
        if not hist:
            bot.send_message(m.chat.id, "هیچ تراکنشی ثبت نشده.", reply_markup=wallet_menu())
            return
        out = []
        for h in reversed(hist[-20:]):
            out.append(f"- {h['type']} | {fmt_toman(h['amount'])} | {h['time']}")
        bot.send_message(m.chat.id, "\n".join(out), reply_markup=wallet_menu())
        return

    if t == ui["btn_tickets"]:
        bot.send_message(m.chat.id, ui["ticket_intro"], reply_markup=kb([[ui["ticket_new"], ui["ticket_mine"]],[ui["btn_back"]]]))
        return

    if t == ui["ticket_new"]:
        U["state"] = {"mode": "new_ticket_choose_subject"}
        save("users", USERS)
        # موضوع‌ها
        rows = [[s] for s in ui["ticket_subjects"]]
        rows.append([ui["btn_cancel"]])
        bot.send_message(m.chat.id, "موضوع تیکت را انتخاب کنید:", reply_markup=kb(rows))
        return

    if t in ui["ticket_subjects"]:
        st = U.get("state", {})
        if st.get("mode") == "new_ticket_choose_subject":
            st["mode"] = "new_ticket_write"
            st["subject"] = t
            save("users", USERS)
            bot.send_message(m.chat.id, "لطفاً متن تیکت را بنویسید:", reply_markup=kb([[ui["btn_cancel"]]]))
            return

    if t == ui["ticket_mine"]:
        my = [TICKETS[k] for k in TICKETS if TICKETS[k]["user_id"] == uid]
        if not my:
            bot.send_message(m.chat.id, "هیچ تیکتی ندارید.", reply_markup=kb([[ui["btn_back"]]]))
            return
        for tk in sorted(my, key=lambda x: x["time"], reverse=True)[:10]:
            status = tk["status"]
            bot.send_message(m.chat.id, f"🎫 تیکت #{tk['id']}\nموضوع: {tk['subject']}\nوضعیت: {status}\n\n{tk['text']}", reply_markup=kb([[ui["btn_back"]]]))
        return

    if t == ui["btn_account"]:
        bought = len([h for h in U.get("history", []) if h["type"] == "purchase"])
        s = SETTINGS["ui"]["account_overview"]
        uname = ("@" + (U.get("username") or "-")) if U.get("username") else "-"
        txt = f"{s}\n\nآیدی عددی: <code>{uid}</code>\nیوزرنیم: {uname}\nتعداد کانفیگ‌های خریداری‌شده: {bought}\nموجودی کیف پول: <b>{fmt_toman(U['wallet'])}</b>"
        bot.send_message(m.chat.id, txt, reply_markup=main_menu(uid))
        return

    # پنل ادمین
    if t == SETTINGS["ui"]["btn_admin"]:
        if not is_admin(uid):
            bot.send_message(m.chat.id, SETTINGS["ui"]["admin_only"])
            return
        bot.send_message(m.chat.id, "پنل ادمین:", reply_markup=admin_menu())
        return

    # زیربخش‌های پنل
    if is_admin(uid):
        if t == SETTINGS["ui"]["btn_admins"]:
            U["state"] = {"mode": "admins_menu"}
            save("users", USERS)
            admin_list = "\n".join([f"- <code>{a}</code>" for a in SETTINGS["admins"]]) or "-"
            bot.send_message(
                m.chat.id,
                f"{SETTINGS['ui']['admins_title']}\nادمین‌های فعلی:\n{admin_list}\n\nبرای افزودن: آیدی عددی را بفرستید.\nبرای حذف: عبارت rem-<id> را بفرستید.\nمثال: rem-123456789",
                reply_markup=kb([[ui["btn_back"]]])
            )
            return

        if t == SETTINGS["ui"]["btn_manage_plans"]:
            U["state"] = {"mode": "plans_menu"}
            save("users", USERS)
            lines = []
            for pid, p in PLANS.items():
                lines.append(f"#{pid} - {p['name']} | {fmt_toman(p['price'])} | {p['days']} روز | {p['volume']} گیگ | {'✅' if p.get('enabled', True) else '❌'}")
            s = "\n".join(lines) or "هیچ پلنی نیست."
            bot.send_message(
                m.chat.id,
                f"{ui['plans_title']}\n{s}\n\nافزودن/ویرایش پلن (پله‌ای): نام → روز → حجم(GB) → قیمت(تومان) → توضیح → فعال/غیرفعال\nبرای ویرایش پلن: edit-<plan_id>",
                reply_markup=kb([["➕ افزودن پلن", "✏️ ویرایش پلن"], [ui["btn_back"]]])
            )
            return

        if t == "➕ افزودن پلن":
            U["state"] = {"mode": "add_plan", "step": "name", "data": {}}
            save("users", USERS)
            bot.send_message(m.chat.id, "نام پلن را وارد کنید:", reply_markup=kb([[ui["btn_cancel"]]]))
            return

        if t == "✏️ ویرایش پلن":
            U["state"] = {"mode": "edit_plan_ask_id"}
            save("users", USERS)
            bot.send_message(m.chat.id, "شناسه پلن (id) را بفرستید:", reply_markup=kb([[ui["btn_cancel"]]]))
            return

        if t == SETTINGS["ui"]["btn_manage_stock"]:
            U["state"] = {"mode": "stock_menu"}
            save("users", USERS)
            bot.send_message(m.chat.id, f"{ui['stock_title']}\n1) برای افزودن کانفیگ: send-<plan_id>\n2) برای دیدن موجودی: show-<plan_id>", reply_markup=kb([[ui["btn_back"]]]))
            return

        if t == SETTINGS["ui"]["btn_manage_coupons"]:
            U["state"] = {"mode": "coupons_menu"}
            save("users", USERS)
            lines = []
            for code, c in COUPONS.items():
                exp = datetime.utcfromtimestamp(c["expire_ts"]).strftime("%Y-%m-%d") if c.get("expire_ts") else "-"
                lim = c.get("max_use") or "-"
                used = c.get("used", 0)
                scope = c.get("plan_id") or "همه پلن‌ها"
                lines.append(f"{code} | {c['percent']}% | {scope} | استفاده:{used}/{lim} | تا: {exp}")
            s = "\n".join(lines) or "کدی وجود ندارد."
            bot.send_message(m.chat.id, f"{ui['coupons_title']}\n{s}\n\nبرای ساخت مرحله‌ای: percent → plan(اختیاری:all یا id) → expire(YYYY-MM-DD یا skip) → max_use(عدد یا skip) → code", reply_markup=kb([["➕ ساخت کد تخفیف", ui["btn_delete_coupon"]],[ui["btn_back"]]]))
            return

        if t == "➕ ساخت کد تخفیف":
            U["state"] = {"mode": "new_coupon", "step": "percent", "data": {}}
            save("users", USERS)
            bot.send_message(m.chat.id, "درصد تخفیف؟ (0..100)", reply_markup=kb([[ui["btn_cancel"]]]))
            return

        if t == ui["btn_delete_coupon"]:
            U["state"] = {"mode": "del_coupon"}
            save("users", USERS)
            bot.send_message(m.chat.id, "کد تخفیف را برای حذف بفرستید:", reply_markup=kb([[ui["btn_cancel"]]]))
            return

        if t == SETTINGS["ui"]["btn_manage_ui"]:
            U["state"] = {"mode": "ui_menu"}
            save("users", USERS)
            bot.send_message(m.chat.id, f"{ui['ui_title']}\nبرای ویرایش یک کلید/متن: بنویسید key=<نام> سپس مقدار را بفرستید.\nمثال: key=card_number", reply_markup=kb([["key=card_number", "key=menu_title"],["key=btn_buy","key=btn_wallet"],[ui["btn_back"]]]))
            return

        if t == SETTINGS["ui"]["btn_features"]:
            U["state"] = {"mode": "features_menu"}
            save("users", USERS)
            feats = SETTINGS["features"]
            lines = ["روشن/خاموش دکمه‌ها:"]
            for k,v in feats.items():
                lines.append(f"- {k} : {'✅' if v else '❌'}")
            bot.send_message(m.chat.id, "\n".join(lines)+"\n\nبرای تغییر: feature=<نام>", reply_markup=kb([[ui["btn_back"]]]))
            return

        if t == SETTINGS["ui"]["btn_manage_users"]:
            U["state"] = {"mode": "users_menu"}
            save("users", USERS)
            bot.send_message(m.chat.id, f"{ui['users_title']}\nبرای جستجو یوزر: user=<id یا @username>", reply_markup=kb([[ui["btn_back"]]]))
            return

        if t == SETTINGS["ui"]["btn_broadcast"]:
            U["state"] = {"mode": "broadcast_wait"}
            save("users", USERS)
            bot.send_message(m.chat.id, ui["broadcast_ask"], reply_markup=kb([[ui["btn_cancel"]]]))
            return

        if t == SETTINGS["ui"]["btn_receipts"]:
            U["state"] = {"mode": "receipts_menu"}
            save("users", USERS)
            # فقط رسیدهای در انتظار و رسیدگی‌نشده
            pending = [r for r in RECEIPTS.values() if r["status"]=="pending" and not r.get("handled")]
            if not pending:
                bot.send_message(m.chat.id, "رسید در انتظار نداریم.", reply_markup=kb([[ui["btn_back"]]]))
            else:
                for r in sorted(pending, key=lambda x: x["time"]):
                    cap = f"🧾 رسید #{r['id']}\nاز: <code>{r['user_id']}</code> @{USERS.get(str(r['user_id']),{}).get('username','-')}\nنوع: {r['kind']}\nمبلغ/انتظار: {fmt_toman(r.get('amount','-'))} / {fmt_toman(r.get('expected','-'))}\nوضعیت: {r['status']}"
                    markup = ikb([[("✅ تأیید", f"rcp_ok:{r['id']}"), ("❌ رد", f"rcp_no:{r['id']}")]])
                    if r.get("photo_id"):
                        bot.send_photo(m.chat.id, r["photo_id"], cap, reply_markup=markup)
                    else:
                        bot.send_message(m.chat.id, cap, reply_markup=markup)
            return

    # -------------- حالت‌ها (State Machine) --------------
    st = U.get("state", {})
    mode = st.get("mode")

    # ساخت تیکت - متن
    if mode == "new_ticket_write":
        text = t
        tk_id = str(uuid.uuid4())[:8]
        TICKETS[tk_id] = {
            "id": tk_id, "user_id": uid, "subject": st.get("subject","-"),
            "text": text, "status": "open", "time": now_iso()
        }
        save("tickets", TICKETS)
        U["tickets"].append(tk_id)
        U["state"] = {}
        save("users", USERS)
        bot.send_message(m.chat.id, SETTINGS["ui"]["ticket_saved"], reply_markup=main_menu(uid))
        # ارسال لحظه‌ای برای همه ادمین‌ها
        for admin_id in SETTINGS["admins"]:
            try:
                markup = ikb([[("✉️ پاسخ", f"t_reply:{tk_id}:{uid}")]])
                bot.send_message(admin_id, f"🎫 تیکت جدید #{tk_id}\nاز: <code>{uid}</code> @{U.get('username','-')}\nموضوع: {TICKETS[tk_id]['subject']}\n\n{text}", reply_markup=markup)
            except: pass
        return

    # مدیریت ادمین‌ها: افزودن/حذف
    if mode == "admins_menu":
        if t.startswith("rem-"):
            try:
                rem_id = int(t[4:].strip())
                if rem_id in SETTINGS["admins"]:
                    SETTINGS["admins"] = [x for x in SETTINGS["admins"] if x != rem_id]
                    save("settings", SETTINGS)
                    bot.send_message(m.chat.id, "ادمین حذف شد.", reply_markup=admin_menu())
                else:
                    bot.send_message(m.chat.id, "این آیدی ادمین نیست.", reply_markup=admin_menu())
            except:
                bot.send_message(m.chat.id, "فرمت نامعتبر.", reply_markup=admin_menu())
        else:
            try:
                add_id = int(t)
                if add_id not in SETTINGS["admins"]:
                    SETTINGS["admins"].append(add_id)
                    save("settings", SETTINGS)
                    bot.send_message(m.chat.id, "ادمین افزوده شد.", reply_markup=admin_menu())
                else:
                    bot.send_message(m.chat.id, "قبلاً ادمین بوده.", reply_markup=admin_menu())
            except:
                bot.send_message(m.chat.id, "آیدی عددی نامعتبر.", reply_markup=admin_menu())
        return

    # افزودن پلن (پله‌ای)
    if mode == "add_plan":
        step = st.get("step")
        data = st.get("data", {})
        if step == "name":
            data["name"] = t
            st["step"] = "days"
            st["data"] = data
            save("users", USERS)
            bot.send_message(m.chat.id, "مدت پلن چند روز است؟ (عدد)", reply_markup=kb([[ui["btn_cancel"]]]))
            return
        if step == "days":
            try:
                data["days"] = int(t)
            except:
                bot.send_message(m.chat.id, "عدد معتبر وارد کنید.", reply_markup=kb([[ui["btn_cancel"]]]))
                return
            st["step"] = "volume"
            st["data"] = data
            save("users", USERS)
            bot.send_message(m.chat.id, "حجم پلن چند گیگ است؟ (عدد)", reply_markup=kb([[ui["btn_cancel"]]]))
            return
        if step == "volume":
            try:
                data["volume"] = int(t)
            except:
                bot.send_message(m.chat.id, "عدد معتبر وارد کنید.", reply_markup=kb([[ui["btn_cancel"]]]))
                return
            st["step"] = "price"
            st["data"] = data
            save("users", USERS)
            bot.send_message(m.chat.id, "قیمت پلن (تومان)؟ (عدد)", reply_markup=kb([[ui["btn_cancel"]]]))
            return
        if step == "price":
            try:
                data["price"] = int(t)
            except:
                bot.send_message(m.chat.id, "عدد معتبر وارد کنید.", reply_markup=kb([[ui["btn_cancel"]]]))
                return
            st["step"] = "desc"
            st["data"] = data
            save("users", USERS)
            bot.send_message(m.chat.id, "توضیح کوتاه پلن:", reply_markup=kb([[ui["btn_cancel"]]]))
            return
        if step == "desc":
            data["desc"] = t
            st["step"] = "enabled"
            st["data"] = data
            save("users", USERS)
            bot.send_message(m.chat.id, "پلن فعال باشد؟ (بله/خیر)", reply_markup=kb([["بله","خیر"],[ui["btn_cancel"]]]))
            return
        if step == "enabled":
            enabled = (t.strip() == "بله")
            data["enabled"] = enabled
            pid = str(uuid.uuid4())[:8]
            data["id"] = pid
            PLANS[pid] = data
            save("plans", PLANS)
            U["state"] = {}
            save("users", USERS)
            bot.send_message(m.chat.id, SETTINGS["ui"]["plan_added"], reply_markup=admin_menu())
            return

    # ویرایش پلن
    if mode == "edit_plan_ask_id":
        pid = t.strip()
        if pid not in PLANS:
            bot.send_message(m.chat.id, "شناسه یافت نشد.", reply_markup=kb([[ui["btn_cancel"]]]))
            return
        U["state"] = {"mode": "edit_plan_step", "pid": pid, "step": "name"}
        save("users", USERS)
        bot.send_message(m.chat.id, f"نام جدید ({PLANS[pid]['name']}):", reply_markup=kb([[ui["btn_cancel"]]]))
        return

    if mode == "edit_plan_step":
        pid = st["pid"]; step = st["step"]
        p = PLANS[pid]
        if step == "name":
            p["name"] = t
            st["step"] = "days"; save("users", USERS)
            bot.send_message(m.chat.id, f"روز جدید ({p['days']}):")
            return
        if step == "days":
            try: p["days"] = int(t)
            except: bot.send_message(m.chat.id,"عدد!"); return
            st["step"] = "volume"; save("users", USERS)
            bot.send_message(m.chat.id, f"حجم جدید ({p['volume']}):")
            return
        if step == "volume":
            try: p["volume"] = int(t)
            except: bot.send_message(m.chat.id,"عدد!"); return
            st["step"] = "price"; save("users", USERS)
            bot.send_message(m.chat.id, f"قیمت جدید ({p['price']}):")
            return
        if step == "price":
            try: p["price"] = int(t)
            except: bot.send_message(m.chat.id,"عدد!"); return
            st["step"] = "desc"; save("users", USERS)
            bot.send_message(m.chat.id, f"توضیح جدید ({p['desc']}):")
            return
        if step == "desc":
            p["desc"] = t
            st["step"] = "enabled"; save("users", USERS)
            bot.send_message(m.chat.id, f"فعال؟ (بله/خیر) [{ 'بله' if p.get('enabled',True) else 'خیر'}]:")
            return
        if step == "enabled":
            p["enabled"] = (t.strip()=="بله")
            save("plans", PLANS)
            U["state"] = {}
            save("users", USERS)
            bot.send_message(m.chat.id, ui["plan_edited"], reply_markup=admin_menu())
            return

    # ساخت کد تخفیف مرحله‌ای
    if mode == "new_coupon":
        step = st["step"]; data = st["data"]
        if step == "percent":
            try:
                pr = int(t)
                if pr<0 or pr>100: raise ValueError()
                data["percent"] = pr
            except:
                bot.send_message(m.chat.id, "درصد نامعتبر.", reply_markup=kb([[ui["btn_cancel"]]])); return
            st["step"]="plan"; st["data"]=data; save("users", USERS)
            bot.send_message(m.chat.id, "محدود به پلن؟ (all یا plan_id)", reply_markup=kb([["all"],[ui["btn_cancel"]]]))
            return
        if step == "plan":
            if t=="all": data["plan_id"]=None
            else:
                if t not in PLANS: bot.send_message(m.chat.id,"شناسه پلن نامعتبر.", reply_markup=kb([[ui["btn_cancel"]]])); return
                data["plan_id"]=t
            st["step"]="expire"; st["data"]=data; save("users", USERS)
            bot.send_message(m.chat.id, "تاریخ انقضا (YYYY-MM-DD) یا skip:", reply_markup=kb([["skip"],[ui["btn_cancel"]]]))
            return
        if step == "expire":
            if t=="skip": data["expire_ts"]=None
            else:
                try:
                    dt = datetime.strptime(t, "%Y-%m-%d")
                    data["expire_ts"]=int(datetime(dt.year, dt.month, dt.day).timestamp())
                except:
                    bot.send_message(m.chat.id,"تاریخ نامعتبر.", reply_markup=kb([[ui["btn_cancel"]]])); return
            st["step"]="max_use"; st["data"]=data; save("users", USERS)
            bot.send_message(m.chat.id, "سقف استفاده (عدد) یا skip:", reply_markup=kb([["skip"],[ui["btn_cancel"]]]))
            return
        if step == "max_use":
            if t=="skip": data["max_use"]=None
            else:
                try: data["max_use"]=int(t)
                except: bot.send_message(m.chat.id,"عدد نامعتبر.", reply_markup=kb([[ui["btn_cancel"]]])); return
            st["step"]="code"; st["data"]=data; save("users", USERS)
            bot.send_message(m.chat.id, "کد را وارد کنید (حروف/اعداد):", reply_markup=kb([[ui["btn_cancel"]]]))
            return
        if step == "code":
            code = t.strip().upper()
            if code in COUPONS: bot.send_message(m.chat.id,"این کد موجود است.", reply_markup=kb([[ui["btn_cancel"]]])); return
            data["used"]=0
            COUPONS[code]=data
            save("coupons", COUPONS)
            U["state"]={}
            save("users", USERS)
            bot.send_message(m.chat.id, ui["coupon_added"], reply_markup=admin_menu())
            return

    if mode == "del_coupon":
        code = t.strip().upper()
        if code in COUPONS:
            del COUPONS[code]
            save("coupons", COUPONS)
            bot.send_message(m.chat.id, ui["coupon_deleted"], reply_markup=admin_menu())
        else:
            bot.send_message(m.chat.id, "کدی با این نام نیست.", reply_markup=admin_menu())
        U["state"]={}
        save("users", USERS)
        return

    if mode == "ui_menu":
        if t.startswith("key="):
            key = t.split("=",1)[1].strip()
            if key not in SETTINGS["ui"]:
                bot.send_message(m.chat.id, "کلید نامعتبر.", reply_markup=kb([[ui["btn_back"]]])); return
            U["state"]={"mode":"ui_edit","key":key}
            save("users", USERS)
            bot.send_message(m.chat.id, f"مقدار جدید برای <b>{key}</b> را بفرستید:", reply_markup=kb([[ui["btn_cancel"]]]))
            return

    if mode == "ui_edit":
        key = st["key"]
        SETTINGS["ui"][key]=t
        save("settings", SETTINGS)
        U["state"]={}
        save("users", USERS)
        bot.send_message(m.chat.id, "ذخیره شد.", reply_markup=admin_menu())
        return

    if mode == "features_menu":
        if t.startswith("feature="):
            k = t.split("=",1)[1].strip()
            if k not in SETTINGS["features"]:
                bot.send_message(m.chat.id,"ویژگی نامعتبر.", reply_markup=kb([[ui["btn_back"]]])); return
            SETTINGS["features"][k] = not SETTINGS["features"][k]
            save("settings", SETTINGS)
            bot.send_message(m.chat.id, f"{k} => {'✅' if SETTINGS['features'][k] else '❌'}", reply_markup=admin_menu())
            return

    if mode == "users_menu":
        if t.startswith("user="):
            q = t.split("=",1)[1].strip()
            target = None
            if q.startswith("@"):
                for u in USERS.values():
                    if u.get("username") and ("@"+u["username"])==q:
                        target=u; break
            else:
                if q in USERS: target=USERS[q]
            if not target:
                bot.send_message(m.chat.id, "کاربر یافت نشد.", reply_markup=admin_menu()); return
            bought = len([h for h in target.get("history",[]) if h["type"]=="purchase"])
            txt = f"👤 آیدی: <code>{target['id']}</code>\nیوزرنیم: @{target.get('username','-')}\nموجودی کیف پول: {fmt_toman(target['wallet'])}\nتعداد خرید: {bought}"
            bot.send_message(m.chat.id, txt, reply_markup=admin_menu())
            return

    if mode == "broadcast_wait":
        text = t
        cnt = 0
        for uid2 in list(USERS.keys()):
            try:
                bot.send_message(int(uid2), text)
                cnt += 1
            except: pass
        U["state"]={}
        save("users", USERS)
        bot.send_message(m.chat.id, f"{ui['broadcast_done']} ({cnt} ارسال)", reply_markup=admin_menu())
        return

    # حالت عمومی: اگر هیچکی نبود
    bot.send_message(m.chat.id, "گزینه نامعتبر است.", reply_markup=main_menu(uid))


# -------------------- خرید پلن: کال‌بک‌ها --------------------
@bot.callback_query_handler(func=lambda c: c.data.startswith("plan:"))
def cb_plan(c):
    pid = c.data.split(":")[1]
    if pid not in PLANS:
        bot.answer_callback_query(c.id, "پلن یافت نشد."); return
    p = PLANS[pid]
    cnt = plan_available(pid)
    ui = SETTINGS["ui"]
    text = f"📦 <b>{p['name']}</b>\n⏳ {p['days']} روز | 💾 {p['volume']} گیگ\n💰 {fmt_toman(p['price'])}\n\n{p['desc']}\n\nموجودی مخزن: {cnt}"
    buttons = [
        [(ui["pay_with_wallet"], f"payw:{pid}"), (ui["pay_with_card"], f"payc:{pid}")],
        [(ui["remove_coupon"], f"rmcp:{pid}")]
    ]
    bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=ikb(buttons))

    # ذخیره‌ی انتخاب پلن در state برای کد تخفیف
    U = user(c.from_user.id)
    U["state"]["buy"] = {"plan_id": pid, "coupon": None}
    save("users", USERS)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rmcp:"))
def cb_rm_coupon(c):
    pid = c.data.split(":")[1]
    U = user(c.from_user.id)
    st = U.get("state",{}).get("buy",{})
    st["coupon"] = None
    U["state"]["buy"] = st
    save("users", USERS)
    bot.answer_callback_query(c.id, "کد تخفیف حذف شد.")
    # دوباره بازنشر جزئیات پلن
    p = PLANS.get(pid)
    cnt = plan_available(pid)
    ui = SETTINGS["ui"]
    text = f"📦 <b>{p['name']}</b>\n⏳ {p['days']} روز | 💾 {p['volume']} گیگ\n💰 {fmt_toman(p['price'])}\n\n{p['desc']}\n\nموجودی مخزن: {cnt}"
    buttons = [
        [(ui["pay_with_wallet"], f"payw:{pid}"), (ui["pay_with_card"], f"payc:{pid}")],
        [("اعمال کد تخفیف", f"addc:{pid}")]
    ]
    bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=ikb(buttons))

@bot.callback_query_handler(func=lambda c: c.data.startswith("addc:"))
def cb_add_coupon(c):
    pid = c.data.split(":")[1]
    U = user(c.from_user.id)
    U["state"]["await_coupon"] = {"plan_id": pid}
    save("users", USERS)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, SETTINGS["ui"]["ask_coupon"], reply_markup=kb([[SETTINGS["ui"]["btn_cancel"]]]))

@bot.message_handler(func=lambda m: user(m.from_user.id).get("state",{}).get("await_coupon"))
def on_coupon(m):
    uid = m.from_user.id
    U = user(uid)
    st = U["state"]["await_coupon"]
    pid = st["plan_id"]
    code = m.text.strip().upper()
    if code == SETTINGS["ui"]["btn_cancel"]:
        U["state"].pop("await_coupon", None)
        save("users", USERS)
        bot.send_message(m.chat.id, "لغو شد.")
        return
    final, off = get_final_amount(PLANS[pid]["price"], code, pid)
    if off == 0 and code != "FREE100000000":  # شوخی :)
        bot.send_message(m.chat.id, SETTINGS["ui"]["invalid_coupon"])
        return
    # ذخیره
    buy = U["state"].get("buy", {"plan_id":pid})
    buy["coupon"] = code
    U["state"]["buy"]=buy
    U["state"].pop("await_coupon", None)
    save("users", USERS)
    bot.send_message(m.chat.id, SETTINGS["ui"]["coupon_applied"])

@bot.callback_query_handler(func=lambda c: c.data.startswith("payw:"))
def cb_pay_wallet(c):
    pid = c.data.split(":")[1]
    U = user(c.from_user.id)
    ui = SETTINGS["ui"]
    if plan_available(pid) <= 0:
        bot.answer_callback_query(c.id, ui["plan_empty"]); return
    buy = U.get("state",{}).get("buy", {"plan_id": pid, "coupon": None})
    buy["plan_id"] = pid
    price = PLANS[pid]["price"]
    final, off = get_final_amount(price, buy.get("coupon"), pid)
    # نمایش مبلغ
    msg = f"{ui['final_amount']} <b>{fmt_toman(final)}</b>"
    if U["wallet"] >= final:
        # کم کن و ارسال کن
        U["wallet"] -= final
        U["history"].append({"type":"purchase","amount":final,"time":now_iso(),"plan_id":pid})
        save("users", USERS)
        # ارسال کانفیگ
        send_config_to_user(c.from_user.id, pid)
        # شمارش کد
        maybe_mark_coupon(buy.get("coupon"))
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, ui["sent_config"], reply_markup=main_menu(c.from_user.id))
    else:
        need = final - U["wallet"]
        btn = ikb([[(ui["btn_pay_diff"], f"paydiff:{pid}:{final}")]])
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, f"{msg}\n{ui['wallet_not_enough']}\n{ui['need_amount']} <b>{fmt_toman(need)}</b>", reply_markup=btn)

@bot.callback_query_handler(func=lambda c: c.data.startswith("paydiff:"))
def cb_pay_diff(c):
    _, pid, final = c.data.split(":")
    U = user(c.from_user.id)
    ui = SETTINGS["ui"]
    need = int(final) - U["wallet"]
    if need <= 0:
        bot.answer_callback_query(c.id, "الان کافی شد! دوباره «پرداخت با کیف پول» را بزنید.")
        return
    # جریان شارژ مخصوص خرید
    U["state"]["await_receipt"] = {"kind":"purchase","plan_id":pid,"expected":int(final),"coupon": U.get("state",{}).get("buy",{}).get("coupon")}
    save("users", USERS)
    text = f"{ui['cardpay_title']}\n{ui['card_number_text']} <code>{ui['card_number']}</code>\n\nبرای تکمیل خرید {fmt_toman(need)} پرداخت کنید و رسید را بفرستید."
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, text, reply_markup=kb([[ui["btn_cancel"]]]))

@bot.callback_query_handler(func=lambda c: c.data.startswith("payc:"))
def cb_pay_card(c):
    pid = c.data.split(":")[1]
    U = user(c.from_user.id)
    ui = SETTINGS["ui"]
    if plan_available(pid) <= 0:
        bot.answer_callback_query(c.id, ui["plan_empty"]); return
    price = PLANS[pid]["price"]
    coupon = U.get("state",{}).get("buy",{}).get("coupon")
    final, off = get_final_amount(price, coupon, pid)
    U["state"]["await_receipt"] = {"kind":"purchase","plan_id":pid,"expected":final,"coupon":coupon}
    save("users", USERS)
    text = f"{ui['cardpay_title']}\n{ui['card_number_text']} <code>{ui['card_number']}</code>\n\n{ui['ask_receipt']}\nمبلغ: <b>{fmt_toman(final)}</b>"
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, text, reply_markup=kb([[ui["btn_cancel"]]]))

def maybe_mark_coupon(code):
    if not code: return
    c = COUPONS.get(code.upper())
    if not c: return
    c["used"] = int(c.get("used",0)) + 1
    save("coupons", COUPONS)

def send_config_to_user(uid, plan_id):
    pid = str(plan_id)
    arr = STOCK.get(pid, [])
    if not arr:
        bot.send_message(uid, SETTINGS["ui"]["stock_empty"]); return
    item = arr.pop(0)
    save("stock", STOCK)
    # تاریخ انقضا برای نوتیف
    exp = (datetime.utcnow() + timedelta(days=PLANS[pid]["days"])).strftime("%Y-%m-%d")
    # ارسال متن + تصویر
    if item.get("photo_id"):
        bot.send_photo(uid, item["photo_id"], f"{item.get('text','')}\n\n⏳ تاریخ انقضا: {exp}")
    else:
        bot.send_message(uid, f"{item.get('text','')}\n\n⏳ تاریخ انقضا: {exp}")

# -------------------- دریافت رسید (عکس/متن) --------------------
@bot.message_handler(content_types=['photo','document'])
def on_media(m):
    uid = m.from_user.id
    U = user(uid)
    st = U.get("state",{})
    if "await_receipt" in st or st.get("mode")=="charge_wallet":
        # استخراج photo_id
        photo_id = None
        if m.photo:
            photo_id = m.photo[-1].file_id
        elif m.document and str(m.document.mime_type or "").startswith("image/"):
            photo_id = m.document.file_id
        # ساخت رسید
        rid = str(uuid.uuid4())[:8]
        kind = "wallet" if st.get("mode")=="charge_wallet" else st["await_receipt"]["kind"]
        entry = {
            "id": rid, "user_id": uid, "username": user(uid).get("username"),
            "kind": kind, "status": "pending", "photo_id": photo_id,
            "time": now_iso(), "handled": False
        }
        # اگر خرید پلن
        if kind == "purchase":
            entry.update(st["await_receipt"])
        # اگر شارژ کیف پول، مقدار را از کپشن/توضیح نمی‌گیریم؛ ادمین وارد می‌کند
        RECEIPTS[rid] = entry
        save("receipts", RECEIPTS)
        U["state"] = {}
        save("users", USERS)
        bot.send_message(m.chat.id, SETTINGS["ui"]["receipt_registered"], reply_markup=main_menu(uid))
        # نوتیف به ادمین‌ها با دکمه تایید/رد
        notify_receipt_admins(entry, media=True)
    else:
        # رسانه‌ای است ولی در حالت انتظار رسید نیست
        pass

@bot.message_handler(content_types=['text'])
def on_maybe_receipt_text(m):
    # این هندلر بعد از on_text ثبت می‌شود و فقط وقتی state رسید است کار می‌کند
    uid = m.from_user.id
    U = user(uid)
    st = U.get("state",{})
    if "await_receipt" in st or st.get("mode")=="charge_wallet":
        rid = str(uuid.uuid4())[:8]
        kind = "wallet" if st.get("mode")=="charge_wallet" else st["await_receipt"]["kind"]
        entry = {
            "id": rid, "user_id": uid, "username": user(uid).get("username"),
            "kind": kind, "status": "pending", "photo_id": None,
            "note": m.text, "time": now_iso(), "handled": False
        }
        if kind == "purchase":
            entry.update(st["await_receipt"])
        RECEIPTS[rid] = entry
        save("receipts", RECEIPTS)
        U["state"] = {}
        save("users", USERS)
        bot.send_message(m.chat.id, SETTINGS["ui"]["receipt_registered"], reply_markup=main_menu(uid))
        notify_receipt_admins(entry, media=False)

def notify_receipt_admins(r, media=False):
    ui = SETTINGS["ui"]
    cap = f"🧾 رسید #{r['id']}\nاز: <code>{r['user_id']}</code> @{USERS.get(str(r['user_id']),{}).get('username','-')}\nنوع: {r['kind']}\n"
    if r["kind"]=="purchase":
        cap += f"انتظار مبلغ: {fmt_toman(r.get('expected','-'))}\nپلن: {r.get('plan_id','-')}\n"
    cap += f"وضعیت: {r['status']}"
    markup = ikb([[("✅ تأیید", f"rcp_ok:{r['id']}"), ("❌ رد", f"rcp_no:{r['id']}")]])
    for admin_id in SETTINGS["admins"]:
        try:
            if media and r.get("photo_id"):
                bot.send_photo(admin_id, r["photo_id"], cap, reply_markup=markup)
            else:
                bot.send_message(admin_id, cap, reply_markup=markup)
        except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("rcp_ok:") or c.data.startswith("rcp_no:"))
def cb_rcp(c):
    ok = c.data.startswith("rcp_ok:")
    rid = c.data.split(":")[1]
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "فقط ادمین."); return
    r = RECEIPTS.get(rid)
    if not r:
        bot.answer_callback_query(c.id, "یافت نشد."); return
    if r["status"]!="pending":
        bot.answer_callback_query(c.id, "قبلاً رسیدگی شده."); return
    r["handled"]=True
    if ok:
        r["status"]="approved"
        # اعمال اثر
        if r["kind"]=="wallet":
            # ادمین باید مبلغ را بفرستد: پیام بعدی ادمین همین ترد
            # ساده‌تر: مبلغ را  در لحظه با پرسش از ادمین بگیریم
            ask = ikb([[("وارد کردن مبلغ شارژ", f"rcp_amt:{rid}")]])
            bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=ask)
            bot.answer_callback_query(c.id, "برای شارژ، دکمه «وارد کردن مبلغ شارژ» را بزنید.")
            save("receipts", RECEIPTS)
            return
        elif r["kind"]=="purchase":
            # ارسال کانفیگ و ثبت خرید
            uid = r["user_id"]; pid = r["plan_id"]
            send_config_to_user(uid, pid)
            U = user(uid)
            final = int(r.get("expected", 0))
            U["history"].append({"type":"purchase","amount":final,"time":now_iso(),"plan_id":pid})
            save("users", USERS)
            maybe_mark_coupon(r.get("coupon"))
            try: bot.send_message(uid, SETTINGS["ui"]["receipt_approved"])
            except: pass
    else:
        r["status"]="rejected"
        try: bot.send_message(r["user_id"], SETTINGS["ui"]["receipt_rejected"])
        except: pass
    save("receipts", RECEIPTS)
    # آپدیت پیام ادمین
    try:
        bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=None)
    except: pass
    bot.answer_callback_query(c.id, "ثبت شد.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("rcp_amt:"))
def cb_rcp_amount(c):
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "فقط ادمین."); return
    rid = c.data.split(":")[1]
    r = RECEIPTS.get(rid)
    if not r or r["kind"]!="wallet":
        bot.answer_callback_query(c.id, "نامعتبر."); return
    # وارد کردن مبلغ شارژ
    admin_uid = c.from_user.id
    A = user(admin_uid)
    A["state"]={"mode":"enter_charge_amount","rid":rid}
    save("users", USERS)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "مبلغ شارژ (تومان) را وارد کنید:")

@bot.message_handler(func=lambda m: user(m.from_user.id).get("state",{}).get("mode")=="enter_charge_amount")
def on_enter_charge_amount(m):
    uid = m.from_user.id
    A = user(uid)
    rid = A["state"]["rid"]
    r = RECEIPTS.get(rid)
    try:
        amt = int(m.text.strip())
    except:
        bot.send_message(m.chat.id, "عدد معتبر وارد کنید."); return
    # شارژ
    U = user(r["user_id"])
    U["wallet"] += amt
    U["history"].append({"type":"topup","amount":amt,"time":now_iso()})
    save("users", USERS)
    try: bot.send_message(r["user_id"], f"کیف پول شما به مبلغ {fmt_toman(amt)} شارژ شد.")
    except: pass
    A["state"]={}
    save("users", USERS)
    bot.send_message(m.chat.id, "شارژ انجام شد.")
    # بستن رسید
    r["status"]="approved"
    r["handled"]=True
    r["amount"]=amt
    save("receipts", RECEIPTS)

# -------------------- مدیریت مخزن (ادمین) --------------------
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and user(m.from_user.id).get("state",{}).get("mode")=="stock_menu", content_types=['text'])
def stock_cmd(m):
    t = m.text.strip()
    if t.startswith("send-"):
        pid = t[5:]
        if pid not in PLANS:
            bot.send_message(m.chat.id, "پلن نامعتبر."); return
        U = user(m.from_user.id)
        U["state"]={"mode":"stock_add","pid":pid}
        save("users", USERS)
        bot.send_message(m.chat.id, "متن کانفیگ را بفرستید (اختیاری، می‌توانید مستقیم عکس بفرستید).")
        return
    if t.startswith("show-"):
        pid = t[5:]
        arr = STOCK.get(pid, [])
        bot.send_message(m.chat.id, f"موجودی مخزن پلن #{pid}: {len(arr)}")
        return

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and user(m.from_user.id).get("state",{}).get("mode")=="stock_add", content_types=['text','photo'])
def stock_add(m):
    U = user(m.from_user.id)
    pid = U["state"]["pid"]
    text = None; photo_id = None
    if m.photo:
        photo_id = m.photo[-1].file_id
        text = m.caption or ""
    else:
        text = m.text or ""
    item = {"id":str(uuid.uuid4())[:8], "text": text, "photo_id": photo_id}
    arr = STOCK.get(pid, [])
    arr.append(item)
    STOCK[pid]=arr
    save("stock", STOCK)
    U["state"]={}
    save("users", USERS)
    bot.send_message(m.chat.id, SETTINGS["ui"]["stock_added"], reply_markup=admin_menu())

# -------------------- فایل‌لاگ ساده --------------------
def log(msg):
    LOGS.append({"time": now_iso(), "msg": msg})
    if len(LOGS)>500: LOGS.pop(0)
    save("logs", LOGS)

# -------------------- وبهوک و وب‌سرور --------------------
@app.route("/", methods=['GET'])
def index():
    return "OK", 200

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('utf-8')
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
        print(f"{datetime.utcnow().isoformat()} | INFO | Webhook set to: {WEBHOOK_URL}")
    except Exception as e:
        # 429 یا هر چیز دیگر: فقط لاگ کن، ربات با وبهوک کار می‌کند وقتی از تلگرام بیاد
        print(f"{datetime.utcnow().isoformat()} | ERROR | Failed to set webhook: {e}")
        traceback.print_exc()

# -------------- اجرای اولیه --------------
set_webhook_once()

# برای Gunicorn
app = app
