# -*- coding: utf-8 -*-
# Telegram Shop Bot - Version 1.0.3
# FastAPI + python-telegram-bot v20 (webhook)
# ویژگی‌ها: منوی اصلی (Reply Keyboard)، فروشگاه/پلن‌ها، تخفیف OFF30، پرداخت از کیف پول،
# کارت‌به‌کارت با ارسال رسید و تایید/رد ادمین، ارسال کانفیگ از مخزن نمونه،
# آموزش قدم‌به‌قدم، پروفایل، کانفیگ‌های من، پشتیبانی. پنل ادمین فقط برای ادمین.

import os
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, Message, User as TGUser
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ---------------------- تنظیمات پایه ----------------------
BOT_VERSION = "1.0.3"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # اگر 0 باشد، اولین /start به عنوان ادمین ست می‌شود

if not TOKEN:
    # برای جلوگیری از کرش روی هاست اگر توکن ست نشده باشد
    TOKEN = "000000:TEST_TOKEN_PLACEHOLDER"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("shopbot")

# ---------------------- دیتابیس ساده در حافظه ----------------------
# کاربران
USERS: Dict[int, Dict[str, Any]] = {}
# رسیدهای در انتظار بررسی
PENDING_RECEIPTS: Dict[str, Dict[str, Any]] = {}
# شمارنده رسید
RECEIPT_SEQ = 1

# پلن‌ها + مخزن نمونه کانفیگ‌ها
PLANS: List[Dict[str, Any]] = [
    {
        "id": "p30_30",
        "title": "30 گیگ 30 روزه ✨",
        "days": 30,
        "traffic_gb": 30,
        "price": 50000,
        "stock": 2,
    },
    {
        "id": "p10_10",
        "title": "10 گیگ 10 روزه ✨",
        "days": 10,
        "traffic_gb": 10,
        "price": 25000,
        "stock": 3,
    },
    {
        "id": "p5_7",
        "title": "5 گیگ 7 روزه ✨",
        "days": 7,
        "traffic_gb": 5,
        "price": 15000,
        "stock": 5,
    },
]

CONFIG_REPO: Dict[str, List[str]] = {
    "p30_30": [
        "vless://TEST-CONFIG-30G-1#30G-1",
        "vless://TEST-CONFIG-30G-2#30G-2",
    ],
    "p10_10": [
        "vless://TEST-CONFIG-10G-1#10G-1",
        "vless://TEST-CONFIG-10G-2#10G-2",
        "vless://TEST-CONFIG-10G-3#10G-3",
    ],
    "p5_7": [
        "vless://TEST-CONFIG-5G-1#5G-1",
        "vless://TEST-CONFIG-5G-2#5G-2",
        "vless://TEST-CONFIG-5G-3#5G-3",
        "vless://TEST-CONFIG-5G-4#5G-4",
        "vless://TEST-CONFIG-5G-5#5G-5",
    ],
}

# کدهای تخفیف
DISCOUNTS = {
    "OFF30": {"percent": 30, "active": True}
}

# متن‌ها و دکمه‌های ثابت (دقیقاً طبق خواسته شما)
BTN_SHOP = "فروشگاه 🛍"
BTN_WALLET = "کیف پول 💳"
BTN_MY_CONFIGS = "کانفیگ‌های من 📄"
BTN_SUPPORT = "پشتیبانی 📰"
BTN_PROFILE = "پروفایل من 👤"
BTN_TUTORIAL = "آموزش 📚"
BTN_ADMIN = "پنل ادمین ⚒"

BTN_APPLY_CODE = "اعمال کد تخفیف 🎟"
BTN_CARD2CARD = "کارت به کارت 🏦"
BTN_PAY_WALLET = "پرداخت از کیف پول 💼"
BTN_BACK = "بازگشت ⤴️"
BTN_CANCEL = "انصراف ❌"
BTN_PAY_DIFF = "پرداخت مابه‌التفاوت 💸"

SUPPORT_TEXT = (
    "🍀 ارتباط با پشتیبانی:\n"
    "• آیدی: @your_support\n"
    "• اگر سوالی داشتی همینجا بپرس، هوامو داریم! ✌️"
)

TUTORIAL_TEXT = (
    "📚 آموزش قدم‌به‌قدم استفاده از بات:\n\n"
    "1) از منوی پایین «فروشگاه 🛍» رو بزن.\n"
    "2) از بین پلن‌ها، هر کدوم موجودی داشت انتخاب کن.\n"
    "3) جزییات پلن رو می‌بینی؛ می‌تونی «اعمال کد تخفیف 🎟» بزنی.\n"
    "4) روش پرداختت رو انتخاب کن: «کارت به کارت 🏦» یا «پرداخت از کیف پول 💼».\n"
    "5) اگه کارت‌به‌کارت کردی، رسید رو به‌صورت عکس یا متن بفرست.\n"
    "6) رسید مستقیم برای ادمین میره؛ بعد از تایید، کانفیگ آماده‌ات ارسال میشه 😍\n"
    "7) تو بخش «کانفیگ‌های من 📄» همه کانفیگ‌هایی که خریدی رو همیشه داری.\n"
    "8) «کیف پول 💳» هم برای پرداخت سریع‌ و افزایش موجودی‌ت کنارته.\n\n"
    "هرجایی گیر کردی «انصراف ❌» یا «بازگشت ⤴️» رو بزن برگردی عقب 😉"
)

WELCOME_TEXT = (
    "سلام رفیق! 👋\n"
    "به بات فروشگاه ما خوش اومدی 😍\n\n"
    "اینجا می‌تونی خیلی ساده و خوشگل، پلن مناسب خودت رو پیدا کنی، "
    "با کد تخفیف خرید کنی، از کیف پولت پرداخت کنی یا کارت‌به‌کارت بزنی و رسیدش رو بفرستی؛ "
    "ادمین‌ها سریع بررسی می‌کنن و همون‌جا کانفیگ آماده‌ استفاده برات میاد ✨\n\n"
    f"نسخه بات: {BOT_VERSION}\n"
    "برای شروع از منوی پایین یکی از گزینه‌ها رو انتخاب کن 👇"
)

CARD_NUMBER = "6037-9911-2233-4455"  # کارت ثابت نمونه جهت تست

# ---------------------- توابع کمکی ----------------------
def is_admin(user_id: int) -> bool:
    if ADMIN_ID and user_id == ADMIN_ID:
        return True
    # اگر ADMIN_ID صفر بود، اولین استارت به عنوان ادمین ذخیره می‌شود
    if USERS.get(user_id, {}).get("is_admin"):
        return True
    return False

def ensure_user(tg: TGUser) -> Dict[str, Any]:
    """ثبت یا بازیابی کاربر از حافظه."""
    u = USERS.get(tg.id)
    if not u:
        u = {
            "id": tg.id,
            "username": tg.username or "-",
            "first_name": tg.first_name or "",
            "wallet": 0,
            "configs": [],
            "session": {},
            "is_admin": False,
        }
        USERS[tg.id] = u
        # اگر هنوز ادمین تعیین نشده، اولین استارت ادمین می‌شود
        global ADMIN_ID
        if ADMIN_ID == 0:
            u["is_admin"] = True
            ADMIN_ID = tg.id
            log.info("First /start -> set ADMIN_ID=%s", ADMIN_ID)
        # موجودی اولیه ادمین برای تست
        if is_admin(tg.id):
            u["wallet"] = 50000
    return u

def build_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(BTN_SHOP), KeyboardButton(BTN_WALLET)],
        [KeyboardButton(BTN_MY_CONFIGS), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_PROFILE)],
        [KeyboardButton(BTN_TUTORIAL)],
    ]
    if is_admin(user_id):
        rows.append([KeyboardButton(BTN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    for p in PLANS:
        if p["id"] == plan_id:
            return p
    return None

def list_available_plans() -> List[Dict[str, Any]]:
    return [p for p in PLANS if p["stock"] > 0 and len(CONFIG_REPO.get(p["id"], [])) > 0]

def format_currency(amount: int) -> str:
    return f"{amount:,} تومان"

def plan_detail_text(p: Dict[str, Any], final_price: Optional[int] = None) -> str:
    price = final_price if final_price is not None else p["price"]
    return (
        f"{p['title']}\n"
        f"⌛ مدت: {p['days']} روز\n"
        f"📶 ترافیک: {p['traffic_gb']}\n"
        f"💲 قیمت: {format_currency(price)}\n"
        f"📦 موجودی مخزن: {p['stock']}"
    )

def plan_inline_kb(plan_id: str, with_back: bool = True) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(BTN_APPLY_CODE, callback_data=f"applycode:{plan_id}")],
        [InlineKeyboardButton(BTN_CARD2CARD, callback_data=f"c2c:{plan_id}")],
        [InlineKeyboardButton(BTN_PAY_WALLET, callback_data=f"paywallet:{plan_id}")],
    ]
    row = []
    if with_back:
        row.append(InlineKeyboardButton(BTN_BACK, callback_data="back_to_plans"))
    row.append(InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_all"))
    buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def shop_menu_kb() -> InlineKeyboardMarkup:
    items = list_available_plans()
    buttons = []
    for p in items:
        label = f"{p['title']} — {format_currency(p['price'])}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"plan:{p['id']}")])
    buttons.append([InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_all")])
    return InlineKeyboardMarkup(buttons)

async def send_config(u: Dict[str, Any], plan: Dict[str, Any], context: ContextTypes.DEFAULT_TYPE) -> bool:
    """تحویل کانفیگ از مخزن و بروزرسانی موجودی پلن."""
    repo = CONFIG_REPO.get(plan["id"], [])
    if not repo:
        return False
    cfg = repo.pop(0)  # بردار و حذف کن
    plan["stock"] = max(0, plan["stock"] - 1)

    u["configs"].append({"plan_id": plan["id"], "config": cfg})
    msg = (
        "🎉 تبریک! خریدت نهایی شد و کانفیگ آماده‌است.\n"
        "🔗 کانفیگت:\n"
        f"```\n{cfg}\n```"
    )
    await context.bot.send_message(chat_id=u["id"], text=msg, parse_mode="Markdown")
    return True

def new_receipt_id() -> str:
    global RECEIPT_SEQ
    rid = f"R{RECEIPT_SEQ:06d}"
    RECEIPT_SEQ += 1
    return rid

# ---------------------- هندلرها ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    u = ensure_user(tg)
    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=build_main_keyboard(u["id"]),
    )

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    u = ensure_user(tg)
    txt = (update.message.text or "").strip()

    # حالت واردکردن کد تخفیف
    if u["session"].get("awaiting_coupon"):
        code = txt.upper()
        u["session"]["awaiting_coupon"] = False
        sel = u["session"].get("selected_plan")
        if not sel:
            await update.message.reply_text("خب برگشتیم به فروشگاه 😉", reply_markup=build_main_keyboard(u["id"]))
            return
        p = get_plan(sel["id"])
        if not p:
            await update.message.reply_text("پلن پیدا نشد!", reply_markup=build_main_keyboard(u["id"]))
            return

        if code in DISCOUNTS and DISCOUNTS[code]["active"]:
            if sel.get("coupon_used"):
                await update.message.reply_text("🎟 این کد قبلاً اعمال شده بود رفیق!")
            else:
                percent = DISCOUNTS[code]["percent"]
                new_price = int(p["price"] * (100 - percent) / 100)
                sel["final_price"] = new_price
                sel["coupon_used"] = code
                await update.message.reply_text(
                    f"🎉 کد تخفیف معتبره! {percent}% اعمال شد.\n"
                    f"مبلغ جدید: {format_currency(new_price)}"
                )
        else:
            await update.message.reply_text("❌ کد تخفیف نامعتبره. دوباره تلاش کن یا بدون کد ادامه بده.")

        # نمایش دوباره جزییات
        final_price = u["session"]["selected_plan"].get("final_price")
        await context.bot.send_message(
            chat_id=u["id"],
            text=plan_detail_text(p, final_price=final_price),
            reply_markup=plan_inline_kb(p["id"]),
        )
        return

    # حالت انتظار رسید
    if u["session"].get("awaiting_receipt"):
        pending = u["session"]["awaiting_receipt"]  # {'rid', 'type', 'amount', 'plan_id'?, ...}
        rid = pending["rid"]

        # ذخیره پیام کاربر داخل رفرنس رسید
        PENDING_RECEIPTS[rid]["user_message_id"] = update.message.message_id

        # ارسال برای ادمین‌ها (بدون دستکاری رسید)
        admins = [ADMIN_ID] if ADMIN_ID else []
        caption = (
            f"🧾 رسید جدید ({rid})\n"
            f"از: @{u['username']} | {u['id']}\n"
            f"نوع: {pending['type']}\n"
            f"مبلغ: {format_currency(pending['amount'])}\n"
        )
        if pending.get("plan_id"):
            p = get_plan(pending["plan_id"])
            if p:
                caption += f"پلن: {p['title']}\n"

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("تایید ✅", callback_data=f"rcpt:approve:{rid}"),
                InlineKeyboardButton("رد ❌", callback_data=f"rcpt:reject:{rid}")
            ]
        ])

        for admin_chat in admins:
            try:
                # کپی خود پیام (عکس/متن) برای ادمین، بدون دستکاری
                if update.message.photo:
                    # آخرین سایز با کیفیت‌تر است
                    photo = update.message.photo[-1].file_id
                    await context.bot.send_photo(
                        chat_id=admin_chat,
                        photo=photo,
                        caption=caption,
                        reply_markup=kb
                    )
                else:
                    await context.bot.send_message(
                        chat_id=admin_chat,
                        text=caption + "\n" + (update.message.text or ""),
                        reply_markup=kb
                    )
            except Exception as e:
                log.warning("send to admin failed: %s", e)

        await update.message.reply_text(
            "✅ رسیدت رسید! مرسی 🙏\n"
            "ادمین بررسی می‌کنه؛ نتیجه رو همینجا خبرت می‌کنیم 👌"
        )
        u["session"].pop("awaiting_receipt", None)
        return

    # منوی اصلی
    if txt == BTN_SHOP:
        items = list_available_plans()
        if not items:
            await update.message.reply_text("فعلاً موجودی پلن‌ها خالیه 😅")
            return
        await update.message.reply_text("لطفاً پلن موردنظر را انتخاب کنید:\nفهرست پلن‌ها:", reply_markup=build_main_keyboard(u["id"]))
        await update.message.reply_text(" ", reply_markup=shop_menu_kb())
        return

    if txt == BTN_WALLET:
        await update.message.reply_text(
            f"💳 موجودی کیف پول: {format_currency(u['wallet'])}\n\n"
            "می‌تونی با «کارت به کارت 🏦» افزایش بدی؛ رسید رو که فرستادی ادمین تایید می‌کنه.",
            reply_markup=build_main_keyboard(u["id"])
        )
        # دکمه‌ افزایش موجودی با ارسال رسید
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("افزایش موجودی (کارت‌به‌کارت) 🏦", callback_data="topup")],
            [InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_all")]
        ])
        await update.message.reply_text("چیکار کنیم؟", reply_markup=kb)
        return

    if txt == BTN_MY_CONFIGS:
        if not u["configs"]:
            await update.message.reply_text("هنوز کانفیگی نخریدی 🤏 از «فروشگاه 🛍» شروع کن.")
        else:
            text = "📄 کانفیگ‌های من:\n\n"
            for i, c in enumerate(u["configs"], 1):
                text += f"{i}) `{c['config']}`\n\n"
            await update.message.reply_text(text, parse_mode="Markdown")
        return

    if txt == BTN_SUPPORT:
        await update.message.reply_text(SUPPORT_TEXT)
        return

    if txt == BTN_PROFILE:
        await update.message.reply_text(
            f"👤 پروفایل من:\n"
            f"نام: {u['first_name']}\n"
            f"یوزرنیم: @{u['username']}\n"
            f"آیدی عددی: {u['id']}\n"
            f"موجودی کیف پول: {format_currency(u['wallet'])}\n"
            f"تعداد کانفیگ‌ها: {len(u['configs'])}\n"
            f"نقش: {'ادمین' if is_admin(u['id']) else 'کاربر'}",
        )
        return

    if txt == BTN_TUTORIAL:
        await update.message.reply_text(TUTORIAL_TEXT)
        return

    if txt == BTN_ADMIN:
        if not is_admin(u["id"]):
            await update.message.reply_text("به نظر ادمین نیستی رفیق 🙃")
            return
        # پنل ساده برای ادمین
        ptext = "⚒ پنل ادمین:\n"
        for p in PLANS:
            ptext += f"• {p['title']} | قیمت: {format_currency(p['price'])} | موجودی: {p['stock']} | مخزن: {len(CONFIG_REPO.get(p['id'], []))}\n"
        ptext += f"\n👥 کاربران ثبت‌شده: {len(USERS)}\n"
        await update.message.reply_text(ptext)
        return

    # اگر هیچ‌کدام نبود:
    await update.message.reply_text("از منوی پایین یکی رو بزن رفیق 😉")

# ---------------------- کال‌بک‌های اینلاین ----------------------
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg = update.effective_user
    u = ensure_user(tg)
    data = query.data

    if data == "back_to_plans":
        await query.message.edit_text("برگشتیم به لیست پلن‌ها 👇", reply_markup=shop_menu_kb())
        return

    if data == "cancel_all":
        u["session"].clear()
        await query.message.edit_text("لغو شد ✅ هر وقت خواستی از «فروشگاه 🛍» ادامه بده.")
        return

    if data.startswith("plan:"):
        pid = data.split(":", 1)[1]
        p = get_plan(pid)
        if not p or p["stock"] <= 0 or len(CONFIG_REPO.get(pid, [])) == 0:
            await query.message.edit_text("این پلن فعلاً موجود نیست 😕")
            return
        # انتخاب پلن در سشن
        u["session"]["selected_plan"] = {"id": pid, "final_price": p["price"]}
        await query.message.edit_text(
            plan_detail_text(p, final_price=p["price"]),
            reply_markup=plan_inline_kb(pid),
        )
        return

    if data.startswith("applycode:"):
        pid = data.split(":", 1)[1]
        sel = u["session"].get("selected_plan")
        if not sel or sel["id"] != pid:
            await query.message.reply_text("اول از لیست، پلن رو انتخاب کن 😉")
            return
        u["session"]["awaiting_coupon"] = True
        await query.message.reply_text("کد تخفیفت رو بفرست 🌟 (مثلاً OFF30)")
        return

    if data.startswith("paywallet:"):
        pid = data.split(":", 1)[1]
        p = get_plan(pid)
        if not p:
            await query.message.reply_text("پلن پیدا نشد!")
            return
        sel = u["session"].get("selected_plan") or {"final_price": p["price"], "id": pid}
        price = sel.get("final_price", p["price"])
        if u["wallet"] >= price:
            # کم کن و ارسال کانفیگ
            u["wallet"] -= price
            ok = await send_config(u, p, context)
            if ok:
                await query.message.edit_text("پرداخت از کیف پول با موفقیت انجام شد ✅")
            else:
                await query.message.edit_text("مخزن خالیه، بعداً دوباره امتحان کن 😕")
        else:
            diff = price - u["wallet"]
            await query.message.edit_text(
                f"موجودی کیف پولت کمه 😅\n"
                f"💳 موجودی: {format_currency(u['wallet'])}\n"
                f"💸 مابه‌التفاوت: {format_currency(diff)}\n"
                "میخوای مابه‌التفاوت رو کارت‌به‌کارت کنی؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(BTN_PAY_DIFF, callback_data=f"paydiff:{pid}:{diff}")],
                    [InlineKeyboardButton(BTN_BACK, callback_data="back_to_plans"),
                     InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_all")]
                ])
            )
        return

    if data.startswith("paydiff:"):
        _, pid, diff_str = data.split(":")
        diff = int(diff_str)
        # درخواست رسید
        rid = new_receipt_id()
        PENDING_RECEIPTS[rid] = {
            "user_id": u["id"],
            "type": "مابه‌التفاوت",
            "amount": diff,
            "plan_id": pid,
            "status": "pending",
        }
        u["session"]["awaiting_receipt"] = {"rid": rid, "type": "مابه‌التفاوت", "amount": diff, "plan_id": pid}
        await query.message.edit_text(
            f"لطفاً مبلغ مابه‌التفاوت {format_currency(diff)} را به کارت زیر واریز کن و رسید را (عکس یا متن) بفرست 🙏\n"
            f"🔢 شماره کارت: {CARD_NUMBER}"
        )
        return

    if data.startswith("c2c:"):
        pid = data.split(":", 1)[1]
        sel = u["session"].get("selected_plan")
        p = get_plan(pid)
        if not p:
            await query.message.reply_text("پلن پیدا نشد!")
            return
        price = (sel or {}).get("final_price", p["price"])
        rid = new_receipt_id()
        PENDING_RECEIPTS[rid] = {
            "user_id": u["id"],
            "type": "کارت به کارت",
            "amount": price,
            "plan_id": pid,
            "status": "pending",
        }
        u["session"]["awaiting_receipt"] = {"rid": rid, "type": "کارت به کارت", "amount": price, "plan_id": pid}
        await query.message.edit_text(
            f"لطفاً مبلغ {format_currency(price)} را به کارت زیر واریز کن و رسید را (عکس یا متن) همینجا بفرست 🙏\n"
            f"🔢 شماره کارت: {CARD_NUMBER}"
        )
        return

    if data == "topup":
        # افزایش موجودی کیف پول
        rid = new_receipt_id()
        amt = 50000  # برای تست: کاربر هر چقدر خواست می‌تونه بفرسته؛ اینجا نمونه 50هزار
        PENDING_RECEIPTS[rid] = {
            "user_id": u["id"],
            "type": "افزایش موجودی کیف پول",
            "amount": amt,
            "status": "pending",
        }
        u["session"]["awaiting_receipt"] = {"rid": rid, "type": "افزایش موجودی کیف پول", "amount": amt}
        await query.message.edit_text(
            f"برای افزایش موجودی، مبلغ {format_currency(amt)} را کارت‌به‌کارت کن و رسید را بفرست 🙏\n"
            f"🔢 شماره کارت: {CARD_NUMBER}"
        )
        return

    # ادمین: تایید/رد رسید
    if data.startswith("rcpt:"):
        _, action, rid = data.split(":")
        rcpt = PENDING_RECEIPTS.get(rid)
        if not rcpt:
            await query.message.reply_text("رسید پیدا نشد.")
            return

        # همیشه دکمه‌ها باقی بمانند
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("تایید ✅", callback_data=f"rcpt:approve:{rid}"),
                InlineKeyboardButton("رد ❌", callback_data=f"rcpt:reject:{rid}")
            ]
        ])

        if action == "reject":
            rcpt["status"] = "rejected"
            await query.message.edit_text(query.message.text_html + "\n\n❌ وضعیت: رد شد", reply_markup=kb)
            # پیام مودبانه برای کاربر
            await context.bot.send_message(
                chat_id=rcpt["user_id"],
                text="متاسفیم! 🙏 رسیدت رد شد.\n"
                     "اگر ابهامی داری با پشتیبانی در ارتباط باش 🌟"
            )
            return

        if action == "approve":
            rcpt["status"] = "approved"
            await query.message.edit_text(query.message.text_html + "\n\n✅ وضعیت: تایید شد", reply_markup=kb)
            # اعمال نتیجه برای کاربر
            u2 = USERS.get(rcpt["user_id"])
            if not u2:
                return

            if rcpt["type"] == "افزایش موجودی کیف پول":
                u2["wallet"] += rcpt["amount"]
                await context.bot.send_message(
                    chat_id=u2["id"],
                    text=f"✅ افزایش موجودی تایید شد! موجودی جدید: {format_currency(u2['wallet'])}"
                )
                return

            if rcpt["type"] in ("کارت به کارت", "مابه‌التفاوت"):
                p = get_plan(rcpt.get("plan_id", ""))
                if not p:
                    await context.bot.send_message(chat_id=u2["id"], text="پلن پیدا نشد!")
                    return
                ok = await send_config(u2, p, context)
                if not ok:
                    await context.bot.send_message(chat_id=u2["id"], text="متاسفانه مخزن خالیه، به‌زودی شارژ میشه 🙏")
                return

# ---------------------- هندلر رسانه برای رسید ----------------------
async def receipt_media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    u = ensure_user(tg)
    if not u["session"].get("awaiting_receipt"):
        return  # رسانه مرتبط با رسید نیست
    # ادامه‌ی رسید در text_router هندل می‌شود؛ اینجا فقط پاس می‌دیم به همون
    await text_router(update, context)

# ---------------------- FastAPI + Webhook ----------------------
app = FastAPI(title="Telegram Shop Bot", version=BOT_VERSION)

application: Application = ApplicationBuilder().token(TOKEN).build()

@app.on_event("startup")
async def on_startup():
    # طبق تجربه خطای initialize را می‌گیریم اگر این دو مرحله نباشند
    await application.initialize()
    # ست وبهوک به /webhook
    base_url = os.getenv("WEBHOOK_BASE", "").rstrip("/")
    if base_url:
        await application.bot.set_webhook(url=f"{base_url}/webhook")
        log.info("✅ Webhook set to: %s/webhook", base_url)
    await application.start()

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()

# مسیر سلامت
@app.get("/", response_class=PlainTextResponse)
async def root():
    return f"OK - Bot v{BOT_VERSION}"

# مسیر وبهوک
@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return PlainTextResponse("OK")

# ---------------------- ثبت هندلرهای تلگرام ----------------------
application.add_handler(CommandHandler("start", start))

# پیام‌های متنی و دکمه‌های Reply Keyboard
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

# دریافت عکس/فایل/رسید
application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, receipt_media_router))

# کال‌بک‌های اینلاین
application.add_handler(CallbackQueryHandler(callbacks))
