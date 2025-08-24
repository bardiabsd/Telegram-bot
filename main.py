import os
import httpx
from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = FastAPI()

telegram_app = Application.builder().token(TOKEN).build()

# ------------------ هندلرها ------------------
async def start(update: Update, context):
    keyboard = [
        [KeyboardButton("📦 خرید اکانت"), KeyboardButton("👤 پروفایل من")],
        [KeyboardButton("🛠 پشتیبانی"), KeyboardButton("ℹ️ درباره ما")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "سلام ✌️ خوش اومدی به GoldenVPN 🚀\nاز منوی زیر انتخاب کن:",
        reply_markup=reply_markup
    )

telegram_app.add_handler(CommandHandler("start", start))


# ------------------ استارتاپ ------------------
@app.on_event("startup")
async def on_startup():
    # initialize تلگرام اپلیکیشن
    await telegram_app.initialize()

    # ست کردن وبهوک
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}/webhook"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        print("Webhook set response:", r.text)


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
