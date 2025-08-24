import os
from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# گرفتن توکن و وبهوک از Environment
TOKEN = os.getenv("BOT_TOKEN", "85505ca3-ac9d-43a9-bfc5-bed8e2f6a971")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-app.koyeb.app")

app = FastAPI()

# ساخت اپلیکیشن تلگرام
telegram_app = Application.builder().token(TOKEN).build()

# ------------------ هندلر /start ------------------
async def start(update: Update, context):
    keyboard = [
        [KeyboardButton("🛍 فروشگاه"), KeyboardButton("💳 کیف پول")],
        [KeyboardButton("🧾 کانفیگ‌های من"), KeyboardButton("🎫 تیکت‌های من")],
        [KeyboardButton("👤 پروفایل من"), KeyboardButton("📞 ارتباط با پشتیبانی")],
        [KeyboardButton("🛠 پنل ادمین")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "سلام ✌️ خوش اومدی به GoldenVPN 🚀\nاز منوی زیر انتخاب کن:",
        reply_markup=reply_markup
    )

telegram_app.add_handler(CommandHandler("start", start))


# ------------------ هندلر دکمه‌ها ------------------
async def menu_handler(update: Update, context):
    text = update.message.text

    responses = {
        "🛍 فروشگاه": "🛍 بخش فروشگاه 🚧",
        "💳 کیف پول": "💳 بخش کیف پول 🚧",
        "🧾 کانفیگ‌های من": "🧾 بخش کانفیگ‌های من 🚧",
        "🎫 تیکت‌های من": "🎫 بخش تیکت‌های من 🚧",
        "👤 پروفایل من": "👤 بخش پروفایل 🚧",
        "📞 ارتباط با پشتیبانی": "📞 ارتباط با پشتیبانی 🚧",
        "🛠 پنل ادمین": "🛠 پنل ادمین 🚧"
    }

    response = responses.get(text, "گزینه نامعتبر ❌")
    await update.message.reply_text(response)

telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))


# ------------------ وبهوک ------------------
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.get("/")
async def home():
    return {"status": "ok", "message": "Bot is running 🚀"}
