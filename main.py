import logging
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# -------------------- تنظیمات --------------------
TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
WEBHOOK_URL = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"  # دامنه اصلی سرور
ADMIN_ID = 1743359080  # آیدی عددی ادمین

# -------------------- راه‌اندازی --------------------
logging.basicConfig(level=logging.INFO)
telegram_app = Application.builder().token(TOKEN).build()
app = FastAPI()

# -------------------- منو اصلی --------------------
def main_menu(user_id: int):
    buttons = [
        [InlineKeyboardButton("🛒 خرید کانفیگ", callback_data="buy_config")],
        [InlineKeyboardButton("🎫 تیکت‌های من", callback_data="my_tickets")],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="my_profile"),
         InlineKeyboardButton("📞 ارتباط با پشتیبانی", callback_data="support")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ پنل ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("به ربات خوش اومدی 🚀", reply_markup=main_menu(user_id))

# -------------------- هندلر دکمه‌ها --------------------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "buy_config":
        plans = [
            [InlineKeyboardButton("💳 پلن 1 ماهه - 100,000 تومان", callback_data="plan_1m")],
            [InlineKeyboardButton("💳 پلن 3 ماهه - 250,000 تومان", callback_data="plan_3m")],
            [InlineKeyboardButton("💳 پلن 6 ماهه - 450,000 تومان", callback_data="plan_6m")],
            [InlineKeyboardButton("❌ انصراف", callback_data="cancel")]
        ]
        await query.edit_message_text(
            "📦 لطفا یکی از پلن‌های زیر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(plans)
        )

    elif query.data.startswith("plan_"):
        await query.edit_message_text(
            f"✅ شما {query.data.replace('plan_', '')} انتخاب کردید.\n"
            "به زودی درگاه پرداخت اضافه میشه 🔑"
        )

    elif query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")

    elif query.data == "my_tickets":
        await query.edit_message_text("🎫 لیست تیکت‌های شما (فعلا خالیه).")

    elif query.data == "my_profile":
        await query.edit_message_text("👤 اطلاعات پروفایل شما:\nنام: تست\nاشتراک: فعال")

    elif query.data == "support":
        await query.edit_message_text("📞 برای ارتباط با پشتیبانی اینجا کلیک کنید:\n@YourSupportUser")

    elif query.data == "admin_panel":
        if query.from_user.id == ADMIN_ID:
            await query.edit_message_text("⚙️ به پنل مدیریت خوش آمدید.")
        else:
            await query.edit_message_text("⛔️ شما دسترسی به پنل مدیریت ندارید.")

# -------------------- ثبت هندلرها --------------------
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CallbackQueryHandler(handle_buttons))

# -------------------- وبهوک --------------------
@app.on_event("startup")
async def on_startup():
    webhook_url = f"{WEBHOOK_URL}/webhook"   # 📌 اصلاح اصلی
    await telegram_app.bot.set_webhook(url=webhook_url)
    logging.info(f"✅ Webhook set to: {webhook_url}")

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}
