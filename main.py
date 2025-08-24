import os
import logging
from fastapi import FastAPI, Request
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ------------------ تنظیمات ------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "توکن_ربات_اینجا")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://live-avivah-bardiabsd-cd8d676a.koyeb.app/webhook")
ADMIN_ID = 1743359080  # فقط برای تو
logging.basicConfig(level=logging.INFO)
# ---------------------------------------------

app = FastAPI()
telegram_app = Application.builder().token(BOT_TOKEN).build()

# ------------------ هندلر استارت ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    keyboard = [
        [KeyboardButton("📦 خرید اکانت"), KeyboardButton("👤 پروفایل من")],
        [KeyboardButton("📞 ارتباط با پشتیبانی"), KeyboardButton("📑 تیکت‌های من")],
    ]

    # فقط ادمین ببیند
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton("⚙️ پنل ادمین")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "سلام ✌️ خوش اومدی به GoldenVPN 🚀\nاز منوی زیر انتخاب کن:",
        reply_markup=reply_markup
    )

# ------------------ هندلر خرید اکانت ------------------
async def buy_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plans = (
        "🔥 پلن‌ها:\n\n"
        "1️⃣ یک ماهه - 100,000 تومان\n"
        "2️⃣ سه ماهه - 250,000 تومان\n"
        "3️⃣ شش ماهه - 450,000 تومان\n"
        "4️⃣ یک ساله - 800,000 تومان\n\n"
        "لطفا یکی رو انتخاب کن یا روی «❌ انصراف» بزن."
    )

    keyboard = [
        [KeyboardButton("1️⃣ یک ماهه"), KeyboardButton("2️⃣ سه ماهه")],
        [KeyboardButton("3️⃣ شش ماهه"), KeyboardButton("4️⃣ یک ساله")],
        [KeyboardButton("❌ انصراف")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(plans, reply_markup=reply_markup)

# ------------------ هندلر انصراف ------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ------------------ ثبت هندلرها ------------------
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.Regex("^📦 خرید اکانت$"), buy_account))
telegram_app.add_handler(MessageHandler(filters.Regex("^❌ انصراف$"), cancel))

# ------------------ FastAPI ------------------
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def on_startup():
    # وبهوک ست شه
    await telegram_app.bot.set_webhook(url=WEBHOOK_URL)
    logging.info(f"✅ Webhook set to: {WEBHOOK_URL}")

@app.get("/")
async def home():
    return {"status": "ok", "message": "Bot is running 🚀"}
