# -*- coding: utf-8 -*-
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List

from fastapi import FastAPI, Request
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import RetryAfter

# =========================
# تنظیمات پایه
# =========================
VERSION = "1.0.3"

# توکن و ادمین از env (خودکار)
TOKEN = os.getenv("BOT_TOKEN", "توکن_اینجا")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
# آدرس سرور برای وبهوک
WEBHOOK_BASE_URL = os.getenv(
    "WEBHOOK_BASE_URL",
    "https://live-avivah-bardiabsd-cd8d676a.koyeb.app",
).rstrip("/")

WEBHOOK_URL = f"{WEBHOOK_BASE_URL}/webhook"

# لاگینگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# =========================
# داده‌های تستی و وضعیت‌ها
# =========================

# کیف پول‌ها (پیش‌فرض: ادمین 50,000)
wallets: Dict[int, int] = {ADMIN_ID: 50000}

# پلن‌ها
plans = {
    1: {"id": 1, "name": "🌐 پلن 1 ماهه", "price": 10000},
    2: {"id": 2, "name": "🚀 پلن 3 ماهه", "price": 25000},
    3: {"id": 3, "name": "🔥 پلن 6 ماهه", "price": 40000},
}

# مخزن کانفیگ‌ها (برای هر پلن چند نمونه)
inventory: Dict[int, List[str]] = {
    1: [
        "vless://sample-config-1m-AAA",
        "vless://sample-config-1m-BBB",
        "vless://sample-config-1m-CCC",
    ],
    2: [
        "vless://sample-config-3m-AAA",
        "vless://sample-config-3m-BBB",
    ],
    3: [
        "vless://sample-config-6m-AAA",
        "vless://sample-config-6m-BBB",
        "vless://sample-config-6m-CCC",
        "vless://sample-config-6m-DDD",
    ],
}

# کدهای تخفیف
discount_codes: Dict[str, int] = {
    "OFF30": 30,  # درصد
}

# وضعیت کاربران
# user_states[user_id] = {
#   'stage': 'selecting_plan' | 'plan_detail' | 'awaiting_discount_code'
#            | 'awaiting_receipt' | 'confirm_wallet_diff'
#   'plan_id': int,
#   'discount_percent': int,
#   'final_price': int,
#   'pending_payment_type': 'card' | 'wallet_diff',
#   'wallet_to_use': int,   (فقط در مابه‌التفاوت)
#   'diff_amount': int      (فقط در مابه‌التفاوت)
# }
user_states: Dict[int, Dict[str, Any]] = {}

# رسیدهای در انتظار تصمیم ادمین
# pending_receipts[receipt_id] = {...}
pending_receipts: Dict[str, Dict[str, Any]] = {}


# =========================
# کمک‌تابع‌ها
# =========================
def format_toman(n: int) -> str:
    return f"{n:,} تومان".replace(",", "٬")


def calc_discounted_price(price: int, percent: int) -> int:
    return max(0, (price * (100 - percent)) // 100)


def plan_available(plan_id: int) -> bool:
    lst = inventory.get(plan_id, [])
    return len(lst) > 0


def get_plan(plan_id: int) -> Dict[str, Any]:
    return plans.get(plan_id)


def build_main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🛒 خرید کانفیگ", callback_data="buy_config")],
        [InlineKeyboardButton("👛 کیف پول من", callback_data="wallet")],
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ پنل ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)


def build_plans_menu() -> InlineKeyboardMarkup:
    keyboard = []
    for pid, p in plans.items():
        status = "✅ موجود" if plan_available(pid) else "⛔️ ناموجود"
        keyboard.append([
            InlineKeyboardButton(
                f"{p['name']} - {format_toman(p['price'])} | {status}",
                callback_data=f"plan_{pid}"
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel_buy")])
    return InlineKeyboardMarkup(keyboard)


def build_plan_detail_menu(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 کارت به کارت", callback_data=f"pay_card_{plan_id}")],
        [InlineKeyboardButton("💸 پرداخت از کیف پول", callback_data=f"pay_wallet_{plan_id}")],
        [InlineKeyboardButton("🎟 اعمال کد تخفیف", callback_data=f"discount_{plan_id}")],
        [InlineKeyboardButton("↩️ برگشت به لیست پلن‌ها", callback_data="buy_config")],
    ])


def build_admin_receipt_keyboard(receipt_id: str) -> InlineKeyboardMarkup:
    # دکمه‌ها همیشه فعال می‌مونن (نابود/خاموش نمی‌شن)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"approve_{receipt_id}"),
            InlineKeyboardButton("⛔️ رد", callback_data=f"reject_{receipt_id}"),
        ]
    ])


# =========================
# FastAPI و تلگرام
# =========================
app = FastAPI(title="Telegram Bot Backend", version=VERSION)
telegram_app: Application = Application.builder().token(TOKEN).build()


@app.on_event("startup")
async def on_startup():
    # هندلرها را ثبت می‌کنیم
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(handle_callback))
    telegram_app.add_handler(MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), handle_message))

    # حتماً initialize → start → set_webhook
    await telegram_app.initialize()
    await telegram_app.start()

    # تنظیم وبهوک (با کنترل 429)
    try:
        await telegram_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
        logger.info(f"✅ Webhook set to: {WEBHOOK_URL}")
    except RetryAfter as e:
        # اگر تلگرام گفت صبر کن، یه بار صبر و تلاش مجدد
        wait_sec = int(getattr(e, "retry_after", 1))
        logger.warning(f"⚠️ Flood control on set_webhook. Retry in {wait_sec}s")
        await asyncio.sleep(wait_sec)
        try:
            await telegram_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
            logger.info(f"✅ Webhook set to: {WEBHOOK_URL}")
        except Exception as ex:
            logger.error(f"❌ Failed to set webhook after retry: {ex}")

    logger.info("🚀 Application startup complete.")


@app.on_event("shutdown")
async def on_shutdown():
    try:
        await telegram_app.stop()
    finally:
        await telegram_app.shutdown()
    logger.info("👋 Application shutdown complete.")


@app.get("/")
async def root():
    return {"ok": True, "version": VERSION, "message": "Bot backend is running 🚀"}


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    try:
        update = Update.de_json(data=data, bot=telegram_app.bot)
        await telegram_app.process_update(update)
    except Exception as e:
        logger.exception(f"Error processing update: {e}")
    return {"ok": True}


# =========================
# هندلرهای ربات
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # منوی اصلی – ادمین فقط خودش دکمه پنل رو می‌بینه
    is_admin = (update.effective_user.id == ADMIN_ID)
    await update.message.reply_text(
        f"سلام 👋 به ربات خوش اومدی!\nنسخه: {VERSION}",
        reply_markup=build_main_menu(is_admin),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    uname = (query.from_user.username or "—")
    await query.answer()

    data = query.data or ""

    # منوها
    if data == "buy_config":
        user_states[uid] = {
            "stage": "selecting_plan",
            "discount_percent": user_states.get(uid, {}).get("discount_percent", 0),
        }
        await query.edit_message_text("📋 لیست پلن‌ها:", reply_markup=build_plans_menu())
        return

    if data == "cancel_buy":
        # برگشت به منوی اصلی
        is_admin = (uid == ADMIN_ID)
        user_states.pop(uid, None)
        await query.edit_message_text("✅ عملیات لغو شد.", reply_markup=build_main_menu(is_admin))
        return

    if data == "wallet":
        bal = wallets.get(uid, 0)
        await query.edit_message_text(f"👛 موجودی کیف پول شما: {format_toman(bal)}")
        return

    if data == "admin_panel":
        if uid != ADMIN_ID:
            await query.answer("دسترسی ادمین لازم است.", show_alert=True)
            return
        await query.edit_message_text("⚙️ خوش اومدی به پنل ادمین 👑")
        return

    # انتخاب پلن
    if data.startswith("plan_"):
        try:
            pid = int(data.split("_")[1])
        except Exception:
            await query.answer("پلن نامعتبر!", show_alert=True)
            return
        p = get_plan(pid)
        if not p:
            await query.edit_message_text("❌ پلن یافت نشد.")
            return

        if not plan_available(pid):
            # ناموجود
            await query.edit_message_text(
                f"⛔️ متاسفانه {p['name']} الان ناموجوده.\n"
                "یه کم دیگه سر بزن یا یه پلن دیگه رو انتخاب کن 🌟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ برگشت به لیست پلن‌ها", callback_data="buy_config")]
                ]),
            )
            return

        # ذخیره وضعیت
        st = user_states.get(uid, {})
        st.update({
            "stage": "plan_detail",
            "plan_id": pid,
            "discount_percent": st.get("discount_percent", 0),
        })
        final_price = calc_discounted_price(p["price"], st["discount_percent"])
        st["final_price"] = final_price
        user_states[uid] = st

        text = (
            f"📌 نام پلن: {p['name']}\n"
            f"💰 قیمت: {format_toman(p['price'])}\n"
            f"🎁 تخفیف اعمال‌شده: {st['discount_percent']}٪\n"
            f"📉 مبلغ نهایی: {format_toman(final_price)}"
        )
        await query.edit_message_text(text, reply_markup=build_plan_detail_menu(pid))
        return

    # کد تخفیف
    if data.startswith("discount_"):
        pid = int(data.split("_")[1])
        st = user_states.get(uid, {})
        st.update({"stage": "awaiting_discount_code", "plan_id": pid})
        user_states[uid] = st
        await query.edit_message_text(
            "🎟 لطفاً کد تخفیفت رو بفرست 🌈\n"
            "مثال: OFF30\n\n"
            "برای برگشت: /cancel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ برگشت به جزئیات پلن", callback_data=f"plan_{pid}")],
                [InlineKeyboardButton("↩️ برگشت به لیست پلن‌ها", callback_data="buy_config")],
            ]),
        )
        return

    # پرداخت از کیف پول
    if data.startswith("pay_wallet_"):
        pid = int(data.split("_")[2])
        p = get_plan(pid)
        if not p:
            await query.edit_message_text("❌ پلن یافت نشد.")
            return
        if not plan_available(pid):
            await query.edit_message_text(
                "⛔️ الان موجود نیست. یه پلن دیگه رو امتحان کن لطفاً 🤝",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ برگشت به لیست پلن‌ها", callback_data="buy_config")]
                ])
            )
            return

        st = user_states.get(uid, {})
        disc = st.get("discount_percent", 0)
        final_price = calc_discounted_price(p["price"], disc)
        st["final_price"] = final_price
        st["plan_id"] = pid
        user_states[uid] = st

        bal = wallets.get(uid, 0)
        if bal >= final_price:
            # پرداخت کامل از کیف پول
            wallets[uid] = bal - final_price
            # ارسال کانفیگ
            cfg_list = inventory.get(pid, [])
            if not cfg_list:
                await query.edit_message_text(
                    "⛔️ متاسفانه موجودی مخزن همین الان تموم شد! مبلغ از کیف پول کم نشد.\n"
                    "دوباره تلاش کن یا با پشتیبانی در تماس باش 🌟",
                    reply_markup=build_plans_menu()
                )
                # برگردونیم؟ (در نمونه: کم نکردیم تا اینجارو نرسه چون قبلش چک کردیم)
                return

            config_str = cfg_list.pop(0)
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    "🎉 تبریک! خریدت با کیف پول انجام شد.\n"
                    "این هم کانفیگت، راحت کُپی کن و استفاده کن 😎👇\n\n"
                    f"```\n{config_str}\n```"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            await query.edit_message_text(
                "✅ پرداخت با کیف پول انجام شد و کانفیگ برات ارسال شد.",
                reply_markup=build_main_menu(uid == ADMIN_ID),
            )
            return
        else:
            # مابه‌التفاوت
            diff = final_price - bal
            st.update({
                "stage": "confirm_wallet_diff",
                "pending_payment_type": "wallet_diff",
                "wallet_to_use": bal,
                "diff_amount": diff,
            })
            user_states[uid] = st
            await query.edit_message_text(
                f"👛 موجودی کیف پولت {format_toman(bal)} هست.\n"
                f"💸 مابه‌التفاوت میشه {format_toman(diff)}.\n\n"
                "میخوای مابه‌التفاوت رو کارت به کارت بدی؟ 😇",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ بزن بریم پرداخت مابه‌التفاوت", callback_data=f"confirm_diff_{pid}")],
                    [InlineKeyboardButton("❌ بی‌خیال، برگرد", callback_data=f"plan_{pid}")],
                ])
            )
            return

    if data.startswith("confirm_diff_"):
        pid = int(data.split("_")[2])
        st = user_states.get(uid, {})
        if st.get("stage") != "confirm_wallet_diff":
            await query.answer("الان در مرحله پرداخت مابه‌التفاوت نیستی.", show_alert=True)
            return
        diff_amount = st.get("diff_amount", 0)
        # ورود به مرحله دریافت رسید
        st["stage"] = "awaiting_receipt"
        st["pending_payment_type"] = "wallet_diff"
        user_states[uid] = st

        await query.edit_message_text(
            "🙏 لطفاً این مبلغ رو کارت به کارت کن و **رسید** رو (عکس یا متن) همینجا بفرست.\n"
            f"💳 مبلغ: {format_toman(diff_amount)}\n"
            "شماره کارت: ۶۲۷۴-۱۲۳۴-۵۶۷۸-۹۰۱۲\n"
            "بعد از ارسال رسید، سریع چک می‌کنیم ✅",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data=f"plan_{pid}")]
            ]),
        )
        return

    # کارت به کارت مستقیم
    if data.startswith("pay_card_"):
        pid = int(data.split("_")[2])
        p = get_plan(pid)
        if not p:
            await query.edit_message_text("❌ پلن یافت نشد.")
            return
        if not plan_available(pid):
            await query.edit_message_text(
                "⛔️ الان موجود نیست. یه پلن دیگه رو امتحان کن لطفاً 🤝",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ برگشت به لیست پلن‌ها", callback_data="buy_config")]
                ])
            )
            return

        st = user_states.get(uid, {})
        disc = st.get("discount_percent", 0)
        final_price = calc_discounted_price(p["price"], disc)
        st.update({
            "stage": "awaiting_receipt",
            "plan_id": pid,
            "final_price": final_price,
            "pending_payment_type": "card",
        })
        user_states[uid] = st

        await query.edit_message_text(
            "مرسی 🙏 لطفاً مبلغ رو کارت به کارت کن و **رسید** رو (عکس یا متن) همینجا بفرست.\n"
            f"💳 مبلغ: {format_toman(final_price)}\n"
            "شماره کارت: ۶۲۷۴-۱۲۳۴-۵۶۷۸-۹۰۱۲\n"
            "به محض دریافت رسید، تایید می‌کنیم ✅",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data=f"plan_{pid}")]
            ]),
        )
        return

    # ادمین: تایید/رد رسید
    if data.startswith("approve_") or data.startswith("reject_"):
        if uid != ADMIN_ID:
            await query.answer("فقط ادمین می‌تونه این کار رو انجام بده.", show_alert=True)
            return
        action, receipt_id = data.split("_", 1)
        rec = pending_receipts.get(receipt_id)
        if not rec:
            await query.answer("این رسید پیدا نشد یا قبلاً رسیدگی شده.", show_alert=True)
            return

        # با توجه به خواسته شما، دکمه‌ها خاموش/حذف نمی‌شن.
        # ما فقط یک پیام وضعیت جداگانه می‌فرستیم.
        if action == "reject":
            # اطلاع به کاربر
            await context.bot.send_message(
                chat_id=rec["user_id"],
                text="😕 رسید پرداختت رد شد. اگر ابهامی هست با پشتیبانی در تماس باش لطفاً 💬",
            )
            await query.message.reply_text(
                f"❌ رسید {receipt_id} رد شد.",
                reply_markup=build_admin_receipt_keyboard(receipt_id),
            )
            return

        if action == "approve":
            # تایید: اگر wallet_diff بود، از کیف پول به میزان wallet_to_use کم کنیم
            plan_id = rec["plan_id"]
            pending_type = rec["payment_type"]
            wallet_to_use = rec.get("wallet_to_use", 0)
            user_id = rec["user_id"]

            # کم کردن کیف پول در حالت مابه‌التفاوت
            if pending_type == "wallet_diff" and wallet_to_use > 0:
                current = wallets.get(user_id, 0)
                # اگر هنوز کم نشده، همین الان کم می‌کنیم
                # (در این فلو، فقط در تایید کم می‌کنیم تا اگر رد شد نیاز به برگشت نباشه)
                wallets[user_id] = max(0, current - wallet_to_use)

            # ارسال کانفیگ از مخزن
            cfg_list = inventory.get(plan_id, [])
            if not cfg_list:
                await query.message.reply_text(
                    f"⚠️ مخزن پلن {plan_id} خالیه! نتونستم کانفیگ بفرستم.",
                    reply_markup=build_admin_receipt_keyboard(receipt_id),
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ در حال حاضر موجودی کانفیگ برای این پلن تموم شده. پوزش 🙏 لطفاً با پشتیبانی در تماس باش."
                )
                return

            config_str = cfg_list.pop(0)

            # پیام تبریک به کاربر + کانفیگ قابل کپی
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🎉 تبریک! پرداختت تایید شد و این هم کانفیگت 😎👇\n\n"
                    f"```\n{config_str}\n```"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            await query.message.reply_text(
                f"✅ رسید {receipt_id} تایید شد و کانفیگ ارسال گردید.",
                reply_markup=build_admin_receipt_keyboard(receipt_id),
            )
            return

    # برگشت پیش‌فرض
    await query.answer()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسیدها و کد تخفیف را اینجا می‌گیریم."""
    if not update.effective_user:
        return
    uid = update.effective_user.id
    uname = update.effective_user.username or "—"
    st = user_states.get(uid, {})

    # لغو با /cancel
    if update.message and update.message.text and update.message.text.strip().lower() == "/cancel":
        is_admin = (uid == ADMIN_ID)
        user_states.pop(uid, None)
        await update.message.reply_text("✅ عملیات لغو شد.", reply_markup=build_main_menu(is_admin))
        return

    # کد تخفیف
    if st.get("stage") == "awaiting_discount_code":
        code = (update.message.text or "").strip()
        pid = st.get("plan_id")
        p = get_plan(pid) if pid else None
        if not p:
            await update.message.reply_text("❌ پلن نامعتبر. از نو امتحان کن.", reply_markup=build_plans_menu())
            return

        percent = discount_codes.get(code.upper(), None)
        if percent is None:
            await update.message.reply_text(
                "😅 کد تخفیف درست نبود عزیز.\n"
                "یه بار دیگه امتحان کن یا برگرد به جزئیات پلن.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ برگشت به جزئیات پلن", callback_data=f"plan_{pid}")],
                    [InlineKeyboardButton("↩️ برگشت به لیست پلن‌ها", callback_data="buy_config")],
                ]),
            )
            return

        st["discount_percent"] = int(percent)
        st["final_price"] = calc_discounted_price(p["price"], st["discount_percent"])
        st["stage"] = "plan_detail"
        user_states[uid] = st
        await update.message.reply_text(
            f"🎉 کدت اوکیه! {st['discount_percent']}٪ تخفیف خوردی.\n"
            f"📉 مبلغ نهایی: {format_toman(st['final_price'])}",
            reply_markup=build_plan_detail_menu(pid),
        )
        return

    # رسید پرداخت (عکس یا متن)
    if st.get("stage") == "awaiting_receipt":
        pid = st.get("plan_id")
        p = get_plan(pid) if pid else None
        if not p:
            await update.message.reply_text("❌ پلن نامعتبر. از نو امتحان کن.", reply_markup=build_plans_menu())
            return

        payment_type = st.get("pending_payment_type", "card")
        final_price = st.get("final_price", p["price"])
        wallet_to_use = st.get("wallet_to_use", 0)
        diff_amount = st.get("diff_amount", 0)

        # ساخت receipt_id یکتا
        ts = int(datetime.utcnow().timestamp())
        receipt_id = f"{uid}:{ts}"

        # آماده‌سازی محتوا برای ادمین
        caption = (
            f"🧾 رسید جدید دریافت شد\n"
            f"👤 کاربر: @{uname} | ID: {uid}\n"
            f"📦 پلن: {p['name']} (ID:{pid})\n"
            f"💳 نوع پرداخت: "
            f"{'کارت به کارت' if payment_type=='card' else 'مابه‌التفاوت کیف پول'}\n"
            f"🎁 تخفیف: {st.get('discount_percent', 0)}٪\n"
            f"💰 مبلغ نهایی: {format_toman(final_price)}\n"
            f"👛 کیف پول قابل استفاده: {format_toman(wallet_to_use)}\n"
            f"💸 مابه‌التفاوت: {format_toman(diff_amount)}\n"
            f"🕒 زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🧩 ReceiptID: {receipt_id}"
        )

        # ذخیره در pending_receipts
        pr = {
            "receipt_id": receipt_id,
            "user_id": uid,
            "username": uname,
            "plan_id": pid,
            "payment_type": payment_type,  # 'card' | 'wallet_diff' | 'wallet_topup'
            "discount_percent": st.get("discount_percent", 0),
            "final_price": final_price,
            "wallet_to_use": wallet_to_use,
            "diff_amount": diff_amount,
            "timestamp": ts,
        }

        pending_receipts[receipt_id] = pr

        # ارسال به ادمین (عکس یا متن)
        if update.message.photo:
            # بزرگ‌ترین سایز آخرین آیتم
            file_id = update.message.photo[-1].file_id
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=caption,
                reply_markup=build_admin_receipt_keyboard(receipt_id),
            )
        else:
            # متن رسید
            text_receipt = update.message.text or "—"
            caption += f"\n\n📝 متن رسید:\n{text_receipt}"
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=caption,
                reply_markup=build_admin_receipt_keyboard(receipt_id),
            )

        # اطلاع به کاربر
        await update.message.reply_text(
            "مرسی! 🙏 رسیدت دریافت شد و رفت برای بررسی ادمین.\n"
            "به محض تایید، کانفیگ برات میاد ✅"
        )

        # در همین مرحله می‌مونیم تا ادمین تایید/رد کنه
        return

    # اگر کاربر خارج از فلو پیام داد
    # چیزی تغییر نمی‌دیم و منوی اصلی رو می‌ذاریم
    if update.message and update.message.text:
        is_admin = (uid == ADMIN_ID)
        await update.message.reply_text(
            "منوی اصلی 👇",
            reply_markup=build_main_menu(is_admin),
        )


# ============ پایان فایل ============
