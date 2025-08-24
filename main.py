# main.py
import os
import logging
from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# ----------------- تنظیمات عمومی -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# آدرس سرور Koyeb تو
BASE_URL = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"

# توکن از متغیر محیطی (حتماً در Koyeb به اسم BOT_TOKEN ست شود)
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Environment variable BOT_TOKEN not set!")

# FastAPI app
app = FastAPI()

# ساخت اپلیکیشن تلگرام (python-telegram-bot v20+)
telegram_app = Application.builder().token(TOKEN).build()

# ----------------- منو و هندلرها -----------------
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("فروشگاه 🛍"), KeyboardButton("کیف پول 💳")],
        [KeyboardButton("کانفیگ‌های من 🧾"), KeyboardButton("تیکت‌های من 🎫")],
        [KeyboardButton("پروفایل من 👤"), KeyboardButton("ارتباط با پشتیبانی 📞")],
        [KeyboardButton("پنل ادمین 🛠")],
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام ✌️ خوش اومدی به GoldenVPN 🚀\nاز منوی زیر انتخاب کن:",
        reply_markup=MAIN_KEYBOARD
    )

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text.startswith("فروشگاه"):
        await update.message.reply_text("🛍 بخش فروشگاه: به‌زودی لیست پلن‌ها رو می‌بینی.")
    elif text.startswith("کیف پول"):
        await update.message.reply_text("💳 موجودی کیف پولت: 0 تومان (نمونه).")
    elif text.startswith("کانفیگ‌های من"):
        await update.message.reply_text("🧾 هنوز کانفیگی ثبت نشده.")
    elif text.startswith("تیکت‌های من"):
        await update.message.reply_text("🎫 فهرست تیکت‌هات خالیه.")
    elif text.startswith("پروفایل من"):
        await update.message.reply_text("👤 نام: ناشناس\nشناسه: {}".format(update.effective_user.id))
    elif text.startswith("ارتباط با پشتیبانی"):
        await update.message.reply_text("📞 برای ارتباط، پیام بده: @YourSupportUsername (نمونه).")
    elif text.startswith("پنل ادمین"):
        await update.message.reply_text("🛠 ورود به پنل ادمین نیازمند دسترسیه.")
    else:
        await update.message.reply_text("از دکمه‌های منو استفاده کن 🙏", reply_markup=MAIN_KEYBOARD)

# ثبت هندلرها
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_router))

# ----------------- راه‌اندازی وبهوک خودکار -----------------
@app.on_event("startup")
async def on_startup():
    # initialize اجباری قبل از process_update
    await telegram_app.initialize()

    webhook_url = f"{BASE_URL}/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
    logger.info("✅ Webhook set to: %s", webhook_url)

@app.on_event("shutdown")
async def on_shutdown():
    await telegram_app.shutdown()
    logger.info("🛑 Telegram application shutdown.")

# ----------------- اندپوینت‌های وب -----------------
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.get("/")
async def home():
    return {"status": "ok", "message": "GoldenVPN Bot is running 🚀"}
