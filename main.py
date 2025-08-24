import logging
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters
)

TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
WEBHOOK_URL = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app/webhook"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# منو اصلی
def main_menu():
    keyboard = [
        [KeyboardButton("🛍 فروشگاه"), KeyboardButton("💳 کیف پول")],
        [KeyboardButton("🧾 کانفیگ‌های من"), KeyboardButton("🎫 تیکت‌های من")],
        [KeyboardButton("👤 پروفایل من"), KeyboardButton("☎️ ارتباط با پشتیبانی")],
        [KeyboardButton("⚒️ پنل ادمین")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# هندلر استارت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام 👋\nبه GoldenVPN خوش اومدی 🌐", reply_markup=main_menu())

# 📦 فروشگاه → لیست پلن‌ها
async def store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("30 روزه | 30 گیگ | 40,000 تومان 💳", callback_data="plan_30d")],
        [InlineKeyboardButton("90 روزه | 100 گیگ | 100,000 تومان 💳", callback_data="plan_90d")],
        [InlineKeyboardButton("365 روزه | نامحدود | 300,000 تومان 💳", callback_data="plan_365d")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel_buy")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("🎁 لطفاً پلن مورد نظر را انتخاب کنید:", reply_markup=reply_markup)

# کال‌بک دکمه‌های پلن‌ها
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_buy":
        await query.edit_message_text("❌ خرید لغو شد. برگشتی به منوی اصلی.")
        await query.message.reply_text("منوی اصلی:", reply_markup=main_menu())
    elif query.data == "plan_30d":
        await query.edit_message_text("✅ پلن 30 روزه انتخاب شد.\n(فعلاً تستی ✅)")
    elif query.data == "plan_90d":
        await query.edit_message_text("✅ پلن 90 روزه انتخاب شد.\n(فعلاً تستی ✅)")
    elif query.data == "plan_365d":
        await query.edit_message_text("✅ پلن 365 روزه انتخاب شد.\n(فعلاً تستی ✅)")

# FastAPI برای وبهوک
app = FastAPI()
telegram_app = Application.builder().token(TOKEN).build()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    await telegram_app.bot.set_webhook(WEBHOOK_URL)

# هندلرها
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.Regex("🛍 فروشگاه"), store))
telegram_app.add_handler(CallbackQueryHandler(button_handler))
