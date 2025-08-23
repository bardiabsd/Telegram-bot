import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# 📌 گرفتن توکن و URL از Environment Variables (Koyeb)
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")

# 📌 آیدی عددی شما (ادمین پیش‌فرض)
ADMIN_ID = 1743359080  

# 🎨 منو کاربر
user_menu = ReplyKeyboardMarkup(
    [
        ["🛍 فروشگاه", "💳 کیف پول"],
        ["🛠 پشتیبانی", "👤 پروفایل"]
    ],
    resize_keyboard=True
)

# 🎨 منو ادمین
admin_menu = ReplyKeyboardMarkup(
    [
        ["📋 لیست کاربران", "💰 مدیریت کیف پول", "📂 مدیریت کانفیگ"]
    ],
    resize_keyboard=True
)

# 🚀 دستور start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 سلام ادمین عزیز، به پنل مدیریت خوش اومدی!",
            reply_markup=admin_menu
        )
    else:
        await update.message.reply_text(
            "👋 سلام! به GoldenVPN خوش اومدی.\nلطفاً از منو یکی رو انتخاب کن:",
            reply_markup=user_menu
        )

# 📌 اجرای ربات روی Koyeb با webhook
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        url_path=BOT_TOKEN,
        webhook_url=f"{APP_URL}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()
