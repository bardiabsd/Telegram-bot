import os
import threading
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# -------------------- تنظیمات پایه --------------------
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1743359080"))

users = set()  # ذخیره آیدی یوزرها (موقت - میشه بعدا دیتابیس وصل کرد)

# -------------------- دستورات ربات --------------------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🛒 خرید کانفیگ", "ℹ️ درباره ما"],
        ["📞 پشتیبانی"]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users.add(update.effective_user.id)
    await update.message.reply_text(
        "سلام 👋 به ربات فروش خوش اومدی\nاز منو یکی رو انتخاب کن:",
        reply_markup=MAIN_MENU
    )

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🛒 خرید کانفیگ":
        await update.message.reply_text("🔐 لیست پلن‌ها:\n\n1️⃣ ماهانه - 50k\n2️⃣ سه ماهه - 120k\n\nپرداخت → پیام به پشتیبانی")

    elif text == "ℹ️ درباره ما":
        await update.message.reply_text("ما بهترین کانفیگ‌های پرسرعت رو ارائه میدیم 🚀")

    elif text == "📞 پشتیبانی":
        await update.message.reply_text("برای پشتیبانی پیام بده: @YourSupportID")

    else:
        await update.message.reply_text("از منو یکی رو انتخاب کن 🙂")

# -------------------- بخش ادمین --------------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ دسترسی ندارید")

    keyboard = ReplyKeyboardMarkup(
        [["📢 ارسال همگانی", "👥 لیست کاربران"], ["⬅️ بازگشت"]],
        resize_keyboard=True
    )
    await update.message.reply_text("منوی ادمین 👑", reply_markup=keyboard)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    text = update.message.text
    if text == "📢 ارسال همگانی":
        await update.message.reply_text("پیام مورد نظر رو بفرست تا برای همه ارسال بشه ✉️")
        context.user_data["broadcast"] = True

    elif text == "👥 لیست کاربران":
        await update.message.reply_text(f"👥 تعداد کاربران: {len(users)}\n{list(users)}")

    elif text == "⬅️ بازگشت":
        await update.message.reply_text("بازگشت به منوی اصلی", reply_markup=MAIN_MENU)

async def catch_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("broadcast") and update.effective_user.id == ADMIN_ID:
        for uid in users:
            try:
                await context.bot.send_message(uid, update.message.text)
            except:
                pass
        context.user_data["broadcast"] = False
        await update.message.reply_text("✅ پیام برای همه ارسال شد")

# -------------------- اجرای بات --------------------
def run_bot():
    app_telegram = Application.builder().token(TOKEN).build()

    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("admin", admin))
    app_telegram.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, catch_broadcast))
    app_telegram.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel))
    app_telegram.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    app_telegram.run_polling()

# -------------------- Flask App برای Gunicorn --------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Telegram bot is running on Koyeb/Heroku!"

# -------------------- Run both --------------------
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000))) 
