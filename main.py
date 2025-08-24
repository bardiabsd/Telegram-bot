import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler

# متغیرها از Koyeb (ENV)
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")  # مثلا: https://your-app.koyeb.app
ADMIN_ID = 1743359080  # آیدی عددی تو

# ساخت بات
bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

# هندلرها
dispatcher = Dispatcher(bot, None, workers=0, use_context=True)


# /start
def start(update, context):
    user_id = update.effective_user.id

    # دکمه‌ها برای همه کاربرا
    buttons = [
        [InlineKeyboardButton("🛒 خرید کانفیگ", callback_data="buy")],
        [InlineKeyboardButton("👤 پنل کاربر", callback_data="panel")],
        [InlineKeyboardButton("💬 پشتیبانی", callback_data="support")],
        [InlineKeyboardButton("ℹ️ درباره ما", callback_data="about")],
    ]

    # اگه ادمین باشه، دکمه مدیریت هم اضافه میشه
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("⚙️ مدیریت ادمین", callback_data="admin")])

    keyboard = InlineKeyboardMarkup(buttons)
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="👋 سلام! خوش اومدی به GoldenVPN.\nاز منوی زیر انتخاب کن:",
        reply_markup=keyboard
    )


# وقتی روی دکمه‌ها کلیک میشه
def button_handler(update, context):
    query = update.callback_query
    data = query.data

    if data == "buy":
        query.message.reply_text("🛒 بخش خرید کانفیگ بزودی فعال میشه.")
    elif data == "panel":
        query.message.reply_text("👤 اینجا پنل کاربریته.")
    elif data == "support":
        query.message.reply_text("💬 برای پشتیبانی به @YourSupport اکانت پیام بده.")
    elif data == "about":
        query.message.reply_text("ℹ️ ما بهترین کانفیگ‌ها رو ارائه میدیم 🚀")
    elif data == "admin":
        if query.from_user.id == ADMIN_ID:
            query.message.reply_text("⚙️ منوی مدیریت ادمین آماده‌ست.")
        else:
            query.message.reply_text("⛔ دسترسی نداری!")


# ثبت هندلرها
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CallbackQueryHandler(button_handler))


# وبهوک دریافت
@app.post(f"/webhook/{BOT_TOKEN}")
async def webhook(request: Request):
    data = await request.json()
    update = telegram.Update.de_json(data, bot)
    dispatcher.process_update(update)
    return JSONResponse({"ok": True})


# تست
@app.get("/")
async def home():
    return {"status": "GoldenVPN Bot Running 🚀"}


# ست وبهوک هنگام ران
import requests
if APP_URL and BOT_TOKEN:
    url = f"{APP_URL}/webhook/{BOT_TOKEN}"
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={url}")
