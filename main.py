import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")  # توکن ربات از محیط Koyeb

# منوی اصلی
main_menu = ReplyKeyboardMarkup(
    [
        ["📋 پنل مدیریت", "👜 کیف پول"],
        ["➕ ثبت تراکنش", "ℹ️ راهنما"]
    ],
    resize_keyboard=True
)

# استارت -> نمایش دکمه‌ها
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام 👋 به ربات خوش اومدی.\nاز منوی زیر انتخاب کن:",
        reply_markup=main_menu
    )

# هندلر پیام‌ها (دکمه‌ها)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📋 پنل مدیریت":
        await update.message.reply_text("🔐 اینجا بخش پنل مدیریت خواهد بود (در حال توسعه...)")

    elif text == "👜 کیف پول":
        await update.message.reply_text("💰 موجودی شما: 0 تومان (فعلاً تستی)")

    elif text == "➕ ثبت تراکنش":
        await update.message.reply_text("✍️ لطفاً مبلغ تراکنش رو بفرست (در حال توسعه...)")

    elif text == "ℹ️ راهنما":
        await update.message.reply_text("📖 راهنما: با دکمه‌ها می‌تونی از امکانات ربات استفاده کنی.")

    else:
        await update.message.reply_text("⚠️ گزینه نامعتبر. لطفاً از منوی پایین انتخاب کن.", reply_markup=main_menu)

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))  # فقط برای بار اول
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
