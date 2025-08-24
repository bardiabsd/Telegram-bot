# main.py
# -*- coding: utf-8 -*-
# GPT-5 Thinking — Bot Version: 1.0.3  (Stable, Koyeb-ready)
# Features:
# - Persian Telegram bot with FastAPI webhook
# - Auto webhook set for Koyeb (/webhook) with idempotent check (no 429 flood)
# - Reads BOT_TOKEN, ADMIN_IDS, BASE_URL, CARD_NUMBER from environment
# - Main menu (reply keyboard) like your screenshot; Admin panel only for admins
# - Plans list -> detail -> pay via wallet OR card-to-card with receipt
# - OFF30 coupon (30%) with polite validation messages
# - Wallet pay (deducts correctly). If insufficient: offer "pay difference"
# - Card-to-card receipts (image/text). Admins get notification with Approve/Reject (toggle-able)
# - On approve: send one config from repository (sample pool), remove from repo, friendly messages
# - On reject: notify user politely with emojis. Buttons remain for re-decision.
# - Orders history, My Account, Step-by-step guide
# - Sample configs in memory for testing

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Message, User, PhotoSize
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, CallbackQueryHandler,
    filters
)
from telegram.error import RetryAfter, BadRequest, InvalidToken

# -----------------------
# Environment & Settings
# -----------------------
BOT_VERSION = "1.0.3"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
CARD_NUMBER = os.environ.get("CARD_NUMBER", "6037-9975-1234-5678")

_admin_env = os.environ.get("ADMIN_IDS", os.environ.get("ADMIN_ID", "")).strip()
ADMIN_IDS: List[int] = []
if _admin_env:
    for part in _admin_env.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_IDS.append(int(part))

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}" if BASE_URL else ""

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
log = logging.getLogger(__name__)

# -----------------------
# In-memory stores
# -----------------------
USERS: Dict[int, Dict[str, Any]] = {}
PENDING_RECEIPTS: Dict[str, Dict[str, Any]] = {}  # receipt_id -> record

# Sample plans & repositories (test pool)
PLANS: Dict[str, Dict[str, Any]] = {
    "bronze": {
        "id": "bronze",
        "name": "پلن برنزی",
        "price": 120_000,
        "traffic": "50GB",
        "duration": "30 روز",
        "stock": 3,  # derived from len(repo)
        "repo": [
            "vless://BRONZE-ABCDEF@1.2.3.4:443?security=reality#Bronze-1",
            "vless://BRONZE-GHIJKL@1.2.3.4:443?security=reality#Bronze-2",
            "vless://BRONZE-MNOPQR@1.2.3.4:443?security=reality#Bronze-3",
        ],
        "desc": "✔️ ترافیک: 50GB\n⏳ مدت: 30 روز\n🚀 پشتیبانی معمولی"
    },
    "silver": {
        "id": "silver",
        "name": "پلن نقره‌ای",
        "price": 190_000,
        "traffic": "120GB",
        "duration": "60 روز",
        "stock": 2,
        "repo": [
            "vless://SILVER-AAAAAA@2.3.4.5:443?security=reality#Silver-1",
            "vless://SILVER-BBBBBB@2.3.4.5:443?security=reality#Silver-2",
        ],
        "desc": "✔️ ترافیک: 120GB\n⏳ مدت: 60 روز\n⚡ پشتیبانی سریع‌تر"
    },
    "gold": {
        "id": "gold",
        "name": "پلن طلایی",
        "price": 290_000,
        "traffic": "200GB",
        "duration": "90 روز",
        "stock": 1,
        "repo": [
            "vless://GOLD-ZZZZZZ@5.6.7.8:443?security=reality#Gold-1",
        ],
        "desc": "✔️ ترافیک: 200GB\n⏳ مدت: 90 روز\n👑 اولویت پشتیبانی"
    }
}

# Coupons
COUPONS: Dict[str, Dict[str, Any]] = {
    "OFF30": {"type": "percent", "value": 30, "active": True}
}

# Constants: Persian labels / emojis (do NOT change texts per user request)
BTN_BUY = "🛒 خرید کانفیگ"
BTN_TUTORIAL = "🎒 آموزش قدم‌به‌قدم"
BTN_MY_ACCOUNT = "👤 حساب من"
BTN_MY_ORDERS = "🧾 سفارش‌های من"
BTN_COUPON = "🎟️ کد تخفیف"
BTN_ADMIN_PANEL = "⚙️ پنل ادمین"

BTN_BACK = "↩️ بازگشت"
BTN_CANCEL = "❌ انصراف"
BTN_PAY_WALLET = "💼 پرداخت از کیف پول"
BTN_PAY_CARD = "💳 کارت به کارت"
BTN_APPLY_COUPON = "🎟️ اعمال کد تخفیف"
BTN_TOPUP = "➕ افزایش موجودی کیف پول"
BTN_PAY_DIFF = "💸 پرداخت مابه‌التفاوت"

WELCOME_TEXT = (
    "سلام 👋\n"
    "خوش اومدی به ربات فروش کانفیگ ما! 😎\n\n"
    "اینجا می‌تونی خیلی راحت پلن‌هاتو ببینی، تخفیف اعمال کنی، با کیف پول یا کارت‌به‌کارت پرداخت کنی، "
    "و بعد از تایید رسید، کانفیگت رو ✨آماده و قابل کپی✨ تحویل بگیری. "
    "اگر سوالی داشتی «🎒 آموزش قدم‌به‌قدم» رو بزن تا مرحله‌به‌مرحله راهنماییت کنم. "
    "هرجا هم نیاز به کمک بود، ما کنارتم 😊"
)

TUTORIAL_TEXT = (
    "🎒 آموزش قدم‌به‌قدم:\n\n"
    "1) از «🛒 خرید کانفیگ» یکی از پلن‌ها رو انتخاب کن.\n"
    "2) جزئیات پلن رو ببین و اگه خواستی «🎟️ اعمال کد تخفیف» بزن.\n"
    "3) روش پرداخت رو انتخاب کن: «💼 پرداخت از کیف پول» یا «💳 کارت به کارت».\n"
    "4) اگه کارت به کارت رو زدی، پس از پرداخت شماره کارت، رسید رو به صورت عکس یا متن بفرست.\n"
    "5) رسیدت برای ادمین میره. ادمین تایید کنه، کانفیگ ✨آماده و قابل کپی✨ برات ارسال میشه.\n"
    "6) اگر موجودی کیف پولت کافی نبود، می‌تونی «💸 پرداخت مابه‌التفاوت» رو بزنی.\n\n"
    "برای مدیریت کیف پول و سفارش‌ها از «👤 حساب من» و «🧾 سفارش‌های من» استفاده کن. 😉"
)

# -----------------------
# FastAPI app
# -----------------------
app = FastAPI(title="Telegram Bot (Koyeb-ready)", version=BOT_VERSION)

application: Optional[Application] = None  # PTB Application instance (async)

# -----------------------
# Helpers
# -----------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def ensure_user(user: User) -> Dict[str, Any]:
    u = USERS.get(user.id)
    if not u:
        u = {
            "id": user.id,
            "username": user.username or "-",
            "first_name": user.first_name or "",
            "wallet": 0,
            "orders": [],
            "session": {
                "step": None,
                "selected_plan": None,
                "amount": None,
                "final_amount": None,
                "coupon_code": None,
                "discount_percent": 0,
                "purpose": None,        # "purchase" | "topup" | "difference"
                "pending_receipt_id": None,
                "pending_diff": 0
            }
        }
        # For testing: give admin 50,000
        if is_admin(user.id) and u["wallet"] < 50_000:
            u["wallet"] = 50_000
        USERS[user.id] = u
    return u

def main_menu_for(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_BUY), KeyboardButton(BTN_TUTORIAL)],
        [KeyboardButton(BTN_MY_ACCOUNT), KeyboardButton(BTN_MY_ORDERS)],
        [KeyboardButton(BTN_COUPON)],
    ]
    if is_admin(user_id):
        rows.append([KeyboardButton(BTN_ADMIN_PANEL)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def plans_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for pid, p in PLANS.items():
        stock = len(p["repo"])
        title = f"{p['name']} — {p['price']:,} تومان {'✅' if stock>0 else '❌'}"
        buttons.append([InlineKeyboardButton(title, callback_data=f"plan:{pid}")])
    return InlineKeyboardMarkup(buttons)

def plan_detail_keyboard(plan_id: str, has_stock: bool) -> InlineKeyboardMarkup:
    buttons = []
    if has_stock:
        buttons.append([
            InlineKeyboardButton(BTN_PAY_WALLET, callback_data=f"buywallet:{plan_id}"),
            InlineKeyboardButton(BTN_PAY_CARD, callback_data=f"buycard:{plan_id}")
        ])
        buttons.append([InlineKeyboardButton(BTN_APPLY_COUPON, callback_data=f"coupon:{plan_id}")])
    buttons.append([
        InlineKeyboardButton(BTN_BACK, callback_data="back:plans"),
        InlineKeyboardButton(BTN_CANCEL, callback_data="cancel")
    ])
    return InlineKeyboardMarkup(buttons)

def receipt_admin_keyboard(receipt_id: str, current_status: str) -> InlineKeyboardMarkup:
    # Keep both buttons always (toggle-able)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"rcpt:{receipt_id}:approve"),
            InlineKeyboardButton("❌ رد", callback_data=f"rcpt:{receipt_id}:reject"),
        ]
    ])

def fmt_amount(rials: int) -> str:
    return f"{rials:,} تومان"

def calc_discounted(price: int, coupon_code: Optional[str]) -> (int, int):
    if not coupon_code:
        return price, 0
    c = COUPONS.get(coupon_code.upper())
    if not c or not c.get("active"):
        return price, 0
    if c["type"] == "percent":
        percent = int(c.get("value", 0))
        discount = price * percent // 100
        return max(price - discount, 0), percent
    return price, 0

def pop_config_for(plan_id: str) -> Optional[str]:
    p = PLANS.get(plan_id)
    if not p:
        return None
    if p["repo"]:
        cfg = p["repo"].pop(0)
        p["stock"] = len(p["repo"])
        return cfg
    return None

async def send_plan_detail(query_message: Message, plan_id: str, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    p = PLANS[plan_id]
    stock = len(p["repo"])
    has_stock = stock > 0
    text = (
        f"📦 <b>{p['name']}</b>\n"
        f"💲 قیمت: <b>{fmt_amount(p['price'])}</b>\n"
        f"📶 ترافیک: <b>{p['traffic']}</b>\n"
        f"📅 مدت: <b>{p['duration']}</b>\n"
        f"{p['desc']}\n"
        f"موجودی: {'✅ موجود' if has_stock else '❌ اتمام موجودی'}\n\n"
        f"یکی از گزینه‌های زیر رو انتخاب کن 👇"
    )
    await query_message.edit_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=plan_detail_keyboard(plan_id, has_stock)
    )

async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
        if msg:
            await msg.edit_text("🛍️ لیست پلن‌ها:", reply_markup=plans_keyboard())
    else:
        await update.message.reply_text("🛍️ لیست پلن‌ها:", reply_markup=plans_keyboard())

def session_reset(u: Dict[str, Any]):
    u["session"] = {
        "step": None,
        "selected_plan": None,
        "amount": None,
        "final_amount": None,
        "coupon_code": None,
        "discount_percent": 0,
        "purpose": None,
        "pending_receipt_id": None,
        "pending_diff": 0
    }

# -----------------------
# Handlers
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user)

    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=main_menu_for(user.id)
    )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await update.message.reply_text(
        "منوی اصلی 👇",
        reply_markup=main_menu_for(user.id)
    )

async def show_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"نسخه ربات: {BOT_VERSION}")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user)
    text = (update.message.text or "").strip()

    # Main menu routes
    if text == BTN_BUY:
        session_reset(u)
        await update.message.reply_text("🛍️ لیست پلن‌ها:", reply_markup=plans_keyboard())
        return

    if text == BTN_TUTORIAL:
        await update.message.reply_text(TUTORIAL_TEXT)
        return

    if text == BTN_MY_ACCOUNT:
        await show_account(update, context, u)
        return

    if text == BTN_MY_ORDERS:
        await show_orders(update, context, u)
        return

    if text == BTN_COUPON:
        u["session"]["step"] = "AWAIT_COUPON_GLOBAL"
        await update.message.reply_text("🎟️ کد تخفیف رو بفرست:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton(BTN_CANCEL)]], resize_keyboard=True))
        return

    if text == BTN_ADMIN_PANEL:
        if is_admin(user.id):
            await show_admin_panel(update, context, u)
        else:
            await update.message.reply_text("این بخش فقط برای ادمین در دسترسه.")
        return

    if text == BTN_CANCEL or text == BTN_BACK:
        session_reset(u)
        await update.message.reply_text("برگشتیم به منوی اصلی ✅", reply_markup=main_menu_for(user.id))
        return

    # Session-driven flows
    step = u["session"]["step"]

    if step == "AWAIT_COUPON_GLOBAL":
        code = text.upper()
        final, percent = calc_discounted(100_000, code)  # sample calc just to validate
        if percent == 0:
            await update.message.reply_text("اوه 😅 این کد تخفیف معتبر نیست. دوباره امتحان کن یا «❌ انصراف» رو بزن.")
        else:
            u["session"]["coupon_code"] = code
            u["session"]["discount_percent"] = percent
            await update.message.reply_text(f"کد تخفیف با موفقیت ثبت شد ✅ ({percent}%)\nحالا از «🛒 خرید کانفیگ» استفاده کن.",
                                            reply_markup=main_menu_for(user.id))
            u["session"]["step"] = None
        return

    if step == "AWAIT_TOPUP_AMOUNT":
        if not text.isdigit():
            await update.message.reply_text("لطفاً فقط مبلغ رو به عدد بفرست (مثلاً 50000) یا «❌ انصراف».")
            return
        amount = int(text)
        if amount <= 0:
            await update.message.reply_text("مبلغ معتبر نیست. دوباره وارد کن یا «❌ انصراف».")
            return
        u["session"]["purpose"] = "topup"
        u["session"]["amount"] = amount
        u["session"]["final_amount"] = amount
        u["session"]["step"] = "AWAIT_RECEIPT"

        msg = (
            f"عالیه! 😍\n"
            f"لطفاً مبلغ <b>{fmt_amount(amount)}</b> رو به این کارت واریز کن و بعد <b>رسید</b> رو (عکس یا متن) بفرست:\n\n"
            f"💳 <b>{CARD_NUMBER}</b>\n\n"
            "منتظر رسیدتم 💌"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    if step == "AWAIT_RECEIPT":
        # Expect photo or text as receipt
        receipt_id = f"rcpt_{user.id}_{int(datetime.now().timestamp())}"
        purpose = u["session"]["purpose"]  # purchase | topup | difference
        plan_id = u["session"]["selected_plan"]
        final_amount = u["session"]["final_amount"] or u["session"]["amount"] or 0

        caption_base = (
            f"🧾 رسید جدید\n"
            f"از: @{u['username']} (ID: {u['id']})\n"
            f"نوع: {'کارت به کارت' if purpose in ['purchase','difference','topup'] else 'نامشخص'}\n"
            f"مبلغ: {fmt_amount(final_amount)}\n"
            f"تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"هدف: {'خرید کانفیگ' if purpose=='purchase' else ('افزایش موجودی کیف پول' if purpose=='topup' else 'پرداخت مابه‌التفاوت')}\n"
        )
        if plan_id:
            caption_base += f"پلن: {PLANS[plan_id]['name']}\n"

        # Save pending
        rec: Dict[str, Any] = {
            "id": receipt_id,
            "user_id": u["id"],
            "username": u["username"],
            "purpose": purpose,
            "plan_id": plan_id,
            "amount": final_amount,
            "status": "pending",  # approved / rejected
            "ts": datetime.now().isoformat(),
            "message_ids": []
        }

        PENDING_RECEIPTS[receipt_id] = rec
        u["session"]["pending_receipt_id"] = receipt_id
        u["session"]["step"] = None  # reset wait state after sending

        # Forward to admins
        if update.message.photo:
            photo: PhotoSize = update.message.photo[-1]
            file_id = photo.file_id
            for admin_id in ADMIN_IDS:
                sent = await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=file_id,
                    caption=caption_base,
                    reply_markup=receipt_admin_keyboard(receipt_id, rec["status"])
                )
                rec["message_ids"].append((admin_id, sent.message_id))
        else:
            # text receipt
            text_rcpt = (update.message.text or "").strip()
            if text_rcpt:
                caption = caption_base + f"\nمتن رسید:\n{text_rcpt}"
            else:
                caption = caption_base + "\n(فاقد متن/عکس رسید)"
            for admin_id in ADMIN_IDS:
                sent = await context.bot.send_message(
                    chat_id=admin_id,
                    text=caption,
                    reply_markup=receipt_admin_keyboard(receipt_id, rec["status"])
                )
                rec["message_ids"].append((admin_id, sent.message_id))

        await update.message.reply_text(
            "رسیدت رسید! 🥰\n"
            "ادمین بررسی می‌کنه؛ نتیجه رو بهت خبر می‌دیم. ✌️",
            reply_markup=main_menu_for(user.id)
        )
        return

    # Fallback
    await update.message.reply_text("متوجه نشدم چی می‌خوای 🙂 از منوی اصلی یکی رو انتخاب کن:", reply_markup=main_menu_for(user.id))

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE, u: Dict[str, Any]):
    txt = (
        f"👤 حساب من\n"
        f"💼 موجودی کیف پول: <b>{fmt_amount(u['wallet'])}</b>\n\n"
        f"برای افزایش موجودی، روی «{BTN_TOPUP}» بزن."
    )
    kb = ReplyKeyboardMarkup([
        [KeyboardButton(BTN_TOPUP)],
        [KeyboardButton(BTN_BACK), KeyboardButton(BTN_CANCEL)]
    ], resize_keyboard=True)
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)

async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, u: Dict[str, Any]):
    if not u["orders"]:
        await update.message.reply_text("هنوز سفارشی نداری 🙂 از «🛒 خرید کانفیگ» شروع کن.")
        return
    lines = ["🧾 سفارش‌های من:"]
    for i, o in enumerate(u["orders"], 1):
        lines.append(f"{i}) {o['plan_name']} — {fmt_amount(o['paid'])} — {o['date']}")
    await update.message.reply_text("\n".join(lines))

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, u: Dict[str, Any]):
    total_pending = sum(1 for r in PENDING_RECEIPTS.values() if r["status"] == "pending")
    txt = (
        "⚙️ پنل ادمین\n"
        f"🟡 رسیدهای در انتظار: {total_pending}\n"
        "برای بررسی رسیدها، رو رسید ارسالی کلیک کنید و تایید/رد بزنید. (قابل تغییره)"
    )
    await update.message.reply_text(txt)

# ------------- Callbacks --------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user)
    q = update.callback_query
    if not q:
        return
    data = q.data or ""
    await q.answer()

    # Back/cancel
    if data == "cancel":
        session_reset(u)
        await q.message.edit_text("منو رو از دکمه‌ها انتخاب کن 👇")
        await q.message.reply_text("منوی اصلی 👇", reply_markup=main_menu_for(user.id))
        return
    if data == "back:plans":
        session_reset(u)
        await q.message.edit_text("🛍️ لیست پلن‌ها:", reply_markup=plans_keyboard())
        return

    # Plan selected
    if data.startswith("plan:"):
        plan_id = data.split(":")[1]
        if plan_id not in PLANS:
            await q.message.edit_text("این پلن موجود نیست.")
            return
        u["session"]["selected_plan"] = plan_id
        u["session"]["purpose"] = "purchase"
        await send_plan_detail(q.message, plan_id, context, user.id)
        return

    # Apply coupon
    if data.startswith("coupon:"):
        plan_id = data.split(":")[1]
        if plan_id not in PLANS:
            await q.message.reply_text("پلن نامعتبره.")
            return
        u["session"]["step"] = "AWAIT_PLAN_COUPON"
        u["session"]["selected_plan"] = plan_id
        await q.message.reply_text("کد تخفیف رو بفرست (مثلاً OFF30) یا «❌ انصراف».")
        return

    # Buy via wallet
    if data.startswith("buywallet:"):
        plan_id = data.split(":")[1]
        if plan_id not in PLANS:
            await q.message.reply_text("پلن نامعتبره.")
            return
        p = PLANS[plan_id]
        if not p["repo"]:
            await q.message.reply_text("متاسفانه موجودی این پلن تموم شده 😕، پلن‌های دیگه رو ببین.")
            return
        # Final amount with last coupon (if set)
        code = u["session"]["coupon_code"]
        final, percent = calc_discounted(p["price"], code)
        u["session"]["final_amount"] = final
        u["session"]["amount"] = p["price"]

        if USERS[user.id]["wallet"] >= final:
            USERS[user.id]["wallet"] -= final
            cfg = pop_config_for(plan_id)
            if not cfg:
                await q.message.reply_text("اوه! ظاهراً همزمان موجودی تموم شد. بعداً دوباره امتحان کن 😅")
                return
            USERS[user.id]["orders"].append({
                "plan_id": plan_id,
                "plan_name": p["name"],
                "paid": final,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            await q.message.reply_text("هورا! 🎉 پرداخت از کیف پول با موفقیت انجام شد و کانفیگت آماده‌ست 👇")
            await q.message.reply_text(f"<code>{cfg}</code>", parse_mode=ParseMode.HTML)
        else:
            diff = final - USERS[user.id]["wallet"]
            u["session"]["purpose"] = "difference"
            u["session"]["pending_diff"] = diff
            txt = (
                "کیف پولت کافی نیست 😅\n"
                f"مبلغ مورد نیاز: <b>{fmt_amount(final)}</b>\n"
                f"موجودی فعلی: <b>{fmt_amount(USERS[user.id]['wallet'])}</b>\n"
                f"مابه‌التفاوت: <b>{fmt_amount(diff)}</b>\n\n"
                "می‌خوای مابه‌التفاوت رو کارت‌به‌کارت پرداخت کنی؟"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(BTN_PAY_DIFF, callback_data=f"paydiff:{plan_id}")],
                [InlineKeyboardButton(BTN_BACK, callback_data=f"plan:{plan_id}")]
            ])
            await q.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    # Pay difference -> request receipt
    if data.startswith("paydiff:"):
        plan_id = data.split(":")[1]
        if plan_id not in PLANS:
            await q.message.reply_text("پلن نامعتبره.")
            return
        p = PLANS[plan_id]
        code = u["session"]["coupon_code"]
        final, percent = calc_discounted(p["price"], code)
        diff = final - USERS[user.id]["wallet"]
        if diff <= 0:
            await q.message.reply_text("الان دیگه موجودیت کافیه! دوباره «پرداخت از کیف پول» رو بزن.")
            return
        u["session"]["purpose"] = "difference"
        u["session"]["selected_plan"] = plan_id
        u["session"]["amount"] = diff
        u["session"]["final_amount"] = diff
        u["session"]["step"] = "AWAIT_RECEIPT"

        txt = (
            f"عالیه! 😍\n"
            f"لطفاً مابه‌التفاوت <b>{fmt_amount(diff)}</b> رو کارت‌به‌کارت کن و رسید رو بفرست.\n\n"
            f"💳 <b>{CARD_NUMBER}</b>\n\n"
            "منتظر رسیدتم 💌"
        )
        await q.message.reply_text(txt, parse_mode=ParseMode.HTML)
        return

    # Buy via card-to-card
    if data.startswith("buycard:"):
        plan_id = data.split(":")[1]
        if plan_id not in PLANS:
            await q.message.reply_text("پلن نامعتبره.")
            return
        p = PLANS[plan_id]
        if not p["repo"]:
            await q.message.reply_text("متاسفانه موجودی این پلن تموم شده 😕، پلن‌های دیگه رو ببین.")
            return
        code = u["session"]["coupon_code"]
        final, percent = calc_discounted(p["price"], code)
        u["session"]["purpose"] = "purchase"
        u["session"]["selected_plan"] = plan_id
        u["session"]["amount"] = p["price"]
        u["session"]["final_amount"] = final
        u["session"]["step"] = "AWAIT_RECEIPT"

        txt = (
            f"خیلی هم عالی! 😎\n"
            f"لطفاً مبلغ <b>{fmt_amount(final)}</b> رو کارت‌به‌کارت کن و بعد رسید رو (عکس یا متن) بفرست.\n\n"
            f"💳 <b>{CARD_NUMBER}</b>\n\n"
            "منتظر رسیدت هستم 💌"
        )
        await q.message.reply_text(txt, parse_mode=ParseMode.HTML)
        return

    # Receipt admin actions
    if data.startswith("rcpt:"):
        parts = data.split(":")
        if len(parts) != 3:
            return
        receipt_id, action = parts[1], parts[2]
        rec = PENDING_RECEIPTS.get(receipt_id)
        if not rec:
            await q.message.reply_text("این رسید پیدا نشد یا منقضی شده.")
            return
        if not is_admin(user.id):
            await q.message.reply_text("فقط ادمین می‌تونه این کار رو انجام بده.")
            return

        # Toggle-able approve/reject; do not disable buttons
        if action == "approve":
            rec["status"] = "approved"
            await q.message.edit_reply_markup(reply_markup=receipt_admin_keyboard(receipt_id, rec["status"]))
            # Apply business effect
            target_user_id = rec["user_id"]
            target_user = USERS.get(target_user_id)
            if not target_user:
                await q.message.reply_text("کاربر یافت نشد.")
                return
            purpose = rec["purpose"]
            plan_id = rec.get("plan_id")
            amount = rec["amount"]

            if purpose == "topup":
                target_user["wallet"] += amount
                await context.bot.send_message(chat_id=target_user_id, text="افزایش موجودی تایید شد ✅ کیف پولت شارژ شد 💸")
            elif purpose == "difference":
                # add to wallet then try to complete purchase
                target_user["wallet"] += amount
                if plan_id and plan_id in PLANS:
                    p = PLANS[plan_id]
                    code = target_user["session"]["coupon_code"]
                    final, percent = calc_discounted(p["price"], code)
                    if target_user["wallet"] >= final:
                        target_user["wallet"] -= final
                        cfg = pop_config_for(plan_id)
                        if cfg:
                            target_user["orders"].append({
                                "plan_id": plan_id,
                                "plan_name": p["name"],
                                "paid": final,
                                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            await context.bot.send_message(chat_id=target_user_id, text="پرداخت مابه‌التفاوت تایید شد ✅ سفارش تکمیل شد 🎉\nاینم کانفیگت:")
                            await context.bot.send_message(chat_id=target_user_id, text=f"<code>{cfg}</code>", parse_mode=ParseMode.HTML)
                        else:
                            await context.bot.send_message(chat_id=target_user_id, text="پرداخت تایید شد اما موجودی پلن به اتمام رسیده 😕 لطفاً با پشتیبانی تماس بگیر.")
                    else:
                        await context.bot.send_message(chat_id=target_user_id, text="پرداخت تایید شد ✅ موجودیت به‌روز شد. دوباره پرداخت از کیف پول رو امتحان کن.")
                else:
                    await context.bot.send_message(chat_id=target_user_id, text="پرداخت تایید شد ✅ موجودیت به‌روز شد.")
            elif purpose == "purchase":
                # directly deliver config
                if plan_id and plan_id in PLANS:
                    p = PLANS[plan_id]
                    code = target_user["session"]["coupon_code"]
                    final, percent = calc_discounted(p["price"], code)
                    cfg = pop_config_for(plan_id)
                    if cfg:
                        target_user["orders"].append({
                            "plan_id": plan_id,
                            "plan_name": p["name"],
                            "paid": final,
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        await context.bot.send_message(chat_id=target_user_id, text="رسیدت تایید شد ✅ اینم کانفیگت، مبارک باشه 🎉👇")
                        await context.bot.send_message(chat_id=target_user_id, text=f"<code>{cfg}</code>", parse_mode=ParseMode.HTML)
                    else:
                        await context.bot.send_message(chat_id=target_user_id, text="رسید تایید شد اما موجودی پلن تموم شده 😕 لطفاً با پشتیبانی در تماس باش.")
                else:
                    await context.bot.send_message(chat_id=target_user_id, text="رسید تایید شد ✅")
            else:
                await q.message.reply_text("هدف رسید نامشخص بود.")

        elif action == "reject":
            rec["status"] = "rejected"
            await q.message.edit_reply_markup(reply_markup=receipt_admin_keyboard(receipt_id, rec["status"]))
            target_user_id = rec["user_id"]
            await context.bot.send_message(
                chat_id=target_user_id,
                text="اوه نه 😕 رسیدت رد شد. اگه فکر می‌کنی اشتباهی شده، لطفاً با پشتیبانی تماس بگیر 💬"
            )
        return

async def on_message_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # photo receipt is handled in on_text when step == AWAIT_RECEIPT too,
    # but Telegram routes photos to this handler. We replicate logic.
    user = update.effective_user
    u = ensure_user(user)
    if u["session"]["step"] == "AWAIT_RECEIPT":
        await on_text(update, context)  # reuse logic
    else:
        await update.message.reply_text("عکست رسید ✅ اگر رسید پرداخت بوده، لطفاً اول مسیر پرداخت رو شروع کن.")

async def on_plan_coupon_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user)
    if u["session"]["step"] != "AWAIT_PLAN_COUPON":
        return
    code = (update.message.text or "").strip().upper()
    if not u["session"]["selected_plan"] or u["session"]["selected_plan"] not in PLANS:
        await update.message.reply_text("پلن نامعتبره. دوباره از «🛒 خرید کانفیگ» شروع کن.")
        u["session"]["step"] = None
        return
    p = PLANS[u["session"]["selected_plan"]]
    final, percent = calc_discounted(p["price"], code)
    if percent == 0:
        await update.message.reply_text("اوه 😅 این کد تخفیف معتبر نیست.")
    else:
        u["session"]["coupon_code"] = code
        u["session"]["discount_percent"] = percent
        await update.message.reply_text(f"کد تخفیف با موفقیت اعمال شد ✅ ({percent}%)\n"
                                        f"مبلغ جدید: <b>{fmt_amount(final)}</b>",
                                        parse_mode=ParseMode.HTML)
    # Back to plan detail view
    await send_plan_detail(update.message, p["id"], context, user.id)
    u["session"]["step"] = None

# -----------------------
# Commands to wire
# -----------------------
def build_application() -> Application:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is empty! Set env BOT_TOKEN.")
    app_builder = ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(True)
    return app_builder.build()

# -----------------------
# FastAPI lifespan
# -----------------------
@app.on_event("startup")
async def on_startup():
    global application
    application = build_application()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("version", show_version))

    # Text & photo flows
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.PHOTO, on_message_photo))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_text))
    # Dedicated coupon catcher while waiting for plan coupon
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_plan_coupon_text))

    # Initialize bot (fixes "Application was not initialized via Application.initialize")
    try:
        await application.initialize()
    except InvalidToken as e:
        log.exception("Invalid token on initialize: %s", e)
        # Let FastAPI fail loudly so Koyeb logs show the issue
        raise

    # Idempotent webhook set: avoid 429, 405
    if WEBHOOK_URL:
        try:
            info = await application.bot.get_webhook_info()
            if info.url != WEBHOOK_URL:
                # set webhook to /webhook; drop pending only when URL changes
                await application.bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
                log.info("✅ Webhook set to: %s", WEBHOOK_URL)
            else:
                log.info("✅ Webhook already set: %s", WEBHOOK_URL)
        except RetryAfter as e:
            log.warning("Webhook flood, retry-after: %s", e)
        except BadRequest as e:
            log.warning("Webhook BadRequest: %s", e)
    else:
        log.warning("BASE_URL not set; webhook not configured.")

    # Start PTB (needed for job queues; updates come via webhook endpoint)
    await application.start()
    log.info("Application startup complete.")

@app.on_event("shutdown")
async def on_shutdown():
    global application
    if application:
        try:
            await application.stop()
            await application.shutdown()
        except Exception:
            pass

# Healthcheck
@app.get("/", response_class=PlainTextResponse)
async def root():
    return "OK"

# Telegram webhook endpoint
@app.post(WEBHOOK_PATH)
async def webhook(req: Request):
    global application
    if not application:
        return Response(status_code=500, content="Application not ready")

    data = await req.json()
    update = Update.de_json(data, application.bot)
    # process_update requires initialized app (we did in startup)
    await application.process_update(update)
    return Response(status_code=200)

# -----------------------
# Local run (optional)
# -----------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), reload=False)
