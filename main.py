import os
import logging
from datetime import datetime
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    InputFile
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ------------------ تنظیمات پایه ------------------
TOKEN = os.getenv("BOT_TOKEN", "توکن_بات_اینجا")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # آیدی عددی ادمین
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-app-url.koyeb.app")

# ------------------ دیتابیس ساده ------------------
users_wallet = {ADMIN_ID: 50000}  # موجودی تستی
discount_codes = {"OFF30": 30}  # کد تخفیف تستی
pending_receipts = {}  # ذخیره رسیدها
plans = {
    1: {"name": "پلن 1 ماهه", "price": 100000, "desc": "حجم نامحدود | سرعت بالا | 1 کاربر"},
    2: {"name": "پلن 3 ماهه", "price": 250000, "desc": "حجم نامحدود | سرعت بالا | 1 کاربر"},
    3: {"name": "پلن 6 ماهه", "price": 450000, "desc": "حجم نامحدود | سرعت بالا | 1 کاربر"},
}
config_repo = {
    1: ["config_1_month_1", "config_1_month_2"],
    2: ["config_3_month_1", "config_3_month_2"],
    3: ["config_6_month_1"],
}

# ------------------ لاگ ------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------ دستورات ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("🛒 خرید کانفیگ", callback_data="buy_config")],
        [InlineKeyboardButton("🎫 تیکت‌های من", callback_data="my_tickets")],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="profile")],
        [InlineKeyboardButton("📞 ارتباط با پشتیبانی", callback_data="support")],
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🛠 پنل ادمین", callback_data="admin_panel")])

    await update.message.reply_text("به ربات خوش اومدی! 👋", reply_markup=InlineKeyboardMarkup(keyboard))

# ------------------ خرید کانفیگ ------------------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # خرید کانفیگ
    if data == "buy_config":
        keyboard = [[InlineKeyboardButton(p["name"], callback_data=f"plan_{pid}")]
                    for pid, p in plans.items()]
        keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel_buy")])
        await query.edit_message_text("📋 لطفا یک پلن انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("plan_"):
        plan_id = int(data.split("_")[1])
        plan = plans[plan_id]
        text = f"📦 {plan['name']}\n💰 قیمت: {plan['price']} تومان\nℹ️ توضیحات: {plan['desc']}"
        keyboard = [
            [InlineKeyboardButton("💳 کارت به کارت", callback_data=f"pay_card_{plan_id}")],
            [InlineKeyboardButton("💰 کیف پول", callback_data=f"pay_wallet_{plan_id}")],
            [InlineKeyboardButton("🏷 کد تخفیف", callback_data=f"discount_{plan_id}")],
            [InlineKeyboardButton("❌ انصراف", callback_data="buy_config")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("pay_card_"):
        plan_id = int(data.split("_")[2])
        price = plans[plan_id]["price"]
        pending_receipts[user_id] = {"plan_id": plan_id, "price": price, "method": "کارت به کارت"}
        await query.edit_message_text(
            f"💳 لطفا مبلغ {price} تومان رو به شماره کارت 1234-5678-9012-3456 واریز کنید.\n\n"
            "بعد از پرداخت رسید رو (عکس یا متن) ارسال کنید."
        )

    elif data.startswith("pay_wallet_"):
        plan_id = int(data.split("_")[2])
        price = plans[plan_id]["price"]
        balance = users_wallet.get(user_id, 0)
        if balance >= price:
            users_wallet[user_id] = balance - price
            await send_config(user_id, plan_id, context)
            await query.edit_message_text("✅ خرید با کیف پول موفق بود! 🎉")
        else:
            diff = price - balance
            pending_receipts[user_id] = {"plan_id": plan_id, "price": diff, "method": "مابه تفاوت"}
            await query.edit_message_text(
                f"💸 موجودی کیف پولت کمه!\nباید {diff} تومان کارت به کارت کنی.\n"
                "لطفا رسید پرداخت رو ارسال کن."
            )

    elif data.startswith("discount_"):
        plan_id = int(data.split("_")[1])
        pending_receipts[user_id] = {"plan_id": plan_id, "method": "کد تخفیف"}
        await query.edit_message_text("🏷 لطفا کد تخفیف رو ارسال کنید:")

    elif data == "cancel_buy":
        await query.edit_message_text("❌ خرید لغو شد.")

# ------------------ رسید ------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pending_receipts:
        receipt = pending_receipts[user_id]
        msg_type = "عکس" if update.message.photo else "متن"
        content = update.message.caption if update.message.caption else update.message.text

        text = (
            f"📥 رسید جدید دریافت شد\n"
            f"👤 یوزرنیم: @{update.effective_user.username}\n"
            f"🆔 آیدی: {user_id}\n"
            f"📦 پلن: {plans[receipt['plan_id']]['name']}\n"
            f"💳 روش پرداخت: {receipt['method']}\n"
            f"📝 نوع رسید: {msg_type}\n"
            f"📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ تایید", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{user_id}")
            ]
        ]

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            await context.bot.send_photo(ADMIN_ID, file_id, caption=text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await context.bot.send_message(ADMIN_ID, text + f"\n📝 رسید: {content}", reply_markup=InlineKeyboardMarkup(keyboard))

        await update.message.reply_text("✅ رسیدت برای ادمین ارسال شد، لطفا منتظر بررسی باش 🌹")
        return

    # کد تخفیف
    if user_id in pending_receipts and pending_receipts[user_id].get("method") == "کد تخفیف":
        code = update.message.text.strip()
        receipt = pending_receipts[user_id]
        plan_id = receipt["plan_id"]
        if code in discount_codes:
            discount = discount_codes[code]
            price = plans[plan_id]["price"]
            new_price = price - (price * discount // 100)
            pending_receipts[user_id] = {"plan_id": plan_id, "price": new_price, "method": "تخفیف"}
            await update.message.reply_text(
                f"✅ کد تخفیف اعمال شد!\n💰 مبلغ جدید: {new_price} تومان\n\n"
                "حالا روش پرداخت رو انتخاب کن:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 کارت به کارت", callback_data=f"pay_card_{plan_id}")],
                    [InlineKeyboardButton("💰 کیف پول", callback_data=f"pay_wallet_{plan_id}")],
                    [InlineKeyboardButton("❌ انصراف", callback_data="buy_config")]
                ])
            )
        else:
            await update.message.reply_text("❌ کد تخفیف نامعتبره! لطفا دوباره تلاش کن.")

# ------------------ تایید / رد رسید ------------------
async def approve_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    admin_id = query.from_user.id

    if admin_id != ADMIN_ID:
        return

    action, user_id = data.split("_")
    user_id = int(user_id)
    receipt = pending_receipts.get(user_id)

    if not receipt:
        await query.edit_message_caption("⛔ رسید پیدا نشد.")
        return

    if action == "approve":
        await send_config(user_id, receipt["plan_id"], context)
        await context.bot.send_message(user_id, "🎉 رسیدت تایید شد و کانفیگ برات ارسال شد! مبارکه 🚀")
        await query.edit_message_caption("✅ رسید تایید شد و کانفیگ ارسال شد.")
        del pending_receipts[user_id]

    elif action == "reject":
        await context.bot.send_message(user_id, "❌ رسیدت رد شد. اگه فکر میکنی اشتباه شده با پشتیبانی تماس بگیر 📞")
        await query.edit_message_caption("❌ رسید رد شد.")

# ------------------ ارسال کانفیگ ------------------
async def send_config(user_id, plan_id, context):
    if config_repo.get(plan_id):
        config = config_repo[plan_id].pop(0)
        await context.bot.send_message(user_id, f"📡 کانفیگ شما:\n\n<code>{config}</code>", parse_mode="HTML")
    else:
        await context.bot.send_message(user_id, "⛔ کانفیگ موجود نیست! لطفا با ادمین تماس بگیر.")

# ------------------ ران ------------------
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(CallbackQueryHandler(approve_reject, pattern="^(approve|reject)_"))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
