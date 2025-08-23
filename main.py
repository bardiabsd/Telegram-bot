# =========================
# main.py  (Single file)
# All-in-One Telegram Shop Bot
# =========================

import os
import json
import time
import uuid
import math
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from flask import Flask, request, abort
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaDocument,
    Message,
    CallbackQuery,
)

# -------------------------
# HARD-CODED CONFIG (per your request)
# -------------------------
BOT_TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"  # توکن شما
APP_URL = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"  # URL شما
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{APP_URL}{WEBHOOK_PATH}"

# Admin default
DEFAULT_ADMINS = [1743359080]   # آیدی عددی شما

# Timezone / locale
TZ = "Asia/Tehran"

# -------------------------
# Flask / Bot
# -------------------------
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=5)
app = Flask(__name__)

# -------------------------
# DB Helpers (JSON file)
# -------------------------
DB_FILE = "db.json"

def _ensure_db() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        data = {
            "admins": DEFAULT_ADMINS[:],
            "users": {},      # user_id -> profile {username, wallet, purchases:[], banned:False, tickets:[], joined_at}
            "plans": {},      # plan_id -> {id, name, days, volume, price, desc, active:True, stock_count:int, card_only:False}
            "stock": {},      # plan_id -> [ {id, text, image_file_id(optional)} ]
            "receipts": {},   # receipt_id -> {id, user_id, kind: purchase|wallet, plan_id?, amount?, status: pending|approved|rejected, created_at, message_id?, caption?, reply_to?}
            "discounts": {},  # code -> {code, percent, plan_limit: null|plan_id, max_uses, used, active:True, expire_at:ts or null}
            "buttons": {      # Editable button titles + visibility
                "buy": {"title": "🛍 خرید پلن", "enabled": True},
                "wallet": {"title": "🪙 کیف پول", "enabled": True},
                "tickets": {"title": "🎫 تیکت پشتیبانی", "enabled": True},
                "orders": {"title": "🧾 سفارش‌های من", "enabled": True},
                "account": {"title": "👤 حساب کاربری", "enabled": True},
                "admin": {"title": "🛠 پنل ادمین", "enabled": True},
            },
            "texts": {       # Editable texts
                "welcome": "به ربات فروش خوش آمدید 🌟 از دکمه‌های زیر استفاده کنید.",
                "card_number": "****-****-****-****",  # شماره کارت
                "card_holder": "نام صاحب کارت",
                "card_bank": "نام بانک",
                "purchase_note": "پس از پرداخت، رسید را آپلود کنید تا بررسی شود.",
                "wallet_rules": "برای شارژ کیف پول رسید کارت‌به‌کارت را بفرستید.",
            },
            "states": {},     # user_id -> arbitrary dict for flows
            "bans": {},       # user_id -> {"banned": True, "reason": "..."}
            "broadcast": {},  # last broadcasts
            "logs": [],       # simple append log lines
            "metrics": {      # counters for stats
                "total_revenue": 0,
                "total_orders": 0
            }
        }
        _save_db(data)
        return data
    else:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {
                    "admins": DEFAULT_ADMINS[:],
                    "users": {},
                    "plans": {},
                    "stock": {},
                    "receipts": {},
                    "discounts": {},
                    "buttons": {},
                    "texts": {},
                    "states": {},
                    "bans": {},
                    "broadcast": {},
                    "logs": [],
                    "metrics": {"total_revenue": 0, "total_orders": 0}
                }

def _save_db(data: Dict[str, Any]) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def db() -> Dict[str, Any]:
    return _ensure_db()

def persist():
    _save_db(_db)

_db = db()

def log_line(s: str):
    _db["logs"].append(f"[{datetime.now()}] {s}")
    if len(_db["logs"]) > 1000:
        _db["logs"] = _db["logs"][-1000:]
    persist()

# -------------------------
# Utility
# -------------------------
def is_admin(uid: int) -> bool:
    return uid in _db.get("admins", [])

def set_state(uid: int, **kwargs):
    st = _db["states"].get(str(uid), {})
    for k, v in kwargs.items():
        st[k] = v
    _db["states"][str(uid)] = st
    persist()

def get_state(uid: int) -> Dict[str, Any]:
    return _db["states"].get(str(uid), {})

def clear_state(uid: int, *keys):
    st = _db["states"].get(str(uid), {})
    if not keys:
        _db["states"][str(uid)] = {}
    else:
        for k in keys:
            st.pop(k, None)
        _db["states"][str(uid)] = st
    persist()

def tomans(n: int) -> str:
    s = f"{int(n):,}"
    return s.replace(",", "،") + " تومان"

def now_ts() -> int:
    return int(time.time())

def next_id(prefix="id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"

def get_user(uid: int, username: Optional[str] = None) -> Dict[str, Any]:
    u = _db["users"].get(str(uid))
    if not u:
        u = {
            "id": uid,
            "username": username or "",
            "wallet": 0,
            "purchases": [],   # [{order_id, plan_id, price, delivered_at, expires_at}]
            "tickets": [],     # [{ticket_id, subject, messages:[{from, text, ts}], open:bool}]
            "joined_at": now_ts(),
            "banned": False
        }
        _db["users"][str(uid)] = u
        persist()
    else:
        if username and u.get("username") != username:
            u["username"] = username
            persist()
    return u

def require_not_banned(uid: int) -> bool:
    u = get_user(uid)
    return not u.get("banned", False)

def pretty_plan(p: Dict[str, Any]) -> str:
    return f"{p['name']} | مدت: {p['days']} روز | حجم: {p['volume']} | قیمت: {tomans(p['price'])}"

def apply_discount(price: int, code: Optional[Dict[str, Any]], plan_id: Optional[str]) -> (int, Optional[str]):
    if not code:
        return price, None
    if not code.get("active", True):
        return price, None
    if code.get("expire_at") and now_ts() > code["expire_at"]:
        return price, None
    if code.get("plan_limit") and plan_id and code["plan_limit"] != plan_id:
        return price, None
    if code.get("max_uses") and code.get("used", 0) >= code["max_uses"]:
        return price, None
    percent = int(code.get("percent", 0))
    final = max(0, math.floor(price * (100 - percent) / 100))
    return final, code["code"]

# -------------------------
# Keyboards
# -------------------------
def main_menu(uid: int) -> InlineKeyboardMarkup:
    k = InlineKeyboardMarkup(row_width=2)
    btns = _db["buttons"]
    # Order of showing:
    rows = []
    if btns.get("buy", {}).get("enabled", True):
        rows.append(InlineKeyboardButton(btns["buy"]["title"], callback_data="menu:buy"))
    if btns.get("wallet", {}).get("enabled", True):
        rows.append(InlineKeyboardButton(btns["wallet"]["title"], callback_data="menu:wallet"))
    if btns.get("tickets", {}).get("enabled", True):
        rows.append(InlineKeyboardButton(btns["tickets"]["title"], callback_data="menu:tickets"))
    if btns.get("orders", {}).get("enabled", True):
        rows.append(InlineKeyboardButton(btns["orders"]["title"], callback_data="menu:orders"))
    if btns.get("account", {}).get("enabled", True):
        rows.append(InlineKeyboardButton(btns["account"]["title"], callback_data="menu:account"))
    if is_admin(uid) and btns.get("admin", {}).get("enabled", True):
        rows.append(InlineKeyboardButton(btns["admin"]["title"], callback_data="admin:panel"))

    # pack by row_width
    chunk = []
    for b in rows:
        chunk.append(b)
        if len(chunk) == 2:
            k.add(*chunk)
            chunk = []
    if chunk:
        k.add(*chunk)

    return k

def back_home():
    k = InlineKeyboardMarkup()
    k.add(InlineKeyboardButton("🏠 بازگشت", callback_data="menu:home"))
    return k

# -------------------------
# UI: User Menus
# -------------------------
def show_home(chat_id: int):
    txt = _db["texts"].get("welcome", "به ربات خوش آمدید")
    bot.edit_message_text(
        txt,
        chat_id,
        get_state(chat_id).get("last_msg_id"),
        reply_markup=main_menu(chat_id),
        parse_mode="HTML"
    )

def send_home(chat_id: int):
    txt = _db["texts"].get("welcome", "به ربات خوش آمدید")
    m = bot.send_message(chat_id, txt, reply_markup=main_menu(chat_id), parse_mode="HTML")
    set_state(chat_id, last_msg_id=m.message_id)

def show_buy_menu(chat_id: int):
    plans = list(_db["plans"].values())
    k = InlineKeyboardMarkup(row_width=1)
    if not plans:
        k.add(InlineKeyboardButton("➕ افزودن پلن (ادمین)", callback_data="admin:plans"))
        txt = "فعلاً پلنی موجود نیست."
    else:
        txt = "📦 لیست پلن‌ها:"
        for p in plans:
            if not p.get("active", True):
                continue
            stock_count = _db["plans"][p["id"]].get("stock_count", 0)
            title = f"{p['name']} ({stock_count} موجود)"
            cd = f"buy:plan:{p['id']}"
            btn = InlineKeyboardButton(title, callback_data=cd)
            if stock_count <= 0:
                # Disabled: به‌صورت ظاهری با پسوند
                title = f"{p['name']} (ناموجود)"
                btn = InlineKeyboardButton(title, callback_data="noop")
            k.add(btn)
    k.add(InlineKeyboardButton("🏠 بازگشت", callback_data="menu:home"))
    bot.edit_message_text(
        txt,
        chat_id,
        get_state(chat_id).get("last_msg_id"),
        reply_markup=k
    )

def show_wallet_menu(chat_id: int):
    u = get_user(chat_id)
    bal = tomans(u["wallet"])
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet:charge"),
        InlineKeyboardButton("❌ انصراف", callback_data="menu:home")
    )
    k.add(InlineKeyboardButton("📜 تاریخچه تراکنش‌ها", callback_data="wallet:history"))
    bot.edit_message_text(
        f"🪙 موجودی فعلی: <b>{bal}</b>\n\n{_db['texts'].get('wallet_rules','')}",
        chat_id,
        get_state(chat_id).get("last_msg_id"),
        reply_markup=k,
        parse_mode="HTML"
    )

def show_orders(chat_id: int):
    u = get_user(chat_id)
    if not u["purchases"]:
        txt = "سفارشی ندارید."
    else:
        lines = ["🧾 سفارش‌های شما:"]
        for o in u["purchases"]:
            p = _db["plans"].get(o["plan_id"])
            pname = p["name"] if p else o["plan_id"]
            exp = datetime.fromtimestamp(o["expires_at"]).strftime("%Y-%m-%d")
            lines.append(f"• {pname} | قیمت: {tomans(o['price'])} | انقضا: {exp}")
        txt = "\n".join(lines)
    bot.edit_message_text(
        txt,
        chat_id,
        get_state(chat_id).get("last_msg_id"),
        reply_markup=back_home()
    )

def show_account(chat_id: int, username: Optional[str]):
    u = get_user(chat_id, username)
    txt = (
        f"👤 حساب کاربری\n\n"
        f"آیدی عددی: <code>{u['id']}</code>\n"
        f"یوزرنیم: @{u['username'] if u['username'] else '—'}\n"
        f"تعداد خرید: {len(u['purchases'])}\n"
        f"موجودی کیف پول: {tomans(u['wallet'])}\n"
    )
    bot.edit_message_text(
        txt, chat_id, get_state(chat_id).get("last_msg_id"),
        reply_markup=back_home(), parse_mode="HTML"
    )

def show_tickets_menu(chat_id: int):
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("🆕 ایجاد تیکت", callback_data="ticket:new"),
        InlineKeyboardButton("📂 تیکت‌های من", callback_data="ticket:list")
    )
    k.add(InlineKeyboardButton("🏠 بازگشت", callback_data="menu:home"))
    bot.edit_message_text(
        "🎫 پشتیبانی", chat_id, get_state(chat_id).get("last_msg_id"),
        reply_markup=k
    )

# -------------------------
# Admin Panel (summarized, but complete)
# -------------------------
def admin_panel(uid: int):
    if not is_admin(uid):
        bot.answer_callback_query(get_state(uid).get("last_cbq_id"), "اجازه دسترسی ندارید.")
        return
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("👑 ادمین‌ها", callback_data="admin:admins"),
        InlineKeyboardButton("🧩 دکمه‌ها و متون", callback_data="admin:ui"),
    )
    k.add(
        InlineKeyboardButton("📦 پلن‌ها/مخزن", callback_data="admin:plans"),
        InlineKeyboardButton("🏷 کد تخفیف", callback_data="admin:discounts"),
    )
    k.add(
        InlineKeyboardButton("🧾 رسیدها", callback_data="admin:receipts"),
        InlineKeyboardButton("🪙 کیف پول", callback_data="admin:wallet"),
    )
    k.add(
        InlineKeyboardButton("👥 کاربران", callback_data="admin:users"),
        InlineKeyboardButton("📢 اعلان همگانی", callback_data="admin:broadcast"),
    )
    k.add(InlineKeyboardButton("📊 آمار فروش", callback_data="admin:stats"))
    k.add(InlineKeyboardButton("🏠 بازگشت", callback_data="menu:home"))
    bot.edit_message_text(
        "🛠 پنل ادمین",
        uid,
        get_state(uid).get("last_msg_id"),
        reply_markup=k
    )

# ---- Admin: Admins ----
def admin_admins(uid: int):
    A = _db["admins"]
    txt = "👑 مدیریت ادمین‌ها\n\n"
    if A:
        txt += "ادمین‌های فعلی:\n" + "\n".join([f"• <code>{a}</code>" for a in A]) + "\n"
    else:
        txt += "ادمینی ثبت نشده.\n"
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin:add_admin"),
        InlineKeyboardButton("➖ حذف ادمین", callback_data="admin:del_admin"),
    )
    k.add(InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel"))
    bot.edit_message_text(
        txt, uid, get_state(uid).get("last_msg_id"),
        reply_markup=k, parse_mode="HTML"
    )

# ---- Admin: UI (buttons & texts) ----
def admin_ui(uid: int):
    btns = _db["buttons"]
    txts = _db["texts"]
    lines = ["🧩 مدیریت دکمه‌ها و متون"]
    lines.append("دکمه‌ها:")
    for key, val in btns.items():
        lines.append(f"• {key}: «{val['title']}» | {'روشن' if val.get('enabled',True) else 'خاموش'}")
    lines.append("\nمتون کلیدی:")
    for key, val in txts.items():
        if key in ("card_number", "card_holder", "card_bank"):
            lines.append(f"• {key}: {val}")
        else:
            preview = val if len(val) < 40 else val[:40] + "…"
            lines.append(f"• {key}: {preview}")
    txt = "\n".join(lines)

    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("✏️ ویرایش متن‌ها", callback_data="ui:edit_texts"),
        InlineKeyboardButton("🔘 ویرایش دکمه‌ها", callback_data="ui:edit_buttons"),
    )
    k.add(InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel"))
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# ---- Admin: Plans & Stock ----
def admin_plans(uid: int):
    plans = list(_db["plans"].values())
    lines = ["📦 مدیریت پلن‌ها و مخزن"]
    if not plans:
        lines.append("هیچ پلنی ثبت نشده.")
    else:
        for p in plans:
            lines.append(f"• {p['name']} | {tomans(p['price'])} | موجودی: {p.get('stock_count',0)} | {'فعال' if p.get('active',True) else 'غیرفعال'}")
    txt = "\n".join(lines)
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("➕ افزودن پلن", callback_data="plan:add"),
        InlineKeyboardButton("✏️ ویرایش/حذف پلن", callback_data="plan:edit"),
    )
    k.add(
        InlineKeyboardButton("📥 مدیریت مخزن", callback_data="stock:manage"),
        InlineKeyboardButton("🔄 روشن/خاموش پلن", callback_data="plan:toggle"),
    )
    k.add(InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel"))
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# ---- Admin: Discounts ----
def admin_discounts(uid: int):
    d = _db["discounts"]
    lines = ["🏷 کدهای تخفیف:"]
    if not d:
        lines.append("هیچ کدی ثبت نشده.")
    else:
        for c, obj in d.items():
            status = "فعال" if obj.get("active", True) else "غیرفعال"
            limit = obj.get("plan_limit") or "همه پلن‌ها"
            uses = f"{obj.get('used',0)}/{obj.get('max_uses','∞')}"
            exp = obj.get("expire_at")
            exp_s = datetime.fromtimestamp(exp).strftime("%Y-%m-%d") if exp else "—"
            lines.append(f"• {c} | %{obj['percent']} | محدودیت: {limit} | مصرف: {uses} | تا: {exp_s} | {status}")
    txt = "\n".join(lines)
    k = InlineKeyboardMarkup(row_width=2)
    k.add(InlineKeyboardButton("➕ ساخت کد تخفیف", callback_data="disc:new"))
    k.add(InlineKeyboardButton("✏️ ویرایش/حذف", callback_data="disc:edit"))
    k.add(InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel"))
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# ---- Admin: Receipts Inbox ----
def admin_receipts(uid: int):
    recs = [r for r in _db["receipts"].values() if r["status"] == "pending"]
    lines = [ "🧾 رسیدهای در انتظار:" ]
    if not recs:
        lines.append("موردی نیست.")
    else:
        for r in recs[:30]:
            kind = "خرید" if r["kind"] == "purchase" else "شارژ کیف پول"
            lines.append(f"• {r['id']} | {kind} | از کاربر {r['user_id']}")
    txt = "\n".join(lines)
    k = InlineKeyboardMarkup(row_width=2)
    k.add(InlineKeyboardButton("📥 مشاهده لیست کامل", callback_data="rec:list"))
    k.add(InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel"))
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# ---- Admin: Wallet Ops ----
def admin_wallet(uid: int):
    txt = (
        "🪙 مدیریت کیف پول\n\n"
        "• تأیید رسیدهای «شارژ کیف پول» در انتظار\n"
        "• شارژ/کسر دستی موجودی کاربر"
    )
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("📥 رسیدهای شارژ (Pending)", callback_data="rec:wallet_pending"),
        InlineKeyboardButton("➕ شارژ دستی", callback_data="wallet:manual_charge"),
    )
    k.add(
        InlineKeyboardButton("➖ کسر دستی", callback_data="wallet:manual_debit"),
        InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel"),
    )
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# ---- Admin: Users ----
def admin_users(uid: int):
    txt = "👥 مدیریت کاربران\n\nبا واردکردن آیدی/یوزرنیم می‌توانید جستجو کنید."
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("🔎 جستجو", callback_data="users:search"),
        InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel")
    )
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# ---- Admin: Broadcast ----
def admin_broadcast(uid: int):
    txt = "📢 ارسال اعلان همگانی\n\nپیام خود را بفرستید (متن)."
    set_state(uid, flow="broadcast_wait_text")
    k = InlineKeyboardMarkup().add(InlineKeyboardButton("انصراف", callback_data="admin:panel"))
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# ---- Admin: Stats ----
def admin_stats(uid: int):
    m = _db["metrics"]
    total_orders = m.get("total_orders", 0)
    total_revenue = m.get("total_revenue", 0)

    # Top buyers
    top = []
    for uid_s, u in _db["users"].items():
        spent = sum([x["price"] for x in u.get("purchases", [])])
        count = len(u.get("purchases", []))
        if count > 0:
            # find most purchased plan name
            plan_counter = {}
            for x in u["purchases"]:
                plan_counter[x["plan_id"]] = plan_counter.get(x["plan_id"], 0) + 1
            most_plan_id = max(plan_counter, key=plan_counter.get)
            mp = _db["plans"].get(most_plan_id, {"name": most_plan_id})
            top.append((int(uid_s), spent, count, mp["name"]))
    top.sort(key=lambda t: t[1], reverse=True)
    lines = [
        "📊 آمار فروش",
        f"تعداد کل سفارش‌ها: {total_orders}",
        f"درآمد کل: {tomans(total_revenue)}",
        "",
        "Top Buyers:"
    ]
    if not top:
        lines.append("—")
    else:
        for i, (uid_i, spent, count, mpname) in enumerate(top[:10], 1):
            lines.append(f"{i}) {uid_i} | {tomans(spent)} | {count} خرید | محبوب: {mpname}")

    txt = "\n".join(lines)
    k = InlineKeyboardMarkup().add(InlineKeyboardButton("↩️ بازگشت", callback_data="admin:panel"))
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=k)

# -------------------------
# Purchase Flow
# -------------------------
def show_plan_detail(chat_id: int, plan_id: str, coupon_code: Optional[str] = None):
    p = _db["plans"].get(plan_id)
    if not p or not p.get("active", True):
        bot.answer_callback_query(get_state(chat_id).get("last_cbq_id"), "این پلن در دسترس نیست.")
        return
    base = p["price"]
    coupon_obj = _db["discounts"].get(coupon_code) if coupon_code else None
    final, applied = apply_discount(base, coupon_obj, plan_id)
    lines = [
        f"📦 {p['name']}",
        f"مدت: {p['days']} روز",
        f"حجم: {p['volume']}",
        f"قیمت: {tomans(base)}",
    ]
    if applied:
        lines.append(f"کد تخفیف اعمال شد: {applied} → مبلغ نهایی: {tomans(final)}")
    txt = "\n".join(lines)
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("🏷 اعمال کد تخفیف", callback_data=f"buy:coupon:{plan_id}"),
        InlineKeyboardButton("انصراف", callback_data="menu:buy")
    )
    # payment options
    k.add(
        InlineKeyboardButton("پرداخت با کیف پول", callback_data=f"buy:pay_wallet:{plan_id}"),
        InlineKeyboardButton("کارت‌به‌کارت", callback_data=f"buy:pay_card:{plan_id}")
    )
    bot.edit_message_text(txt, chat_id, get_state(chat_id).get("last_msg_id"), reply_markup=k)

def prompt_coupon(chat_id: int, plan_id: str):
    set_state(chat_id, flow="await_coupon", plan_id=plan_id)
    k = InlineKeyboardMarkup().add(InlineKeyboardButton("انصراف", callback_data=f"buy:plan:{plan_id}"))
    bot.edit_message_text("کد تخفیف را وارد کنید:", chat_id, get_state(chat_id).get("last_msg_id"), reply_markup=k)

def pay_by_wallet(chat_id: int, plan_id: str):
    u = get_user(chat_id)
    p = _db["plans"].get(plan_id)
    if not p:
        bot.answer_callback_query(get_state(chat_id).get("last_cbq_id"), "پلن یافت نشد.")
        return
    # discount?
    st = get_state(chat_id)
    coupon_code = st.get("coupon_code")
    coupon_obj = _db["discounts"].get(coupon_code) if coupon_code else None
    price, applied = apply_discount(p["price"], coupon_obj, plan_id)
    if u["wallet"] >= price:
        # cut wallet + deliver
        u["wallet"] -= price
        deliver_plan(chat_id, plan_id, price)
        persist()
        bot.answer_callback_query(get_state(chat_id).get("last_cbq_id"), "پرداخت انجام شد.")
        send_home(chat_id)
    else:
        diff = price - u["wallet"]
        k = InlineKeyboardMarkup(row_width=2)
        k.add(
            InlineKeyboardButton(f"شارژ همین مقدار ({tomans(diff)})", callback_data=f"wallet:charge_diff:{diff}"),
            InlineKeyboardButton("انصراف", callback_data=f"buy:plan:{plan_id}")
        )
        bot.edit_message_text(
            f"موجودی کافی نیست. مابه‌التفاوت: <b>{tomans(diff)}</b>",
            chat_id, get_state(chat_id).get("last_msg_id"), reply_markup=k, parse_mode="HTML"
        )

def pay_by_card(chat_id: int, plan_id: str):
    st = get_state(chat_id)
    coupon_code = st.get("coupon_code")
    coupon_obj = _db["discounts"].get(coupon_code) if coupon_code else None
    p = _db["plans"].get(plan_id)
    if not p:
        bot.answer_callback_query(get_state(chat_id).get("last_cbq_id"), "پلن یافت نشد.")
        return
    price, applied = apply_discount(p["price"], coupon_obj, plan_id)
    text = (
        "لطفاً مبلغ را کارت‌به‌کارت کنید و رسید را همینجا ارسال نمایید.\n\n"
        f"شماره کارت: <b>{_db['texts'].get('card_number')}</b>\n"
        f"به نام: {_db['texts'].get('card_holder')} ({_db['texts'].get('card_bank')})\n\n"
        f"مبلغ: <b>{tomans(price)}</b>\n\n"
        f"{_db['texts'].get('purchase_note','')}"
    )
    k = InlineKeyboardMarkup(row_width=2)
    k.add(
        InlineKeyboardButton("ارسال رسید", callback_data=f"buy:send_receipt:{plan_id}:{price}"),
        InlineKeyboardButton("انصراف", callback_data=f"buy:plan:{plan_id}")
    )
    bot.edit_message_text(text, chat_id, get_state(chat_id).get("last_msg_id"), reply_markup=k, parse_mode="HTML")

def deliver_plan(uid: int, plan_id: str, price_paid: int):
    # pick one stock from pool
    pool = _db["stock"].get(plan_id, [])
    if not pool:
        # fallback: بدون مخزن (هشدار به ادمین)
        for a in _db["admins"]:
            try:
                bot.send_message(a, f"هشدار: مخزن پلن {plan_id} خالی است.")
            except:
                pass
        cfg_text = "کانفیگ فعلاً موجود نیست. با ادمین تماس بگیرید."
        bot.send_message(uid, cfg_text)
    else:
        item = pool.pop(0)
        _db["stock"][plan_id] = pool
        # send to user
        lines = [f"✅ کانفیگ پلن شما ({_db['plans'][plan_id]['name']})"]
        if item.get("text"):
            lines.append("\n")
            lines.append(item["text"])
        bot.send_message(uid, "\n".join(lines))
        if item.get("image_file_id"):
            try:
                bot.send_photo(uid, item["image_file_id"], caption="تصویر کانفیگ")
            except:
                pass
        # update stock_count
        _db["plans"][plan_id]["stock_count"] = max(0, _db["plans"][plan_id].get("stock_count", 0) - 1)

    # record purchase
    expires_at = now_ts() + int(_db["plans"][plan_id]["days"]) * 86400
    get_user(uid)
    _db["users"][str(uid)]["purchases"].append({
        "order_id": next_id("order"),
        "plan_id": plan_id,
        "price": price_paid,
        "delivered_at": now_ts(),
        "expires_at": expires_at
    })
    # metrics
    _db["metrics"]["total_orders"] = _db["metrics"].get("total_orders", 0) + 1
    _db["metrics"]["total_revenue"] = _db["metrics"].get("total_revenue", 0) + int(price_paid)
    persist()

# -------------------------
# Ticketing
# -------------------------
def ticket_new(uid: int):
    set_state(uid, flow="ticket_subject")
    k = InlineKeyboardMarkup().add(InlineKeyboardButton("انصراف", callback_data="menu:tickets"))
    bot.edit_message_text("موضوع تیکت را بنویسید:", uid, get_state(uid).get("last_msg_id"), reply_markup=k)

def ticket_list(uid: int):
    u = get_user(uid)
    T = u.get("tickets", [])
    if not T:
        txt = "تیکتی ندارید."
    else:
        lines = ["📂 تیکت‌های شما:"]
        for t in T[-10:]:
            status = "باز" if t.get("open", True) else "بسته"
            lines.append(f"• {t['ticket_id']} | {t['subject']} | {status}")
        txt = "\n".join(lines)
    bot.edit_message_text(txt, uid, get_state(uid).get("last_msg_id"), reply_markup=back_home())

def admin_ticket_notify(uid: int, ticket):
    for a in _db["admins"]:
        try:
            bot.send_message(a, f"تیکت جدید از {uid

