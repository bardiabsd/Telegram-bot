import os
import logging
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application

# 📌 گرفتن توکن و آیدی ادمین از Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # اینجا یه دیفالت گذاشتم که اگه ست نشده باشه ارور نده

WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # آدرس سرور (از Koyeb یا هرجایی که ست کردی)

# 📌 لاگ‌گیری
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📌 ساخت اپلیکیشن تلگرام
telegram_app = Application.builder().token(BOT_TOKEN).build()

# 📌 ساخت اپلیکیشن FastAPI
app = FastAPI()

# =========================
#   هندلرهای ربات
# =========================
async def start(update: Update, context):
    user_id = update.effective_user.id

    # ساخت منوی اصلی
    keyboard = [
        [InlineKeyboardButton("🛒 خرید کانفیگ", callback_data="buy_config")],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="my_profile")],
        [InlineKeyboardButton("🎟 تیکت‌های من", callback_data="my_tickets")],
        [InlineKeyboardButton("☎️ ارتباط با پشتیبانی", callback_data="support")]
    ]

    # اگه کاربر ادمین بود، دکمه پنل ادمین هم اضافه کن
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🛠 پنل ادمین", callback_data="admin_panel")])

    await update.message.reply_text(
        "به ربات GoldenVPN خوش آمدی 🌐",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# 📌 خرید کانفیگ
async def buy_config(update: Update, context):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("پلن 1️⃣ - ماهانه - 100,000 تومان", callback_data="plan_1")],
        [InlineKeyboardButton("پلن 2️⃣ - سه ماهه - 250,000 تومان", callback_data="plan_2")],
        [InlineKeyboardButton("پلن 3️⃣ - شش ماهه - 450,000 تومان", callback_data="plan_3")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel_buy")]
    ]

    await query.edit_message_text(
        text="🛒 لطفا یکی از پلن‌های زیر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# 📌 پروفایل کاربر
async def my_profile(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👤 اطلاعات پروفایل شما (در آینده تکمیل می‌شود).")

# 📌 تیکت‌های من
async def my_tickets(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎟 لیست تیکت‌های شما (در آینده نمایش داده می‌شود).")

# 📌 ارتباط با پشتیبانی
async def support(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("☎️ برای ارتباط با پشتیبانی پیام خود را ارسال کنید.")

# 📌 پنل ادمین
async def admin_panel(update: Update, context):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔️ شما دسترسی به پنل ادمین ندارید.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text("🛠 خوش آمدید به پنل ادمین.")

# 📌 کال‌بک‌ها
telegram_app.add_handler(
    telegram.ext.CommandHandler("start", start)
)
telegram_app.add_handler(
    telegram.ext.CallbackQueryHandler(buy_config, pattern="buy_config")
)
telegram_app.add_handler(
    telegram.ext.CallbackQueryHandler(my_profile, pattern="my_profile")
)
telegram_app.add_handler(
    telegram.ext.CallbackQueryHandler(my_tickets, pattern="my_tickets")
)
telegram_app.add_handler(
    telegram.ext.CallbackQueryHandler(support, pattern="support")
)
telegram_app.add_handler(
    telegram.ext.CallbackQueryHandler(admin_panel, pattern="admin_panel")
)

# =========================
#   FastAPI Webhook
# =========================
@app.on_event("startup")
async def on_startup():
    await telegram_app.initialize()  # 🔥 مشکل اصلی این بود
    await telegram_app.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"✅ Webhook set to: {WEBHOOK_URL}")

@app.on_event("shutdown")
async def on_shutdown():
    await telegram_app.shutdown()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True} 
